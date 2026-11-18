"""Tüm gün etkinlikte store'daki sabit süre hesapları DST gününde doğru mu,
ve ağ kipinde aynı-köken Origin kabulü (AGENTS 13, 40, 65)."""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from core import UTC, Override
from store import Repo
from tests.helpers import make_event
from ui.server import make_server

NY = "America/New_York"
_TZ = ZoneInfo(NY)


def _yerel(*a) -> datetime:
    return datetime(*a, tzinfo=_TZ).astimezone(UTC)


@pytest.fixture
def repo():
    with Repo.open(":memory:", check_same_thread=False) as r:
        r.add_calendar("Kişisel", "#3b82f6")
        yield r


def _tum_gun(repo, **kw):
    # 2026-03-07 (24 saat) -> 8 Mart'ta New York ileri saate geçiyor (23 saat)
    return repo.add_event(
        make_event(
            _yerel(2026, 3, 7), _yerel(2026, 3, 8), tzid=NY, all_day=True,
            event_id=None, uid="tg-1", calendar_id=repo.list_calendars()[0].id, **kw,
        )
    )


def test_override_tasima_dst_gununde_bitisi_gece_yarisi_tutar(repo):
    ev = _tum_gun(repo)
    ov = repo.put_override(
        Override(event_id=ev.id, original_start_utc=ev.start_utc,
                 new_start_utc=_yerel(2026, 3, 8))
    )
    assert ov.new_end_utc == _yerel(2026, 3, 9)  # +24 saat 01:00 verirdi


def test_task_slots_bitissiz_override_dst_dogru(repo):
    ev = _tum_gun(repo)
    repo.conn.execute(
        "INSERT INTO event_overrides (event_id, original_start_utc, cancelled, new_start_utc)"
        " VALUES (?, ?, 0, ?)",
        (ev.id, ev.start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
         _yerel(2026, 3, 8).strftime("%Y-%m-%dT%H:%M:%SZ")),
    )
    assert repo.task_slots([ev.id])[ev.id][1] == _yerel(2026, 3, 9)


def test_seri_bolme_yeni_seri_dst_gununde_dogru_biter(repo):
    ev = _tum_gun(repo, rrule="FREQ=DAILY;COUNT=5")
    sonuc = repo.split_series(ev.id, _yerel(2026, 3, 8))
    yeni = repo.get_event(sonuc["yeni_id"])
    assert yeni.start_utc == _yerel(2026, 3, 8)
    assert yeni.end_utc == _yerel(2026, 3, 9)


# ---- ağ kipi kaynak denetimi


def _sunucu(repo, host):
    httpd = make_server(repo, "Europe/Istanbul", host=host, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _post(port, origin, host_basligi=None):
    basliklar = {"Content-Type": "application/json", "Origin": origin}
    if host_basligi:
        basliklar["Host"] = host_basligi
    istek = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/events", method="POST",
        data=b'{"text": "ag testi yarin 10:00"}', headers=basliklar,
    )
    try:
        with urllib.request.urlopen(istek, timeout=10) as y:
            return y.status
    except urllib.error.HTTPError as h:
        h.close()
        return h.code


def test_ag_kipinde_ayni_koken_gecer_farkli_origin_403(repo):
    httpd = _sunucu(repo, "0.0.0.0")
    try:
        port = httpd.server_address[1]
        ad = f"192.168.1.20:{port}"
        assert _post(port, f"http://{ad}", ad) != 403
        assert _post(port, "http://kotu.example", ad) == 403
        assert _post(port, f"http://{ad}") == 403  # Host bizim ağ adresimiz değil
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_loopback_kipinde_ayni_koken_kurali_isletilmez(repo):
    httpd = _sunucu(repo, "127.0.0.1")
    try:
        port = httpd.server_address[1]
        assert _post(port, f"http://127.0.0.1:{port}") != 403
        # Host == Origin olsa bile loopback listesinde değilse reddedilir
        assert _post(port, "http://kotu.example", "kotu.example") == 403
    finally:
        httpd.shutdown()
        httpd.server_close()
