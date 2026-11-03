"""Wi-Fi eşleştirme sunucusu (`senkron/wifi.py`, docs/senkron-wifi.md §3).

Ağ testleri 127.0.0.1 üstünde: oturuma `test_ipleri` ile loopback izni verilir
(yalnız testler; üretim yolunda yalnız spec §3 aralıkları, bkz.
`test_ozel_ip_kurali`). Veritabanı geçici dosya; gerçek veriye dokunulmaz.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import re
import socket
import ssl
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from core import Event
from senkron import WifiHatasi, WifiYonetici, durum_uret, json_metni
from senkron import wifi as wifi_modulu
from senkron.wifi import (
    KARAR_SN,
    MAKS_GOVDE,
    MAKS_HATA,
    OMUR_SN,
    WifiOturumu,
    ozel_ip_mi,
    sertifika_uret,
    varsayilan_ip_bul,
)
from store import Repo
from tests.helpers import IST, ist

LOOPBACK = frozenset({"127.0.0.1"})


class Saat:
    """Enjekte edilen monoton saat (saniye)."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def db(tmp_path):
    yol = str(tmp_path / "takvim.db")
    with Repo.open(yol) as repo:
        repo.add_calendar("Kişisel", "#3b82f6")
    return yol


def _depo_acici(db):
    @contextmanager
    def ac():
        repo = Repo.open(db)
        try:
            yield repo
        finally:
            repo.close()

    return ac


@pytest.fixture
def saat():
    return Saat()


@pytest.fixture
def gunluk():
    return []


@pytest.fixture
def oturum(db, saat, gunluk):
    o = WifiOturumu(
        ip="127.0.0.1", depo_ac=_depo_acici(db), cihaz_adi="Test PC", cihaz_id="cihaz-1",
        uygulama="desktop test", zaman=saat, gunluk=gunluk.append, test_ipleri=LOOPBACK,
    )
    o.baslat()
    yield o
    o.bitir("iptal")


def _token(o: WifiOturumu) -> str:
    return re.search(r"&t=([0-9a-f]{32})&", o.baglanti).group(1)  # type: ignore[union-attr]


def _istemci_baglami() -> ssl.SSLContext:
    baglam = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    baglam.check_hostname = False
    baglam.verify_mode = ssl.CERT_NONE
    return baglam


def _istek(o, metot, yol, *, token="", govde=None, basliklar=None, zaman_asimi=10):
    """(durum, başlıklar, gövde) döndürür."""
    c = http.client.HTTPSConnection("127.0.0.1", o.port, context=_istemci_baglami(), timeout=zaman_asimi)
    try:
        b = dict(basliklar or {})
        if token:
            b["Authorization"] = f"Bearer {token}"
        c.request(metot, yol, body=govde, headers=b)
        r = c.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    finally:
        c.close()


def _port_kapali(o, sn=3.0) -> bool:
    """Port kapanana kadar bekler (token ölür ölmez, dinleyici hemen arkasından kapanır)."""
    son = time.monotonic() + sn
    while time.monotonic() < son:
        try:
            socket.create_connection(("127.0.0.1", o.port), timeout=1).close()
        except OSError:
            return True
        time.sleep(0.05)
    return False


def _bekle(kosul, sn=5.0):
    son = time.monotonic() + sn
    while time.monotonic() < son:
        if kosul():
            return True
        time.sleep(0.02)
    return False


def _telefon_dosyasi(uid="tel-1") -> bytes:
    """Başka bir 'cihaz'ın tek takvim + tek etkinlikli dosyası."""
    with Repo.open(":memory:") as diger:
        k = diger.add_calendar("Telefon", "#3b82f6")
        diger.add_event(Event(
            id=None, uid=uid, calendar_id=k.id, title="Telefondan gelen",
            start_utc=ist(2026, 11, 3, 10), end_utc=ist(2026, 11, 3, 11), tzid=IST,
        ))
        return json_metni(
            durum_uret(diger, cihaz_id="tel", cihaz_adi="Telefon", uygulama="test")
        ).encode("utf-8")


def _etkinlik_sayisi(db) -> int:
    with Repo.open(db) as repo:
        return repo.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


class _Post(threading.Thread):
    """POST /v1/state'i ayrı thread'de gönderir (masaüstü onayını beklediği için)."""

    def __init__(self, o, govde: bytes, **kw) -> None:
        super().__init__(daemon=True)
        self.o, self.govde, self.kw = o, govde, kw
        self.sonuc = None

    def run(self) -> None:
        self.sonuc = _istek(
            self.o, "POST", "/v1/state", token=_token(self.o), govde=self.govde,
            zaman_asimi=30, **self.kw,
        )


