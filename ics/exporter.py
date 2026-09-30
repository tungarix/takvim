"""`.ics` dışa aktarma — taşınabilirlik garantisi.

Amaç tek: verinin bu uygulamada hapsolmaması. Dışa aktarılan dosya kendi
içe aktarıcımızdan geçtiğinde aynı örnekleri üretmeli (test bunu ölçüyor) ve
Google Calendar / Outlook tarafından okunabilmeli.

Kritik karar: saatli etkinlikler UTC'ye ÇEVRİLMEZ, `TZID` parametresiyle kendi
dilimlerinde yazılır ve dosyaya `VTIMEZONE` blokları eklenir. UTC'ye çevirseydik
tekrarlı bir etkinliğin duvar saati karşı tarafta DST geçişinde kayardı --
`core/recurrence.py`'de çözdüğümüz hatanın aynısını dışarıya ihraç etmiş olurduk.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from icalendar import Calendar as ICalendar
from icalendar import Event as IEvent
from icalendar import Timezone, vRecur
from icalendar import Todo as ITodo

from core import UTC, Event, Override, Task
from core.timeutil import get_tz

__all__ = ["export_text", "export_repo", "write_file", "PRODID"]

PRODID = "-//Aktenak//Takvim 0.1//TR"


def _yerel(an: datetime, tzid: str) -> datetime:
    """UTC anı etkinliğin kendi dilimine çevirir (duvar saati için)."""
    return an.astimezone(get_tz(tzid))


def _rrule_ekle(bilesen: IEvent, rrule_metni: str) -> None:
    """Ham RRULE metnini bileşene ekler.

    Metin `RRULE:` önekiyle veya öneksiz gelebilir; çok satırlı da olabilir
    (RDATE/EXDATE satırları RRULE alanında saklanmaz ama üretici garipse olur).
    Sadece RRULE satırlarını alıyoruz, gerisi zaten ayrı alanlarda.
    """
    for satir in rrule_metni.splitlines():
        satir = satir.strip()
        if not satir:
            continue
        if ":" in satir:
            onek, _, govde = satir.partition(":")
            if onek.strip().upper().split(";")[0] != "RRULE":
                continue
        else:
            govde = satir
        bilesen.add("RRULE", vRecur.from_ical(govde))


def _vevent(event: Event, dtstamp: datetime) -> IEvent:
    """Ana kaydın VEVENT'i."""
    ve = IEvent()
    ve.add("UID", event.uid)
    ve.add("DTSTAMP", dtstamp)
    ve.add("SUMMARY", event.title)

    if event.all_day:
        # RFC 5545: DATE değerlerinde TZID YOKTUR ve DTEND dışlayıcıdır.
        # Modelimiz bitişi zaten dışlayıcı yerel gece yarısı tuttuğu için
        # doğrudan eşleşiyor. Bunun bedeli: tüm gün etkinliğin tzid'i dosyada
        # taşınamaz, içe aktarırken default_tzid'e düşer. Biçimin sınırı.
        ve.add("DTSTART", _yerel(event.start_utc, event.tzid).date())
        ve.add("DTEND", _yerel(event.end_utc, event.tzid).date())
    else:
        ve.add("DTSTART", _yerel(event.start_utc, event.tzid))
        ve.add("DTEND", _yerel(event.end_utc, event.tzid))

    if event.description:
        ve.add("DESCRIPTION", event.description)
    if event.location:
        ve.add("LOCATION", event.location)
    if event.rrule:
        _rrule_ekle(ve, event.rrule)

    # RDATE/EXDATE UTC saklanıyor; UTC olarak yazmak her zaman tek anlamlı.
    for ek in event.rdate:
        ve.add("RDATE", ek)
    for haric in event.exdate:
        ve.add("EXDATE", haric)

    return ve


# Görev bloğu bilgisi: (başlangıç_utc, bitiş_utc, tzid, blok etkinliğinin UID'si).
GorevBlogu = tuple[datetime, datetime, str, str]


def _vtodo(task: Task, dtstamp: datetime, blok: GorevBlogu | None) -> ITodo:
    """Görevin VTODO'su.

    Saat planlı görevde saat, bloğun GEÇERLİ saatinden (sürüklemeyle taşınmış
    olabilir) yazılıyor ve `X-TAKVIM-BLOK-UID` bloğun VEVENT'ini gösteriyor:
    kendi içe aktarıcımız görevi ikinci bir blok açmadan ona bağlıyor. Başka
    uygulamalar `X-` özelliğini yok sayar; onlar için VTODO kendi başına anlamlı
    (DTSTART/DUE bloğun saatleri). Gün planlıda yalnızca `DUE` (tarih): saatsiz
    görevin ızgarada yeri yok, tüm gün etkinliği gibi yazmak yanlış olurdu.
    """
    vt = ITodo()
    vt.add("UID", task.uid)
    vt.add("DTSTAMP", dtstamp)
    vt.add("SUMMARY", task.title)
    if task.notes:
        vt.add("DESCRIPTION", task.notes)

    if task.done_at is not None:
        vt.add("STATUS", "COMPLETED")
        vt.add("COMPLETED", task.done_at)
        vt.add("PERCENT-COMPLETE", 100)
    else:
        vt.add("STATUS", "NEEDS-ACTION")

    if blok is not None:
        bas, bit, tzid, blok_uid = blok
        vt.add("DTSTART", _yerel(bas, tzid))
        vt.add("DUE", _yerel(bit, tzid))
        vt.add("X-TAKVIM-BLOK-UID", blok_uid)
    elif task.plan_day is not None:
        vt.add("DUE", task.plan_day)
    return vt


