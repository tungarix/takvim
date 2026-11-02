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
    created_at  TEXT NOT NULL,

    -- 006 ile eklendi (sonda: ALTER kolonu sona ekler). Senkron dosyasının
    -- birleştirme anahtarı ve son yazan kazanır kuralının zaman damgası.
    uid         TEXT,
    updated_at  TEXT
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

-- 004 ile eklendi. Son silinen serinin satırları (JSON anlık görüntü);
-- geri alma tek adımlı: yeni silme eskisinin üstüne yazar.
CREATE TABLE silinen_seriler (
    id              INTEGER PRIMARY KEY,
    event_id        INTEGER NOT NULL,
    title           TEXT NOT NULL,
    snapshot_json   TEXT NOT NULL,
    deleted_at      TEXT NOT NULL
);

-- 005 ile eklendi. Görev takvim etkinliği değil; ne zaman yapılacağı üç
-- hâlden biri (plansız / gün / saat) ve ikisi birden olamaz. Saat planlıysa
-- saati bağlı etkinlik (zaman bloğu) taşır; blok silinirse görev plansıza döner.
CREATE TABLE tasks (
    id          INTEGER PRIMARY KEY,
    uid         TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    notes       TEXT,
    plan_day    TEXT,
    event_id    INTEGER UNIQUE REFERENCES events(id) ON DELETE SET NULL,
    done_at     TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    CHECK (plan_day IS NULL OR event_id IS NULL)
);

CREATE INDEX idx_tasks_plan_day ON tasks(plan_day);

-- 006 ile eklendi. Takvim uid'i benzersiz; senkron dosyası biçimi docs/senkron.md.
CREATE UNIQUE INDEX idx_calendars_uid ON calendars(uid);

-- 006: silinen kayıtlar (mezar taşı) ve zaman damgalarını tutan tetikleyiciler.
-- Gerekçe migrations/006_senkron.sql'de; iki dosyadaki tetikleyici metni aynı
-- olmalı (test_schema_sql_migrationlarla_ayni tetikleyicileri de karşılaştırır).
-- kind: calendar | event | task. deleted_at UTC, sabit genişlikte.
CREATE TABLE silinenler (
    kind        TEXT NOT NULL CHECK (kind IN ('calendar', 'event', 'task')),
    uid         TEXT NOT NULL,
    deleted_at  TEXT NOT NULL,
    PRIMARY KEY (kind, uid)
);

CREATE TRIGGER trg_takvim_ekle_doldur AFTER INSERT ON calendars
WHEN NEW.uid IS NULL OR NEW.updated_at IS NULL
BEGIN
    UPDATE calendars
    SET uid = COALESCE(uid, lower(hex(randomblob(16)))),
        updated_at = COALESCE(updated_at, created_at)
    WHERE id = NEW.id;
END;

CREATE TRIGGER trg_takvim_ekle_mezar AFTER INSERT ON calendars
WHEN NEW.uid IS NOT NULL
BEGIN
    DELETE FROM silinenler WHERE kind = 'calendar' AND uid = NEW.uid;
END;

CREATE TRIGGER trg_takvim_sil AFTER DELETE ON calendars
WHEN OLD.uid IS NOT NULL
BEGIN
    INSERT OR REPLACE INTO silinenler (kind, uid, deleted_at)
    VALUES ('calendar', OLD.uid, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
END;

CREATE TRIGGER trg_takvim_guncelle AFTER UPDATE OF name, color, visible ON calendars
BEGIN
    UPDATE calendars SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE id = NEW.id;
END;

CREATE TRIGGER trg_etkinlik_ekle_mezar AFTER INSERT ON events
BEGIN
    DELETE FROM silinenler WHERE kind = 'event' AND uid = NEW.uid;
END;

CREATE TRIGGER trg_etkinlik_sil AFTER DELETE ON events
BEGIN
    INSERT OR REPLACE INTO silinenler (kind, uid, deleted_at)
    VALUES ('event', OLD.uid, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
END;

CREATE TRIGGER trg_gorev_ekle_mezar AFTER INSERT ON tasks
BEGIN
    DELETE FROM silinenler WHERE kind = 'task' AND uid = NEW.uid;
END;

CREATE TRIGGER trg_gorev_sil AFTER DELETE ON tasks
BEGIN
    INSERT OR REPLACE INTO silinenler (kind, uid, deleted_at)
    VALUES ('task', OLD.uid, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
END;

-- Override ve hatırlatıcı etkinliğin PARÇASI: biri değişince etkinlik değişmiş
-- sayılır (senkronda etkinlik tek birim). Etkinlik zaten silinmişse (CASCADE)
-- UPDATE hiçbir satıra denk gelmez.
CREATE TRIGGER trg_override_ekle AFTER INSERT ON event_overrides
BEGIN
    UPDATE events SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE id = NEW.event_id;
END;

CREATE TRIGGER trg_override_guncelle AFTER UPDATE ON event_overrides
BEGIN
    UPDATE events SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE id IN (OLD.event_id, NEW.event_id);
END;

CREATE TRIGGER trg_override_sil AFTER DELETE ON event_overrides
BEGIN
    UPDATE events SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE id = OLD.event_id;
END;

CREATE TRIGGER trg_hatirlatici_ekle AFTER INSERT ON reminders
BEGIN
    UPDATE events SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE id = NEW.event_id;
END;

CREATE TRIGGER trg_hatirlatici_guncelle AFTER UPDATE ON reminders
BEGIN
    UPDATE events SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE id IN (OLD.event_id, NEW.event_id);
END;

CREATE TRIGGER trg_hatirlatici_sil AFTER DELETE ON reminders
BEGIN
    UPDATE events SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE id = OLD.event_id;
END;
