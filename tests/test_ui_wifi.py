"""Wi-Fi eşleştirme arayüz uçları (`/api/senkron/wifi/*`) ve ön yüz kablolaması.

Gerçek HTTP sunucusu + geçici dosya DB (gerçek %LOCALAPPDATA% DB'sine dokunulmaz).
Eşleştirme sunucusunun kendisi `tests/test_senkron_wifi.py`'de; burada ui katmanı:
koruma başlıkları, token'ın yalnız `baslat` yanıtında dönmesi, karar akışı, kapanış.
"""

from __future__ import annotations

import http.client
import json
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request

import pytest

from core import Event
from senkron import durum_uret, json_metni
from store import Repo
from tests.helpers import IST, ist
from ui.server import STATIC, make_server

LOOPBACK_AYAR = {"ip_bul": lambda: "127.0.0.1", "test_ipleri": frozenset({"127.0.0.1"})}


@pytest.fixture
def db(tmp_path):
    yol = str(tmp_path / "takvim.db")
    with Repo.open(yol) as repo:
        repo.add_calendar("Kişisel", "#3b82f6")
    return yol


@pytest.fixture
def sunucu(db):
    """(temel adres, httpd). Wi-Fi yöneticisi loopback test izniyle kurulur."""
    repo = Repo.open(db, check_same_thread=False)
    httpd = make_server(repo, IST, host="127.0.0.1", port=0, db_yolu=db)
    httpd.wifi_ayar = dict(LOOPBACK_AYAR)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", httpd
    httpd.shutdown()
    httpd.server_close()
    repo.close()


def _istek(temel, metot, yol, govde=None, basliklar=None):
    """(durum, JSON) döndürür; HTTP hatalarında da gövdeyi okur."""
    veri = None if govde is None else json.dumps(govde).encode("utf-8")
    req = urllib.request.Request(temel + yol, method=metot, data=veri, headers=basliklar or {})
    if veri is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as yanit:
            return yanit.status, json.loads(yanit.read())
    except urllib.error.HTTPError as hata:
        return hata.code, json.loads(hata.read())


def _bekle(kosul, sn=8.0):
    son = time.monotonic() + sn
    while time.monotonic() < son:
        if kosul():
            return True
        time.sleep(0.03)
    return False


def _telefon_post(baglanti: str, govde: bytes):
    """Telefon rolü: bağlantıdaki adrese/token'a POST eder; (durum, gövde) döner."""
    m = re.search(r"h=([\d.]+):(\d+)&t=([0-9a-f]{32})", baglanti)
    baglam = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    baglam.check_hostname = False
    baglam.verify_mode = ssl.CERT_NONE
    c = http.client.HTTPSConnection(m.group(1), int(m.group(2)), context=baglam, timeout=30)
    try:
        c.request("POST", "/v1/state", body=govde, headers={"Authorization": f"Bearer {m.group(3)}"})
        r = c.getresponse()
        return r.status, r.read()
    finally:
        c.close()


def _telefon_dosyasi() -> bytes:
    with Repo.open(":memory:") as diger:
        k = diger.add_calendar("Telefon", "#3b82f6")
        diger.add_event(Event(
            id=None, uid="tel-1", calendar_id=k.id, title="Telefondan gelen",
            start_utc=ist(2026, 11, 3, 10), end_utc=ist(2026, 11, 3, 11), tzid=IST,
        ))
        return json_metni(
            durum_uret(diger, cihaz_id="tel", cihaz_adi="Telefon", uygulama="test")
        ).encode("utf-8")


def _port(baglanti: str) -> int:
    return int(re.search(r"h=[\d.]+:(\d+)&", baglanti).group(1))


def _kapali(port: int) -> bool:
    def dene():
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
        except OSError:
            return True
        return False

    return _bekle(dene, 3)


def _acik(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=2).close()
    except OSError:
        return False
    return True


def _post_thread(baglanti):
    sonuc = {}
    t = threading.Thread(
        target=lambda: sonuc.update(r=_telefon_post(baglanti, _telefon_dosyasi())), daemon=True
    )
    t.start()
    return t, sonuc


# ---------------------------------------------------------------------------

