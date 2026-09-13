"""Faz 0 kabul kriterleri: tekrar genişletme.

Her test, blueprint'teki kabul listesinden bir maddeye karşılık gelir.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from core import Override, expand, series_end, to_local
from tests.helpers import IST, NY, ist, local_stamps, make_event, ny, utc_stamps

# ---------------------------------------------------------------------------
# 1. Her ayın son iş günü
# ---------------------------------------------------------------------------

def test_son_is_gunu_aylik():
    """BYDAY=MO..FR;BYSETPOS=-1 her ayın son iş gününü vermeli.

    Mart ve Haziran 2024'ün 31'i/30'u hafta sonuna denk geliyor; kural o
    aylarda bir önceki cumaya kaymalı.
    """
    event = make_event(
        ist(2024, 1, 31, 9, 0),
        ist(2024, 1, 31, 10, 0),
        rrule="FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
    )
    got = expand(event, [], ist(2024, 1, 1), ist(2024, 7, 1))

    assert local_stamps(got) == [
        "2024-01-31 09:00",  # Çarşamba
        "2024-02-29 09:00",  # Perşembe
        "2024-03-29 09:00",  # 31'i Pazar -> Cuma'ya kaydı
        "2024-04-30 09:00",  # Salı
        "2024-05-31 09:00",  # Cuma
        "2024-06-28 09:00",  # 30'u Pazar -> Cuma'ya kaydı
    ]


# ---------------------------------------------------------------------------
# 2. 31 Ocak başlangıçlı aylık tekrar -- Şubat davranışı
# ---------------------------------------------------------------------------

def test_ocak_31_aylik_subati_atlar():
    """31'i olmayan aylar ATLANIR, ayın sonuna çekilmez.

    Bu bilinçli bir karar: dateutil (ve RFC 5545) var olmayan tarihi üretmez.
    "Şubat'ta 29'a çeksin" isteniyorsa BYMONTHDAY=-1 gibi ayrı bir kural gerekir.
    """
    event = make_event(
        ist(2024, 1, 31, 9, 0),
        ist(2024, 1, 31, 10, 0),
        rrule="FREQ=MONTHLY",
    )
    got = expand(event, [], ist(2024, 1, 1), ist(2024, 7, 1))

    assert local_stamps(got) == [
        "2024-01-31 09:00",
        "2024-03-31 09:00",
        "2024-05-31 09:00",
    ]
    aylar = {to_local(o.start_utc, IST).month for o in got}
    assert 2 not in aylar, "Şubat'ta örnek üretilmemeli"
    assert 4 not in aylar and 6 not in aylar, "30 günlük aylar da atlanmalı"


# ---------------------------------------------------------------------------
# 3. İki haftada bir salı + perşembe
# ---------------------------------------------------------------------------

def test_iki_haftada_bir_sali_persembe():
    """INTERVAL=2 hafta atlamalı; ara haftada hiç örnek olmamalı."""
    event = make_event(
        ist(2024, 1, 2, 10, 0),  # Salı
        ist(2024, 1, 2, 11, 0),
        rrule="FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,TH",
    )
    got = expand(event, [], ist(2024, 1, 1), ist(2024, 2, 5))

    assert local_stamps(got) == [
        "2024-01-02 10:00",
        "2024-01-04 10:00",
        # 8-14 Ocak haftası atlandı
        "2024-01-16 10:00",
        "2024-01-18 10:00",
        # 22-28 Ocak haftası atlandı
        "2024-01-30 10:00",
        "2024-02-01 10:00",
    ]


# ---------------------------------------------------------------------------
# 4. Gece yarısını aşan etkinlik
# ---------------------------------------------------------------------------

def test_gece_yarisini_asan_etkinlik_iki_gunde_de_gorunur():
    """23:00-01:00 etkinliği hem başladığı hem bittiği günün penceresinde."""
    event = make_event(ist(2024, 3, 15, 23, 0), ist(2024, 3, 16, 1, 0))

    ilk_gun = expand(event, [], ist(2024, 3, 15), ist(2024, 3, 16))
    ikinci_gun = expand(event, [], ist(2024, 3, 16), ist(2024, 3, 17))
    ucuncu_gun = expand(event, [], ist(2024, 3, 17), ist(2024, 3, 18))

    assert len(ilk_gun) == 1
    assert len(ikinci_gun) == 1, "Pencereden önce başlayıp içine sarkan örnek kaçtı"
    assert ucuncu_gun == []


def test_gece_yarisini_asan_tekrarli_etkinlik():
    """Tekrarlı sürümde tek günlük pencerede İKİ örnek görünür.

    Dünden sarkan ve bugün başlayan. Bu, rruleset sorgusunun süre kadar geriye
    genişletilmesini test eder -- yapılmazsa sarkan örnek sessizce kaybolur.
    """
    event = make_event(
        ist(2024, 3, 15, 23, 0),
        ist(2024, 3, 16, 1, 0),
        rrule="FREQ=DAILY",
    )
    got = expand(event, [], ist(2024, 3, 16), ist(2024, 3, 17))

    assert local_stamps(got) == ["2024-03-15 23:00", "2024-03-16 23:00"]


# ---------------------------------------------------------------------------
# 5. Çok günlü tüm gün etkinlik
# ---------------------------------------------------------------------------

def test_cok_gunlu_all_day():
    """3 günlük tüm gün etkinliği aradaki her günde görünür, bittiği gün görünmez."""
    event = make_event(
        ist(2024, 6, 10),
        ist(2024, 6, 13),  # 13'ü gece yarısı = 12'nin sonu
        all_day=True,
    )

    for gun in (10, 11, 12):
        pencere = expand(event, [], ist(2024, 6, gun), ist(2024, 6, gun + 1))
        assert len(pencere) == 1, f"Haziran {gun} boş çıktı"
        assert pencere[0].all_day is True

    assert expand(event, [], ist(2024, 6, 13), ist(2024, 6, 14)) == [], (
        "Yarı açık aralık: bitiş anı ertesi güne sızmamalı"
    )
    assert expand(event, [], ist(2024, 6, 9), ist(2024, 6, 10)) == []


# ---------------------------------------------------------------------------
# 6. Sonsuz seri + dar pencere
# ---------------------------------------------------------------------------

def test_sonsuz_seri_sadece_pencereyi_uretir():
    """UNTIL'siz günlük seri, 7 günlük pencerede tam 7 örnek vermeli."""
    event = make_event(
        ist(2020, 1, 1, 8, 0),
        ist(2020, 1, 1, 9, 0),
        rrule="FREQ=DAILY",
    )
    got = expand(event, [], ist(2024, 5, 1), ist(2024, 5, 8))

    assert len(got) == 7
    assert local_stamps(got)[0] == "2024-05-01 08:00"
    assert local_stamps(got)[-1] == "2024-05-07 08:00"
    assert series_end(event) is None, "Sonsuz seride series_end None olmalı"


