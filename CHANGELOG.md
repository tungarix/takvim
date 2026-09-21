# Değişim günlüğü

Bu proje [Keep a Changelog](https://keepachangelog.com/) biçimini ve
[Semantic Versioning](https://semver.org/)'ı takip etmeye çalışır. Sürümler
GitHub [Releases](https://github.com/tungarix/takvim/releases) sayfasında
`Takvim.exe` ekiyle yayınlanır.

## [Yayınlanmamış]

### Eklendi
- **Monitör başına (per-monitor) DPI farkındalığı** (`ui/pencere.py`
  `dpi_farkindaligini_ac`, `pencere_ac()`in en başında çağrılıyor) — pywebview
  bunu kendisi ayarlamıyordu, çoklu monitör/farklı ölçekli (%125, %150 vb.)
  kurulumlarda pencere bulanık görünebiliyor ya da bu dosyanın piksel
  matematiği yanlış ölçekte çalışabiliyordu. Windows 10 1703+'ta modern
  `SetProcessDpiAwarenessContext`, olmayan sistemlerde `SetProcessDpiAwareness`
  fallback'i ile (`tests/test_ui_pencere.py`, toplam 436 test).
- Ön yüz duman testlerine 4 yeni senaryo: silme + bildirimden geri alma,
  tekrarlı seride "Bu örneği sil" / "Seriyi tamamen sil" ikisinin birden
  görünmesi, arama kutusunun yeni oluşturulan etkinliği bulması, panelin
  tıklanan etkinliğin gerçek başlık/saatini göstermesi (`tests/
  test_frontend_smoke.py`, toplam 8 duman testi).
- Ön yüz duman testlerine 6 senaryo daha: ay görünümündeki etkinlik bloğunun
  ve "+N daha" düğmesinin klavyeyle açılması, gün listesi satırına tıklamanın
  doğru etkinliği açması, `g`/`h`/`a` görünüm kısayolları, boş bir saate
  tıklayarak yapıştırma (Ctrl+V basmadan), arama şeridinin Escape ile
  kapanması (`tests/test_frontend_smoke.py`, toplam 14 duman testi →
  434 test).
- Ön yüz duman testlerine 1 senaryo daha: arama sonucuna klavyeyle
  (Tab + Enter) gidilebilmesi (`tests/test_frontend_smoke.py`, toplam 15
  duman testi → 435 test).

### Düzeltildi
- **Modal kutularda Tab tuşu artık odağı kutunun dışına kaçırmıyor**
  (`ui/static/app.js` `modalAc`) — önceden Tab, perdenin altında görsel
  olarak gizli kalan arka plan öğelerine geçebiliyordu; klavye/ekran
  okuyucu kullanan biri ekranda görünmeyen bir yere odaklanmış oluyordu.
- **Bildirim kutusuna `aria-live="polite"` eklendi** (`ui/static/app.js`)
  — "Etkinlik eklendi" / "Veri alınamadı" gibi mesajlar önceden yalnızca
  görsel kalıyordu, ekran okuyucu hiç duyurmuyordu.
- **Ay görünümünde etkinlik bloğu ve "+N daha" yalnızca fareyle açılabiliyordu**
  (`<div onclick>`) — klavye/ekran okuyucu kullanan biri ay görünümünde HİÇBİR
  etkinliği açamıyordu. İkisi de artık `<button>`. Gün listesi kutusunun
  konumu da artık tıklama olayının clientX/clientY'si değil, "+N daha"
  düğmesinin kendi konumu (`ui/static/app.js` `gunListesiAc`) — klavyeyle
  (Enter) tetiklenen bir `click`'te clientX/clientY 0 olduğu için kutu
  eskiden ekranın sol üst köşesine fırlıyordu.
- **Kısa/dar bloklarda CSS ile kırpılan başlık artık `title` (araç ipucu)
  olarak da yazılıyor** (zaman ızgarası, ay görünümü, tüm gün şeridi, gün
  listesi) — üzerine gelince tam başlık (ve saat) görünüyor.
- **Arama sonuçları da yalnızca fareyle açılabiliyordu** (`<li onclick>`) —
  aynı sınıf hata ay görünümündeki bloklarda da vardı. `<li>` artık yalnızca
  liste çerçevesi, tıklanabilir yüzey içindeki `<button>` (`ui/static/app.js`
  `aramaYap`).
- README/AGENTS.md'deki eski test sayısı (424) ve AGENTS.md §5'teki "kod
  tanımlayıcıları İngilizce" satırı güncel değildi; ikisi de düzeltildi
  (bkz. AGENTS.md §5, §6). Test sayısı bu değişikliklerle birlikte 435'e
  çıktı.

## [1.2.0] - 2026-09-21

### Eklendi
- Yedekler penceresinde **"Şimdi yedekle"** ve **"Klasörü aç"** artık
  çalışıyor (önceden yalnızca listeleme/geri yükleme vardı).
- Ön yüzün ilk otomatik testleri: gerçek başsız tarayıcıyla (Playwright)
  sayfa açılışı, hızlı ekleme, görünüm geçişi ve çakışma onay kutusunu
  kapsayan 4 duman testi. `app.js` daha önce hiç test edilmiyordu.
- CI: her push/PR'da `ruff` + `mypy` + `pytest` (424 test) + `app.js`
  sözdizimi + ön yüz duman testleri otomatik çalışıyor.

### Değişti
- **Hızlı eklemede çakışma** artık "ekle, sonra bildir + geri al" değil:
  kaydetmeden ÖNCE düzenlenebilir bir onay kutusu açılıyor (Başlık/Tarih/
  Başlangıç/Bitiş/Takvim + "Yine de kaydet / Saati değiştir / Vazgeç").
  Tekrarlı ifadeler bu akışı atlıyor, eski davranış onlarda geçerli.
- **Yedekler penceresi** tek bir açılır listeden, her yedeğin tarihini,
  etkinlik sayısını ve boyutunu gösteren gerçek bir listeye dönüştü.
- README'nin hero ekran görüntüsü yeni tasarımla güncellendi.

## [1.1.0] - 2026-09-21

### Değişti
- **Arayüz baştan tasarlandı** (Claude Design ile üretilen spesifikasyona
  göre, kontrast oranları elle hesaplanıp WCAG AA (4.5:1) karşısında
  doğrulandı): asıl sorun üst çubuğun 1398px'e ihtiyaç duyması,
  varsayılan pencerede (1180px) bile ezilmesiydi. Kök çözüm yapısal --
  ikincil eylemler (İçe/Dışa aktar, Yedekler, Ayarlar, saat dilimi, takvim
  listesi) üst çubuktan kenar çubuğuna taşındı; kenar çubuğuna ana
  görünümden bağımsız gezinen bir mini ay takvimi eklendi. Dar pencerede
  (<1040px) kenar çubuğu ikon rayına iniyor, arama üstten inen bir
  şeride taşınıyor. Renk paleti, köşe yarıçapı, boşluk/tipografi ölçeği
  ve düğme yükseklikleri tek bir belirteç kümesine bağlandı.
- Yakınlaştırma uçlarında (24px–160px saat yüksekliği) blok içeriği
  yoğunluğa göre uyarlanıyor: en sıkışıkta yalnızca başlık, en ferahta
  etkinliğin konumu da görünüyor.

### Eklendi
- **İlk açılış ekranı**: hiç etkinlik yoksa (yalnızca varsayılan
  "Kişisel" takvimle) artık boş bir ızgara yerine "Takvim hazır"
  karşılama ekranı ve üç örnek eylem (Etkinlik ekle / .ics içe aktar /
  Yedekten geri yükle) gösteriliyor; bir etkinlik oluşturulunca
  kendiliğinden kapanıyor.

### Düzeltildi
- Bir etkinliği kopyaladıktan (`Ctrl+C`) sonra tıklanan HER boş saat aynı
  etkinliği yapıştırıyordu, pano yalnızca `Escape` ile ya da yeniden
  kopyalayarak temizleniyordu -- kullanıcı gözünde "sonsuza kadar
  yapıştırma" gibi görünüyordu. Artık bir yapıştırma (tıklama, `Ctrl+V`
  ya da Çoğalt) başarıyla tamamlanınca pano kendiliğinden boşalıyor;
  tekrar yapıştırmak için yeniden kopyalamak gerekiyor.

### Güvenlik
Harici bir API güvenlik denetiminin beş bulgusu da elle (gerçek HTTP
istekleri, ham soketler, ölçülen süreler) doğrulanıp düzeltildi:
- **RRULE hizmet engelleme (DoS)**: `FREQ=SECONDLY` + büyük `COUNT`/`UNTIL`
  içeren bir `.ics`, tek bir istekle sunucuyu dakikalarca kilitleyebiliyordu
  (`COUNT=2.000.000` gerçek istekte 4.9 sn, ay görünümünde sınırsız bir seri
  17 sn). Artık 10.000 örneği aşan seriler içe aktarımda reddediliyor,
  görüntülemede sessizce kırpılıyor.
- **İçe aktarmada dosya yolu okuma**: `POST /api/import` gövdesi, diskte var
  olan bir dosya adına denk gelirse o dosya okunup `/api/export` ile dışarı
  sızdırılabiliyordu (uçtan uca kanıtlandı) -- bu, `icalendar` paketinin
  kendi dosya-yolu sezgisinden kaynaklanıyordu, iki katmanda kapatıldı.
- **Statik dosya sunumunda yol geçişi**: dizin sınırı kontrolü metin öneki
  karşılaştırıyordu; `ui/static` ile aynı önekli bir kardeş dizindeki dosya
  sızdırılabiliyordu (canlı kanıtlandı).
- **Tek istekle sunucu kilitlenmesi**: geçersiz/negatif `Content-Length`
  başlığı, TEK THREAD'li sunucuyu TÜM istemciler için kilitliyordu (ham
  soketle kanıtlandı: ilgisiz bir istek 12 sn zaman aşımına uğradı).
- **Ağa açık, kimlik doğrulamasız API**: `--host` loopback dışına
  ayarlanırsa artık `--ag-erisimine-izin-ver` bayrağı şart.

Ayrıntı: `tests/test_guvenlik.py` (16 yeni test).

## [1.0.2] - 2026-09-20

### Düzeltildi
- Tepsi modunda pencere her kapatıldığında YENİ bir `NotifyIcon` kuruluyordu,
  eskisi `Dispose` edilmiyordu -- "tepsiye in, geri aç, tekrar tepsiye in"
  döngüsü tepside hayalet ikon biriktiriyordu. Artık varsa mevcut ikon
  yeniden kullanılıyor.
- `yedekten_don`'un kenara aldığı `onceki-takvim-*.db` anlık görüntüleri
  düzenli yedeklerin `takvim-*.db` deseninin dışında kaldığı için hiç
  budanmıyordu, her geri yükleme denemesinde bir tam DB kopyası kalıcı
  olarak birikiyordu. Kendi penceresi eklendi (`ONCEKI_SAKLANAN = 5`).

## [1.0.1] - 2026-09-20

### Eklendi
- Klavye panosu: `Ctrl+C` kopyala, `Ctrl+X` kes, `Ctrl+V` yapıştır, `Ctrl+D`
  çoğalt, `Ctrl+Z` görünen "Geri al" bildirimini tetikler.
- Kopyaladıktan sonra boş bir saate **tıklamak** da doğrudan oraya
  yapıştırır (yalnızca `Ctrl+V` değil); normal "Yeni etkinlik" akışına
  dönmek için `Escape` panoyu temizler.
- `Ctrl`+fare tekerleği (trackpad pinch dahil) ile gün/hafta ızgarasını
  yakınlaştır/uzaklaştır (24–160 px/saat); imlecin altındaki saat sabit
  kalır.

### Değişti
- Sürükleyerek taşıma ve boyutlandırmanın yuvarlama adımı 15 dakikadan
  5 dakikaya indirildi. Dakikası dakikasına ayar için etkinliği **Düzenle**
  panelinden saati elle yazmak zaten çalışıyordu, o değişmedi.

### Düzeltildi
- Seri bölme (`split_series` / "Bundan sonrasını değiştir"): EXDATE'li
  `COUNT` serilerinde örnek kaybı, RDATE noktasından bölününce serinin
  kalanının gün kayması.
- Otomatik başlatma açıkken masaüstü kısayolu hiç açılmıyordu (arka plan
  kopyası tek-örnek kilidini tutuyordu); aynı kök sebepten tepsiye
  küçültülmüş pencere de ikinci tıkta açılmıyordu.
- Yedekten geri yükleme, hatırlatıcı arka planda çalışırken sessizce
  başarısız olup "başarılı" dönüyordu.

## [1.0.0] - 2026-09-20

İlk yayın. Yerel-öncelikli, hesapsız, çevrimdışı masaüstü takvim
uygulaması (Windows).

- Gün / Hafta / Ay görünümleri, sürükle-bırak, boyutlandırma
- Tek seferlik, tekrarlı ve tüm gün etkinlikler
- Hızlı ekleme: "yarın 14:00 diş hekimi" yaz, yeter
- `.ics` içe/dışa aktarma (Google/Outlook takviminden geçiş)
- Hatırlatıcılar, sistem tepsisi, otomatik başlatma
- Otomatik yedekleme (son 7 gün saklanır) + geri yükleme arayüzü
- Seri silmede anlık görüntü + tek adımlı geri alma
