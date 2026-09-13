-- 003: hatırlatıcılar.
--
-- Hatırlatıcı SERİYE bağlanır ama her ÖRNEK için ayrı ayrı tetiklenir.
-- `reminder_fired` bu yüzden var: arka plan süreci düzenli aralıklarla
-- yokluyor ve aynı örnek için ikinci kez bildirim göndermemeli.
--
-- UNIQUE(reminder_id, occurrence_start_utc) tekrarı veritabanı düzeyinde
-- imkânsız kılıyor; uygulama mantığındaki bir hata bile mükerrer bildirim
-- üretemesin.

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