# ---------------------------------------------------------------------------
# 7. Serinin tek örneğini silme
# ---------------------------------------------------------------------------

def test_tek_ornek_iptali():
    """cancelled=1 override'ı yalnız hedef örneği düşürür."""
    event = make_event(
        ist(2024, 5, 1, 8, 0), ist(2024, 5, 1, 9, 0), rrule="FREQ=DAILY"
    )
    override = Override(
        event_id=1, original_start_utc=ist(2024, 5, 3, 8, 0), cancelled=True
    )
    got = expand(event, [override], ist(2024, 5, 1), ist(2024, 5, 8))

    assert len(got) == 6
    assert "2024-05-03 08:00" not in local_stamps(got)
    assert "2024-05-02 08:00" in local_stamps(got)
    assert "2024-05-04 08:00" in local_stamps(got)


# ---------------------------------------------------------------------------
# 8. Serinin tek örneğini kaydırma
# ---------------------------------------------------------------------------

def test_tek_ornek_kaydirma_komsulari_etkilemez():
    """+2 saat kaydırılan örnek taşınır, başlık/konum ezilir, komşular durur."""
    event = make_event(
        ist(2024, 5, 1, 8, 0),
        ist(2024, 5, 1, 9, 0),
        rrule="FREQ=DAILY",
        location="A101",
    )
    override = Override(
        event_id=1,
        original_start_utc=ist(2024, 5, 3, 8, 0),
        new_start_utc=ist(2024, 5, 3, 10, 0),
        new_title="Telafi dersi",
        new_location="B204",
    )
    got = expand(event, [override], ist(2024, 5, 1), ist(2024, 5, 8))

    assert len(got) == 7
    kaydirilan = [o for o in got if o.is_override]
    assert len(kaydirilan) == 1

    tasinan = kaydirilan[0]
    assert local_stamps([tasinan]) == ["2024-05-03 10:00"]
    assert tasinan.duration == timedelta(hours=1), "Süre korunmalı"
    assert tasinan.title == "Telafi dersi"
    assert tasinan.location == "B204"

    komsular = [o for o in got if not o.is_override]
    assert len(komsular) == 6
    assert all(to_local(o.start_utc, IST).hour == 8 for o in komsular)
    assert all(o.title == "Etkinlik" and o.location == "A101" for o in komsular)


