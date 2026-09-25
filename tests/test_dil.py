"""TR/EN dil seçeneği: ayar, sunucu hata kodları, İngilizce payload, bildirim.

Varsayılan dil `tr`; bu dosya İngilizce yolun çalıştığını kilitliyor.
Türkçe davranışın değişmediğini mevcut 400+ test zaten söylüyor.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import date

import pytest

from store import Repo
from tests.helpers import IST, ist
from ui.presenter import day_payload, month_payload, week_payload
from ui.server import _hata_esle, make_server


@pytest.fixture
def repo():
    """Bellekte taze DB."""
    with Repo.open(":memory:", check_same_thread=False) as r:
        yield r


@pytest.fixture
def sunucu(repo):
    """Bellek DB'li canlı sunucu."""
    repo.add_calendar("Ders", "#e0524a")
    httpd = make_server(repo, IST, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def sunucu_dosya(tmp_path):
    """Dosya DB'li canlı sunucu (ayarlar.json yazılabiliyor)."""
    db = str(tmp_path / "takvim.db")
    repo = Repo.open(db, check_same_thread=False)
    repo.add_calendar("Ders", "#e0524a")
    httpd = make_server(repo, IST, host="127.0.0.1", port=0, db_yolu=db)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", tmp_path
    finally:
        httpd.shutdown()
        httpd.server_close()
        repo.close()


def _jget(temel, yol):
    with urllib.request.urlopen(temel + yol) as yanit:
        return json.loads(yanit.read().decode("utf-8"))


def _jpost(temel, yol, govde):
    req = urllib.request.Request(
        temel + yol, method="POST",
        data=json.dumps(govde).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req) as yanit:
        return json.loads(yanit.read().decode("utf-8"))


def _hata_govdesi(temel, yol, govde):
    req = urllib.request.Request(
        temel + yol, method="POST",
        data=json.dumps(govde).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as hata:
        assert hata.code == 400
        return json.loads(hata.read().decode("utf-8"))
    raise AssertionError("400 bekleniyordu")


# ---------------------------------------------------------------------------
# ayarlar.json: dil anahtarı
# ---------------------------------------------------------------------------

def test_dil_varsayilan_tr(tmp_path):
    """Dosya yoksa dil Türkçe."""
    from ui.ayarlar import ayar_dosyasi, ayar_oku

    assert ayar_oku(ayar_dosyasi(tmp_path))["dil"] == "tr"


def test_dil_gecersiz_deger_tr_ye_duser(tmp_path):
    """Elde yazılmış `"de"` sessizce kabul edilmiyor."""
    import json as j

    from ui.ayarlar import ayar_dosyasi, ayar_oku

    yol = ayar_dosyasi(tmp_path)
    yol.write_text(j.dumps({"dil": "de"}), encoding="utf-8")
    assert ayar_oku(yol)["dil"] == "tr"


def test_dil_en_gidis_donus(tmp_path):
    """Yazılan `en` aynen okunuyor."""
    from ui.ayarlar import ayar_dosyasi, ayar_oku, ayar_yaz

    yol = ayar_dosyasi(tmp_path)
    assert ayar_yaz(yol, {"dil": "en"}) is True
    assert ayar_oku(yol)["dil"] == "en"


def test_ayarlar_api_dil_kaydedilir(sunucu_dosya):
    """POST /api/ayarlar dili dosyaya yazıyor, GET'e yansıyor."""
    from ui.ayarlar import ayar_dosyasi, ayar_oku

    temel, tmp_path = sunucu_dosya
    assert _jpost(temel, "/api/ayarlar", {"dil": "en"})["dil"] == "en"
    assert ayar_oku(ayar_dosyasi(tmp_path))["dil"] == "en"


def test_ayarlar_api_gecersiz_dil_400(sunucu_dosya):
    """Kapalı küme dışı dil reddediliyor."""
    temel, _ = sunucu_dosya
    try:
        _jpost(temel, "/api/ayarlar", {"dil": "de"})
    except urllib.error.HTTPError as hata:
        assert hata.code == 400
        return
    raise AssertionError("400 bekleniyordu")


# ---------------------------------------------------------------------------
# sunucu hata kodları: `error` aynı, `error_code` ekleniyor
# ---------------------------------------------------------------------------

def test_hata_kodu_baslik_bos(sunucu):
    """Boş başlık: Türkçe mesaj + kod birlikte dönüyor."""
    govde = _hata_govdesi(
        sunucu, "/api/events",
        {"title": "   ", "date": "2026-09-14", "minutes": 600},
    )
    assert govde["error"] == "başlık boş"
    assert govde["error_code"] == "baslik_bos"


def test_hata_kodu_parametreli(sunucu):
    """Dinamik mesajda parametre ayrı alanda taşınıyor."""
    govde = _hata_govdesi(
        sunucu, "/api/events",
        {"title": "x", "date": "2026-09-14", "minutes": 1500},
    )
    assert govde["error"] == "minutes gün içinde olmalı: 1500"
    assert govde["error_code"] == "minutes_aralik"
    assert govde["error_param"] == {"dakika": 1500}


def test_hata_kodu_bilinmeyen_yol(sunucu):
    """404 gövdesi de kod taşıyor."""
    try:
        urllib.request.urlopen(sunucu + "/api/yok-boyle-uc", timeout=10)
    except urllib.error.HTTPError as hata:
        assert hata.code == 404
        govde = json.loads(hata.read().decode("utf-8"))
        assert govde == {"error": "bulunamadı", "error_code": "bulunamadi"}
        return
    raise AssertionError("404 bekleniyordu")


def test_hata_esle_depo_mesajlari():
    """`store/` mesajları koda çevriliyor (`store/`a dokunulmadan)."""
    assert _hata_esle("Etkinlik bulunamadı: id=5") == (
        "etkinlik_bulunamadi", {"id": "5"})
    assert _hata_esle("etkinlik bulunamadı") == ("etkinlik_bulunamadi", None)
    assert _hata_esle("takvim bulunamadı") == ("takvim_bulunamadi", None)
    assert _hata_esle("Boş metin ayrıştırılamaz") == ("metin_bos", None)
    assert _hata_esle("çok kurallı seriler bölünemez") == (
        "seri_bolunemez_cok_kuralli", None)
    assert _hata_esle("bilinmeyen bir şey oldu") == (None, None)


# ---------------------------------------------------------------------------
# İngilizce payload: gün/ay adları + etiketler
# ---------------------------------------------------------------------------

def test_ingilizce_gun_adlari(repo):
    """`dayName`/`monthName` İngilizce geliyor."""
    from core import Event
    from store import new_uid

    takvim = repo.add_calendar("Ders", "#e0524a")
    repo.add_event(
        Event(
            id=None, uid=new_uid(), calendar_id=takvim.id, title="Ders",
            start_utc=ist(2026, 9, 14, 10, 0), end_utc=ist(2026, 9, 14, 11, 0),
            tzid=IST,
        )
    )
    payload = day_payload(repo, date(2026, 9, 14), IST, dil="en")
    gun = payload["days"][0]
    assert gun["dayName"] == "Mon"
    assert gun["monthName"] == "September"
    assert payload["label"] == "Monday 14 September 2026"


def test_ingilizce_hafta_etiketi(repo):
    """Hafta başlığı aynı yapıda, İngilizce ay adıyla."""
    repo.add_calendar("Ders", "#e0524a")
    payload = week_payload(repo, date(2026, 9, 9), IST, dil="en")
    assert payload["label"] == "7 - 13 September 2026"


def test_ingilizce_ay_etiketi_ve_gunler(repo):
    """Ay başlığı + `dayNames` İngilizce."""
    repo.add_calendar("Ders", "#e0524a")
    payload = month_payload(repo, date(2026, 9, 15), IST, dil="en")
    assert payload["label"] == "September 2026"
    assert payload["dayNames"] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def test_turkce_varsayilan_degismedi(repo):
    """`dil` verilmezse her şey eskisi gibi Türkçe."""
    repo.add_calendar("Ders", "#e0524a")
    payload = day_payload(repo, date(2026, 9, 14), IST)
    assert payload["days"][0]["dayName"] == "Pzt"
    assert payload["label"] == "14 Eylül 2026 Pazartesi"


def test_api_hafta_dile_gore_yerellesiyor(sunucu_dosya):
    """Ayar `en` olunca `/api/week` İngilizce adlar dönüyor."""
    temel, _ = sunucu_dosya
    _jpost(temel, "/api/ayarlar", {"dil": "en"})
    payload = _jget(temel, "/api/week?date=2026-09-09")
    assert payload["label"] == "7 - 13 September 2026"
    assert payload["days"][0]["dayName"] == "Mon"


# ---------------------------------------------------------------------------
# varsayılan takvim adı + hatırlatıcı bildirimi
# ---------------------------------------------------------------------------

def test_varsayilan_takvim_en_personal(repo):
    """İngilizce kurulumda ilk takvim "Personal"."""
    from ui.__main__ import varsayilan_takvim_saglat

    assert varsayilan_takvim_saglat(repo, dil="en") is True
    assert [c.name for c in repo.list_calendars()] == ["Personal"]


def test_varsayilan_takvim_tr_kisisel(repo):
    """Türkçe varsayılan değişmedi."""
    from ui.__main__ import varsayilan_takvim_saglat

    assert varsayilan_takvim_saglat(repo) is True
    assert [c.name for c in repo.list_calendars()] == ["Kişisel"]


def test_bildirim_metni_ingilizce(repo):
    """Toast gövdesi İngilizce kuruluyor."""
    from core import Event
    from remind.daemon import bildirim_metni
    from store import new_uid
    from tests.helpers import ist as _ist

    takvim = repo.add_calendar("Ders", "#e0524a")
    event = repo.add_event(
        Event(
            id=None, uid=new_uid(), calendar_id=takvim.id, title="Ders",
            start_utc=_ist(2026, 9, 14, 10, 0), end_utc=_ist(2026, 9, 14, 11, 30),
            tzid=IST, location="B204",
        )
    )
    repo.add_reminder(event.id, 30)

    class _Due:
        minutes_before = 30

        def __init__(self, occ):
            self.occurrence = occ

    occ = repo.occurrences(_ist(2026, 9, 14, 8, 0), _ist(2026, 9, 14, 12, 0))[0]
    baslik, govde = bildirim_metni(_Due(occ), IST, dil="en")
    assert baslik == "Ders"
    assert "10:00 – 11:30" in govde
    assert "in 30 minutes" in govde
    assert "B204" in govde


def test_bildirim_metni_ingilizce_tumgun(repo):
    """Tüm gün + `şimdi` kalıpları İngilizce."""
    from core import Event
    from remind.daemon import bildirim_metni
    from store import new_uid
    from tests.helpers import ist as _ist

    takvim = repo.add_calendar("Ders", "#e0524a")
    repo.add_event(
        Event(
            id=None, uid=new_uid(), calendar_id=takvim.id, title="Tatil",
            start_utc=_ist(2026, 9, 14), end_utc=_ist(2026, 9, 15),
            tzid=IST, all_day=True,
        )
    )

    class _Due:
        minutes_before = 0

        def __init__(self, occ):
            self.occurrence = occ

    occ = repo.occurrences(_ist(2026, 9, 14, 0, 0), _ist(2026, 9, 14, 1, 0))[0]
    _, govde = bildirim_metni(_Due(occ), IST, dil="en")
    assert "All day" in govde
    assert "14/09/2026" in govde
    assert "starting now" in govde