def test_baslat_baglanti_doner_durum_doner_ama_tokensiz(sunucu):
    temel, _ = sunucu
    durum, govde = _istek(temel, "POST", "/api/senkron/wifi/baslat")
    assert durum == 200
    assert re.fullmatch(
        r"https://aktenak\.tech/s#v=1&h=127\.0\.0\.1:\d+&t=[0-9a-f]{32}&f=[A-Za-z0-9_-]{43}&n=.+",
        govde["baglanti"],
    )
    assert govde["ip"] == "127.0.0.1" and govde["port"] == _port(govde["baglanti"])
    assert govde["asama"] == "bekliyor" and 0 < govde["kalan_sn"] <= 180
    token = re.search(r"&t=([0-9a-f]{32})", govde["baglanti"]).group(1)

    durum, yoklama = _istek(temel, "GET", "/api/senkron/wifi/durum")
    assert durum == 200 and yoklama["asama"] == "bekliyor"
    assert token not in json.dumps(yoklama) and "baglanti" not in yoklama and "parmak_izi" not in yoklama


def test_baslatmadan_durum_yok_ve_cihaz_dosyasi_yazilmaz(sunucu, tmp_path):
    temel, _ = sunucu
    assert _istek(temel, "GET", "/api/senkron/wifi/durum") == (200, {"asama": "yok"})
    assert not (tmp_path / "cihaz.json").exists()


def test_tam_akis_onay_birlestirir(sunucu, db):
    temel, _ = sunucu
    baglanti = _istek(temel, "POST", "/api/senkron/wifi/baslat")[1]["baglanti"]
    t, sonuc = _post_thread(baglanti)
    assert _bekle(lambda: _istek(temel, "GET", "/api/senkron/wifi/durum")[1]["asama"] == "onay_bekliyor")
    d = _istek(temel, "GET", "/api/senkron/wifi/durum")[1]
    assert d["ozet"] == {"calendars": 1, "events": 1, "tasks": 0, "deleted": 0}
    assert 0 < d["karar_kalan_sn"] <= 60
    assert _istek(temel, "POST", "/api/senkron/wifi/karar", {"onay": True})[0] == 200
    t.join(10)
    assert sonuc["r"][0] == 200
    assert _bekle(lambda: _istek(temel, "GET", "/api/senkron/wifi/durum")[1]["asama"] == "bitti")
    son = _istek(temel, "GET", "/api/senkron/wifi/durum")[1]
    assert son["sonuc"] == "birlestirildi" and son["rapor"]["total"]["added"] == 2
    with Repo.open(db) as repo:
        assert repo.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    # Birleşen veri arayüzün öbür uçlarında da görünür (aynı DB, ayrı bağlantı).
    assert _kapali(_port(baglanti))


def test_tam_akis_ret_veriyi_degistirmez(sunucu, db):
    temel, _ = sunucu
    baglanti = _istek(temel, "POST", "/api/senkron/wifi/baslat")[1]["baglanti"]
    t, sonuc = _post_thread(baglanti)
    assert _bekle(lambda: _istek(temel, "GET", "/api/senkron/wifi/durum")[1]["asama"] == "onay_bekliyor")
    assert _istek(temel, "POST", "/api/senkron/wifi/karar", {"onay": False})[0] == 200
    t.join(10)
    assert sonuc["r"][0] == 403
    assert _bekle(lambda: _istek(temel, "GET", "/api/senkron/wifi/durum")[1]["sonuc"] == "reddedildi")
    with Repo.open(db) as repo:
        assert repo.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_iptal_oturumu_kapatir(sunucu):
    temel, _ = sunucu
    baglanti = _istek(temel, "POST", "/api/senkron/wifi/baslat")[1]["baglanti"]
    assert _istek(temel, "POST", "/api/senkron/wifi/iptal", {}) == (200, {"ok": True})
    assert _kapali(_port(baglanti))
    assert _istek(temel, "GET", "/api/senkron/wifi/durum")[1]["sonuc"] == "iptal"


def test_oturum_yokken_iptal_zararsiz(sunucu):
    temel, _ = sunucu
    assert _istek(temel, "POST", "/api/senkron/wifi/iptal", {}) == (200, {"ok": True})


