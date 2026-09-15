"""Kalıcılık katmanı: CRUD ve aralık sorgusu.

`store/` -> `core/` import eder; tersi ASLA olmaz.

Buradaki asıl iş `occurrences()`. Tekrarlı bir etkinlik DB'de tek satır olduğu
için "şu hafta neler var" sorusu basit bir BETWEEN ile cevaplanamaz: serinin
başlangıcı üç yıl önce olabilir. Sorgu iki parçalı, ayrıntı orada.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

from core import (
    UTC,
    Calendar,
    Event,
    Occurrence,
    Override,
    Reminder,
    ensure_aware,
    expand,
    get_tz,
    instance_starts,
    parse_iso,
    series_end,
)

from .migrator import migrate

__all__ = ["Repo", "connect", "new_uid"]

# Sabit genişlikli UTC biçimi: SQLite metin karşılaştırması kronolojik sırayla
# örtüşsün diye mikrosaniye TAŞIMIYORUZ. Takvim için saniye fazlasıyla yeterli.
_DB_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def new_uid() -> str:
    """RFC 5545 uyumlu yeni UID üretir."""
    return f"{uuid.uuid4()}@takvim.local"


def _to_db(value: datetime | None) -> str | None:
    """Aware datetime -> sabit genişlikli UTC metni."""
    if value is None:
        return None
    ensure_aware(value)
    return value.astimezone(UTC).replace(microsecond=0).strftime(_DB_FORMAT)


def _from_db(raw: str | None) -> datetime | None:
    """UTC metni -> aware datetime."""
    return parse_iso(raw) if raw else None


def _join_dates(values) -> str | None:
    """rdate/exdate listesini virgüllü metne çevirir; boşsa NULL."""
    # `cast`: elemanlar her zaman datetime, `_to_db` o girdide asla None
    # döndürmüyor; dönüş tipi yalnızca None girdiyi de kabul ettiği için geniş.
    return ",".join(cast(str, _to_db(v)) for v in values) if values else None


def _split_dates(raw: str | None) -> tuple[datetime, ...]:
    """Virgüllü metni datetime tuple'ına çevirir."""
    if not raw:
        return ()
    return tuple(parse_iso(part) for part in raw.split(",") if part)


def _now_db() -> str:
    """Şimdi, DB biçiminde."""
    return datetime.now(UTC).replace(microsecond=0).strftime(_DB_FORMAT)


# Arama için katlama tablosu. DİLBİLİMSEL OLARAK DOĞRU Türkçe küçültme
# ('I'->'ı', 'İ'->'i') arama için YANLIŞ davranış: Türkçe klavyesi olmayan biri
# "ALGORITMA" yazdığında "algorıtma" elde edilir ve "Algoritma" bulunamaz.
# Aramada niyet eşleştirmek, dil kuralı uygulamak değil; bu yüzden I ailesini
# (I/İ/ı/i) tek harfe indiriyor ve şapkalı harfleri düzlüyoruz. Böylece
# "carsamba" da "Çarşamba"yı buluyor.
_ARAMA_KATLAMA = str.maketrans({
    "I": "i", "İ": "i", "ı": "i",
    "Ş": "s", "ş": "s",
    "Ğ": "g", "ğ": "g",
    "Ç": "c", "ç": "c",
    "Ö": "o", "ö": "o",
    "Ü": "u", "ü": "u",
})


def _arama_anahtari(metin: str) -> str:
    """Metni arama karşılaştırması için normalize eder."""
    return metin.translate(_ARAMA_KATLAMA).lower()


