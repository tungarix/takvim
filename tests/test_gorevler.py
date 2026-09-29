"""Görevler: model ve depo (yapılacaklar listesi).

Görev takvim etkinliği DEĞİL; ne zaman yapılacağı üç hâlden biri (plansız /
gün / saat). Saat planlıysa saati bağlı bir etkinlik (zaman bloğu) taşır.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from core import Task
from store import Repo, new_uid
from tests.helpers import IST, ist, make_event


@pytest.fixture
def repo():
    """Her test için bellekte taze, migrate edilmiş bir DB."""
    with Repo.open(":memory:") as r:
        yield r


@pytest.fixture
def kisisel(repo):
    """Blokların yazılacağı takvim."""
    return repo.add_calendar("Kişisel", "#3366cc")


def _gorev(**kw) -> Task:
    """Kaydedilmeye hazır (id'siz) görev."""
    kw.setdefault("id", None)
    kw.setdefault("uid", new_uid())
    kw.setdefault("title", "Rapor yaz")
    return Task(**kw)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def test_baslik_kirpilir_ve_bos_olamaz():
    assert _gorev(title="  rapor  ").title == "rapor"
    with pytest.raises(ValueError, match="başlığı boş"):
        _gorev(title="   ")


def test_bos_not_none_olur():
    assert _gorev(notes="  ").notes is None
    assert _gorev(notes=" taslak ").notes == "taslak"


def test_gun_ve_saat_ayni_anda_olamaz():
    """İki plan birden dolu olursa hangisinin geçerli olduğu belirsiz kalırdı."""
    with pytest.raises(ValueError, match="hem gün hem saat"):
        _gorev(plan_day=date(2026, 10, 1), event_id=7)


def test_plan_gunu_datetime_olamaz():
    """datetime, date'in alt sınıfı: gün bekleyen yere an verilirse saat sessizce düşerdi."""
    with pytest.raises(ValueError, match="date"):
        _gorev(plan_day=datetime(2026, 10, 1, 14, 0))


def test_done_at_utcye_normalize_edilir():
    t = _gorev(done_at=ist(2026, 10, 1, 12, 0))
    assert t.done and t.done_at is not None and t.done_at.utcoffset() == timedelta(0)
    assert _gorev().done is False


@pytest.mark.parametrize(
    ("kw", "beklenen"),
    [({}, "yok"), ({"plan_day": date(2026, 10, 1)}, "gun"), ({"event_id": 3}, "saat")],
)
def test_plan_durumu(kw, beklenen):
    assert _gorev(**kw).plan == beklenen


# ---------------------------------------------------------------------------
# Kayıt
# ---------------------------------------------------------------------------

def test_gorev_kaydedilir_ve_okunur(repo):
    yeni = repo.add_task(_gorev(notes="taslak", plan_day=date(2026, 10, 1)))

    assert yeni.id is not None
    assert repo.get_task(yeni.id) == yeni
    assert repo.get_task_by_uid(yeni.uid) == yeni
    assert repo.get_task(999) is None


def test_ayni_uid_ikinci_kez_eklenemez(repo):
    """İçe aktarma aynı VTODO'yu ikinci kez eklemesin diye veritabanı düzeyinde."""
    ilk = repo.add_task(_gorev())
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_task(_gorev(uid=ilk.uid))


def test_liste_eklenme_sirasinda(repo):
    a = repo.add_task(_gorev(title="a"))
    b = repo.add_task(_gorev(title="b"))
    assert [t.id for t in repo.list_tasks()] == [a.id, b.id]


def test_olmayan_gorev_uzerinde_islem_hata_verir(repo):
    with pytest.raises(LookupError):
        repo.set_task_done(42, True)
    with pytest.raises(LookupError):
        repo.plan_task_day(42, date(2026, 10, 1))
    with pytest.raises(LookupError):
        repo.delete_task(42)
    with pytest.raises(LookupError):
        repo.update_task(_gorev(id=42))


def test_baslik_ve_not_guncellenir_plan_dokunulmaz(repo):
    """update_task yalnızca başlık/not yazar: bayat bir nesne planı geri almasın."""
    t = repo.add_task(_gorev(plan_day=date(2026, 10, 1)))
    bayat = _gorev(id=t.id, uid=t.uid, title="Yeni ad", notes="not")  # planı yok

    repo.update_task(bayat)

    son = repo.get_task(t.id)
    assert (son.title, son.notes) == ("Yeni ad", "not")
    assert son.plan_day == date(2026, 10, 1)


# ---------------------------------------------------------------------------
# Tamamlanma
# ---------------------------------------------------------------------------

def test_tamamlanir_ve_geri_acilir(repo):
    t = repo.add_task(_gorev())

    kapali = repo.set_task_done(t.id, True)
    assert kapali.done

    acik = repo.set_task_done(t.id, False)
    assert not acik.done and acik.done_at is None


def test_tamamlanma_blogu_yerinde_birakir(repo, kisisel):
    """Bitirilen görevin bloğu ızgarada durur (soluk çizilir); silinmez."""
    t = repo.add_task(_gorev())
    t = repo.plan_task_slot(t.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15), kisisel.id, IST)

    kapali = repo.set_task_done(t.id, True)

    assert kapali.event_id == t.event_id
    assert repo.get_event(t.event_id) is not None


