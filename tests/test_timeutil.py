"""timeutil sözleşmesi: naive datetime sisteme sızmaz."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core import (
    UTC,
    format_iso,
    from_wall_clock,
    is_valid_tzid,
    parse_iso,
    to_local,
    to_utc,
)
from tests.helpers import IST, NY


def test_naive_girdi_reddedilir():
    """to_utc / to_local naive değeri sessizce yorumlamaz."""
    naive = datetime(2024, 5, 6, 10, 0)
    with pytest.raises(ValueError, match="naive"):
        to_utc(naive, IST)
    with pytest.raises(ValueError, match="naive"):
        to_local(naive, IST)


def test_from_wall_clock_aware_girdiyi_reddeder():
    """Aware değeri from_wall_clock'a vermek programcı hatasıdır."""
    with pytest.raises(ValueError):
        from_wall_clock(datetime(2024, 5, 6, 10, 0, tzinfo=UTC), IST)


def test_from_wall_clock_ofseti_dogru_secer():
    """İstanbul sabit +03; New York yaz/kış farklı ofset kullanır."""
    assert from_wall_clock(datetime(2024, 5, 6, 10, 0), IST) == datetime(
        2024, 5, 6, 7, 0, tzinfo=UTC
    )
    # 6 Mayıs yaz saati (EDT, -04:00)
    assert from_wall_clock(datetime(2024, 5, 6, 10, 0), NY) == datetime(
        2024, 5, 6, 14, 0, tzinfo=UTC
    )
    # 6 Ocak kış saati (EST, -05:00)
    assert from_wall_clock(datetime(2024, 1, 6, 10, 0), NY) == datetime(
        2024, 1, 6, 15, 0, tzinfo=UTC
    )


def test_gecersiz_tzid():
    """Bilinmeyen IANA adı ValueError verir, sessizce UTC'ye düşmez."""
    assert is_valid_tzid(IST) is True
    assert is_valid_tzid("Mars/Olympus") is False
    with pytest.raises(ValueError):
        to_local(datetime(2024, 5, 6, tzinfo=UTC), "Mars/Olympus")


def test_parse_iso_ofset_sart():
    """Ofsetsiz ISO metni reddedilir."""
    assert parse_iso("2024-05-06T07:00:00Z") == datetime(2024, 5, 6, 7, 0, tzinfo=UTC)
    assert parse_iso("2024-05-06T10:00:00+03:00") == datetime(
        2024, 5, 6, 7, 0, tzinfo=UTC
    )
    with pytest.raises(ValueError):
        parse_iso("2024-05-06T10:00:00")
    with pytest.raises(ValueError):
        parse_iso("dün")


def test_format_iso_utc_icin_z_kullanir():
    """UTC değerler 'Z' ile yazılır; diğer ofsetler korunur."""
    assert format_iso(datetime(2024, 5, 6, 7, 0, tzinfo=UTC)) == "2024-05-06T07:00:00Z"

    yerel = to_local(datetime(2024, 5, 6, 7, 0, tzinfo=UTC), IST)
    assert format_iso(yerel) == "2024-05-06T10:00:00+03:00"


def test_iso_gidis_donus():
    """format_iso -> parse_iso aynı anı korur."""
    an = datetime(2024, 5, 6, 7, 30, 15, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert parse_iso(format_iso(an)) == an
