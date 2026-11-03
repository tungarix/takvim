"""Takvim uygulamasının senkron dosyası (`.takvimsync`) dışa/içe aktarma paketi.

Biçim ve birleştirme kuralları: `docs/senkron.md`. Masaüstü ile mobil uygulama
aynı dosyayı konuşur; ağ, hesap, sunucu yok -- dosyayı kullanıcı taşır.
"""

from .disa import BICIM, SURUM, UZANTI, cihaz_kimligi, durum_uret, json_metni
from .ice import SenkronHatasi, SenkronRaporu, ice_aktar
from .wifi import WifiHatasi, WifiYonetici

__all__ = [
    # dışa aktarma
    "durum_uret",
    "json_metni",
    "cihaz_kimligi",
    # içe aktarma
    "ice_aktar",
    "SenkronRaporu",
    "SenkronHatasi",
    # Wi-Fi eşleştirme (docs/senkron-wifi.md)
    "WifiYonetici",
    "WifiHatasi",
    # biçim
    "BICIM",
    "SURUM",
    "UZANTI",
]