# ---------------------------------------------------------------------------
# Adres ve bağlantı
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ip,beklenen", [
    ("10.0.0.1", True), ("10.255.255.254", True),
    ("172.16.0.1", True), ("172.31.255.255", True), ("172.15.255.255", False), ("172.32.0.1", False),
    ("192.168.1.20", True), ("192.169.0.1", False),
    ("169.254.10.5", True), ("169.253.0.1", False),
    ("127.0.0.1", False), ("0.0.0.0", False), ("8.8.8.8", False), ("100.64.0.1", False),
    ("::1", False), ("abc", False), ("", False),
])
def test_ozel_ip_kurali(ip, beklenen):
    assert ozel_ip_mi(ip) is beklenen


def test_ozel_olmayan_ip_icin_oturum_baslamaz(db):
    for ip in ("8.8.8.8", "127.0.0.1"):  # loopback da test izni olmadan reddedilir
        with pytest.raises(WifiHatasi) as hata:
            WifiOturumu(ip=ip, depo_ac=_depo_acici(db), cihaz_adi="x", cihaz_id="x", uygulama="x")
        assert hata.value.kod == "wifi_ozel_ag_degil"


def test_belirsiz_adrese_test_izniyle_bile_baglanilmaz(db):
    with pytest.raises(ValueError):
        WifiOturumu(
            ip="0.0.0.0", depo_ac=_depo_acici(db), cihaz_adi="x", cihaz_id="x", uygulama="x",
            test_ipleri=frozenset({"0.0.0.0"}),
        )


def test_sunucu_yalniz_secilen_ipye_baglanir(db, monkeypatch):
    """Dinleme adresi tam olarak seçilen IP; `0.0.0.0` ya da boş dize ASLA."""
    adresler = []

    class Sahte:
        def __init__(self, adres, *a, **k):
            adresler.append(adres)
            raise OSError("dolu")

    monkeypatch.setattr(wifi_modulu, "_Sunucu", Sahte)
    o = WifiOturumu(
        ip="127.0.0.1", depo_ac=_depo_acici(db), cihaz_adi="x", cihaz_id="x", uygulama="x",
        test_ipleri=LOOPBACK,
    )
    with pytest.raises(WifiHatasi) as hata:
        o.baslat()
    assert hata.value.kod == "wifi_baslatilamadi"
    assert adresler and all(a[0] == "127.0.0.1" for a in adresler)
    assert all(49152 <= a[1] <= 65535 for a in adresler)


def test_gercek_dinleme_adresi_secilen_ip(oturum):
    assert oturum._httpd.server_address[0] == "127.0.0.1"


def test_baglanti_bicimi(oturum):
    m = re.fullmatch(
        r"https://aktenak\.tech/s#v=1&h=127\.0\.0\.1:(\d+)&t=([0-9a-f]{32})&f=([A-Za-z0-9_-]{43})&n=Test%20PC",
        oturum.baglanti,
    )
    assert m, oturum.baglanti
    assert int(m.group(1)) == oturum.port and 49152 <= oturum.port <= 65535
    assert m.group(3) == oturum.parmak_izi


def test_cihaz_adi_40_karaktere_kirpilir_ve_url_kodlanir(db):
    o = WifiOturumu(
        ip="127.0.0.1", depo_ac=_depo_acici(db), cihaz_adi="Ç" * 60, cihaz_id="x", uygulama="x",
        test_ipleri=LOOPBACK,
    )
    o.baslat()
    try:
        ad = o.baglanti.split("&n=")[1]
        assert ad == "%C3%87" * 40
    finally:
        o.bitir("iptal")


def test_her_oturum_farkli_token_ve_port(db):
    ilk = []
    for _ in range(2):
        o = WifiOturumu(
            ip="127.0.0.1", depo_ac=_depo_acici(db), cihaz_adi="x", cihaz_id="x", uygulama="x",
            test_ipleri=LOOPBACK,
        )
        o.baslat()
        ilk.append(_token(o))
        o.bitir("iptal")
    assert ilk[0] != ilk[1]


def test_varsayilan_ip_bul(monkeypatch):
    class Sahte:
        AF_INET, SOCK_DGRAM = 2, 2
        ip = "192.168.1.9"
        hata = False

        class socket:
            def __init__(self, *a):
                pass

            def connect(self, adres):
                if Sahte.hata:
                    raise OSError("ağ yok")

            def getsockname(self):
                return (Sahte.ip, 5)

            def close(self):
                pass

    monkeypatch.setattr(wifi_modulu, "socket", Sahte)
    assert varsayilan_ip_bul() == "192.168.1.9"
    Sahte.ip = "0.0.0.0"
    with pytest.raises(WifiHatasi) as h1:
        varsayilan_ip_bul()
    Sahte.hata = True
    with pytest.raises(WifiHatasi) as h2:
        varsayilan_ip_bul()
    assert h1.value.kod == h2.value.kod == "wifi_ag_yok"


