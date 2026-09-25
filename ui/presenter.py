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

__all__ = [
    "week_start",
    "week_bounds",
    "day_bounds",
    "week_payload",
    "day_payload",
    "month_payload",
]

_GUN_ADLARI = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
_TAM_GUN_ADLARI = [
    "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar",
]
_AY_ADLARI = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]

# İngilizce karşılıklar: sunucu gün/ay ADINI seçiyor, istemci aynen basıyor.
# Biçim (`label` yapısı) iki dilde de aynı, yalnızca adlar değişiyor -- ön yüz
# tek bir şablonla çalışıyor, dil başına ayrı çizim kodu yok.
_GUN_ADLARI_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_TAM_GUN_ADLARI_EN = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]
_AY_ADLARI_EN = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _adlar(dil: str) -> tuple[list[str], list[str], list[str]]:
    """Dile göre (kısa gün, tam gün, ay) ad listeleri.

    Tanınmayan değer sessizce Türkçe'ye düşüyor: bozuk `ayarlar.json`
    yüzünden ızgaranın boş/anahtarsız kalması kabul edilemez.
    """
    if dil == "en":
        return _GUN_ADLARI_EN, _TAM_GUN_ADLARI_EN, _AY_ADLARI_EN
    return _GUN_ADLARI, _TAM_GUN_ADLARI, _AY_ADLARI


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


def _occ_sozluk(
    occ: Occurrence,
    renkler: dict[int, str],
    hatirlaticilar: dict[int, list] | None = None,
) -> dict:
    """Occurrence'ın ekrana taşınacak alanları.

    `reminderMinutes` seriye bağlı hatırlatıcıların dakika listesi; panel
    mevcut hatırlatıcıları göstermek için kullanıyor.
    """
    kayitli = (hatirlaticilar or {}).get(occ.event_id, [])
    return {
        "reminders": [
            {"id": r.id, "minutesBefore": r.minutes_before} for r in kayitli
        ],
        "uid": occ.uid,
        "eventId": occ.event_id,
        "title": occ.title,
        "calendarId": occ.calendar_id,
        "color": renkler.get(occ.calendar_id, "#6b7280"),
        "isOverride": occ.is_override,
        "recurring": occ.recurring,
        "allDay": occ.all_day,
        "location": occ.location,
        "description": occ.description,
        "tzid": occ.tzid,
        "startUtc": occ.start_utc.isoformat(),
        "endUtc": occ.end_utc.isoformat(),
        # Override anahtarı: taşınmış örnekte startUtc ile AYNI DEĞİL.
        "originalStartUtc": occ.series_slot_utc.isoformat(),
    }


def day_payload(
    repo,
    anchor: date,
    tzid: str,
    *,
    calendar_ids: list[int] | None = None,
    include_hidden: bool = False,
    dil: str = "tr",
) -> dict:
    """Tek günlük ızgara. Hafta ile aynı yapı, tek gün.

    Ön yüz aynı çizim koduyla ilgilenebilsin diye `days` yine liste.
    """
    return _izgara_payload(
        repo, anchor, 1, tzid,
        calendar_ids=calendar_ids, include_hidden=include_hidden,
        etiket=_gun_etiketi(anchor, dil), gorunum="day", dil=dil,
    )


def month_payload(
    repo,
    anchor: date,
    tzid: str,
    *,
    calendar_ids: list[int] | None = None,
    include_hidden: bool = False,
    dil: str = "tr",
) -> dict:
    """Ay görünümü: saat ızgarası yok, gün hücrelerinde etkinlik listesi.

    Izgara her zaman tam haftalardan oluşur (pazartesiden başlar), yani ayın
    başındaki ve sonundaki komşu ay günleri de gelir; `inMonth` alanı bunları
    ayırt ediyor. Sabit 6 satır YAPMIYORUZ: ay 5 haftaya sığıyorsa 5 satır
    gösterip boş bir hafta çizmiyoruz.
    """
    ilk = anchor.replace(day=1)
    izgara_baslangic = week_start(ilk)
    sonraki_ay = (ilk.replace(day=28) + timedelta(days=4)).replace(day=1)
    son = sonraki_ay - timedelta(days=1)
    izgara_bitis = week_start(son) + timedelta(days=6)
    gun_sayisi = (izgara_bitis - izgara_baslangic).days + 1

    baslangic, _ = day_bounds(izgara_baslangic, tzid)
    _, bitis = day_bounds(izgara_bitis, tzid)

    takvimler = repo.list_calendars()
    renkler = {c.id: c.color for c in takvimler}
    hatirlaticilar = repo.all_reminders()
    occurrences = repo.occurrences(
        baslangic, bitis, calendar_ids=calendar_ids, include_hidden=include_hidden
    )

    gunler = []
    for offset in range(gun_sayisi):
        gun = izgara_baslangic + timedelta(days=offset)
        gun_baslangic, gun_bitis = day_bounds(gun, tzid)
        icerik = [
            o for o in occurrences
            if o.start_utc < gun_bitis and o.end_utc > gun_baslangic
        ]
        # Tüm gün etkinlikleri üstte, sonra saate göre.
        icerik.sort(key=lambda o: (not o.all_day, o.start_utc))
        gunler.append(
            {
                "date": gun.isoformat(),
                "dayNumber": gun.day,
                "inMonth": gun.month == ilk.month,
                "events": [
                    dict(
                        _occ_sozluk(o, renkler, hatirlaticilar),
                        startMin=_dakika(max(o.start_utc, gun_baslangic), gun_baslangic),
                    )
                    for o in icerik
                ],
            }
        )

    return {
        "view": "month",
        "tzid": tzid,
        "anchor": ilk.isoformat(),
        "gridStart": izgara_baslangic.isoformat(),
        "gridEnd": izgara_bitis.isoformat(),
        "label": _ay_etiketi(ilk, dil),
        "dayNames": _adlar(dil)[0],
        "calendars": [
            {"id": c.id, "name": c.name, "color": c.color, "visible": c.visible}
            for c in takvimler
        ],
        "days": gunler,
    }