def test_yeni_baslat_eski_oturumu_kapatir(sunucu):
    temel, _ = sunucu
    ilk = _istek(temel, "POST", "/api/senkron/wifi/baslat")[1]["baglanti"]
    ikinci = _istek(temel, "POST", "/api/senkron/wifi/baslat")[1]["baglanti"]
    assert ilk != ikinci
    assert _kapali(_port(ilk))
    assert _acik(_port(ikinci))


def test_bekleyen_karar_yokken_karar_400(sunucu):
    temel, _ = sunucu
    _istek(temel, "POST", "/api/senkron/wifi/baslat")
    durum, govde = _istek(temel, "POST", "/api/senkron/wifi/karar", {"onay": True})
    assert durum == 400 and govde["error_code"] == "wifi_karar_yok"


def test_oturum_hic_yokken_karar_400(sunucu):
    temel, _ = sunucu
    durum, govde = _istek(temel, "POST", "/api/senkron/wifi/karar", {"onay": True})
    assert durum == 400 and govde["error_code"] == "wifi_karar_yok"


@pytest.mark.parametrize("govde", [{}, {"onay": "evet"}, {"onay": 1}, {"onay": None}])
def test_gecersiz_karar_400(sunucu, govde):
    temel, _ = sunucu
    durum, yanit = _istek(temel, "POST", "/api/senkron/wifi/karar", govde)
    assert durum == 400 and yanit["error_code"] == "wifi_karar_gecersiz"


def test_bilinmeyen_wifi_eylemi_404(sunucu):
    temel, _ = sunucu
    assert _istek(temel, "POST", "/api/senkron/wifi/sil", {})[0] == 404


def test_ozel_olmayan_ag_anlasilir_hata(sunucu):
    temel, httpd = sunucu
    httpd.wifi_ayar = {"ip_bul": lambda: "8.8.8.8"}
    durum, govde = _istek(temel, "POST", "/api/senkron/wifi/baslat")
    assert durum == 400 and govde["error_code"] == "wifi_ozel_ag_degil"


def test_uretim_yapilandirmasi_loopbacki_kabul_etmez(sunucu):
    """`test_ipleri` verilmediyse (üretim) loopback de özel ağ sayılmaz."""
    temel, httpd = sunucu
    httpd.wifi_ayar = {"ip_bul": lambda: "127.0.0.1"}
    durum, govde = _istek(temel, "POST", "/api/senkron/wifi/baslat")
    assert durum == 400 and govde["error_code"] == "wifi_ozel_ag_degil"


def test_ag_yok_anlasilir_hata(sunucu):
    from senkron import WifiHatasi

    def yok():
        raise WifiHatasi("wifi_ag_yok", "ağ bağlantısı bulunamadı")

    temel, httpd = sunucu
    httpd.wifi_ayar = {"ip_bul": yok}
    durum, govde = _istek(temel, "POST", "/api/senkron/wifi/baslat")
    assert durum == 400 and govde["error_code"] == "wifi_ag_yok"


# -- koruma başlıkları: yazan uçlarla AYNI (kural 40, 77) -----------------------

@pytest.mark.parametrize("ad", ["baslat", "iptal", "karar"])
def test_yazan_uclar_yabanci_originden_reddedilir(sunucu, ad):
    temel, _ = sunucu
    durum, govde = _istek(
        temel, "POST", f"/api/senkron/wifi/{ad}", {"onay": True},
        {"Origin": "http://evil.example"},
    )
    assert durum == 403 and govde["error_code"] == "kaynak_guvensiz"
    durum, govde = _istek(
        temel, "POST", f"/api/senkron/wifi/{ad}", {"onay": True}, {"Sec-Fetch-Site": "cross-site"},
    )
    assert durum == 403 and govde["error_code"] == "kaynak_guvensiz"
    assert _istek(temel, "GET", "/api/senkron/wifi/durum")[1] == {"asama": "yok"}  # hiçbir şey başlamadı


@pytest.mark.parametrize("ad", ["baslat", "iptal", "karar"])
def test_yazan_uclar_yabanci_host_reddedilir(sunucu, ad):
    temel, _ = sunucu
    durum, govde = _istek(temel, "POST", f"/api/senkron/wifi/{ad}", {"onay": True}, {"Host": "evil.example"})
    assert durum == 403 and govde["error_code"] == "host_guvensiz"


