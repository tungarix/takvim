"""Güvenlik denetimi düzeltmeleri (TKV-API-001..005).

Bulguların hepsi önce ELLE çalıştırılarak (gerçek HTTP istekleri, ham
soketler, ölçülen süreler) doğrulandı -- buradaki testler o kanıtlanmış
davranışı regresyona karşı kilitliyor. Denetim raporu ve ölçümler sohbette.
"""

from __future__ import annotations

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
from tests.helpers import IST, ist
from ui.__main__ import _ag_erisimi_dogrula, _loopback_mi
from ui.server import make_server

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
        "POST /api/import HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        "Content-Type: text/calendar\r\nContent-Length: -1\r\n\r\n",
    )
    assert b" 400 " in yanit


def test_sayisal_olmayan_content_length_reddedilir(sunucu):
    yanit = _ham_istek(
        sunucu,
        "POST /api/import HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        "Content-Type: text/calendar\r\nContent-Length: muz\r\n\r\n",
    )
    assert b" 400 " in yanit


def test_asiri_buyuk_content_length_reddedilir(sunucu):
    """Zaten vardı (_MAKS_GOVDE), ortak `_icerik_uzunlugu` sonrası da
    çalışmaya devam ediyor mu diye regresyon."""
    yanit = _ham_istek(
        sunucu,
        "POST /api/import HTTP/1.1\r\nHost: 127.0.0.1\r\n"
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