def _override_vevent(event: Event, ov: Override, dtstamp: datetime) -> IEvent:
    """Bir örnek geçersiz kılmanın VEVENT'i (aynı UID + RECURRENCE-ID)."""
    ve = IEvent()
    ve.add("UID", event.uid)
    ve.add("DTSTAMP", dtstamp)
    # RECURRENCE-ID orijinal başlangıcı işaret eder, kaydırılmış hâli değil.
    ve.add("RECURRENCE-ID", ov.original_start_utc)

    if ov.cancelled:
        ve.add("STATUS", "CANCELLED")
        # İptal edilmiş örnek de geçerli bir VEVENT olmalı: DTSTART şart.
        ve.add("DTSTART", ov.original_start_utc)
        ve.add("SUMMARY", ov.new_title or event.title)
        return ve

    baslangic = ov.new_start_utc or ov.original_start_utc
    bitis = ov.new_end_utc or (baslangic + event.duration)
    ve.add("DTSTART", _yerel(baslangic, event.tzid))
    ve.add("DTEND", _yerel(bitis, event.tzid))
    ve.add("SUMMARY", ov.new_title if ov.new_title is not None else event.title)
    konum = ov.new_location if ov.new_location is not None else event.location
    if konum:
        ve.add("LOCATION", konum)
    if event.description:
        ve.add("DESCRIPTION", event.description)
    return ve


def export_text(
    events: list[Event],
    overrides_by_event: dict[int | None, list[Override]] | None = None,
    *,
    tasks: list[Task] | None = None,
    task_blocks: dict[int, GorevBlogu] | None = None,
    prodid: str = PRODID,
    dtstamp: datetime | None = None,
) -> str:
    """Etkinlikleri (ve verilmişse görevleri) `.ics` metnine çevirir. DB bilmez, saf.

    `overrides_by_event` anahtarı `event.id`'dir. `task_blocks` anahtarı
    görevin `event_id`'si (bkz. `GorevBlogu`). `dtstamp` testlerde sabit
    verilebilsin diye parametre; verilmezse şimdiki an kullanılır.
    """
    overrides_by_event = overrides_by_event or {}
    dtstamp = dtstamp or datetime.now(UTC).replace(microsecond=0)

    takvim = ICalendar()
    takvim.add("PRODID", prodid)
    takvim.add("VERSION", "2.0")
    takvim.add("CALSCALE", "GREGORIAN")

    # Saatli etkinliklerin kullandığı her dilim için VTIMEZONE.
    # Tüm gün etkinlikler TZID taşımadığı için onları saymıyoruz.
    # Saat planlı görevin VTODO'su da bloğunun diliminde yazılıyor.
    task_blocks = task_blocks or {}
    dilimler = sorted(
        {e.tzid for e in events if not e.all_day} | {b[2] for b in task_blocks.values()}
    )
    for tzid in dilimler:
        takvim.add_component(Timezone.from_tzid(tzid))

    for event in events:
        takvim.add_component(_vevent(event, dtstamp))
        for ov in overrides_by_event.get(event.id, []):
            takvim.add_component(_override_vevent(event, ov, dtstamp))

    for gorev in tasks or []:
        blok = task_blocks.get(gorev.event_id) if gorev.event_id is not None else None
        takvim.add_component(_vtodo(gorev, dtstamp, blok))

    return takvim.to_ical().decode("utf-8")


def export_repo(
    repo,
    *,
    calendar_ids: list[int] | None = None,
    prodid: str = PRODID,
    dtstamp: datetime | None = None,
) -> str:
    """Veritabanındaki etkinlikleri `.ics` metnine çevirir.

    `calendar_ids` verilmezse GÖRÜNÜRLÜKTEN BAĞIMSIZ olarak hepsi aktarılır:
    dışa aktarma bir yedek, ekran filtresi değil. Görevler takvime ait değil;
    yalnızca TAM dışa aktarmada (takvim süzgeci yokken) yazılıyor.
    """
    if calendar_ids is None:
        events = repo.list_events()
        gorevler = repo.list_tasks()
    else:
        events = [e for cid in calendar_ids for e in repo.list_events(calendar_id=cid)]
        events.sort(key=lambda e: e.start_utc)
        gorevler = []

    overrides = {e.id: repo.list_overrides(e.id) for e in events}

    # Bloğun GEÇERLİ saati (sürüklemede override yazılıyor; etkinlik satırı eski kalır).
    blok_idleri = [g.event_id for g in gorevler if g.event_id is not None]
    slotlar = repo.task_slots(blok_idleri)
    bloklar = repo.get_events(blok_idleri)
    task_blocks = {
        eid: (slotlar[eid][0], slotlar[eid][1], bloklar[eid].tzid, bloklar[eid].uid)
        for eid in blok_idleri if eid in slotlar and eid in bloklar
    }
    return export_text(
        events, overrides, tasks=gorevler, task_blocks=task_blocks,
        prodid=prodid, dtstamp=dtstamp,
    )


def write_file(
    repo,
    path: str | Path,
    *,
    calendar_ids: list[int] | None = None,
    prodid: str = PRODID,
) -> Path:
    """Dışa aktarımı dosyaya yazar ve yolunu döndürür."""
    hedef = Path(path)
    hedef.write_text(
        export_repo(repo, calendar_ids=calendar_ids, prodid=prodid),
        encoding="utf-8",
        newline="",
    )
    return hedef