# ---------------------------------------------------------------------------
# 9. Override'ın örneği pencere dışına / içine taşıması
# ---------------------------------------------------------------------------

def test_override_ornegi_pencere_disina_tasir():
    """Pencere içindeki örnek dışarı kaydırılırsa sonuçtan düşer."""
    event = make_event(
        ist(2024, 5, 1, 8, 0), ist(2024, 5, 1, 9, 0), rrule="FREQ=DAILY"
    )
    override = Override(
        event_id=1,
        original_start_utc=ist(2024, 5, 3, 8, 0),
        new_start_utc=ist(2024, 5, 20, 8, 0),
    )
    got = expand(event, [override], ist(2024, 5, 1), ist(2024, 5, 8))

    assert len(got) == 6
    assert "2024-05-03 08:00" not in local_stamps(got)
    assert "2024-05-20 08:00" not in local_stamps(got)


def test_override_ornegi_pencere_icine_tasir():
    """Pencere dışındaki örnek içeri kaydırılırsa sonuca girer.

    Ters yön: naif bir uygulama yalnızca pencerede üretilen örneklere override
    uyguladığı için bu vakayı kaçırır.
    """
    event = make_event(
        ist(2024, 5, 1, 8, 0), ist(2024, 5, 1, 9, 0), rrule="FREQ=DAILY"
    )
    override = Override(
        event_id=1,
        original_start_utc=ist(2024, 5, 20, 8, 0),  # pencerenin çok dışında
        new_start_utc=ist(2024, 5, 1, 15, 0),
        new_end_utc=ist(2024, 5, 1, 16, 0),
    )
    got = expand(event, [override], ist(2024, 5, 1), ist(2024, 5, 2))

    assert local_stamps(got) == ["2024-05-01 08:00", "2024-05-01 15:00"]
    assert got[1].is_override is True


def test_seriye_ait_olmayan_override_yok_sayilir():
    """original_start_utc seride yoksa hayalet örnek üretilmez."""
    event = make_event(
        ist(2024, 5, 1, 8, 0), ist(2024, 5, 1, 9, 0), rrule="FREQ=DAILY"
    )
    hayalet = Override(
        event_id=1,
        original_start_utc=ist(2024, 5, 20, 8, 30),  # 08:30 diye bir örnek yok
        new_start_utc=ist(2024, 5, 1, 15, 0),
    )
    got = expand(event, [hayalet], ist(2024, 5, 1), ist(2024, 5, 2))

    assert local_stamps(got) == ["2024-05-01 08:00"]


