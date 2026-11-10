"""Kod incelemesi bulguları (7, 8, 9): sunucu, otomatik başlatma, hatırlatıcı sınırı."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request

import pytest

from store import Repo
from store.repo import MAKS_HATIRLATICI
from tests.helpers import IST, ist, make_event
from ui import otomatik
from ui.server import make_server


@pytest.fixture
def repo():
    with Repo.open(":memory:", check_same_thread=False) as r:
        r.add_calendar("Kişisel", "#3b82f6")
        yield r


@pytest.fixture
def port(repo):
    httpd = make_server(repo, IST, host="127.0.0.1", port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _istek(port: int, yontem: str, yol: str, govde: dict | None = None) -> tuple[int, dict]:
    """(durum, JSON gövde); yanıtsız bağlantı kopması istisna olarak yükselir."""
    veri = json.dumps(govde).encode("utf-8") if govde is not None else None
    istek = urllib.request.Request(
        f"http://127.0.0.1:{port}{yol}", method=yontem, data=veri,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(istek, timeout=10) as yanit:
            return yanit.status, json.loads(yanit.read())
    except urllib.error.HTTPError as hata:
        return hata.code, json.loads(hata.read())


def _etkinlik(repo: Repo):
    takvim_id = repo.list_calendars()[0].id
    return repo.add_event(
        make_event(ist(2026, 5, 5, 9, 0), ist(2026, 5, 5, 10, 0), event_id=None,
                   uid="inc-1", title="x", calendar_id=takvim_id)
    )


# ------------------------------------------------------------ Bulgu 7


def test_repo_devasa_hatirlatici_reddeder(repo):
    e = _etkinlik(repo)
    with pytest.raises(ValueError):
        repo.add_reminder(e.id, MAKS_HATIRLATICI + 1)
    assert repo.add_reminder(e.id, MAKS_HATIRLATICI).minutes_before == MAKS_HATIRLATICI


def test_http_devasa_hatirlatici_400(port, repo):
    e = _etkinlik(repo)
    durum, yanit = _istek(port, "POST", f"/api/events/{e.id}/reminders",
                          {"minutesBefore": 5_000_000_000})
    assert durum == 400
    assert yanit["error_code"] == "hatirlatici_aralik_disi"
    assert repo.list_reminders(e.id) == []


def test_http_gorev_devasa_hatirlatici_400_ve_gorev_kalmaz(port, repo):
    durum, yanit = _istek(port, "POST", "/api/tasks",
                          {"title": "x", "plan": "saat", "date": "2026-10-01", "minutes": 600,
                           "reminderMinutes": 10**20})
    assert (durum, yanit["error_code"]) == (400, "hatirlatici_aralik_disi")
    assert repo.list_tasks() == []


# ------------------------------------------------------------ Bulgu 8


def test_olmayan_takvime_etkinlik_404(port):
    durum, yanit = _istek(port, "POST", "/api/events",
                          {"text": "yarın 10:00 x", "calendarId": 999})
    assert (durum, yanit["error_code"]) == (404, "takvim_bulunamadi")


def test_olmayan_takvime_acik_etkinlik_404(port):
    durum, _ = _istek(port, "POST", "/api/events",
                      {"title": "x", "date": "2026-09-24", "minutes": 600, "calendarId": 999})
    assert durum == 404


@pytest.mark.parametrize("ay", ["week", "month", "day"])
def test_asiri_tarih_gorunumu_400(port, ay):
    for tarih in ("9999-12-31", "0001-01-01"):
        durum, _ = _istek(port, "GET", f"/api/{ay}?date={tarih}")
        assert durum == 400


def test_cakisma_asiri_bitis_400(port):
    durum, _ = _istek(port, "GET", "/api/conflicts?date=2026-05-05&start=600&end=99999999999999")
    assert durum == 400


def test_post_tip_hatalari_400(port, repo):
    e = _etkinlik(repo)
    assert _istek(port, "POST", "/api/occurrences/cancel", {"eventId": None})[0] == 400
    assert _istek(port, "POST", "/api/calendars", {"name": 5, "color": "#112233"})[0] == 400
    assert _istek(port, "PATCH", f"/api/events/{e.id}", {"title": 5})[0] == 400


def test_delete_devasa_id_400(port):
    durum, _ = _istek(port, "DELETE", "/api/events/99999999999999999999")
    assert durum in (400, 404)
    assert _istek(port, "DELETE", "/api/reminders/99999999999999999999")[0] in (400, 404)


# ------------------------------------------------------------ Bulgu 9


def test_kurkomutu_tek_tirnagi_kacirir():
    komut = otomatik._kurKomutu(
        r"C:\Users\O'Neil\pythonw.exe", "-m remind --db \"C:\\O'Neil\\t.db\"",
        r"C:\O'Neil", r"C:\Users\O'Neil\Takvim Hatirlatici.lnk",
    )
    assert "O''Neil" in komut
    assert "O'Neil" not in komut.replace("O''Neil", "")


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell/WScript.Shell yalnız Windows'ta")
def test_apostroflu_klasore_kisayol_kurulur(tmp_path):
    klasor = tmp_path / "O'Neil"
    assert otomatik.kur(klasor) is True
    assert otomatik.kurulu_mu(klasor) is True


def test_gorev_guncellemede_devasa_hatirlatici_basligi_degistirmez(port, repo):
    """PATCH'te hepsi yazmadan ÖNCE doğrulanır (AGENTS 70): yarım değişiklik kalmasın."""
    _, yanit = _istek(port, "POST", "/api/tasks",
                  {"title": "Eski", "plan": "saat", "date": "2026-10-01", "minutes": 600})
    g = yanit["task"]
    durum, yanit = _istek(port, "PATCH", f"/api/tasks/{g['id']}",
                          {"title": "Yeni", "reminderMinutes": 5_000_000_000})
    assert (durum, yanit["error_code"]) == (400, "hatirlatici_aralik_disi")
    assert repo.get_task(g["id"]).title == "Eski"
