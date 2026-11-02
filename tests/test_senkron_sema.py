"""006 migration'ı: takvim uid/updated_at, mezar taşı tablosu ve tetikleyiciler.

Tetikleyiciler Repo koduna dokunmadan TÜM silme yollarını yakalıyor (takvimin
CASCADE'i, görev silme, seri silme/geri alma); burada her yol ayrı ayrı sınanıyor.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta

import pytest

from core import UTC, Event, Task
from store import Repo, connect, migrate
from store.migrator import MIGRATIONS_DIR
from tests.helpers import IST, ist

ESKI = "2020-01-01T00:00:00Z"


@pytest.fixture
def repo():
    """Bellekte taze DB (gerçek %LOCALAPPDATA% veritabanına ASLA dokunulmaz)."""
    with Repo.open(":memory:") as r:
        yield r


@pytest.fixture
def takvim(repo):
    return repo.add_calendar("Kişisel", "#3b82f6")


def _etkinlik(repo, takvim, uid="e1@x", **kw) -> Event:
    return repo.add_event(Event(
        id=None, uid=uid, calendar_id=takvim.id, title="Toplantı",
        start_utc=ist(2026, 11, 3, 10), end_utc=ist(2026, 11, 3, 11), tzid=IST, **kw,
    ))


def _mezarlar(repo) -> dict:
    return {
        (r["kind"], r["uid"]): r["deleted_at"]
        for r in repo.conn.execute("SELECT * FROM silinenler")
    }


def _guncelleme(repo, uid) -> str:
    return repo.conn.execute("SELECT updated_at FROM events WHERE uid = ?", (uid,)).fetchone()[0]


def _eskit(repo, uid) -> None:
    """Etkinliğin updated_at'ini eskitir; tetikleyici onu 'şimdi'ye çekerse fark edilir."""
    repo.conn.execute("UPDATE events SET updated_at = ? WHERE uid = ?", (ESKI, uid))


def _simdiden_yeni(zaman: str) -> bool:
    return datetime.strptime(zaman, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) > (
        datetime.now(UTC) - timedelta(minutes=1)
    )


# ---------------------------------------------------------------------------
# Takvim uid / updated_at
# ---------------------------------------------------------------------------

def test_takvim_uid_ve_updated_at_atanir(repo):
    takvim = repo.add_calendar("Ders", "#e0524a")

    assert takvim.uid
    satir = repo.conn.execute("SELECT uid, updated_at FROM calendars WHERE id = ?", (takvim.id,)).fetchone()
    assert satir["uid"] == takvim.uid
    assert _simdiden_yeni(satir["updated_at"])
    assert repo.get_calendar(takvim.id).uid == takvim.uid


def test_takvim_uidleri_benzersiz(repo):
    assert repo.add_calendar("A", "#000000").uid != repo.add_calendar("A", "#000000").uid


def test_dogrudan_insert_edilen_takvime_uid_verilir(repo):
    """Repo'yu atlayan INSERT (yedek testleri böyle yapıyor) uid'siz kalmamalı."""
    repo.conn.execute(
        "INSERT INTO calendars (name, color, visible, created_at) "
        "VALUES ('Ham', '#000000', 1, '2026-01-02T03:04:05Z')"
    )
    satir = repo.conn.execute("SELECT uid, updated_at FROM calendars").fetchone()
    assert satir["uid"] and len(satir["uid"]) == 32
    assert satir["updated_at"] == "2026-01-02T03:04:05Z"


def test_takvim_guncelleme_updated_ati_yeniler(repo, takvim):
    repo.conn.execute("UPDATE calendars SET updated_at = ?", (ESKI,))

    repo.update_calendar(type(takvim)(id=takvim.id, name="Yeni ad", color="#000000", visible=False))

    assert _simdiden_yeni(repo.conn.execute("SELECT updated_at FROM calendars").fetchone()[0])


def test_migration_mevcut_takvimlere_uid_verir(tmp_path):
    """005'te kurulu DB 006'ya geçince her takvim benzersiz uid alır."""
    eski = tmp_path / "eski"
    eski.mkdir()
    for yol in MIGRATIONS_DIR.glob("00[1-5]_*.sql"):
        shutil.copy(yol, eski)
    conn = connect(":memory:")
    migrate(conn, eski)
    for ad in ("A", "B", "C"):
        conn.execute(
            "INSERT INTO calendars (name, color, visible, created_at) VALUES (?, '#000000', 1, ?)",
            (ad, "2026-01-02T03:04:05Z"),
        )

    migrate(conn)

    satirlar = conn.execute("SELECT uid, updated_at, created_at FROM calendars").fetchall()
    assert len({s["uid"] for s in satirlar}) == 3 and all(s["uid"] for s in satirlar)
    assert all(s["updated_at"] == s["created_at"] for s in satirlar)


# ---------------------------------------------------------------------------
# Mezar taşları
# ---------------------------------------------------------------------------

def test_etkinlik_silme_mezar_tasi_yazar(repo, takvim):
    etkinlik = _etkinlik(repo, takvim)

    repo.delete_event(etkinlik.id)

    assert list(_mezarlar(repo)) == [("event", "e1@x")]
    assert _simdiden_yeni(_mezarlar(repo)[("event", "e1@x")])


