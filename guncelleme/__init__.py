"""Otomatik güncelleme (docs/otomatik-guncelleme-plani.md).

- `saf`: sürüm karşılaştırma, release çözümleme, özet ayrıştırma (ağsız, dosyasız)
- `ag`: GitHub istemcisi (yalnız izinli sunucular)
- `kurulum`: indirme doğrulama + çalışan exe'yi değiştirme + geri alma
- `durum`: günlük denetim zamanı ve ETag'in saklanması

`core/` kuralı korunur: `core/` bu paketi import etmez.
"""
