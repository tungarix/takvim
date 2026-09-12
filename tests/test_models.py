"""Model doğrulaması: bozuk bir Event'i oluşturmak mümkün olmamalı."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core import UTC, Event, Occurrence, Override
from tests.helpers import IST, NY, ist, make_event, ny


def test_bitis_baslangictan_sonra_olmali():
    """end_utc <= start_utc kabul edilmez."""
    with pytest.raises(ValueError, match="end_utc"):
        make_event(ist(2024, 5, 6, 11, 0), ist(2024, 5, 6, 10, 0))
    with pytest.raises(ValueError, match="end_utc"):
        make_event(ist(2024, 5, 6, 10, 0), ist(2024, 5, 6, 10, 0))


def test_gecersiz_tzid_reddedilir():
    """tzid geçerli bir IANA adı olmalı."""
    with pytest.raises(ValueError):
        make_event(ist(2024, 5, 6, 10, 0), ist(2024, 5, 6, 11, 0), tzid="TRT")


def test_all_day_yerel_gece_yarisi_olmali():
    """Tüm gün etkinliği yerel gece yarısında başlayıp bitmeli."""
    with pytest.raises(ValueError, match="all_day"):
        make_event(ist(2024, 6, 10, 9, 0), ist(2024, 6, 11), all_day=True)

    # Doğru kurulum patlamamalı
    make_event(ist(2024, 6, 10), ist(2024, 6, 13), all_day=True)


def test_all_day_dst_gecisinde_gecerli():
    """DST'li dilimde 1 günlük tüm gün etkinliği 23 saat sürer -- yine de geçerli.

    Süreyi UTC'de "24'ün katı mı" diye ölçseydik bu etkinlik reddedilirdi.
    Ölçüt yerel gece yarısı olmak.
    """
    event = make_event(ny(2024, 3, 10), ny(2024, 3, 11), tzid=NY, all_day=True)
    assert event.duration == timedelta(hours=23)


def test_naive_datetime_reddedilir():
    """Model sınırında da naive değer geçmez."""
    with pytest.raises(ValueError):
        Event(
            id=1,
            uid="x",
            calendar_id=1,
            title="x",
            start_utc=datetime(2024, 5, 6, 10, 0),
            end_utc=datetime(2024, 5, 6, 11, 0),
            tzid=IST,
        )


def test_frozen_degistirilemez():
    """Occurrence üretildikten sonra değiştirilemez."""
    occ = Occurrence(
        event_id=1,
        uid="x",
        title="x",
        start_utc=ist(2024, 5, 6, 10, 0),
        end_utc=ist(2024, 5, 6, 11, 0),
        all_day=False,
        tzid=IST,
        calendar_id=1,
    )
    with pytest.raises(Exception):
        occ.title = "yeni"


def test_rdate_exdate_utc_ye_normalize_edilir():
    """Farklı dilimde verilen rdate/exdate UTC'ye çevrilip sıralanır."""
    event = make_event(
        ist(2024, 5, 1, 8, 0),
        ist(2024, 5, 1, 9, 0),
        rrule="FREQ=DAILY",
        rdate=[ny(2024, 5, 9, 4, 0), ist(2024, 5, 4, 20, 0)],
    )
    assert all(d.tzinfo is UTC for d in event.rdate)
    assert list(event.rdate) == sorted(event.rdate), "rdate sıralı tutulmalı"
    assert isinstance(event.rdate, tuple), "frozen dataclass'ta mutable alan olmamalı"


def test_bos_rrule_reddedilir():
    """Tekrar yoksa None kullanılmalı, boş metin değil."""
    with pytest.raises(ValueError, match="rrule"):
        make_event(ist(2024, 5, 1, 8, 0), ist(2024, 5, 1, 9, 0), rrule="   ")


def test_override_ters_aralik_reddedilir():
    """new_end_utc, new_start_utc'den önce olamaz."""
    with pytest.raises(ValueError):
        Override(
            event_id=1,
            original_start_utc=ist(2024, 5, 3, 8, 0),
            new_start_utc=ist(2024, 5, 3, 10, 0),
            new_end_utc=ist(2024, 5, 3, 9, 0),
        )


def test_event_utc_ye_normalize_eder():
    """Hangi dilimde verilirse verilsin start_utc/end_utc UTC'dir."""
    event = make_event(ist(2024, 5, 6, 10, 0), ist(2024, 5, 6, 11, 0))
    assert event.start_utc.tzinfo is UTC
    assert event.start_utc == datetime(2024, 5, 6, 7, 0, tzinfo=UTC)
    assert event.duration == timedelta(hours=1)
    assert event.is_recurring is False
