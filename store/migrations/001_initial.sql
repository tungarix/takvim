-- 001: ilk şema.
--
-- Bu dosya kaynak; store/schema.sql onun okunabilir anlık görüntüsü.
-- Uygulanan sürüm SQLite "PRAGMA user_version" içinde tutulur.

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

    sequence        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
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
