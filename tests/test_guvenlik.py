"""Güvenlik denetimi düzeltmeleri (TKV-API-001..005).

Bulguların hepsi önce ELLE çalıştırılarak (gerçek HTTP istekleri, ham
soketler, ölçülen süreler) doğrulandı -- buradaki testler o kanıtlanmış
davranışı regresyona karşı kilitliyor. Denetim raporu ve ölçümler sohbette.
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from datetime import timedelta

import pytest

from core.models import Event
from core.recurrence import _MAKS_ORNEK, expand, series_end
from ics.importer import parse_ics
from store import Repo
from tests.helpers import IST, ist, make_event
from ui.__main__ import _ag_erisimi_dogrula, _loopback_mi
from ui.server import STATIC, host_gecerli_mi, make_server

# --------------------------------------------------------------- TKV-API-001


def _yogun_etkinlik(kural: str) -> Event:
    bas = ist(2026, 1, 1, 9, 0)
    return Event(
        id=None, uid="x", calendar_id=1, title="t",
        start_utc=bas, end_utc=bas + timedelta(hours=1),
        tzid=IST, all_day=False, rrule=kural, rdate=(), exdate=(),
    )


def test_seri_end_yogun_seriyi_reddeder():
    """COUNT sınırlı olsa da FREQ=SECONDLY ile milyonlarca örnek üretebilir;
    2_000_000'lık gerçek bir COUNT gerçek bir HTTP isteğinde 4.9 sn sürdü."""
    ev = _yogun_etkinlik(f"FREQ=SECONDLY;COUNT={_MAKS_ORNEK * 5}")
    with pytest.raises(ValueError, match="çok yoğun"):
        series_end(ev)


def test_seri_end_siniri_asmayan_seri_gecer():
    """Yanlışlıkla her seriyi reddetmiyoruz -- yalnızca sınırı aşanı."""
    ev = _yogun_etkinlik(f"FREQ=DAILY;COUNT={_MAKS_ORNEK - 1}")
    assert series_end(ev) is not None


def test_expand_yogun_pencerede_kirpar_hata_vermez():
    """expand() her RENDER'da çağrılıyor; series_end()'in tersine reddetmek
    o pencereyi kullanıcıya bir daha hiç açılamaz yapardı -- sessizce kırpar.
    Sınırsız + saniyelik bir seri bir ay penceresinde eskiden 17 sn sürüyordu.
    """
    ev = _yogun_etkinlik("FREQ=SECONDLY")  # sınırsız + yoğun
    bas = ist(2026, 1, 1, 0, 0)
    sonuc = expand(ev, [], bas, bas + timedelta(days=30))
    assert len(sonuc) == _MAKS_ORNEK


def test_expand_normal_seride_kirpilmiyor():
    """Kırpma yalnızca yoğun seride devreye girsin; normal bir seri
    eskisiyle (rs.between) birebir aynı sonucu vermeli."""
    ev = _yogun_etkinlik("FREQ=WEEKLY;COUNT=20")
    bas = ist(2026, 1, 1, 0, 0)
    sonuc = expand(ev, [], bas, bas + timedelta(days=365))
    assert len(sonuc) == 20


# --------------------------------------------------------------- TKV-API-002


def test_loopback_taniniyor():
    assert _loopback_mi("127.0.0.1")
    assert _loopback_mi("::1")
    assert _loopback_mi("localhost")
    assert not _loopback_mi("0.0.0.0")
    assert not _loopback_mi("192.168.1.5")


def test_ag_erisimi_izinsiz_reddedilir():
    with pytest.raises(ValueError, match="ag-erisimine-izin-ver"):
        _ag_erisimi_dogrula("0.0.0.0", False)


def test_ag_erisimi_izinle_gecer_ve_uyarir(capsys):
    _ag_erisimi_dogrula("0.0.0.0", True)  # ValueError ATMAMALI
    assert "UYARI" in capsys.readouterr().out


