# AGENTS.md — Takvim projesi

Bu dosya, projede çalışan her kodlama ajanı için kalıcı talimattır. Yeni bir
göreve başlamadan önce tamamını oku.

---

## 0. Projenin hâli

Yerel-öncelikli, tek kullanıcı, çevrimdışı masaüstü takvim uygulaması.

| Faz | Durum |
|---|---|
| Faz 0 — saf mantık çekirdeği (`core/`) | ✅ bitti |
| Faz 1 — kalıcılık (`store/`) | ✅ bitti |
| **Faz 2 — `.ics` içe aktarma (`ics/`)** | ⬅️ **sıradaki** |
| Faz 3 — UI | bekliyor (arayüz kararı verilmedi, bkz. README §8) |
| Faz 4 — konfor | bekliyor |
| Faz 5 — `.ics` dışa aktarma | bekliyor |

**84 test geçiyor.** Görev bitmeden önce hepsinin geçtiğini göstermeden
"tamamlandı" deme.

Ayrıntılı gerekçeler ve kapsam listesi: [README.md](README.md).

---

## 1. Ortam — önce burayı oku

Windows 11, **PowerShell 5.1**. Python 3.14.7, proje kökünde `.venv`.

> **`&&` PowerShell 5.1'de ÇALIŞMAZ.** `The token '&&' is not a valid statement
> separator in this version` hatası verir. Komutları `;` ile ayır.

```powershell
# testler
cd "C:\Users\Arda\Desktop\Aktenak\Projeler\takvim"; .\.venv\Scripts\python.exe -m pytest

# tek dosya
.\.venv\Scripts\python.exe -m pytest tests/test_store.py

# bağımlılık kurulumu
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Sistem Python'unu değil **her zaman `.venv\Scripts\python.exe`** kullan.

### Bağımlılıklar

`python-dateutil` (RRULE), `pytest`, ve `tzdata`.

`tzdata` Windows'ta **zorunlu**: işletim sisteminin IANA veritabanı yok, stdlib
`zoneinfo` onsuz `ZoneInfoNotFoundError` veriyor. Kaldırma.

Yeni bağımlılık eklemeden önce gerekçelendir. Faz 2 için `icalendar` önceden
onaylı; başkası için önce sor.

---

## 2. Değiştirilemez mimari kuralı

```
core/   saf mantık — DB, dosya, ekran bilmez
store/  kalıcılık (SQLite)
ics/    içe/dışa aktarma
ui/     arayüz
```

**`core/` hiçbir zaman `store/`, `ics/` veya `ui/` import etmez. Tersi serbest.**

Bu tek kural motoru ileride başka bir uygulamaya taşınabilir tutuyor. İhlal
etmek için iyi bir sebebin varsa, sebep yanlıştır.

---

## 3. Bozulmaması gereken davranışlar

Bunların her biri gerçek bir hatayı önlüyor ve her birinin mutasyonla
doğrulanmış testi var. Bir tanesini bozarsan ilgili test kırmızıya döner —
testi değiştirerek düzeltmeye çalışma, kodu düzelt.

### core/recurrence.py

1. **Tekrar genişletmesi UTC'de değil, etkinliğin kendi saat diliminde yapılır.**
   "Her gün 09:00" DST geçişinde 09:00 kalmalı. Türkiye'de DST olmadığı için bu
   hata yerel testlerde görünmez; testler bu yüzden `America/New_York` kullanıyor.
2. **Pencere sorgusu, etkinlik süresi kadar geriye genişletilir:**
   `rs.between(window_start - duration, window_end)`. Yapılmazsa 23:00–01:00
   etkinliği ertesi günün penceresinden sessizce kaybolur.
3. **Override bir örneği pencere dışına taşıyabildiği gibi içine de sokabilir.**
   `expand()` içindeki ikinci döngü bunun için var; silme.

### store/repo.py

4. **`PRAGMA foreign_keys = ON` her bağlantıda.** SQLite'ta varsayılan kapalı;
   açılmazsa `ON DELETE CASCADE` sessizce hiçbir şey yapmaz.
5. **İki parçalı aday sorgusu.** Tekrarlı etkinlik DB'de tek satır olduğu için
   `WHERE start_utc BETWEEN ?` yetmez. Bkz. `_candidate_events()`.
6. **`event_overrides` tablosunu tarayan ikinci aday sorgusu.** Serisi geçen yıl
   bitmiş bir etkinliğin örneği bu haftaya taşınmış olabilir.
7. **`series_end_utc` her yazımda yeniden hesaplanır** (`add_event` ve
   `update_event`). Bayatlarsa aralık sorgusu etkinlik kaybeder.
