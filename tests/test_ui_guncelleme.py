"""Güncelleme uçları, ayar anahtarı ve arka plan kuralı ("denetim kapalıyken sıfır ağ").

Sahte GitHub ve exe değiştirme testleri `test_guncelleme.py`'de; burada sunucu kablolaması.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

import pytest

from guncelleme import Guncelleyici
from guncelleme.hizmet import arka_plan_adimi
from guncelleme.kurulum import tamamla_komutu
from store import Repo
from tests.helpers import IST
from tests.test_guncelleme import ESKI_EXE, YENI_EXE, _ag, sahte  # noqa: F401 - fixture
from ui.server import make_server

AN = datetime(2026, 11, 7, 12, tzinfo=UTC)


class _Olay(list):
    """Kancaların çağrı kaydı; `patlat` ile başlatma hatası taklit edilir."""

    patlat = False


@pytest.fixture
def uygulama(sahte, tmp_path):  # noqa: F811
    """Dosya veritabanlı sunucu + sahte GitHub'a bağlı güncelleyici (+ kayıt tutan kancalar)."""
    db = str(tmp_path / "takvim.db")
    repo = Repo.open(db, check_same_thread=False)
    repo.add_calendar("Ders", "#e0524a")
    exe = tmp_path / "Takvim.exe"
    exe.write_bytes(ESKI_EXE)
    httpd = make_server(repo, IST, host="127.0.0.1", port=0, db_yolu=db)
    httpd.guncelleyici = Guncelleyici(tmp_path, "1.9.0", ag=_ag(sahte), simdi=lambda: AN, exe_yolu=exe)
    olay = _Olay()

    def baslat(yeni, eski):
        if olay.patlat:
            raise OSError("başlatılamadı")
        olay.append(("baslat", yeni, eski))

    httpd.guncelleme_baslat = baslat
    httpd.guncelleme_kapat = lambda: olay.append(("kapat",))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    temel = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield temel, tmp_path, sahte, olay
    httpd.shutdown()
    httpd.server_close()
    repo.close()


def _istek(temel, yol, govde=None, basliklar=None):
    req = urllib.request.Request(
        temel + yol, method="GET" if govde is None else "POST",
        data=None if govde is None else json.dumps(govde).encode(),
        headers={"Content-Type": "application/json", **(basliklar or {})},
    )
    try:
        with urllib.request.urlopen(req) as y:
            return y.status, json.loads(y.read().decode())
    except urllib.error.HTTPError as h:
        return h.code, json.loads(h.read().decode() or "{}")


def _ag_istegi_sayisi(sahte):  # noqa: F811
    return len(sahte.istekler)


# -- ayar anahtarı ------------------------------------------------------------

def test_varsayilan_denetim_sorulmadi_ve_ag_yok(uygulama):
    temel, _, sahte, _ = uygulama  # noqa: F811
    kod, ayar = _istek(temel, "/api/ayarlar")
    assert kod == 200 and ayar["guncelleme_denetimi"] is None
    kod, durum = _istek(temel, "/api/guncelleme/durum")
    assert kod == 200 and durum["denetim"] is None and durum["yeni"] is None
    assert _ag_istegi_sayisi(sahte) == 0  # durum sorgusu ağa gitmez


@pytest.mark.parametrize("deger", [True, False])
def test_denetim_secimi_kaydedilir(uygulama, deger):
    temel, _, _, _ = uygulama
    assert _istek(temel, "/api/ayarlar", {"guncelleme_denetimi": deger})[1]["guncelleme_denetimi"] is deger
    assert _istek(temel, "/api/ayarlar")[1]["guncelleme_denetimi"] is deger
    # Başka bir ayarı kaydetmek seçimi silmiyor.
    _istek(temel, "/api/ayarlar", {"tema": "acik"})
    assert _istek(temel, "/api/ayarlar")[1]["guncelleme_denetimi"] is deger


@pytest.mark.parametrize("kotu", ["evet", 1, [], {}])
def test_denetim_bool_olmayan_400(uygulama, kotu):
    temel, _, _, _ = uygulama
    kod, govde = _istek(temel, "/api/ayarlar", {"guncelleme_denetimi": kotu})
    assert kod == 400 and govde["error_code"] == "ayar_tipi_gecersiz"