def test_gorev_silme_gorev_ve_blok_icin_mezar_tasi_yazar(repo, takvim):
    gorev = repo.add_task(Task(id=None, uid="g1", title="Rapor"))
    gorev = repo.plan_task_slot(gorev.id, ist(2026, 11, 3, 10), ist(2026, 11, 3, 11), takvim.id, IST)
    blok_uid = repo.get_event(gorev.event_id).uid

    repo.delete_task(gorev.id)

    assert set(_mezarlar(repo)) == {("task", "g1"), ("event", blok_uid)}


def test_takvim_silme_cascade_ile_giden_etkinliklerin_mezar_tasi_yazilir(repo, takvim):
    _etkinlik(repo, takvim, "e1@x")
    _etkinlik(repo, takvim, "e2@x")

    repo.delete_calendar(takvim.id)

    assert set(_mezarlar(repo)) == {
        ("calendar", takvim.uid), ("event", "e1@x"), ("event", "e2@x"),
    }


def test_seri_silme_mezar_tasi_yazar(repo, takvim):
    etkinlik = _etkinlik(repo, takvim, rrule="FREQ=WEEKLY")

    repo.snapshot_and_delete(etkinlik.id)

    assert ("event", "e1@x") in _mezarlar(repo)


def test_ayni_uid_yeniden_eklenince_mezar_tasi_silinir(repo, takvim):
    etkinlik = _etkinlik(repo, takvim)
    repo.delete_event(etkinlik.id)
    assert _mezarlar(repo)

    _etkinlik(repo, takvim)

    assert _mezarlar(repo) == {}


def test_geri_alma_mezar_tasini_siler_ve_updated_ati_simdiye_ceker(repo, takvim):
    etkinlik = _etkinlik(repo, takvim, rrule="FREQ=WEEKLY")
    _eskit(repo, "e1@x")
    repo.snapshot_and_delete(etkinlik.id)

    diriltilen = repo.restore_last_deleted()

    assert diriltilen is not None
    assert _mezarlar(repo) == {}, "geri alınan etkinliğin silme kaydı kalmamalı"
    assert _simdiden_yeni(_guncelleme(repo, "e1@x")), "eski updated_at kalırsa diğer cihazdaki silme kazanır"


def test_geri_alma_cocuklu_etkinlikte_de_updated_at_simdi(repo, takvim):
    etkinlik = _etkinlik(repo, takvim, rrule="FREQ=WEEKLY")
    repo.add_reminder(etkinlik.id, 10)
    repo.cancel_occurrence(etkinlik.id, etkinlik.start_utc + timedelta(days=7))
    repo.snapshot_and_delete(etkinlik.id)

    repo.restore_last_deleted()

    assert _simdiden_yeni(_guncelleme(repo, "e1@x"))


# ---------------------------------------------------------------------------
# Etkinliğin updated_at'i: override ve hatırlatıcı etkinliğin parçası
# ---------------------------------------------------------------------------

def _hatirlatici_ekle(repo, e):
    repo.add_reminder(e.id, 10)


def _override_ekle(repo, e):
    repo.cancel_occurrence(e.id, e.start_utc + timedelta(days=7))


def _override_guncelle(repo, e):
    repo.cancel_occurrence(e.id, e.start_utc + timedelta(days=7))
    _eskit(repo, e.uid)
    repo.move_occurrence(e.id, e.start_utc + timedelta(days=7), e.start_utc + timedelta(days=7, hours=1))


def _override_sil(repo, e):
    repo.cancel_occurrence(e.id, e.start_utc + timedelta(days=7))
    _eskit(repo, e.uid)
    repo.delete_override(e.id, e.start_utc + timedelta(days=7))


def _hatirlatici_sil(repo, e):
    hat = repo.add_reminder(e.id, 10)
    _eskit(repo, e.uid)
    repo.delete_reminder(hat.id)


def _hatirlatici_guncelle(repo, e):
    repo.add_reminder(e.id, 10)
    _eskit(repo, e.uid)
    repo.conn.execute("UPDATE reminders SET minutes_before = 30 WHERE event_id = ?", (e.id,))


@pytest.mark.parametrize(
    "islem",
    [
        _hatirlatici_ekle, _override_ekle, _override_guncelle,
        _override_sil, _hatirlatici_sil, _hatirlatici_guncelle,
    ],
)
def test_override_ve_hatirlatici_degisince_etkinlik_updated_ati_yenilenir(repo, takvim, islem):
    etkinlik = _etkinlik(repo, takvim, rrule="FREQ=WEEKLY")
    _eskit(repo, etkinlik.uid)

    islem(repo, etkinlik)

    assert _simdiden_yeni(_guncelleme(repo, etkinlik.uid))


def test_etkinlik_silinirken_cocuk_tetikleyicileri_hata_vermez(repo, takvim):
    """CASCADE ile giden override/hatırlatıcı, zaten giden etkinliğe UPDATE atar: sessiz kalmalı."""
    etkinlik = _etkinlik(repo, takvim, rrule="FREQ=WEEKLY")
    repo.add_reminder(etkinlik.id, 10)
    repo.cancel_occurrence(etkinlik.id, etkinlik.start_utc + timedelta(days=7))

    repo.delete_event(etkinlik.id)

    assert repo.conn.execute("SELECT count(*) FROM event_overrides").fetchone()[0] == 0
    assert repo.conn.execute("SELECT count(*) FROM reminders").fetchone()[0] == 0