def test_durum_get_yabanci_kaynak_ve_hosttan_reddedilir(sunucu):
    temel, _ = sunucu
    _istek(temel, "POST", "/api/senkron/wifi/baslat")
    durum, govde = _istek(temel, "GET", "/api/senkron/wifi/durum", basliklar={"Sec-Fetch-Site": "cross-site"})
    assert durum == 403 and govde["error_code"] == "kaynak_guvensiz"
    durum, govde = _istek(temel, "GET", "/api/senkron/wifi/durum", basliklar={"Origin": "http://evil.example"})
    assert durum == 403 and govde["error_code"] == "kaynak_guvensiz"
    durum, govde = _istek(temel, "GET", "/api/senkron/wifi/durum", basliklar={"Host": "evil.example"})
    assert durum == 403 and govde["error_code"] == "host_guvensiz"
    # Aynı kaynak / adres çubuğu geçer.
    assert _istek(temel, "GET", "/api/senkron/wifi/durum", basliklar={"Sec-Fetch-Site": "same-origin"})[0] == 200
    assert _istek(temel, "GET", "/api/senkron/wifi/durum", basliklar={"Sec-Fetch-Site": "none"})[0] == 200


def test_uygulama_kapaninca_acik_oturum_temizlenir(db):
    repo = Repo.open(db, check_same_thread=False)
    httpd = make_server(repo, IST, host="127.0.0.1", port=0, db_yolu=db)
    httpd.wifi_ayar = dict(LOOPBACK_AYAR)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    temel = f"http://127.0.0.1:{httpd.server_address[1]}"
    baglanti = _istek(temel, "POST", "/api/senkron/wifi/baslat")[1]["baglanti"]
    port = _port(baglanti)
    assert _acik(port)
    httpd.shutdown()
    httpd.server_close()
    repo.close()
    assert _kapali(port)


def test_bellek_veritabaninda_da_calisir():
    """`--db :memory:` (geliştirme): ortak bağlantı kullanılır, çökmez."""
    repo = Repo.open(":memory:", check_same_thread=False)
    repo.add_calendar("K", "#3b82f6")
    httpd = make_server(repo, IST, host="127.0.0.1", port=0)
    httpd.wifi_ayar = dict(LOOPBACK_AYAR)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        temel = f"http://127.0.0.1:{httpd.server_address[1]}"
        assert _istek(temel, "POST", "/api/senkron/wifi/baslat")[0] == 200
    finally:
        httpd.shutdown()
        httpd.server_close()
        repo.close()


# -- ön yüz kablolaması -------------------------------------------------------

def test_qr_kutuphanesi_ve_betik_sirasi():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    sira = [m.group(1) for m in re.finditer(r'<script src="([^"]+)"', html)]
    assert sira == ["i18n.js", "qrcode.js", "app.js"]
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)  # satır içi betik YOK
    lib = (STATIC / "qrcode.js").read_text(encoding="utf-8")
    assert "Kazuhiko Arase" in lib and "MIT license" in lib  # lisans başlığı yerinde


def test_arayuz_metinleri_iki_dilde_tanimli():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    i18n = (STATIC / "i18n.js").read_text(encoding="utf-8")
    kullanilan = set(re.findall(r'\bt\("((?:wifi_|senkron_wifi)\w*)"', app))
    kullanilan |= set(re.findall(r'"(wifi_sonuc_\w+)"', app))
    assert {"senkron_wifi_btn", "wifi_baslik", "wifi_onay_baslik", "wifi_guvenlik_duvari"} <= kullanilan
    bolumler = i18n.split("const EN")
    for anahtar in kullanilan | {
        "hata_wifi_ag_yok", "hata_wifi_ozel_ag_degil", "hata_wifi_baslatilamadi",
        "hata_wifi_karar_yok", "hata_wifi_karar_gecersiz",
    }:
        for bolum in bolumler:
            assert re.search(rf"^\s*{anahtar}:", bolum, re.M), anahtar
    assert len(bolumler) == 2
