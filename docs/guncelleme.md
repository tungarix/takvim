# Otomatik güncelleme sözleşmesi (masaüstü)

Plan ve gerekçe: `otomatik-guncelleme-plani.md`. Bu belge uygulanan sözleşmedir.

## Yayın varlıkları (yayın hattının uyması gereken)
Her release şu ADLARLA iki varlık içermeli; uygulama başka adı kabul etmez:

| Ad | İçerik |
|---|---|
| `Takvim.exe` | paketli uygulama (boyut > 0 ve ≤ 100 MB) |
| `SHA256SUMS.txt` | `sha256sum` biçimi: `<64 hex>  Takvim.exe` (aynı ad iki satırda geçerse belirsiz sayılır, kurulum iptal) |

Etiket `vX.Y.Z` (yalnız düz üç sayı); taslak ve ön sürümler yok sayılır.

## Ağ
- Yalnız `api.github.com` (`/repos/tungarix/takvim/releases/latest`), `github.com/tungarix/takvim/releases/...`
  ve GitHub'ın varlık depolaması (`objects.githubusercontent.com`, `release-assets.githubusercontent.com`).
  Yönlendirmeler de aynı denetimden geçer. Yalnız `https`.
- Günde en çok 1 denetim; `If-None-Match` (ETag) kullanılır. "Şimdi denetle" kullanıcının kendi isteğidir.
- Gönderilen tek başlık `User-Agent: Takvim/<sürüm>` (+ `Accept`, `If-None-Match`).

## Akış
1. Denetim → `guncelleme.json` (veri klasörü): son denetim, ETag, bulunan sürüm.
2. Kullanıcı onayı → `POST /api/guncelleme/kur {"surum"}`: yalnız denetimin bulduğu sürüm kurulur.
3. İndirme `guncelleme/Takvim-X.Y.Z.exe.part` → boyut = bildirilen boyut → SHA-256 = `SHA256SUMS.txt` → ad.
4. Yeni exe `--guncelle-tamamla --eski <yol> --pid <n>` ile başlar; uygulama kapanır.
5. Yeni exe, eski sürecin bitmesini bekler; eskiyi `Takvim.eski.exe`'ye taşır (Windows çalışan exe'yi yeniden
   adlandırmaya izin verir, üzerine yazmaya vermez; kilit varsa en çok 30 sn yeniden dener), yenisini eski yola kopyalar,
   SHA-256 ile sağlar, normal kipte açar. Hata → eski dosya geri konur ve ESKİ sürüm açılır.
6. Sonraki açılışta `Takvim.eski.exe` ve `guncelleme/` silinir.

## Bilinen sınırlar
- `SHA256SUMS.txt` aynı release'te durur: GitHub hesabı ele geçirilirse tek başına koruma değil.
  Exe imzası ileride (ücretli sertifika) eklenecek.
- Yazılabilir olmayan konumdaki exe (Program Files) otomatik kurulmaz; elle indirme bağlantısı gösterilir.