def week_payload(
    repo,
    anchor: date,
    tzid: str,
    *,
    calendar_ids: list[int] | None = None,
    include_hidden: bool = False,
    dil: str = "tr",
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
    return _izgara_payload(
        repo, pazartesi, 7, tzid,
        calendar_ids=calendar_ids, include_hidden=include_hidden,
        etiket=_hafta_etiketi(pazartesi, dil), gorunum="week", dil=dil,
    )


def _izgara_payload(
    repo,
    ilk_gun: date,
    gun_sayisi: int,
    tzid: str,
    *,
    calendar_ids: list[int] | None,
    include_hidden: bool,
    etiket: str,
    gorunum: str,
    dil: str = "tr",
) -> dict:
    """Gün ve hafta görünümlerinin ortak gövdesi.

    İkisi de aynı zaman ızgarası; fark yalnızca gün sayısı ve başlık.
    """
    baslangic, _ = day_bounds(ilk_gun, tzid)
    _, bitis = day_bounds(ilk_gun + timedelta(days=gun_sayisi - 1), tzid)

    takvimler = repo.list_calendars()
    renkler = {c.id: c.color for c in takvimler}
    hatirlaticilar = repo.all_reminders()

    occurrences = repo.occurrences(
        baslangic, bitis, calendar_ids=calendar_ids, include_hidden=include_hidden
    )

    gun_adlari, _, ay_adlari = _adlar(dil)
    gunler = []
    for offset in range(gun_sayisi):
        gun = ilk_gun + timedelta(days=offset)
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
                tum_gun.append(_occ_sozluk(occ, renkler, hatirlaticilar))
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
            veri = _occ_sozluk(occ, renkler, hatirlaticilar)
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
                "dayName": gun_adlari[gun.weekday()],
                "dayNumber": gun.day,
                "monthName": ay_adlari[gun.month - 1],
                "dayMinutes": gun_dakika,
                "allDay": tum_gun,
                "timed": saatli,
            }
        )

    son_gun = ilk_gun + timedelta(days=gun_sayisi - 1)
    return {
        "view": gorunum,
        "tzid": tzid,
        "weekStart": ilk_gun.isoformat(),
        "weekEnd": son_gun.isoformat(),
        "label": etiket,
        "calendars": [
            {"id": c.id, "name": c.name, "color": c.color, "visible": c.visible}
            for c in takvimler
        ],
        "days": gunler,
    }


def _gun_etiketi(gun: date, dil: str = "tr") -> str:
    """'13 Eylül 2026 Pazar' / 'Sunday 13 September 2026' biçiminde başlık."""
    _, tam_gunler, aylar = _adlar(dil)
    if dil == "en":
        return f"{tam_gunler[gun.weekday()]} {gun.day} {aylar[gun.month - 1]} {gun.year}"
    return f"{gun.day} {aylar[gun.month - 1]} {gun.year} {tam_gunler[gun.weekday()]}"


def _ay_etiketi(ilk: date, dil: str = "tr") -> str:
    """'Eylül 2026' / 'September 2026' biçiminde ay başlığı."""
    return f"{_adlar(dil)[2][ilk.month - 1]} {ilk.year}"


def _hafta_etiketi(pazartesi: date, dil: str = "tr") -> str:
    """'6 - 12 Mayıs 2024' / '29 Nisan - 5 Mayıs 2024' biçiminde başlık."""
    _, _, aylar = _adlar(dil)
    pazar = pazartesi + timedelta(days=6)
    if pazartesi.month == pazar.month:
        return f"{pazartesi.day} - {pazar.day} {aylar[pazar.month - 1]} {pazar.year}"
    if pazartesi.year == pazar.year:
        return (
            f"{pazartesi.day} {aylar[pazartesi.month - 1]} - "
            f"{pazar.day} {aylar[pazar.month - 1]} {pazar.year}"
        )
    return (
        f"{pazartesi.day} {aylar[pazartesi.month - 1]} {pazartesi.year} - "
        f"{pazar.day} {aylar[pazar.month - 1]} {pazar.year}"
    )