8. **Zaman alanları sabit genişlikte UTC metni:** `2024-05-06T07:00:00Z`,
   20 karakter, mikrosaniye YOK. SQLite bunları metin olarak karşılaştırıyor;
   mikrosaniye eklenirse sözlük sırası kronolojik sıradan ayrılır.

### store/migrator.py

9. **`BEGIN`/`COMMIT` migration script'inin İÇİNDE.** `executescript`
   kendisinden önce açılmış transaction'ı örtük commit ediyor; dışarıdan
   sarmak koruma sağlamıyor ve `ROLLBACK` "no transaction is active" ile patlar.
10. **Uygulanmış bir migration DEĞİŞTİRİLMEZ.** Şema değişikliği yeni bir
    dosyadır (`002_...sql`). Aksi hâlde iki makinedeki DB sessizce farklılaşır.
11. **`schema.sql` ile `migrations/` aynı şemayı üretmeli.**
    `test_schema_sql_migrationlarla_ayni` bunu zorluyor. Şema değiştirirsen
    ikisini birden güncelle.

---

## 4. Kasıtlı kararlar — "hata" sanıp düzeltme

- **31 Ocak + `FREQ=MONTHLY` → Şubat atlanır**, ayın sonuna çekilmez. RFC 5545
  ve dateutil davranışı. "Ayın son günü" isteniyorsa `BYMONTHDAY=-1` ayrı kuraldır.
- **Yarı açık aralık `[start, end)`**: bitişi tam pencere başına denk gelen
  etkinlik içeride sayılmaz. Gün görünümlerinin birbirine sızmaması buna bağlı.
- **`all_day` doğrulaması yerel gece yarısı üzerinden**, UTC süresi üzerinden
  değil: DST'li bir dilimde bir tam gün 23 veya 25 saat sürer.
- **Materialize edilmiş occurrence cache tablosu YOK.** Performans ölçülene
  kadar da olmayacak. Erken optimizasyon burada tutarlılık kâbusuna dönüşür.
- **`core/` içindeki `rdate`/`exdate` tuple**, list değil. Frozen dataclass'ta
  mutable default sorun çıkarıyor; çağıran taraf yine list geçebilir.

### Bilinen sınır

`DTSTART`'tan **önceye** düşen bir `RDATE`, aday sorgusuyla bulunamaz
(`start_utc` alt sınır kabul ediliyor). RFC yasaklamıyor, üreticiler pratikte
yapmıyor. Faz 2'de gerçek veride karşılaşırsan `events` tablosuna
`series_start_utc` kolonu ekleyen bir migration yaz — sessizce geçme.

---

## 5. Kod ve test konvansiyonları

- **Yorumlar ve docstring'ler Türkçe.** Test adları da Türkçe
  (`test_tek_ornek_iptali`). Kod tanımlayıcıları İngilizce.
- Her public fonksiyona **tip ipucu ve kısa docstring**.
- Yorum *ne* yaptığını değil **neden** yaptığını anlatsın. Mevcut yorumlar bu
  tonda; aynı yoğunluğu koru.
- Modeller **frozen dataclass**, doğrulama `__post_init__` içinde. "Sonra
  kontrol ederiz" aşaması yok.
- `core/` fonksiyonları **saf**: yan etki yok, I/O yok, piksel/koordinat yok.
- Her davranış için **ayrı test**. Bir testte üç şey doğrulama.

### Testin gerçekten bir şey ölçtüğünü doğrula

Kritik bir yol eklediysen mutasyonla sına: ilgili satırı kasten boz, testin
kırmızıya döndüğünü gör, sonra **geri yükle**. Yedeği `finally` ile geri
yükleyen bir script kullan — düz kabuk komutuyla yaparsan yarıda kalıp bozuk
dosya bırakırsın (bu projede bir kez oldu).

---

## 6. Çalışma tarzı

- Kapsam dışı listesi README §1'de. Oraya yeni özellik eklemeden önce sor.
- Bir şeyi yapamadıysan **söyle**; sessizce daraltma.
- Testler geçmeden "bitti" deme, `pytest` çıktısını göster.
- Büyük dosyaları kabuk heredoc'u ile yazma: bu ortamda ~8KB'da kesiliyor ve
  "unexpected EOF" veriyor. Dosya yazma aracını kullan.

### Sürüm kontrolü yok — ilk iş bu

Proje henüz git deposu değil. Kod değiştirmeye başlamadan önce:

```powershell
cd "C:\Users\Arda\Desktop\Aktenak\Projeler\takvim"; git init; git add -A; git commit -m "Faz 0 ve Faz 1"
```

`.gitignore` hazır (`.venv/`, `__pycache__/`, `*.db`).

---

## 7. Sıradaki görev

[docs/faz2-ics-import.md](docs/faz2-ics-import.md) — `.ics` içe aktarma.
Kabul kriterleri ve tuzaklar orada.