def connect(path: str | Path, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Takvim DB'sine bağlanır.

    isolation_level=None: transaction'ları açıkça biz yönetiyoruz.
    foreign_keys=ON: SQLite'ta varsayılan KAPALI; açılmazsa ON DELETE CASCADE
    sessizce hiçbir şey yapmaz ve silinen takvimin etkinlikleri öksüz kalır.

    `check_same_thread=False` sqlite3'ün thread kontrolünü KAPATIR ve bağlantıyı
    başka bir thread'den kullanmaya izin verir. Varsayılan True, çünkü kontrolü
    kapatmak eşzamanlılığı güvenli yapmaz -- yalnızca kontrolü susturur.
    False geçen çağıran, erişimin sırayla olmasını KENDİSİ garanti etmelidir
    (tek bir sunucu thread'i, ya da bir kilit). Bunu testler kullanıyor: HTTP
    sunucusunu arka plan thread'inde çalıştırıp ana thread'de kurulan depoya
    konuşuyorlar.
    """
    conn = sqlite3.connect(
        str(path), isolation_level=None, check_same_thread=check_same_thread
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def _tx(conn: sqlite3.Connection):
    """Açık transaction; hata hâlinde geri alır."""
    conn.execute("BEGIN")
    try:
        yield
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _row_to_calendar(row: sqlite3.Row) -> Calendar:
    """calendars satırı -> Calendar."""
    return Calendar(
        id=row["id"],
        name=row["name"],
        color=row["color"],
        visible=bool(row["visible"]),
    )


def _row_to_event(row: sqlite3.Row) -> Event:
    """events satırı -> Event (sequence/created_at modele girmez)."""
    return Event(
        id=row["id"],
        uid=row["uid"],
        calendar_id=row["calendar_id"],
        title=row["title"],
        start_utc=parse_iso(row["start_utc"]),
        end_utc=parse_iso(row["end_utc"]),
        tzid=row["tzid"],
        all_day=bool(row["all_day"]),
        rrule=row["rrule"],
        rdate=_split_dates(row["rdate"]),
        exdate=_split_dates(row["exdate"]),
        description=row["description"],
        location=row["location"],
    )


def _row_to_reminder(row: sqlite3.Row) -> Reminder:
    """reminders satırı -> Reminder."""
    return Reminder(
        id=row["id"],
        event_id=row["event_id"],
        minutes_before=row["minutes_before"],
    )


def _row_to_override(row: sqlite3.Row) -> Override:
    """event_overrides satırı -> Override."""
    return Override(
        event_id=row["event_id"],
        original_start_utc=parse_iso(row["original_start_utc"]),
        cancelled=bool(row["cancelled"]),
        new_start_utc=_from_db(row["new_start_utc"]),
        new_end_utc=_from_db(row["new_end_utc"]),
        new_title=row["new_title"],
        new_location=row["new_location"],
    )


def _tek_kural(rrule: str) -> str:
    """RRULE metnindeki TEK kural gövdesini döndürür.

    Satır sınıflandırması `_is_bounded` ile aynı (`RRULE:` önekli ya da çıplak
    satır kuraldır, `DTSTART`/`EXDATE` satırı değil). Birden çok kural varsa
    ValueError: COUNT/UNTIL hesabı kural başına değil küme başına yapılır ve
    bölme yanlış sayardı.
    """
    kurallar = []
    for satir in rrule.splitlines():
        s = satir.strip()
        if not s:
            continue
        if ":" in s:
            prefix, _, body = s.partition(":")
            if prefix.strip().upper().split(";")[0] != "RRULE":
                continue
            kurallar.append(body)
        else:
            kurallar.append(s)
    if len(kurallar) != 1:
        raise ValueError("çok kurallı seriler bölünemez")
    return kurallar[0]


def _kural_satiri_degistir(metin: str, eski: str, yeni: str) -> str:
    """Gövdesi `eski` olan İLK RRULE satırını `yeni` ile değiştirir.

    `str.replace` kullanılmıyor: kural gövdesi metnin başka yerinde de
    geçebilir; satır bazlı eşleşme kesin.
    """
    cikti: list[str] = []
    yapildi = False
    for satir in metin.splitlines():
        s = satir.strip()
        govde, onek = s, ""
        if ":" in s:
            prefix, _, body = s.partition(":")
            if prefix.strip().upper().split(";")[0] != "RRULE":
                cikti.append(satir)
                continue
            govde, onek = body, prefix + ":"
        if not yapildi and govde == eski:
            cikti.append(f"{onek}{yeni}")
            yapildi = True
        else:
            cikti.append(satir)
    return "\n".join(cikti)


def _yeni_kurali_sabitle(kural_govde: str, event: Event, split: datetime) -> str:
    """RDATE noktasından bölünen yeni serinin kuralını ilk güne ÇAPALAR.

    `FREQ=WEEKLY` (BYDAY'siz) gibi kurallar deseni DTSTART'tan alır: Pazartesi
    başlayan seri + Çarşamba RDATE varken Çarşamba'dan bölünüp aynı kural
    yeni DTSTART'la (Çarşamba) kurulursa kalan Pazartesiler Çarşamba'ya KAYAR.
    `BYDAY=MO` yazan kuralda ise kayma yok ama Çarşamba RRULE üretmediği için
    (dateutil DTSTART'ı desene uymuyorsa saymıyor) bölme anı KAYBOLUR.

    Çözüm ikisi için de aynı: bölme anı bir RDATE ise (`split in event.rdate`)
    deseni orijinal güne açıkça yazıyoruz (WEEKLY->BYDAY, MONTHLY->BYMONTHDAY,
    YEARLY->BYMONTH+BYMONTHDAY) ve bölme anını yeni RDATE'te tutuyoruz
    (çağıran `>=` ile ayırıyor; rruleset yineleneni tek sayıyor).
    RRULE örneğinden bölünüyorsa desen zaten korunuyor, dokunulmuyor.
    """
    if split not in set(event.rdate):
        return kural_govde
    parca = re.search(r"FREQ=(\w+)", kural_govde, re.IGNORECASE)
    freq = parca.group(1).upper() if parca else ""
    ust = kural_govde.upper()
    try:
        yerel = event.start_utc.astimezone(get_tz(event.tzid))
    except ValueError:
        return kural_govde
    if freq == "WEEKLY" and "BYDAY=" not in ust:
        kodlar = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
        return f"{kural_govde};BYDAY={kodlar[yerel.weekday()]}"
    if freq == "MONTHLY" and "BYDAY=" not in ust and "BYMONTHDAY=" not in ust:
        return f"{kural_govde};BYMONTHDAY={yerel.day}"
    if (
        freq == "YEARLY"
        and "BYMONTH=" not in ust
        and "BYDAY=" not in ust
        and "BYMONTHDAY=" not in ust
        and "BYYEARDAY=" not in ust
        and "BYWEEKNO=" not in ust
    ):
        return f"{kural_govde};BYMONTH={yerel.month};BYMONTHDAY={yerel.day}"
    return kural_govde


def _seriyi_bol(
    event: Event, overrides: list[Override], split_utc: datetime
) -> tuple[Event, Event, list[Override], list[Override]]:
    """Seriyi BÖLER `(eski, yeni, eski_override'lar, yeni_override'lar)`.

    Saf çekirdek: DB yazmaz. Eski seri `[..., split)` aralığını, yeni seri
    `[split, ...)` aralığını taşır (RFC 5545 `RANGE=THISANDFUTURE` karşılığı).
    Yeni etkinliğin `uid`'si BOŞ dönüyor; çağıran `new_uid()` ile dolduruyor
    (`new_uid` store'a ait, bölme mantığı saf kalıyor).

    Kurallar:
    - COUNT'lu kuralda iki tarafa düşen RRULE ÖRNEK SAYISI yazılıyor (EXDATE
      düşülmeden: iptal edilmiş örnek de kural sayacında durur; görünür sayıya
      bakmak EXDATE'li seride eski tarafı kısa yazar ve örnek kaybolur).
    - COUNT'suz kuralda eskiye `UNTIL` ekleniyor (UTC `Z` biçimi).
    - RDATE/EXDATE ve override'lar bölme anına göre iki tarafa ayrılıyor;
      bölme anı RDATE ise yeni tarafta TUTULUYOR (`>=`) ve yeni kural ilk
      güne çapalanıyor (`_yeni_kurali_sabitle`), yoksa Çarşamba RDATE'ten
      bölünce Çarşamba kayboluyor ya da kalan Pazartesiler Çarşamba'ya kayıyor.
    - Zaman/süre DEĞİŞMİYOR: yeni seri bölme anında aynı saatte başlıyor.
      Başlık/konum/açıklama değişimi çağıranın işi (`replace` ile).
    """
    split = ensure_aware(split_utc, "split_utc").astimezone(UTC)
    if not event.is_recurring:
        raise ValueError("tekrarsız seri bölünemez")

    def _dogrula(baslangiclar: list) -> int:
        """Bölme noktasını listeye karşı doğrular; önceki örnek sayısını döndürür."""
        if split not in baslangiclar:
            raise ValueError("bölme noktası serinin bir örneği olmalı")
        once = sum(1 for s in baslangiclar if s < split)
        if not once:
            raise ValueError("ilk örnekten bölünemez; tümünü düzenle")
        return once

    if event.rrule:
        kural = _tek_kural(event.rrule)
        sayi = re.search(r"COUNT=(\d+)", kural, re.IGNORECASE)
        if sayi:
            # COUNT'lu seri SINIRLI: görünür liste doğrulanır, SAYAÇ kural
            # düzeyinde bölünür. `tum` EXDATE düşülmüş hâl (bölme noktası
            # gerçek bir örnek mi diye bakıyoruz); `R` ise yalın RRULE
            # (RDATE/EXDATE'siz) — COUNT yalnızca onu sayar.
            tum = instance_starts(event)
            _dogrula(tum)
            yalın = replace(event, rdate=(), exdate=())
            kural_ornekleri = instance_starts(yalın)
            once_kural = sum(1 for s in kural_ornekleri if s < split)
            toplam_kural = len(kural_ornekleri)
            yeni_kural_sayisi = toplam_kural - once_kural
            if once_kural <= 0:
                eski_govde = ""
            else:
                eski_govde = re.sub(
                    r"COUNT=\d+", f"COUNT={once_kural}", kural, flags=re.IGNORECASE
                )
            if yeni_kural_sayisi <= 0:
                yeni_govde = ""
            else:
                ham_yeni = re.sub(
                    r"COUNT=\d+",
                    f"COUNT={yeni_kural_sayisi}",
                    kural,
                    flags=re.IGNORECASE,
                )
                yeni_govde = _yeni_kurali_sabitle(ham_yeni, event, split)
        else:
            # UNTIL'li ya da sınırsız: bölme ve öncesi sayılıyor, tam liste yok.
            # Burada SAYI değil doğrulama önemli (COUNT yazılmıyor).
            once = instance_starts(event, before=split)
            genis = instance_starts(event, before=split + timedelta(seconds=1))
            _dogrula([*once, *(s for s in genis if s not in once)])
            # UNTIL kapsayıcı: bölme anının 1 saniye öncesi, bölme örneği
            # eskiye SIZMASIN. Kuralda UNTIL zaten varsa DEĞİŞTİRİLİYOR
            # (eklenmiyor): çift UNTIL'de dateutil sonuncuyu alır ve eski
            # sınır sessizce yanlış olurdu.
            sinir = (split - timedelta(seconds=1)).strftime("%Y%m%dT%H%M%SZ")
            if re.search(r"UNTIL=", kural, re.IGNORECASE):
                eski_govde = re.sub(
                    r"UNTIL=[^;]+", f"UNTIL={sinir}", kural, flags=re.IGNORECASE
                )
            else:
                eski_govde = f"{kural};UNTIL={sinir}"
            yeni_govde = _yeni_kurali_sabitle(kural, event, split)
        if not eski_govde:
            eski_rrule = None
        else:
            eski_rrule = _kural_satiri_degistir(event.rrule, kural, eski_govde)
        if not yeni_govde:
            yeni_rrule: str | None = None
        else:
            yeni_rrule = _kural_satiri_degistir(event.rrule, kural, yeni_govde)
    else:
        # Yalnızca RDATE: liste her zaman sonlu (dönüş değeri değil,
        # doğrulama önemli: ilk örnekten bölünemez).
        _dogrula(instance_starts(event))
        eski_rrule = None
        yeni_rrule = None

    eski = replace(
        event,
        rrule=eski_rrule,
        rdate=tuple(d for d in event.rdate if d < split),
        exdate=tuple(d for d in event.exdate if d < split),
    )
    sure = event.duration
    # Yeni RDATE ayrımı: RRULE'suz seride `>` (bölme anı yeni DTSTART ve
    # DTSTART kuralsızken her zaman sayılıyor, tekrarsız yazılmıyor); RRULE'li
    # seride `>=` (bölme anı RDATE ise yeni RDATE'te TUTULUYOR, çünkü dateutil
    # desene uymayan DTSTART'ı saymıyor — BYDAY=MO kuralında Çarşamba
    # RDATE'ten bölünce Çarşamba kayboluyordu; rruleset yineleneni tek
    # saydığı için RRULE örneğinde bölününce de çift üretim olmuyor).
    # EXDATE'te eşitlik zaten olamaz (doğrulanmış bölme noktası görünür
    # örnek, dışlanmış değil).
    if event.rrule is None:
        yeni_rdate = tuple(d for d in event.rdate if d > split)
    else:
        yeni_rdate = tuple(d for d in event.rdate if d >= split)
    yeni = Event(
        id=None,
        uid="",
        calendar_id=event.calendar_id,
        title=event.title,
        start_utc=split,
        end_utc=split + sure,
        tzid=event.tzid,
        all_day=event.all_day,
        rrule=yeni_rrule,
        rdate=yeni_rdate,
        exdate=tuple(d for d in event.exdate if d >= split),
        description=event.description,
        location=event.location,
    )
    eski_ov = [ov for ov in overrides if ov.original_start_utc.astimezone(UTC) < split]
    yeni_ov = [ov for ov in overrides if ov.original_start_utc.astimezone(UTC) >= split]
    return eski, yeni, eski_ov, yeni_ov


def _event_ekle(conn: sqlite3.Connection, event: Event, now: str) -> int:
    """events satırı yazar, id döndürür. Transaction ÇAĞIRANA ait.

    `add_event` ve `split_series` aynı SQL'i kullanıyor: biri tek başına
    transaction açıyor, öteki bölmenin parçası olarak dışarıdan alıyor.
    """
    cur = conn.execute(
        """
        INSERT INTO events (
            uid, calendar_id, title, description, location,
            start_utc, end_utc, tzid, all_day,
            rrule, rdate, exdate, series_end_utc,
            sequence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        """,
        (
            event.uid,
            event.calendar_id,
            event.title,
            event.description,
            event.location,
            _to_db(event.start_utc),
            _to_db(event.end_utc),
            event.tzid,
            int(event.all_day),
            event.rrule,
            _join_dates(event.rdate),
            _join_dates(event.exdate),
            _to_db(series_end(event)),
            now,
            now,
        ),
    )
    yeni_id = cur.lastrowid
    if yeni_id is None:  # INSERT başarılıysa olmamalı
        raise RuntimeError("Etkinlik yazıldı ama id alınamadı")
    return yeni_id


def _event_guncelle(conn: sqlite3.Connection, event: Event) -> None:
    """events satırını günceller (sequence+1, series_end yeniden). Transaction
    ÇAĞIRANA ait; gerekçe `_event_ekle` ile aynı."""
    if event.id is None:
        raise ValueError("id'si olan bir Event bekler")
    cur = conn.execute(
        """
        UPDATE events SET
            calendar_id = ?, title = ?, description = ?, location = ?,
            start_utc = ?, end_utc = ?, tzid = ?, all_day = ?,
            rrule = ?, rdate = ?, exdate = ?, series_end_utc = ?,
            sequence = sequence + 1, updated_at = ?
        WHERE id = ?
        """,
        (
            event.calendar_id,
            event.title,
            event.description,
            event.location,
            _to_db(event.start_utc),
            _to_db(event.end_utc),
            event.tzid,
            int(event.all_day),
            event.rrule,
            _join_dates(event.rdate),
            _join_dates(event.exdate),
            _to_db(series_end(event)),
            _now_db(),
            event.id,
        ),
    )
    if cur.rowcount == 0:
        raise LookupError(f"Etkinlik bulunamadı: id={event.id}")


class Repo:
    """Takvim veritabanı üzerinde CRUD ve aralık sorgusu."""
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @classmethod
    def open(cls, path: str | Path, *, check_same_thread: bool = True) -> Repo:
        """DB'yi açar ve bekleyen migrationları uygular.

        `check_same_thread` için bkz. `connect()`; varsayılanı değiştirmeden
        önce erişimin sırayla olduğundan emin ol.
        """
        conn = connect(path, check_same_thread=check_same_thread)
        migrate(conn)
        return cls(conn)

    def close(self) -> None:
        """Bağlantıyı kapatır."""
        self.conn.close()

    def __enter__(self) -> Repo:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ----------------------------------------------------------------- takvim

    def add_calendar(self, name: str, color: str, visible: bool = True) -> Calendar:
        """Yeni takvim ekler, id'si atanmış hâlini döndürür."""
        cur = self.conn.execute(
            "INSERT INTO calendars (name, color, visible, created_at) "
            "VALUES (?, ?, ?, ?)",
            (name, color, int(visible), _now_db()),
        )
        return Calendar(id=cur.lastrowid, name=name, color=color, visible=visible)

    def get_calendar(self, calendar_id: int) -> Calendar | None:
        """Tek takvimi getirir; yoksa None."""
        row = self.conn.execute(
            "SELECT * FROM calendars WHERE id = ?", (calendar_id,)
        ).fetchone()
        return _row_to_calendar(row) if row else None

    def list_calendars(self, *, include_hidden: bool = True) -> list[Calendar]:
        """Takvimleri ada göre sıralı döndürür."""
        sql = "SELECT * FROM calendars"
        if not include_hidden:
            sql += " WHERE visible = 1"
        sql += " ORDER BY name"
        return [_row_to_calendar(r) for r in self.conn.execute(sql)]

    def update_calendar(self, calendar: Calendar) -> None:
        """Takvimin adını/rengini/görünürlüğünü günceller."""
        if calendar.id is None:
            raise ValueError("update_calendar id'si olan bir Calendar bekler")
        self.conn.execute(
            "UPDATE calendars SET name = ?, color = ?, visible = ? WHERE id = ?",
            (calendar.name, calendar.color, int(calendar.visible), calendar.id),
        )

    def delete_calendar(self, calendar_id: int) -> None:
        """Takvimi ve (CASCADE ile) tüm etkinliklerini siler."""
        self.conn.execute("DELETE FROM calendars WHERE id = ?", (calendar_id,))

    # --------------------------------------------------------------- etkinlik

    def add_event(self, event: Event) -> Event:
        """Etkinliği kaydeder; series_end_utc'yi RRULE'dan hesaplar."""
        now = _now_db()
        with _tx(self.conn):
            event_id = _event_ekle(self.conn, event, now)
        return replace(event, id=event_id)

    def get_event(self, event_id: int) -> Event | None:
        """Tek etkinliği getirir; yoksa None."""
        row = self.conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        return _row_to_event(row) if row else None

    def get_event_by_uid(self, uid: str) -> Event | None:
        """UID ile etkinlik getirir (.ics içe aktarmada mükerrer kaydı önler)."""
        row = self.conn.execute(
            "SELECT * FROM events WHERE uid = ?", (uid,)
        ).fetchone()
        return _row_to_event(row) if row else None

    def list_events(self, *, calendar_id: int | None = None) -> list[Event]:
        """Etkinlikleri başlangıca göre sıralı döndürür."""
        if calendar_id is None:
            rows = self.conn.execute("SELECT * FROM events ORDER BY start_utc")
        else:
            rows = self.conn.execute(
                "SELECT * FROM events WHERE calendar_id = ? ORDER BY start_utc",
                (calendar_id,),
            )
        return [_row_to_event(r) for r in rows]

    def search_events(self, sorgu: str, *, limit: int = 50) -> list[Event]:
        """Başlık, açıklama ve konumda geçen etkinlikleri arar.

        Eşleştirme Python tarafında yapılıyor, SQL `LIKE` ile değil: SQLite'ın
        `lower()`/`LIKE`'ı yalnızca ASCII'de büyük-küçük harf duyarsız, yani
        "İstanbul" araması "istanbul"u bulamazdı. Karşılaştırma `_arama_anahtari`
        ile hoşgörülü: büyük/küçük harf ve Türkçe şapkalar önemsenmez. Tam tarama, kişisel bir
        takvimin ölçeğinde (binlerce satır) sorun değil; ölçüp gerekirse FTS5
        eklenir -- şimdiden değil.
        """
        anahtar = _arama_anahtari(sorgu).strip()
        if not anahtar:
            return []
        bulunan: list[Event] = []
        for event in self.list_events():
            havuz = " ".join(
                p for p in (event.title, event.description, event.location) if p
            )
            if anahtar in _arama_anahtari(havuz):
                bulunan.append(event)
                if len(bulunan) >= limit:
                    break
        return bulunan

    def update_event(self, event: Event) -> None:
        """Etkinliği günceller; sequence artar, series_end_utc yeniden hesaplanır."""
        if event.id is None:
            raise ValueError("update_event id'si olan bir Event bekler")
        with _tx(self.conn):
            _event_guncelle(self.conn, event)

    def delete_event(self, event_id: int) -> None:
        """Etkinliği ve (CASCADE ile) override'larını siler."""
        self.conn.execute("DELETE FROM events WHERE id = ?", (event_id,))

    @staticmethod
    def _satir_sozluk(row: sqlite3.Row) -> dict:
        """Satırı JSON'lanabilir sözlüğe çevirir (tarih alanları zaten DB metni)."""
        return {k: row[k] for k in row.keys()}

    def snapshot_and_delete(self, event_id: int) -> dict:
        """Seriyi GERİ ALINABİLİR şekilde siler; başlık bilgisini döndürür.

        Satırların tamamı (event + override + hatırlatıcı + fired geçmişi)
        `silinen_seriler` tablosuna JSON olarak yazılır, SONRA silinir. Yeni bir
        silme eskisinin üstüne yazar: geri alma tek adımlı ama süresiz.
        Fired geçmişi de snapshot'ta; yoksa geri alınan serinin o hafta ötmüş
        örnekleri yeniden bildirilirdi.

        `delete_event` duruyor: takvim silmenin CASCADE'i ve mevcut testler onu
        kullanıyor; arayüz seri silmede bunu çağırıyor.
        """
        event_row = self.conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if event_row is None:
            raise LookupError(f"Etkinlik bulunamadı: id={event_id}")
        override_satirlari = self.conn.execute(
            "SELECT * FROM event_overrides WHERE event_id = ?", (event_id,)
        ).fetchall()
        reminder_satirlari = self.conn.execute(
            "SELECT * FROM reminders WHERE event_id = ?", (event_id,)
        ).fetchall()
        fired_satirlari = []
        if reminder_satirlari:
            isaretler = ",".join("?" for _ in reminder_satirlari)
            fired_satirlari = self.conn.execute(
                f"SELECT * FROM reminder_fired WHERE reminder_id IN ({isaretler})",
                tuple(r["id"] for r in reminder_satirlari),
            ).fetchall()
        anlik = {
            "event": self._satir_sozluk(event_row),
            "overrides": [self._satir_sozluk(r) for r in override_satirlari],
            "reminders": [self._satir_sozluk(r) for r in reminder_satirlari],
            "fired": [self._satir_sozluk(r) for r in fired_satirlari],
        }
        with _tx(self.conn):
            self.conn.execute("DELETE FROM silinen_seriler")
            self.conn.execute(
                "INSERT INTO silinen_seriler (event_id, title, snapshot_json, deleted_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    event_id,
                    event_row["title"],
                    json.dumps(anlik, ensure_ascii=False),
                    _now_db(),
                ),
            )
            self.conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        return {"id": event_id, "title": event_row["title"]}

    def son_silinen(self) -> dict | None:
        """Geri alınabilir son silme; yoksa None."""
        row = self.conn.execute(
            "SELECT id, event_id, title, deleted_at FROM silinen_seriler"
            " ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "event_id": row["event_id"],
            "title": row["title"],
            "deleted_at": row["deleted_at"],
        }

    def restore_last_deleted(self) -> Event | None:
        """Son silinen seriyi diriltir; geri alınacak silme yoksa None.

        Eski id'ler BOŞSA korunur (override/hatırlatıcı eşleşmesi birebir olur);
        araya yeni kayıt girmişse yenisi verilir ve çocuklar ona bağlanır. UID
        çakışırsa (aynı UID yeniden içe aktarılmışsa) yenisi üretilir; sessizce
        UNIQUE patlatmak yerine.
        Takvim o arada silinmişse LookupError ve snapshot SAKLANIR: başka
        takvime sessizce yazmak, yazmamaktan kötü.
        """
        row = self.conn.execute("SELECT * FROM silinen_seriler ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        anlik = json.loads(row["snapshot_json"])
        event = anlik["event"]
        with _tx(self.conn):
            if (
                self.conn.execute(
                    "SELECT 1 FROM calendars WHERE id = ?", (event["calendar_id"],)
                ).fetchone()
                is None
            ):
                raise LookupError(
                    "Serinin takvimi silinmiş; önce takvimi oluşturup yeniden dene"
                )
            yeni_id = event["id"]
            if (
                self.conn.execute("SELECT 1 FROM events WHERE id = ?", (yeni_id,)).fetchone()
                is not None
            ):
                yeni_id = None  # araya yeni kayıt girmiş; otomatik id verilsin
            uid = event["uid"]
            if (
                self.conn.execute("SELECT 1 FROM events WHERE uid = ?", (uid,)).fetchone()
                is not None
            ):
                uid = new_uid()
            kolonlar = (
                "uid, calendar_id, title, description, location, start_utc, end_utc,"
                " tzid, all_day, rrule, rdate, exdate, series_end_utc,"
                " sequence, created_at, updated_at, ics_sequence"
            )
            degerler = (
                uid, event["calendar_id"], event["title"], event["description"],
                event["location"], event["start_utc"], event["end_utc"],
                event["tzid"], event["all_day"], event["rrule"], event["rdate"],
                event["exdate"], event["series_end_utc"], event["sequence"],
                event["created_at"], event["updated_at"], event["ics_sequence"],
            )
            if yeni_id is None:
                cur = self.conn.execute(
                    f"INSERT INTO events ({kolonlar}) VALUES ({','.join('?' * 17)})",
                    degerler,
                )
                yeni_id = cur.lastrowid
            else:
                self.conn.execute(
                    f"INSERT INTO events (id, {kolonlar}) VALUES ({','.join('?' * 18)})",
                    (yeni_id, *degerler),
                )
            esleme: dict[int, int] = {}
            for hat in anlik["reminders"]:
                cur = self.conn.execute(
                    "INSERT INTO reminders (event_id, minutes_before, created_at)"
                    " VALUES (?, ?, ?)",
                    (yeni_id, hat["minutes_before"], hat["created_at"]),
                )
                yeni_hat = cur.lastrowid
                if yeni_hat is None:  # INSERT başarılıysa olmamalı
                    raise RuntimeError("Hatırlatıcı geri yazılamadı")
                esleme[hat["id"]] = yeni_hat
            for ov in anlik["overrides"]:
                self.conn.execute(
                    "INSERT INTO event_overrides (event_id, original_start_utc,"
                    " cancelled, new_start_utc, new_end_utc, new_title, new_location)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        yeni_id, ov["original_start_utc"], ov["cancelled"],
                        ov["new_start_utc"], ov["new_end_utc"],
                        ov["new_title"], ov["new_location"],
                    ),
                )
            for ates in anlik["fired"]:
                self.conn.execute(
                    "INSERT INTO reminder_fired (reminder_id, occurrence_start_utc,"
                    " fired_at_utc) VALUES (?, ?, ?)",
                    (
                        esleme[ates["reminder_id"]],
                        ates["occurrence_start_utc"],
                        ates["fired_at_utc"],
                    ),
                )
            self.conn.execute("DELETE FROM silinen_seriler WHERE id = ?", (row["id"],))
        diriltilen = self.get_event(yeni_id)
        if diriltilen is None:  # olmamalı; sessiz None dönülmesin
            raise RuntimeError("Geri alma yazıldı ama okunamadı")
        return diriltilen

    def series_info(self, event_id: int) -> dict:
        """Silme ONAY kutusu için: başlık + örnek sayısı.

        Sonsuz seride sayı "önümüzdeki 2 yıl" demek; `sonsuz` bayrağı metne
        yansıyor ki "104 örnek" sonsuz bir seriyi sınırlı göstermesin.
        Sonlu seride GERÇEK toplam (taşınmış örnekler dahil): 2 yıllık
        pencere 5 yıllık bir ders programını eksik sayıyordu.
        """
        event = self.get_event(event_id)
        if event is None:
            raise LookupError(f"Etkinlik bulunamadı: id={event_id}")
        son = series_end(event)
        overrides = self.list_overrides(event_id)
        if son is None:
            simdi = datetime.now(UTC)
            bas = min(simdi, event.start_utc)
            bit = simdi + timedelta(days=730)
            sayi = len(expand(event, overrides, bas, bit))
        else:
            # Sonlu seri: kural sınırları + taşınmış örneklerin yeni
            # konumları dahil her şey sayılsın (hepsi silinecek).
            adaylar = [event.start_utc, son]
            adaylar.extend(event.rdate)
            for ov in overrides:
                adaylar.append(ov.original_start_utc)
                if ov.new_start_utc is not None:
                    adaylar.append(ov.new_start_utc)
                if ov.new_end_utc is not None:
                    adaylar.append(ov.new_end_utc)
            bas = min(adaylar) - event.duration - timedelta(seconds=1)
            bit = max(adaylar) + timedelta(seconds=1)
            sayi = len(expand(event, overrides, bas, bit))
        return {
            "id": event.id,
            "title": event.title,
            "recurring": event.is_recurring,
            "ornek_sayisi": sayi,
            "sonsuz": son is None,
        }

    def split_series(
        self,
        event_id: int,
        split_utc: datetime,
        *,
        title: str | None = None,
        location: str | None = None,
        description: str | None = None,
    ) -> dict:
        """Seriyi BÖLER: `[..., split)` eski seride kalır, `[split, ...)` YENİ
        seriye taşınır (RFC 5545 `RANGE=THISANDFUTURE` karşılığı).

        `title`/`location`/`description` verilirse YENİ seriye yazılır (dersin
        adı dönem ortasında değişti senaryosu); verilmezse eski değerler aynen
        taşınır. Saat/süre DEĞİŞMEZ — o iş örnek kaydırmada.

        Hepsi TEK transaction'da: eski güncellenir (sequence+1), yeni yazılır,
        override'lar bölünür, hatırlatıcılar kopyalanır, bölme anından SONRAKİ
        fired kayıtları yeni hatırlatıcılara taşınır (taşınmazsa o örnekler
        yeniden öter). Hata hâlinde hiçbir şey değişmez.
        """
        event = self.get_event(event_id)
        if event is None:
            raise LookupError(f"Etkinlik bulunamadı: id={event_id}")
        eski, yeni, _, yeni_ov = _seriyi_bol(
            event, self.list_overrides(event_id), split_utc
        )
        if title is not None:
            yeni = replace(yeni, title=title)
        if location is not None:
            yeni = replace(yeni, location=location)
        if description is not None:
            yeni = replace(yeni, description=description)
        yeni = replace(yeni, uid=new_uid())
        split_metni = _to_db(ensure_aware(split_utc, "split_utc"))
        with _tx(self.conn):
            _event_guncelle(self.conn, eski)
            yeni_id = _event_ekle(self.conn, yeni, _now_db())
            for ov in yeni_ov:
                self.conn.execute(
                    "DELETE FROM event_overrides WHERE event_id = ?"
                    " AND original_start_utc = ?",
                    (event_id, _to_db(ov.original_start_utc)),
                )
                self.put_override(replace(ov, event_id=yeni_id))
            for hat in self.list_reminders(event_id):
                yeni_hat = self.add_reminder(yeni_id, hat.minutes_before)
                # Sabit genişlikte UTC metni sözlük sırasıyla da kronolojik
                # (kural 8); bölme anından sonrakiler yeni hatırlatıcıya taşınır.
                satirlar = self.conn.execute(
                    "SELECT occurrence_start_utc, fired_at_utc FROM reminder_fired"
                    " WHERE reminder_id = ? AND occurrence_start_utc >= ?",
                    (hat.id, split_metni),
                ).fetchall()
                for satir in satirlar:
                    self.conn.execute(
                        "INSERT INTO reminder_fired (reminder_id,"
                        " occurrence_start_utc, fired_at_utc) VALUES (?, ?, ?)",
                        (
                            yeni_hat.id,
                            satir["occurrence_start_utc"],
                            satir["fired_at_utc"],
                        ),
                    )
        return {"eski_id": event_id, "yeni_id": yeni_id, "bolme": split_metni}

    def metadata(self, event_id: int) -> dict | None:
        """Modelde taşınmayan DB alanları: sequence, zaman damgaları, seri sonu."""
        row = self.conn.execute(
            "SELECT sequence, ics_sequence, created_at, updated_at, series_end_utc "
            "FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "sequence": row["sequence"],
            "ics_sequence": row["ics_sequence"],
            "created_at": parse_iso(row["created_at"]),
            "updated_at": parse_iso(row["updated_at"]),
            "series_end_utc": _from_db(row["series_end_utc"]),
        }

    def get_ics_sequence(self, event_id: int) -> int | None:
        """Etkinliğin en son içe aktarıldığı `.ics` SEQUENCE'i; hiç aktarılmadıysa None.

        `sequence` ile karıştırma: o Repo'nun yerel revizyon sayacı ve her
        `update_event` çağrısında artar. Bu kolon yalnızca `.ics` dosyasından
        gelen sürümü taşır, böylece "elle düzenledim" ile "dosya eskidi"
        birbirine karışmaz.
        """
        row = self.conn.execute(
            "SELECT ics_sequence FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            return None
        return None if row["ics_sequence"] is None else int(row["ics_sequence"])

    def set_ics_sequence(self, event_id: int, sequence: int) -> None:
        """İçe aktarılan `.ics` SEQUENCE'ini kaydeder.

        Yerel revizyon sayacına (`sequence`) dokunmaz.
        """
        cur = self.conn.execute(
            "UPDATE events SET ics_sequence = ? WHERE id = ?",
            (int(sequence), event_id),
        )
        if cur.rowcount == 0:
            raise LookupError(f"Etkinlik bulunamadı: id={event_id}")

    # --------------------------------------------------------------- override

    def put_override(self, override: Override) -> Override:
        """Override ekler veya (event_id, original_start_utc) üzerinden günceller.

        new_start_utc verilip new_end_utc verilmediyse bitişi etkinliğin
        süresinden hesaplayıp YAZARIZ. Böylece aday sorgusu override'ın
        kapladığı aralığı SQL'de tam olarak bilebilir.
        """
        if override.event_id is None:
            raise ValueError("put_override event_id bekler")

        resolved = override
        if override.new_start_utc is not None and override.new_end_utc is None:
            event = self.get_event(override.event_id)
            if event is None:
                raise LookupError(f"Etkinlik bulunamadı: id={override.event_id}")
            resolved = replace(
                override, new_end_utc=override.new_start_utc + event.duration
            )

        self.conn.execute(
            """
            INSERT INTO event_overrides (
                event_id, original_start_utc, cancelled,
                new_start_utc, new_end_utc, new_title, new_location
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id, original_start_utc) DO UPDATE SET
                cancelled = excluded.cancelled,
                new_start_utc = excluded.new_start_utc,
                new_end_utc = excluded.new_end_utc,
                new_title = excluded.new_title,
                new_location = excluded.new_location
            """,
            (
                resolved.event_id,
                _to_db(resolved.original_start_utc),
                int(resolved.cancelled),
                _to_db(resolved.new_start_utc),
                _to_db(resolved.new_end_utc),
                resolved.new_title,
                resolved.new_location,
            ),
        )
        return resolved

    def list_overrides(self, event_id: int) -> list[Override]:
        """Bir etkinliğin override'larını orijinal başlangıca göre sıralı döndürür."""
        rows = self.conn.execute(
            "SELECT * FROM event_overrides WHERE event_id = ? "
            "ORDER BY original_start_utc",
            (event_id,),
        )
        return [_row_to_override(r) for r in rows]

    def delete_override(self, event_id: int, original_start_utc: datetime) -> None:
        """Tek override'ı siler (örnek seriye geri döner)."""
        self.conn.execute(
            "DELETE FROM event_overrides WHERE event_id = ? AND original_start_utc = ?",
            (event_id, _to_db(original_start_utc)),
        )

    def cancel_occurrence(
        self, event_id: int, original_start_utc: datetime
    ) -> Override:
        """Serinin tek örneğini iptal eder."""
        return self.put_override(
            Override(
                event_id=event_id,
                original_start_utc=original_start_utc,
                cancelled=True,
            )
        )

    def move_occurrence(
        self,
        event_id: int,
        original_start_utc: datetime,
        new_start_utc: datetime,
        new_end_utc: datetime | None = None,
    ) -> Override:
        """Serinin tek örneğini kaydırır; bitiş verilmezse süre korunur."""
        return self.put_override(
            Override(
                event_id=event_id,
                original_start_utc=original_start_utc,
                new_start_utc=new_start_utc,
                new_end_utc=new_end_utc,
            )
        )

    # ------------------------------------------------------------ hatırlatıcı

    def add_reminder(self, event_id: int, minutes_before: int) -> Reminder:
        """Seriye hatırlatıcı ekler; aynısı varsa mevcudu döndürür."""
        if minutes_before < 0:
            raise ValueError("minutes_before negatif olamaz")
        if self.get_event(event_id) is None:
            raise LookupError(f"Etkinlik bulunamadı: id={event_id}")
        self.conn.execute(
            "INSERT OR IGNORE INTO reminders (event_id, minutes_before, created_at) "
            "VALUES (?, ?, ?)",
            (event_id, int(minutes_before), _now_db()),
        )
        row = self.conn.execute(
            "SELECT * FROM reminders WHERE event_id = ? AND minutes_before = ?",
            (event_id, int(minutes_before)),
        ).fetchone()
        return _row_to_reminder(row)

    def list_reminders(self, event_id: int) -> list[Reminder]:
        """Bir etkinliğin hatırlatıcıları, en erkenden en geçe."""
        rows = self.conn.execute(
            "SELECT * FROM reminders WHERE event_id = ? ORDER BY minutes_before DESC",
            (event_id,),
        )
        return [_row_to_reminder(r) for r in rows]

    def all_reminders(self) -> dict[int, list[Reminder]]:
        """Tüm hatırlatıcılar, event_id'ye göre gruplu.

        Arka plan süreci her turda bunu bir kez çekiyor; etkinlik başına ayrı
        sorgu atmak N+1 olurdu.
        """
        grouped: dict[int, list[Reminder]] = defaultdict(list)
        for row in self.conn.execute("SELECT * FROM reminders ORDER BY minutes_before DESC"):
            grouped[row["event_id"]].append(_row_to_reminder(row))
        return dict(grouped)

    def delete_reminder(self, reminder_id: int) -> None:
        """Hatırlatıcıyı ve (CASCADE ile) tetiklenme kayıtlarını siler."""
        self.conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))

    def fired_keys(self) -> set[tuple]:
        """Daha önce tetiklenmiş (reminder_id, örnek başlangıcı) çiftleri."""
        return {
            (r["reminder_id"], parse_iso(r["occurrence_start_utc"]))
            for r in self.conn.execute(
                "SELECT reminder_id, occurrence_start_utc FROM reminder_fired"
            )
        }

    def mark_fired(self, reminder_id: int, occurrence_start_utc: datetime) -> bool:
        """Tetiklendi olarak işaretler; zaten işaretliyse False döndürür.

        Dönen değer önemli: bildirimi GÖSTERMEDEN ÖNCE bunu çağırıp False
        alırsak gösterme. UNIQUE kısıtı sayesinde iki süreç aynı anda
        çalışsa bile yalnızca biri True alabiliyor.
        """
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO reminder_fired "
            "(reminder_id, occurrence_start_utc, fired_at_utc) VALUES (?, ?, ?)",
            (reminder_id, _to_db(occurrence_start_utc), _now_db()),
        )
        return cur.rowcount > 0

    def prune_fired(self, before: datetime) -> int:
        """Verilen andan eski tetiklenme kayıtlarını siler; silinen sayıyı döndürür.

        Tablo sonsuza kadar büyümesin diye; tetiklenmiş bir örneğin kaydı
        örnek geçtikten sonra bir işe yaramıyor.
        """
        cur = self.conn.execute(
            "DELETE FROM reminder_fired WHERE occurrence_start_utc < ?",
            (_to_db(before),),
        )
        return cur.rowcount

    # ---------------------------------------------------------- aralık sorgusu

    def _candidate_events(
        self,
        window_start: datetime,
        window_end: datetime,
        calendar_ids: list[int] | None,
        include_hidden: bool,
    ) -> list[Event]:
        """Pencereye örnek DÜŞÜREBİLECEK etkinlikleri çeker (iki parçalı sorgu).

        1. Tekrarsız etkinlikler: pencereyle doğrudan kesişenler.
        2. Tekrarlı etkinlikler: başlangıcı pencere sonundan önce VE
           series_end_utc pencere başından sonra (ya da NULL = sonsuz seri).

        Buradan dönenler sadece ADAY; gerçek örnekler core.expand() ile
        üretilip pencereye göre eleniyor.

        Bilinen sınır: DTSTART'tan ÖNCEYE düşen bir RDATE bu sorguyla bulunamaz,
        çünkü start_utc alt sınır kabul ediliyor. RFC bunu yasaklamıyor ama
        üreticiler pratikte yapmıyor; Faz 2 aksini gösterirse series_start_utc
        kolonu eklenir.
        """
        ws, we = _to_db(window_start), _to_db(window_end)
        params: list = []
        where: list[str] = []

        if not include_hidden:
            where.append("c.visible = 1")
        if calendar_ids is not None:
            if not calendar_ids:
                return []
            marks = ",".join("?" for _ in calendar_ids)
            where.append(f"e.calendar_id IN ({marks})")
            params.extend(calendar_ids)

        where.append(
            """(
                (e.rrule IS NULL AND e.rdate IS NULL
                    AND e.start_utc < ? AND e.end_utc > ?)
                OR
                ((e.rrule IS NOT NULL OR e.rdate IS NOT NULL)
                    AND e.start_utc < ?
                    AND (e.series_end_utc IS NULL OR e.series_end_utc > ?))
            )"""
        )
        params.extend([we, ws, we, ws])

        sql = (
            "SELECT e.* FROM events e JOIN calendars c ON c.id = e.calendar_id "
            "WHERE " + " AND ".join(where)
        )
        found = {r["id"]: _row_to_event(r) for r in self.conn.execute(sql, params)}

        # Kaydırılmış bir örnek, serisi pencereye hiç uğramasa bile pencereye
        # düşmüş olabilir (geçen yıl biten seriden bu haftaya taşınan telafi
        # dersi). O etkinlikleri ayrıca topluyoruz.
        extra_where = ["o.cancelled = 0", "o.new_start_utc IS NOT NULL"]
        extra_params: list = []
        if not include_hidden:
            extra_where.append("c.visible = 1")
        if calendar_ids is not None:
            marks = ",".join("?" for _ in calendar_ids)
            extra_where.append(f"e.calendar_id IN ({marks})")
            extra_params.extend(calendar_ids)
        extra_where.append("o.new_start_utc < ?")
        extra_where.append("COALESCE(o.new_end_utc, o.new_start_utc) > ?")
        extra_params.extend([we, ws])

        extra_sql = (
            "SELECT DISTINCT e.* FROM event_overrides o "
            "JOIN events e ON e.id = o.event_id "
            "JOIN calendars c ON c.id = e.calendar_id "
            "WHERE " + " AND ".join(extra_where)
        )
        for row in self.conn.execute(extra_sql, extra_params):
            found.setdefault(row["id"], _row_to_event(row))

        return list(found.values())

    def _overrides_for_events(self, event_ids: list[int]) -> dict[int, list[Override]]:
        """Adayların override'larını TEK sorguda çeker (N+1'den kaçınmak için)."""
        if not event_ids:
            return {}
        marks = ",".join("?" for _ in event_ids)
        rows = self.conn.execute(
            f"SELECT * FROM event_overrides WHERE event_id IN ({marks})", event_ids
        )
        grouped: dict[int, list[Override]] = defaultdict(list)
        for row in rows:
            grouped[row["event_id"]].append(_row_to_override(row))
        return grouped

    def occurrences(
        self,
        window_start: datetime,
        window_end: datetime,
        *,
        calendar_ids: list[int] | None = None,
        include_hidden: bool = False,
    ) -> list[Occurrence]:
        """Pencereye düşen tüm örnekleri başlangıca göre sıralı döndürür.

        Gizli takvimler varsayılan olarak DIŞARIDA; hafta görünümünün takvim
        açıp kapatma davranışı buna dayanıyor.
        """
        ensure_aware(window_start, "window_start")
        ensure_aware(window_end, "window_end")

        candidates = self._candidate_events(
            window_start, window_end, calendar_ids, include_hidden
        )
        overrides = self._overrides_for_events(
            [e.id for e in candidates if e.id is not None]
        )

        out: list[Occurrence] = []
        for event in candidates:
            # Adaylar DB satırından geliyor, id'leri her zaman var. `-1` yalnızca
            # tip denetleyici için; rowid ≥ 1 olduğundan asla çakışmaz.
            anahtar = event.id if event.id is not None else -1
            out.extend(expand(event, overrides.get(anahtar, []), window_start, window_end))
        out.sort(key=lambda o: (o.start_utc, o.end_utc, o.uid))
        return out
