"""Tekrar kurallarının genişletilmesi.

Buradaki tek kritik karar: genişletme UTC'de DEĞİL, etkinliğin kendi saat
diliminde yapılır. "Her gün 09:00" DST geçişinde 09:00 kalmalı; UTC'de
genişletirsen sessizce 08:00 veya 10:00 olur. Türkiye'de DST olmadığı için bu
hata yerel testlerde hiç görünmez -- bu yüzden testler America/New_York ile.

Sonsuz seriler asla materialize edilmez: rruleset.between() ile sadece istenen
pencere üretilir.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timedelta, tzinfo

from dateutil.rrule import rruleset, rrulestr

from .models import Event, Occurrence, Override
from .timeutil import UTC, ensure_aware, get_tz

__all__ = ["expand", "series_end"]

_UNTIL_RE = re.compile(r"UNTIL=([^;\s]+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# RRULE metni hazırlığı
# ---------------------------------------------------------------------------

def _normalize_until(text: str, tz: tzinfo) -> str:
    """RRULE içindeki UTC olmayan UNTIL değerlerini UTC'ye çevirir.

    RFC 5545: DTSTART saat dilimliyse UNTIL UTC olmak ZORUNDA. dateutil bunu
    sıkı uygular ve aksi hâlde ValueError fırlatır. Gerçek .ics dosyalarında
    naive UNTIL bol miktarda var (Faz 2 bunu görecek), o yüzden değeri
    etkinliğin kendi diliminde yorumlayıp UTC'ye çeviriyoruz.
    """

    def repl(match: "re.Match[str]") -> str:
        raw = match.group(1)
        if raw.upper().endswith("Z"):
            return match.group(0)
        try:
            if "T" in raw.upper():
                naive = datetime.strptime(raw, "%Y%m%dT%H%M%S")
            else:
                # Sadece tarih verilmiş: o günün sonunu kastediyor.
                naive = (
                    datetime.strptime(raw, "%Y%m%d")
                    + timedelta(days=1)
                    - timedelta(seconds=1)
                )
        except ValueError:
            # Tanımadık biçim; dateutil kendi hatasını versin.
            return match.group(0)
        as_utc = naive.replace(tzinfo=tz).astimezone(UTC)
        return "UNTIL=" + as_utc.strftime("%Y%m%dT%H%M%SZ")

    return _UNTIL_RE.sub(repl, text)


def _ruleset(event: Event) -> rruleset:
    """Etkinlik için YEREL saat diliminde bir rruleset kurar.

    dtstart yerel (tzid) olarak verilir; dateutil her örneği aynı tzinfo ile
    üretir, dolayısıyla duvar saati sabit kalır ve UTC ofseti DST'ye göre
    kendiliğinden değişir.

    Not: dateutil, RRULE desenine uymayan bir DTSTART'ı ilk örnek saymaz
    (RFC 5545 sayar). Google Calendar dahil çoğu üretici DTSTART'ı desene
    uydurduğu için bu fark pratikte veriye yansımıyor; bilinçli kabul.
    """
    tz = get_tz(event.tzid)
    dtstart = event.start_utc.astimezone(tz)

    if event.rrule:
        # forceset=True: metin RDATE/EXDATE satırları da içerse tek tip sonuç.
        rs = rrulestr(
            _normalize_until(event.rrule, tz),
            dtstart=dtstart,
            forceset=True,
            cache=True,
        )
    else:
        rs = rruleset(cache=True)
        rs.rdate(dtstart)

    for extra in event.rdate:
        rs.rdate(extra.astimezone(tz))
    for excluded in event.exdate:
        rs.exdate(excluded.astimezone(tz))
    return rs


# ---------------------------------------------------------------------------
# Occurrence üretimi
# ---------------------------------------------------------------------------

def _overrides_for(
    event: Event, overrides: Iterable[Override] | None
) -> dict[datetime, Override]:
    """Override'ları orijinal başlangıca göre indeksler (anahtar UTC)."""
    out: dict[datetime, Override] = {}
    for ov in overrides or ():
        # event.id None ise (henüz kaydedilmemiş etkinlik) eşleştirme yapamayız;
        # gelen listeyi bu etkinliğe ait kabul ederiz.
        if event.id is not None and ov.event_id is not None and ov.event_id != event.id:
            continue
        out[ov.original_start_utc.astimezone(UTC)] = ov
    return out


def _plain(event: Event, start_utc: datetime, duration: timedelta) -> Occurrence:
    """Override'sız örnek."""
    return Occurrence(
        event_id=event.id,
        uid=event.uid,
        title=event.title,
        start_utc=start_utc,
        end_utc=start_utc + duration,
        all_day=event.all_day,
        tzid=event.tzid,
        calendar_id=event.calendar_id,
        is_override=False,
        recurring=event.is_recurring,
        location=event.location,
        description=event.description,
        original_start_utc=start_utc,
    )


