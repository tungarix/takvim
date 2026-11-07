"""Güncelleyici: denetim zamanı, ETag ve bulunan sürümün saklanması + kurulum hazırlığı.

Durum `guncelleme.json`'da (veritabanının yanında; bellek DB'sinde yalnız
bellekte). Kullanıcı verisi değil: bozuk/eksik dosya = "hiç denetlenmedi".
"""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .ag import Ag, GuncellemeHatasi
from .kurulum import hazirla, kurulabilir_mi
from .saf import MAKS_EXE_BAYT, Yayin, adres_uygun, daha_yeni_mi

__all__ = ["ARALIK", "Guncelleyici", "arka_plan_adimi"]

# Günde en çok bir denetim (plan §1.2). "Şimdi denetle" bu sınıra takılmaz: o,
# kullanıcının kendi isteği.
ARALIK = timedelta(hours=24)


def _simdi() -> datetime:
    return datetime.now(UTC)


class Guncelleyici:
    """Tek örnek; sunucu ve arka plan denetim thread'i paylaşır (kilitli)."""

    def __init__(
        self,
        veri_dizini: Path | None,
        surum: str,
        *,
        ag: Ag | None = None,
        simdi: Callable[[], datetime] = _simdi,
        exe_yolu: Path | None = None,
    ) -> None:
        self.surum = surum
        self.ag = ag or Ag(surum=surum)
        self._simdi = simdi
        self._dosya = veri_dizini / "guncelleme.json" if veri_dizini else None
        self.indirme_klasoru = veri_dizini / "guncelleme" if veri_dizini else None
        self._exe = exe_yolu if exe_yolu is not None else (
            Path(sys.executable) if getattr(sys, "frozen", False) else None
        )
        self._kilit = threading.RLock()
        self._durum: dict = self._oku()

    # -- saklama -------------------------------------------------------------

    def _oku(self) -> dict:
        if self._dosya is None:
            return {}
        try:
            ham = json.loads(self._dosya.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {}
        return ham if isinstance(ham, dict) else {}

    def _yaz(self) -> None:
        if self._dosya is None:
            return
        try:
            self._dosya.parent.mkdir(parents=True, exist_ok=True)
            self._dosya.write_text(json.dumps(self._durum, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # saklanamayan durum yalnızca bir sonraki açılışta yeniden sorgulatır

    def _bilinen_yayin(self) -> Yayin | None:
        """Saklı sürüm; dosya elle bozulmuş olabilir, adres/boyut yeniden doğrulanır."""
        ham = self._durum.get("yayin")
        if not isinstance(ham, dict):
            return None
        try:
            yayin = Yayin(
                surum=str(ham["surum"]), exe_url=str(ham["exe_url"]),
                exe_boyut=int(ham["exe_boyut"]), ozet_url=str(ham["ozet_url"]),
                sayfa_url=str(ham["sayfa_url"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if not 0 < yayin.exe_boyut <= MAKS_EXE_BAYT:
            return None
        if not all(
            adres_uygun(u, self.ag.depo, self.ag.ek_sunucular)
            for u in (yayin.exe_url, yayin.ozet_url, yayin.sayfa_url)
        ):
            return None
        return yayin if daha_yeni_mi(yayin.surum, self.surum) else None

    # -- genel ---------------------------------------------------------------

    def son_denetim(self) -> datetime | None:
        ham = self._durum.get("son_denetim")
        try:
            an = datetime.fromisoformat(ham) if isinstance(ham, str) else None
        except ValueError:
            return None
        return an if an is not None and an.tzinfo is not None else None

    def denetim_zamani_geldi(self) -> bool:
        """Son denetimden en az 24 saat geçti mi (ya da hiç denetlenmedi mi)."""
        son = self.son_denetim()
        simdi = self._simdi()
        # Saat geriye alındıysa (son gelecekte) beklemek yerine yeniden denetle.
        return son is None or son > simdi or simdi - son >= ARALIK

    def durum(self) -> dict:
        # Kilitsiz: arka plan denetimi ağdayken (kilit tutulurken) tek thread'li sunucu bu sorguda
        # takılmasın. Yalnızca anlık okuma; yazan taraf sözlüğü atomik tek anahtar atamalarıyla değiştirir.
        yayin = self._bilinen_yayin()
        son = self.son_denetim()
        return {
            "mevcut": self.surum,
            "yeni": {"surum": yayin.surum, "sayfa": yayin.sayfa_url} if yayin else None,
            "son_denetim": son.isoformat() if son else None,
            "hata_kodu": self._durum.get("hata_kodu"),
            "kurulabilir": self._exe is not None and kurulabilir_mi(self._exe),
        }

    def denetle(self) -> dict:
        """GitHub'a sorar; sonucu saklar ve `durum()`u döndürür.

        Ağ/limit hatası istisna atmaz: `hata_kodu` olarak saklanır (mevcut sürümle
        devam; kullanıcıya yalnızca Ayarlar'da görünür). Hatada da `son_denetim`
        yazılır: kötü bir ağda her açılışta yeniden denememek için.
        """
        with self._kilit:
            etag = self._durum.get("etag") if self._bilinen_yayin() else None
            try:
                sonuc, yayin, yeni_etag = self.ag.son_yayin(etag if isinstance(etag, str) else None)
            except GuncellemeHatasi as hata:
                self._durum["hata_kodu"] = hata.kod
            except Exception:
                self._durum["hata_kodu"] = "ag_hatasi"
            else:
                self._durum["hata_kodu"] = None
                if sonuc == "yeni" and yayin is not None:
                    self._durum["yayin"] = {
                        "surum": yayin.surum, "exe_url": yayin.exe_url,
                        "exe_boyut": yayin.exe_boyut, "ozet_url": yayin.ozet_url,
                        "sayfa_url": yayin.sayfa_url,
                    }
                    self._durum["etag"] = yeni_etag
                elif sonuc == "yok":
                    self._durum.pop("yayin", None)
                    self._durum.pop("etag", None)
                # "degismedi": saklı sürüm olduğu gibi kalır
            self._durum["son_denetim"] = self._simdi().isoformat()
            self._yaz()
            return self.durum()

    def kurulum_hazirla(self, surum: str) -> tuple[Path, Path, str]:
        """İstenen sürümü indirir ve doğrular; `(yeni_exe, eski_exe, sha256)` verir.

        `sha256` SHA256SUMS.txt'teki beklenen özet: yeni exe devri bunu yeniden doğrular
        (doğrulama ile kullanım arasındaki pencereyi daraltır).

        `surum` bilinen teklifle eşleşmezse (arayüz bayat/değiştirilmiş) reddedilir:
        yalnızca denetimin bulduğu sürüm kurulabilir.
        """
        with self._kilit:
            yayin = self._bilinen_yayin()
            if yayin is None or yayin.surum != surum:
                raise GuncellemeHatasi("surum_bilinmiyor", surum)
            if self._exe is None or self.indirme_klasoru is None or not kurulabilir_mi(self._exe):
                raise GuncellemeHatasi("kurulamaz", "exe yazılabilir bir konumda değil")
            yeni, ozet = hazirla(self.ag, yayin, self.indirme_klasoru)
            return yeni, self._exe, ozet


def arka_plan_adimi(g: Guncelleyici, denetim_acik: bool) -> bool:
    """Arka plan döngüsünün tek adımı; ağa GİTTİYSE True.

    Kural (plan §1.1): kullanıcı denetimi açmadıysa (kapalı ya da hiç sorulmadı)
    ağ isteği YOK. Açıksa en çok günde bir kez.
    """
    if not denetim_acik or not g.denetim_zamani_geldi():
        return False
    g.denetle()
    return True
