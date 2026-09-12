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
| Faz 2 — `.ics` içe aktarma (`ics/`) | ✅ bitti |
| Faz 3 — UI, gün/hafta/ay (`ui/`) | ✅ bitti |
| Faz 4 — konfor (hızlı ekleme, arama, kısayollar) | ✅ bitti |
| Faz 5 — `.ics` dışa aktarma | ✅ bitti |

**v1 kapsamı tamamlandı.**

**185 test geçiyor.** Görev bitmeden önce hepsinin geçtiğini göstermeden
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

`icalendar` Faz 2 ile eklendi (`.ics` ayrıştırma).

Yeni bağımlılık eklemeden önce gerekçelendir ve önce sor.

---

## 2. Değiştirilemez mimari kuralı

```
core/   saf mantık — DB, dosya, ekran bilmez
store/  kalıcılık (SQLite)
ics/    içe/dışa aktarma
ui/     arayüz (yerel web, stdlib http.server)
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
9. **`sequence` ve `ics_sequence` AYRI kolonlar, karıştırma.** `sequence`
   Repo'nun yerel revizyon sayacı (`update_event` her çağrıda artırır);
   `ics_sequence` yalnızca `.ics` dosyasından gelen RFC 5545 SEQUENCE'i taşır ve
   `NULL` "hiç içe aktarılmadı" demektir. İkisi bir kez tek kolonda birleşmişti:
   elle düzenlenen etkinlik `sequence`'i artırdığı için `SEQUENCE:0` yazan her
   dosya sonsuza dek "eski" sayılıyor ve içe aktarma SESSİZCE düşüyordu.
   Erişim `repo.get_ics_sequence()` / `repo.set_ics_sequence()` ile; `ics/`
   içinden `repo.conn`'a ham SQL yazma.

### store/migrator.py

10. **`BEGIN`/`COMMIT` migration script'inin İÇİNDE.** `executescript`
   kendisinden önce açılmış transaction'ı örtük commit ediyor; dışarıdan
   sarmak koruma sağlamıyor ve `ROLLBACK` "no transaction is active" ile patlar.
11. **Uygulanmış bir migration DEĞİŞTİRİLMEZ.** Şema değişikliği yeni bir
    dosyadır (`003_...sql`). Aksi hâlde iki makinedeki DB sessizce farklılaşır.
12. **`schema.sql` ile `migrations/` aynı şemayı üretmeli.**
    `test_schema_sql_migrationlarla_ayni` bunu zorluyor -- ham DDL metnini değil
    YAPIYI (kolon/indeks/yabancı anahtar) karşılaştırır, çünkü `ALTER TABLE ADD
    COLUMN` saklanan metni değiştiriyor. Şema değiştirirsen ikisini de güncelle
    ve yeni kolonu `schema.sql`'de SONA yaz (ALTER kolonu sona ekler).

### ui/

13. **Gün sınırları `başlangıç + 24 saat` DEĞİL.** DST gününde bir gün 23 veya
    25 saat sürer. `day_bounds()` her iki sınırı da `datetime.combine` ile kurar
    ve `dayMinutes` her gün için ayrı gönderilir.
14. **Aware datetime farkını UTC'ye çevirmeden ALMA.** CPython'ın
    `datetime.__sub__`'ı `self._tzinfo is other._tzinfo` ise ofsetleri
    uygulamadan naive farkı döndürüyor. `get_tz` lru_cache'li olduğu için gün
    sınırları aynı `ZoneInfo` nesnesini taşır ve doğrudan çıkarma DST gününde
    24 saat verir. `_dakika()` bu yüzden `astimezone(UTC)` yapıyor.
15. **Kırpma `layout()`'tan ÖNCE.** Gece yarısını aşan etkinlik her güne
    kırpılıp öyle yerleştirilir; yoksa dünden sarkan blok ertesi sabahı boşuna
    daraltır. Kırpılmış blok ızgarada kesik çizilir ama panelde GERÇEK saatini
    gösterir (`startUtc`/`endUtc` orijinal kalır, yalnızca `startMin`/`endMin`
    kırpılır).
16. **Sunucu TEK THREAD'li.** `ThreadingHTTPServer` yaparsan sqlite3 bağlantısı
    "created in a thread can only be used in that same thread" hatası verir.
    Tek kullanıcıda eşzamanlılık kazandırmıyor; dönmek istersen
    `store.connect()`'e `check_same_thread=False` geçip erişimi kilitle.

### core/quickadd.py

17. **Ayrıştırma sırası: tarih -> süre -> saat aralığı -> tek saat**, her adım
    bir öncekini MASKELER. İkisi de gerçek hatadan çıktı: "15.10.2026" içindeki
    `15.10` saat sanılıyordu; "2 saat 14:00" içindeki `saat 14:00` deseni
    süreyle çakışıp saati başlıkta bırakıyordu.
18. **İşaretsiz çıplak sayı saat DEĞİL.** "3 ekim 10 kişilik toplantı"da 10'u
    saat sanmaktansa zamanı bulamamış olmayı tercih ediyoruz. Tanınmayan ifade
    `matched=""` ile bildirilir; arayüz kullanıcıyı uyarır.

### ics/exporter.py

19. **Dışa aktarmada saatli etkinlikler UTC'ye ÇEVRİLMEZ.** `TZID` + `VTIMEZONE`
    yazılır. UTC'ye çevirseydik tekrarlı etkinliğin duvar saati karşı tarafta
    DST geçişinde kayardı -- kendi düzelttiğimiz hatayı ihraç ederdik.
    Gidiş-dönüş testi bunu KASTEN farklı bir `default_tzid` ile ölçüyor.

### store/repo.py (arama)

20. **Arama katlaması dilbilimsel Türkçe küçültme DEĞİL.** `I`->`ı` doğru
    Türkçedir ama aramada yanlış davranış: "ALGORITMA" yazan "Algoritma"yı
    bulamaz. `_arama_anahtari` I ailesini (I/İ/ı/i) tek harfe indirir ve
    şapkaları düzler. Arama niyet eşleştirir, dil kuralı uygulamaz.

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

### Sürüm kontrolü

Proje bir git deposu. Değişikliğe başlamadan önce çalışma ağacının temiz
olduğundan emin ol (`git status`), işin bitince anlamlı bir commit bırak.
`.gitignore` hazır (`.venv/`, `__pycache__/`, `*.db`).

---

## 7. Sıradaki görev

**v1 kapsamı tamamlandı** (README §1). Yeni özellik eklemeden önce SOR --
kapsam dışı listesi bilinçli olarak kısa tutuluyor.

Bilinçli olarak yapılmamış olanlar README §9'da. Hatırlatıcı kararı hâlâ
açık (README §10): uygulama kapalıyken de çalışacaksa arka plan servisi
gerekir ve bu ayrı bir proje kadar iş -- kendi başına başlama.
