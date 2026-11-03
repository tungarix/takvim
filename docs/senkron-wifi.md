# Takvim Wi-Fi eşleştirme (aynı ağda doğrudan senkron) — protokol v1

`docs/senkron.md`'deki `.takvimsync` biçimini ve birleştirme kurallarını DEĞİŞTİRMEZ;
yalnızca dosyanın cihazdan cihaza **nasıl taşındığını** anlatır. Bulut, hesap, kalıcı
sunucu yok: masaüstü, kullanıcı "eşleştir" deyince **kısa ömürlü** bir yerel HTTPS
sunucusu açar; telefon QR'dan gelen bağlantıyla ona bağlanır. Dosya aktarmayla
senkron (docs/senkron.md) yedek yol olarak AYNEN kalır.

## 1. Roller ve akış

Masaüstü = geçici sunucu, telefon = istemci.

1. Masaüstü Ayarlar → Telefonla senkron → **"Wi-Fi ile eşleştir"**: oturum açılır,
   QR kod + aynı bağlantının metni + geri sayım + "İptal" gösterilir.
2. Telefon bağlantıyı açar (kamera uygulamasıyla QR → App Link, ya da metni
   yapıştırır). Takvim Mobil **onay ekranı** gösterir (bilgisayarın adı + IP).
3. Telefon `GET /v1/hello`, sonra `GET /v1/state` (masaüstünün tam durumu).
4. Telefon dosyayı **mevcut içe aktarma akışıyla** (önizleme + onay) kendi
   verisine birleştirir.
5. Telefon kendi birleşmiş tam durumunu `POST /v1/state` ile masaüstüne gönderir.
6. Masaüstü gelen dosyayı doğrular, **ekranında önizleme + onay** sorar; onaylanırsa
   mevcut `senkron/ice.py` ile birleştirir, rapor döner. Oturum kapanır.

Birleştirme idempotent olduğundan 4 ve 6 sırası/tekrarı sorun yaratmaz.

## 2. Bağlantı (QR içeriği)

```
https://aktenak.tech/s#v=1&h=192.168.1.20:51734&t=<token>&f=<parmak izi>&n=<ad>
```

Masaüstü her zaman `/s` biçimini üretir; istemci `/s/` biçimini de kabul eder.

- Bilgi **fragment**'ta (`#`): tarayıcı sunucuya göndermez, aktenak.tech token'ı görmez.
- `v` = 1. `h` = `IPv4:port` (yalnızca özel/yerel aralık, §3). `t` = 32 küçük hex
  (128 bit rastgele, oturum başına). `f` = sunucu sertifikasının DER'inin SHA-256'sı,
  base64url (dolgusuz, 43 karakter). `n` = cihaz adı (URL-kodlu, en çok 40 karakter,
  yalnızca gösterim; güvenlik kararı vermez).
- Bilinmeyen anahtarlar yok sayılır; `v` bilinenden büyükse istemci "Takvim'i güncelle"
  der.

## 3. Sunucu (masaüstü)

- **Adres:** varsayılan yoldaki (default route) arayüzün IPv4'ü; özel aralıklar
  (10/8, 172.16/12, 192.168/16) veya link-local (169.254/16) DEĞİLSE oturum
  başlamaz ("özel bir ağa bağlı değilsin"). `0.0.0.0`'a DEĞİL, yalnız o IP'ye bağlanır.
  Port: 49152-65535 arası rastgele boş port.
- **TLS:** oturum başına bellekte üretilen kendi imzalı sertifika (ECDSA P-256, SAN =
  o IP, 1 gün geçerli; özel anahtar diske yazılmaz). TLS ≥ 1.2.
- **Ömür:** en çok **3 dakika**; başarılı `POST /v1/state` yanıtından, İptal'den,
  pencere/uygulama kapanmasından ya da **tüm kaynaklardan toplam 50 başarısız kimlik
  doğrulamasından** sonra sunucu kapanır ve token geçersizdir. Aynı anda tek oturum.
  İptal, onay verildikten sonra birleştirme sürerken (`isleniyor`) YOK SAYILIR: veri
  birleşir ve oturum sonucu "birleştirildi" yazılır.
