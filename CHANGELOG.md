# Değişim günlüğü

Bu proje [Keep a Changelog](https://keepachangelog.com/) biçimini ve
[Semantic Versioning](https://semver.org/)'ı takip etmeye çalışır. Sürümler
GitHub [Releases](https://github.com/tungarix/takvim/releases) sayfasında
`Takvim.exe` ekiyle yayınlanır.

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
