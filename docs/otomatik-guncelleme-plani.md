# Otomatik güncelleme planı (masaüstü 1.10.0 + mobil 0.4.0)

Durum: **PLAN, uygulanmadı.** Karar tarihi 2026-11-07 (Arda: "sıradaki güncellemede
uygulamalara otomatik güncelleme yaptırmak lazım"). İki uygulama aynı ilkeleri paylaşır;
ayrıntılar platforma göre ayrışır. Sıradaki güncellemenin kapsamı: **tasarım A + tema
seçeneği (Sistem/Koyu/Açık) + otomatik güncelleme**.

## 1. İlkeler (ikisi için ortak)

1. **Kullanıcı izniyle.** Güncelleme denetimi bir ağ isteğidir; ürün sözü "ağ yalnız sen
   istersen". Denetim kapalıyken hiçbir ağ isteği yok. Varsayılan: ilk açılışta (güncellemeli
   sürümün ilk çalıştırılmasında) **tek seferlik soru**: "Yeni sürümler otomatik denetlensin
   mi?" Evet / Hayır / Sonra sor değil, seçim zorunlu; seçilene kadar ağ isteği yok. Ayarlar'da
   her zaman değiştirilebilir.
2. **Yalnız GitHub'a.** `api.github.com/repos/tungarix/<depo>/releases/latest` ve o
   release'in ek dosyaları. Başka alan adı yok, veri gönderilmez (çerez, kimlik, sürüm dışı
   hiçbir şey; yalnız `User-Agent: Takvim/<sürüm>`). Günde en çok 1 sorgu, `ETag` ile
   (`If-None-Match`; 304 sayılmaz ve limit yemez).
3. **Yalnız "Latest" (taslak ve ön sürüm değil).** Sürüm karşılaştırma semver; yalnız
   daha YÜKSEK sürüm teklif edilir (sürüm düşürme yok).
