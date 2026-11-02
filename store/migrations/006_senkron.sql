-- 006: senkron dosyası (.takvimsync) için gereken şema. Biçim: docs/senkron.md.
--
-- Cihazlar arası birleştirme anahtarı `uid`'dir (yerel tamsayı id'ler cihazdan
-- cihaza farklı); etkinlik ve görevde zaten vardı, takvimde yoktu. Son yazan
-- kazanır kuralı `updated_at` ister; takvimde o da yoktu. Silmeler ise hiç iz
-- bırakmıyordu: "ben sildim" ile "bende hiç yoktu" ayırt edilemeyince silme
-- diğer cihaza ulaşamaz, eski dosya silineni geri getirirdi.
--
-- Silinen kayıtlar (mezar taşı) ve zaman damgaları TETİKLEYİCİLERLE tutuluyor:
-- Repo koduna dokunmadan tüm silme yollarını (takvimin CASCADE'i, görev
-- silme, seri silme, geri alma) tek yerde yakalar. Elle yazılan her silme
-- yolunda "mezar taşı yazmayı unutma" kuralı er geç unutulur.

-- Mevcut takvimlere uid verilir; sonra UNIQUE olur. Sütun NULL'a açık kalıyor
-- çünkü ALTER TABLE ADD COLUMN sabit varsayılan olmadan NOT NULL kabul etmiyor;
-- doğrudan INSERT edilen satıra uid'i aşağıdaki trg_takvim_ekle_doldur veriyor.
ALTER TABLE calendars ADD COLUMN uid TEXT;
ALTER TABLE calendars ADD COLUMN updated_at TEXT;
UPDATE calendars SET uid = lower(hex(randomblob(16))), updated_at = created_at;
CREATE UNIQUE INDEX idx_calendars_uid ON calendars(uid);

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
