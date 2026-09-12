-- 002: .ics SEQUENCE'i ayrı kolona taşı.
--
-- Sorun: `sequence` iki işi birden yapıyordu. Repo onu yerel revizyon sayacı
-- olarak artırıyor (update_event -> sequence + 1), ics/importer ise dosyadaki
-- RFC 5545 SEQUENCE'i oraya yazıp "gelen küçükse atla" karşılaştırması
-- yapıyordu. Sonuç: bir etkinliği elle düzenledikten sonra (sequence 1 olur)
-- aynı .ics dosyasını tekrar içe aktarmak SESSİZCE atlanıyordu, çünkü
-- Google çoğu kayıtta SEQUENCE:0 yazıyor.
--
-- Çözüm: `sequence` Repo'nun sayacı olarak kalır, .ics sürümü ayrı kolonda.
-- NULL = bu etkinlik hiç .ics'ten içe aktarılmadı (karşılaştıracak sürüm yok).

ALTER TABLE events ADD COLUMN ics_sequence INTEGER;
