"""Otomatik başlatma kaydı (Başlangıç klasörü kısayolu).

README §9'daki el komutunun makineleşmiş hâli: aynı `.lnk`, aynı hedef, ama
kurma/kaldırma Ayarlar kutusundaki bir anahtarla oluyor. Kural değişmedi:
KURULUM KENDİLİĞİNDEN OLMAZ (AGENTS 24); burası yalnızca kullanıcının
isteğini yerine getiriyor.

Hedef iki kipte farklı:
- Paketlenmiş `.exe`: `Takvim.exe --no-browser --reminder` — penceresiz,
  yalnızca sunucu + hatırlatıcı; `--no-browser` ana thread'de `serve()` ile
  bloklanıyor, yani görünmez bir arka plan süreci olarak yaşıyor.
- Geliştirme: `pythonw.exe -m remind --db ...` (README §9 ile aynı).

Kısayol WScript.Shell COM ile kuruluyor (ek bağımlılık yok, Windows'un
kendisi). PowerShell üzerinden çağrılıyor çünkü `.exe` penceresiz derleniyor
ve COM'u doğrudan kullanmak için `pywin32` gerekirdi.

`klasor` parametresi testler için: verilmezse gerçek Başlangıç klasörü.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

__all__ = [
    "KISAYOL_ADI",
    "baslangic_klasoru",
    "hedef_hesapla",
    "kaldir",
    "kisayol_yolu",
    "kur",
    "kurulu_mu",
]

KISAYOL_ADI = "Takvim Hatırlatıcı.lnk"


def baslangic_klasoru() -> Path:
    """Kullanıcının Başlangıç (Startup) klasörü."""
    appdata = os.environ.get("APPDATA") or str(Path.home())
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def kisayol_yolu(klasor: str | Path | None = None) -> Path:
    """Kısayolun tam yolu."""
    kok = baslangic_klasoru() if klasor is None else Path(klasor)
    return kok / KISAYOL_ADI


def kurulu_mu(klasor: str | Path | None = None) -> bool:
    """Kayıt var mı (dosya orada mı)."""
    try:
        return kisayol_yolu(klasor).exists()
    except OSError:
        return False


def hedef_hesapla(db_yolu: str | None = None) -> tuple[str, str, str]:
    """(hedef, argümanlar, çalışma_dizini) — kuruluma da teste de aynı fonksiyon.

    Dönen yollar MUTLAK: Başlangıç klasöründen çalışan kısayolun çalışma
    dizini kestirilemez, görece yol bırakılmıyor. Paketlenmiş `.exe` kendi
    varsayılan DB'sini bildiği için bayrak gerekmiyor; geliştirme kipinde
    `--db` ŞART (yoksa hatırlatıcı Başlangıç klasöründeki yanlış dosyayı izler).
    """
    if getattr(sys, "frozen", False):
        exe = str(Path(sys.executable).resolve())
        return exe, "--no-browser --reminder", str(Path(exe).resolve().parent)
    # Geliştirme kökü dosyanın kendi konumundan türetiliyor (çağrı dizininden
    # bağımsız olsun diye); hedef Windows'un konsolsuz Python'u.
    kok = str(Path(__file__).resolve().parent.parent)
    pythonw = str(Path(sys.executable).parent / "pythonw.exe")
    db = str(Path(db_yolu).resolve()) if db_yolu else str(Path(kok) / "takvim.db")
    return pythonw, f'-m remind --db "{db}"', kok


def _kurKomutu(hedef: str, argumanlar: str, dizin: str, lnk: str) -> str:
    """PowerShell komut metni (ayrı fonksiyon ki test edilebilsin)."""
    # Çift tırnaklar PowerShell'e göre kaçıyor; tek tırnaklı alanlar dosya yolu.
    return (
        "$w = New-Object -ComObject WScript.Shell; "
        f"$k = $w.CreateShortcut('{lnk}'); "
        f"$k.TargetPath = '{hedef}'; "
        f"$k.Arguments = '{argumanlar}'; "
        f"$k.WorkingDirectory = '{dizin}'; "
        "$k.Save()"
    )


def kur(klasor: str | Path | None = None, db_yolu: str | None = None) -> bool:
    """Kaydı kurar; başardıysa True.

    Başarısızlık SESSİZ (False): Başlangıç klasörü yazılabilir olmayabilir
    (kurum ilkesi) ve bu, ayarı kaydetmeye engel değil — bir dahaki açılışta
    arayüz "kayıt yok" gösterip yeniden deneyebilir.
    """
    try:
        lnk = kisayol_yolu(klasor)
        lnk.parent.mkdir(parents=True, exist_ok=True)
        hedef, argumanlar, dizin = hedef_hesapla(db_yolu)
        komut = _kurKomutu(hedef, argumanlar, dizin, str(lnk))
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", komut],
            capture_output=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return lnk.exists()
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def kaldir(klasor: str | Path | None = None) -> bool:
    """Kaydı kaldırır; yoksa da True (istenen durum zaten o)."""
    try:
        lnk = kisayol_yolu(klasor)
        if lnk.exists():
            lnk.unlink()
        return True
    except OSError:
        return False
