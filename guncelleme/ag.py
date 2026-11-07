"""Güncelleme ağ katmanı: GitHub'dan son sürümü sorar, dosyayı indirir.

Yalnızca `saf.IZINLI_SUNUCULAR`'a gider; yönlendirmeler de aynı denetimden
geçer. Hiçbir kimlik, çerez ya da kullanıcı verisi gönderilmez; tek başlık
`User-Agent: Takvim/<sürüm>`. Bu modül yalnızca kullanıcı denetimi AÇTIYSA (ya
da "Şimdi denetle"ye bastıysa) çağrılır; çağıran taraf bunu garanti eder.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .saf import IZINLI_SUNUCULAR, Yayin, adres_uygun, yayin_coz

__all__ = ["Ag", "GuncellemeHatasi"]

_MAKS_JSON = 1024 * 1024
_MAKS_OZET = 64 * 1024
_PARCA = 64 * 1024


class GuncellemeHatasi(Exception):
    """`kod` arayüzde yerelleştirilen kısa tanımlayıcı; ileti günlük içindir."""

    def __init__(self, kod: str, ileti: str = "") -> None:
        super().__init__(ileti or kod)
        self.kod = kod


class Ag:
    """Tek depo için GitHub istemcisi.

    `ek_sunucular` yalnızca testler içindir (yerel sahte sunucu); üretim kodu
    boş bırakır, böylece izinli sunucu kümesi gevşemez.
    """

    def __init__(
        self,
        depo: str = "tungarix/takvim",
        surum: str = "",
        *,
        api_taban: str = "https://api.github.com",
        ek_sunucular: frozenset[str] = frozenset(),
        zaman_asimi: float = 10.0,
    ) -> None:
        self.depo = depo
        self.surum = surum
        self.api_taban = api_taban.rstrip("/")
        self.ek_sunucular = ek_sunucular
        self.zaman_asimi = zaman_asimi
        self._acici = urllib.request.build_opener(_Yonlendirme(self))

    # -- iç ------------------------------------------------------------------

    def _istek(self, url: str, baslik: dict[str, str] | None = None):
        if not adres_uygun(url, self.depo, self.ek_sunucular):
            raise GuncellemeHatasi("adres_izinsiz", url)
        basliklar = {"User-Agent": f"Takvim/{self.surum}"} | (baslik or {})
        return self._acici.open(
            urllib.request.Request(url, headers=basliklar), timeout=self.zaman_asimi
        )

    @staticmethod
    def _hata_kodu(hata: Exception) -> str:
        if isinstance(hata, urllib.error.HTTPError) and hata.code in (403, 429):
            return "limit"
        return "ag_hatasi"

    # -- genel ---------------------------------------------------------------

    def son_yayin(self, etag: str | None = None) -> tuple[str, Yayin | None, str | None]:
        """`("yeni", yayin, etag)`, `("degismedi", None, etag)` ya da `("yok", None, None)`.

        Uygun "Latest" yoksa (404, taslak, ön sürüm, eksik varlık...) "yok".
        Ağ/limit hatasında `GuncellemeHatasi`. 304 limit yemez (ETag'in amacı).
        """
        baslik = {"Accept": "application/vnd.github+json"}
        if etag:
            baslik["If-None-Match"] = etag
        url = f"{self.api_taban}/repos/{self.depo}/releases/latest"
        try:
            with self._istek(url, baslik) as yanit:
                ham = yanit.read(_MAKS_JSON + 1)
                yeni_etag = yanit.headers.get("ETag")
        except urllib.error.HTTPError as hata:
            if hata.code == 304:
                return "degismedi", None, etag
            if hata.code == 404:
                return "yok", None, None
            raise GuncellemeHatasi(self._hata_kodu(hata), f"HTTP {hata.code}") from hata
        except (urllib.error.URLError, OSError, ValueError) as hata:
            raise GuncellemeHatasi("ag_hatasi", type(hata).__name__) from hata
        if len(ham) > _MAKS_JSON:
            raise GuncellemeHatasi("bozuk_yanit", "yanıt çok büyük")
        try:
            veri = json.loads(ham.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as hata:
            raise GuncellemeHatasi("bozuk_yanit", "geçersiz JSON") from hata
        yayin = yayin_coz(veri, self.depo, self.ek_sunucular)
        return ("yeni", yayin, yeni_etag) if yayin else ("yok", None, yeni_etag)

    def metin_indir(self, url: str) -> str:
        """Küçük bir metin dosyası (SHA256SUMS.txt)."""
        try:
            with self._istek(url) as yanit:
                ham = yanit.read(_MAKS_OZET + 1)
        except (urllib.error.URLError, OSError, ValueError) as hata:
            raise GuncellemeHatasi("ag_hatasi", type(hata).__name__) from hata
        if len(ham) > _MAKS_OZET:
            raise GuncellemeHatasi("bozuk_yanit", "özet dosyası çok büyük")
        return ham.decode("utf-8", errors="replace")

    def indir(self, url: str, hedef: Path, beklenen_boyut: int) -> str:
        """`url`'yi `hedef`'e indirir ve SHA-256'sını döndürür.

        Önce `<hedef>.part`'a yazılır, tamamlanınca hedefe taşınır; her hatada
        kısmi dosya silinir. Boyut `beklenen_boyut`'tan farklıysa (kesik ya da
        taşan akış) iptal: sunucunun bildirdiğinden fazlasını diske yazmıyoruz.
        """
        gecici = hedef.with_name(hedef.name + ".part")
        ozet = hashlib.sha256()
        toplam = 0
        try:
            hedef.parent.mkdir(parents=True, exist_ok=True)
            with self._istek(url) as yanit, open(gecici, "wb") as cikti:
                while True:
                    parca = yanit.read(_PARCA)
                    if not parca:
                        break
                    toplam += len(parca)
                    if toplam > beklenen_boyut:
                        raise GuncellemeHatasi("boyut_uyusmuyor", "beklenenden büyük")
                    ozet.update(parca)
                    cikti.write(parca)
            if toplam != beklenen_boyut:
                raise GuncellemeHatasi("boyut_uyusmuyor", f"{toplam} != {beklenen_boyut}")
            os.replace(gecici, hedef)
        except GuncellemeHatasi:
            _sil(gecici)
            raise
        except PermissionError as hata:
            _sil(gecici)
            raise GuncellemeHatasi("izin_yok", type(hata).__name__) from hata
        except (urllib.error.URLError, OSError, ValueError) as hata:
            _sil(gecici)
            raise GuncellemeHatasi("ag_hatasi", type(hata).__name__) from hata
        return ozet.hexdigest()


def _sil(yol: Path) -> None:
    try:
        yol.unlink()
    except OSError:
        pass


class _Yonlendirme(urllib.request.HTTPRedirectHandler):
    """Yönlendirmeyi yalnızca izinli sunuculara izin verir (GitHub depolaması)."""

    def __init__(self, ag: Ag) -> None:
        self._ag = ag

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not adres_uygun(newurl, self._ag.depo, self._ag.ek_sunucular):
            raise urllib.error.URLError(f"izinsiz yönlendirme: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Dışarıdan okunabilsin (testler, belgeler).
IZINLI = IZINLI_SUNUCULAR