4. **Her kurulumdan önce kullanıcı onayı** ("Takvim X.Y.Z hazır. Yeniden başlatıp kuralım
   mı?"). Zorunlu güncelleme, sessiz yeniden başlatma, telemetri yok.
5. **Bütünlük:** indirilen dosyanın SHA-256'sı, AYNI release'teki `SHA256SUMS.txt` ile
   eşleşmezse kurulum iptal, dosya silinir, kullanıcıya "elle indir" bağlantısı gösterilir.
   Bilinen sınır: `SHA256SUMS.txt` aynı release'te durduğu için GitHub hesabı ele geçirilirse
   tek başına koruma değil. Güvence katmanları: masaüstü için exe imzası (ileride), mobil
   için Android'in kendi imza denetimi (§3).
6. **Başarısızlık güvenli:** hata her zaman "mevcut sürümle devam"; kısmi dosya silinir;
   veritabanı yedeği zaten migration öncesi alınıyor (AGENTS 55), güncelleme bunu değiştirmez.
7. **Kapsam dışı:** delta/yama güncelleme, beta kanalı, otomatik geri alma sunucusu, mağaza.

## 2. Masaüstü (Windows, PyInstaller tek dosya exe)

**Akış:** denetim thread'i (açılışta + her 24 saatte) → `releases/latest` → yeni sürüm
varsa durum satırı ("1.10.0 hazır") + tepsi/uygulama içi bildirim, ayarlar anahtarı açıksa
**önden indirme** (ya da yalnız bildirim; bkz. §6 açık karar) → hash doğrulama →
onay → kurulum.

**Kurulum yöntemi (Windows çalışan exe'yi üzerine yazdırmaz):**
1. Yeni exe `%LOCALAPPDATA%\Takvim\guncelleme\Takvim-<sürüm>.exe` olarak iner (`.part` →
   hash → yeniden adlandır).
2. Onayda uygulama yeni exe'yi `--guncelle-tamamla --eski <yol> --pid <pid>` ile başlatıp
   KENDİ penceresini kapatır.
3. Yeni exe eski sürecin bitmesini bekler (süre sınırı 30 sn), eski dosyayı `Takvim.eski.exe`
   adına taşır (kısayol aynı yolu gösterdiği için değişmez), yeni dosyayı eski yola kopyalar,
   sağlamasını yapar, **kendini normal modda yeniden başlatır** ve bir sonraki açılışta
   `Takvim.eski.exe`'yi siler.
4. Herhangi bir adım patlarsa eski dosya geri adlandırılır ve eski sürüm açılır (kullanıcı
   hiç kurulum yapılmamış gibi devam eder; günlüğe yazılır).
5. exe yazılabilir olmayan bir konumdaysa (Program Files vb.) otomatik kurulum yok: "indir"
   bağlantısı gösterilir.

**Arayüz:** Ayarlar → Güncellemeler (anahtar, "Şimdi denetle", son denetim, durum, sürüm
notlarına bağlantı); tepsi menüsünde "Güncelleme hazır"; ilk soru kutusu.

**Kodda:** `guncelleme/` paketi (saf mantık: sürüm karşılaştırma, release çözümleme, hash;
ağ ve dosya katmanı ayrı, `core/` kuralı korunur), `ui/server.py` ucu
(`/api/guncelleme/*`, Host/Origin korumalı, yazan uçlar gibi), `ayarlar.json`'a
`guncelleme_denetimi` (`null` = hiç sorulmadı, `true`/`false`).

**Test (hepsi mutasyonla doğrulanacak):** sürüm karşılaştırma (1.9.0<1.10.0, ön ek `v`),
sahte yerel GitHub sunucusu (200/304/403 limit/404/bozuk JSON/draft/prerelease), hash
uyuşmazlığı, kesilmiş indirme, boş/aşırı büyük dosya, asset adı beklenenle eşleşmiyor,
yazma izni yok, eski sürüm teklif edilmiyor, denetim kapalıyken sıfır ağ isteği, Windows'ta
çalışan exe değiştirme entegrasyon testi (geçici bir `Takvim.exe` kopyası üzerinde, gerçek
kullanıcı kurulumuna DOKUNMADAN), `exe_duman.py`'ye "yeni kurulumda ağ isteği yok" adımı.

## 3. Mobil (Android, tek APK)

**Akış:** uygulama açılışında ve ayarlar anahtarı açıksa en çok günde bir kez denetim
(arka plan işi/WorkManager YOK, yeni bağımlılık YOK) → yeni sürüm varsa uygulama içi
bildirim ("0.4.0 hazır, 58 MB") → onayda indir (**varsayılan yalnız Wi-Fi'da**; mobil
veride ayrı onay) → hash → sistem kurulum penceresi.

**Kurulum:** `PackageInstaller` oturumu (`MainActivity.kt` method channel'ı), manifest'e
`REQUEST_INSTALL_PACKAGES` (yeni izin; "bilinmeyen uygulamaları yükle" izni sistem
ayarında ayrıca verilmeli: uygulama kullanıcıyı ilgili Ayarlar ekranına yönlendirir),
`FileProvider` ile APK. Android 12+'ta uygulama bir kez kendini kurunca (installer-of-record
= Takvim) sonraki güncellemeler `USER_ACTION_NOT_REQUIRED` ile onaysız olabilir;
buna GÜVENMİYORUZ, her durumda önce kendi onay kutumuz çıkar.

**Güvence:** Android, farklı anahtarla imzalı APK'yı yüklemeyi reddeder. Bu, hash'ten güçlü
asıl katman. Yayın imza anahtarı (`Documents\takvim-mobil-imza`) KAYBEDİLMEMELİ.

**İzin ve belge değişiklikleri:** manifest, README izin bölümü, SECURITY.md, site metni
ve güvenlik kaydı yeni izni açıkça yazar (`INTERNET` Wi-Fi + güncelleme, `REQUEST_INSTALL_PACKAGES`
yalnız güncelleme).

**Test:** saf Dart (sürüm, release çözümleme, hash) + yerel sahte sunucuyla istemci (mevcut
`tool/e2e/wifi_istemci_testi.dart` deseni); emülatörde gerçek güncelleme (iki aynı anahtarlı
APK, eski sürümün üstüne kurulumda veri korunuyor); izin reddi; Wi-Fi dışı onay; hash
uyuşmazlığı; yarım indirme; denetim kapalıyken sıfır ağ isteği.

## 4. Yayın hattı

Değişiklik gerekmiyor: release zaten `SHA256SUMS.txt` ve sabit adlı varlıklar
(`Takvim.exe`, `Takvim-X.Y.Z.apk`) içeriyor. Eklenecek tek şey, uygulamanın okuyacağı
varlık adlarının sözleşmesi (`docs/` içinde bir cümle) ve release notu şablonunda
"otomatik güncelleme" bölümü.

## 5. Sürümler ve sıra

- **Masaüstü 1.10.0:** tasarım A + tema seçeneği (Sistem/Koyu/Açık) + güncelleyici.
- **Mobil 0.4.0:** aynı üçü + yeni izin.
- Önce tasarım (ayrı, hızlı), sonra güncelleyici (güvenlik incelemesi gerektirir: dışarıdan
  indirilen ve çalıştırılan dosya = en yüksek riskli yüzey).
- Mevcut kurulumlar (≤ 1.9.0 ve ≤ 0.3.0) bu özelliği içermez: **bir kez elle** güncellenir
  (Pati'de de böyleydi). Site ve release notları bunu söyler.

## 6. Açık kararlar (Arda)

1. **İlk soru mu, varsayılan mı?** Öneri: ilk soru (zorunlu seçim), ağ isteği seçimden önce yok.
2. **Masaüstünde önden indirme mi, yalnız bildirim mi?** Öneri: bildir, onayda indir
   (kullanıcı onay vermeden 20 MB indirmemek ürün sözüne daha yakın).
3. **Mobilde yalnız Wi-Fi varsayılanı** (öneri: evet).
4. Güvenlik incelemesi (zorunlu) ve masaüstü exe kod imzalama (ücretli, ertelenmiş karar).

## 7. Riskler

- Çalışan exe'yi değiştirme: Windows kilidi, antivirüs gecikmesi, kısayol/yol bozulması.
  Geri alma yolu (§2.4) testle kanıtlanmadan yayın yok.
- Mobilde izin sayısı artıyor: her yeni izin güven maliyeti; metinler dürüst olmalı.
- `SHA256SUMS.txt` aynı release'te: hesap ele geçirilirse hash yetmez (kabul edilen sınır,
  belgede yazılı).
