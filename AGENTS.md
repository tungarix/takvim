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
| Hatırlatıcı (`remind/`) + sürükle-bırak | ✅ bitti |
| Boyutlandırma, tüm gün taşıma, ay açılır listesi | ✅ bitti |
| Masaüstü penceresi (`ui/pencere.py`, tarayıcı yerine WebView2) | ✅ bitti |
| Görevler (`Task`, 005 migration'ı, `/api/tasks`, `.ics` VTODO, `görev:`) | ✅ bitti (v1.5.0) |
| Senkron dosyası (`senkron/`, 006 migration'ı, Ayarlar → Telefonla senkron) | ✅ bitti (v1.8.0) |
| Wi-Fi eşleştirme (`senkron/wifi.py`, `/api/senkron/wifi/*`, QR) | ✅ bitti (v1.9.0) |
| Otomatik güncelleme (`guncelleme/`, `/api/guncelleme/*`) + Görünüm (tema) | ✅ yerelde bitti (v1.10.0 yayınlanacak) |

**v1 kapsamı tamamlandı + Faz A–E (güvenlik/konfor) bitti.**

**1154 test geçiyor** (1 Playwright testi atlanır; ayrıca CI'da her push/PR'da otomatik: bkz.
`.github/workflows/ci.yml`). Görev bitmeden önce hepsinin geçtiğini
göstermeden "tamamlandı" deme.

Ayrıntılı gerekçeler ve kapsam listesi: [README.md](README.md).

---

## 1. Ortam — önce burayı oku

Windows 11, **PowerShell 5.1**. Python 3.14.7, proje kökünde `.venv`.

> **`&&` PowerShell 5.1'de ÇALIŞMAZ.** `The token '&&' is not a valid statement
> separator in this version` hatası verir. Komutları `;` ile ayır.

Kullanıcı uygulamayı masaüstündeki **Takvim** kısayoluyla açıyor; kısayol
`dist/Takvim.exe` (PyInstaller ile paketlenmiş, Python gerektirmiyor)
dosyasını çalıştırıyor. Uygulama TARAYICIDA DEĞİL, kendi masaüstü
penceresinde açılıyor (pywebview + Windows'un WebView2 bileşeni). Gerçek veri
`%LOCALAPPDATA%/Takvim/takvim.db` içinde -- testlerde ASLA kullanma,
`:memory:` ya da `--demo` kullan. Aynı klasörde `pencere.json` (pencere
boyutu/konumu), `ornek.pid` ve `takvim.log` var.

Geliştirirken arayüzü tarayıcıda açmak istersen `--tarayici`, hiç ön yüz
istemiyorsan `--no-browser` bayrağı var.

Kodu değiştirdikten sonra `.exe` ESKİ KALIR; yeniden derlemeden
"kullanıcıda çalışıyor" deme:
`.venv\Scripts\python.exe -m PyInstaller takvim.spec --noconfirm --clean`

**Resmi sürüm akışı artık `v*` etiketi + `.github/workflows/release.yml`
üzerinden gidiyor:** sürümü `ui/surum.py`'de yükselt (TEK kaynak:
`pyproject.toml` onu okuyor, Ayarlar kutusu onu gösteriyor; `test_surum.py`
kurulu paketle karşılaştırıyor) → **güvenlik incelemesi:** önceki etiketten bu
yana olan farkı incele (`/security-review`), sonucu `guvenlik/incelemeler/vX.Y.Z.md`
olarak yaz ve commit et (sıra ve biçim: `guvenlik/incelemeler/README.md`) → etiket at
(`git tag vX.Y.Z && git push origin vX.Y.Z`) → workflow önce güvenlik kapısını
(`scripts/guvenlik_kapisi.py`) çalıştırır: kayıt yoksa, sonuç `geçti` değilse ya da
incelemeden sonra kod değiştiyse sürüm durur → testleri çalıştırıp `.exe`'yi derler, exe'yi duman testinden geçirir (`scripts/exe_duman.py`, kural 82), SHA256 + build provenance
attestation üretir → taslak (draft) bir release açar (exe + `SHA256SUMS.txt`
ekli) → notları elle yaz → yayımla. `workflow_dispatch` ile de tetiklenebilir,
o zaman release AÇMAZ, yalnızca artifact yükler (deneme/doğrulama içindir).
Yukarıdaki yerel derleme komutu hâlâ geçerli ama artık YALNIZCA geliştirirken
".exe güncel mi" diye sınamak için gerekli — resmi `.exe`'yi elle derleyip
release'e elle yükleme, workflow yapıyor.

```powershell
# testler
cd "C:\Users\Arda\Desktop\Aktenak\Projeler\takvim"; .\.venv\Scripts\python.exe -m pytest

# tek dosya
.\.venv\Scripts\python.exe -m pytest tests/test_store.py

# bağımlılık kurulumu
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Sistem Python'unu değil **her zaman `.venv\Scripts\python.exe`** kullan.
Özellikle `.exe` derlerken: sistem Python'unda `python-dateutil` yok, PyInstaller
bunu hata vermeden atlar ve exe açılışta `No module named 'dateutil'` ile ölür
(Ekim 2026'da yaşandı). `.venv` silinmişse önce
`python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"`,
sonra derle; `build\takvim\warn-takvim.txt` içinde "missing module named dateutil"
satırı olmamalı, ardından `scripts\exe_duman.py --exe dist\Takvim.exe` çalıştır.

### Bağımlılıklar

`python-dateutil` (RRULE), `pytest`, ve `tzdata`.

`tzdata` Windows'ta **zorunlu**: işletim sisteminin IANA veritabanı yok, stdlib
`zoneinfo` onsuz `ZoneInfoNotFoundError` veriyor. Kaldırma.

`icalendar` Faz 2 ile eklendi (`.ics` ayrıştırma).

`pywebview` masaüstü penceresi için eklendi (kullanıcı onayıyla). Yanında
`pythonnet`, `clr_loader`, `cffi`, `bottle`, `proxy_tools` geliyor. Windows'un
KENDİ WebView2 bileşenini kullanıyor: uygulamaya tarayıcı motoru gömülmüyor,
bu yüzden `.exe` 15 MB'tan ~20 MB'a çıkıyor, 150 MB'a değil.

`cryptography` Wi-Fi eşleştirme için eklendi (Arda onayıyla, v1.9.0). Gerekçe:
stdlib'de kendi imzalı sertifika ÜRETİMİ yok ve kendi X.509/ECDSA kodumuzu yazmak yanlış
olurdu. Yalnızca `senkron/wifi.py::sertifika_uret` içinde ve fonksiyonun İÇİNDEN import
edilir: açılış ve geri kalan modüller onsuz da yüklenir. Başka yerde kullanma (TLS, parola
saklama vb. için yeni bir ihtiyaç doğarsa önce sor).

QR kodu için `ui/static/qrcode.js` = **qrcode-generator 1.4.4** (Kazuhiko Arase, MIT; npm
paketinden DEĞİŞTİRİLMEDEN, sha256 `18ae399f81182bc9de916e9c77b195df20cc58d6f2d55a62b085a299f1bf1780`,
lisans başlığı dosyanın başında). Bağımlılık değil, tek dosya, satır içi betik yok. Elle QR
kodlayıcı YAZMA; kütüphaneyi güncellersen QR'ı bir çözücüyle yeniden doğrula (sınama yöntemi:
kural 101). Yalnız ASCII bayt kipinde kullanılıyor (bağlantı öyle); Unicode metin için kullanma.

Yeni bağımlılık eklemeden önce gerekçelendir ve önce sor.

---

## 2. Değiştirilemez mimari kuralı

```
core/   saf mantık — DB, dosya, ekran bilmez
store/  kalıcılık (SQLite)
ics/    içe/dışa aktarma
ui/     arayüz (masaüstü penceresi + yerel http.server)
remind/ hatırlatıcı arka plan süreci
senkron/ senkron dosyası (.takvimsync) dışa/içe aktarma
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

### core/models.py + arayüz

21. **`Occurrence.start_utc` ile `series_slot_utc` AYNI ŞEY DEĞİL.** Taşınmış
    bir örnekte `start_utc` yeni saati, `series_slot_utc` (yani
    `original_start_utc`) override kaydının ANAHTARINI gösterir. API'ye
    gönderilecek olan ikincisidir. Karıştırmak, mevcut override'ı güncellemek
    yerine seriye ait olmayan ikinci bir kayıt yaratır; `expand` onu hayalet
    sayıp atar ve kullanıcının değişikliği SESSİZCE kaybolur. Bu bir kez oldu.

### remind/

22. **Ölçüt "ne kadar geciktik" değil, "etkinlik hâlâ güncel mi".**
    `fire_at <= now` VE `occurrence.end > now`. Uygulama bir hafta kapalı
    kalıp açıldığında geçmiş bildirim seli olmasın, ama 5 dakika sonra
    başlayacak toplantı yine bildirilsin diye.
23. **`mark_fired` bildirimden ÖNCE çağrılır ve dönüş değeri KONTROL EDİLİR.**
    `due_reminders`'ın elemesi tek başına yetmez: iki `remind` süreci aynı anda
    çalışıyorsa ikisinin de anlık görüntüsü bayattır. İkinci hat
    `reminder_fired` UNIQUE kısıtı. Sıra da bilinçli: çöküşte nadiren bir
    bildirimi kaçırmak, kullanıcıyı bildirim döngüsüne sokmaktan yeğdir.
24. **Otomatik başlatma KURULMAZ.** Başlangıç klasörü kısayolu / Görev
    Zamanlayıcı kaydı sistem düzeyinde değişiklik. Komut README §9'da; kurmak
    kullanıcının kararı, kendi başına yapma.

25. **Konsol çıktısı `errors="replace"` ile yapılandırılıyor**
    (`core/console.py`). Windows konsolu cp1254; basılamayan tek bir karakter
    `UnicodeEncodeError` fırlatır ve uzun yaşayan hatırlatıcı döngüsünü
    öldürebilir. Bir etkinlik başlığı yüzünden hatırlatıcının susması kabul
    edilemez.
26. **İlk açılışta varsayılan takvim açılır** (`varsayilan_takvim_saglat`).
    Takvim yoksa hızlı ekleme reddediyor ve kullanıcı hiçbir şey yapamıyor.

27. **`takvim.spec` içindeki `datas` listesi kritik.** `ui/static/*` ve
    `store/migrations/*.sql` DOSYA olarak okunuyor; PyInstaller yalnızca
    import edilen modülleri topluyor. Yeni bir veri dosyası eklersen
    spec'e de ekle, yoksa `.exe` açılır ama boş sayfa gösterir.
28. **Tarayıcı soket BAĞLANDIKTAN sonra açılır** (`serve(..., on_ready=)`).
    Önce açılıyordu ve hızlı makinede "siteye ulaşılamıyor" çıkıyordu --
    son kullanıcı için bu "uygulama çalışmıyor" demek.
29. **Port sondası BAĞLANARAK yapılır, bind ile DEĞİL.** Windows'ta
    `SO_REUSEADDR`, Unix'in aksine dinlenen bir porta bind etmeye de izin
    veriyor; bind sondası dolu portu "boş" sanıyordu.

30. **Hızlı eklemede bulunma eki rakama BİTİŞİK olmalı** (`9da`, `14'te`).
    Araya boşluk izni veren desen, ardından gelen kelimenin ilk iki
    harfini ek sanıp yiyordu: "11:30 tasarım" -> başlık "sarım". Türkçede
    bu harflerle başlayan kelime bol (test, deneme, davet, tatil, dava).
    Uygulamayı ELLE denerken çıktı, testler görmemişti.
31. **Enter açıkça ele alınıyor** (`hizli-girdi` keydown -> `requestSubmit`).
    Tek girdili formda tarayıcının örtük submit davranışına güvenmiyoruz;
    yazıp Enter'a basınca hiçbir şey olmaması "uygulama bozuk" demek.
    Formda ayrıca görünür bir + düğmesi var.


### ui/pencere.py (masaüstü penceresi)

32. **`webview.start()` ANA THREAD'de çalışır ve pencere kapanana kadar
    DÖNMEZ.** Bu yüzden HTTP sunucusu arka plan thread'ine taşındı ve `Repo`
    `check_same_thread=False` ile açılıyor. Sunucu hâlâ TEK THREAD'li (kural
    16 duruyor); değişen tek şey o tek thread'in artık ana thread olmaması.
    `make_server()` doğrudan çağrılıyor ki pencere kapanınca `shutdown()`
    edilecek bir tutamak elimizde olsun.
33. **`webview.settings["ALLOW_DOWNLOADS"] = True` ŞART.** pywebview
    indirmeleri varsayılan olarak İPTAL ediyor. Kapalıyken "Dışa aktar"
    düğmesi hiçbir şey yapmıyor: ne dosya, ne hata, ne mesaj. Ölçüldü:
    açıkken Windows'un kendi "Farklı Kaydet" penceresi çıkıyor.
34. **`private_mode=True` ile `storage_path` BİRLİKTE VERİLMEZ.** O bileşimde
    pywebview verilen klasörü `shutil.rmtree` ile SİLİYOR. Kod bu yüzden
    ikisini birbirinin tersi olarak kuruyor.
35. **Pencere ölçüsü `closing` olayında okunur, `closed`'da DEĞİL.** `closed`
    anında pencere yok olmuş oluyor ve `pencere.width` hata veriyor. `closing`
    senkron çalışıyor; oradan `False` DÖNDÜRME, kapanmayı iptal eder.
36. **Küçültülmüş başlatma stiline karşı `shown` olayında `restore()`.**
    Kısayol süreci "küçültülmüş" stille başlatabiliyor (eski sürümde konsol
    göze batmasın diye böyle kurulmuştu) ve o stil uygulama penceresine de
    uygulanıyor: kullanıcı tıklıyor, ekranda hiçbir şey açılmıyor. Gerçekten
    yaşandı; kısayolu düzeltmek yetmez, kopyalanan kısayol aynı tuzağa düşer.
37. **WebView2 yoksa pywebview İSTİSNA ATMAZ**, sessizce eski Internet
    Explorer motoruna düşüp bembeyaz bir pencere gösterir. Bu yüzden
    `pencere_ac()` en başta kayıt defterinden sürümü soruyor ve yoksa kendisi
    `RuntimeError` fırlatıyor — ancak o zaman tarayıcı geri düşüşü çalışıyor.
38. **Geri düşüş yalnızca pencere GÖRÜNMEDEN önceki hatalar için.**
    `webview.start()` pencerenin tüm ömrü boyunca bloklar; onu saran
    `except` kapanış hatalarını da yakalar ve kullanıcı uygulamayı
    kapattıktan sonra karşısında bir tarayıcı sekmesi bulurdu.
39. **Tek örnek: mutex + SÜREÇ NUMARASI.** Pencereyi yalnızca başlıktan
    aramak yanlış pencereyi öne alıyor: veri klasörünün adı da "Takvim" ve
    Explorer'da açılınca pencere başlığı da tam olarak "Takvim" oluyor.

### ui/server.py (kaynak denetimi)

40. **Durum değiştiren isteklerde `Origin`/`Sec-Fetch-Site` denetimi.**
    Sunucu yalnızca 127.0.0.1'i dinliyor ama bu, kullanıcının tarayıcıda
    açtığı başka bir sayfanın buraya POST etmesini engellemiyor (CORS
    yalnızca YANITI okumayı engeller). Başlık hiç yoksa geçiyoruz: testler ve
    komut satırı araçları göndermiyor, saldırı yüzeyi tarayıcı.

### Paketleme

41. **pywebview'in WebView2 DLL'lerini ELLE EKLEME.** Paket kendi PyInstaller
    hook'unu getiriyor (`webview/__pyinstaller/hook-webview.py`) ve
    `webview/lib` + `webview/js` klasörlerini topluyor; elle eklemek mükerrer
    dosya üretir.
42. **`console=False` ile `stdout`/`stderr` None oluyor.** `takvim_app.py`
    bunları `%LOCALAPPDATA%/Takvim/takvim.log` dosyasına yönlendiriyor:
    penceresiz uygulamada kullanıcıya "ekranda ne yazıyordu" diye
    soramıyoruz. Aynı sebeple hatırlatıcının PowerShell toast'ı
    `CREATE_NO_WINDOW` ile çalışıyor — yoksa her bildirimde siyah bir konsol
    çakıyor.
43. **Arayüz dosyalarında `hidden` özniteliğine güvenirken CSS'e dikkat.**
    `.perde { display: flex }` tarayıcının `[hidden] { display: none }`
    kuralını EZİYOR; `.perde[hidden] { display: none }` olmadan soru kutusu
    uygulama açılırken ekranda duruyordu. Elle çalıştırınca görüldü.

### Etkinlik oluşturmanın İKİ yolu var

44. **`POST /api/events` iki biçim kabul ediyor ve karıştırılmamalı.**
    `{"text": ...}` hızlı ekleme: metin ayrıştırılır ve referans BUGÜNDÜR.
    `{"title", "date", "minutes"}` ızgarada boş saate tıklama: gün ve saat
    zaten belli, AYRIŞTIRMA YAPILMAZ. İkincisinde başlığı ayrıştırmak
    "3 ekim toplantısı" adlı etkinliği 3 Ekim'e kaçırırdı; oysa kullanıcı
    başka bir güne tıklamıştı.
45. **Hızlı ekleme kutusu ekrandaki haftayı DEĞİL bugünü referans alır.**
    Bilinçli: "yarın" her yerde yarın demek. Başka bir haftaya eklemenin yolu
    ızgaraya tıklamak ya da "haftaya salı" / "22 eylül" gibi açık ifade.
46. **Niteleyiciden sonra "hafta" isteğe bağlı** (`gelecek hafta salı`).
    Desende yokken ifade hiç tanınmıyor, tarih sessizce BU haftanın salısına
    düşüyor ve "gelecek hafta" başlıkta kalıyordu. Aynı yerde `onumuzdeki`
    (şapkasız) da var: `haftaya`/`gelecek` şapkasız çalışırken o çalışmıyordu.
47. **Klavye kısayolları ve panel düğmeleri AYNI fonksiyonu çağırır**
    (`basligiDegistir`, `ornegiSil`, `seriyiSil`). Ayrı yazılsalardı onay
    metni birinde güncellenip diğerinde unutulurdu; silme geri alınamaz.
48. **`Del`/`Backspace` yalnızca bir etkinlik SEÇİLİYKEN ve odak bir girdi
    kutusunda DEĞİLKEN çalışır.** Hızlı ekleme kutusunda yazarken Del harf
    silmeli, etkinlik değil. `Shift+Del` seriyi siler; ikisi de onay sorar --
    klavye silmeyi hızlandırır, geri alınamaz hâle getirmez.

### Silme, tekrar, takvim

49. **Tekrarsız etkinlikte "bu örneği sil" KAYDI SİLER.** Eskiden orada da
    iptal override'ı yazılıyordu: etkinlik ızgaradan kayboluyor ama aramada
    çıkıyor ve `.ics` dışa aktarmasına ETKİN yazılıyordu -- yedekten dönünce
    diriliyordu. Ayrımı `Occurrence.recurring` taşıyor.
50. **Tekrar kuralı KAPALI bir kümeden geliyor** (`TEKRAR_SECENEKLERI`),
    serbest RRULE metni değil. Tanınmayan değer sessizce "tekrarsız"a
    düşmüyor, 400 veriyor: sessizce tek seferlik olan bir ders programı hiç
    oluşturulmamış olandan kötü.
51. **"her salı"da yalnızca "her" yutulur**, gün adı tarih çözücüye kalır.
    Gün adını da yutarsak başlangıç bugüne düşer ve seri yanlış günde tekrarlar.
52. **Yeni etkinlik GÖRÜNÜR takvime yazılır.** `list_calendars()` gizlileri de
    veriyor ve ada göre sıralı; alfabede başa düşen gizli bir takvim varsayılan
    olunca "Eklendi" bildirimi çıkıp ekranda hiçbir şey belirmiyordu.
53. **Son takvim silinemez.** Takvimsiz veritabanında hızlı ekleme "önce bir
    takvim oluşturulmalı" diye reddediyor; kullanıcı çıkışsız kalır.
54. **Takvim rengi `#rrggbb` olarak DOĞRULANIR.** Değer doğrudan
    `style.background` içine yazılıyor; doğrulanmazsa oraya CSS enjekte edilir.
55. **Yedek migration'dan ÖNCE alınır** ve geçici ada yazılıp taşınır. Yarım
    bir "yedek" yedeksizlikten kötüdür: insan ona güvenir.
56. **Arayüzde tek bir `setInterval` var** (`canliBaslat`): şimdi çizgisini
    tazeliyor ve gün değişince yeniden çiziyor. Sürükleme ya da açık kutu
    varsa dokunmuyor, `durum.anchor`a da dokunmuyor.
57. **Seri bölmede COUNT kural düzeyinde sayılır.** Görünür örnek sayısı
    EXDATE düşülmüş hâl; sayaca onu yazmak dışlanmış örnek kadar eski tarafı
    kısa yazar ve örnek kaybolur. Doğrulama görünür listede, sayaç yalın
    RRULE'da (`_seriyi_bol`).
58. **Yeni seri desen üstünden başlar.** Bölme anı RDATE ise yeni DTSTART
    sonraki kural örneğidir (`next_rule_start`), kural metni değişmez.
    Desen dışına düşen DTSTART `INTERVAL` fazını/saat ızgarasını kaydırır ve
    sayaç kayan ızgarayı sayıp örnek düşürür. Bölme anının kendisi RDATE ile
    taşınır.
59. **Yedek temp dosyası süreç-özeldir** (`.gecici-<pid>`). Ön yüzle arka
    plan kopyası aynı gün yedek alırsa ortak temp birbirinin anlık
    görüntüsünü bozar. Bir saatten eski kalıntılar açılışta temizlenir;
    canlı yazana dokunulmaz.
60. **`--no-browser` tek-örnek kilidini ALMAZ.** Penceresiz arka plan
    kopyası (otomatik başlatma) kilidi tutarsa kısayol tıklaması "zaten
    açık" deyip kapanır — öne alınacak pencere olmadığı hâlde. Arka plan
    kopyaları birbirini engellemez (`reminder_fired` UNIQUE + `bos_port_bul`).
61. **Pencere arama gizli pencereyi de bulur.** Tepsideyken uygulama penceresi
    YOK; yerinde görünmez "Takvim" başlıklı boş bir form var (kural 83) ve
    ikinci tık onu bulmalı: yalnızca görünürleri listelemek tıkı boşa düşürür.
    Öne alırken önce `SW_SHOW`, sonra `SW_RESTORE` (tek komut iki hâli kapsamıyor).
62. **Yedekten dönüş dosya DEĞİŞTİRMEZ, `backup` API'siyle yazar.** Açık
    bağlantı varken `replace` Windows kilidine takılıyor ve eski kod hatayı
    yutup "geri yüklendi" diyordu. Başarısızlık `RuntimeError`, sahte
    başarı yok; aynı depo nesnesi dönüyor.
63. **Yapıştırma İKİ yoldan olur: tıklama VE Ctrl+V.** İlk sürümde yalnızca
    Ctrl+V vardı (imleci götür, tuşa bas) ama kullanıcı "tıkladığım yere
    yapışmıyor" dedi -- boş saate tıklamak hâlâ "Yeni etkinlik" kutusunu
    açıyordu. Düzeltme: `izgaraTik` artık en başta `durum.pano` doluysa
    doğrudan `panoyaYaz` çağırıyor, dialog araya girmiyor. Pano boşalana
    kadar HER tıklama yapıştırır -- "Yeni etkinlik" kutusuna dönmenin yolu
    `Escape`, o da panoyu temizliyor (`kisayollar.Escape`). `durum.imlecSaat`
    (Ctrl+V'nin hedefi) fare takibiyle dolu kalıyor, `ciz()`'in HER
    çağrısında sıfırlanıyor: aksi hâlde fare kıpırdamadan görünüm/tarih
    değişince (ör. bir saati hoverlayıp fareyi oynatmadan `a`ya basıp ay
    görünümüne geçmek) eski hedef sessizce geçerli sanılıp yanlış güne
    yapıştırma olurdu -- elle denendi, bulundu. Yapıştırılan kopya HER ZAMAN
    tekrarsız tek etkinlik, tüm gün etkinlikler kapsam dışı (süre birimi
    dakika/gün karışıklığı). `Ctrl+X` = kopyala + `ornegiSil` -- yeni bir
    silme yolu açmıyor, mevcut onay + geri alma aynen çalışıyor. `Ctrl+Z`
    yeni bir geri-alma mekanizması değil, görünen bildirimin "Geri al"
    düğmesini tıklıyor.
64. **Saat yüksekliği artık SABİT değil, `durum.saatYukseklik`.** Ctrl+Scroll
    (`izgaraYakinlastir`, `#izgara-kaydirma` üzerinde) 24–160px/saat arasında
    değiştiriyor; `ciz()` her çağrıda hem `gunlerKap.style.height`'ı hem CSS
    değişkeni `--saat-yukseklik`'i (`.saat-etiket` ondan okuyor) YENİDEN
    YAZIYOR -- ikisi elle senkron tutulan iki sabit değil, biri diğerini
    besliyor. Etkinlik blokları (`blokYap`, sürükleme, boyutlandırma) zaten
    YÜZDE ile konumlanıyordu, bu yüzden yükseklik değişince ekstra hesap
    gerekmedi. İmlecin altındaki saat sabit kalsın diye zoom öncesi/sonrası
    aynı oranı hedefleyen bir `scrollTop` hesabı var -- yoksa her tekerlek
    hareketinde ekran farklı bir saate zıplardı. `wheel` dinleyicisi
    `{ passive: false }`: `preventDefault` olmadan tarayıcı SAYFAYI
    yakınlaştırırdı, ızgarayı değil. Yalnızca `e.ctrlKey` true'yken
    devreye giriyor; düz kaydırma dokunulmadan tarayıcıya bırakılıyor.
65. **Güvenlik denetimi (TKV-API-001..005), hepsi ELLE ürettikten sonra
    düzeltildi.** Beş bulgu, `tests/test_guvenlik.py`:
    - **RRULE yoğunluk bütçesi** (`core/recurrence.py`, `_MAKS_ORNEK=10_000`).
      "Sınırlı" (`COUNT`/`UNTIL`) yoğun DEĞİL demek değil: `FREQ=SECONDLY` +
      büyük `COUNT`, `series_end()`'i (`list(_ruleset(event))`) dakikalarca
      kilitleyebiliyordu -- gerçek `COUNT=2_000_000` HTTP isteği 4.9 sn sürdü,
      düzeltmeden sonra 0.02 sn. `itertools.islice` `rruleset`'i TEMBEL
      tüketiyor (dateutil kaynağından doğrulandı: `_iter()` gerçek bir
      üreteç), yani sınırı aşan seri TAMAMEN üretilmeden yakalanıyor.
      `series_end()` REDDEDİYOR (`add_event`/import zamanı, veri hiç girmez);
      `expand()` her RENDER'da çağrıldığı için REDDETMİYOR, sessizce kırpıyor
      -- reddetseydi kalıcı kötü veri o ayı bir daha AÇILAMAZ yapardı. Ayrıca
      `rs.between()` pencereyi TAMAMEN üretip listeye topluyor (dateutil
      kaynağı: `gen = self` sonra tam tüketim); yerine `xafter()`+elle üst
      sınır (`_pencere_ornekleri`) TEMBEL ve `between()`'le birebir aynı
      sonucu veriyor (diferansiyel testle doğrulandı) -- sınırsız+yoğun bir
      seride ay görünümü 17 sn'den 0.06 sn'ye düştü.
    - **`ics/importer.py::_to_calendar`**: `str` girdi ASLA dosya yolu
      sayılmaz. İKİ KATMANDA düzeltildi: önce kendi `BEGIN:VCALENDAR`
      sezgimiz kaldırıldı, ama YETMEDİ -- `icalendar` paketinin KENDİ
      `from_ical`'ı da satır sonu taşımayan bir `str`'i `Path(st).is_file()`
      ile diskte arıyor (paket kaynağında elle doğrulandı). Asıl çözüm:
      `str`'i `.encode("utf-8")` ile `bytes`'a çevirmek -- paket yalnızca
      `str` girdiyi yol olarak deniyor, `bytes`'ı hiç. Uçtan uca kanıtlandı:
      diskteki bir dosyanın yolu POST gövdesi olarak gönderilince önce
      okunup `/api/export`'la sızıyordu, düzeltmeden sonra sızmıyor. `Path`
      açıkça geçilirse dosya okuma (testlerin kullandığı yol) DEĞİŞMEDİ.
    - **`ui/server.py::_statik`**: `startswith()` METİN öneki
      karşılaştırıyordu, dizin sınırı değil -- `ui/static` kökü `ui/static-x`
      gibi bir kardeş dizinle aynı öneki taşır. Gerçek bir kardeş dizin
      kurup `GET /../static-x/sir.txt` ile canlı sızdırıldı; `is_relative_to`
      düzeltti (segment sınırına saygılı).
    - **`ui/server.py::_icerik_uzunlugu`** (`_govde`+`_metin_govde` ortak):
      `Content-Length` negatifse `rfile.read(negatif)` bağlantı kapanana
      kadar okur; sunucu TEK THREAD'li olduğu için TEK bir istek TÜM
      istemcileri kilitliyordu -- ham soketle kanıtlandı, ardından gelen
      ilgisiz bir `GET` 12 sn zaman aşımına uğradı, düzeltmeden sonra
      0.03 sn. `0 <= uzunluk <= _MAKS_GOVDE` dışı her değer artık ANINDA
      400. `_govde` ayrıca sözlük OLMAYAN geçerli JSON'u (`[1,2,3]`) da
      reddediyor -- eskiden çağıranların `govde.get(...)`'i yakalanmayan
      `AttributeError` verirdi.
    - **`ui/__main__.py`**: `--host` loopback (127.0.0.1/::1/localhost)
      dışındaysa `--ag-erisimine-izin-ver` ŞART, yoksa `_ag_erisimi_dogrula`
      `ValueError` atar. API'nin hiçbir kimlik doğrulaması yok;
      `Origin`/`Sec-Fetch-Site` kontrolü CSRF'e karşı, ağdaki başka bir
      cihaza karşı DEĞİL -- bu bayrak olmadan `--host 0.0.0.0` ile açılan
      bir örneğe ağdaki HERKES erişip yazabilirdi.

### core/recurrence.py (kural kümesi önbelleği)

66. **Kural kümesi render'lar arasında SAKLANIYOR** (`_onbellekli_ruleset`,
    yalnızca `expand()` kullanıyor). Önceden her çizimde her seri DTSTART'tan
    baştan yürünüyordu ve süre serinin yaşıyla doğrusal büyüyordu (3000
    etkinlik + 2 yıllık 150 seride hafta 122 → 36 ms, ay 189 → 97 ms,
    ölçüldü). Dört kural, hepsinin mutasyonla doğrulanmış testi var
    (`tests/test_kural_onbellegi.py`):
    - **Anahtar, `_ruleset`'in okuduğu alanların TAMAMI** (`_kural_anahtari`:
      rrule, start_utc, tzid, rdate, exdate). `_ruleset`'e yeni bir alan
      okutursan anahtara da ekle; yoksa düzenlenen seri ESKİ hâliyle,
      sessizce çizilir.
    - **Thread başına ayrı önbellek** (`threading.local`). dateutil'in
      `_iter_cached`'i yineleme tükenince kilidini bırakmıyor ve kilit
      yeniden girişli değil (2.9.0.post0 kaynağından doğrulandı): sunucu ile
      hatırlatıcı thread'i aynı kümeyi paylaşsaydı biri sonsuza dek
      kilitlenebilirdi. Aynı sebeple bir kümede iki yineleyiciyi iç içe
      kullanma.
    - **İç önbelleği 5.000 örneği aşan küme saklanmaz** (`_buyuduyse_birak`).
      Yoğun bir seri (TKV-API-001) pencereye varana dek on binlerce örneği
      önbelleğe yazar; saklamak o kaynak tüketimini kalıcı yapardı. `_cache`
      dateutil'in özel alanı: bulunamazsa küme saklanmaz (hız kaybolur, sonuç
      bozulmaz) ve `test_ayni_seri_ikinci_renderda_yeniden_kurulmaz`
      kırmızıya döner.
    - **Thread başına en fazla 256 küme**, en uzun süre kullanılmayan düşer.

    Sonucun önbelleksiz hâlle birebir aynı olduğunu diferansiyel bir test
    ölçüyor (ileri/geri/uzağa gezinme, DST haftası, geçen yıldan taşınmış
    override, COUNT'u tükenen seri).

### Görevler (v1.5.0)

67. **Görev takvim etkinliği DEĞİL; saat blokta durur.** Plan üç hâl (plansız /
    gün / saat), ikisi birden olamaz (model + `CHECK`). Saat planlı görevin
    saati `tasks`'ta değil bağlı etkinlikte: bloğu sürüklemek tekrarsız
    etkinlikte de override yazıyor, etkinlik satırı DEĞİŞMİYOR. Bu yüzden
    görevin geçerli saatini `Repo.task_slots` okur (override'ı hesaba katar);
    `events.start_utc`'e bakmak sürüklenmiş bloğun eski saatini verir. Listeden
    yeniden planlama eski override'ı siler (hayalet kalmasın).
68. **Saatsiz görev ızgarada HİÇ görünmez**, tüm gün şeridi dahil. Kullanıcının
    kararı ("bugün yapabilirim" bir randevu değil). Görev bloğu tekrarlı ya da
    tüm gün OLAMAZ (`update_event`/`add_task` reddeder): tüm gün bloğu şeride
    düşüp bu kuralı çiğnerdi, tekrarlıda "tamamlandı" hangi örnek için olurdu.
69. **Başlık/not görev ↔ blok İKİ YÖNLÜ eşit** (`update_task` bloğu, `update_event`
    görevi günceller): panelde bloğun adı değişince liste ayrışmasın. Bloğu
    silmek görevi silmez (`ON DELETE SET NULL` → plansız), görevi silmek
    (`delete_task`) bloğu siler. Takvim silinirse blok gider, görev kalır.
70. **`update_task` yalnızca başlık/not yazar**; plan ve tamamlanma AYRI
    yöntemler (`plan_task_day/slot`, `clear_task_plan`, `set_task_done`): tüm
    `Task`'ı yazan bir güncelleme bayat nesneyle planı sessizce geri alırdı.
    `PATCH /api/tasks` gövdedeki HER ŞEYİ yazmadan önce doğrular; `POST` plan
    yazımı patlarsa görevi geri siler (yarım görev kalmaz).
71. **Hatırlatıcı süzgeci yalnızca daemon'da**: `all_reminders(exclude_done_tasks=
    True)`. Arayüz ÇAĞIRMAZ (tamamlanmış bloğun panelinde hatırlatıcılar
    görünmeli); görev yeniden açılırsa bildirim geri gelir.
72. **`.ics`**: `parse_ics` VTODO'yu ATLAR (eski sözleşme ve testi duruyor);
    görevleri `parse_ics_tasks` okur ve `import_ics` etkinliklerden SONRA
    yazar (blok önce kayıtlı olmalı). Saat planlı görevin VTODO'su bloğun
    VEVENT'ine `X-TAKVIM-BLOK-UID` ile bağlanır; bulunamaz/tekrarlı/dolu ise
    DUE'daki gün planına düşer (veri kaybı yok). `DUE:...Z` yerel güne
    çevrilir. Var olan UID'ye DOKUNULMAZ (görevlerde SEQUENCE yok). Test
    dosyası yazarken `write_text` Windows'ta `\r\n`'yi bozar: `write_bytes`.
73. **Hızlı ekleme `görev:` öneki iki nokta İSTER** ("görev toplantısı yarın
    10:00" bir etkinlik başlığı olabilir). Zaman ayrıştırması etkinlikteki
    AYNISI ama anlam farklı: zaman yok = plansız (etkinlikte tüm gün),
    yalnız tarih = gün planlı, saat = saat planlı. Tekrarlı ve başlıksız
    metin reddedilir. `POST /api/tasks`'ta `title` verilmişse `text` yok sayılır
    (AGENTS 44'ün görevdeki karşılığı).
74. **Arayüz**: listeden ızgaraya sürükleme HTML5 sürükle-bırak, ızgaradaki blok
    sürüklemesi işaretçi olayları: karışmasın diye ayrı. Karşılama perdesi
    görevi "bir şey eklendi" sayar (perde ızgarayı örtüyor, ilk görev
    sürüklenemezdi). Görev bloğu Ctrl+C/X/D'de reddedilir (`panoyaKopyala` tek
    kapı; kopya görevsiz etkinlik olurdu). Görev listesi <1040 px'te gizli.

### Yedekten dönüş, kaynak denetimi, hatırlatıcı (denetimden sonra)

75. **Yedekten dönüşte şema GÜNCELLENİR** (`store/yedek.py::yedekten_don`,
    `migrate(repo.conn)`). Yedek, kendinden sonra gelen bir migration'dan ÖNCEKİ
    şemada olabilir (AGENTS 55: yedek migration'dan önce alınır); uygulama
    yeniden başlamadan aynı bağlantıyla sürdüğü için güncellenmezse v1.5.0
    öncesi bir yedeğe dönüş görev listesini ve hatırlatıcıları "no such table:
    tasks" ile susturuyordu. Güncelleme başarısız olursa kenara alınan hâl geri
    yazılır ve `RuntimeError` fırlar.
76. **`PRAGMA quick_check` SONUCUNA bakılır, yalnızca istisnaya değil**
    (`_bozukluk`). SQLite bozukluğun çoğunu istisnayla değil SATIR olarak
    döndürür; yalnızca `try/except` ile bakan kod bozuk ama açılabilen bir
    yedeği sağlam sayıp canlı verinin üzerine yazıyordu. Testte bozulma
    kasten "çocuk sayfa numarasını kopyalama"yla yapılır: hücre işaretçilerini
    bozmak SQLite içinde belirsiz davranışa yol açar (aynı dosya kimi
    çalıştırmada istisna, kimisinde satır verir).
77. **`Host` başlığı TÜM isteklerde denetlenir** (`ui/server.py::host_gecerli_mi`,
    GET ve statik dosyalar dahil). `Origin`/`Sec-Fetch-Site` (kural 40) yalnızca
    YAZAN isteklere bakar; DNS rebinding ile saldırgan bir sayfa alan adını
    127.0.0.1'e çözdürüp `GET /api/export` ile tüm takvimi okuyabilirdi
    (tarayıcı o durumda `Host: saldirgan.example:PORT` gönderir). Loopback'e
    bağlıyken yalnızca `127.0.0.1:PORT`, `localhost:PORT`, `[::1]:PORT` (PORT =
    GERÇEK port) geçer; başlık hiç yoksa geçer; `--ag-erisimine-izin-ver` ile
    loopback DIŞI bağlıyken denetim atlanır. Yeni bir kaynak denetimi eklerken
    `_loopback_mi` ile `_LOOPBACK_ADRESLERI`'nin uyumunu bozma (testi var).
    Reddedilen isteğin gövdesi OKUNUP atılır (`_guvensizi_reddet`, `Host` ve
    `kaynak_guvensiz` için ortak): başlıkları görüp hemen 403 yazıp kapatmak,
    gövde ayrı/geç gelince TCP sıfırlamasıyla yanıtı ezer ve istemci 403 yerine
    bağlantı hatası görür (ölçüldü: 20/20; tam takımda `urllib` testleri
    kararsız düşüyordu). Reddeden yeni bir yol eklersen aynı yardımcıyı kullan.
78. **Hatırlatıcı dili HER TURDA çözülür, tetiklenme kayıtları budanır.**
    `run_forever`/`run_once` `dil`i metin ya da argümansız çağrılabilir olarak
    alır (`_dil_coz`); uygulama içi thread ve `python -m remind` ayar dosyasını
    okuyan çağrılabilir verir, böylece Ayarlar'dan dil değişince bildirim dili
    hemen uyar (eskiden `.exe`'de hep Türkçeydi). `Repo.prune_fired` kaydı
    YALNIZCA örneğin başlangıcı VE bitişi sınırdan eskiyse siler: yalnızca
    başlangıca bakmak, 40 gün süren bir etkinliğin kaydını silip her gün aynı
    bildirimi getirirdi. `run_forever` budamayı başta bir kez, sonra günde bir
    yapar (`_temizlik`); hatası döngüyü öldürmez.

### Bozuk veritabanı, arama, sürüm duman testi

79. **`yedek_al` bozuk veritabanından yedek ALMAZ** (`_bozukluk` en başta).
    Günde tek dosya olduğu için bozuk kopya o sabahın SAĞLAM yedeğinin üstüne
    yazılıyordu, budama da birkaç gün içinde eski sağlamları siliyordu. Paketli
    exe'de ölçüldü: bozuk ama açılabilen dosyayla uygulama hiçbir şey demeden
    açılıp bugünkü yedeği bozuyordu. "Şimdi yedekle" bu durumda "disk sorunu"
    değil `veritabani_bozuk` kodunu döndürür.
80. **Açılışta bozukluk `Repo.open`'DAN ÖNCE, salt okunur denetlenir**
    (`ui/kurtarma.py::bozuksa_kurtar`): açılış migration çalıştırıp hemen yedek
    alıyor, ikisi de bozuk dosyaya dokunmamalı. Kurallar, hepsinin testi
    (`tests/test_bozuk_veritabani.py`) mutasyonla doğrulandı:
    - **Kilit bozukluk SAYILMAZ** (`OperationalError` → None). Arka plan kopyası
      yazarken sağlam dosyayı kenara almak verinin yarısını yedekte bırakırdı.
    - **Soru yalnızca pencereli açılışta.** `--no-browser` (otomatik başlatma)
      kullanıcının karşısında olmayabilir: hiçbir şeye dokunmadan, kısayoldan
      açmasını söyleyen bir hatayla durur.
    - **Bozuk dosya SİLİNMEZ**, `bozuk-takvim-<zaman>.db` olarak kenara alınır
      (yedekten sonra girilmiş veri içinde olabilir). `-journal`/`-wal`/`-shm`
      eşleri de taşınır: yerinde kalan sıcak günlük yeni dosyaya "geri alma"
      diye uygulanıp onu bozardı.
    - **Yedek önce geçici ada kopyalanıp yeniden doğrulanır**, bozuğa ancak
      sonra dokunulur. En yeni yedeğe körü körüne güvenilmez
      (`son_saglam_yedek` her adayı denetler): bu koruma gelmeden önceki
      sürümler bozuk kopyayı yedeklemiş olabilir.
    - Diyaloglar tkinter (`takvim.spec` hiddenimports; pencere henüz yok,
      WebView2'ye dayanılamaz). Testlerde `sor`/`bildir` dışarıdan veriliyor.
81. **Arama görevleri de döndürür** (`/api/search` → `tasks`, `Repo.search_tasks`,
    `_arama_anahtari` ile aynı katlama). `results` (etkinlikler) eski sözleşme,
    değişmedi. Saat planlı görevin BLOĞU etkinlik sonuçlarından ayıklanır, yoksa
    aynı şey iki kez listelenirdi. Ön yüz bugünün görevine "Bugün" etiketini
    KENDİSİ ekler: `gorevMeta` bugünü yazmıyor (listede grup başlığı var), aramada
    boş kalıp "Plansız" sanılıyordu (önizlemede elle görüldü, testi var).
82. **Release, derlenen exe'yi `scripts/exe_duman.py` ile çalıştırır**, SHA256 ve
    attestation'dan ÖNCE: bozuk exe'ye özet üretilmesin. Geçici bir veritabanıyla
    açıp sürümü (etiket = `ui/surum.py` = exe'nin bildirdiği), paketlenmiş arayüz
    dosyalarını, şemayı, açılış yedeğini, yazma + `.ics` dışa aktarmayı ve
    gerçek `%LOCALAPPDATA%\Takvim\takvim.db`'ye dokunulmadığını sınar. Geçici DB
    BİR ÖNCEKİ şemada (içinde bir takvimle) önceden kurulur: boş dosya "yeni
    kurulum" sayılıp yedeklenmez; yedeğin migration'dan ÖNCE alındığı (yedek
    `user_version` = önceki şema) ve verinin yükseltmede korunduğu ancak böyle
    görünür. Tek dosyalık exe önyükleyici + asıl süreç: kapatırken `taskkill /T` (yalnızca
    önyükleyiciyi öldürmek portu açık bırakır). Ayarlar kutusundaki günlük yolu
    (`ui/server.py::gunluk_yolu`) `takvim_app._gunluk_yolu` ile aynı olmalı (testi
    var); oradan import edilmiyor, çünkü `takvim_app` günlüğü `ui`'den önce bağlıyor.
83. **Tepsiye inmek pencereyi GİZLEMEZ, KAPATIR** (`pencere_ac` döngüsü,
    `_tepside_bekle`). Gizli bir WebView2 ~170 MB tutuyordu (ölçüldü: tepside toplam
    241 → 72 MB); düşük bellek hedefi yalnızca 14 MB kazandırdı, `TrySuspendAsync`
    gizli formda hata verdi. Pencere kapanınca `webview.start()` döner, simgeyi
    `Application.Run()` pompalar; "Aç" döngüyü bitirir ve pencere yeniden
    kurulur (pywebview aynı süreçte ikinci `start`'ı destekliyor, denendi).
    `closing` kapanışı ASLA iptal etmez. İkinci kısayol tıkı için tepside görünmez
    (ekran dışı, 1x1, görev çubuğunda yok) "Takvim" başlıklı bir form tutulur;
    `pencereyi_one_al` onu gösterince `VisibleChanged`/`Activated` "Aç" sayılır.
    "Arka planda çalışıyor" balonu yalnızca ilk inişte (`Tepsi.kur(baloncuk=)`).

### Senkron dosyası (v1.8.0)

Biçim ve birleştirme kuralları `docs/senkron.md`'de (mobil uygulama aynı belgeyi
uyguluyor); aşağıdakiler masaüstü tarafının kararları, hepsinin testi mutasyonla
doğrulandı (`tests/test_senkron*.py`).

84. **Biçim tek kaynaktan: `docs/senkron.md`.** Kural/biçim değişince belge,
    `senkron/` ve uyum fixture'ı birlikte güncellenir: fixture
    (`docs/senkron-ornek.takvimsync` + `senkron-ornek-olusumlar.json`) elle
    yazılmaz, `scripts/senkron_ornek_uret.py`'den çıkar; `test_senkron_ornek.py`
    bayatlamayı yakalar. Dosya `version`'ı bilinenden büyükse içe aktarma reddeder.
85. **Mezar taşı ve `updated_at` TETİKLEYİCİDE (006), Repo kodunda değil.** Takvim/
    etkinlik/görev silmenin her yolu (takvimin CASCADE'i dahil) `silinenler`'e yazılır,
    aynı uid yeniden eklenince (geri alma, içe aktarma) kayıt silinir; override ve
    hatırlatıcı değişince etkinliğin `updated_at`'i 'şimdi' olur. Yeni bir silme yolu
    eklersen elle `INSERT INTO silinenler` YAZMA, tetikleyici zaten yakalıyor.
    `restore_last_deleted` `updated_at`'i şimdiye çeker (eski değer kalırsa diğer
    cihazdaki silme kazanır). `schema.sql`'deki tetikleyici metni migration'la AYNI
    olmalı (`test_migrations` tetikleyicileri de karşılaştırır). `calendars.uid`
    sütunu NULL'a açık (ALTER NOT NULL ekleyemez) ama `trg_takvim_ekle_doldur` her
    INSERT'e uid verir; Repo'yu atlayan INSERT (yedek testleri) uid'siz kalmaz.
86. **İçe aktarma TEK transaction'dır ve zaman damgasını DOSYADAKİ değere sabitler**
    (`senkron/ice.py`). Tetikleyiciler 'şimdi' yazdığı için her yazımdan SONRA kaydın
    `updated_at`'i, mezar taşının `deleted_at`'i dosyadakine çekilir; yoksa içe
    aktarılan kayıt 'şimdi' damgalı olup bir sonraki dosyada hep "yerelden yeni"
    görünürdü (idempotency kırılır, silme cihazlar arasında sonsuza yankılanır).
    `ice.py` ham SQL yazar (Repo `updated_at`'i/mezar taşını bilmiyor) ve
    `store.repo`'nun `_event_ekle`/`_event_guncelle`/`_tx` yardımcılarını kullanır:
    `series_end` bütçesi (kural 65) ve `sequence` aynı yerden gelsin.
87. **Dosya önce SAF ayrıştırılır; tek bozuk kayıt TÜM dosyayı reddeder**
    (`SenkronHatasi`: `senkron_bozuk` / `senkron_surum_yeni`, sunucuda kodlu 400).
    Kayıt kayıt atlamak yarım birleşmiş veritabanı demek, ikinci içe aktarma
    farklı sonuç verirdi. Reddedilenler: sabit genişlikli UTC dışı zaman, `#rrggbb`
    olmayan renk (54), tekrarlayan uid, hem `plan_day` hem `event_uid` dolu görev,
    çok yoğun RRULE (65), geçersiz tzid, ÇÖZÜLEMEYEN RRULE (sınırsız bozuk kural series_end'de
    çözülmüyordu; içeri girse `expand()` her görünümde patlardı), yalnız vekil karakter (UTF-8'e
    yazılamaz), 10 yıldan büyük hatırlatıcı (`MAKS_HATIRLATICI`; SQLite/timedelta taşması). Takvim adı
    kırpılır, rdate/exdate tekilleştirilir (mobil model de öyle; yoksa iki cihaz sonsuza dek ayrışır).
    Sayaçta tek istisna: takvimi yerelde olmayan
    etkinlik (yetim) `skipped`, dosya reddedilmez.
88. **Karşılaştırmalar KESİN (`>`), eşitlikte kayıt kalır.** Güncelleme yalnızca
    dosyadaki `updated_at` kesin yeniyse; silme yalnızca `deleted_at` kesin yeniyse;
    canlanma mezar taşı kayıttan kesin yeni DEĞİLSE (yani eşitlikte canlanır).
    docs/senkron.md eşitlikte "kayıt kalır" diyor ama canlanma için parantez içinde
    "`>`" yazıyor; veri kaybetmeme ilkesine göre eşitlikte canlanma seçildi (belge
    değiştirilmedi, mobil de aynısını yapmalı). Zamanlar saniye hassasiyetli: aynı
    saniyedeki düzenleme ve silmede düzenleme kazanır. Dosyada mezar taşı kayıttan
    yeniyse canlı kayıt hiç yazılmaz (ekle-sonra-sil yok).
89. **Hatırlatıcılar FARKLA güncellenir, override'lar sil-yeniden-ekle.** Hatırlatıcıyı
    silip yeniden eklemek `reminder_fired`'i CASCADE ile silerdi: değişmeyen
    hatırlatıcı bu hafta ötmüş örnekler için yeniden öterdi (kural 23).
90. **Silmeler sırası: görev → etkinlik → takvim**, hepsi görev/etkinlik/takvim
    yazımından SONRA. Etkinlikler kendi zamanlarıyla ayrı silinir, takvimin
    CASCADE'iyle gidenler takvimin `deleted_at`'ini taşır. Takvim silme, içindeki
    daha yeni değiştirilmiş etkinlikleri de götürür (belge böyle: karşılaştırma
    yalnızca takvim kaydına bakar). Silinen kaydın mezar taşı yerelde yoksa da
    taşınır (üçüncü cihaza ulaşsın); mezar taşları budanmaz.
91. **Takvim ad eşleşmesi `casefold()` + kırpma**: uid bulunamazsa aynı adlı yerel
    takvim uid'ini dosyadakine çevirerek benimsenir; dosyada kendi uid'iyle yer
    alan yerel takvim benimsenmez. `casefold` Türkçe İ/ı'yı eşlemez ("İş" ≠ "Iş").
92. **Görev bağlantısı savunmalı**: `event_uid` yerelde yoksa, tekrarlı/tüm gün bir
    etkinliği gösteriyorsa (68) ya da blok başka bir göreve bağlıysa (`UNIQUE`)
    görev plansıza döner, dosya reddedilmez.
93. **Arayüz**: Ayarlar'da `tur: "dugmeler"` alanı (`modalForm`); dışa aktarma `.ics`
    ile aynı yoldan (indirme, kural 33), içe aktarma gizli `#senkron-dosya`. Dosya
    seçici `await`'lerden ÖNCE açılır (kullanıcı etkileşimi eskirse tarayıcı
    reddeder). Önizleme (`dry_run`) YOK: yazmadan önce tek onay, sonra sayılı özet.
    Cihaz kimliği veri klasöründeki `cihaz.json`'da (`ayarlar.json`'a konmadı: ayar
    testleri sözlüğün tamamına kilitli). Cihaz saatleri farklıysa "son yazan"
    yanılabilir; belge bu sınırı kabul ediyor.
94. **Güvenilmeyen dosya (v1.8.0 incelemesi, `guvenlik/incelemeler/v1.8.0.md`)**, hepsinin
    testi mutasyonla doğrulandı:
    - **Uzak DTSTART'lı sık seri** (`core/recurrence.py::_ankraj`): dateutil pencereye kuralı
      DTSTART'tan tek tek yürüyerek varıyor; yıl 1'den `FREQ=HOURLY` görünüm başına 37 sn,
      geçen aydan `FREQ=SECONDLY` 46 sn tutuyordu (`_MAKS_ORNEK` yalnız DÖNEN örnekleri
      kırpıyor, pencere ÖNCESİNİ değil). Izgarası sabit birimli (saniye..hafta), COUNT'suz,
      tek kurallı serilerde `expand` ve `_is_instance` kuralı pencerenin 2 adım gerisindeki
      ızgara noktasından başlatır (tek kullanımlık küme, kural 66 önbelleğine girmez). Aylık/yıllık
      ve COUNT'lu kurallar DTSTART'tan yürümeye devam eder (ay/yıl uzunluğu, sayaç). Sonucun
      ankrajsızla birebir aynı olduğunu `tests/test_tekrar_ankraj.py` karşılaştırır.
    - **İmkânsız BYMONTH/BYMONTHDAY** (`series_end` → ValueError, her giriş yolu: `.ics`,
      senkron, UI): günlük ve daha sık frekansta dateutil 9999'a kadar gün gün tarıyordu.
      Yalnız pozitif gün numaraları denetlenir; başka imkânsız kombinasyonlar (BYYEARDAY...) hâlâ
      yavaş olabilir (kabul edilen risk).
    - **RecursionError** (`ice_aktar` ve `_govde`): yüzlerce iç içe `[` yakalanmıyordu. Etkinlik
      başına en çok `MAKS_HATIRLATICI_SAYISI` (1000) hatırlatıcı.
    - **`GET /api/senkron/disa` kaynak denetimi** (`_kaynak_guvenli`): GET'in yan etkisi var
      (`cihaz.json`); `Sec-Fetch-Site: cross-site` reddedilir, adres çubuğu (`none`) geçer.
    - **Açılışta yedek migration'dan ÖNCE** (`ui/__main__.py::depoyu_ac`): kural 55 böyle
      diyordu ama `Repo.open` migration'ı önce çalıştırıyordu. Şemasız (yeni) dosya yedeklenmez.

### Wi-Fi eşleştirme (v1.9.0)

Protokol ve tehdit modeli `docs/senkron-wifi.md`'de (bağlayıcı; çelişki çıkarsa belgeyi sessizce
düzeltme, sor). Hepsinin testi mutasyonla doğrulandı (`tests/test_senkron_wifi.py`,
`tests/test_ui_wifi.py`).

95. **Sunucu yalnız seçilen özel IPv4'e bağlanır, `0.0.0.0`'a ASLA** ve yalnız kısa ömürlüdür
    (en çok 180 sn, tek oturum). Özel aralık `ozel_ip_mi`'dir (10/8, 172.16/12, 192.168/16,
    169.254/16); `ipaddress.is_private` KULLANMA: loopback ve 100.64/10'u da özel sayar. Testlerde
    loopback için TEK kanal var: `WifiOturumu(test_ipleri=...)` / `_TakvimSunucu.wifi_ayar` (yalnız
    testler ve `scripts/wifi_sunucu_dene.py --test-ip`); komut satırı/ayar dosyası/ortam değişkeni
    üzerinden erişilemez ve belirsiz adres (`0.0.0.0`) orada da reddedilir. Üretim yolunu gevşetme.
96. **Sertifika ve özel anahtar diske yazılmaz, yazılmak ZORUNDA kalan an en kısa tutulur.**
    `ssl` belleğten yükleyemediği için anahtar RASTGELE PAROLAYLA şifreli PEM olarak geçici
    dosyaya yazılır, `load_cert_chain` döner dönmez `finally` ile silinir (yükleme patlasa da).
    Parola hiçbir yere yazılmaz. ECDSA P-256, SAN = IP, 1 gün; TLS ≥ 1.2. Parmak izi = DER'in
    SHA-256'sı base64url dolgusuz (QR'daki `f`).
97. **Kimlik HER ŞEYDEN ÖNCE** (`_Istek._isle`): yetkisiz istek yol/metot ne olursa olsun 401 alır
    (404/405 yalnız doğrulanmış isteğe), her başarısızlık KAYNAK IP başına sayılır: bir IP 5.'de o oturum
    boyunca engellenir (bağlantısı yanıtsız kapanır; oturum ÖLMEZ, ağdaki biri tokensız 5 istekle
    eşleştirmeyi bozamasın), tüm IP'lerden toplam 50'de oturum kapanır. Kimliğin
    doğrulandığı `_kimlikli` BAYRAĞIYLA izlenir, `Expect` başlığına güvenilmez: HTTP/1.0 +
    `Expect: 100-continue` `handle_expect_100`'e hiç uğramaz. `Expect` akışı da sayılır, 100
    Continue yetkisiz ya da 16 MiB üstü gövdeye verilmez. Karşılaştırma `hmac.compare_digest`.
98. **Gövde sınırı başlıkta uygulanır.** `Content-Length` zorunlu (411; chunked de 411), 16 MiB
    üstü gövde OKUNMADAN 413. Reddedilen küçük (≤1 MiB) gövde okunup atılır, yoksa kapanan
    bağlantıda TCP sıfırlaması yanıtı ezer (kural 77'deki tuzağın aynısı; PUT testi yakaladı).
    Dosya doğrulaması `ice.dogrula` = `ice_aktar`ın doğrulayıcısı (derinlik/boyut/kayıt
    kuralları AYNI, RecursionError → 400); doğrulanmadan arayüze HİÇBİR şey gitmez.
99. **Onay olmadan yazılmaz.** POST doğrulanır → oturum `onay_bekliyor` → arayüz Birleştir/Reddet
    → yalnız onayda `ice_aktar`. Karar POST'un ALINDIĞI andan 60 sn bekler (408); oturumun kapanış süresi onay bitene kadar uzar;
    ret 403, süre 408, ikinci eşzamanlı POST `dogrula`dan ÖNCE 409 (CPU yedirmez); `isleniyor`
    fazında İptal yok sayılır. Doğrulamanın CPU bütçesi: en çok 20.000 etkinlik, sınırlı serilerin
    toplam 500.000 örneği (`ice.MAKS_ETKINLIK/MAKS_TOPLAM_ORNEK`, dosya içe aktarmayla ortak). Onay penceresi "Reddet" odağıyla açılır
    (`wifiOnayKutusu`): yanlışlıkla Enter veri birleştirmesin. Başarılı/reddedilen/zaman aşımına
    uğrayan POST'tan sonra oturum kapanır; geçersiz dosya (400) kapatmaz.
100. **Thread düzeni.** Eşleştirme sunucusu thread'li (`TCPServer`+`ThreadingMixIn`; `HTTPServer`
    DEĞİL: `server_bind` Windows'ta saniyelerce ters DNS bekliyor), çünkü POST 60 sn onay
    bekliyor. Ana sunucunun tek-thread kuralı (16) bozulmuyor: her istek `depo_ac()` ile KENDİ
    sqlite bağlantısını açıp kapatır (bellek DB'sinde ortak bağlantı, yalnız geliştirme). TLS
    el sıkışması kabul döngüsünde değil istek thread'inde (takılan istemci diğerlerini tutmasın);
    eşzamanlı bağlantı en çok 8, kaynak IP başına 2; kimliksiz bağlantının TOPLAM ömrü 10 sn (TLS dahil;
    soket-başı zaman aşımı damlatan istemciyi kesmez), kimlikli POST gövdesi toplam 30 sn
    (`_Istek._sayac_kur`). Geçici PEM silinemezse (virüs tarayıcısı) yutulur, çıkışta silinir. Yeni `baslat` eski oturumu kapatır (token'ı ölür); uygulama
    kapanışında `_TakvimSunucu.server_close` açık oturumu temizler. `bitir` önce token'ı öldürür
    (`faz="bitti"`), dinleyiciyi hemen arkasından kapatır.
101. **Günlük ve arayüz.** Günlük yalnız "oturum açıldı/kapandı, sonuç, istek sayısı" (`print`);
    token, IP, port, dosya içeriği ve istisna iletisi YAZILMAZ (`handle_error` yalnız sayar).
    Bağlantı (içinde token var) YALNIZ `POST /api/senkron/wifi/baslat` yanıtında döner; `durum`
    yoklaması dönmez. Uçlar yazan uçlarla aynı `Host` + `Origin`/`Sec-Fetch-Site` korumalarında,
    `durum` GET'i de dahil. QR her zaman siyah-beyaz (koyu temada da; temayı izleyen QR okunmaz),
    4 modül sessiz bölge, SVG DOM ile kurulur (satır içi betik/`innerHTML` yok). QR doğrulaması:
    tarayıcıda çizilen SVG → canvas → PNG → `zxing-cpp` (geçici venv) ile çözülüp
    bağlantı metniyle karşılaştırıldı (en kötü durum: 374 karakter, 85x85 modül, de çözüldü;
    projeye bağımlılık eklenmedi).

### Otomatik güncelleme (v1.10.0)

Sözleşme `docs/guncelleme.md`'de; kod `guncelleme/` paketinde (`saf` ağsız mantık, `ag` GitHub istemcisi,
`kurulum` doğrulama + exe değiştirme, `hizmet` durum). `core/` bu paketi import etmez. Hepsinin testi
mutasyonla doğrulandı (`tests/test_guncelleme.py`, `tests/test_ui_guncelleme.py`); paketli exe ile gerçek
değişim `scripts/exe_guncelleme_dene.py` ile elle denenir.

102. **Kullanıcı seçmeden ağ isteği YOK.** `ayarlar.json` → `guncelleme_denetimi`: `None` (hiç sorulmadı) |
    bool. Arka plan denetimi (`ui/__main__.py::_guncelleme_dongusu`) yalnız `True` iken ve en çok günde
    bir kez çalışır (`arka_plan_adimi`); ayar HER turda dosyadan okunur. İstisna "Şimdi denetle"
    (`POST /api/guncelleme/denetle`): kullanıcının kendi tıkı. Elle yazılmış `"evet"` seçim SAYILMAZ.
    Yeni bir yerde GitHub'a istek atacaksan bu kuralı ve testlerini bozma. `--no-browser` kopyası denetim
    yapmaz (yalnız pencereli açılış): iki süreç aynı sorguyu atmasın. İlk açılış rıza kutusunda odak
    "Hayır"dadır ve `oku` odaktaki öğeye bakar ("Evet" yalnız kendi düğmesiyle; odak dışı Enter = karar yok):
    bunu BASİTLEŞTİRME, yazarken beliren kutu Enter'la ağ izni vermesin. Bellek veritabanında soru çıkmaz
    (`guncelleme_denetimi: false` döner). Bu davranışın tarayıcı testi `tests/test_frontend_smoke.py`'de.
103. **Adres denetimi tek yerde** (`saf.adres_uygun`): yalnız https + `IZINLI_SUNUCULAR`; `github.com`'da yol
    bu deponun release'i olmalı; yönlendirmeler (`ag._Yonlendirme`) ve diskten okunan saklı teklif de aynı
    denetimden geçer. Yeni sunucu EKLEME; testler için `ek_sunucular` (yalnız loopback, üretimde boş).
104. **Dosya adı sözleşmesi sabit**: `Takvim.exe` + `SHA256SUMS.txt` (`saf.EXE_ADI/OZET_ADI`). Başka adlı varlık
    sessizce kabul edilmez; aynı adlı ikinci varlık yok sayılır; özet dosyasında aynı ad iki kez geçerse
    belirsiz sayılıp kurulum iptal olur. Yayın hattında bu adları değiştirirsen güncelleyici KIRILIR.
105. **Önce doğrula, sonra yerleştir**: indirme `.part`'a, boyut bildirilene EŞİT olmalı (fazlası okunmaz:
    disk doldurma), SHA-256 `SHA256SUMS.txt`'le eşleşmeli, yoksa dosya silinir. Onaydan ÖNCE indirme yok.
    `kur` yalnızca denetimin bulduğu sürümü kurar (arayüzdeki bayat sürüm reddedilir).
106. **Çalışan exe'yi değiştirme** (`kurulum.tamamla`): tek dosyalı exe'de İKİ süreç var (önyükleyici + asıl),
    süreç numarasını beklemek YETMEZ: taşıma `PermissionError`da süre sınırına kadar yeniden denenir.
    Yeni exe `--sha256` (beklenen özet, zorunlu) ile başlar ve eskiye dokunmadan önce kendini bununla doğrular;
    uyuşmazlıkta ESKİ SÜRECİ İKİNCİ KEZ AÇMAZ (hâlâ yaşıyor olabilir). Sıra: eski → `Takvim.eski.exe`, yeni → `.yeni` geçici adına kopya + SHA-256 sağlaması → eski yola
    `os.replace`. Herhangi bir adım patlarsa eski dosya geri konur ve ESKİ sürüm açılır; kilit hiç
    açılmazsa eski dosyaya hiç dokunulmaz. `--guncelle-tamamla` `takvim_app.py`'de normal açılıştan ÖNCE
    ele alınır (tek-örnek kilidi/veritabanı açılmadan). Yeni süreç `PYINSTALLER_RESET_ENVIRONMENT=1` ile
    başlar. Windows çalışan exe'yi YENİDEN ADLANDIRMAYA izin verir, üzerine yazmaya/silmeye vermez
    (`exe_guncelleme_dene.py` paketli exe'de ölçtü): akış bu yüzden rename tabanlı, yeniden deneme döngüsü
    antivirüs/önyükleyici kilidi içindir. Yazılabilir olmayan konumda (`kurulabilir_mi`) otomatik kurulum yok, elle indirme gösterilir.
107. **Uygulama kapanışı sert** (`_uygulamayi_kapat`: yanıt yazıldıktan 0.5 sn sonra `os._exit(0)`): tepsiye
    küçültme açıkken `webview.destroy()` süreci bitirmez ve yeni exe eskisini boşuna beklerdi. SQLite her
    işlemi kendi yazıyor, veri kaybı yok.
108. **Tema**: `ayarlar.json` → `tema` (`koyu`|`acik`|`sistem`), `ui/static/tema.js` `<html data-tema>`'yı
    açılışta (localStorage önbelleğiyle, göz kırpmasın diye) koyar; renkler yalnız `style.css` jetonlarında
    (`:root` koyu, `:root[data-tema="acik"]` açık). Yeni renk eklerken İKİ temada da tanımla; açık temada
    vurgu bilerek `#c2331d` (mockup'taki `#e5412a` AA'nın altında, hesap CSS yorumunda).

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
  (Bellekteki kural kümesi önbelleği ayrı bir şey: ölçüldükten sonra eklendi,
  DB'ye yazmıyor, sonucu değiştirmiyor — kural 66.)
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
  (`test_tek_ornek_iptali`). **Kod tanımlayıcıları da fiilen Türkçe**
  (`pencere_ac`, `sanal_ekran`, `monitorde_mi`, `kur`, `kaldir`,
  `kurulu_mu`, `ciz`, `hizliEkleBaslat`…) — bu satır önceden "İngilizce"
  diyordu, gerçek kod hiçbir zaman öyle olmadı. Yeni bir tanımlayıcı
  eklerken dokunduğun dosyadaki mevcut adlandırma desenini taklit et.
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
- Bir betik/dosya içine ters eğik çizgi (`\r\n` gibi) yazacaksan araç katmanı çift
  ters eğik çizgiyi TEKE indirebiliyor (Python kaynağında gerçek CR/LF olarak
  çıkıyor, string kırılıyor). Betiği Write ile dosyaya yaz ve gerekirse
  `chr(92)` kullan; sonucu `repr` ile bayt düzeyinde doğrula.

### Sürüm kontrolü

Proje bir git deposu. Değişikliğe başlamadan önce çalışma ağacının temiz
olduğundan emin ol (`git status`), işin bitince anlamlı bir commit bırak.
`.gitignore` hazır (`.venv/`, `__pycache__/`, `*.db`).

---

## 7. Sıradaki görev

**v1 kapsamı + Faz A–E + v1.0.1 + v1.0.2 + v1.1.0 + v1.2.0 + v1.3.0 + v1.4.0 + v1.4.1
+ v1.5.0 + v1.6.0 + v1.7.0 + v1.7.1 + v1.7.2 + v1.8.0 + v1.9.0 tamamlandı** (README §1, §10, [CHANGELOG.md](CHANGELOG.md)). Yeni özellik
eklemeden önce SOR -- kapsam dışı listesi bilinçli olarak kısa tutuluyor.

v1.9.0'da bitenler (ayrıntı CHANGELOG.md'de; release SHA256: yayınlanınca doldurulacak):
**Wi-Fi eşleştirme** (kural 95-101, `docs/senkron-wifi.md`,
`guvenlik/incelemeler/v1.9.0.md`): `senkron/wifi.py`, `/api/senkron/wifi/*`, Ayarlar → "Wi-Fi ile
eşleştir" (QR + bağlantı + geri sayım + masaüstü onayı), `scripts/wifi_sunucu_dene.py` (mobil
istemciyi uçtan uca denemek için; exe'ye girmez). Test sayısı 926 → 1045 (güvenlik incelemesi düzeltmeleri dahil). Paketli exe duman
testi artık eşleştirmeyi gerçekten başlatıp TLS parmak izini okuyor (özel ağ yoksa atlar):
`cryptography` paketlemede eksik kalırsa hata ilk kullanıcıda değil burada görünür. exe boyutu
16,96 → 20,75 MB (cryptography'nin yerel kütüphaneleri; not: pywebview'in `ssl=True` yolu
`cryptography`yi zaten isteğe bağlı import ediyor, venv'de kuruluysa PyInstaller onu her hâlükârda
toplar). ELLE DENENMEYENLER: gerçek telefonla Wi-Fi eşleştirme, gerçek Windows güvenlik duvarı istemi
(testler loopback üstünde; duman testi kendi IP'sine bağlanıyor, güvenlik duvarını tetiklemez) ve
paketli exe'de WebView2 dosya seçici (senkron dosyası oluştur/aç); ilk gerçek kullanımda dene.
Sürüm güvenlik incelemesinin düzeltmeleri kural 95-101'de; kabul edilen riskler kayıtta
(varsayılan yol VPN ise yanlış IP, yerel süreçlerin başlıksız API çağrısı, CSP yokluğu).

v1.8.0'da bitenler (ayrıntı CHANGELOG.md'de; release SHA256: `fc1572c5…1f7d03`, resmi exe duman testinden, hash ve attestation'dan geçti):
**Telefonla senkron dosyası** (kural 84-93, `docs/senkron.md`): `senkron/` paketi,
`006_senkron.sql` (takvim `uid`/`updated_at`, `silinenler` mezar taşları, tetikleyiciler),
Ayarlar → "Telefonla senkron" (oluştur / aç), `GET /api/senkron/disa` +
`POST /api/senkron/ice`, mobil için uyum fixture'ı (`docs/senkron-ornek*`,
`scripts/senkron_ornek_uret.py`) ve sürüm güvenlik incelemesinin düzeltmeleri (kural 94).
Test sayısı 872 → 926. Paketli exe'de senkron dosyası oluştur/aç ELLE denenmedi (WebView2
indirme + dosya seçici bu ortamda otomatik denenemedi); ilk gerçek kullanımda dene.

v1.7.2'de bitenler (ayrıntı CHANGELOG.md'de):

- **Tasarım geçişi**: tek ikon seti (satır içi SVG), üç yazı boyutu (11/13/20), kenar
  çubuğu boşlukları; davranış değişmedi.

v1.7.1'de bitenler (ayrıntı CHANGELOG.md'de):

- **Tepside az bellek** (kural 83): tepsiye inmek pencereyi ve WebView2'yi kapatıyor,
  simgeden açınca yeniden kuruluyor; tepside toplam ~246 → ~78 MB (paketli exe'de ölçüldü).

v1.7.0'da bitenler (ayrıntı CHANGELOG.md'de):

- **Aramada görev durum filtresi** (Tüm görevler / Açık / Tamamlanan, `/api/search?gorev=`).

v1.6.0'da bitenler (ayrıntı CHANGELOG.md'de):

- **Bozuk veritabanı koruması + açılışta kurtarma** (kural 79-80), **arama
  görevleri de buluyor** (81), **release exe duman testi** ve Ayarlar'da günlük
  yolu (82), sürüm güvenlik kapısı, yedekten dönüşte şema, `Host` denetimi,
  hatırlatıcı dili (75-78). Test sayısı 623 → 775.

v1.5.0'da bitenler (ayrıntı CHANGELOG.md'de):

- **Görevler** (kural 67-74, README §10): `core.Task`, `005_gorevler.sql`, Repo
  yöntemleri, `/api/tasks`, kenar çubuğu listesi + form + ızgarada blok +
  sürükle-bırak, hızlı ekleme `görev:`, `.ics` VTODO, hatırlatıcı süzgeci.
  Kullanıcı kararı: saatsiz görev ızgarada görünmez; "bu saatlerde" ya da "bugün
  yapabilirim" seçenekleri. Test sayısı 469 → 623.

v1.4.1'de bitenler (ayrıntı CHANGELOG.md'de):

- **Tekrarlı seri kural kümesi önbelleği** (kural 66): hafta görünümü
  122 → 36 ms (ağır test verisi), sonuç birebir aynı.
- **Sürüm ⚙ Ayarlar'da görünüyor**; tek kaynağı `ui/surum.py` (bkz. §1
  sürüm akışı).
- CI/release action'ları Node 24 sürümlerine alındı. Test sayısı 457 → 469.

v1.4.0'da bitenler (ayrıntı CHANGELOG.md'de):

- **Türkçe / İngilizce arayüz dili** (⚙ Ayarlar → Dil, varsayılan Türkçe).
  Yeni `ui/static/i18n.js` (`TR`/`EN`, 225 anahtar), `app.js`te `t()`,
  gün/ay adları + hatırlatıcı toast'ı dahil sunucu tarafı yerelleştirme.
  Bilinen bilinçli sınır: **hızlı ekleme kutusu İngilizce modda da Türkçe
  cümle bekliyor** (`core/quickadd.py` değişmedi, seçenek 1) — placeholder
  metninde açıkça yazıyor. Yeni görünen metin eklerken `i18n.js`teki İKİ
  dile de yaz; TR değerler eski metinle birebir aynı olmalı (varsayılan dil
  `tr`, eski testler buna kilitli). Sunucu hatalarında `error` alanını
  DEĞİŞTİRME (eski sözleşme), kodu `_KodluHata`/`_hata_esle` ile ekle.
- Ayarlar kutusundaki select'lerin sabit 32px yüksekliği kaldırıldı
  (metin taşıyordu).
- Test sayısı 436 → 457.

v1.3.0'da bitenler (ayrıntı CHANGELOG.md'de):

- **Monitör başına DPI farkındalığı** (`ui/pencere.py`
  `dpi_farkindaligini_ac`).
- **Ön yüz erişilebilirlik düzeltmeleri**: ay görünümü/gün listesi/arama
  sonuçları artık klavyeyle de açılabiliyor (`<div onclick>` → `<button>`),
  modal'da Tab odağı kaçmıyor, bildirim kutusu `aria-live`.
- **Köşe yarıçapı 0 → 6px** (`ui/static/style.css` `--yaricap`, tek merkezi
  değişken).
- Ön yüz duman testleri 4 → 15 (`tests/test_frontend_smoke.py`); toplam
  436 test.

v1.2.0'da bitenler (ayrıntı CHANGELOG.md'de):

- **Çakışma onay kutusu**: hızlı eklemede çakışma artık kaydetmeden ÖNCE
  düzenlenebilir bir onay kutusu açıyor (Yine de kaydet / Saati değiştir
  / Vazgeç) -- Takvim Arayuz.pdf §1f. Yeni `POST /api/events/parse`
  (DB'ye dokunmadan önizleme, import'taki `dry_run` ile aynı fikir).
- **Yedekler penceresi**: gerçek liste (tarih/sayı/boyut) + "Şimdi
  yedekle" (`POST /api/backups`) + "Klasörü aç" (`POST /api/backups/
  open`, `os.startfile`) -- Takvim Arayuz.pdf §1h.
- **CI** (`.github/workflows/ci.yml`): her push/PR'da ruff + mypy +
  pytest + `app.js` sözdizimi, ayrı bir işte Playwright duman testleri.
- **Ön yüzün ilk otomatik testleri** (`tests/test_frontend_smoke.py`,
  `pytest-playwright`, ayrı `test-ui` extra'sında).

v1.1.0'da bitenler (ayrıntı CHANGELOG.md'de):

- **Arayüz baştan tasarlandı** (Claude Design spesifikasyonuna göre): üst
  çubuktaki ikincil eylemler kenar çubuğuna taşındı (asıl dar-pencere
  taşma sorununu bu çözdü), mini ay takvimi + ilk açılış ekranı eklendi,
  renk paleti WCAG AA'ya çekildi.
- **5 güvenlik bulgusu düzeltildi** (harici denetim, TKV-API-001..005):
  RRULE DoS, içe aktarmada dosya yolu okuma, statik dosya yol geçişi, tek
  istekle sunucu kilitlenmesi, ağa açık kimlik doğrulamasız API
  (`tests/test_guvenlik.py`, 16 test).
- Yapıştırma (`Ctrl+V`/tıkla) artık tek seferlik; önceden pano
  temizlenene kadar her tıklama aynı etkinliği yapıştırıyordu.

v1.0.1'de bitenler (ayrıntı CHANGELOG.md'de):

- **Klavye panosu**: `Ctrl+C/X/V/D/Z` (kopyala/kes/yapıştır/çoğalt/son
  işlemi geri al); kopyaladıktan sonra boş saate tıklamak da yapıştırır.
- **`Ctrl`+tekerlek ile ızgara yakınlaştırma** (24–160px/saat, imleç sabit
  kalır); sürükleme yuvarlaması 15dk'dan 5dk'ya indirildi.
- Seri bölme, otomatik başlatma kısayolu ve sessiz yedek geri yükleme
  hatalarının düzeltilmesi (CHANGELOG.md [1.0.1]).

v1.0.2'de bitenler (ayrıntı CHANGELOG.md'de):

- Tepsi ikonu her kapanışta yeniden kuruluyordu, eskisi Dispose
  edilmiyordu (`ui/pencere.py`, `kapanirken`); artık varsa yeniden
  kullanılıyor.
- `onceki-takvim-*.db` (yedekten dönüş öncesi kenara alınan anlık
  görüntüler) `takvim-*.db` deseninin dışında kaldığı için hiç
  budanmıyordu; kendi penceresi eklendi (`ONCEKI_SAKLANAN`).

Faz A–E'de bitenler (detay README §10'da):

- **Sistem tepsisi simgesi** (`ui/tepsi.py`, pythonnet `NotifyIcon`, yeni
  bağımlılık yok). Varsayılan KAPALI; `ui/ayarlar.py` + ⚙ kutusundan açılıyor.
- **`.ics` içe aktarma arayüzü** (önizlemeli, `?dry_run=1`) + **çakışma
  uyarısı** (`GET /api/conflicts`, engellemez).
- **Yedek geri yükleme** (`POST /api/backups/restore`) + **seri silmede
  anlık görüntü/geri alma** (`004_silinen_seriler.sql`).
- **"Bundan sonrasını değiştir"** (`Repo.split_series`, THISANDFUTURE).
- **Lint/tip**: `ruff` + `mypy` (`core/` + `store/` katı); istisnalar
  `pyproject.toml`'da gerekçeli.

Hâlâ bilinçli olarak yapılmayanlar: kendi sağ tık menümüz, bildirimde kendi
uygulama adı (PowerShell AUMID'i ödünç — Başlat menüsü kaydı + kayıt defteri
yazmak gerektirir, sistem düzeyi değişiklik, kullanıcı onayı bekliyor).
Monitör başına DPI farkındalığı artık AÇIK (`ui/pencere.py`
`dpi_farkindaligini_ac`, `pencere_ac()`in en başında çağrılıyor).

Düşünülüp ertelenenler: `.exe` imzasız (SmartScreen uyarısı) — ücretli kod
imzalama sertifikası gerektiriyor, bilinçli/gelecekteki bir yatırım kararı.
CI artık var (`.github/workflows/ci.yml`: ruff + mypy + pytest + ayrı
`test-ui` işinde Playwright duman testleri) ve ön yüzün ilk otomatik
testleri de var (`tests/test_frontend_smoke.py`, v1.2.0) — bu ikisi daha
önce burada "yok" diye listeleniyordu, o satır güncel değildi.
