"""Arama görev durum filtresi (`Repo.search_tasks(durum=)`, `/api/search?gorev=`).

Filtre yalnızca GÖREV sonuçlarını etkiler: "hepsi" (varsayılan), "acik"
(tamamlanmamış), "biten" (tamamlanmış). Etkinlik sonuçları değişmez.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
from datetime import UTC, datetime

import pytest

from core import Task
from store import Repo, new_uid
from tests.helpers import IST
from ui.server import make_server


@pytest.fixture
def repo():
    with Repo.open(":memory:", check_same_thread=False) as r:
        yield r


@pytest.fixture
def sunucu(repo):
    httpd = make_server(repo, IST, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _ekle(repo, baslik, *, bitti=False):
    done_at = datetime(2026, 10, 12, 9, 0, tzinfo=UTC) if bitti else None
    return repo.add_task(Task(id=None, uid=new_uid(), title=baslik, done_at=done_at))


def _hazirla(repo):
    _ekle(repo, "Rapor yaz")
    _ekle(repo, "Rapor gönder", bitti=True)
    _ekle(repo, "Market")


def _ara(temel, sorgu, gorev=None):
    yol = "/api/search?q=" + urllib.parse.quote(sorgu)
    if gorev is not None:
        yol += "&gorev=" + urllib.parse.quote(gorev)
    with urllib.request.urlopen(temel + yol) as yanit:
        return json.loads(yanit.read().decode("utf-8"))


def _basliklar(sonuc):
    return sorted(g["title"] for g in sonuc["tasks"])


# --- Repo.search_tasks -------------------------------------------------------


def test_varsayilan_hepsi(repo):
    _hazirla(repo)
    assert sorted(g.title for g in repo.search_tasks("rapor")) == ["Rapor gönder", "Rapor yaz"]


def test_durum_hepsi_acikca(repo):
    _hazirla(repo)
    bulunan = repo.search_tasks("rapor", durum="hepsi")
    assert sorted(g.title for g in bulunan) == ["Rapor gönder", "Rapor yaz"]


def test_durum_acik_bitenleri_ayiklar(repo):
    _hazirla(repo)
    assert [g.title for g in repo.search_tasks("rapor", durum="acik")] == ["Rapor yaz"]


def test_durum_biten_acik_olanlari_ayiklar(repo):
    _hazirla(repo)
    assert [g.title for g in repo.search_tasks("rapor", durum="biten")] == ["Rapor gönder"]


def test_gecersiz_durum_hata_verir(repo):
    _hazirla(repo)
    with pytest.raises(ValueError):
        repo.search_tasks("rapor", durum="yarim")


def test_limit_filtreden_sonra_uygulanir(repo):
    # Önce biten 3 görev, sonra 1 açık: limit=1 + durum="acik" açık olanı
    # bulmalı (filtre limitten ÖNCE uygulanmazsa ilk 1 sonuç bitendir, boş döner).
    for i in range(3):
        _ekle(repo, f"Ödev {i}", bitti=True)
    _ekle(repo, "Ödev son")
    assert [g.title for g in repo.search_tasks("ödev", limit=1, durum="acik")] == ["Ödev son"]


# --- /api/search?gorev= ------------------------------------------------------


def test_api_parametresiz_hepsi(repo, sunucu):
    _hazirla(repo)
    assert _basliklar(_ara(sunucu, "rapor")) == ["Rapor gönder", "Rapor yaz"]


def test_api_acik(repo, sunucu):
    _hazirla(repo)
    assert _basliklar(_ara(sunucu, "rapor", "acik")) == ["Rapor yaz"]


def test_api_biten(repo, sunucu):
    _hazirla(repo)
    assert _basliklar(_ara(sunucu, "rapor", "biten")) == ["Rapor gönder"]


def test_api_bilinmeyen_deger_hepsine_duser(repo, sunucu):
    _hazirla(repo)
    assert _basliklar(_ara(sunucu, "rapor", "saçma")) == ["Rapor gönder", "Rapor yaz"]
