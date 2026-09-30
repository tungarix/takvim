# Security Policy · Güvenlik Politikası

[English](#english) · [Türkçe](#türkçe)

---

## English

Takvim is a local-first desktop app: no server, no account, no network
sync. Your data stays in a local SQLite file. That keeps the attack surface
small, but not empty. The app runs a small HTTP server on `127.0.0.1` for its
own window, reads `.ics` files you import, and restores backups.

### Supported versions

Only the [latest release](https://github.com/tungarix/takvim/releases/latest)
gets security fixes. If you are on an older version, update first and check
whether the problem is still there.

### Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Use GitHub's private reporting instead:
**[Report a vulnerability](https://github.com/tungarix/takvim/security/advisories/new)**
(repository → *Security* tab → *Report a vulnerability*). Only the maintainer
sees the report.

Helpful to include:

- the Takvim version (⚙ Settings shows "Takvim vX.Y.Z"),
- what you did, what you expected, what happened,
- the impact as you see it (what could an attacker read, change or break),
- a minimal `.ics` file or request that reproduces it, if relevant.

**Do not attach your own `takvim.db`** or any file with real personal data;
a small made-up example is enough.

This is a one-person project, so replies are best effort. I will try to
answer within about a week, and to credit you in the release notes unless you
prefer not to be named.

### What counts

For example: another web page in your browser being able to change your data
through the local server, path traversal in static file serving or `.ics`
import, a crafted `.ics` or recurrence rule that hangs or crashes the app,
a backup/restore path that loses or leaks data, or a release file that does
not match its published checksum and attestation.

### What does not count

- Someone who already has access to your Windows account and can read
  `%LOCALAPPDATA%\Takvim\takvim.db`. It is a plain, unencrypted SQLite file by
  design; it is your own data on your own machine.
- The Windows SmartScreen warning. The `.exe` is not code-signed; this is a
  known, documented limit.
- Problems that only exist in a build you compiled or modified yourself.

### Verifying a download

Each release from v1.4.1 on ships a `SHA256SUMS.txt` and a GitHub build
provenance attestation. See
[Verify your download](README.md#verify-your-download) in the README.

### Earlier findings

The five findings of an external API security review (recurrence-rule denial
of service, file-path read on import, static-file path traversal, single-request
server lock-up, unauthenticated API exposed to the network) were verified and
fixed in [v1.1.0](CHANGELOG.md). The server listens on loopback only unless you
explicitly pass a flag to allow network access, and state-changing requests are
checked against `Origin` / `Sec-Fetch-Site`.

---

## Türkçe

Takvim yerel-öncelikli bir masaüstü uygulaması: sunucu yok, hesap yok, ağ
üzerinden senkron yok. Verin yerel bir SQLite dosyasında kalır. Bu saldırı
yüzeyini küçültür ama sıfırlamaz: uygulama kendi penceresi için `127.0.0.1`'de
küçük bir HTTP sunucusu çalıştırır, içe aktardığın `.ics` dosyalarını okur ve
yedekleri geri yükler.

### Desteklenen sürümler

Güvenlik düzeltmeleri yalnızca
[son sürüme](https://github.com/tungarix/takvim/releases/latest) gelir. Eski
bir sürümdeysen önce güncelle, sorun hâlâ varsa bildir.

### Açık bildirme

**Güvenlik sorunu için lütfen herkese açık issue açma.**

Bunun yerine GitHub'ın özel bildirimini kullan:
**[Güvenlik açığı bildir](https://github.com/tungarix/takvim/security/advisories/new)**
(depo → *Security* sekmesi → *Report a vulnerability*). Bildirimi yalnızca
bakımcı görür.

Şunları yazarsan işim kolaylaşır:

- Takvim sürümü (⚙ Ayarlar'da "Takvim vX.Y.Z" yazar),
- ne yaptın, ne bekledin, ne oldu,
- sence etkisi ne (saldırgan neyi okuyabilir, değiştirebilir, bozabilir),
- gerekiyorsa sorunu yeniden üreten küçük bir `.ics` dosyası ya da istek.

**Kendi `takvim.db` dosyanı ya da gerçek kişisel veri içeren dosya EKLEME**;
küçük, uydurma bir örnek yeter.

Bu tek kişilik bir proje; yanıt vermek elimden geldiği kadar. Yaklaşık bir hafta
içinde cevap vermeye, istemezsen adını yazmamak koşuluyla sürüm notlarında sana
teşekkür etmeye çalışırım.

### Neler kapsamda

Örneğin: tarayıcındaki başka bir sayfanın yerel sunucu üzerinden verini
değiştirebilmesi, statik dosya sunumunda ya da `.ics` içe aktarmada yol geçişi,
uygulamayı donduran ya da çökerten hazırlanmış bir `.ics` / tekrar kuralı, veri
kaybettiren ya da sızdıran bir yedek/geri yükleme yolu, yayımlanan özet ve
attestation'a uymayan bir sürüm dosyası.

### Neler kapsam dışı

- Windows hesabına zaten erişimi olan ve `%LOCALAPPDATA%\Takvim\takvim.db`'yi
  okuyabilen biri. Bu dosya bilerek şifrelenmemiş, düz bir SQLite dosyası; kendi
  bilgisayarındaki kendi verin.
- Windows SmartScreen uyarısı. `.exe` imzalı değil; bu bilinen ve belgelenmiş
  bir sınır.
- Yalnızca kendi derlediğin ya da değiştirdiğin bir sürümde görülen sorunlar.

### İndirmeyi doğrulama

v1.4.1'den beri her sürümde `SHA256SUMS.txt` ve GitHub build provenance
attestation'ı var. Adımlar README'de:
[İndirilen dosyayı doğrula](README.md#verify-your-download) (Türkçe anlatım
README'nin Türkçe bölümünde, "İndirilen dosyayı doğrula" başlığında).

### Önceki bulgular

Harici bir API güvenlik incelemesinin beş bulgusu (tekrar kuralı ile hizmet
engelleme, içe aktarmada dosya yolu okuma, statik dosyada yol geçişi, tek
istekle sunucu kilitlenmesi, ağa açık kimlik doğrulamasız API) doğrulanıp
[v1.1.0](CHANGELOG.md)'da düzeltildi. Sunucu, ağ erişimine izin veren bir bayrağı
açıkça vermedikçe yalnızca loopback'te dinler; durum değiştiren istekler
`Origin` / `Sec-Fetch-Site` ile denetlenir.