def test_elle_yazilmis_evet_secim_sayilmaz(tmp_path):
    from ui.ayarlar import ayar_dosyasi, ayar_oku

    yol = ayar_dosyasi(tmp_path)
    yol.write_text(json.dumps({"guncelleme_denetimi": "evet"}), encoding="utf-8")
    assert ayar_oku(yol)["guncelleme_denetimi"] is None  # sorulmamış: ağ isteği YOK
    yol.write_text(json.dumps({"guncelleme_denetimi": True}), encoding="utf-8")
    assert ayar_oku(yol)["guncelleme_denetimi"] is True


# -- denetle / durum -----------------------------------------------------------

def test_simdi_denetle_teklifi_bulur(uygulama):
    temel, _, sahte, _ = uygulama  # noqa: F811
    kod, d = _istek(temel, "/api/guncelleme/denetle", {})
    assert kod == 200 and d["yeni"]["surum"] == "1.10.0" and d["mevcut"] == "1.9.0"
    assert d["kurulabilir"] is True and d["denetim"] is None  # elle denetim, ayar yine de sorulmamış
    assert _istek(temel, "/api/guncelleme/durum")[1]["yeni"]["surum"] == "1.10.0"
    assert _ag_istegi_sayisi(sahte) == 1


def test_denetle_limit_hatasi_durumda_gorunur(uygulama):
    temel, _, sahte, _ = uygulama  # noqa: F811
    sahte.release_durum = 403
    kod, d = _istek(temel, "/api/guncelleme/denetle", {})
    assert kod == 200 and d["hata_kodu"] == "limit" and d["yeni"] is None


# -- kur -----------------------------------------------------------------------

def test_kur_dogrular_baslatir_sonra_kapatir(uygulama):
    temel, tmp_path, _, olay = uygulama
    _istek(temel, "/api/guncelleme/denetle", {})
    kod, govde = _istek(temel, "/api/guncelleme/kur", {"surum": "1.10.0"})
    assert kod == 200 and govde["ok"] is True
    assert [o[0] for o in olay] == ["baslat", "kapat"]  # önce başlat, sonra kapan
    _, yeni, eski = olay[0]
    assert yeni.read_bytes() == YENI_EXE and eski == tmp_path / "Takvim.exe"
    assert eski.read_bytes() == ESKI_EXE  # çalışan dosyaya dokunulmadı


def test_kur_ozet_tutmazsa_baslatmaz_ve_kapatmaz(uygulama):
    temel, tmp_path, sahte, olay = uygulama  # noqa: F811
    _istek(temel, "/api/guncelleme/denetle", {})
    sahte.ozet = "0" * 64
    kod, govde = _istek(temel, "/api/guncelleme/kur", {"surum": "1.10.0"})
    assert kod == 400 and govde["error_code"] == "guncelleme_ozet_uyusmuyor"
    assert olay == []  # uygulama açık kalır, mevcut sürümle devam
    assert not list((tmp_path / "guncelleme").glob("Takvim-*"))


def test_kur_bilinmeyen_surumu_reddeder(uygulama):
    temel, _, _, olay = uygulama
    _istek(temel, "/api/guncelleme/denetle", {})
    assert _istek(temel, "/api/guncelleme/kur", {"surum": "9.9.9"})[1]["error_code"] == "guncelleme_surum_bilinmiyor"
    assert _istek(temel, "/api/guncelleme/kur", {})[1]["error_code"] == "surum_gerekli"
    assert _istek(temel, "/api/guncelleme/kur", {"surum": 5})[0] == 400
    assert olay == []


def test_kur_teklif_yokken_reddeder(uygulama):
    temel, _, sahte, olay = uygulama  # noqa: F811
    kod, govde = _istek(temel, "/api/guncelleme/kur", {"surum": "1.10.0"})  # hiç denetlenmedi
    assert kod == 400 and govde["error_code"] == "guncelleme_surum_bilinmiyor"
    assert olay == [] and _ag_istegi_sayisi(sahte) == 0  # indirme/ağ yok


def test_kur_baslatma_hatasinda_kapanmaz(uygulama):
    temel, tmp_path, sahte, olay = uygulama  # noqa: F811
    _istek(temel, "/api/guncelleme/denetle", {})

    olay.patlat = True
    kod, govde = _istek(temel, "/api/guncelleme/kur", {"surum": "1.10.0"})
    assert kod == 400 and govde["error_code"] == "guncelleme_baslatilamadi"
    assert olay == []  # kapat çağrılmadı


