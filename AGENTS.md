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

**v1 kapsamı tamamlandı + Faz A–E (güvenlik/konfor) bitti.**

**383 test geçiyor.** Görev bitmeden önce hepsinin geçtiğini göstermeden
"tamamlandı" deme.

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

`pywebview` masaüstü penceresi için eklendi (kullanıcı onayıyla). Yanında
`pythonnet`, `clr_loader`, `cffi`, `bottle`, `proxy_tools` geliyor. Windows'un
KENDİ WebView2 bileşenini kullanıyor: uygulamaya tarayıcı motoru gömülmüyor,
bu yüzden `.exe` 15 MB'tan ~20 MB'a çıkıyor, 150 MB'a değil.

Yeni bağımlılık eklemeden önce gerekçelendir ve önce sor.

---

## 2. Değiştirilemez mimari kuralı

```
core/   saf mantık — DB, dosya, ekran bilmez
store/  kalıcılık (SQLite)
ics/    içe/dışa aktarma
ui/     arayüz (masaüstü penceresi + yerel http.server)
remind/ hatırlatıcı arka plan süreci
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

**v1 kapsamı + Faz A–E tamamlandı** (README §1, §10). Yeni özellik eklemeden
önce SOR -- kapsam dışı listesi bilinçli olarak kısa tutuluyor.

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

Hâlâ bilinçli olarak yapılmayanlar: kendi sağ tık menümüz, monitör başına DPI
farkındalığı, bildirimde kendi uygulama adı (PowerShell AUMID'i ödünç).
