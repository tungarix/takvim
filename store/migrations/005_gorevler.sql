-- 005: görevler (yapılacaklar listesi).
--
-- Görev takvim etkinliği DEĞİL: saati olmayabilir. "Ne zaman yapacağım" üç
-- hâlden biri ve ikisi birden OLAMAZ (CHECK): plansız, gün planlı
-- (`plan_day`, saatsiz) ya da saat planlı (`event_id`).
--
-- Saat planlı görevin saati görevde DEĞİL, bağlı etkinlikte (zaman bloğu)
-- durur: iki yerde tutulan bir saat, blok sürüklenince sessizce bayatlardı.
-- Bloğu ızgarada gösteren, taşıyan, boyutlandıran, çakışma uyaran ve
-- hatırlatıcı taşıyan hazır etkinlik altyapısı da böylece görevlere bedavaya
-- geliyor.
--
-- event_id UNIQUE: bir blok tek göreve ait. NULL'lar birbirini çakıştırmaz
-- (SQLite), yani saatsiz görevler serbest.
--
-- ON DELETE SET NULL: blok silinirse (ya da takvimi CASCADE ile giderse)
-- görev YOK OLMAZ, plansıza döner. Görevi silmek ise bloğu da siler; bunu
-- veritabanı değil `Repo.delete_task` yapıyor.
--
-- plan_day 'YYYY-MM-DD' (yerel duvar günü, saat dilimi yok); done_at UTC,
-- NULL = açık. uid VTODO'nun UID'i: .ics içe aktarma aynı görevi ikinci kez
-- eklemesin diye.

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