# ---------------------------------------------------------------------------
# Sertifika / TLS
# ---------------------------------------------------------------------------

def test_sertifika_parmak_izi_istemcinin_hesabiyla_ayni(oturum):
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric import ec

    with socket.create_connection(("127.0.0.1", oturum.port), timeout=5) as ham:
        with _istemci_baglami().wrap_socket(ham) as tls:
            der = tls.getpeercert(binary_form=True)
            surum = tls.version()
    hesap = base64.urlsafe_b64encode(hashlib.sha256(der).digest()).rstrip(b"=").decode()
    assert hesap == oturum.parmak_izi == re.search(r"&f=([^&]+)", oturum.baglanti).group(1)
    assert surum in ("TLSv1.2", "TLSv1.3")

    sert = x509.load_der_x509_certificate(der)
    assert isinstance(sert.public_key(), ec.EllipticCurvePublicKey)
    assert sert.public_key().curve.name == "secp256r1"
    san = sert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert [str(a) for a in san.get_values_for_type(x509.IPAddress)] == ["127.0.0.1"]
    omur = sert.not_valid_after_utc - sert.not_valid_before_utc
    assert 24 * 3600 <= omur.total_seconds() <= 25 * 3600


def test_her_oturum_yeni_sertifika():
    _, a = sertifika_uret("192.168.1.2")
    _, b = sertifika_uret("192.168.1.2")
    assert a != b


def test_tls_en_az_1_2(oturum):
    assert oturum._httpd.baglam.minimum_version == ssl.TLSVersion.TLSv1_2


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
@pytest.mark.parametrize("surum", [ssl.TLSVersion.TLSv1, ssl.TLSVersion.TLSv1_1])
def test_eski_tls_reddedilir(oturum, surum):
    baglam = _istemci_baglami()
    try:
        baglam.set_ciphers("DEFAULT:@SECLEVEL=0")
        baglam.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
        baglam.maximum_version = surum
    except (ssl.SSLError, ValueError):
        pytest.skip("bu OpenSSL TLS 1.0/1.1 istemcisi kuramıyor")
    with pytest.raises((ssl.SSLError, OSError)):
        with socket.create_connection(("127.0.0.1", oturum.port), timeout=5) as ham:
            baglam.wrap_socket(ham).close()
    # Olumlu kontrol: aynı bağlam TLS 1.2 ile bağlanır (reddin sebebi sürüm).
    baglam.maximum_version = ssl.TLSVersion.TLSv1_2
    baglam.minimum_version = ssl.TLSVersion.TLSv1_2
    with socket.create_connection(("127.0.0.1", oturum.port), timeout=5) as ham:
        baglam.wrap_socket(ham).close()