def test_loopback_icin_izin_gerekmez_ve_sessiz(capsys):
    _ag_erisimi_dogrula("127.0.0.1", False)  # ValueError ATMAMALI
    assert capsys.readouterr().out == ""


# --------------------------------------------------------------- TKV-API-003


def test_dosya_yolu_metin_olarak_yorumlanmaz(tmp_path):
    """Var olan bir dosyanın YOLUNU metin gibi gönderirsen dosya OKUNMAZ.

    Eskiden `_to_calendar` bu string'i diskte arayıp buluyor, içeriğini
    (SUMMARY'si "GIZLI" olan bir VEVENT) sessizce içe aktarıyordu -- uçtan
    uca kanıtlandı: /api/export ile dışarı sızdı."""
    hedef = tmp_path / "gizli.ics"
    hedef.write_text(
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:gizli-1\r\n"
        "DTSTAMP:20260101T090000Z\r\nDTSTART:20260401T090000Z\r\n"
        "DTEND:20260401T100000Z\r\nSUMMARY:GIZLI\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n",
        encoding="utf-8", newline="",
    )
    parsed, rapor = parse_ics(str(hedef), default_tzid=IST)
    assert parsed == []
    assert rapor.errors, "dosya yolu geçerli .ics METNİ değil, hata vermeli"
    assert "GIZLI" not in str(rapor.errors), "dosyanın içeriği hiç okunmamalı"


def test_path_nesnesiyle_dosya_hala_okunabiliyor(tmp_path):
    """Regresyon değil: Python içinden `Path` AÇIKÇA geçilirse dosyadan
    okumak hâlâ çalışıyor -- testler zaten böyle kullanıyor."""
    hedef = tmp_path / "acik.ics"
    hedef.write_text(
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:acik-1\r\n"
        "DTSTAMP:20260101T090000Z\r\nDTSTART:20260401T090000Z\r\n"
        "DTEND:20260401T100000Z\r\nSUMMARY:Acik\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n",
        encoding="utf-8", newline="",
    )
    parsed, rapor = parse_ics(hedef, default_tzid=IST)
    assert not rapor.errors
    assert len(parsed) == 1
    assert parsed[0].event.title == "Acik"


# ------------------------------------------------------- TKV-API-004 / 005


@pytest.fixture
def repo():
    with Repo.open(":memory:", check_same_thread=False) as r:
        r.add_calendar("Kişisel", "#3b82f6")
        yield r


