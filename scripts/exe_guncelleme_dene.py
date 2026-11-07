"""Paketli `Takvim.exe`'nin kendi kendini değiştirmesini GERÇEKTEN dener (yalnızca Windows).

Kullanım:
    python scripts/exe_guncelleme_dene.py [--exe dist/Takvim.exe]

Geçici bir klasörde iki exe kopyası kurar: "eski" (çalışan sürüm, kısayolun gösterdiği
yer) ve "yeni" (PE zaman damgası değiştirilmiş kopya: baytları farklı, hâlâ geçerli exe).
Sonra uygulamanın yaptığını yapar: eskiyi çalıştırır, yeniyi `--guncelle-tamamla` ile
başlatır, eskiyi kapatır ve şunları doğrular:

- eski yolun içeriği artık yeni exe'nin baytları,
- `Takvim.eski.exe` eski baytlarla duruyor (geri dönüş yolu),
- eski yoldan yeni bir süreç gerçekten açıldı.

Veri klasörü geçici (`LOCALAPPDATA` yönlendirilir): gerçek `%LOCALAPPDATA%\\Takvim`
kullanıcı kurulumuna DOKUNULMAZ ve çalışan gerçek Takvim'in süreçleri öldürülmez
(süreçler yola göre bulunur, ada göre değil). Pencere kısa süre görünebilir.
Çıkış kodu 0 = geçti, 1 = başarısız.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
BEKLEME_SN = 90


def farkli_kopya(kaynak: Path, hedef: Path) -> None:
    """exe'yi kopyalar ve PE `TimeDateStamp` alanını değiştirir (geçerli kalır, baytlar değişir)."""
    veri = bytearray(kaynak.read_bytes())
    pe = struct.unpack_from("<I", veri, 0x3C)[0]
    if veri[pe:pe + 4] != b"PE\0\0":
        raise ValueError("PE başlığı bulunamadı")
    zaman = struct.unpack_from("<I", veri, pe + 8)[0]
    struct.pack_into("<I", veri, pe + 8, (zaman + 1) & 0xFFFFFFFF)
    hedef.write_bytes(bytes(veri))


def _yolla_calisan(yol: Path) -> list[int]:
    """Çalıştırılabilir yolu BU dosya olan süreçlerin numaraları (ada göre değil)."""
    komut = (
        "Get-Process | Where-Object { $_.Path -eq '" + str(yol).replace("'", "''") + "' } "
        "| ForEach-Object { $_.Id }"
    )
    cikti = subprocess.run(
        ["powershell", "-NoProfile", "-Command", komut], capture_output=True, text=True, check=False
    ).stdout
    return [int(s) for s in cikti.split() if s.isdigit()]


def _yolu_oldur(yol: Path) -> None:
    for pid in _yolla_calisan(yol):
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)


def _bos_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _bekle(kosul, sure: float) -> bool:
    """Koşul sağlanana dek yoklar; değişim sırasında dosya anlık yok/kilitli olabilir (OSError = henüz değil)."""
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        try:
            if kosul():
                return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def calistir(exe: Path) -> list[str]:
    hatalar: list[str] = []

    def kontrol(kosul: bool, ad: str) -> None:
        print(("  ok   " if kosul else "  HATA ") + ad)
        if not kosul:
            hatalar.append(ad)

    with tempfile.TemporaryDirectory(prefix="takvim-guncelle-", ignore_cleanup_errors=True) as g:
        kok = Path(g)
        eski = kok / "kurulum" / "Takvim.exe"
        yeni = kok / "veri" / "Takvim" / "guncelleme" / "Takvim-99.0.0.exe"
        eski.parent.mkdir()
        yeni.parent.mkdir(parents=True)
        shutil.copyfile(exe, eski)
        farkli_kopya(exe, yeni)
        eski_bayt, yeni_bayt = eski.read_bytes(), yeni.read_bytes()
        kontrol(eski_bayt != yeni_bayt, "iki kopyanın baytları farklı (deneme anlamlı)")
        ortam = {**os.environ, "LOCALAPPDATA": str(kok / "veri")}
        port = _bos_port()
        db = kok / "veri" / "Takvim" / "takvim.db"

        # 1) Eski sürüm çalışıyor (arka plan kipi: pencere yok, dosyayı gerçekten kilitler).
        calisan = subprocess.Popen(
            [str(eski), "--no-browser", "--db", str(db), "--port", str(port)],
            env=ortam, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        def yanit_veriyor() -> bool:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ayarlar", timeout=3) as y:
                    return y.status == 200
            except OSError:
                return False

        try:
            kontrol(_bekle(yanit_veriyor, BEKLEME_SN), "eski exe çalışıyor")
            # Windows çalışan exe'nin ÜZERİNE YAZMAYI reddeder (yeniden adlandırmaya izin verir:
            # güncelleme akışı bu yüzden önce eskiyi kenara taşıyıp yenisini eski yola koyuyor).
            try:
                with open(eski, "r+b"):
                    pass
                kontrol(False, "çalışan exe üzerine yazmaya karşı kilitli")
            except PermissionError:
                kontrol(True, "çalışan exe üzerine yazmaya karşı kilitli")

            # 2) Yeni exe devri başlatır, 3) uygulama kapanır.
            subprocess.Popen(
                [str(yeni), "--guncelle-tamamla", "--eski", str(eski), "--pid", str(calisan.pid)],
                env=ortam, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(1.5)
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(calisan.pid)], capture_output=True, check=False)

            # 4) Değişim tamamlanıyor.
            kontrol(_bekle(lambda: eski.read_bytes() == yeni_bayt, 60), "eski yol artık yeni exe'nin baytlarında")
            yedek = eski.with_name("Takvim.eski.exe")
            kontrol(yedek.is_file() and yedek.read_bytes() == eski_bayt, "Takvim.eski.exe eski baytlarla duruyor")
            kontrol(_bekle(lambda: bool(_yolla_calisan(eski)), 60), "eski yoldan yeni süreç açıldı")
        finally:
            _yolu_oldur(eski)  # yalnızca BU geçici yolun süreçleri
            if calisan.poll() is None:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(calisan.pid)], capture_output=True, check=False)
    return hatalar


def main(argv: list[str] | None = None) -> int:
    if sys.platform != "win32":
        print("Yalnızca Windows.")
        return 0
    ayristirici = argparse.ArgumentParser(description="Takvim.exe kendini değiştirme denemesi")
    ayristirici.add_argument("--exe", type=Path, default=KOK / "dist" / "Takvim.exe")
    args = ayristirici.parse_args(argv)
    if not args.exe.is_file():
        print(f"exe bulunamadı: {args.exe}")
        return 1
    hatalar = calistir(args.exe)
    print("GEÇTİ" if not hatalar else f"BAŞARISIZ ({len(hatalar)}): " + "; ".join(hatalar))
    return 1 if hatalar else 0


if __name__ == "__main__":
    sys.exit(main())
