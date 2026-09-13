-- Takvim veritabanı şeması (güncel hâl).
--
-- Bu dosya REFERANStır: yeni bir DB bundan değil, migrations/ altındaki
-- adımlardan kurulur. İkisinin aynı şemayı ürettiğini test_migrations.py
-- doğruluyor -- iki doğruluk kaynağı olmasın diye.
--
-- Zaman alanları: ISO 8601, her zaman UTC, saniye hassasiyetinde,
-- '2024-05-06T07:00:00Z' biçiminde sabit genişlikte. Sabit genişlik şart:
-- SQLite bunları metin olarak karşılaştırıyor, mikrosaniye eklenirse
-- sözlük sırası kronolojik sıradan ayrılır.

CREATE TABLE calendars (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    color       TEXT NOT NULL,
    visible     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE events (
    id              INTEGER PRIMARY KEY,
    uid             TEXT NOT NULL UNIQUE,   -- RFC 5545 UID, ics uyumu için
    calendar_id     INTEGER NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    description     TEXT,
    location        TEXT,

    start_utc       TEXT NOT NULL,          -- ISO 8601, her zaman UTC
    end_utc         TEXT NOT NULL,
    tzid            TEXT NOT NULL,          -- IANA adı: 'Europe/Istanbul'
    all_day         INTEGER NOT NULL DEFAULT 0,

    rrule           TEXT,                   -- ham RFC 5545 RRULE satırı, nullable
    rdate           TEXT,                   -- ek tarihler, virgüllü
    exdate          TEXT,                   -- hariç tarihler, virgüllü
    series_end_utc  TEXT,                   -- hesaplanmış; sonsuz seride NULL

    sequence        INTEGER NOT NULL DEFAULT 0,   -- Repo'nun yerel revizyon sayacı
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,

    -- 002 ile eklendi. Sonda durmasının sebebi ALTER TABLE ADD COLUMN'un
    -- kolonu tabloya sona eklemesi; burada başka yere yazmak migration'la
    -- kurulan DB'den farklı bir kolon sırası anlamına gelirdi.
    ics_sequence    INTEGER                 -- .ics'teki RFC 5545 SEQUENCE;
                                            -- NULL = hiç içe aktarılmadı
);

-- RFC 5545'teki RECURRENCE-ID karşılığı: serinin tek bir örneğini değiştirmek
CREATE TABLE event_overrides (
    id                  INTEGER PRIMARY KEY,
    event_id            INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    original_start_utc  TEXT NOT NULL,      -- hangi örneği hedefliyor
    cancelled           INTEGER NOT NULL DEFAULT 0,
    new_start_utc       TEXT,
    new_end_utc         TEXT,
    new_title           TEXT,
    new_location        TEXT,
    UNIQUE(event_id, original_start_utc)
);

CREATE INDEX idx_events_window ON events(start_utc, series_end_utc);
CREATE INDEX idx_events_calendar ON events(calendar_id);

-- 003 ile eklendi. Hatırlatıcı SERİYE bağlanır, her ÖRNEK için ayrı tetiklenir;
-- reminder_fired mükerrer bildirimi veritabanı düzeyinde imkânsız kılar.
CREATE TABLE reminders (
    id              INTEGER PRIMARY KEY,
    event_id        INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    minutes_before  INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE(event_id, minutes_before)
);

CREATE TABLE reminder_fired (
    id                    INTEGER PRIMARY KEY,
    reminder_id           INTEGER NOT NULL REFERENCES reminders(id) ON DELETE CASCADE,
    occurrence_start_utc  TEXT NOT NULL,
    fired_at_utc          TEXT NOT NULL,
    UNIQUE(reminder_id, occurrence_start_utc)
);

CREATE INDEX idx_reminders_event ON reminders(event_id);