@pytest.fixture
def sunucu(repo):
    """Gerçek bir HTTP sunucusu, rastgele boş portta."""
    httpd = make_server(repo, IST, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _ham_istek(port: int, basliklar: str, zaman_asimi: float = 5.0) -> bytes:
    """Ham bir HTTP isteği gönderir, ilk yanıtı okuyup döndürür."""
    s = socket.create_connection(("127.0.0.1", port), timeout=zaman_asimi)
    try:
        s.sendall(basliklar.encode("ascii"))
        s.settimeout(zaman_asimi)
        return s.recv(300)
    finally:
        s.close()


def test_statik_kardes_dizin_sizmaz(sunucu):
    """`startswith()` metin öneki karşılaştırıyordu; `STATIC` ile aynı
    ÖNEKİ taşıyan bir kardeş dizindeki dosya sızabiliyordu -- gerçek bir
    kardeş dizinle uçtan uca kanıtlandı. `is_relative_to` düzeltti."""
    import ui.server as sunucu_modul

    kardes = sunucu_modul.STATIC.parent / "static-guvenlik-testi"
    kardes.mkdir(exist_ok=True)
    (kardes / "sir.txt").write_text("SIZAN_ICERIK", encoding="utf-8")
    try:
        with pytest.raises(urllib.error.HTTPError) as bilgi:
            urllib.request.urlopen(
                f"http://127.0.0.1:{sunucu}/../static-guvenlik-testi/sir.txt",
                timeout=10,
            )
        assert bilgi.value.code == 404
    finally:
        (kardes / "sir.txt").unlink()
        kardes.rmdir()


def test_negatif_content_length_aninda_400_doner(sunucu):
    """Eskiden `rfile.read(-1)` bağlantı kapanana kadar okuyup TEK
    THREAD'li sunucuyu TÜM istemciler için kilitliyordu -- ham soketle,
    ardından gelen ilgisiz bir GET'in 12 sn zaman aşımına uğramasıyla
    kanıtlandı. Artık hemen 400 dönüyor, bağlantı asılı kalmıyor."""
    yanit = _ham_istek(
        sunucu,
        f"POST /api/import HTTP/1.1\r\nHost: 127.0.0.1:{sunucu}\r\n"
        "Content-Type: text/calendar\r\nContent-Length: -1\r\n\r\n",
    )
    assert b" 400 " in yanit


def test_sayisal_olmayan_content_length_reddedilir(sunucu):
    yanit = _ham_istek(
        sunucu,
        f"POST /api/import HTTP/1.1\r\nHost: 127.0.0.1:{sunucu}\r\n"
        "Content-Type: text/calendar\r\nContent-Length: muz\r\n\r\n",
    )
    assert b" 400 " in yanit


def test_asiri_buyuk_content_length_reddedilir(sunucu):
    """Zaten vardı (_MAKS_GOVDE), ortak `_icerik_uzunlugu` sonrası da
    çalışmaya devam ediyor mu diye regresyon."""
    yanit = _ham_istek(
        sunucu,
        f"POST /api/import HTTP/1.1\r\nHost: 127.0.0.1:{sunucu}\r\n"
        f"Content-Type: text/calendar\r\nContent-Length: {9 * 1024 * 1024}\r\n\r\n",
    )
    assert b" 400 " in yanit


def test_sozluk_olmayan_json_govdesi_reddedilir(sunucu):
    """`[1,2,3]` gibi geçerli ama sözlük OLMAYAN bir JSON gövdesi eskiden
    `govde.get(...)` içinde yakalanmayan bir `AttributeError`'a düşerdi."""
    req = urllib.request.Request(
        f"http://127.0.0.1:{sunucu}/api/calendars",
        method="POST",
        data=b"[1, 2, 3]",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as bilgi:
        urllib.request.urlopen(req, timeout=10)
    assert bilgi.value.code == 400


def test_normal_json_govdesi_hala_calisiyor(sunucu):
    """Regresyon değil: normal bir sözlük gövdesi hâlâ kabul ediliyor."""
    req = urllib.request.Request(
        f"http://127.0.0.1:{sunucu}/api/calendars",
        method="POST",
        data=b'{"name": "Yeni", "color": "#123456"}',
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as yanit:
        assert yanit.status == 201


# ------------------------------------------------- Host denetimi (DNS rebinding)

_GIZLI_BASLIK = "GIZLI-TOPLANTI"


@pytest.fixture
def dolu_sunucu(repo, sunucu):
    """`sunucu` + içinde tanınabilir bir etkinlik olan depo: `(port, depo, id)`.

    Sızıntıyı ölçmek için: yanıt gövdesinde bu başlığın OLMAMASI gerekiyor.
    """
    takvim_id = repo.list_calendars()[0].id
    kayit = repo.add_event(
        make_event(
            ist(2026, 1, 5, 9, 0), ist(2026, 1, 5, 10, 0),
            event_id=None, uid="gizli-1", title=_GIZLI_BASLIK, calendar_id=takvim_id,
        )
    )
    return sunucu, repo, kayit.id


def _istek(port: int, yol: str, *, host: str | None = None, yontem: str = "GET",
           govde: dict | None = None) -> tuple[int, bytes]:
    """Gerçek bir HTTP isteği; `host` verilirse Host başlığı ONUNLA değişir.

    DNS rebinding'de tarayıcı bağlantıyı 127.0.0.1'e kurar ama `Host`ta
    saldırganın alan adını taşır; burada da aynısı: soket yine 127.0.0.1'e,
    başlık başka. 4xx/5xx istisna FIRLATMAZ, testler durum kodunu ölçüyor.
    """
    basliklar = {}
    if host is not None:
        basliklar["Host"] = host
    veri = None
    if govde is not None:
        veri = json.dumps(govde).encode("utf-8")
        basliklar["Content-Type"] = "application/json"
    istek = urllib.request.Request(
        f"http://127.0.0.1:{port}{yol}", method=yontem, data=veri, headers=basliklar
    )
    try:
        with urllib.request.urlopen(istek, timeout=10) as yanit:
            return yanit.status, yanit.read()
    except urllib.error.HTTPError as hata:
        try:
            return hata.code, hata.read()
        finally:
            hata.close()


@pytest.mark.parametrize(
    "yol",
    [
        "/api/export",
        "/api/week?date=2026-01-05",
        "/api/search?q=GIZLI",
        "/api/calendars",
        "/",
    ],
)
def test_okuma_ucu_kotu_host_ile_403_ve_veri_sizmaz(dolu_sunucu, yol):
    """Saldırgan alan adı 127.0.0.1'e çözülünce tarayıcı sayfayı bizimle
    same-origin sayar; `Origin` denetimi okuma isteklerine bakmadığı için
    `GET /api/export` tüm takvimi veriyordu. `/` de listede: saldırgan
    sayfayı da statik yoldan yükler."""
    port, _, _ = dolu_sunucu
    durum, govde = _istek(port, yol, host=f"kotu.example:{port}")
    assert durum == 403
    assert _GIZLI_BASLIK.encode() not in govde


@pytest.mark.parametrize("host_adi", ["127.0.0.1", "localhost", "LOCALHOST", "[::1]"])
@pytest.mark.parametrize("yol", ["/api/export", "/api/week?date=2026-01-05"])
def test_okuma_ucu_gecerli_host_ile_200(dolu_sunucu, host_adi, yol):
    """Meşru yol: pywebview/tarayıcı 127.0.0.1:PORT (ya da localhost) ile
    gelir. Etkinliğin gövdede OLMASI da şart: yukarıdaki "sızmaz" testleri
    sunucu hiç veri üretmiyorsa boşuna geçerdi."""
    port, _, _ = dolu_sunucu
    durum, govde = _istek(port, yol, host=f"{host_adi}:{port}")
    assert durum == 200
    assert _GIZLI_BASLIK.encode() in govde


def test_kotu_host_yaniti_hata_kodu_tasir(dolu_sunucu):
    """`error` eski sözleşmedeki Türkçe metin; ön yüz çeviriyi `error_code`
    ile yapıyor (`kaynak_guvensiz` ile aynı desen)."""
    port, _, _ = dolu_sunucu
    durum, govde = _istek(port, "/api/calendars", host=f"kotu.example:{port}")
    veri = json.loads(govde)
    assert durum == 403
    assert veri["error_code"] == "host_guvensiz"
    assert isinstance(veri["error"], str)


@pytest.mark.parametrize(
    ("yontem", "yol", "govde"),
    [
        ("POST", "/api/events", {"title": "SIZDI", "date": "2026-01-06", "minutes": 600}),
        ("PATCH", "/api/events/{id}", {"title": "DEGISTI"}),
        ("DELETE", "/api/events/{id}", None),
    ],
)
def test_yazan_istek_kotu_host_ile_403_ve_veri_degismez(dolu_sunucu, yontem, yol, govde):
    """Başlıkları bilerek eksik bırakıyoruz (`Origin`/`Sec-Fetch-Site` yok):
    `_kaynak_guvenli` bu isteği geçirirdi, yani 403'ün tek sebebi `Host`."""
    port, repo, etkinlik_id = dolu_sunucu
    once = repo.list_events()
    durum, _ = _istek(
        port, yol.format(id=etkinlik_id), host=f"kotu.example:{port}",
        yontem=yontem, govde=govde,
    )
    assert durum == 403
    assert repo.list_events() == once


@pytest.mark.parametrize(
    "ek_baslik",
    [
        "Host: kotu.example:{port}",  # host_guvensiz
        "Host: 127.0.0.1:{port}\r\nOrigin: http://kotu.example",  # kaynak_guvensiz
    ],
)
def test_reddedilen_istegin_govdesi_gec_gelse_de_403_okunur(dolu_sunucu, ek_baslik):
    """Başlıklar ve gövde AYRI ulaşınca reddedilen istek yine 403 almalı.

    `http.client` ve tarayıcılar başlıkları gövdeden ayrı gönderebilir. Sunucu
    başlıklara bakıp hemen 403 yazıp bağlantıyı kapatırsa gövde kapanmış
    bağlantıya ulaşır, TCP sıfırlaması yanıtı da ezer ve istemci 403 yerine
    `ConnectionAbortedError` görürdü (ölçüldü: 20/20; tam test takımında
    `urllib` testleri kararsız düşüyordu). Burada boşluk kasten 150 ms.
    """
    import time

    port, _, etkinlik_id = dolu_sunucu
    govde = b'{"title": "x"}' * 40
    baslik = (
        f"PATCH /api/events/{etkinlik_id} HTTP/1.1\r\n"
        + ek_baslik.format(port=port)
        + "\r\nContent-Type: application/json\r\n"
        + f"Content-Length: {len(govde)}\r\n\r\n"
    ).encode("ascii")
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(baslik)
        time.sleep(0.15)
        s.sendall(govde)
        yanit = b""
        while parca := s.recv(4096):
            yanit += parca
    assert b" 403 " in yanit.split(b"\r\n")[0], yanit[:80]


def test_yazan_istek_gecerli_host_ile_calisir(dolu_sunucu):
    """Olumlu kontrol: aynı POST doğru `Host` ile kaydediyor (yukarıdaki
    "veri değişmedi" testi sunucu hiç yazmıyorsa boşuna geçerdi)."""
    port, repo, _ = dolu_sunucu
    once = len(repo.list_events())
    durum, _ = _istek(
        port, "/api/events", host=f"127.0.0.1:{port}", yontem="POST",
        govde={"title": "Gercek", "date": "2026-01-06", "minutes": 600},
    )
    assert durum == 201
    assert len(repo.list_events()) == once + 1


def test_yanlis_portlu_host_reddedilir(dolu_sunucu):
    """`bos_port_bul` istenenden farklı port seçebiliyor: geçerli olan
    GERÇEK port, başka bir loopback portu değil (başka bir yerel servisin
    alan adı yönlendirmesiyle gelen istek de aynı yoldan gelir)."""
    port, _, _ = dolu_sunucu
    assert _istek(port, "/api/calendars", host="127.0.0.1:1")[0] == 403
    assert _istek(port, "/api/calendars", host=f"127.0.0.1:{port + 1}")[0] == 403


def test_portsuz_host_reddedilir(dolu_sunucu):
    """Tarayıcı varsayılan olmayan porta giderken `Host`a portu da yazar;
    portsuz `127.0.0.1` bu sunucuya değil 80. porta gidiş demektir."""
    port, _, _ = dolu_sunucu
    assert _istek(port, "/api/calendars", host="127.0.0.1")[0] == 403


def test_host_basligi_hic_yoksa_gecer(sunucu):
    """HTTP/1.0 istemcisi `Host` göndermeyebilir (komut satırı araçları,
    betikler); tarayıcı her zaman gönderir. `Origin` politikasıyla aynı
    gerekçe: başlık yoksa saldırı yüzeyi (tarayıcı) da yok."""
    yanit = _ham_istek(sunucu, "GET /api/calendars HTTP/1.0\r\n\r\n")
    assert b" 200 " in yanit


@pytest.mark.parametrize(
    ("host_basligi", "bagli_host", "port", "beklenen"),
    [
        # loopback'e bağlı sunucu: yalnızca üç yazım, GERÇEK portla
        ("127.0.0.1:8765", "127.0.0.1", 8765, True),
        ("localhost:8765", "127.0.0.1", 8765, True),
        ("[::1]:8765", "127.0.0.1", 8765, True),
        ("[::1]:8765", "::1", 8765, True),
        ("localhost:8765", "localhost", 8765, True),
        # büyük/küçük harf duyarsız
        ("LOCALHOST:8765", "127.0.0.1", 8765, True),
        ("LocalHost:8765", "localhost", 8765, True),
        # başlık hiç yok: geç
        (None, "127.0.0.1", 8765, True),
        (None, "::1", 8765, True),
        # saldırganın alan adı
        ("kotu.example:8765", "127.0.0.1", 8765, False),
        ("127.0.0.1.kotu.example:8765", "127.0.0.1", 8765, False),
        ("localhost.kotu.example:8765", "127.0.0.1", 8765, False),
        ("127.0.0.1:8765, kotu.example", "127.0.0.1", 8765, False),
        # yanlış / eksik / bozuk port
        ("127.0.0.1:1", "127.0.0.1", 8765, False),
        ("127.0.0.1:8766", "127.0.0.1", 8765, False),
        ("127.0.0.1:08765", "127.0.0.1", 8765, False),
        ("127.0.0.1", "127.0.0.1", 8765, False),
        ("localhost", "127.0.0.1", 8765, False),
        ("[::1]", "127.0.0.1", 8765, False),
        ("127.0.0.1:", "127.0.0.1", 8765, False),
        # köşeli parantezsiz IPv6 geçerli bir Host değil
        ("::1:8765", "127.0.0.1", 8765, False),
        # başlık var ama boş: "hiç yok"tan FARKLI, reddedilir
        ("", "127.0.0.1", 8765, False),
        # loopback DIŞI bağlı sunucu (--ag-erisimine-izin-ver): denetim atlanır
        ("kotu.example:8765", "0.0.0.0", 8765, True),
        ("192.168.1.5:8765", "192.168.1.5", 8765, True),
        ("evim.lan", "192.168.1.5", 8765, True),
        ("", "0.0.0.0", 8765, True),
        (None, "0.0.0.0", 8765, True),
    ],
)
def test_host_gecerli_mi_tablosu(host_basligi, bagli_host, port, beklenen):
    assert host_gecerli_mi(host_basligi, bagli_host, port) is beklenen


@pytest.mark.parametrize(
    "bagli_host",
    ["127.0.0.1", "::1", "localhost", "0.0.0.0", "192.168.1.5", "evim.lan"],
)
def test_host_denetimi_loopback_kumesi_main_ile_ayni(bagli_host):
    """`ui/server.py` kümeyi `ui/__main__.py::_loopback_mi`den import
    edemiyor (döngü); iki kopya ayrışırsa `--host` doğrulaması ile `Host`
    denetimi farklı adreslere farklı davranırdı."""
    denetleniyor = not host_gecerli_mi("kotu.example:1", bagli_host, 1)
    assert denetleniyor == _loopback_mi(bagli_host)


def test_host_guvensiz_kodu_iki_dilde_cevrili():
    """Ön yüz hata metnini `hata_<kod>` anahtarından çeviriyor; anahtar
    yoksa İngilizce kullanıcı Türkçe ham metni görürdü."""
    metin = (STATIC / "i18n.js").read_text(encoding="utf-8")
    assert metin.count("hata_host_guvensiz:") == 2  # TR + EN
