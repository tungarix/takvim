"""Testlerde tekrar eden kurulum yardımcıları.

Etkinlikleri hep YEREL duvar saatiyle kuruyoruz (`from_wall_clock`), çünkü
insan da öyle düşünüyor: "salı 09:00". UTC'ye çevirme işi kütüphanenin.
"""

from __future__ import annotations

from datetime import datetime

from core import Event, Occurrence, Override, from_wall_clock

IST = "Europe/Istanbul"   # DST yok -- hataları saklar
NY = "America/New_York"   # DST var -- hataları ortaya çıkarır

__all__ = [
    "IST",
    "NY",
    "wall",
    "ist",
    "ny",
    "make_event",
    "make_occ",
    "local_stamps",
    "utc_stamps",
]


def wall(tzid: str, y: int, m: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    """Yerel duvar saatinden aware UTC datetime üretir."""
    return from_wall_clock(datetime(y, m, d, h, mi), tzid)


def ist(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    """Europe/Istanbul duvar saatinden UTC."""
    return wall(IST, y, m, d, h, mi)


def ny(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    """America/New_York duvar saatinden UTC."""
    return wall(NY, y, m, d, h, mi)


def make_event(
    start_utc: datetime,
    end_utc: datetime,
    *,
    tzid: str = IST,
    rrule: str | None = None,
    rdate: tuple[datetime, ...] = (),
    exdate: tuple[datetime, ...] = (),
    all_day: bool = False,
    event_id: int | None = 1,
    uid: str = "evt-1",
    title: str = "Etkinlik",
    calendar_id: int | None = 1,
    location: str | None = None,
    description: str | None = None,
) -> Event:
    """Testler için kısa Event kurucusu."""
    return Event(
        id=event_id,
        uid=uid,
        calendar_id=calendar_id,
        title=title,
        start_utc=start_utc,
        end_utc=end_utc,
        tzid=tzid,
        all_day=all_day,
        rrule=rrule,
        rdate=rdate,
        exdate=exdate,
        location=location,
        description=description,
    )


def make_occ(
    start_utc: datetime,
    end_utc: datetime,
    *,
    uid: str = "occ",
    title: str = "Occ",
    all_day: bool = False,
    tzid: str = IST,
    event_id: int | None = 1,
    calendar_id: int | None = 1,
) -> Occurrence:
    """layout/query testleri için doğrudan Occurrence kurucusu."""
    return Occurrence(
        event_id=event_id,
        uid=uid,
        title=title,
        start_utc=start_utc,
        end_utc=end_utc,
        all_day=all_day,
        tzid=tzid,
        calendar_id=calendar_id,
    )


def local_stamps(occurrences, tzid: str = IST) -> list[str]:
    """Örnekleri okunur yerel damgalara çevirir: '2024-01-31 09:00'."""
    from core import to_local

    return [to_local(o.start_utc, tzid).strftime("%Y-%m-%d %H:%M") for o in occurrences]


def utc_stamps(occurrences) -> list[str]:
    """Örnekleri UTC damgalarına çevirir: '2024-03-10 13:00Z'."""
    return [o.start_utc.strftime("%Y-%m-%d %H:%MZ") for o in occurrences]
