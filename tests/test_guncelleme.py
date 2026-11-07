"""Otomatik güncelleme: sürüm, release çözümleme, ağ, doğrulama, exe değiştirme.

Ağ testleri yerel sahte bir "GitHub" sunucusuyla koşar (gerçek ağ yok);
exe değiştirme testleri geçici bir klasördeki sahte `Takvim.exe`'lerle,
gerçek kullanıcı kurulumuna DOKUNMADAN.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import shutil
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from guncelleme import kurulum
from guncelleme.ag import Ag, GuncellemeHatasi
from guncelleme.hizmet import Guncelleyici
from guncelleme.saf import (
    MAKS_EXE_BAYT,
    daha_yeni_mi,
    ozet_coz,
    surum_coz,
    yayin_coz,
)

DEPO = "tungarix/takvim"
YENI_EXE = b"MZ-yeni-surum" * 1000
ESKI_EXE = b"MZ-eski-surum" * 1000


# ---------------------------------------------------------------------------
# sürüm
# ---------------------------------------------------------------------------

def test_surum_sayisal_karsilastirilir():
    assert daha_yeni_mi("1.10.0", "1.9.0")  # metin sırasıyla 1.10 < 1.9 olurdu
    assert daha_yeni_mi("v1.10.0", "1.9.0")
    assert daha_yeni_mi("2.0.0", "1.99.99")


def test_ayni_ve_eski_surum_teklif_edilmez():
    assert not daha_yeni_mi("1.9.0", "1.9.0")
    assert not daha_yeni_mi("1.8.9", "1.9.0")


@pytest.mark.parametrize("kotu", ["1.10", "1.10.0-beta", "bir.iki.uc", "", "1.2.3.4", None, 5])
def test_taninmayan_surum_teklif_edilmez(kotu):
    assert surum_coz(kotu) is None
    assert not daha_yeni_mi(kotu, "1.9.0")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# release çözümleme
# ---------------------------------------------------------------------------

def _release(**degisiklik):
    taban = "https://github.com/tungarix/takvim/releases/download/v1.10.0"
    veri = {
        "tag_name": "v1.10.0", "draft": False, "prerelease": False,
        "html_url": "https://github.com/tungarix/takvim/releases/tag/v1.10.0",
        "assets": [
            {"name": "Takvim.exe", "size": 21_000_000, "browser_download_url": f"{taban}/Takvim.exe"},
            {"name": "SHA256SUMS.txt", "size": 90, "browser_download_url": f"{taban}/SHA256SUMS.txt"},
        ],
    }
    veri.update(degisiklik)
    return veri


def test_gecerli_release_cozulur():
    y = yayin_coz(_release(), DEPO)
    assert y is not None
    assert (y.surum, y.exe_boyut) == ("1.10.0", 21_000_000)
    assert y.exe_url.endswith("/Takvim.exe") and y.ozet_url.endswith("/SHA256SUMS.txt")


@pytest.mark.parametrize("degisiklik", [
    {"draft": True},
    {"prerelease": True},
    {"tag_name": "v1.10.0-rc1"},
    {"tag_name": "nightly"},
    {"assets": None},
    {"assets": []},
])
def test_uygunsuz_release_teklif_edilmez(degisiklik):
    assert yayin_coz(_release(**degisiklik), DEPO) is None


def test_govde_sozluk_degilse_teklif_yok():
    assert yayin_coz([1, 2], DEPO) is None
    assert yayin_coz("x", DEPO) is None


def test_beklenen_ada_sahip_varlik_sart():
    # Başka adlı exe (Takvim-1.10.0.exe) sessizce kabul edilmez: sözleşme sabit ad.
    r = _release()
    r["assets"][0]["name"] = "Takvim-1.10.0.exe"
    assert yayin_coz(r, DEPO) is None
    r = _release()
    r["assets"].pop(1)
    assert yayin_coz(r, DEPO) is None


@pytest.mark.parametrize("boyut", [0, -5, MAKS_EXE_BAYT + 1, "21", True, None, 1.5])
def test_gecersiz_boyut_reddedilir(boyut):
    r = _release()
    r["assets"][0]["size"] = boyut
    assert yayin_coz(r, DEPO) is None


@pytest.mark.parametrize("adres", [
    "http://github.com/tungarix/takvim/releases/download/v1.10.0/Takvim.exe",  # http
    "https://evil.example/Takvim.exe",  # başka sunucu
    "https://github.com/baskasi/depo/releases/download/v1/Takvim.exe",  # başka depo
    "https://user:pw@github.com/tungarix/takvim/releases/download/v1/Takvim.exe",
    "https://github.com.evil.example/tungarix/takvim/releases/download/v1/Takvim.exe",
    "file:///C:/Takvim.exe",
    None,
])
def test_izinsiz_adres_reddedilir(adres):
    r = _release()
    r["assets"][0]["browser_download_url"] = adres
    assert yayin_coz(r, DEPO) is None


def test_bilinen_depolama_sunucusu_kabul_edilir():
    r = _release()
    r["assets"][0]["browser_download_url"] = "https://objects.githubusercontent.com/x/Takvim.exe"
    assert yayin_coz(r, DEPO) is not None


def test_ayni_adli_ikinci_varlik_yok_sayilir():
    r = _release()
    r["assets"].append({"name": "Takvim.exe", "size": 5, "browser_download_url": "https://evil.example/x"})
    assert yayin_coz(r, DEPO).exe_boyut == 21_000_000  # ilk eşleşme


# ---------------------------------------------------------------------------
# SHA256SUMS.txt
# ---------------------------------------------------------------------------

H = "a" * 64


def test_ozet_okunur():
    assert ozet_coz(f"{H}  Takvim.exe\n") == H
    assert ozet_coz(f"{H.upper()} *Takvim.exe") == H  # ikili kip işareti, büyük harf
    assert ozet_coz(f"{'b' * 64}  baska.txt\n{H}  Takvim.exe\n") == H


@pytest.mark.parametrize("metin", [
    "", "bozuk", f"{H}  baska.exe", f"{'a' * 63}  Takvim.exe", f"{'z' * 64}  Takvim.exe",
    f"{H}  Takvim.exe\n{'b' * 64}  Takvim.exe",  # belirsiz: iki farklı satır
])
def test_belirsiz_ozet_none(metin):
    assert ozet_coz(metin) is None


# ---------------------------------------------------------------------------
# sahte GitHub
# ---------------------------------------------------------------------------

class _Sahte:
    """Her testte yeniden yapılandırılabilen yerel sunucu."""

    def __init__(self) -> None:
        self.istekler: list[tuple[str, dict]] = []
        self.release_durum = 200
        self.release_govde: bytes | None = None
        self.etag = '"v1"'
        self.exe = YENI_EXE
        self.exe_kes = False  # akışı yarıda bırak
        self.ozet = hashlib.sha256(YENI_EXE).hexdigest()
        self.ozet_metni: str | None = None
        self.yonlendir_exe: str | None = None
        self.httpd: http.server.ThreadingHTTPServer | None = None

    def adres(self, yol: str = "") -> str:
        assert self.httpd is not None
        return f"http://127.0.0.1:{self.httpd.server_address[1]}{yol}"

    def release_json(self, surum: str = "1.10.0", boyut: int | None = None) -> bytes:
        return json.dumps({
            "tag_name": f"v{surum}", "draft": False, "prerelease": False,
            "html_url": self.adres("/sayfa"),
            "assets": [
                {"name": "Takvim.exe", "size": len(self.exe) if boyut is None else boyut,
                 "browser_download_url": self.adres("/dl/Takvim.exe")},
                {"name": "SHA256SUMS.txt", "size": 90, "browser_download_url": self.adres("/dl/SHA256SUMS.txt")},
            ],
        }).encode()


@pytest.fixture
def sahte():
    s = _Sahte()

    class Isleyici(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):  # sessiz
            pass

        def do_GET(self):
            s.istekler.append((self.path, dict(self.headers)))
            if self.path.endswith("/releases/latest"):
                if s.release_durum != 200:
                    self.send_response(s.release_durum)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.headers.get("If-None-Match") == s.etag:
                    self.send_response(304)
                    self.end_headers()
                    return
                govde = s.release_govde if s.release_govde is not None else s.release_json()
                self.send_response(200)
                self.send_header("ETag", s.etag)
                self.send_header("Content-Length", str(len(govde)))
                self.end_headers()
                self.wfile.write(govde)
            elif self.path == "/dl/Takvim.exe":
                if s.yonlendir_exe:
                    self.send_response(302)
                    self.send_header("Location", s.yonlendir_exe)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(s.exe)))
                self.end_headers()
                self.wfile.write(s.exe[: len(s.exe) // 2] if s.exe_kes else s.exe)
                if s.exe_kes:
                    self.wfile.flush()
                    self.connection.close()
            elif self.path == "/dl/SHA256SUMS.txt":
                metin = s.ozet_metni if s.ozet_metni is not None else f"{s.ozet}  Takvim.exe\n"
                veri = metin.encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(veri)))
                self.end_headers()
                self.wfile.write(veri)
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

    s.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Isleyici)
    threading.Thread(target=s.httpd.serve_forever, daemon=True).start()
    yield s
    s.httpd.shutdown()
    s.httpd.server_close()


def _ag(s: _Sahte) -> Ag:
    return Ag(DEPO, "1.9.0", api_taban=s.adres(), ek_sunucular=frozenset({"127.0.0.1"}), zaman_asimi=5)


# ---------------------------------------------------------------------------
# ağ
# ---------------------------------------------------------------------------

def test_son_yayin_okunur_ve_basliklar_dogru(sahte):
    durum, y, etag = _ag(sahte).son_yayin()
    assert durum == "yeni" and y is not None and y.surum == "1.10.0" and etag == '"v1"'
    yol, basliklar = sahte.istekler[0]
    assert yol == f"/repos/{DEPO}/releases/latest"
    assert basliklar["User-Agent"] == "Takvim/1.9.0"
    # Veri sızmıyor: çerez/yetki başlığı yok.
    assert not {"Cookie", "Authorization"} & set(basliklar)


def test_etag_ile_304_degismedi(sahte):
    ag = _ag(sahte)
    _, _, etag = ag.son_yayin()
    durum, y, etag2 = ag.son_yayin(etag)
    assert (durum, y, etag2) == ("degismedi", None, etag)
    assert sahte.istekler[-1][1]["If-None-Match"] == '"v1"'


def test_404_uygun_surum_yok(sahte):
    sahte.release_durum = 404
    assert _ag(sahte).son_yayin()[:2] == ("yok", None)


@pytest.mark.parametrize("kod", [403, 429])
def test_limit_hatasi(sahte, kod):
    sahte.release_durum = kod
    with pytest.raises(GuncellemeHatasi) as h:
        _ag(sahte).son_yayin()
    assert h.value.kod == "limit"


def test_sunucu_hatasi_ag_hatasi(sahte):
    sahte.release_durum = 500
    with pytest.raises(GuncellemeHatasi) as h:
        _ag(sahte).son_yayin()
    assert h.value.kod == "ag_hatasi"


@pytest.mark.parametrize("govde", [b"{bozuk", bytes([255, 254]), "BUYUK"], ids=["json", "utf8", "buyuk"])
def test_bozuk_json(sahte, govde):
    sahte.release_govde = b"x" * (1024 * 1024 + 10) if govde == "BUYUK" else govde
    with pytest.raises(GuncellemeHatasi) as h:
        _ag(sahte).son_yayin()
    assert h.value.kod == "bozuk_yanit"


def test_taslak_release_teklif_edilmez(sahte):
    veri = json.loads(sahte.release_json())
    veri["draft"] = True
    sahte.release_govde = json.dumps(veri).encode()
    assert _ag(sahte).son_yayin()[:2] == ("yok", None)


def test_sunucu_kapaliyken_ag_hatasi():
    ag = Ag(DEPO, "1.9.0", api_taban="http://127.0.0.1:1", ek_sunucular=frozenset({"127.0.0.1"}), zaman_asimi=2)
    with pytest.raises(GuncellemeHatasi) as h:
        ag.son_yayin()
    assert h.value.kod == "ag_hatasi"


def test_izinsiz_sunucuya_istek_hic_gitmez(sahte):
    ag = Ag(DEPO, "1.9.0")  # ek sunucu yok: üretim ayarı
    with pytest.raises(GuncellemeHatasi) as h:
        ag.metin_indir(sahte.adres("/dl/SHA256SUMS.txt"))
    assert h.value.kod == "adres_izinsiz" and sahte.istekler == []


def test_izinsiz_yonlendirme_reddedilir(sahte):
    sahte.yonlendir_exe = "http://evil.example/Takvim.exe"
    with pytest.raises(GuncellemeHatasi) as h:
        _ag(sahte).indir(sahte.adres("/dl/Takvim.exe"), Path("x.exe"), len(YENI_EXE))
    assert h.value.kod == "ag_hatasi"


# ---------------------------------------------------------------------------
# indirme + doğrulama
# ---------------------------------------------------------------------------

def _yayin(sahte, boyut=None):
    return yayin_coz(json.loads(sahte.release_json(boyut=boyut)), DEPO, frozenset({"127.0.0.1"}))


def test_dogru_dosya_indirilir_ve_dogrulanir(sahte, tmp_path):
    yol, ozet = kurulum.hazirla(_ag(sahte), _yayin(sahte), tmp_path / "g")
    assert ozet == hashlib.sha256(YENI_EXE).hexdigest()
    assert yol.name == "Takvim-1.10.0.exe" and yol.read_bytes() == YENI_EXE
    assert not list((tmp_path / "g").glob("*.part"))


def test_ozet_uyusmazligi_dosyayi_siler(sahte, tmp_path):
    sahte.ozet = hashlib.sha256(b"baska").hexdigest()
    with pytest.raises(GuncellemeHatasi) as h:
        kurulum.hazirla(_ag(sahte), _yayin(sahte), tmp_path / "g")
    assert h.value.kod == "ozet_uyusmuyor"
    assert list((tmp_path / "g").iterdir()) == []


def test_ozet_satiri_yoksa_indirmeden_iptal(sahte, tmp_path):
    sahte.ozet_metni = f"{H}  baska.exe\n"
    with pytest.raises(GuncellemeHatasi) as h:
        kurulum.hazirla(_ag(sahte), _yayin(sahte), tmp_path / "g")
    assert h.value.kod == "ozet_bulunamadi"
    assert all(yol != "/dl/Takvim.exe" for yol, _ in sahte.istekler)  # exe hiç indirilmedi


def test_kesik_indirme_kismi_dosya_birakmaz(sahte, tmp_path):
    sahte.exe_kes = True
    with pytest.raises(GuncellemeHatasi):
        kurulum.hazirla(_ag(sahte), _yayin(sahte), tmp_path / "g")
    assert list((tmp_path / "g").iterdir()) == []


def test_bildirilenden_buyuk_akis_iptal(sahte, tmp_path):
    y = _yayin(sahte, boyut=100)  # sunucu 13 000 bayt yollar
    with pytest.raises(GuncellemeHatasi) as h:
        kurulum.hazirla(_ag(sahte), y, tmp_path / "g")
    assert h.value.kod == "boyut_uyusmuyor"
    assert list((tmp_path / "g").iterdir()) == []


def test_bildirilenden_kucuk_akis_iptal(sahte, tmp_path):
    y = _yayin(sahte, boyut=len(YENI_EXE) + 50)
    with pytest.raises(GuncellemeHatasi) as h:
        kurulum.hazirla(_ag(sahte), y, tmp_path / "g")
    assert h.value.kod == "boyut_uyusmuyor"


def test_eski_indirmeler_temizlenir(sahte, tmp_path):
    g = tmp_path / "g"
    g.mkdir()
    (g / "Takvim-1.0.0.exe").write_bytes(b"x")
    (g / "Takvim-1.0.1.exe.part").write_bytes(b"x")
    kurulum.hazirla(_ag(sahte), _yayin(sahte), g)
    assert sorted(p.name for p in g.iterdir()) == ["Takvim-1.10.0.exe"]


# ---------------------------------------------------------------------------
# Guncelleyici (durum, aralık, teklif)
# ---------------------------------------------------------------------------

def _hizmet(sahte, tmp_path, surum="1.9.0", simdi=None, exe=None):
    return Guncelleyici(
        tmp_path, surum, ag=_ag(sahte), simdi=simdi or (lambda: datetime(2026, 11, 7, 12, tzinfo=UTC)),
        exe_yolu=exe,
    )


def test_denetim_yeni_surumu_saklar_ve_bir_sonraki_acilista_hatirlar(sahte, tmp_path):
    d = _hizmet(sahte, tmp_path).denetle()
    assert d["yeni"]["surum"] == "1.10.0" and d["hata_kodu"] is None
    # Yeni örnek (uygulama yeniden açıldı): ağsız bile teklifi biliyor.
    assert _hizmet(sahte, tmp_path).durum()["yeni"]["surum"] == "1.10.0"
    # İkinci denetim ETag ile 304 alır ve teklif kalır.
    hizmet = _hizmet(sahte, tmp_path)
    assert hizmet.denetle()["yeni"]["surum"] == "1.10.0"
    assert sahte.istekler[-1][1]["If-None-Match"] == '"v1"'


def test_eski_ya_da_ayni_surum_teklif_edilmez(sahte, tmp_path):
    assert _hizmet(sahte, tmp_path, surum="1.10.0").denetle()["yeni"] is None
    assert _hizmet(sahte, tmp_path, surum="2.0.0").denetle()["yeni"] is None


def test_guncelleme_sonrasi_saklı_teklif_dusurulur(sahte, tmp_path):
    _hizmet(sahte, tmp_path).denetle()
    # Uygulama 1.10.0'a güncellendi: eski teklif artık teklif değil.
    assert _hizmet(sahte, tmp_path, surum="1.10.0").durum()["yeni"] is None


def test_ag_hatasi_kodlanir_ve_teklifi_silmez(sahte, tmp_path):
    h = _hizmet(sahte, tmp_path)
    h.denetle()
    sahte.release_durum = 403
    d = h.denetle()
    assert d["hata_kodu"] == "limit" and d["yeni"]["surum"] == "1.10.0"
    assert d["son_denetim"] is not None  # kötü ağda her açılışta yeniden denenmez


def test_yayin_kalkarsa_teklif_kalkar(sahte, tmp_path):
    h = _hizmet(sahte, tmp_path)
    h.denetle()
    sahte.release_durum = 404
    assert h.denetle()["yeni"] is None


def test_gunde_en_cok_bir_denetim(sahte, tmp_path):
    an = [datetime(2026, 11, 7, 12, tzinfo=UTC)]
    h = _hizmet(sahte, tmp_path, simdi=lambda: an[0])
    assert h.denetim_zamani_geldi()  # hiç denetlenmedi
    h.denetle()
    assert not h.denetim_zamani_geldi()
    an[0] += timedelta(hours=23, minutes=59)
    assert not h.denetim_zamani_geldi()
    an[0] += timedelta(minutes=2)
    assert h.denetim_zamani_geldi()
    an[0] = datetime(2026, 11, 6, tzinfo=UTC)  # saat geri alındı
    assert h.denetim_zamani_geldi()


def test_bozuk_durum_dosyasi_hic_denetlenmedi_sayilir(sahte, tmp_path):
    (tmp_path / "guncelleme.json").write_text("{bozuk", encoding="utf-8")
    h = _hizmet(sahte, tmp_path)
    assert h.durum()["yeni"] is None and h.denetim_zamani_geldi()


def test_elle_bozulmus_saklı_adres_teklif_olmaz(sahte, tmp_path):
    h = _hizmet(sahte, tmp_path)
    h.denetle()
    yol = tmp_path / "guncelleme.json"
    veri = json.loads(yol.read_text(encoding="utf-8"))
    veri["yayin"]["exe_url"] = "https://evil.example/Takvim.exe"
    yol.write_text(json.dumps(veri), encoding="utf-8")
    assert _hizmet(sahte, tmp_path).durum()["yeni"] is None


def test_bilinmeyen_surum_kurulmaz(sahte, tmp_path):
    exe = tmp_path / "Takvim.exe"
    exe.write_bytes(ESKI_EXE)
    h = _hizmet(sahte, tmp_path, exe=exe)
    h.denetle()
    with pytest.raises(GuncellemeHatasi) as hata:
        h.kurulum_hazirla("9.9.9")
    assert hata.value.kod == "surum_bilinmiyor"


def test_kurulum_hazirla_dogrulanmis_exe_verir(sahte, tmp_path):
    exe = tmp_path / "Takvim.exe"
    exe.write_bytes(ESKI_EXE)
    h = _hizmet(sahte, tmp_path, exe=exe)
    h.denetle()
    yeni, eski, ozet = h.kurulum_hazirla("1.10.0")
    assert yeni.read_bytes() == YENI_EXE and eski == exe
    assert ozet == hashlib.sha256(YENI_EXE).hexdigest()


def test_exe_yok_ya_da_paketli_degilse_kurulamaz(sahte, tmp_path):
    h = _hizmet(sahte, tmp_path, exe=None)  # geliştirme ortamı (paketli değil)
    h.denetle()
    assert h.durum()["kurulabilir"] is False
    with pytest.raises(GuncellemeHatasi) as hata:
        h.kurulum_hazirla("1.10.0")
    assert hata.value.kod == "kurulamaz"


def test_yazma_izni_yoksa_kurulabilir_degil(tmp_path, monkeypatch):
    exe = tmp_path / "Takvim.exe"
    exe.write_bytes(b"x")
    assert kurulum.kurulabilir_mi(exe) is True

    def reddet(self, *a, **k):
        raise PermissionError

    monkeypatch.setattr(Path, "write_bytes", reddet)
    assert kurulum.kurulabilir_mi(exe) is False
    assert kurulum.kurulabilir_mi(tmp_path / "yok.exe") is False


# ---------------------------------------------------------------------------
# exe değiştirme (geçici dosyalar; gerçek kurulum yok)
# ---------------------------------------------------------------------------

@pytest.fixture
def exeler(tmp_path):
    eski = tmp_path / "Takvim.exe"
    yeni = tmp_path / "guncelleme" / "Takvim-1.10.0.exe"
    yeni.parent.mkdir()
    eski.write_bytes(ESKI_EXE)
    yeni.write_bytes(YENI_EXE)
    baslatilan: list[list[str]] = []
    return eski, yeni, baslatilan


def _tamamla(exeler, **kw):
    eski, yeni, baslatilan = exeler
    kw.setdefault("sure", 1.0)
    kw.setdefault("uyku", 0.02)
    return kurulum.tamamla(yeni, eski, 0, pid_bekle=lambda p, s: None, baslat=baslatilan.append, **kw)


def test_degistirme_basarili(exeler):
    eski, _, baslatilan = exeler
    assert _tamamla(exeler) is True
    assert eski.read_bytes() == YENI_EXE
    assert (eski.parent / "Takvim.eski.exe").read_bytes() == ESKI_EXE  # geri dönüş yolu duruyor
    assert baslatilan == [[str(eski)]]  # kısayolun gösterdiği yol aynı kaldı
    assert not (eski.parent / "Takvim.exe.yeni").exists()


def test_kopya_saglamasi_tutmazsa_eski_surum_geri_gelir(exeler, monkeypatch):
    eski, _, baslatilan = exeler

    def bozuk_kopya(kaynak, hedef, **k):
        Path(hedef).write_bytes(b"bozuk")
        return hedef

    monkeypatch.setattr(shutil, "copyfile", bozuk_kopya)
    assert _tamamla(exeler) is False
    assert eski.read_bytes() == ESKI_EXE  # kullanıcı hiç kurulum yapılmamış gibi devam eder
    assert not (eski.parent / "Takvim.eski.exe").exists()
    assert not (eski.parent / "Takvim.exe.yeni").exists()
    assert baslatilan == [[str(eski)]]  # ESKİ sürüm açıldı


def test_yerine_koyma_patlarsa_geri_alinir(exeler, monkeypatch):
    eski, _, baslatilan = exeler
    gercek = os.replace

    def replace(kaynak, hedef):
        if str(hedef) == str(eski) and str(kaynak).endswith(".yeni"):
            raise OSError("disk dolu")
        return gercek(kaynak, hedef)

    monkeypatch.setattr(os, "replace", replace)
    assert _tamamla(exeler) is False
    assert eski.read_bytes() == ESKI_EXE
    assert baslatilan == [[str(eski)]]


def test_kilit_acilmazsa_eskiye_dokunulmaz(exeler, monkeypatch):
    eski, _, baslatilan = exeler

    def kilitli(kaynak, hedef):
        raise PermissionError("kullanımda")

    monkeypatch.setattr(os, "replace", kilitli)
    t0 = time.monotonic()
    assert _tamamla(exeler, sure=0.3) is False
    assert time.monotonic() - t0 < 5
    assert eski.read_bytes() == ESKI_EXE
    assert baslatilan == [[str(eski)]]


def test_gecici_kilit_yeniden_denenir(exeler, monkeypatch):
    eski, _, _ = exeler
    gercek = os.replace
    sayac = {"n": 0}

    def replace(kaynak, hedef):
        sayac["n"] += 1
        if sayac["n"] <= 3:
            raise PermissionError("önyükleyici hâlâ kilitli")
        return gercek(kaynak, hedef)

    monkeypatch.setattr(os, "replace", replace)
    assert _tamamla(exeler, sure=3.0) is True
    assert eski.read_bytes() == YENI_EXE


@pytest.mark.skipif(sys.platform != "win32", reason="Windows dosya kilidi")
def test_gercek_windows_kilidi_kalkinca_degistirir(exeler):
    """Çalışan exe'nin kilidini Python `open` ile taklit eder (silme/taşıma paylaşımı yok)."""
    eski, _, _ = exeler
    tutamak = open(eski, "rb")
    with pytest.raises(PermissionError):
        os.replace(eski, eski.with_name("deneme.exe"))  # kilidin gerçek olduğunu doğrula

    def birak():
        time.sleep(0.4)
        tutamak.close()

    threading.Thread(target=birak).start()
    assert _tamamla(exeler, sure=5.0) is True
    assert eski.read_bytes() == YENI_EXE


