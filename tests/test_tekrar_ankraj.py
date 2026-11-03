"""Uzak DTSTART'lı sonsuz seri: kural pencereye yakın bir ızgara noktasından başlar.

Güvenlik: yıl 1'den `FREQ=HOURLY` ya da geçen aydan `FREQ=SECONDLY` seri her görünümde
dateutil'e DTSTART'tan pencereye kadar milyonlarca adım yürütüyordu (ölçüldü: 37-46 sn,
kalıcı donma; `.ics` ve `.takvimsync` içe aktarmasıyla girebiliyordu). Düzeltme
sonucu DEĞİŞTİRMEMELİ: aşağıdaki testler ankrajlı ve ankrajsız sonucu karşılaştırır.
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from core import UTC, Override, expand, recurrence, series_end
from tests.helpers import IST, NY, ist, make_event, ny

KURALLAR = [
    "FREQ=DAILY",
    "FREQ=DAILY;INTERVAL=3;BYHOUR=9,17",
    "FREQ=WEEKLY;BYDAY=MO,WE,FR",
    "FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,SA;WKST=SU",
    "FREQ=HOURLY;INTERVAL=5",
    "FREQ=HOURLY;BYDAY=MO;BYHOUR=9,10",
    "FREQ=MINUTELY;INTERVAL=7;BYHOUR=3",
    "FREQ=SECONDLY;INTERVAL=1800",
    "FREQ=DAILY;UNTIL=20271231T000000Z",
    "FREQ=DAILY;BYMONTH=2,11;BYMONTHDAY=3,-1",
]


@pytest.fixture(autouse=True)
def bos_onbellek():
    vars(recurrence._yerel).clear()
    yield
    vars(recurrence._yerel).clear()


def _seri(kural, tzid, bas):
    return make_event(bas, bas + timedelta(minutes=45), tzid=tzid, rrule=kural)


def _ankrajsiz(monkeypatch, event, overrides, bas, bit):
    with monkeypatch.context() as m:
        m.setattr(recurrence, "_ANKRAJ_ESIK", 10**12)
        vars(recurrence._yerel).clear()
        return expand(event, overrides, bas, bit)


@pytest.mark.parametrize("kural", KURALLAR)
@pytest.mark.parametrize("tzid,baslangic", [(IST, ist(2021, 3, 4, 9, 30)), (NY, ny(2022, 1, 9, 17, 5))])
def test_ankrajli_sonuc_ankrajsizla_ayni(monkeypatch, kural, tzid, baslangic):
    event = _seri(kural, tzid, baslangic)
    # Pencereler: DST geçişleri (Mart/Kasım), yıl sonu, ay ortası.
    for bas in (
        datetime(2026, 3, 7, 12, tzinfo=UTC), datetime(2026, 11, 1, 3, tzinfo=UTC),
        datetime(2026, 12, 30, 22, tzinfo=UTC), datetime(2026, 6, 15, 0, 0, 1, tzinfo=UTC),
    ):
        bit = bas + timedelta(days=2)
        beklenen = _ankrajsiz(monkeypatch, event, [], bas, bit)
        vars(recurrence._yerel).clear()
        assert expand(event, [], bas, bit) == beklenen, (kural, tzid, bas)


def test_ankraj_gercekten_devreye_giriyor():
    """Yukarıdaki karşılaştırma ankraj hiç kurulmasa da geçerdi: kurulduğunu doğrula."""
    event = _seri("FREQ=HOURLY", IST, ist(2021, 3, 4, 9, 30))
    ankraj = recurrence._ankraj(event, datetime(2026, 11, 1, tzinfo=UTC))
    assert ankraj is not None and ankraj.year == 2026
    # COUNT, DTSTART satırı, çoklu kural, aylık/yıllık: eski davranış.
    for kural in ("FREQ=HOURLY;COUNT=99999", "FREQ=MONTHLY", "FREQ=YEARLY;BYMONTH=2",
                  "DTSTART:20210304T093000\nRRULE:FREQ=HOURLY"):
        assert recurrence._ankraj(_seri(kural, IST, ist(2021, 3, 4, 9, 30)),
                                  datetime(2026, 11, 1, tzinfo=UTC)) is None


def test_hareket_ettirilmis_ornek_uzak_seride_dogrulanir(monkeypatch):
    """`_is_instance` da ankrajlı: pencereye taşınmış uzak bir örnek override'ı yine görünür,
    seriye ait olmayan hayalet override yine elenir."""
    event = _seri("FREQ=DAILY", IST, ist(2019, 1, 1, 9, 0))
    gercek = ist(2026, 5, 1, 9, 0)
    hayalet = ist(2026, 5, 2, 9, 7)  # ızgarada değil
    yeni = ist(2026, 11, 3, 14, 0)
    overrides = [
        Override(event_id=1, original_start_utc=gercek, new_start_utc=yeni, new_end_utc=yeni + timedelta(minutes=45)),
        Override(event_id=1, original_start_utc=hayalet, new_start_utc=yeni + timedelta(hours=2),
                 new_end_utc=yeni + timedelta(hours=2, minutes=45)),
    ]
    bas, bit = ist(2026, 11, 3), ist(2026, 11, 4)
    sonuc = expand(event, overrides, bas, bit)
    assert [o.start_utc for o in sonuc if o.is_override] == [yeni]
    assert sonuc == _ankrajsiz(monkeypatch, event, overrides, bas, bit)


@pytest.mark.parametrize("kural,baslangic", [
    ("FREQ=HOURLY", datetime(1, 1, 2, tzinfo=UTC)),
    ("FREQ=SECONDLY", datetime(2026, 1, 1, tzinfo=UTC)),
    ("FREQ=MINUTELY", datetime(2000, 1, 1, tzinfo=UTC)),
    ("FREQ=DAILY", datetime(1, 1, 2, tzinfo=UTC)),
])
def test_uzak_baslangicli_sonsuz_seri_donmaz(kural, baslangic):
    """Eskiden 1-46 sn (ve yıl 2000'den SECONDLY saatler) sürerdi."""
    event = _seri(kural, "UTC", baslangic)
    t0 = time.monotonic()
    sonuc = expand(event, [], datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC))
    assert time.monotonic() - t0 < 2.0
    assert sonuc  # yoğun seri pencerede örnek veriyor (kırpılsa bile)


@pytest.mark.parametrize("kural", [
    "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30",
    "FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30,31",
    "FREQ=DAILY;COUNT=5;BYMONTH=4,6,9,11;BYMONTHDAY=31",
    "FREQ=HOURLY;UNTIL=99991231T000000Z;BYMONTHDAY=32",
])
def test_imkansiz_kural_reddedilir(kural):
    t0 = time.monotonic()
    with pytest.raises(ValueError, match="hiçbir tarihe"):
        series_end(_seri(kural, "UTC", datetime(2026, 3, 1, tzinfo=UTC)))
    assert time.monotonic() - t0 < 1.0


@pytest.mark.parametrize("kural", [
    "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29",
    "FREQ=MONTHLY;BYMONTHDAY=31",
    "FREQ=MONTHLY;BYMONTHDAY=-1",
    "FREQ=DAILY;BYMONTH=2,3;BYMONTHDAY=30",   # Mart'ta 30 var
    "FREQ=MONTHLY;BYMONTHDAY=30,-1;BYMONTH=2",  # negatif gün her ayda var
])
def test_mumkun_kural_kabul_edilir(kural):
    series_end(replace(_seri(kural, "UTC", datetime(2026, 3, 1, tzinfo=UTC))))
