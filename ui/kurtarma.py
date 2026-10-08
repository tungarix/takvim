"""Açılışta bozuk veritabanından kurtarma.

Neden var: bozuk bir `takvim.db` ile karşılaşan kullanıcıya eskiden yalnızca
ham hata metni ve yedek klasörünün yolu gösteriliyordu; kurtarmak için
dosyaları elle yeniden adlandırması gerekiyordu. Bozuk ama AÇILABİLEN bir
dosyada ise uygulama hiçbir şey demeden açılıyor ve o sabahın sağlam yedeğini
bozuk kopyayla eziyordu (paketli exe'de ölçüldü; yedek tarafı `store/yedek.py`
`yedek_al` içinde kapatıldı).

Akış: veritabanı açılmadan ÖNCE salt okunur denetlenir. Bozuksa en yeni sağlam
yedek bulunur ve kullanıcıya sorulur. Evet: bozuk dosya SİLİNMEDEN kenara
alınır, yerine yedek konur. Hayır ya da soru sorulamıyorsa (penceresiz arka
plan kopyası): hiçbir dosyaya dokunulmaz.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from store.yedek import (
    bozuk_veritabanini_degistir,
    son_saglam_yedek,
    veritabani_bozuklugu,
    yedek_klasoru,
)

# Evet/hayır sorusu: True/False, ya da soru gösterilemediyse None.
Soru = Callable[[str, str], "bool | None"]
Bilgi = Callable[[str, str], None]


class KurtarmaReddedildi(Exception):
    """Kullanıcı yedeğe dönmeyi reddetti; hiçbir dosya değişmedi."""


METIN = {
    "tr": {
        "baslik": "Takvim veritabanı bozuk",
        "soru": (
            "Takvim verilerinin durduğu dosya bozuk görünüyor:\n{sorun}\n\n"
            "En son sağlam yedek {tarih} tarihli. Bu yedeğe dönülsün mü?\n\n"
            "Bozuk dosya silinmez, aynı klasörde kenara alınır. {tarih} tarihinden "
            "sonra yapılan değişiklikler yedekte yok.\n\n"
            "Hayır dersen hiçbir dosyaya dokunulmaz ve Takvim kapanır."
        ),
        "tamam": "{tarih} tarihli yedeğe dönüldü.\n\nBozuk dosya şurada saklanıyor:\n{kenara}",
        "yedek_yok": (
            "Takvim veritabanı bozuk ({sorun}) ve dönülebilecek sağlam bir yedek "
            "bulunamadı. Hiçbir dosyaya dokunulmadı.\n"
            "Veritabanı: {db}\nYedek klasörü: {klasor}"
        ),
        "soramadi": (
            "Takvim veritabanı bozuk ({sorun}). Son sağlam yedeğe dönmek için "
            "Takvim'i masaüstü kısayolundan aç. Hiçbir dosyaya dokunulmadı.\n"
            "Yedek klasörü: {klasor}"
        ),
        "vazgecildi": "Yedeğe dönülmedi, hiçbir dosyaya dokunulmadı. Yedekler: {klasor}",
    },
    "en": {
        "baslik": "Takvim database is damaged",
        "soru": (
            "The file that holds your Takvim data looks damaged:\n{sorun}\n\n"
            "The latest healthy backup is from {tarih}. Go back to this backup?\n\n"
            "The damaged file is not deleted; it is set aside in the same folder. "
            "Changes made after {tarih} are not in the backup.\n\n"
            "If you say No, no file is touched and Takvim closes."
        ),
        "tamam": "Restored the backup from {tarih}.\n\nThe damaged file is kept here:\n{kenara}",
        "yedek_yok": (
            "The Takvim database is damaged ({sorun}) and no healthy backup was "
            "found. No file was touched.\n"
            "Database: {db}\nBackup folder: {klasor}"
        ),
        "soramadi": (
            "The Takvim database is damaged ({sorun}). To go back to the latest "
            "healthy backup, open Takvim from its desktop shortcut. No file was "
            "touched.\nBackup folder: {klasor}"
        ),
        "vazgecildi": "Did not restore a backup; no file was touched. Backups: {klasor}",
    },
}


def bozuksa_kurtar(
    db: str | Path,
    *,
    veri_dizini: str | Path,
    dil: str,
    sor: Soru | None,
    bildir: Bilgi | None,
    simdi: datetime,
) -> Path | None:
    """Veritabanı sağlamsa None; kurtarıldıysa kenara alınan bozuk dosyanın yolu.

    Kurtarılamıyorsa `RuntimeError` (mesajı kullanıcıya gösterilmeye hazır),
    kullanıcı reddettiyse `KurtarmaReddedildi`. İkisinde de hiçbir dosya
    değişmemiştir.
    """
    sorun = veritabani_bozuklugu(db)
    if sorun is None:
        return None
    m = METIN.get(dil, METIN["tr"])
    klasor = yedek_klasoru(veri_dizini)
    yedek = son_saglam_yedek(klasor)
    if yedek is None:
        raise RuntimeError(m["yedek_yok"].format(sorun=sorun, db=db, klasor=klasor))
    tarih = yedek.stem.removeprefix("takvim-")
    cevap = sor(m["baslik"], m["soru"].format(sorun=sorun, tarih=tarih)) if sor else None
    if cevap is None:
        raise RuntimeError(m["soramadi"].format(sorun=sorun, klasor=klasor))
    if not cevap:
        raise KurtarmaReddedildi(m["vazgecildi"].format(klasor=klasor))
    kenara = bozuk_veritabanini_degistir(db, yedek, simdi=simdi)
    if bildir is not None:
        bildir(m["baslik"], m["tamam"].format(tarih=tarih, kenara=kenara))
    return kenara


def tk_evet_hayir(baslik: str, mesaj: str) -> bool | None:
    """tkinter evet/hayır kutusu; ekran ya da tkinter yoksa None.

    tkinter paketli exe'de var (`takvim.spec` hiddenimports): `_olumcul_hata`
    da onu kullanıyor. Pencere henüz açılmadığı için WebView2'ye dayanamayız.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox

        kok = tk.Tk()
        kok.withdraw()
        try:
            return bool(messagebox.askyesno(baslik, mesaj, icon="warning"))
        finally:
            kok.destroy()
    except Exception:
        return None


def tk_bilgi(baslik: str, mesaj: str) -> None:
    """tkinter bilgi kutusu; gösterilemezse sessizce geçer (günlükte zaten yazıyor)."""
    try:
        import tkinter as tk
        from tkinter import messagebox

        kok = tk.Tk()
        kok.withdraw()
        try:
            messagebox.showinfo(baslik, mesaj)
        finally:
            kok.destroy()
    except Exception:
        pass