def test_ilk_acilista_eski_exe_yoksa_yenisi_kurulur(exeler):
    eski, _, _ = exeler
    eski.unlink()
    assert _tamamla(exeler) is True
    assert eski.read_bytes() == YENI_EXE


def test_artiklar_temizlenir(exeler):
    eski, yeni, _ = exeler
    (eski.parent / "Takvim.eski.exe").write_bytes(b"x")
    kurulum.eski_artiklari_temizle(eski, yeni.parent)
    assert not (eski.parent / "Takvim.eski.exe").exists() and not yeni.parent.exists()
    kurulum.eski_artiklari_temizle(eski, yeni.parent)  # ikinci çağrı hata vermez


def test_sonsuz_akis_bildirilen_boyutta_kesilir(tmp_path, monkeypatch):
    """Sunucu bildirdiğinden fazlasını yollarsa diske yazmaya DEVAM edilmez (disk doldurma)."""
    okuma = {"n": 0}

    class SonsuzYanit:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            okuma["n"] += 1
            assert okuma["n"] < 50, "sınırsız okunuyor"
            return b"x" * n

    ag = Ag(DEPO, "1.9.0")
    monkeypatch.setattr(ag, "_istek", lambda url, baslik=None: SonsuzYanit())
    with pytest.raises(GuncellemeHatasi) as h:
        ag.indir("https://github.com/tungarix/takvim/releases/download/v1/Takvim.exe", tmp_path / "x.exe", 100)
    assert h.value.kod == "boyut_uyusmuyor" and okuma["n"] == 1
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# güvenlik incelemesi düzeltmeleri (v1.10.0)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("adres", [
    "https://github.com/tungarix/takvim/releases/../../evil/x/releases/a",
    "https://github.com/tungarix/takvim/releases/%2e%2e/%2e%2e/evil",
    "https://github.com/tungarix/takvim/releases/a%2Fb",
    "https://github.com:8443/tungarix/takvim/releases/download/v1/Takvim.exe",
    "https://api.github.com\t/x",
    "https://api.github.com/x y",
    "https://api.github.com/x\r\nX: y",
    " https://api.github.com/x",
    "https://api.github.com/x\\y",
    "https://api.github.com/\u0131",
])
def test_adres_denetimi_ayristirici_farklarini_kapatir(adres):
    from guncelleme.saf import adres_uygun

    assert adres_uygun(adres, DEPO, frozenset()) is False


