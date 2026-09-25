"""Masaüstü bildirimi — işletim sistemine dokunan tek yer.

Üç arka uç var ve sırayla denenir:

1. `WindowsToastNotifier` — PowerShell üzerinden WinRT toast. Ek bağımlılık yok.
2. `TkNotifier`   — stdlib tkinter ile küçük bir pencere. Toast çalışmayan
                    ortamlarda (eski Windows, kısıtlı oturum) devreye girer.
3. `ConsoleNotifier` — stdout. Testlerde ve başsız çalıştırmada.

Bilerek soyutladık: hatırlatıcı MANTIĞI `core/reminders.py` içinde saf duruyor,
burası yalnızca "göster" diyor. Böylece hangi bildirimin ne zaman çıkacağını
işletim sistemi olmadan test edebiliyoruz.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from typing import Protocol

__all__ = [
    "Notifier",
    "ConsoleNotifier",
    "TkNotifier",
    "WindowsToastNotifier",
    "pick_notifier",
]


class Notifier(Protocol):
    """Bildirim arka ucu sözleşmesi."""

    def available(self) -> bool:
        """Bu ortamda kullanılabilir mi."""
        ...

    def notify(self, title: str, body: str) -> bool:
        """Bildirimi gösterir; başarılıysa True."""
        ...


class ConsoleNotifier:
    """stdout'a yazar. Her yerde çalışır, son çare."""

    def available(self) -> bool:
        """Her zaman kullanılabilir."""
        return True

    def notify(self, title: str, body: str) -> bool:
        """Bildirimi konsola yazar."""
        print(f"\n[HATIRLATICI] {title}\n              {body}\n", flush=True)
        return True


def _ps_kacir(metin: str) -> str:
    """PowerShell tek tırnaklı dizesi + XML için kaçırma.

    Sıra önemli: önce XML varlıkları, sonra PowerShell tırnağı. Ters sırada
    yapılırsa `&` kaçırması `&amp;` üretir ve `&` yeniden kaçırılır.
    """
    metin = (
        metin.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return metin.replace("'", "''")


def _pencere_gizle() -> dict:
    """PowerShell'i GÖRÜNMEZ çalıştırmak için `subprocess` bayrakları.

    Uygulama penceresiz paketleniyor (`console=False`). O derlemede bir alt
    süreç başlatmak kendi konsol penceresini açar: her hatırlatıcıda ekranın
    ortasında bir anlığına siyah bir kare çakar. Kullanıcı bunu "bir şey ters
    gitti" diye okur. `CREATE_NO_WINDOW` bunu engelliyor.
    """
    if platform.system() != "Windows":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


class WindowsToastNotifier:
    """Windows toast bildirimi, PowerShell + WinRT ile.

    AUMID olarak PowerShell'in kendi kayıtlı kimliğini kullanıyoruz; kendi
    uygulamamızı Başlat menüsüne kaydetmek gerekmesin diye. Bunun bedeli
    bildirimin "Windows PowerShell" adıyla görünmesi -- kayıt işlemi sistem
    düzeyinde bir değişiklik olurdu ve onu kullanıcıya sormadan yapmıyoruz.
    """

    AUMID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

    def available(self) -> bool:
        """Windows ve powershell.exe var mı."""
        return platform.system() == "Windows" and shutil.which("powershell") is not None

    def notify(self, title: str, body: str) -> bool:
        """Toast gösterir; PowerShell hata verirse False."""
        script = f"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastText02"><text id="1">{_ps_kacir(title)}</text><text id="2">{_ps_kacir(body)}</text></binding></visual></toast>')
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{self.AUMID}').Show($toast)
"""
        try:
            sonuc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=20,
                **_pencere_gizle(),
            )
            return sonuc.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False


class TkNotifier:
    """stdlib tkinter ile küçük, üstte kalan bir bildirim penceresi.

    Toast'ın çalışmadığı ortamlar için. Pencere birkaç saniye sonra kendini
    kapatıyor; kullanıcı bir şeye tıklamak zorunda kalmasın.
    """

    def __init__(self, saniye: int = 12, dil: str = "tr") -> None:
        self.saniye = saniye
        # Tek düğmenin yazısı; başlık ("Takvim") ürün adı, çevrilmiyor.
        self.dil = dil

    def available(self) -> bool:
        """tkinter kurulu ve bir ekran var mı."""
        try:
            import tkinter  # noqa: F401
        except ImportError:
            return False
        return True

    def notify(self, title: str, body: str) -> bool:
        """Pencereyi gösterir; ekran yoksa False."""
        try:
            import tkinter as tk
        except ImportError:
            return False

        try:
            kok = tk.Tk()
        except Exception:
            return False  # ekran yok (başsız oturum)

        try:
            kok.title("Takvim")
            kok.attributes("-topmost", True)
            kok.resizable(False, False)
            kok.configure(bg="#171a21")

            cerceve = tk.Frame(kok, bg="#171a21", padx=18, pady=14)
            cerceve.pack()
            tk.Label(
                cerceve, text=title, bg="#171a21", fg="#e6e8ee",
                font=("Segoe UI", 12, "bold"), justify="left", anchor="w",
            ).pack(fill="x")
            tk.Label(
                cerceve, text=body, bg="#171a21", fg="#9aa1b1",
                font=("Segoe UI", 10), justify="left", anchor="w",
            ).pack(fill="x", pady=(4, 0))
            tk.Button(
                cerceve, text="OK" if self.dil == "en" else "Tamam", command=kok.destroy,
                bg="#1e222b", fg="#e6e8ee", relief="flat", padx=14,
            ).pack(pady=(12, 0))

            kok.update_idletasks()
            g, y = kok.winfo_width(), kok.winfo_height()
            kok.geometry(
                f"+{kok.winfo_screenwidth() - g - 40}+{kok.winfo_screenheight() - y - 90}"
            )
            kok.after(self.saniye * 1000, kok.destroy)
            kok.mainloop()
            return True
        except Exception:
            try:
                kok.destroy()
            except Exception:
                pass
            return False


def pick_notifier(tercih: str = "auto", dil: str = "tr") -> Notifier:
    """Ortama uygun bildirim arka ucunu seçer.

    `tercih`: "auto" | "toast" | "tk" | "console". `dil` yalnızca Tk
    düğmesini etkiliyor (toast gövdesi `daemon.bildirim_metni`'nden
    geliyor, konsol ise işletmene bakıyor).
    """
    arka_uclar = {
        "toast": WindowsToastNotifier,
        "tk": TkNotifier,
        "console": ConsoleNotifier,
    }
    if tercih != "auto":
        if tercih not in arka_uclar:
            raise ValueError(f"bilinmeyen bildirim arka ucu: {tercih!r}")
        if tercih == "tk":
            return TkNotifier(dil=dil)
        return arka_uclar[tercih]()

    for sinif in (WindowsToastNotifier, TkNotifier, ConsoleNotifier):
        aday = sinif()
        if aday.available():
            return aday
    return ConsoleNotifier()