def test_ozel_anahtar_diskte_kalmaz(tmp_path, monkeypatch):
    """Geçici dosya yüklenirken VAR ve şifreli; sonra silinmiş (başarıda ve hatada)."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    gorulen = {}
    gercek = ssl.SSLContext.load_cert_chain

    def izle(self, certfile, keyfile=None, password=None):
        icerik = Path(certfile).read_text()
        gorulen.update(
            var=True, sifreli="BEGIN ENCRYPTED PRIVATE KEY" in icerik,
            acik="BEGIN PRIVATE KEY" in icerik or "BEGIN EC PRIVATE KEY" in icerik,
            parola_dosyada=bytes(password).decode() in icerik,
        )
        if gorulen.get("hata"):
            raise ssl.SSLError("yükleme hatası")
        return gercek(self, certfile, keyfile, password)

    monkeypatch.setattr(ssl.SSLContext, "load_cert_chain", izle)
    sertifika_uret("192.168.1.2")
    assert gorulen == {"var": True, "sifreli": True, "acik": False, "parola_dosyada": False}
    assert list(tmp_path.iterdir()) == []

    gorulen["hata"] = True
    with pytest.raises(ssl.SSLError):
        sertifika_uret("192.168.1.2")
    assert list(tmp_path.iterdir()) == []  # yükleme patlasa da dosya silinir


def test_oturum_boyunca_ve_sonrasinda_diskte_anahtar_yok(tmp_path, monkeypatch, db):
    gecici = tmp_path / "gecici"  # `db` tmp_path'te: karışmasın
    gecici.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(gecici))
    o = WifiOturumu(
        ip="127.0.0.1", depo_ac=_depo_acici(db), cihaz_adi="x", cihaz_id="x", uygulama="x",
        test_ipleri=LOOPBACK,
    )
    o.baslat()
    assert list(gecici.iterdir()) == []
    o.bitir("iptal")
    assert list(gecici.iterdir()) == []


# ---------------------------------------------------------------------------
# Kimlik, yol ve metot kuralları
# ---------------------------------------------------------------------------

def test_token_yok_ya_da_yanlis_401(oturum):
    yanlis = "0" * 32
    for token in ("", yanlis):
        durum, _, govde = _istek(oturum, "GET", "/v1/hello", token=token)
        assert durum == 401 and json.loads(govde) == {"error": "yetkisiz"}
    durum, _, _ = _istek(oturum, "GET", "/v1/hello", token=_token(oturum))
    assert durum == 200


def test_bearer_disi_sema_ve_kisa_token_reddedilir(oturum):
    t = _token(oturum)
    for baslik in (f"Basic {t}", t, f"bearer {t}", f"Bearer {t[:-1]}", f"Bearer {t}x", "Bearer "):
        durum, _, _ = _istek(oturum, "GET", "/v1/hello", basliklar={"Authorization": baslik})
        assert durum == 401, baslik
        if oturum.faz == "bitti":
            break


def test_token_sabit_zamanli_karsilastirilir(oturum, monkeypatch):
    cagrilar = []
    gercek = wifi_modulu.hmac.compare_digest
    monkeypatch.setattr(wifi_modulu.hmac, "compare_digest", lambda a, b: cagrilar.append(1) or gercek(a, b))
    _istek(oturum, "GET", "/v1/hello", token=_token(oturum))
    assert cagrilar


def test_besinci_basarisiz_kimlikte_oturum_olur(oturum):
    t = _token(oturum)
    for _ in range(MAKS_HATA - 1):
        assert _istek(oturum, "GET", "/v1/hello", token="y" * 32)[0] == 401
    assert oturum.faz == "bekliyor"
    assert _istek(oturum, "GET", "/v1/hello", token=t)[0] == 200  # doğru token hâlâ geçer
    assert _istek(oturum, "GET", "/v1/hello", token="y" * 32)[0] == 401  # 5. hata
    assert _bekle(lambda: oturum.faz == "bitti")
    assert oturum.sonuc == "cok_hata"
    assert _port_kapali(oturum)  # doğru token bile artık ulaşamaz


def test_yetkisiz_istege_yol_ve_metot_bilgisi_sizmaz(oturum):
    for metot, yol in (("GET", "/yok"), ("DELETE", "/v1/state"), ("POST", "/v1/hello")):
        durum, _, govde = _istek(oturum, metot, yol)
        assert (durum, json.loads(govde)) == (401, {"error": "yetkisiz"}), (metot, yol)
        if oturum.faz == "bitti":
            break


def test_bilinmeyen_yol_404_ve_metot_405(oturum):
    t = _token(oturum)
    assert _istek(oturum, "GET", "/", token=t)[0] == 404
    assert _istek(oturum, "GET", "/v2/state", token=t)[0] == 404
    assert _istek(oturum, "GET", "/v1/state/", token=t)[0] == 404
    durum, basliklar, _ = _istek(oturum, "POST", "/v1/hello", token=t, govde=b"{}")
    assert durum == 405 and basliklar["allow"] == "GET"
    durum, basliklar, _ = _istek(oturum, "DELETE", "/v1/state", token=t)
    assert durum == 405 and set(basliklar["allow"].split(", ")) == {"GET", "POST"}
    assert _istek(oturum, "PUT", "/v1/state", token=t, govde=b"{}")[0] == 405
    assert _istek(oturum, "FOO", "/v1/hello", token=t)[0] == 405  # tanınmayan metot da aynı yoldan


def test_sorgu_dizesi_yolu_degistirmez(oturum):
    assert _istek(oturum, "GET", "/v1/hello?x=1", token=_token(oturum))[0] == 200


def test_hello(oturum):
    durum, basliklar, govde = _istek(oturum, "GET", "/v1/hello", token=_token(oturum))
    assert durum == 200 and basliklar["content-type"].startswith("application/json")
    assert json.loads(govde) == {
        "format": "takvim-wifi", "version": 1,
        "device": {"name": "Test PC", "app": "desktop test"},
    }


def test_get_state_tum_durum(oturum, db):
    with Repo.open(db) as repo:
        k = repo.list_calendars()[0]
        repo.add_event(Event(
            id=None, uid="m-1", calendar_id=k.id, title="Masaüstü",
            start_utc=ist(2026, 11, 3, 9), end_utc=ist(2026, 11, 3, 10), tzid=IST,
        ))
    durum, basliklar, govde = _istek(oturum, "GET", "/v1/state", token=_token(oturum))
    assert durum == 200 and basliklar["content-type"].startswith("application/json")
    dosya = json.loads(govde)
    assert dosya["format"] == "takvim-sync" and dosya["version"] == 1
    assert [e["title"] for e in dosya["events"]] == ["Masaüstü"]
    assert dosya["device"]["id"] == "cihaz-1"


def test_yanitlarda_cors_basligi_yok(oturum):
    t = _token(oturum)
    yanitlar = [
        _istek(oturum, "GET", "/v1/hello", token=t, basliklar={"Origin": "https://evil.example"}),
        _istek(oturum, "GET", "/v1/state", token=t, basliklar={"Origin": "https://evil.example"}),
        _istek(oturum, "GET", "/yok", token=t),
        _istek(oturum, "POST", "/v1/hello", token=t),
        _istek(oturum, "OPTIONS", "/v1/state", token=t, basliklar={
            "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}),
        _istek(oturum, "OPTIONS", "/v1/state", basliklar={"Origin": "https://evil.example"}),
    ]
    assert [y[0] for y in yanitlar] == [200, 200, 404, 405, 405, 401]
    for _, basliklar, _ in yanitlar:
        assert not [b for b in basliklar if b.startswith("access-control-")]
        assert "server" in basliklar and "python" not in basliklar["server"].lower()


def test_http_1_1_ve_baglanti_kapanir(oturum):
    ham = socket.create_connection(("127.0.0.1", oturum.port), timeout=5)
    with _istemci_baglami().wrap_socket(ham) as tls:
        tls.sendall(f"GET /v1/hello HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {_token(oturum)}\r\n\r\n".encode())
        veri = b""
        while chunk := tls.recv(4096):
            veri += chunk  # sunucu kapatmazsa recv zaman aşımına uğrar
    assert veri.startswith(b"HTTP/1.1 200")


# ---------------------------------------------------------------------------
# Ömür
# ---------------------------------------------------------------------------

def test_uc_dakika_sonra_oturum_kapanir(oturum, saat):
    assert _istek(oturum, "GET", "/v1/hello", token=_token(oturum))[0] == 200
    saat.t += OMUR_SN - 1
    time.sleep(0.4)
    assert oturum.faz == "bekliyor"
    saat.t += 2
    assert _bekle(lambda: oturum.faz == "bitti")
    assert oturum.sonuc == "sure_doldu"
    assert _port_kapali(oturum)


def test_istek_sirasinda_sure_dolmussa_istek_reddedilir(oturum, saat):
    t = _token(oturum)
    oturum._bitti.set()  # bekçiyi sustur: istek-zamanı denetimini ayrı sınayalım
    saat.t += OMUR_SN + 1
    assert _istek(oturum, "GET", "/v1/hello", token=t)[0] == 401
    assert oturum.faz == "bitti" and oturum.sonuc == "sure_doldu"


def test_iptal_sonrasi_port_kapali_ve_token_olu(oturum):
    t = _token(oturum)
    oturum.bitir("iptal")
    assert _port_kapali(oturum)
    assert oturum.yetkili_mi(f"Bearer {t}") is False
    assert oturum.sonuc == "iptal"


def test_tek_oturum_yonetici_eskisini_kapatir(db):
    y = WifiYonetici(
        depo_ac=_depo_acici(db), cihaz_adi="x", cihaz_id="x", uygulama="x",
        ip_bul=lambda: "127.0.0.1", test_ipleri=LOOPBACK,
    )
    try:
        ilk = y.baslat()
        eski = y._oturum
        ikinci = y.baslat()
        assert eski.faz == "bitti" and eski.sonuc == "iptal"
        assert _port_kapali(eski)
        assert ilk["baglanti"] != ikinci["baglanti"]
        assert y._oturum is not eski and y._oturum.faz == "bekliyor"
        assert _istek(y._oturum, "GET", "/v1/hello", token=_token(y._oturum))[0] == 200
    finally:
        y.kapat()
    assert y._oturum.sonuc == "kapandi" and _port_kapali(y._oturum)


def test_yonetici_baslatma_yanitinda_token_yalniz_baglantida(db):
    y = WifiYonetici(
        depo_ac=_depo_acici(db), cihaz_adi="x", cihaz_id="x", uygulama="x",
        ip_bul=lambda: "127.0.0.1", test_ipleri=LOOPBACK,
    )
    try:
        bilgi = y.baslat()
        token = re.search(r"&t=([0-9a-f]{32})&", bilgi["baglanti"]).group(1)
        durum = y.durum()
        assert token not in json.dumps(durum)
        assert token not in json.dumps({k: v for k, v in bilgi.items() if k != "baglanti"})
    finally:
        y.kapat()


def test_yonetici_ozel_olmayan_ag_hatasi(db):
    y = WifiYonetici(depo_ac=_depo_acici(db), cihaz_adi="x", cihaz_id="x", uygulama="x", ip_bul=lambda: "8.8.8.8")
    with pytest.raises(WifiHatasi) as h:
        y.baslat()
    assert h.value.kod == "wifi_ozel_ag_degil"
    assert y.durum() == {"asama": "yok"}
    with pytest.raises(WifiHatasi) as h:
        y.karar(True)
    assert h.value.kod == "wifi_karar_yok"


# ---------------------------------------------------------------------------
# POST /v1/state: gövde sınırları
# ---------------------------------------------------------------------------

def _ham_post(o, basliklar: list[str], govde: bytes = b"", okuma_sn=5):
    """Başlıkları elle yazan TLS istemcisi; yanıt durum satırını döndürür."""
    ham = socket.create_connection(("127.0.0.1", o.port), timeout=okuma_sn)
    with _istemci_baglami().wrap_socket(ham) as tls:
        tls.settimeout(okuma_sn)
        istek = "POST /v1/state HTTP/1.1\r\nHost: x\r\n" + "".join(b + "\r\n" for b in basliklar) + "\r\n"
        tls.sendall(istek.encode() + govde)
        veri = b""
        try:
            while chunk := tls.recv(65536):
                veri += chunk
        except (TimeoutError, ssl.SSLError):
            pass
    return veri


def test_content_length_yoksa_411(oturum):
    veri = _ham_post(oturum, [f"Authorization: Bearer {_token(oturum)}"])
    assert veri.startswith(b"HTTP/1.1 411") and b'"uzunluk_gerekli"' in veri


def test_chunked_gonderim_411(oturum):
    veri = _ham_post(oturum, [f"Authorization: Bearer {_token(oturum)}", "Transfer-Encoding: chunked"], b"0\r\n\r\n")
    assert veri.startswith(b"HTTP/1.1 411")


def test_gecersiz_content_length_400(oturum):
    t = _token(oturum)
    for deger in ("abc", "-5", "1e3", "12 34"):
        veri = _ham_post(oturum, [f"Authorization: Bearer {t}", f"Content-Length: {deger}"])
        assert veri.startswith(b"HTTP/1.1 400"), deger


def test_16_mib_ustu_govde_okunmadan_413(oturum):
    """Başlık yeter: gövde GÖNDERİLMEDEN yanıt gelmeli (okumaya kalkarsa zaman aşımı)."""
    t = _token(oturum)
    baslangic = time.monotonic()
    veri = _ham_post(oturum, [f"Authorization: Bearer {t}", f"Content-Length: {MAKS_GOVDE + 1}"], okuma_sn=4)
    assert veri.startswith(b"HTTP/1.1 413") and b'"cok_buyuk"' in veri
    assert time.monotonic() - baslangic < 3


def test_tam_16_mib_sinirinda_gecer_ama_gecersiz_dosya_400(oturum):
    """Sınırın kendisi kabul edilir (gövde okunur, içerik reddedilir): `>` değil `>=` hatası yakalar."""
    govde = b" " * MAKS_GOVDE
    durum, _, yanit = _istek(oturum, "POST", "/v1/state", token=_token(oturum), govde=govde, zaman_asimi=30)
    assert durum == 400 and json.loads(yanit)["error"] == "senkron_bozuk"


def test_expect_100_buyuk_govdeye_continue_verilmez(oturum):
    veri = _ham_post(oturum, [f"Authorization: Bearer {_token(oturum)}", f"Content-Length: {MAKS_GOVDE + 1}", "Expect: 100-continue"])
    assert veri.startswith(b"HTTP/1.1 413") and b"100 Continue" not in veri


def test_expect_100_yanlis_token_sayilir(oturum):
    for _ in range(MAKS_HATA):
        veri = _ham_post(oturum, ["Authorization: Bearer " + "y" * 32, "Content-Length: 10", "Expect: 100-continue"])
        assert veri.startswith(b"HTTP/1.1 401") and b"100 Continue" not in veri
    assert _bekle(lambda: oturum.faz == "bitti") and oturum.sonuc == "cok_hata"


def test_http_1_0_expect_ile_kimlik_atlanmaz(oturum):
    ham = socket.create_connection(("127.0.0.1", oturum.port), timeout=5)
    with _istemci_baglami().wrap_socket(ham) as tls:
        tls.sendall(b"GET /v1/hello HTTP/1.0\r\nExpect: 100-continue\r\n\r\n")
        veri = tls.recv(4096)
    assert b" 401 " in veri.split(b"\r\n")[0]


def test_derin_ic_ice_json_400_ve_sunucu_ayakta(oturum):
    t = _token(oturum)
    derin = b"[" * 200_000 + b"]" * 200_000
    durum, _, yanit = _istek(oturum, "POST", "/v1/state", token=t, govde=derin, zaman_asimi=30)
    assert durum == 400 and json.loads(yanit)["error"] == "senkron_bozuk"
    derin_nesne = b'{"a":' * 100_000 + b"1" + b"}" * 100_000
    durum, _, yanit = _istek(oturum, "POST", "/v1/state", token=t, govde=derin_nesne, zaman_asimi=30)
    assert durum == 400 and json.loads(yanit)["error"] == "senkron_bozuk"
    assert _istek(oturum, "GET", "/v1/hello", token=t)[0] == 200


def test_gecersiz_dosya_400_oturum_acik_kalir(oturum, db):
    t = _token(oturum)
    for govde, kod in (
        (b"bu json degil", "senkron_bozuk"),
        (b'{"format": "baska"}', "senkron_bozuk"),
        (b'{"format": "takvim-sync", "version": 99}', "senkron_surum_yeni"),
        (b"\xff\xfe", "senkron_bozuk"),
    ):
        durum, _, yanit = _istek(oturum, "POST", "/v1/state", token=t, govde=govde)
        assert (durum, json.loads(yanit)["error"]) == (400, kod), govde
    assert oturum.faz == "bekliyor" and oturum.istek_sayisi == 4
    assert _etkinlik_sayisi(db) == 0
    assert _istek(oturum, "GET", "/v1/hello", token=t)[0] == 200


# ---------------------------------------------------------------------------
# POST /v1/state: masaüstü onayı
# ---------------------------------------------------------------------------

def test_post_onay_birlestirir_rapor_doner_oturum_kapanir(oturum, db):
    post = _Post(oturum, _telefon_dosyasi())
    post.start()
    assert _bekle(lambda: oturum.faz == "onay_bekliyor")
    d = oturum.durum()
    assert d["ozet"] == {"calendars": 1, "events": 1, "tasks": 0, "deleted": 0}
    assert d["karar_kalan_sn"] > 0
    assert _etkinlik_sayisi(db) == 0  # onaydan ÖNCE hiçbir şey yazılmadı
    oturum.karar_ver(True)
    post.join(10)
    durum, _, yanit = post.sonuc
    assert durum == 200
    rapor = json.loads(yanit)["report"]
    assert set(rapor) == {"added", "updated", "deleted", "skipped"}
    assert rapor["added"] == {"calendar": 1, "event": 1, "task": 0}
    assert _etkinlik_sayisi(db) == 1
    assert _bekle(lambda: oturum.faz == "bitti") and oturum.sonuc == "birlestirildi"
    assert oturum.rapor["total"]["added"] == 2
    assert _port_kapali(oturum)


def test_post_ret_403_hicbir_sey_degismez(oturum, db):
    post = _Post(oturum, _telefon_dosyasi())
    post.start()
    assert _bekle(lambda: oturum.faz == "onay_bekliyor")
    oturum.karar_ver(False)
    post.join(10)
    assert post.sonuc[0] == 403 and json.loads(post.sonuc[2]) == {"error": "reddedildi"}
    assert _etkinlik_sayisi(db) == 0
    assert _bekle(lambda: oturum.faz == "bitti") and oturum.sonuc == "reddedildi"
    assert _port_kapali(oturum)


def test_post_karar_gelmezse_60_sn_sonra_408(oturum, saat, db):
    post = _Post(oturum, _telefon_dosyasi())
    post.start()
    assert _bekle(lambda: oturum.faz == "onay_bekliyor")
    saat.t += KARAR_SN - 1
    time.sleep(0.3)
    assert oturum.faz == "onay_bekliyor"
    saat.t += 2
    post.join(10)
    assert post.sonuc[0] == 408 and json.loads(post.sonuc[2]) == {"error": "zaman_asimi"}
    assert _etkinlik_sayisi(db) == 0
    assert _bekle(lambda: oturum.faz == "bitti") and oturum.sonuc == "zaman_asimi"


def test_karar_suresi_oturum_omrunu_asmaz(oturum, saat):
    """Ömrün son 10 saniyesinde gelen dosya 60 sn değil kalan süre kadar bekler."""
    saat.t += OMUR_SN - 10
    post = _Post(oturum, _telefon_dosyasi())
    post.start()
    assert _bekle(lambda: oturum.faz == "onay_bekliyor")
    saat.t += 11
    post.join(10)
    assert post.sonuc[0] == 408


def test_onay_beklerken_ikinci_post_409(oturum):
    post = _Post(oturum, _telefon_dosyasi())
    post.start()
    assert _bekle(lambda: oturum.faz == "onay_bekliyor")
    durum, _, yanit = _istek(oturum, "POST", "/v1/state", token=_token(oturum), govde=_telefon_dosyasi("tel-2"))
    assert (durum, json.loads(yanit)["error"]) == (409, "mesgul")
    oturum.karar_ver(False)
    post.join(10)


def test_onay_beklerken_get_calisir(oturum):
    post = _Post(oturum, _telefon_dosyasi())
    post.start()
    assert _bekle(lambda: oturum.faz == "onay_bekliyor")
    assert _istek(oturum, "GET", "/v1/hello", token=_token(oturum))[0] == 200  # onay beklerken tıkanmaz
    oturum.karar_ver(False)
    post.join(10)


def test_bekleyen_karar_yokken_karar_hatasi(oturum):
    with pytest.raises(WifiHatasi) as h:
        oturum.karar_ver(True)
    assert h.value.kod == "wifi_karar_yok"


def test_iptal_onay_beklerken_post_409_ve_veri_yazilmaz(oturum, db):
    post = _Post(oturum, _telefon_dosyasi())
    post.start()
    assert _bekle(lambda: oturum.faz == "onay_bekliyor")
    oturum.bitir("iptal")
    post.join(10)
    assert post.sonuc[0] == 409
    assert _etkinlik_sayisi(db) == 0


def test_ayni_dosya_ikinci_oturumda_degisiklik_yapmaz(db, saat, gunluk):
    """Birleştirme idempotent (docs/senkron-wifi.md §1): ikinci eşleştirme 0 sayar."""
    sayilar = []
    for _ in range(2):
        o = WifiOturumu(
            ip="127.0.0.1", depo_ac=_depo_acici(db), cihaz_adi="x", cihaz_id="x", uygulama="x",
            zaman=saat, gunluk=gunluk.append, test_ipleri=LOOPBACK,
        )
        o.baslat()
        post = _Post(o, _telefon_dosyasi())
        post.start()
        assert _bekle(lambda: o.faz == "onay_bekliyor")
        o.karar_ver(True)
        post.join(10)
        sayilar.append(json.loads(post.sonuc[2])["report"]["added"])
    assert sayilar[0]["event"] == 1 and sayilar[1] == {"calendar": 0, "event": 0, "task": 0}
    assert _etkinlik_sayisi(db) == 1


# ---------------------------------------------------------------------------
# Günlük
# ---------------------------------------------------------------------------

def test_gunlukte_token_ve_icerik_yok(oturum, gunluk, db):
    t = _token(oturum)
    _istek(oturum, "GET", "/v1/hello", token=t)
    _istek(oturum, "GET", "/v1/hello", token="y" * 32)
    post = _Post(oturum, _telefon_dosyasi())
    post.start()
    assert _bekle(lambda: oturum.faz == "onay_bekliyor")
    oturum.karar_ver(True)
    post.join(10)
    assert _bekle(lambda: oturum.faz == "bitti")
    metin = "\n".join(gunluk)
    assert "oturum açıldı" in metin and "oturum kapandı" in metin and "sonuç=birlestirildi" in metin
    assert "istek=" in metin
    for yasak in (t, oturum.parmak_izi, "Telefondan gelen", "tel-1", "127.0.0.1", str(oturum.port)):
        assert yasak not in metin


def test_varsayilan_gunluk_stdout_token_yok(db, capfd):
    o = WifiOturumu(
        ip="127.0.0.1", depo_ac=_depo_acici(db), cihaz_adi="x", cihaz_id="x", uygulama="x",
        test_ipleri=LOOPBACK,
    )
    o.baslat()
    t = _token(o)
    _istek(o, "GET", "/v1/hello", token=t)
    _istek(o, "GET", "/v1/hello", token="y" * 32)
    ham = socket.create_connection(("127.0.0.1", o.port), timeout=5)
    ham.sendall(b"merhaba kirli istek")  # TLS olmayan bağlantı: hata içeriği yazılmamalı
    ham.close()
    time.sleep(0.2)
    o.bitir("iptal")
    cikti = capfd.readouterr()
    assert t not in cikti.out + cikti.err
    assert "Traceback" not in cikti.out + cikti.err
    assert "wifi: oturum açıldı" in cikti.out


def test_tls_olmayan_baglanti_sunucuyu_dusurmez(oturum):
    ham = socket.create_connection(("127.0.0.1", oturum.port), timeout=5)
    ham.sendall(b"GET /v1/hello HTTP/1.1\r\n\r\n")
    ham.close()
    assert _bekle(lambda: oturum.baglanti_hatasi >= 1)
    assert _istek(oturum, "GET", "/v1/hello", token=_token(oturum))[0] == 200
    assert oturum.hata_sayisi == 0  # TLS'siz bağlantı kimlik hatası sayılmaz