def test_adres_denetimi_mesru_adresleri_kabul_eder():
    from guncelleme.saf import adres_uygun

    for a in (
        "https://api.github.com/repos/tungarix/takvim/releases/latest",
        "https://github.com/tungarix/takvim/releases/download/v1.10.0/Takvim.exe",
        "https://github.com:443/tungarix/takvim/releases/download/v1.10.0/Takvim.exe",
        "https://objects.githubusercontent.com/github-production-release-asset/1/2?X-Amz=abc&response-content-disposition=attachment",
    ):
        assert adres_uygun(a, DEPO, frozenset()) is True, a


def test_tamamla_ozet_tutmazsa_eskiye_dokunmadan_eski_surum_acilir(exeler):
    eski, _, baslatilan = exeler
    assert _tamamla(exeler, beklenen_ozet="0" * 64) is False
    assert eski.read_bytes() == ESKI_EXE
    assert not (eski.parent / "Takvim.eski.exe").exists()
    assert baslatilan == [[str(eski)]]


def test_tamamla_dogru_ozetle_calisir(exeler):
    eski, _, _ = exeler
    assert _tamamla(exeler, beklenen_ozet=hashlib.sha256(YENI_EXE).hexdigest().upper()) is True
    assert eski.read_bytes() == YENI_EXE


