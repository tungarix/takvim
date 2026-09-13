-- 004: silinen serinin son hâli (tek adımlı geri alma).
--
-- Seri silme geri alınamıyordu: onay kutusu "geri alınamaz" diyordu, çünkü
-- override + hatırlatıcı + fired geçmişiyle birlikte diriltmenin yolu yoktu.
-- Bu tablo SON silinen serinin satırlarını JSON olarak saklıyor; yeni bir
-- silme eskisinin üstüne yazıyor (tek adım, süre sınırı yok).
--
-- Snapshot TÜM çocukları kapsıyor: event_overrides, reminders ve fired geçmişi.
-- Fired olmazsa geri alınan serinin o hafta ÖTMÜŞ örnekleri yeniden bildirilirdi.
-- `deleted_at` yalnızca bilgi için; budama yok, satır hep tek (DELETE + INSERT).
CREATE TABLE silinen_seriler (
    id              INTEGER PRIMARY KEY,
    event_id        INTEGER NOT NULL,   -- silinen serinin eski id'si (bilgi)
    title           TEXT NOT NULL,      -- geri alma bildiriminde gösterilir
    snapshot_json   TEXT NOT NULL,      -- event + overrides + reminders + fired
    deleted_at      TEXT NOT NULL
);
