"""Tek örnek — kısayola ikinci kez tıklayınca yeni pencere AÇILMAZ.

İki sebep var ve ikisi de gerçek:

1. Aynı veritabanına iki süreç yazıyor. SQLite buna dayanıyor ama yazma
   kilitleri çakışınca "database is locked" hatası kullanıcının karşısına
   çıkıyor; üstelik iki hatırlatıcı süreci aynı bildirimi kovalıyor.
2. Kullanıcı açısından uygulama TEKTİR. Kısayola yeniden tıklamak "uygulamayı
   göster" demektir, "ikinci bir takvim aç" değil — her masaüstü uygulaması
   böyle davranıyor.

Kilit, adlandırılmış bir Windows mutex'i: süreç nasıl ölürse ölsün (çökme,
görev yöneticisinden sonlandırma) işletim sistemi onu bırakıyor. Dosya
kilidinde artık kalan dosya sorunu yaşanıyor, burada yaşanmıyor.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

__all__ = [
    "kilit_adi",
    "kilit_al",
    "pencereyi_one_al",
    "pid_dosyasi",
    "pid_oku",
    "pid_yaz",
]

_ZATEN_VAR = 183  # ERROR_ALREADY_EXISTS


def kilit_adi(db_yolu: str) -> str:
    """Veritabanına özel kilit adı.

    Kilidi VERİTABANINA bağlıyoruz, uygulamaya değil: geliştirme sırasında
    `--db deneme.db` ile ikinci bir örnek açmak meşru. Aynı veriye iki süreç
    yazması ise değil. Yol özeti alınıyor çünkü mutex adında `\\` ayraç
    anlamına geliyor ve Türkçe karakterli yollar da sorun çıkarabiliyor.
    """
    ozet = hashlib.sha256(str(Path(db_yolu)).casefold().encode("utf-8")).hexdigest()[:16]
    return f"Local\\AktenakTakvim-{ozet}"


def kilit_al(ad: str):
    """Kilidi almayı dener. `(alindi, tutamak)` döndürür.

    Tutamak işletim sistemine ait; süreç bitene kadar açık kalıyor ve kilidi o
    tutuyor (ham bir sayı olduğu için Python'un çöp toplayıcısı ona dokunmaz).
    Geri döndürüyoruz ki gerekirse açıkça kapatılabilsin.

    Windows dışında kilit yok; orada her zaman "alındı" diyoruz (uygulama
    Windows'a yönelik, ama testler ve geliştirme başka yerde de koşabilmeli).
    """
    if sys.platform != "win32":
        return True, None
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        tutamak = kernel32.CreateMutexW(None, False, ad)
        if not tutamak:
            return True, None  # kilit kurulamadı; engellemek yerine devam et
        return kernel32.GetLastError() != _ZATEN_VAR, tutamak
    except (AttributeError, OSError):
        # Kilit bir KOLAYLIK. Kurulamıyorsa uygulamayı açmamak yanlış olur.
        return True, None


def pid_dosyasi(veri_dizini: str | Path) -> Path:
    """Çalışan örneğin süreç numarasını tuttuğumuz dosya."""
    return Path(veri_dizini) / "ornek.pid"


def pid_yaz(veri_dizini: str | Path) -> bool:
    """Kendi süreç numaramızı yazar; yazabildiyse True.

    Neden gerekli: ikinci örnek, var olan pencereyi BAŞLIĞINDAN buluyordu ve
    başlık "Takvim". Uygulamanın kendi veri klasörünün adı da "Takvim" —
    kullanıcı o klasörü Explorer'da açtıysa Explorer penceresinin başlığı da
    tam olarak "Takvim" oluyor ve ikinci tık Takvim'i değil Explorer'ı öne
    alıyordu. Süreç numarası bu karışıklığı tamamen ortadan kaldırıyor.
    """
    try:
        yol = pid_dosyasi(veri_dizini)
        yol.parent.mkdir(parents=True, exist_ok=True)
        yol.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except OSError:
        return False


def pid_oku(veri_dizini: str | Path) -> int | None:
    """Kayıtlı süreç numarasını okur; yoksa ya da bozuksa None."""
    try:
        return int(pid_dosyasi(veri_dizini).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _win32_pencereler() -> list[tuple[int, str, int]]:
    """Görünür üst düzey pencereleri `(tutamak, başlık, süreç)` olarak listeler."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    sonuc: list[tuple[int, str, int]] = []

    GERI = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def topla(tutamak, _lparam):
        if user32.IsWindowVisible(tutamak):
            tampon = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(tutamak, tampon, 512)
            if tampon.value:
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(tutamak, ctypes.byref(pid))
                sonuc.append((int(tutamak), tampon.value, int(pid.value)))
        return True

    user32.EnumWindows(GERI(topla), 0)
    return sonuc


def pencereyi_one_al(baslik: str, pid: int | None = None, listele=None) -> bool:
    """Takvim penceresini geri yükleyip öne getirir; bulduysa True.

    `pid` verilirse YALNIZCA o sürece ait pencere kabul edilir; aynı başlıklı
    başka bir pencere (bkz. `pid_yaz`) yanlışlıkla öne alınmaz.

    `listele` testler için: gerçek Win32 taraması yerine sahte bir liste
    verilebiliyor.

    `FindWindowW` yerine tüm pencereleri tarıyoruz: WebView2 penceresi
    `FindWindowW` ile güvenilir biçimde bulunamıyor (elle denendi, `EnumWindows`
    buluyor o bulmuyor).
    """
    try:
        pencereler = _win32_pencereler() if listele is None else listele()
    except (AttributeError, OSError, ImportError):
        return False

    for tutamak, ad, sahip in pencereler:
        if pid is not None and sahip != pid:
            continue
        if ad != baslik:
            continue
        if listele is not None:  # testte Win32'ye dokunma
            return True
        return _one_getir(tutamak)
    return False


def _one_getir(tutamak: int) -> bool:
    """Pencereyi simge durumundan çıkarıp odağı ona verir."""
    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        user32.ShowWindow(tutamak, 9)  # SW_RESTORE
        if user32.SetForegroundWindow(tutamak):
            return True
        # SetForegroundWindow, çağıran süreç ön planda değilse sessizce
        # başarısız olur (Windows'un odak çalma koruması). SwitchToThisWindow
        # belgelenmemiş ama tam bu durumda çalışıyor.
        user32.SwitchToThisWindow(tutamak, True)
        return True
    except (AttributeError, OSError):
        return False