def test_yerine_koymadaki_gecici_kilit_yeniden_denenir(exeler, monkeypatch):
    """Antivirüs yeni kopyayı kısa süre kilitleyebilir: geri almaya düşmeden yeniden dene."""
    eski, _, _ = exeler
    gercek = os.replace
    sayac = {"n": 0}

    def replace(kaynak, hedef):
        if str(kaynak).endswith(".yeni"):
            sayac["n"] += 1
            if sayac["n"] <= 2:
                raise PermissionError("antivirüs")
        return gercek(kaynak, hedef)

    monkeypatch.setattr(os, "replace", replace)
    assert _tamamla(exeler, sure=3.0) is True
    assert eski.read_bytes() == YENI_EXE and sayac["n"] == 3


def test_tamamla_komutu_ozet_zorunlu_ve_gecerli(tmp_path, monkeypatch):
    import sys

    from guncelleme.kurulum import tamamla_komutu

    kendisi = tmp_path / "Yeni.exe"
    kendisi.write_bytes(YENI_EXE)
    monkeypatch.setattr(sys, "executable", str(kendisi))
    hedef = str(tmp_path / "Takvim.exe")
    with pytest.raises(SystemExit):  # --sha256 olmadan argparse reddeder
        tamamla_komutu(["--guncelle-tamamla", "--eski", hedef])
    assert tamamla_komutu(["--guncelle-tamamla", "--eski", hedef, "--sha256", "xyz"]) == 2