def _overridden(
    event: Event,
    original_start_utc: datetime,
    duration: timedelta,
    ov: Override,
) -> Occurrence:
    """Override uygulanmış örnek; verilmeyen alanlar seriden miras alınır."""
    start = ov.new_start_utc if ov.new_start_utc is not None else original_start_utc
    if ov.new_end_utc is not None:
        end = ov.new_end_utc
    else:
        # Sadece başlangıç kaydırıldıysa süre korunur.
        end = start + duration
    return Occurrence(
        event_id=event.id,
        uid=event.uid,
        title=ov.new_title if ov.new_title is not None else event.title,
        start_utc=start,
        end_utc=end,
        all_day=event.all_day,
        tzid=event.tzid,
        calendar_id=event.calendar_id,
        is_override=True,
        recurring=event.is_recurring,
        location=ov.new_location if ov.new_location is not None else event.location,
        description=event.description,
        original_start_utc=original_start_utc,
    )


def _intersects(occ: Occurrence, window_start: datetime, window_end: datetime) -> bool:
    """Yarı açık kesişim: [start, end) ile [window_start, window_end).

    Bitişi tam pencere başına denk gelen etkinlik İÇERİDE DEĞİL; başlangıcı tam
    pencere sonuna denk gelen de değil. Gün görünümlerinin birbirine sızmaması
    bu sınır seçimine bağlı.
    """
    return occ.start_utc < window_end and occ.end_utc > window_start


def expand(
    event: Event,
    overrides: list[Override],
    window_start: datetime,
    window_end: datetime,
) -> list[Occurrence]:
    """Etkinliği verilen pencere içinde örneklerine açar.

    Dönen liste start_utc'ye göre sıralıdır. Sonsuz serilerde bile yalnızca
    pencere kadar iş yapılır.
    """
    ensure_aware(window_start, "window_start")
    ensure_aware(window_end, "window_end")
    window_start = window_start.astimezone(UTC)
    window_end = window_end.astimezone(UTC)
    if window_end <= window_start:
        return []

    duration = event.duration
    ov_map = _overrides_for(event, overrides)

    rs: rruleset | None = None
    if event.rrule or event.rdate or event.exdate:
        rs = _ruleset(event)
        # Pencereden ÖNCE başlayıp içine sarkan örnekleri kaçırmamak için sorgu
        # başlangıcını bir süre kadar geriye alıyoruz (gece yarısını aşan
        # etkinlikler, çok günlü tüm gün etkinlikler).
        raw_starts = rs.between(window_start - duration, window_end, inc=True)
    else:
        raw_starts = [event.start_utc]

    out: list[Occurrence] = []
    handled: set[datetime] = set()

    for raw in raw_starts:
        start_utc = raw.astimezone(UTC)
        ov = ov_map.get(start_utc)
        if ov is not None:
            handled.add(start_utc)
            if ov.cancelled:
                continue
            occ = _overridden(event, start_utc, duration, ov)
        else:
            occ = _plain(event, start_utc, duration)
        if _intersects(occ, window_start, window_end):
            out.append(occ)

    # Kaydırılmış bir örnek pencere DIŞINDAN İÇERİ girmiş olabilir: orijinali
    # sorgulanan aralığa hiç düşmediği için yukarıdaki döngü onu görmedi.
    for original_start, ov in ov_map.items():
        if original_start in handled or ov.cancelled or ov.new_start_utc is None:
            continue
        occ = _overridden(event, original_start, duration, ov)
        if not _intersects(occ, window_start, window_end):
            continue
        if not _is_instance(event, rs, original_start):
            continue  # seriye ait olmayan hayalet override
        out.append(occ)

    out.sort(key=lambda o: (o.start_utc, o.end_utc, o.uid))
    return out


def _is_instance(event: Event, rs: rruleset | None, start_utc: datetime) -> bool:
    """start_utc gerçekten bu serinin bir örneği mi (override doğrulaması)."""
    if rs is None:
        return start_utc == event.start_utc
    tz = get_tz(event.tzid)
    target = start_utc.astimezone(tz)
    return any(
        hit.astimezone(UTC) == start_utc
        for hit in rs.between(target, target, inc=True)
    )


# ---------------------------------------------------------------------------
# Seri sonu
# ---------------------------------------------------------------------------

def _is_bounded(rrule_text: str) -> bool:
    """RRULE metnindeki TÜM kurallar UNTIL veya COUNT ile sınırlı mı."""
    seen_rule = False
    for line in rrule_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            prefix, _, body = line.partition(":")
            if prefix.strip().upper().split(";")[0] != "RRULE":
                continue  # DTSTART / RDATE / EXDATE satırı
        else:
            body = line
        seen_rule = True
        upper = body.upper()
        if "UNTIL=" not in upper and "COUNT=" not in upper:
            return False
    return seen_rule


def series_end(event: Event) -> datetime | None:
    """Serinin son örneğinin bitişi; seri sonsuzsa None.

    Bu değer DB'de `series_end_utc` olarak saklanır ve aralık sorgusunun ikinci
    parçasını mümkün kılar: başlangıcı üç yıl önce olan bir seriyi pencereyle
    kesiştirebilmenin tek yolu.
    """
    duration = event.duration

    if not event.rrule:
        last = event.start_utc
        for extra in event.rdate:
            last = max(last, extra)
        return last + duration

    if not _is_bounded(event.rrule):
        return None  # sonsuz seri; RDATE eklense bile sonsuz kalır

    # Sınırlı olduğunu bildiğimiz için materialize etmek güvenli.
    starts = list(_ruleset(event))
    if not starts:
        return None  # tüm örnekler EXDATE ile silinmiş
    return max(starts).astimezone(UTC) + duration