# ---------------------------------------------------------------------------
# 10. DST sınırı
# ---------------------------------------------------------------------------

def test_dst_sinirinda_duvar_saati_sabit_kalir():
    """America/New_York'ta günlük 09:00, DST geçiş haftasında 09:00 kalmalı.

    10 Mart 2024'te saatler ileri alınıyor. Genişletme UTC'de yapılsaydı
    geçişten sonra yerel saat 10:00 olurdu ve Türkiye'de test edildiği için
    kimse fark etmezdi.
    """
    event = make_event(
        ny(2024, 3, 1, 9, 0), ny(2024, 3, 1, 10, 0), tzid=NY, rrule="FREQ=DAILY"
    )
    got = expand(event, [], ny(2024, 3, 8), ny(2024, 3, 15))

    assert len(got) == 7
    assert all(
        to_local(o.start_utc, NY).strftime("%H:%M") == "09:00" for o in got
    ), "Yerel duvar saati kaymamalı"

    # UTC karşılığı ise geçişte 14:00Z -> 13:00Z olarak DEĞİŞMELİ.
    assert utc_stamps(got) == [
        "2024-03-08 14:00Z",  # EST (-05:00)
        "2024-03-09 14:00Z",
        "2024-03-10 13:00Z",  # EDT (-04:00) -- geçiş günü
        "2024-03-11 13:00Z",
        "2024-03-12 13:00Z",
        "2024-03-13 13:00Z",
        "2024-03-14 13:00Z",
    ]


def test_dst_sonbahar_gerileme():
    """Sonbahar geçişinde de duvar saati sabit, UTC ofseti geri döner."""
    event = make_event(
        ny(2024, 10, 25, 9, 0), ny(2024, 10, 25, 10, 0), tzid=NY, rrule="FREQ=DAILY"
    )
    got = expand(event, [], ny(2024, 11, 1), ny(2024, 11, 6))

    assert all(to_local(o.start_utc, NY).strftime("%H:%M") == "09:00" for o in got)
    assert utc_stamps(got) == [
        "2024-11-01 13:00Z",  # EDT
        "2024-11-02 13:00Z",
        "2024-11-03 14:00Z",  # 3 Kasım geri alındı -> EST
        "2024-11-04 14:00Z",
        "2024-11-05 14:00Z",
    ]


# ---------------------------------------------------------------------------
# Farklı tzid'li iki etkinlik aynı ekranda (kabul kriteri §7)
# ---------------------------------------------------------------------------

def test_farkli_tzid_ayni_ekranda_dogru_sirada():
    """Duvar saati küçük olan, mutlak zamanda sonra gelebilir.

    İstanbul 10:00 = 07:00Z; New York 04:00 = 08:00Z. Ekranda İstanbul önce.
    """
    ders = make_event(
        ist(2024, 5, 6, 10, 0), ist(2024, 5, 6, 11, 0), uid="ist", title="Ders"
    )
    toplanti = make_event(
        ny(2024, 5, 6, 4, 0),
        ny(2024, 5, 6, 5, 0),
        tzid=NY,
        uid="ny",
        title="Toplantı",
        event_id=2,
    )

    pencere = (ist(2024, 5, 6), ist(2024, 5, 7))
    hepsi = expand(ders, [], *pencere) + expand(toplanti, [], *pencere)
    hepsi.sort(key=lambda o: o.start_utc)

    assert [o.title for o in hepsi] == ["Ders", "Toplantı"]
    assert utc_stamps(hepsi) == ["2024-05-06 07:00Z", "2024-05-06 08:00Z"]


# ---------------------------------------------------------------------------
# EXDATE / RDATE ve series_end
# ---------------------------------------------------------------------------