def test_tamamlamayi_baslat_hemen_kapanan_surec_hata_verir(monkeypatch, tmp_path):
    class Olu:
        def poll(self):
            return 1

    monkeypatch.setattr(kurulum, "_baslat", lambda komut: Olu())
    with pytest.raises(OSError):
        kurulum.tamamlamayi_baslat(tmp_path / "a.exe", tmp_path / "b.exe", "a" * 64, bekle=0)


def test_tamamlamayi_baslat_ozeti_komuta_koyar(monkeypatch, tmp_path):
    komutlar: list = []

    class Canli:
        def poll(self):
            return None

    monkeypatch.setattr(kurulum, "_baslat", lambda komut: (komutlar.append(komut), Canli())[1])
    kurulum.tamamlamayi_baslat(tmp_path / "a.exe", tmp_path / "b.exe", "ab" * 32, pid=7, bekle=0)
    assert komutlar[0][komutlar[0].index("--sha256") + 1] == "ab" * 32


def test_http_istisnalari_ag_hatasina_cevrilir(sahte, monkeypatch):
    import http.client

    ag = _ag(sahte)

    def patlat(*a, **k):
        raise http.client.IncompleteRead(b"x")

    monkeypatch.setattr(ag._acici, "open", patlat)
    with pytest.raises(GuncellemeHatasi) as h:
        ag.son_yayin()
    assert h.value.kod == "ag_hatasi"


