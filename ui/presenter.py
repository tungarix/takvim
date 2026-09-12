"""Hafta görünümünün veri hazırlığı.

HTTP bilmez, şablon bilmez, piksel bilmez: girdi `Repo` + bir tarih, çıktı düz
sözlük. Böylece hafta mantığı (gün sınırları, gece yarısını aşan etkinliklerin
kırpılması, kolon yerleşimi) sunucudan bağımsız test edilebiliyor.

Kolon yerleşimi `core.layout()`'tan geliyor; burada yeniden hesaplanmıyor.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta

from core import Occurrence, layout
from core.timeutil import UTC, get_tz

__all__ = ["week_start", "week_bounds", "day_bounds", "week_payload"]

_GUN_ADLARI = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
_AY_ADLARI = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]


def week_start(anchor: date) -> date:
    """Verilen tarihin içinde bulunduğu haftanın pazartesisi."""
    return anchor - timedelta(days=anchor.weekday())


def day_bounds(gun: date, tzid: str) -> tuple[datetime, datetime]:
    """Günün yerel [00:00, ertesi gün 00:00) sınırları.

    Bitişi `başlangıç + 24 saat` diye hesaplamıyoruz: DST geçiş gününde bir gün
    23 veya 25 saat sürer ve ızgara bir saat kayardı.
    """
    tz = get_tz(tzid)
    return (
        datetime.combine(gun, time(0, 0), tzinfo=tz),
        datetime.combine(gun + timedelta(days=1), time(0, 0), tzinfo=tz),
    )


def week_bounds(anchor: date, tzid: str) -> tuple[datetime, datetime]:
    """Haftanın yerel [pazartesi 00:00, ertesi pazartesi 00:00) sınırları."""
    pazartesi = week_start(anchor)
    baslangic, _ = day_bounds(pazartesi, tzid)
    _, bitis = day_bounds(pazartesi + timedelta(days=6), tzid)
    return baslangic, bitis


def _dakika(an: datetime, gun_baslangici: datetime) -> int:
    """Gün başlangıcından itibaren GERÇEKTEN geçen dakika.

    İkisini de UTC'ye çevirmek şart. CPython'da `a - b`, iki aware datetime'ın
    tzinfo'su AYNI NESNE ise ofsetleri uygulamadan naive farkı döndürüyor
    (`datetime.__sub__` içinde `if self._tzinfo is other._tzinfo` kısayolu).
    `get_tz` lru_cache'li olduğu için gün sınırlarının ikisi de aynı ZoneInfo
    nesnesini taşıyor; doğrudan çıkarsaydık DST günü 24 saat görünürdü ve
    ızgara o günlerde bir saat kayardı.
    """
    return int(
        (an.astimezone(UTC) - gun_baslangici.astimezone(UTC)).total_seconds() // 60
    )


def _occ_sozluk(occ: Occurrence, renkler: dict[int, str]) -> dict:
    """Occurrence'ın ekrana taşınacak alanları."""
    return {
        "uid": occ.uid,
        "eventId": occ.event_id,
        "title": occ.title,
        "calendarId": occ.calendar_id,
        "color": renkler.get(occ.calendar_id, "#6b7280"),
        "isOverride": occ.is_override,
        "allDay": occ.all_day,
        "location": occ.location,
        "description": occ.description,
        "tzid": occ.tzid,
        "startUtc": occ.start_utc.isoformat(),
        "endUtc": occ.end_utc.isoformat(),
    }


