"""Kullanıcı ayarları (`ayarlar.json`, veritabanının yanında).

Tek dosya, iki anahtar: tepsiye küçült + otomatik başlatma. İkisi de
varsayılan KAPALI — pencereyi kapatmak uygulamayı kapatır (mevcut davranış),
Başlangıç klasörüne yazmak sistem düzeyinde değişiklik (AGENTS 24). Açmak
kullanıcının bilinçli kararı, arayüzdeki Ayarlar kutusundan.

`geometri_oku` ile aynı disiplin: bozuk/eksik dosyada istisna YOK, varsayılan
dönüyor. Ayar okunamadığı için uygulamayı açmamak ya da tepsiyi yanlış
davrandırmak kabul edilemez.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["VARSAYILANLAR", "ayar_dosyasi", "ayar_oku", "ayar_yaz"]

VARSAYILANLAR: dict[str, Any] = {
    "tepsiye_kucult": False,
    "otomatik_baslat": False,
}


def ayar_dosyasi(veri_dizini: str | Path) -> Path:
    """Ayar dosyasının yeri — pencere konumu ve DB ile aynı klasör."""
    return Path(veri_dizini) / "ayarlar.json"


def ayar_oku(yol: str | Path) -> dict[str, Any]:
    """Ayarları okur; dosya yoksa/bozuksa varsayılanlar.

    Bilinmeyen anahtarlar korunur (ileride eklenen ayar eski dosyayı ezmesin),
    bilinenler tip kontrolünden geçer (elde düzenlenmiş `"tepsiye_kucult": "evet"`
    gibi bir değer sessizce True OLMASIN).
    """
    sonuc = dict(VARSAYILANLAR)
    try:
        ham = json.loads(Path(yol).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return sonuc
    if not isinstance(ham, dict):
        return sonuc
    for anahtar, varsayilan in VARSAYILANLAR.items():
        deger = ham.get(anahtar, varsayilan)
        if isinstance(deger, type(varsayilan)):
            sonuc[anahtar] = deger
    return sonuc


def ayar_yaz(yol: str | Path, ayarlar: dict[str, Any]) -> bool:
    """Ayarları yazar; başardıysa True.

    Yalnızca BİLİNEN anahtarlar yazılıyor: arayüzden geçen sözlükte fazladan
    bir şey varsa dosyaya sızmasın. Hata yutuluyor (`geometri_yaz` ile aynı
    gerekçe).
    """
    try:
        hedef = Path(yol)
        hedef.parent.mkdir(parents=True, exist_ok=True)
        temiz = {
            anahtar: ayarlar.get(anahtar, varsayilan)
            for anahtar, varsayilan in VARSAYILANLAR.items()
        }
        hedef.write_text(
            json.dumps(temiz, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except (OSError, TypeError, ValueError):
        return False