- **Bağlantı sınırları (yavaş istemci / kaynak taciz):** kimlik doğrulanana dek bağlantının
  TOPLAM ömrü (TLS el sıkışması dahil) 10 sn; kimlik doğrulandıktan sonra POST gövdesini
  okumak için toplam 30 sn (onay beklemesi bu süreye girmez). Aynı kaynak IP'den en çok 2
  eşzamanlı bağlantı, sunucu genelinde en çok 8; aşan bağlantı yanıtsız hemen kapatılır.
- **Kimlik:** her istekte `Authorization: Bearer <t>`; sabit zamanlı karşılaştırma;
  yanlış/eksik → `401 {"error":"yetkisiz"}` ve o **kaynak IP**'nin sayacı artar; başka
  hiçbir şey sızmaz. Bir IP **5 başarısız denemede o oturum boyunca engellenir**: bağlantıları
  yanıtsız hemen kapatılır (doğru token bile). Oturum KAPANMAZ, böylece ağdaki biri
  tokensız isteklerle eşleştirmeyi bozamaz; başka IP'deki telefon etkilenmez.
- **Uçlar** (diğer yol 404, diğer metot 405, CORS başlığı YOK, HTTP/1.1):
  - `GET /v1/hello` → `{"format":"takvim-wifi","version":1,"device":{"name":"…","app":"desktop 1.9.0"}}`
  - `GET /v1/state` → `.takvimsync` JSON'u (docs/senkron.md), `Content-Type: application/json`.
  - `POST /v1/state` → gövde telefonun `.takvimsync` JSON'u. `Content-Length` zorunlu,
    en çok 16 MiB (`Content-Length` yoksa `411`, sınır aşılırsa gövde okunmadan `413`),
    JSON derinlik/boyut sınırları dosya içe aktarmayla aynı: dosyada en çok 20.000
    etkinlik ve sınırlı (COUNT/UNTIL'li) serilerin doğrulamada sayılan toplam örneği en
    çok 500.000 (aşarsa `400 senkron_bozuk`; gerçek kullanıcı verisinin çok üstünde,
    ölçüm: en kötü durum ~1 sn CPU). Oturumda aynı anda yalnız BİR POST doğrulanır/onay
    bekler; ikincisi doğrulamaya hiç girmeden `409 mesgul` alır. (Not: Wi-Fi POST sınırı
    16 MiB, dosya içe aktarma yolunun gövde sınırı `_MAKS_GOVDE` 8 MB'dır; fark
    bilerek korunur, iki yol birleştirilmez.) Doğrulama
    geçerse masaüstü arayüzünde **onay penceresi** ("Telefondan: N etkinlik, M görev, K
    silme. Birleştirilsin mi?") açılır; kullanıcı, POST'un **alındığı andan** itibaren en çok 60 sn içinde karar verir. Bu
    bekleme oturumun kalan ömründen bağımsızdır: onay beklerken oturumun kapanma süresi
    onay bitene kadar uzar (en çok +60 sn; 2:55'te gelen POST da tam 60 sn bekler).
    Onay → birleşir, `200 {"report":{"added":…,"updated":…,"deleted":…,"skipped":…}}`;
    ret → `403 {"error":"reddedildi"}`; süre dolarsa `408`; onay beklerken gelen ikinci
    POST → `409 {"error":"mesgul"}`, onay beklerken İptal → bekleyen POST'a `409 {"error":"iptal"}`. Oturumda yalnız BİR başarılı
    ya da reddedilmiş POST olur, sonra oturum kapanır. Geçersiz dosya → `400` ve
    docs/senkron.md'deki hata kodu.
- **Günlük:** token ve dosya içeriği ASLA günlüğe yazılmaz; yalnız "oturum açıldı/kapandı,
  kaç istek, sonuç".
- **Windows Güvenlik Duvarı:** ilk kullanımda sistem "izin ver" sorabilir; arayüz bunu
  QR'ın altında tek cümleyle söyler ("Windows sorarsa **Özel ağlar**'a izin ver").

## 4. İstemci (telefon)

- Bağlantıyı **doğrular**: şema `https`, ana makine `aktenak.tech`, yol `/s` ya da `/s/` (`/s//`, `/s/x`, `/sss` gibi
  başka yollar reddedilir), fragment
  alanları geçerli biçimde; `h` özel/yerel IPv4 değilse **bağlanmaz**.
- **Onay ekranı** (bağlanmadan önce): "«n» (IP) ile eşleşilecek. Bunu, bilgisayarında
  senin açtığın eşleştirme ekranından aldıysan devam et." Kullanıcı onaylamadan ağ
  isteği yok.
- Sertifika **sabitlenir**: sunum edilen sertifikanın DER SHA-256'sı `f` ile
  eşleşmezse bağlantı reddedilir (`badCertificateCallback` yalnız bu eşleşmede true).
  Sistem güven deposuna ya da herhangi bir sertifikaya güvenilmez.
- Zaman aşımı: bağlanma 10 sn, `GET` 30 sn, `POST` 90 sn (masaüstü onayı bekler).
- Veri **yalnız ikinci onaydan sonra** gönderilir (telefondaki önizleme "Birleştir ve
  gönder" ile onaylanınca). Kullanıcı vazgeçerse hiçbir şey gönderilmez.
- Hata iletileri anlaşılır Türkçe: ağa ulaşılamadı (aynı Wi-Fi'da mısın? Misafir
  ağlar cihazları ayırabilir), süre doldu, parmak izi uyuşmadı (güvenlik uyarısı),
  masaüstü reddetti, sürüm eski/yeni.
- Android: `INTERNET` izni (yeni), `usesCleartextTraffic="false"` AYNEN kalır (yalnız
  HTTPS), `CAMERA` YOK. `https://aktenak.tech/s` ve `/s/` için (`android:path` her ikisi) `android:autoVerify="true"`
  App Link `intent-filter`'ı; `assetlinks.json` sitede (§5). Bağlantıyı yapıştırma
  alanı yedek yoldur.

## 5. Site (aktenak.tech)

- `/.well-known/assetlinks.json`: paket `com.aktenak.takvim`, imza sertifikası SHA-256
  parmak izi (`5F:34:E5:EA:47:46:F3:55:E6:9D:9A:77:E5:91:EA:EF:29:04:70:34:DD:C5:7C:3F:3E:4B:02:AB:6B:83:71:14`);
  `Content-Type: application/json`.
- `/s/` ve `/en/s/`: bağlantı uygulama kurulu değilse (ya da bilgisayarda) açılan sade
  sayfa: "Bu bağlantı Takvim Mobil içindir. Telefonunda Takvim Mobil kuruluysa kamerayı
  QR koda tut. Kurulu değilse [indir]." Sayfa fragment'ı HİÇBİR script ile okumaz/
  göndermez; `noindex`.

## 6. Tehdit modeli (özet)

| Saldırgan | Neden olmaz |
|---|---|
| Aynı ağdaki gözlemci | TLS; dinleyemez. Sertifika parmak izi QR'dan gelir, ortadaki adam sertifikayı taklit edemez |
| Aynı ağda tarayıcı/port tarayıcı | Token 128 bit; IP başına 5 hatada o IP engellenir (oturum sürer), toplam 50 hatada oturum kapanır; 3 dk ömür; IP'ye bağlı, rastgele port |
| Yavaş/bağlantı yığan istemci (slowloris) | Kimliksiz bağlantıya toplam 10 sn, gövdeye 30 sn; IP başına 2 bağlantı; tek IP tüm yuvaları dolduramaz |
| Token sahibi / kötü niyetli dosya ile CPU yedirme | Etkinlik ve toplam örnek bütçesi; tek eşzamanlı POST doğrulaması |
| Telefona sahte bağlantı gönderen (kimlik avı) | Yalnız özel IP; bağlanmadan önce ve göndermeden önce ayrı onay; sahte sunucu telefondan veri ancak kullanıcı iki kez onaylarsa alır |
| Telefon olarak davranıp masaüstüne veri basan | Token + masaüstünde zorunlu önizleme/onay |
| Sonradan token yeniden kullanımı | Oturum tek kullanımlık, sunucu kapanınca ölür |

Bilinen sınırlar: kullanıcı, kendi masaüstü ekranındaki QR yerine saldırganın verdiği
bir bağlantıyı iki kez onaylarsa verisini ona verir (onay metinleri bunu söyler);
"misafir"/istemci yalıtımlı Wi-Fi'larda iki cihaz birbirini göremez (dosya aktarma
yolu kalır); masaüstü exe'si imzasız olduğundan Windows ilk açılışta uyarabilir.