def test_exdate_ornegi_duserir_rdate_ekler():
    """EXDATE seriden çıkarır, RDATE desene uymayan tek tarih ekler."""
    event = make_event(
        ist(2024, 5, 1, 8, 0),
        ist(2024, 5, 1, 9, 0),
        rrule="FREQ=DAILY",
        exdate=(ist(2024, 5, 3, 8, 0),),
        rdate=(ist(2024, 5, 4, 20, 0),),
    )
    got = expand(event, [], ist(2024, 5, 1), ist(2024, 5, 6))

    assert local_stamps(got) == [
        "2024-05-01 08:00",
        "2024-05-02 08:00",
        "2024-05-04 08:00",
        "2024-05-04 20:00",  # RDATE ile eklenen
        "2024-05-05 08:00",
    ]


def test_series_end_count_ile_sinirli():
    """COUNT'lu seride series_end son örneğin BİTİŞİ olmalı."""
    event = make_event(
        ist(2024, 5, 1, 8, 0), ist(2024, 5, 1, 9, 0), rrule="FREQ=DAILY;COUNT=5"
    )
    assert series_end(event) == ist(2024, 5, 5, 9, 0)


def test_series_end_until_ile_sinirli():
    """UNTIL'li seride de son örneğin bitişi döner."""
    event = make_event(
        ist(2024, 5, 1, 8, 0),
        ist(2024, 5, 1, 9, 0),
        rrule="FREQ=DAILY;UNTIL=20240504T050000Z",  # 04 May 08:00 IST
    )
    assert series_end(event) == ist(2024, 5, 4, 9, 0)


def test_series_end_naive_until_kabul_eder():
    """Gerçek .ics dosyalarındaki UTC olmayan UNTIL patlamamalı.

    dateutil aware DTSTART + naive UNTIL kombinasyonunda ValueError fırlatır;
    normalize etmeseydik Faz 2'de içe aktarma çökerdi.
    """
    event = make_event(
        ist(2024, 5, 1, 8, 0),
        ist(2024, 5, 1, 9, 0),
        rrule="FREQ=DAILY;UNTIL=20240504T080000",  # Z yok, yerel kabul edilir
    )
    assert series_end(event) == ist(2024, 5, 4, 9, 0)
    assert len(expand(event, [], ist(2024, 5, 1), ist(2024, 5, 8))) == 4


def test_series_end_tekrarsiz_etkinlik():
    """Tekrarsız etkinlikte series_end doğrudan bitiş anıdır."""
    event = make_event(ist(2024, 5, 1, 8, 0), ist(2024, 5, 1, 9, 0))
    assert series_end(event) == ist(2024, 5, 1, 9, 0)


# ---------------------------------------------------------------------------
# Pencere sınırları ve savunmacı davranış
# ---------------------------------------------------------------------------

def test_pencere_sinirlari_yari_acik():
    """Pencere sonunda başlayan içeride değil, pencere başında biten de değil."""
    event = make_event(ist(2024, 5, 1, 10, 0), ist(2024, 5, 1, 11, 0))

    assert expand(event, [], ist(2024, 5, 1, 11, 0), ist(2024, 5, 1, 12, 0)) == []
    assert expand(event, [], ist(2024, 5, 1, 9, 0), ist(2024, 5, 1, 10, 0)) == []
    assert len(expand(event, [], ist(2024, 5, 1, 10, 30), ist(2024, 5, 1, 10, 45))) == 1


def test_ters_pencere_bos_doner():
    """window_end <= window_start ise sonuç boş; hata fırlatmıyoruz."""
    event = make_event(ist(2024, 5, 1, 10, 0), ist(2024, 5, 1, 11, 0))
    assert expand(event, [], ist(2024, 5, 2), ist(2024, 5, 1)) == []


def test_naive_pencere_reddedilir():
    """Naive pencere sınırı sessizce yorumlanmaz."""
    from datetime import datetime as _dt

    event = make_event(ist(2024, 5, 1, 10, 0), ist(2024, 5, 1, 11, 0))
    with pytest.raises(ValueError):
        expand(event, [], _dt(2024, 5, 1), ist(2024, 5, 2))
