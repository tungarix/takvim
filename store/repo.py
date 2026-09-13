"""Kalıcılık katmanı: CRUD ve aralık sorgusu.

`store/` -> `core/` import eder; tersi ASLA olmaz.

Buradaki asıl iş `occurrences()`. Tekrarlı bir etkinlik DB'de tek satır olduğu
için "şu hafta neler var" sorusu basit bir BETWEEN ile cevaplanamaz: serinin
başlangıcı üç yıl önce olabilir. Sorgu iki parçalı, ayrıntı orada.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from core import (
    UTC,
    Calendar,
    Event,
    Occurrence,
    Override,
    Reminder,
    ensure_aware,
    expand,
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
    return ",".join(_to_db(v) for v in values) if values else None


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


class Repo:
    """Takvim veritabanı üzerinde CRUD ve aralık sorgusu."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @classmethod
    def open(cls, path: str | Path, *, check_same_thread: bool = True) -> "Repo":
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

    def __enter__(self) -> "Repo":
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
            cur = self.conn.execute(
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
            event_id = cur.lastrowid
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
            cur = self.conn.execute(
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

    def delete_event(self, event_id: int) -> None:
        """Etkinliği ve (CASCADE ile) override'larını siler."""
        self.conn.execute("DELETE FROM events WHERE id = ?", (event_id,))

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
        overrides = self._overrides_for_events([e.id for e in candidates])

        out: list[Occurrence] = []
        for event in candidates:
            out.extend(
                expand(event, overrides.get(event.id, []), window_start, window_end)
            )
        out.sort(key=lambda o: (o.start_utc, o.end_utc, o.uid))
        return out
