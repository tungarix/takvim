"""Otomatik yerel yedek.

Neden var: bütün veri `%LOCALAPPDATA%/Takvim/takvim.db` içinde TEK kopya
hâlinde duruyor. Kullanıcıya "yedeklemek için Dışa aktar'a bas" demek yeterli
değil, çünkü üretilen `.ics` bir yedek DEĞİL: hatırlatıcıları ve hangi
etkinliğin hangi takvime ait olduğunu taşımıyor. Dosyanın kendisinin kopyası
gerekiyor.

`sqlite3.Connection.backup()` kullanılıyor, dosyayı elle kopyalamak DEĞİL:
bağlantı açıkken düz kopyalama yarım yazılmış bir sayfayı yakalayabilir,
backup API'si ise tutarlı bir anlık görüntü veriyor ve bunu kilitlemeden
yapıyor.

Buradaki her şey SESSİZCE BAŞARISIZ OLUR. Yedek alamamak uygulamayı
açmamak için sebep değil; en kötü ihtimalle kullanıcı yedeksiz kalır ve bunu
günlükte görür.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

__all__ = ["SAKLANAN", "yedek_al", "yedek_dosyalari", "yedek_klasoru"]

# Kaç günlük yedek saklanacak. Yedi gün, "geçen hafta yanlışlıkla sildim"
# senaryosunu kurtarmaya yetiyor; daha fazlası disk ve karmaşa.
SAKLANAN = 7


def yedek_klasoru(veri_dizini: str | Path) -> Path:
    """Yedeklerin durduğu klasör (veritabanının yanında)."""
    return Path(veri_dizini) / "yedek"


def yedek_dosyalari(klasor: str | Path) -> list[Path]:
    """Var olan yedekler, ESKİDEN YENİYE sıralı.

    Ad biçimi `takvim-YYYY-AA-GG.db` olduğu için alfabetik sıralama kronolojik
    sıralamayla aynı; dosya zaman damgasına güvenmiyoruz (kopyalama,
    senkronizasyon ve yedekten dönme damgayı bozar).
    """
    try:
        return sorted(Path(klasor).glob("takvim-*.db"))
    except OSError:
        return []


def yedek_al(baglanti: sqlite3.Connection, veri_dizini: str | Path, *, bugun: date) -> Path | None:
    """Veritabanının kopyasını alır; aldıysa dosya yolunu döndürür.

    Günde TEK dosya: aynı gün içinde uygulama beş kez açılırsa beş yedek değil,
    güncellenen tek bir yedek olur. Yoksa yedi kopyalık pencere, uygulamayı sık
    açan bir günde tek güne sıkışır ve "geçen hafta" kurtarılamaz hâle gelir.

    `bugun` dışarıdan veriliyor: testler tarihi ilerletebilsin diye.
    """
    try:
        klasor = yedek_klasoru(veri_dizini)
        klasor.mkdir(parents=True, exist_ok=True)
        hedef = klasor / f"takvim-{bugun.isoformat()}.db"

        # Geçici ada yazıp sonra taşıyoruz: yedek alırken uygulama kapanırsa
        # geriye YARIM bir "yedek" kalmasın. Yarım yedek, yedeksiz olmaktan
        # kötüdür -- insan ona güvenir.
        gecici = hedef.with_name(hedef.name + ".gecici")
        kopya = sqlite3.connect(gecici)
        try:
            baglanti.backup(kopya)
        finally:
            # `with sqlite3.connect(...)` KAPATMAZ, yalnızca transaction'ı
            # yönetir. Dosya açık kalırsa Windows taşımaya izin vermiyor ve
            # yedek sessizce alınamıyordu.
            kopya.close()
        gecici.replace(hedef)

        _budama(klasor)
        return hedef
    except (sqlite3.Error, OSError):
        return None


def _budama(klasor: Path) -> list[Path]:
    """En eski yedekleri siler, `SAKLANAN` tanesini bırakır; silinenleri döndürür."""
    dosyalar = yedek_dosyalari(klasor)
    silinecek = dosyalar[: max(0, len(dosyalar) - SAKLANAN)]
    silinen = []
    for d in silinecek:
        try:
            d.unlink()
            silinen.append(d)
        except OSError:
            pass  # kilitli ya da izin yok; bir dahaki açılışta yine denenir
    return silinen
