"""Hızlı ekleme: "görev: rapor yaz yarın 14:00" (core ayrıştırıcı + /api/tasks {"text"})."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

import pytest

from core import UTC, gorev_metni_mi, parse_task_add, to_local
from store import Repo
from tests.helpers import IST, ist
from ui.server import make_server

# Çarşamba 30 Eylül 2026, İstanbul 12:00: "yarın" = 1 Ekim.
SIMDI = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)


def _coz(metin):
    return parse_task_add(metin, now=SIMDI, tzid=IST)


# ---------------------------------------------------------------------------
# Önek
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("metin", ["görev: x", "Görev: x", "GÖREV:x", "gorev : x", "  görev:   x"])
def test_gorev_oneki_taninir(metin):
    assert gorev_metni_mi(metin)


@pytest.mark.parametrize("metin", ["görev toplantısı yarın 10:00", "yarın görev: x", "görevli izin", "", "x"])
def test_iki_nokta_olmadan_onek_sayilmaz(metin):
    """"görev toplantısı" bir etkinlik başlığı olabilir; ilk kelimeye bakıp görev sanmamalı."""
    assert not gorev_metni_mi(metin)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

def test_zaman_yoksa_plansiz():
    """Etkinlikte zamansız metin 'bugünün tüm günü' olurdu; görevde 'plansız'."""
    r = _coz("görev: rapor yaz")

    assert (r.title, r.plan, r.day, r.start_utc, r.matched) == ("rapor yaz", "yok", None, None, "")


def test_yalniz_tarih_gun_planli():
    r = _coz("görev: rapor yaz yarın")

    assert (r.title, r.plan, r.day, r.start_utc, r.matched) == ("rapor yaz", "gun", date(2026, 10, 1), None, "yarın")


def test_gun_adi_ve_ay_tarihi_gun_planli():
    assert _coz("görev: market cuma").day == date(2026, 10, 2)
    assert _coz("görev: market 3 ekim").day == date(2026, 10, 3)


def test_saat_varsa_saat_planli_bir_saat_varsayilan():
    r = _coz("görev: rapor yaz yarın 14:00")

    assert (r.plan, r.day, r.start_utc, r.end_utc) == ("saat", date(2026, 10, 1), ist(2026, 10, 1, 14), ist(2026, 10, 1, 15))


def test_saat_araligi_saat_planli():
    r = _coz("görev: rapor yaz yarın 14:00-15:30")

    assert (r.title, r.start_utc, r.end_utc) == ("rapor yaz", ist(2026, 10, 1, 14), ist(2026, 10, 1, 15, 30))


def test_yalniz_saat_bugune_duser():
    """Tarih yoksa referans BUGÜN (AGENTS 45)."""
    r = _coz("görev: ara 16:30")

    assert (r.plan, r.day, r.start_utc) == ("saat", date(2026, 9, 30), ist(2026, 9, 30, 16, 30))


def test_gun_gece_yarisindan_hemen_sonra_yerel_gundur():
    """00:30 İstanbul, UTC'de önceki gün: `day` yerel takvim günü olmalı."""
    r = _coz("görev: nöbet yarın 00:30")

    assert (r.day, r.start_utc) == (date(2026, 10, 1), ist(2026, 10, 1, 0, 30))


# ---------------------------------------------------------------------------
# Reddedilenler
# ---------------------------------------------------------------------------

def test_tekrarli_gorev_reddedilir():
    """Tekrarlı görevde 'tamamlandı' hangi örnek için olurdu; sessizce tek seferliğe çevirmek yok."""
    with pytest.raises(ValueError, match="tekrarlanamaz"):
        _coz("görev: spor her salı 18:00")


def test_bos_ve_basliksiz_reddedilir():
    with pytest.raises(ValueError, match="Boş metin"):
        _coz("görev:")
    with pytest.raises(ValueError, match="başlığı boş"):
        _coz("görev: yarın 14:00")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

@pytest.fixture
def sunucu():
    with Repo.open(":memory:", check_same_thread=False) as repo:
        repo.add_calendar("Ders", "#e0524a")
        httpd = make_server(repo, IST, host="127.0.0.1", port=0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            yield f"http://127.0.0.1:{httpd.server_address[1]}", repo
        finally:
            httpd.shutdown()
            httpd.server_close()


def _post(temel, govde):
    req = urllib.request.Request(
        temel + "/api/tasks", method="POST", data=json.dumps(govde).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req) as yanit:
            return yanit.status, json.loads(yanit.read().decode("utf-8"))
    except urllib.error.HTTPError as hata:
        return hata.code, json.loads(hata.read().decode("utf-8"))


def test_metinle_saat_planli_gorev_blok_olusturur(sunucu):
    temel, repo = sunucu

    durum, yanit = _post(temel, {"text": "görev: rapor yaz yarın 14:00-15:30"})

    assert durum == 201
    g = yanit["task"]
    assert (g["title"], g["plan"], g["startMin"], g["endMin"]) == ("rapor yaz", "saat", 840, 930)
    assert g["day"] == _yarin()
    assert yanit["parsed"] == {"title": "rapor yaz", "matched": "yarın 14:00-15:30", "plan": "saat"}
    blok = repo.get_event(g["eventId"])
    assert (blok.title, blok.all_day, blok.rrule) == ("rapor yaz", False, None)


def test_metinle_gun_planli_gorev_blok_olusturmaz(sunucu):
    temel, repo = sunucu

    durum, yanit = _post(temel, {"text": "görev: market yarın"})

    assert durum == 201 and yanit["task"]["plan"] == "gun" and yanit["task"]["eventId"] is None
    assert repo.list_events() == []


def test_metinle_plansiz_gorev(sunucu):
    temel, _ = sunucu

    _, yanit = _post(temel, {"text": "görev: rapor yaz"})

    assert (yanit["task"]["plan"], yanit["parsed"]["matched"]) == ("yok", "")


def test_metinle_tekrarli_gorev_kodlu_hata(sunucu):
    temel, repo = sunucu

    durum, yanit = _post(temel, {"text": "görev: spor her salı 18:00"})

    assert (durum, yanit["error_code"]) == (400, "gorev_tekrarlanamaz")
    assert repo.list_tasks() == []


def test_metinle_basliksiz_gorev_baslik_bos_kodu(sunucu):
    temel, repo = sunucu

    durum, yanit = _post(temel, {"text": "görev: yarın 14:00"})

    assert (durum, yanit["error_code"]) == (400, "baslik_bos")
    assert repo.list_tasks() == []


def test_bos_metin_metin_bos_kodu(sunucu):
    temel, _ = sunucu

    durum, yanit = _post(temel, {"text": "   "})

    assert (durum, yanit["error_code"]) == (400, "metin_bos")


def test_acik_govde_ve_metin_birlikte_acik_govde_kazanir(sunucu):
    """`title` verilmişse `text` yok sayılır: iki biçim karışmasın (AGENTS 44'ün görev karşılığı)."""
    temel, _ = sunucu

    _, yanit = _post(temel, {"title": "Açık başlık", "text": "görev: başka şey yarın"})

    assert (yanit["task"]["title"], yanit["task"]["plan"]) == ("Açık başlık", "yok")
    assert "parsed" not in yanit


def _yarin():
    """Sunucunun 'yarın'ı (İstanbul); testin çalıştığı saatten bağımsız."""
    return (to_local(datetime.now(UTC), IST).date() + timedelta(days=1)).isoformat()
