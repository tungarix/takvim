"""Yeni exe'yi doğrulayıp eskisinin yerine koyar (Windows, tek dosyalı exe).

Windows çalışan exe'yi üzerine yazdırmaz. Akış (docs/otomatik-guncelleme-plani.md §2):

1. `hazirla`: yeni exe `guncelleme/` klasörüne iner, SHA-256'sı AYNI release'in
   `SHA256SUMS.txt`'iyle eşleşmezse dosya silinir ve kurulum iptal olur.
2. Uygulama yeni exe'yi `--guncelle-tamamla` ile başlatıp kendini kapatır.
3. `tamamla` (yeni exe içinde): eski sürecin bitmesini bekler, eskiyi
   `<ad>.eski.exe`ye taşır, yenisini eski yola kopyalar, sağlamasını yapar ve
   normal modda yeniden başlatır. Herhangi bir adım patlarsa eski dosya geri
   konur ve ESKİ sürüm açılır.

Tek dosyalı exe'de iki süreç var (önyükleyici + asıl süreç); biri bitse de diğeri
dosyayı kilitli tutabilir. Bu yüzden süreç numarasını beklemek yetmez: taşıma,
süre sınırına kadar `PermissionError`da yeniden denenir.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from .ag import Ag, GuncellemeHatasi
from .saf import EXE_ADI, Yayin, ozet_coz

__all__ = [
    "eski_artiklari_temizle",
    "hazirla",
    "kurulabilir_mi",
    "sha256_dosya",
    "tamamla",
    "tamamlamayi_baslat",
]

ESKI_EK = ".eski.exe"


def sha256_dosya(yol: Path) -> str:
    ozet = hashlib.sha256()
    with open(yol, "rb") as f:
        for parca in iter(lambda: f.read(1024 * 1024), b""):
            ozet.update(parca)
    return ozet.hexdigest()


def hazirla(ag: Ag, yayin: Yayin, klasor: Path) -> Path:
    """Yeni exe'yi indirir ve DOĞRULAR; doğrulanmış dosyanın yolunu verir.

    `SHA256SUMS.txt` bulunamaz/belirsizse ya da özet tutmazsa dosya silinir.
    Aynı klasördeki eski indirmeler (yarım ya da önceki sürüm) önce temizlenir.
    """
    klasor.mkdir(parents=True, exist_ok=True)
    for eski in klasor.glob("Takvim-*.exe*"):
        try:
            eski.unlink()
        except OSError:
            pass
    beklenen = ozet_coz(ag.metin_indir(yayin.ozet_url), EXE_ADI)
    if beklenen is None:
        raise GuncellemeHatasi("ozet_bulunamadi", "SHA256SUMS.txt'te Takvim.exe satırı yok/belirsiz")
    hedef = klasor / f"Takvim-{yayin.surum}.exe"
    gelen = ag.indir(yayin.exe_url, hedef, yayin.exe_boyut)
    if gelen != beklenen:
        try:
            hedef.unlink()
        except OSError:
            pass
        raise GuncellemeHatasi("ozet_uyusmuyor", f"{gelen} != {beklenen}")
    return hedef


def kurulabilir_mi(exe: Path | None = None) -> bool:
    """Paketli exe mi ve klasörü yazılabilir mi (Program Files vb. değil)."""
    if exe is None:
        if not getattr(sys, "frozen", False):
            return False
        exe = Path(sys.executable)
    try:
        if not exe.is_file():
            return False
        klasor = exe.parent
        deneme = klasor / f".takvim-yazma-{os.getpid()}"
        deneme.write_bytes(b"")
        deneme.unlink()
        return True
    except OSError:
        return False


def _bayraklar() -> int:
    if sys.platform != "win32":
        return 0
    return (
        subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    )


def _baslat(komut: list[str]) -> None:
    # Önyükleyicinin kendi geçici klasörünü yeni süreç yeniden kullanmasın.
    ortam = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    subprocess.Popen(
        komut, creationflags=_bayraklar(), env=ortam, close_fds=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def tamamlamayi_baslat(yeni_exe: Path, eski_exe: Path, pid: int | None = None) -> None:
    """Doğrulanmış yeni exe'yi `--guncelle-tamamla` ile başlatır (çağıran sonra kapanır)."""
    _baslat([
        str(yeni_exe), "--guncelle-tamamla",
        "--eski", str(eski_exe), "--pid", str(pid if pid is not None else os.getpid()),
    ])


