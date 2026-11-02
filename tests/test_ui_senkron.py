"""Senkron dosyası uçları (`/api/senkron/disa`, `/api/senkron/ice`) ve arayüz metinleri.

Gerçek HTTP sunucusu, dosya veritabanı geçici klasörde (gerçek
%LOCALAPPDATA% veritabanına ASLA dokunulmaz).
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from core import Event
from senkron import durum_uret, json_metni
from store import Repo
from tests.helpers import IST, ist
from ui.server import STATIC, make_server


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "takvim.db")


@pytest.fixture
def repo(db):
    with Repo.open(db, check_same_thread=False) as r:
        yield r


@pytest.fixture
def sunucu(repo, db):
    httpd = make_server(repo, IST, host="127.0.0.1", port=0, db_yolu=db)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _diger_cihaz_dosyasi() -> str:
    """Başka bir 'cihaz'ın tek takvim + tek etkinlikli dosyası."""
    with Repo.open(":memory:") as diger:
        k = diger.add_calendar("Telefon", "#3b82f6")
        diger.add_event(Event(
            id=None, uid="tel-1", calendar_id=k.id, title="Telefondan gelen",
            start_utc=ist(2026, 11, 3, 10), end_utc=ist(2026, 11, 3, 11), tzid=IST,
        ))
        return json_metni(durum_uret(diger, cihaz_id="tel", cihaz_adi="Telefon", uygulama="test"))


def _post(temel, metin, basliklar=None):
    """(durum, gövde) döndürür; HTTP hatalarında da gövdeyi okur."""
    req = urllib.request.Request(
        temel + "/api/senkron/ice", method="POST", data=metin.encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8", **(basliklar or {})},
    )
    try:
        with urllib.request.urlopen(req) as yanit:
            return yanit.status, json.loads(yanit.read().decode("utf-8"))
    except urllib.error.HTTPError as hata:
        return hata.code, json.loads(hata.read().decode("utf-8"))


def test_disa_aktarma_dosya_olarak_iner(sunucu, repo):
    repo.add_calendar("Kişisel", "#3b82f6")

    with urllib.request.urlopen(sunucu + "/api/senkron/disa") as yanit:
        govde = json.loads(yanit.read().decode("utf-8"))
        ek = yanit.headers["Content-Disposition"]

    assert ek.startswith("attachment;") and ".takvimsync" in ek
    assert govde["format"] == "takvim-sync" and govde["version"] == 1
    assert govde["device"]["app"].startswith("desktop ")
    assert [c["name"] for c in govde["calendars"]] == ["Kişisel"]


def test_disa_aktarma_cihaz_kimligi_kalici(sunucu, tmp_path):
    def kimlik():
        with urllib.request.urlopen(sunucu + "/api/senkron/disa") as yanit:
            return json.loads(yanit.read().decode("utf-8"))["device"]["id"]

    ilk = kimlik()

    assert kimlik() == ilk
    assert json.loads((tmp_path / "cihaz.json").read_text(encoding="utf-8"))["id"] == ilk


def test_ice_aktarma_birlestirir_ve_rapor_doner(sunucu, repo):
    durum, rapor = _post(sunucu, _diger_cihaz_dosyasi())

    assert durum == 200
    assert rapor["added"] == {"calendar": 1, "event": 1, "task": 0}
    assert rapor["total"] == {"added": 2, "updated": 0, "deleted": 0, "skipped": 0}
    assert repo.get_event_by_uid("tel-1") is not None
    with urllib.request.urlopen(sunucu + "/api/week?date=2026-11-03") as yanit:
        hafta = json.loads(yanit.read().decode("utf-8"))
    assert any(o["title"] == "Telefondan gelen" for g in hafta["days"] for o in g["timed"])


def test_ice_aktarma_ikinci_kez_degisiklik_yok(sunucu):
    metin = _diger_cihaz_dosyasi()
    _post(sunucu, metin)

    durum, rapor = _post(sunucu, metin)

    assert durum == 200 and rapor["total"] == {"added": 0, "updated": 0, "deleted": 0, "skipped": 0}


def test_disa_sonra_ice_ayni_sunucuda_degistirmez(sunucu, repo):
    k = repo.add_calendar("Kişisel", "#3b82f6")
    repo.add_event(Event(
        id=None, uid="e1", calendar_id=k.id, title="X",
        start_utc=ist(2026, 11, 3, 10), end_utc=ist(2026, 11, 3, 11), tzid=IST,
    ))
    with urllib.request.urlopen(sunucu + "/api/senkron/disa") as yanit:
        metin = yanit.read().decode("utf-8")

    durum, rapor = _post(sunucu, metin)

    assert durum == 200 and rapor["total"]["added"] == rapor["total"]["updated"] == 0


def test_bozuk_dosya_400_ve_kodlu_hata(sunucu, repo):
    durum, govde = _post(sunucu, "{ bu json değil")

    assert durum == 400
    assert govde["error_code"] == "senkron_bozuk"
    assert govde["error"].startswith("senkron dosyası geçersiz:")
    assert repo.list_calendars() == []


def test_yeni_surum_400_guncelle_der(sunucu):
    dosya = json.loads(_diger_cihaz_dosyasi())
    dosya["version"] = 99

    durum, govde = _post(sunucu, json.dumps(dosya))

    assert durum == 400 and govde["error_code"] == "senkron_surum_yeni"
    assert govde["error_param"] == {"dosya": 99, "uygulama": 1}


def test_yabanci_kaynaktan_ice_aktarma_reddedilir(sunucu, repo):
    """Kural 40: başka sayfadan gelen POST veriyi değiştiremez."""
    durum, govde = _post(sunucu, _diger_cihaz_dosyasi(), {"Origin": "http://kotu.example"})

    assert durum == 403 and govde["error_code"] == "kaynak_guvensiz"
    assert repo.list_calendars() == []


def test_yabanci_host_ile_disa_aktarma_reddedilir(sunucu):
    """Kural 77: DNS rebinding ile tüm takvim okunamasın."""
    req = urllib.request.Request(sunucu + "/api/senkron/disa", headers={"Host": "kotu.example"})

    with pytest.raises(urllib.error.HTTPError) as hata:
        urllib.request.urlopen(req)

    assert hata.value.code == 403


def test_bellek_veritabaninda_da_disa_aktarilir():
    """db_yolu yok (test/--demo): kimlik kalıcı değil ama uç çalışır."""
    with Repo.open(":memory:", check_same_thread=False) as r:
        httpd = make_server(r, IST, host="127.0.0.1", port=0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_address[1]}/api/senkron/disa") as y:
                assert json.loads(y.read().decode("utf-8"))["format"] == "takvim-sync"
        finally:
            httpd.shutdown()
            httpd.server_close()


# ---------------------------------------------------------------------------
# Arayüz metinleri: TR + EN, eksik anahtar İngilizce kullanıcıya ham anahtar gösterirdi
# ---------------------------------------------------------------------------

def _anahtarlar(blok: str) -> set[str]:
    return set(re.findall(r"^  ([a-z_0-9]+):", blok, re.MULTILINE))


def test_senkron_metinleri_iki_dilde_var():
    i18n = (STATIC / "i18n.js").read_text(encoding="utf-8")
    tr, en = i18n.split("const EN = {")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    kullanilan = set(re.findall(r't\("(senkron_[a-z_]+)"', app))

    assert len(kullanilan) >= 10, "arayüz senkron metinlerini kullanıyor olmalı"
    for anahtar in kullanilan | {"hata_senkron_bozuk", "hata_senkron_surum_yeni"}:
        assert anahtar in _anahtarlar(tr), f"TR'de yok: {anahtar}"
        assert anahtar in _anahtarlar(en), f"EN'de yok: {anahtar}"


def test_senkron_arayuz_baglantilari_yerinde():
    """Dosya girdisi sayfada, Ayarlar eylemleri sunucu uçlarına bağlı."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'id="senkron-dosya"' in html and ".takvimsync" in html
    assert "/api/senkron/disa" in app and "/api/senkron/ice" in app
    assert Path(STATIC / "i18n.js").read_text(encoding="utf-8").count("senkron_disa_btn:") == 2