def week_payload(
    repo,
    anchor: date,
    tzid: str,
    *,
    calendar_ids: list[int] | None = None,
    include_hidden: bool = False,
) -> dict:
    """Bir haftanın tüm görüntüleme verisini hazırlar.

    Her gün için:
    - `allDay`: tüm gün etkinlikleri (ızgaraya değil üst şeride gider)
    - `timed`: saatli etkinlikler, GÜN SINIRINA KIRPILMIŞ hâlde

    Kırpma önemli: 23:00-01:00 etkinliği iki günde de görünmeli ve her günde
    yalnızca o güne düşen parçası çizilmeli. Kolonlar da kırpılmış parçalar
    üzerinden hesaplanır, yoksa gece yarısını aşan bir etkinlik ertesi günün
    sabahını boş yere daraltırdı.

    `dayMinutes` her gün için ayrı gönderiliyor: DST gününde 1380 veya 1500
    olabilir, ön yüz yüzdeleri buna göre hesaplıyor.
    """
    pazartesi = week_start(anchor)
    hafta_baslangic, hafta_bitis = week_bounds(anchor, tzid)

    takvimler = repo.list_calendars()
    renkler = {c.id: c.color for c in takvimler}

    occurrences = repo.occurrences(
        hafta_baslangic,
        hafta_bitis,
        calendar_ids=calendar_ids,
        include_hidden=include_hidden,
    )

    gunler = []
    for offset in range(7):
        gun = pazartesi + timedelta(days=offset)
        gun_baslangic, gun_bitis = day_bounds(gun, tzid)
        gun_dakika = _dakika(gun_bitis, gun_baslangic)

        tum_gun: list[dict] = []
        kirpilmis: list[Occurrence] = []
        # Kırpılmış parçadan orijinaline dönüş: layout() aynı nesneleri geri
        # verdiği için kimlik üzerinden eşliyoruz. uid ile eşlemek yanlış olurdu,
        # aynı serinin aynı güne düşen iki örneği olabilir.
        orijinali: dict[int, Occurrence] = {}

        for occ in occurrences:
            if not (occ.start_utc < gun_bitis and occ.end_utc > gun_baslangic):
                continue
            if occ.all_day:
                tum_gun.append(_occ_sozluk(occ, renkler))
                continue
            # Saatli etkinliği güne kırp; layout() kırpılmış hâl üzerinden çalışsın,
            # yoksa gece yarısını aşan bir etkinlik ertesi sabahı boşuna daraltır.
            parca = replace(
                occ,
                start_utc=max(occ.start_utc, gun_baslangic),
                end_utc=min(occ.end_utc, gun_bitis),
            )
            kirpilmis.append(parca)
            orijinali[id(parca)] = occ

        saatli = []
        for parca, kolon, kolon_sayisi in layout(kirpilmis):
            occ = orijinali[id(parca)]
            # Sözlük GERÇEK sınırları taşır (panel doğru saati göstersin);
            # yalnızca ızgara konumu kırpılmış parçadan gelir.
            veri = _occ_sozluk(occ, renkler)
            veri.update(
                {
                    "col": kolon,
                    "colCount": kolon_sayisi,
                    "startMin": _dakika(parca.start_utc, gun_baslangic),
                    "endMin": _dakika(parca.end_utc, gun_baslangic),
                    "clipped": occ.start_utc < gun_baslangic or occ.end_utc > gun_bitis,
                }
            )
            saatli.append(veri)

        gunler.append(
            {
                "date": gun.isoformat(),
                "dayName": _GUN_ADLARI[offset],
                "dayNumber": gun.day,
                "monthName": _AY_ADLARI[gun.month - 1],
                "dayMinutes": gun_dakika,
                "allDay": tum_gun,
                "timed": saatli,
            }
        )

    return {
        "tzid": tzid,
        "weekStart": pazartesi.isoformat(),
        "weekEnd": (pazartesi + timedelta(days=6)).isoformat(),
        "label": _hafta_etiketi(pazartesi),
        "calendars": [
            {"id": c.id, "name": c.name, "color": c.color, "visible": c.visible}
            for c in takvimler
        ],
        "days": gunler,
    }


def _hafta_etiketi(pazartesi: date) -> str:
    """'6 - 12 Mayıs 2024' / '29 Nisan - 5 Mayıs 2024' biçiminde başlık."""
    pazar = pazartesi + timedelta(days=6)
    if pazartesi.month == pazar.month:
        return f"{pazartesi.day} - {pazar.day} {_AY_ADLARI[pazar.month - 1]} {pazar.year}"
    if pazartesi.year == pazar.year:
        return (
            f"{pazartesi.day} {_AY_ADLARI[pazartesi.month - 1]} - "
            f"{pazar.day} {_AY_ADLARI[pazar.month - 1]} {pazar.year}"
        )
    return (
        f"{pazartesi.day} {_AY_ADLARI[pazartesi.month - 1]} {pazartesi.year} - "
        f"{pazar.day} {_AY_ADLARI[pazar.month - 1]} {pazar.year}"
    )