def _pid_bekle(pid: int, sure: float) -> None:
    """Süreç bitene (ya da süre dolana) kadar bekler; bulunamayan süreç = bitmiş."""
    if sys.platform != "win32" or pid <= 0:
        return
    import ctypes

    SYNCHRONIZE = 0x00100000
    kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
    tutamak = kernel.OpenProcess(SYNCHRONIZE, False, pid)
    if not tutamak:
        return
    try:
        kernel.WaitForSingleObject(tutamak, int(sure * 1000))
    finally:
        kernel.CloseHandle(tutamak)


def tamamla(
    yeni_exe: Path,
    eski_exe: Path,
    pid: int = 0,
    *,
    sure: float = 30.0,
    uyku: float = 0.25,
    pid_bekle: Callable[[int, float], None] = _pid_bekle,
    baslat: Callable[[list[str]], None] = _baslat,
) -> bool:
    """Eski exe'yi yenisiyle değiştirir ve açar; başarılıysa True.

    Başarısızlıkta eski dosya geri konur ve ESKİ sürüm açılır (False). Kurulum
    hiç başlamadıysa (kilit süre içinde açılmadı) eski dosyaya hiç dokunulmaz.
    """
    yedek = eski_exe.with_name(eski_exe.stem + ESKI_EK)
    gecici = eski_exe.with_name(eski_exe.name + ".yeni")
    bitis = time.monotonic() + sure
    try:
        pid_bekle(pid, sure)
        yedeklendi = False
        while True:
            try:
                if eski_exe.exists():
                    os.replace(eski_exe, yedek)
                    yedeklendi = True
                break
            except PermissionError:
                if time.monotonic() >= bitis:
                    raise
                time.sleep(uyku)
        try:
            beklenen = sha256_dosya(yeni_exe)
            shutil.copyfile(yeni_exe, gecici)
            if sha256_dosya(gecici) != beklenen:
                raise OSError("kopya sağlaması tutmadı")
            os.replace(gecici, eski_exe)
        except BaseException:
            _geri_al(eski_exe, yedek, gecici, yedeklendi)
            raise
        baslat([str(eski_exe)])
        return True
    except Exception as hata:  # her hatada eski sürüm açılmalı
        print(f"Güncelleme tamamlanamadı, eski sürüm açılıyor: {type(hata).__name__}: {hata}", flush=True)
        try:
            if eski_exe.exists():
                baslat([str(eski_exe)])
        except OSError as acma_hatasi:
            print(f"Eski sürüm açılamadı: {acma_hatasi}", flush=True)
        return False


def _geri_al(eski_exe: Path, yedek: Path, gecici: Path, yedeklendi: bool) -> None:
    for yol in (gecici,):
        try:
            yol.unlink()
        except OSError:
            pass
    if not yedeklendi:
        return
    try:
        if eski_exe.exists():
            eski_exe.unlink()
    except OSError:
        pass
    os.replace(yedek, eski_exe)


def eski_artiklari_temizle(eski_exe: Path, klasor: Path) -> None:
    """Başarılı güncellemeden sonra `<ad>.eski.exe` ve indirme klasörünü siler.

    Hata yutulur: kilitli bir artık uygulamayı açmamak için sebep değil, bir
    sonraki açılışta yeniden denenir.
    """
    try:
        eski_exe.with_name(eski_exe.stem + ESKI_EK).unlink()
    except OSError:
        pass
    shutil.rmtree(klasor, ignore_errors=True)