# ---------------------------------------------------------------------------
# Plan: gün / saat / yok
# ---------------------------------------------------------------------------

def test_gun_planinda_etkinlik_olusmaz(repo):
    """Saatsiz görev ızgarada (tüm gün şeridi dahil) HİÇ görünmemeli."""
    t = repo.add_task(_gorev())

    repo.plan_task_day(t.id, date(2026, 10, 1))

    assert repo.list_events() == []
    assert repo.get_task(t.id).plan == "gun"


def test_saat_plani_bagli_blok_olusturur(repo, kisisel):
    t = repo.add_task(_gorev(title="Rapor yaz", notes="ilk taslak"))

    t = repo.plan_task_slot(t.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15, 30), kisisel.id, IST)

    blok = repo.get_event(t.event_id)
    assert (blok.title, blok.description) == ("Rapor yaz", "ilk taslak")
    assert (blok.start_utc, blok.end_utc) == (ist(2026, 10, 1, 14), ist(2026, 10, 1, 15, 30))
    assert (blok.calendar_id, blok.tzid, blok.all_day, blok.rrule) == (kisisel.id, IST, False, None)
    assert t.plan == "saat" and t.plan_day is None


def test_saat_plani_tekrar_verilince_mevcut_blok_tasinir(repo, kisisel):
    """Görevi ikinci kez ızgaraya bırakmak ikinci blok açmamalı, mevcut olanı taşımalı."""
    t = repo.add_task(_gorev())
    ilk = repo.plan_task_slot(t.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15), kisisel.id, IST)

    ikinci = repo.plan_task_slot(t.id, ist(2026, 10, 2, 9), ist(2026, 10, 2, 10), kisisel.id, IST)

    assert ikinci.event_id == ilk.event_id
    assert len(repo.list_events()) == 1
    assert repo.get_event(ikinci.event_id).start_utc == ist(2026, 10, 2, 9)


def test_saat_planindan_gun_planina_gecince_blok_silinir(repo, kisisel):
    t = repo.add_task(_gorev())
    t = repo.plan_task_slot(t.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15), kisisel.id, IST)

    t = repo.plan_task_day(t.id, date(2026, 10, 3))

    assert repo.list_events() == []
    assert (t.plan, t.plan_day, t.event_id) == ("gun", date(2026, 10, 3), None)


def test_plan_kaldirilinca_blok_silinir(repo, kisisel):
    t = repo.add_task(_gorev())
    t = repo.plan_task_slot(t.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15), kisisel.id, IST)

    t = repo.clear_task_plan(t.id)

    assert repo.list_events() == []
    assert t.plan == "yok"


def test_gun_planindan_saat_planina_gecince_gun_temizlenir(repo, kisisel):
    """İkisi birden dolu kalırsa CHECK kısıtı patlar; plan tek hâlde olmalı."""
    t = repo.add_task(_gorev(plan_day=date(2026, 10, 1)))

    t = repo.plan_task_slot(t.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15), kisisel.id, IST)

    assert (t.plan, t.plan_day) == ("saat", None)


def test_gecersiz_saat_araligi_hicbir_sey_yazmaz(repo, kisisel):
    """Bitiş başlangıçtan önceyse görev plansız kalır, yarım blok bırakılmaz."""
    t = repo.add_task(_gorev())

    with pytest.raises(ValueError):
        repo.plan_task_slot(t.id, ist(2026, 10, 1, 15), ist(2026, 10, 1, 14), kisisel.id, IST)

    assert repo.list_events() == [] and repo.get_task(t.id).plan == "yok"


def test_veritabani_gun_ve_saati_birlikte_reddeder(repo, kisisel):
    """Model zaten reddediyor; ham SQL'i de kısıt (CHECK) durdurmalı, ikinci savunma hattı."""
    blok = repo.add_event(make_event(ist(2026, 10, 1, 9), ist(2026, 10, 1, 10), event_id=None,
                                     uid=new_uid(), calendar_id=kisisel.id))
    with pytest.raises(sqlite3.IntegrityError):
        repo.conn.execute(
            "INSERT INTO tasks (uid, title, plan_day, event_id, created_at, updated_at)"
            " VALUES ('x', 'x', '2026-10-01', ?, 'z', 'z')", (blok.id,))


# ---------------------------------------------------------------------------
# Silme
# ---------------------------------------------------------------------------

def test_gorevi_silmek_blogunu_da_siler(repo, kisisel):
    t = repo.add_task(_gorev())
    t = repo.plan_task_slot(t.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15), kisisel.id, IST)

    repo.delete_task(t.id)

    assert repo.list_tasks() == [] and repo.list_events() == []


