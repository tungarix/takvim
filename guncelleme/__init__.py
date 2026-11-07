"""Otomatik güncelleme (docs/otomatik-guncelleme-plani.md).

- `saf`: sürüm karşılaştırma, release çözümleme, özet ayrıştırma (ağsız, dosyasız)
- `ag`: GitHub istemcisi (yalnız izinli sunucular)
- `kurulum`: indirme doğrulama + çalışan exe'yi değiştirme + geri alma
- `durum`: günlük denetim zamanı ve ETag'in saklanması

`core/` kuralı korunur: `core/` bu paketi import etmez.
"""

from .ag import Ag, GuncellemeHatasi
from .hizmet import Guncelleyici
from .kurulum import eski_artiklari_temizle, tamamlamayi_baslat

__all__ = ["Ag", "GuncellemeHatasi", "Guncelleyici", "eski_artiklari_temizle", "tamamlamayi_baslat"]
