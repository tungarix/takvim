"""Güncelleme mantığının SAF kısmı: sürüm karşılaştırma, release çözümleme, hash.

Ağ ve dosya burada yok (`core/` ile aynı disiplin): her şey dize alıp dize/nesne
döndürüyor, bu yüzden hepsi ağsız test edilebiliyor. Güvenlik kararları (hangi
adres, hangi dosya adı, hangi boyut) tek yerde, burada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

__all__ = [
    "IZINLI_SUNUCULAR",
    "MAKS_EXE_BAYT",
    "EXE_ADI",
    "OZET_ADI",
    "Yayin",
    "adres_uygun",
    "daha_yeni_mi",
    "ozet_coz",
    "surum_coz",
    "yayin_coz",
]

EXE_ADI = "Takvim.exe"
OZET_ADI = "SHA256SUMS.txt"
# Beklenen exe ~21 MB; ikiye katlanana dek makul, ötesi bozuk/kötü niyetli sayılır.
MAKS_EXE_BAYT = 100 * 1024 * 1024
# Yalnızca GitHub: API, release sayfası ve varlıkların yönlendirildiği depolama.
IZINLI_SUNUCULAR = frozenset({
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
})

# Yalnız düz X.Y.Z (isteğe bağlı `v`): "1.10.0-beta" ya da "1.10" bilerek tanınmıyor,
# çünkü yalnızca kararlı sürüm teklif edilir.
_SURUM = re.compile(r"v?(\d{1,6})\.(\d{1,6})\.(\d{1,6})")
_HEX64 = re.compile(r"[0-9a-fA-F]{64}")


def surum_coz(metin: object) -> tuple[int, int, int] | None:
    """`v1.10.0` / `1.10.0` -> (1, 10, 0); tanınmazsa None."""
    if not isinstance(metin, str):
        return None
    m = _SURUM.fullmatch(metin.strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def daha_yeni_mi(aday: str, mevcut: str) -> bool:
    """`aday` KESİN daha yüksekse True. Sayısal karşılaştırma: 1.10.0 > 1.9.0.

    Sürüm düşürme ve aynı sürüm teklif edilmez; çözülemeyen taraf False verir.
    """
    a, m = surum_coz(aday), surum_coz(mevcut)
    return a is not None and m is not None and a > m


@dataclass(frozen=True)
class Yayin:
    """GitHub'daki "Latest" sürümden uygulamanın ihtiyacı olan kısım."""

    surum: str  # "1.10.0" (başında v yok)
    exe_url: str
    exe_boyut: int
    ozet_url: str
    sayfa_url: str


def adres_uygun(url: object, depo: str, ek_sunucular: frozenset[str]) -> bool:
    """https + izinli sunucu; github.com'da yol bu deponun release'i olmalı."""
    if not isinstance(url, str):
        return False
    try:
        p = urlsplit(url)
    except ValueError:
        return False
    sunucu = (p.hostname or "").lower()
    if sunucu in ek_sunucular:  # yalnız testler (loopback); üretimde boş
        return p.scheme in ("http", "https")
    if p.scheme != "https" or sunucu not in IZINLI_SUNUCULAR or p.username or p.password:
        return False
    if sunucu == "github.com":
        return p.path.startswith(f"/{depo}/releases/")
    return True


def yayin_coz(veri: object, depo: str, ek_sunucular: frozenset[str] = frozenset()) -> Yayin | None:
    """`releases/latest` JSON'unu doğrular; uygun değilse None (sessizce teklif yok).

    Reddedilenler: sözlük olmayan gövde, taslak/ön sürüm, kararlı X.Y.Z olmayan
    etiket, `Takvim.exe` ya da `SHA256SUMS.txt` adlı varlığın eksikliği,
    sıfır/aşırı büyük boyut, izinli olmayan adres.
    """
    if not isinstance(veri, dict) or veri.get("draft") or veri.get("prerelease"):
        return None
    sayi = surum_coz(veri.get("tag_name"))
    if sayi is None:
        return None
    varliklar = veri.get("assets")
    if not isinstance(varliklar, list):
        return None
    bulunan: dict[str, dict] = {}
    for v in varliklar:
        if isinstance(v, dict) and v.get("name") in (EXE_ADI, OZET_ADI):
            bulunan.setdefault(v["name"], v)  # ilk eşleşme; yinelenen ad yok sayılır
    exe, ozet = bulunan.get(EXE_ADI), bulunan.get(OZET_ADI)
    if exe is None or ozet is None:
        return None
    boyut = exe.get("size")
    if not isinstance(boyut, int) or isinstance(boyut, bool) or not 0 < boyut <= MAKS_EXE_BAYT:
        return None
    exe_url, ozet_url = exe.get("browser_download_url"), ozet.get("browser_download_url")
    sayfa = veri.get("html_url")
    if not all(adres_uygun(u, depo, ek_sunucular) for u in (exe_url, ozet_url)):
        return None
    if not adres_uygun(sayfa, depo, ek_sunucular):
        sayfa = f"https://github.com/{depo}/releases"
    return Yayin(
        surum=".".join(str(n) for n in sayi),
        exe_url=exe_url,  # type: ignore[arg-type]
        exe_boyut=boyut,
        ozet_url=ozet_url,  # type: ignore[arg-type]
        sayfa_url=sayfa,  # type: ignore[arg-type]
    )


def ozet_coz(metin: str, ad: str = EXE_ADI) -> str | None:
    """`SHA256SUMS.txt` içinden `ad` dosyasının küçük harfli SHA-256'sını verir.

    Biçim `sha256sum`'unki: "<64 hex>  <ad>" (ikinci ayraç ` *` de olabilir).
    Aynı ad iki kez geçerse belirsizlik güvenli değil: None.
    """
    bulunan: list[str] = []
    for satir in metin.splitlines():
        parca = satir.strip().split(None, 1)
        if len(parca) != 2:
            continue
        ozet, dosya = parca
        if dosya.lstrip("*").strip() == ad and _HEX64.fullmatch(ozet):
            bulunan.append(ozet.lower())
    return bulunan[0] if len(bulunan) == 1 else None
