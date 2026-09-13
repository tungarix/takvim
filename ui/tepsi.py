"""Sistem tepsisi simgesi (Windows `NotifyIcon`, pythonnet üzerinden).

Neden var: pencere kapanınca süreç bitiyor ve hatırlatıcı susuyor. Tepsi modu
açıksa kapatma PENCEREYİ GİZLİYOR, süreci yaşatıyor; simgeye tıklayınca pencere
geri geliyor. Varsayılan KAPALI (mevcut davranış korunuyor).

Tasarım kararları:

- Yeni bağımlılık YOK: `pythonnet` pywebview ile zaten geliyor. `pystray` +
  `Pillow` çekmek `.exe`'yi şişirirdi.
- Ek thread YOK: simge GUI thread'inde kuruluyor (`pencere_ac` içinden) ve
  mesaj döngüsünü `webview.start()` pompalıyor. Böylece `on_ac` içindeki
  `window.show()` thread atlama sorunu çıkarmıyor.
- Kurulum BAŞARISIZ olursa `kur()` None dönüyor ve uygulama tepsisiz
  çalışmaya devam ediyor: tepsi konfor, kapanışın çalışması şart.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

__all__ = ["Tepsi", "simge_bul"]

_BASLIK = "Takvim"


def simge_bul() -> str | None:
    """Tepsi simgesi dosyasını arar; yoksa None (stok ikon kullanılır).

    Paketlenmiş `.exe`de `takvim.ico` `datas` ile geliyor (`takvim.spec`);
    geliştirmede proje kökünde.
    """
    adaylar: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            adaylar.append(Path(meipass) / "takvim.ico")
        adaylar.append(Path(sys.executable).resolve().parent / "takvim.ico")
    adaylar.append(Path(__file__).resolve().parent.parent / "takvim.ico")
    for aday in adaylar:
        try:
            if aday.is_file():
                return str(aday)
        except OSError:
            continue
    return None


class Tepsi:
    """Canlı bir tepsi simgesi. Yalnızca `kur()` ile üretilir."""

    def __init__(self, simge, ac, kapa) -> None:
        self._simge = simge
        self._ac = ac
        self._kapa = kapa

    @classmethod
    def kur(
        cls,
        on_ac: Callable[[], None],
        on_kapat: Callable[[], None],
        *,
        simge_yolu: str | None = None,
        arka_uc: Any | None = None,
    ) -> Tepsi | None:
        """Simgeyi kurar; kurulamazsa None.

        `arka_uc` testler için: `NotifyIcon`, `Icon`, `SystemIcons`,
        `ToolStripMenuItem` ve `ContextMenuStrip` üreten sahte nesne.
        Üretimde None (gerçek WinForms).
        """
        try:
            if arka_uc is None:
                import clr  # pythonnet köprüsü; aşağıda AddReference ile kullanılıyor

                # Derlemelere açıkça referans ŞART: eklenmezse `System.*`
                # import'u `ModuleNotFoundError` veriyor ve `kur()` hep None
                # dönüyor (tepsi sessizce hiç çalışmıyor).
                clr.AddReference("System.Windows.Forms")
                clr.AddReference("System.Drawing")
                from System.Drawing import Icon, SystemIcons
                from System.Windows.Forms import (
                    ContextMenuStrip,
                    NotifyIcon,
                    ToolStripMenuItem,
                )

                class _Gercek:
                    pass

                arka_uc = _Gercek()
                arka_uc.NotifyIcon = NotifyIcon
                arka_uc.ContextMenuStrip = ContextMenuStrip
                arka_uc.ToolStripMenuItem = ToolStripMenuItem
                arka_uc.Icon = Icon
                arka_uc.SystemIcons = SystemIcons

            simge = arka_uc.NotifyIcon()
            simge.Text = _BASLIK
            if simge_yolu:
                simge.Icon = arka_uc.Icon(simge_yolu)
            else:
                simge.Icon = arka_uc.SystemIcons.Application
            menu = arka_uc.ContextMenuStrip()
            ac_o = arka_uc.ToolStripMenuItem("Takvim'i Aç")
            ac_o.Click += lambda *_: on_ac()
            kapat_o = arka_uc.ToolStripMenuItem("Kapat")
            kapat_o.Click += lambda *_: on_kapat()
            menu.Items.Add(ac_o)
            menu.Items.Add(kapat_o)
            simge.ContextMenuStrip = menu
            simge.DoubleClick += lambda *_: on_ac()
            simge.Visible = True
            try:
                simge.ShowBalloonTip(
                    3000, _BASLIK, "Takvim arka planda çalışıyor.", 1  # info
                )
            except Exception:
                pass  # baloncuk konfor; simge esas iş
            return cls(simge, on_ac, on_kapat)
        except Exception:
            return None

    def kapat(self) -> None:
        """Simgeyi kaldırır (gerçek çıkışta çağrılır)."""
        try:
            self._simge.Visible = False
            self._simge.Dispose()
        except Exception:
            pass
