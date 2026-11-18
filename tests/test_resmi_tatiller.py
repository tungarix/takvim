"""Resmi tatiller: saf veri, görünüm yanıtındaki ayrı alan, ayar ve "kullanıcı verisi değil" ilkesi.

Gerçek %LOCALAPPDATA% DB'sine dokunmaz: dosya DB'si tmp_path'te.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import date

import pytest

from core.resmi_tatiller import resmi_tatiller
from store import Repo
from tests.helpers import IST
from ui.ayarlar import ayar_dosyasi, ayar_yaz
from ui.presenter import month_payload, week_payload
from ui.server import make_server


def _adlar(bas, bit):
    return [(t.tarih.isoformat(), t.ad_tr) for t in resmi_tatiller(bas, bit)]


def test_sabit_gunler_her_yil_sekiz_kayit():
    for yil in (2024, 2030, 2035):
        sabit = [t for t in resmi_tatiller(date(yil, 1, 1), date(yil, 12, 31)) if t.tur == "ulusal"]
        assert len(sabit) == 8
    arife = [t for t in resmi_tatiller(date(2026, 10, 1), date(2026, 10, 31)) if t.yarim_gun]
    assert [t.tarih for t in arife] == [date(2026, 10, 28)]


def test_dini_bayram_ramazan_2026():
    # 2026 Ramazan: arife + 3 gün (Diyanet: 20-23 Mart; arife 19 Mart).
    gunler = [t for t in resmi_tatiller(date(2026, 3, 1), date(2026, 3, 31)) if t.tur == "dini"]
    assert [t.tarih.day for t in gunler] == [19, 20, 21, 22]
    assert gunler[0].yarim_gun and not any(t.yarim_gun for t in gunler[1:])
    assert gunler[0].ad_en.startswith("Eve of")


def test_kapsam_disi_yilda_yalniz_sabit_gunler():
    # 2040 tabloda yok: dini bayram uydurulmaz. 2028 Ramazan da kaynak çelişkisiyle dışarıda.
    assert {t.tur for t in resmi_tatiller(date(2040, 1, 1), date(2040, 12, 31))} == {"ulusal"}
    assert {t.tur for t in resmi_tatiller(date(2028, 2, 1), date(2028, 3, 31))} == set()


def test_ayni_gune_iki_kayit_tam_gun_once():
    t = resmi_tatiller(date(2029, 4, 23), date(2029, 4, 23))
    assert [x.yarim_gun for x in t] == [False, True]


def test_aralik_uclari_dahil_ve_yil_sinirini_asar():
    t = resmi_tatiller(date(2025, 12, 31), date(2026, 1, 1))
    assert [x.tarih for x in t] == [date(2026, 1, 1)]


@pytest.fixture
def repo():
    with Repo.open(":memory:") as r:
        r.add_calendar("Ders", "#e0524a")
        yield r


def test_ay_ve_hafta_yanitinda_holidays_alani(repo):
    ay = month_payload(repo, date(2026, 10, 1), IST)
    gun = {g["date"]: g for g in ay["days"]}
    assert gun["2026-10-29"]["holidays"] == [{"name": "Cumhuriyet Bayramı", "halfDay": False, "kind": "ulusal"}]
    assert gun["2026-10-28"]["holidays"][0]["halfDay"] is True
    assert gun["2026-10-15"]["holidays"] == []
    hafta = week_payload(repo, date(2026, 10, 29), IST, dil="en")
    assert [h["name"] for g in hafta["days"] for h in g["holidays"]] == ["Eve of Republic Day", "Republic Day"]


def test_ayar_kapaliyken_tatil_yok(repo):
    ay = month_payload(repo, date(2026, 10, 1), IST, resmi_tatil=False)
    assert all(g["holidays"] == [] for g in ay["days"])


@pytest.fixture
def sunucu(tmp_path):
    db = str(tmp_path / "takvim.db")
    repo = Repo.open(db, check_same_thread=False)
    repo.add_calendar("Kişisel", "#3b82f6")
    httpd = make_server(repo, IST, host="127.0.0.1", port=0, db_yolu=db)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", tmp_path
    httpd.shutdown()
    httpd.server_close()


def _al(temel, yol):
    with urllib.request.urlopen(temel + yol) as y:
        return y.read().decode("utf-8")


def test_sunucu_ayara_uyar(sunucu):
    temel, tmp_path = sunucu
    ay = json.loads(_al(temel, "/api/month?date=2026-10-01"))
    assert any(g["holidays"] for g in ay["days"])
    ayar_yaz(ayar_dosyasi(tmp_path), {"resmi_tatiller": False})
    ay = json.loads(_al(temel, "/api/month?date=2026-10-01"))
    assert not any(g["holidays"] for g in ay["days"])


def test_ayar_api_ile_kaydedilir_ve_tipi_denetlenir(sunucu):
    temel, _ = sunucu

    def gonder(govde):
        istek = urllib.request.Request(
            temel + "/api/ayarlar", method="POST", data=json.dumps(govde).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(istek) as y:
                return y.status, json.loads(y.read())
        except urllib.error.HTTPError as h:
            return h.code, None

    assert json.loads(_al(temel, "/api/ayarlar"))["resmi_tatiller"] is True
    assert gonder({"resmi_tatiller": False})[1]["resmi_tatiller"] is False
    assert gonder({"resmi_tatiller": "hayir"})[0] == 400


def test_tatiller_ics_ve_senkrona_girmez(sunucu):
    temel, _ = sunucu
    ics = _al(temel, "/api/export")
    senkron = _al(temel, "/api/senkron/disa")
    for metin in (ics, senkron):
        assert "Cumhuriyet" not in metin and "Yılbaşı" not in metin
    assert "VEVENT" not in ics
    assert json.loads(senkron)["events"] == []