def test_kur_paketli_degilse_kurulamaz(sahte, tmp_path):  # noqa: F811
    db = str(tmp_path / "takvim.db")
    repo = Repo.open(db, check_same_thread=False)
    httpd = make_server(repo, IST, host="127.0.0.1", port=0, db_yolu=db)
    httpd.guncelleyici = Guncelleyici(tmp_path, "1.9.0", ag=_ag(sahte), simdi=lambda: AN, exe_yolu=None)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    temel = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        _istek(temel, "/api/guncelleme/denetle", {})
        kod, govde = _istek(temel, "/api/guncelleme/kur", {"surum": "1.10.0"})
        assert kod == 400 and govde["error_code"] == "guncelleme_kurulamaz"
    finally:
        httpd.shutdown()
        httpd.server_close()
        repo.close()


@pytest.mark.parametrize("yol", ["/api/guncelleme/denetle", "/api/guncelleme/kur"])
def test_baska_siteden_istek_reddedilir(uygulama, yol):
    temel, _, sahte, olay = uygulama  # noqa: F811
    kod, _ = _istek(temel, yol, {"surum": "1.10.0"}, {"Sec-Fetch-Site": "cross-site"})
    assert kod == 403
    kod, _ = _istek(temel, yol, {"surum": "1.10.0"}, {"Origin": "http://evil.example"})
    assert kod == 403
    assert olay == [] and _ag_istegi_sayisi(sahte) == 0


def test_yanlis_host_basligi_reddedilir(uygulama):
    temel, _, _, _ = uygulama
    kod, _ = _istek(temel, "/api/guncelleme/durum", None, {"Host": "evil.example:80"})
    assert kod == 403


# -- arka plan kuralı ------------------------------------------------------------

def test_denetim_kapaliyken_sifir_ag_istegi(sahte, tmp_path):  # noqa: F811
    g = Guncelleyici(tmp_path, "1.9.0", ag=_ag(sahte), simdi=lambda: AN)
    for acik in (False, False, False):  # None ve False ikisi de "açık değil"
        assert arka_plan_adimi(g, acik) is False
    assert sahte.istekler == []


def test_denetim_aciksa_gunde_bir_kez(sahte, tmp_path):  # noqa: F811
    an = [AN]
    g = Guncelleyici(tmp_path, "1.9.0", ag=_ag(sahte), simdi=lambda: an[0])
    assert arka_plan_adimi(g, True) is True
    assert arka_plan_adimi(g, True) is False  # aynı gün tekrar sorulmaz
    an[0] += timedelta(hours=25)
    assert arka_plan_adimi(g, True) is True
    assert len(sahte.istekler) == 2


def test_dongu_ayari_her_turda_okur(sahte, tmp_path, monkeypatch):  # noqa: F811
    """Döngü ayar dosyasına bakıyor: seçim yoksa/kapalıysa ağ yok, açıkken denetler."""
    from ui import __main__ as ana
    from ui.ayarlar import ayar_dosyasi, ayar_yaz

    yol = ayar_dosyasi(tmp_path)
    g = Guncelleyici(tmp_path, "1.9.0", ag=_ag(sahte), simdi=lambda: AN)

    def tur(sayi):
        dur = threading.Event()
        gercek_bekle = dur.wait
        kalan = [sayi]

        def bekle(sn):
            kalan[0] -= 1
            return gercek_bekle(0) if kalan[0] > 0 else (dur.set() or True)

        dur.wait = bekle  # type: ignore[method-assign]
        ana._guncelleme_dongusu(g, yol, dur)

    tur(2)  # ayar dosyası yok = sorulmadı
    ayar_yaz(yol, {"guncelleme_denetimi": False})
    tur(2)
    assert sahte.istekler == []
    ayar_yaz(yol, {"guncelleme_denetimi": True})
    tur(2)
    assert len(sahte.istekler) == 1


# -- yeni exe girişi ---------------------------------------------------------------

def test_tamamla_komutu_gecersiz_hedefi_reddeder(tmp_path, monkeypatch):
    import sys

    assert tamamla_komutu(["--guncelle-tamamla", "--eski", str(tmp_path / "bir.txt")]) == 2
    kendisi = tmp_path / "Takvim.exe"
    monkeypatch.setattr(sys, "executable", str(kendisi))
    assert tamamla_komutu(["--guncelle-tamamla", "--eski", str(kendisi)]) == 2
