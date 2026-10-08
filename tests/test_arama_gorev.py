"""Arama görevleri de bulur (`Repo.search_tasks`, `/api/search` → `tasks`).

v1.5.0'da görevler geldi ama arama yalnızca etkinliklere bakıyordu: listede
olan bir görev aramada "Sonuç yok" diyordu.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
from datetime import date

import pytest

from store import Repo
from tests.helpers import IST
from ui.server import make_server

GUN = date(2026, 10, 12).isoformat()


@pytest.fixture
def repo():
    with Repo.open(":memory:", check_same_thread=False) as r:
        yield r


@pytest.fixture
def sunucu(repo):
    repo.add_calendar("Ders", "#e0524a")
    httpd = make_server(repo, IST, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _istek(temel, yontem, yol, govde=None):
    veri = json.dumps(govde).encode("utf-8") if govde is not None else None
    req = urllib.request.Request(
        temel + yol, method=yontem, data=veri,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req) as yanit:
        return json.loads(yanit.read().decode("utf-8"))


def _gorev(temel, **govde):
    return _istek(temel, "POST", "/api/tasks", govde)["task"]


def _ara(temel, sorgu):
    return _istek(temel, "GET", "/api/search?q=" + urllib.parse.quote(sorgu))


# --- Repo.search_tasks -------------------------------------------------------


def _ekle(repo, baslik, notlar=""):
    from core import Task
    from store import new_uid

    return repo.add_task(Task(id=None, uid=new_uid(), title=baslik, notes=notlar))


def test_baslikta_gecen_gorev_bulunur(repo):
    _ekle(repo, "Rapor yaz")
    _ekle(repo, "Market")
    assert [g.title for g in repo.search_tasks("rapor")] == ["Rapor yaz"]


def test_notta_gecen_gorev_bulunur(repo):
    _ekle(repo, "Ödev", notlar="istatistik bölüm 3")
    assert [g.title for g in repo.search_tasks("istatistik")] == ["Ödev"]


def test_turkce_buyuk_harf_ve_sapka_onemsenmez(repo):
    """AGENTS 20: arama niyet eşleştirir, dil kuralı uygulamaz."""
    _ekle(repo, "Algoritma ödevi")
    assert len(repo.search_tasks("ALGORITMA ODEVI")) == 1


def test_tamamlanmis_gorev_de_bulunur(repo):
    gorev = _ekle(repo, "Bitmiş rapor")
    repo.set_task_done(gorev.id, True)
    assert [g.title for g in repo.search_tasks("rapor")] == ["Bitmiş rapor"]


def test_bos_sorgu_hicbir_sey_dondurmez(repo):
    _ekle(repo, "Rapor yaz")
    assert repo.search_tasks("   ") == []


def test_sinir_asilmaz(repo):
    for i in range(5):
        _ekle(repo, f"Rapor {i}")
    assert len(repo.search_tasks("rapor", limit=3)) == 3


# --- /api/search -------------------------------------------------------------


def test_api_gorevleri_ayri_alanda_dondurur(sunucu):
    _gorev(sunucu, title="Rapor yaz", plan="gun", date=GUN)
    yanit = _ara(sunucu, "rapor")
    assert [g["title"] for g in yanit["tasks"]] == ["Rapor yaz"]
    assert yanit["tasks"][0]["plan"] == "gun" and yanit["tasks"][0]["day"] == GUN
    assert yanit["results"] == []


def test_api_eski_alanlar_duruyor(sunucu):
    """Eski sözleşme: `query` ve `results` (etkinlikler) aynen."""
    _istek(sunucu, "POST", "/api/events", {"text": "yarın 10:00 rapor toplantısı"})
    yanit = _ara(sunucu, "rapor")
    assert yanit["query"] == "rapor"
    assert [e["title"] for e in yanit["results"]] == ["rapor toplantısı"]


def test_gorev_blogu_etkinlik_olarak_ikinci_kez_listelenmez(sunucu):
    """Saat planlı görevin bloğu da bir etkinlik ve adı aynı (AGENTS 69)."""
    _gorev(sunucu, title="Sunum hazırla", plan="saat", date=GUN, minutes=600, endMinutes=660)
    yanit = _ara(sunucu, "sunum")
    assert yanit["results"] == []
    assert [g["title"] for g in yanit["tasks"]] == ["Sunum hazırla"]
    assert yanit["tasks"][0]["plan"] == "saat"
