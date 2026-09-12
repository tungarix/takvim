"""Aralık sorguları: çakışma tespiti ve boş slot bulma.

Hepsi saf fonksiyon; girdi bir Occurrence listesi, çıktı yeni veri.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .models import Occurrence
from .timeutil import get_tz

__all__ = ["overlaps", "conflicts", "free_slots"]


def overlaps(a: Occurrence, b: Occurrence) -> bool:
    """İki örnek zamanda kesişiyor mu (yarı açık aralık).

    Biri bitip diğeri tam o anda başlıyorsa çakışma YOK: 10-11 ile 11-12 peş
    peşedir, üst üste değil.
    """
    return a.start_utc < b.end_utc and b.start_utc < a.end_utc


def conflicts(occurrences: list[Occurrence]) -> list[tuple[Occurrence, Occurrence]]:
    """Çakışan tüm örnek çiftlerini döndürür.

    Süpürme (sweep) yaklaşımı: başlangıca göre sıralayıp yalnızca hâlâ "açık"
    olan örneklerle karşılaştırır, böylece O(n^2) yerine O(n log n + çift sayısı).
    Çiftler (önce başlayan, sonra başlayan) sırasındadır.
    """
    items = sorted(occurrences, key=lambda o: (o.start_utc, o.end_utc, o.uid))
    out: list[tuple[Occurrence, Occurrence]] = []
    active: list[Occurrence] = []

    for occ in items:
        # Bu örnek başlamadan kapanmış olanları düşür.
        active = [a for a in active if a.end_utc > occ.start_utc]
        for earlier in active:
            out.append((earlier, occ))
        active.append(occ)

    return out


def _covered_days(occ: Occurrence, tz) -> list[date]:
    """Örneğin yerel takvimde dokunduğu günler.

    Bitiş tam gece yarısıysa ertesi güne sayılmaz: 23:00-00:00 tek gündür.
    """
    start_local = occ.start_utc.astimezone(tz)
    end_local = occ.end_utc.astimezone(tz)
    last = (end_local - timedelta(microseconds=1)).date()
    days = []
    cursor = start_local.date()
    while cursor <= last:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def free_slots(
    occurrences: list[Occurrence],
    day_start: time,
    day_end: time,
    min_minutes: int,
    tzid: str,
) -> list[tuple[datetime, datetime]]:
    """Günlük [day_start, day_end] penceresinde en az min_minutes uzunluğunda
    boş aralıkları bulur.

    all_day etkinlikleri meşgul SAYMAZ -- "doğum günü" bütün günü kapatmamalı.

    Hangi günlere bakılacağı verilen örneklerden çıkarılır: bir örneğin
    dokunduğu her yerel gün değerlendirilir. Dönen datetime'lar `tzid`
    dilimindedir; day_start/day_end zaten yerel duvar saati kavramı.
    """
    tz = get_tz(tzid)
    busy = [o for o in occurrences if not o.all_day and o.end_utc > o.start_utc]
    if not busy:
        return []

    minimum = timedelta(minutes=max(int(min_minutes), 0))

    days: set[date] = set()
    for occ in busy:
        days.update(_covered_days(occ, tz))

    out: list[tuple[datetime, datetime]] = []
    for day in sorted(days):
        window_start = datetime.combine(day, day_start, tzinfo=tz)
        window_end = datetime.combine(day, day_end, tzinfo=tz)
        if window_end <= window_start:
            continue  # anlamsız gün penceresi

        # Meşgul aralıkları gün penceresine kırp.
        clipped: list[tuple[datetime, datetime]] = []
        for occ in busy:
            start = max(occ.start_utc.astimezone(tz), window_start)
            end = min(occ.end_utc.astimezone(tz), window_end)
            if start < end:
                clipped.append((start, end))
        clipped.sort()

        # Üst üste binenleri birleştir.
        merged: list[list[datetime]] = []
        for start, end in clipped:
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])

        cursor = window_start
        for start, end in merged:
            if start > cursor and start - cursor >= minimum:
                out.append((cursor, start))
            cursor = max(cursor, end)
        if window_end > cursor and window_end - cursor >= minimum:
            out.append((cursor, window_end))

    out.sort()
    return out