def test_beklenmeyen_hata_da_son_denetimi_yazar(sahte, tmp_path):
    h = _hizmet(sahte, tmp_path)

    def patlat(etag=None):
        raise RuntimeError("beklenmedik")

    h.ag.son_yayin = patlat  # type: ignore[method-assign]
    d = h.denetle()
    assert d["hata_kodu"] == "ag_hatasi" and d["son_denetim"] is not None
    assert not h.denetim_zamani_geldi()  # her açılışta yeniden denenmez


def test_toplam_indirme_suresi_asilinca_iptal(tmp_path, monkeypatch):
    import guncelleme.ag as agmod

    class Yavas:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return b"x"

    ag = Ag(DEPO, "1.9.0")
    monkeypatch.setattr(ag, "_istek", lambda url, baslik=None: Yavas())
    monkeypatch.setattr(agmod, "TOPLAM_INDIRME_SN", -1.0)
    with pytest.raises(GuncellemeHatasi) as h:
        ag.indir("https://github.com/tungarix/takvim/releases/download/v1/Takvim.exe", tmp_path / "x.exe", 10_000)
    assert h.value.kod == "ag_hatasi"
    assert list(tmp_path.iterdir()) == []


def test_durum_arka_plan_denetimi_kilidi_tutarken_bile_cevap_verir(sahte, tmp_path):
    h = _hizmet(sahte, tmp_path)
    cevap: list = []
    with h._kilit:  # arka plan denetimi ağdayken kilit tutulur
        t = threading.Thread(target=lambda: cevap.append(h.durum()))
        t.start()
        t.join(2)
    assert cevap and cevap[0]["mevcut"] == "1.9.0"