def test_blogu_silmek_gorevi_silmez_plansiza_doner(repo, kisisel):
    """Izgaradan blok silinince yapılacak iş kaybolmamalı."""
    t = repo.add_task(_gorev())
    t = repo.plan_task_slot(t.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15), kisisel.id, IST)

    repo.delete_event(t.event_id)

    kalan = repo.get_task(t.id)
    assert kalan is not None and kalan.plan == "yok"


def test_takvim_silinince_gorev_kalir_blogu_gider(repo, kisisel):
    t = repo.add_task(_gorev())
    t = repo.plan_task_slot(t.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15), kisisel.id, IST)

    repo.delete_calendar(kisisel.id)

    assert repo.get_task(t.id).plan == "yok"


# ---------------------------------------------------------------------------
# Görev <-> blok eşitliği
# ---------------------------------------------------------------------------

def test_gorev_adi_degisince_blok_adi_da_degisir(repo, kisisel):
    t = repo.add_task(_gorev(title="Eski"))
    t = repo.plan_task_slot(t.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15), kisisel.id, IST)

    repo.update_task(_gorev(id=t.id, uid=t.uid, title="Yeni", notes="ayrıntı"))

    blok = repo.get_event(t.event_id)
    assert (blok.title, blok.description) == ("Yeni", "ayrıntı")


def test_blok_adi_degisince_gorev_adi_da_degisir(repo, kisisel):
    """Etkinlik paneli bloğu düzenleyebiliyor; listedeki ad ızgaradakinden ayrışmamalı."""
    t = repo.add_task(_gorev(title="Eski"))
    t = repo.plan_task_slot(t.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15), kisisel.id, IST)
    blok = repo.get_event(t.event_id)

    repo.update_event(replace(blok, title="Panelden yeni", description="  panel notu "))

    son = repo.get_task(t.id)
    assert (son.title, son.notes) == ("Panelden yeni", "panel notu")


def test_bagli_olmayan_etkinlik_guncellemesi_gorevlere_dokunmaz(repo, kisisel):
    t = repo.add_task(_gorev(title="Görev", plan_day=date(2026, 10, 1)))
    baska = repo.add_event(make_event(ist(2026, 10, 1, 9), ist(2026, 10, 1, 10),
                                      event_id=None, uid=new_uid(), calendar_id=kisisel.id,
                                      title="Toplantı"))

    repo.update_event(replace(baska, title="Toplantı 2"))

    assert repo.get_task(t.id).title == "Görev"


def test_blok_tekrarli_yapilamaz(repo, kisisel):
    """Görev bloğu bir seri olursa 'tamamlandı' hangi örnek için olurdu."""
    t = repo.add_task(_gorev())
    t = repo.plan_task_slot(t.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15), kisisel.id, IST)
    blok = repo.get_event(t.event_id)

    with pytest.raises(ValueError, match="tekrarlı"):
        repo.update_event(replace(blok, rrule="FREQ=DAILY"))


def test_blok_tum_gun_yapilamaz(repo, kisisel):
    """Tüm gün şeridine düşen görev bloğu, 'saatsiz görev şeritte görünmesin' kararını çiğnerdi."""
    t = repo.add_task(_gorev())
    t = repo.plan_task_slot(t.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15), kisisel.id, IST)
    blok = repo.get_event(t.event_id)

    with pytest.raises(ValueError, match="tüm gün"):
        repo.update_event(replace(blok, start_utc=ist(2026, 10, 1), end_utc=ist(2026, 10, 2),
                                  all_day=True))


def test_tekrarli_etkinlige_gorev_baglanamaz(repo, kisisel):
    seri = repo.add_event(make_event(ist(2026, 10, 1, 9), ist(2026, 10, 1, 10), event_id=None,
                                     uid=new_uid(), calendar_id=kisisel.id, rrule="FREQ=DAILY"))
    with pytest.raises(ValueError, match="tekrarlı"):
        repo.add_task(_gorev(event_id=seri.id))


def test_bir_bloga_tek_gorev(repo, kisisel):
    """Aynı bloğa ikinci görev bağlanırsa 'tamamlandı' hangisi için olurdu."""
    a = repo.add_task(_gorev())
    a = repo.plan_task_slot(a.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15), kisisel.id, IST)

    with pytest.raises(sqlite3.IntegrityError):
        repo.add_task(_gorev(event_id=a.event_id))


def test_bloklara_bagli_gorevler_tek_sorguda(repo, kisisel):
    a = repo.add_task(_gorev(title="a"))
    a = repo.plan_task_slot(a.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15), kisisel.id, IST)
    repo.add_task(_gorev(title="b", plan_day=date(2026, 10, 1)))

    esle = repo.tasks_by_event([a.event_id, 9999])

    assert list(esle) == [a.event_id] and esle[a.event_id].title == "a"
    assert repo.tasks_by_event([]) == {}


def test_get_events_toplu(repo, kisisel):
    e1 = repo.add_event(make_event(ist(2026, 10, 1, 9), ist(2026, 10, 1, 10), event_id=None,
                                   uid=new_uid(), calendar_id=kisisel.id))
    assert list(repo.get_events([e1.id, 9999])) == [e1.id]
    assert repo.get_events([]) == {}
