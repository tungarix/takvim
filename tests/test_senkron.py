"""Senkron dosyası: dışa aktarma, içe aktarma ve birleştirme kuralları.

Kurallar `docs/senkron.md`'de. İki "cihaz" iki bellek DB'si; dosya
`durum_uret` ile üretilip `ice_aktar` ile öbürüne gidiyor. Zaman damgaları
saniye hassasiyetli olduğu için çakışma testlerinde `updated_at` SQL ile
kasten sabitleniyor (gerçek saate güvenmek testi kırılgan yapardı).
"""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import date, timedelta

import pytest

import senkron.ice as ice_modulu
from core import UTC, Event, Task
from senkron import SenkronHatasi, cihaz_kimligi, durum_uret, ice_aktar, json_metni
from store import Repo
from tests.helpers import IST, NY, ist

ESKI = "2026-01-01T00:00:00Z"
ORTA = "2026-06-01T00:00:00Z"
YENI = "2026-11-01T00:00:00Z"


@pytest.fixture
def a():
    with Repo.open(":memory:") as r:
        yield r


@pytest.fixture
def b():
    with Repo.open(":memory:") as r:
        yield r


def _dosya(repo, ad="cihaz") -> dict:
    return durum_uret(repo, cihaz_id=ad, cihaz_adi=ad, uygulama="test")


def _gonder(kaynak, hedef):
    """kaynak cihazın dosyasını hedefe içe aktarır; raporu döndürür."""
    return ice_aktar(hedef, json_metni(_dosya(kaynak)))


def _etkinlik(repo, takvim, uid="e1", baslik="Toplantı", **kw) -> Event:
    kw.setdefault("start_utc", ist(2026, 11, 3, 10))
    kw.setdefault("end_utc", ist(2026, 11, 3, 11))
    return repo.add_event(Event(
        id=None, uid=uid, calendar_id=takvim.id, title=baslik, tzid=kw.pop("tzid", IST), **kw,
    ))


def _damga(repo, tablo, uid, zaman):
    repo.conn.execute(f"UPDATE {tablo} SET updated_at = ? WHERE uid = ?", (zaman, uid))


def _mezar_zamani(repo, tur, uid, zaman):
    repo.conn.execute(
        "UPDATE silinenler SET deleted_at = ? WHERE kind = ? AND uid = ?", (zaman, tur, uid)
    )


def _mezarlar(repo) -> dict:
    return {(r["kind"], r["uid"]): r["deleted_at"] for r in repo.conn.execute("SELECT * FROM silinenler")}


def _durum(repo) -> dict:
    """Karşılaştırma için dışa aktarma (dosyayı oluşturan zaman/cihaz hariç)."""
    d = _dosya(repo)
    d.pop("created_at")
    d.pop("device")
    return d


def _ham(repo) -> list:
    """Yerel kimlikler ve sayaçlar dahil TÜM satırlar: 'hiçbir şey değişmedi' kanıtı."""
    return [
        [tuple(r) for r in repo.conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2")]
        for t in ("calendars", "events", "event_overrides", "reminders", "tasks", "silinenler")
    ]


def _event_baslik(repo, uid):
    satir = repo.conn.execute("SELECT title FROM events WHERE uid = ?", (uid,)).fetchone()
    return satir["title"] if satir else None


def _guncelleme(repo, uid, tablo="events"):
    return repo.conn.execute(f"SELECT updated_at FROM {tablo} WHERE uid = ?", (uid,)).fetchone()[0]


def _iki_cihaz_ortak(a, b):
    """Her iki cihazda aynı takvim + etkinlik bulunur (a'dan b'ye bir senkron sonrası)."""
    takvim = a.add_calendar("Kişisel", "#3b82f6")
    etkinlik = _etkinlik(a, takvim)
    _gonder(a, b)
    return takvim, etkinlik


# ---------------------------------------------------------------------------
# Dışa aktarma
# ---------------------------------------------------------------------------

def test_disa_aktarma_ust_duzey_biçim(a):
    d = durum_uret(a, cihaz_id="kimlik-1", cihaz_adi="Arda-PC", uygulama="desktop 1.8.0")

    assert d["format"] == "takvim-sync" and d["version"] == 1
    assert d["device"] == {"id": "kimlik-1", "name": "Arda-PC", "app": "desktop 1.8.0"}
    assert d["created_at"].endswith("Z") and len(d["created_at"]) == 20
    assert (d["calendars"], d["events"], d["tasks"], d["deleted"]) == ([], [], [], [])


def test_disa_aktarma_etkinlik_alanlari(a):
    takvim = a.add_calendar("Kişisel", "#3b82f6")
    e = _etkinlik(
        a, takvim, "e1", rrule="FREQ=WEEKLY;BYDAY=TU", description="not", location="Oda 3",
        rdate=(ist(2026, 12, 25, 10),), exdate=(ist(2026, 11, 10, 10),),
    )
    a.add_reminder(e.id, 60)
    a.add_reminder(e.id, 10)
    a.move_occurrence(e.id, ist(2026, 11, 17, 10), ist(2026, 11, 17, 12))

    ev = _dosya(a)["events"][0]

    assert ev["calendar_uid"] == takvim.uid
    assert (ev["title"], ev["description"], ev["location"]) == ("Toplantı", "not", "Oda 3")
    assert (ev["start_utc"], ev["end_utc"]) == ("2026-11-03T07:00:00Z", "2026-11-03T08:00:00Z")
    assert (ev["tzid"], ev["all_day"], ev["rrule"]) == (IST, False, "FREQ=WEEKLY;BYDAY=TU")
    assert ev["rdate"] == ["2026-12-25T07:00:00Z"] and ev["exdate"] == ["2026-11-10T07:00:00Z"]
    assert ev["reminders"] == [10, 60]
    assert ev["overrides"] == [{
        "original_start_utc": "2026-11-17T07:00:00Z", "cancelled": False,
        "new_start_utc": "2026-11-17T09:00:00Z", "new_end_utc": "2026-11-17T10:00:00Z",
        "new_title": None, "new_location": None,
    }]


def test_disa_aktarma_cihaza_ozel_alanlar_dosyaya_girmez(a):
    takvim = a.add_calendar("Kişisel", "#3b82f6")
    e = _etkinlik(a, takvim)
    a.add_reminder(e.id, 5)

    ham = json_metni(_dosya(a))

    for yasak in ("sequence", "ics_sequence", "reminder_fired", "silinen_seriler", "series_end"):
        assert yasak not in ham


def test_disa_aktarma_gorev_ve_silinenler(a):
    takvim = a.add_calendar("Kişisel", "#3b82f6")
    plansiz = a.add_task(Task(id=None, uid="g1", title="Rapor", notes="taslak"))
    saatli = a.plan_task_slot(
        a.add_task(Task(id=None, uid="g2", title="Ders")).id,
        ist(2026, 11, 3, 10), ist(2026, 11, 3, 11), takvim.id, IST,
    )
    a.set_task_done(plansiz.id, True)
    olu = _etkinlik(a, takvim, "olu")
    a.delete_event(olu.id)

    d = _dosya(a)
    gorevler = {g["uid"]: g for g in d["tasks"]}

    assert gorevler["g1"]["done_at"] is not None and gorevler["g1"]["notes"] == "taslak"
    assert gorevler["g2"]["event_uid"] == a.get_event(saatli.event_id).uid
    assert gorevler["g2"]["plan_day"] is None
    assert [(s["kind"], s["uid"]) for s in d["deleted"]] == [("event", "olu")]


def test_disa_aktarma_ayni_durum_ayni_cikti(a, b):
    """Sıralama uid'e göre: eklenme sırası dosyayı değiştirmez."""
    takvim_a = a.add_calendar("Kişisel", "#3b82f6")
    _etkinlik(a, takvim_a, "e1")
    _etkinlik(a, takvim_a, "e2", baslik="İkinci")
    _gonder(a, b)

    assert _durum(a) == _durum(b)


def test_json_metni_turkce_karakterleri_kacirmaz(a):
    a.add_calendar("Çalışma İşleri", "#3b82f6")

    metin = json_metni(_dosya(a))

    assert "Çalışma İşleri" in metin
    assert json.loads(metin)["calendars"][0]["name"] == "Çalışma İşleri"


def test_cihaz_kimligi_kalici_ve_dizinsiz_gecici(tmp_path):
    ilk = cihaz_kimligi(tmp_path)

    assert cihaz_kimligi(tmp_path) == ilk
    assert cihaz_kimligi(None) != cihaz_kimligi(None)


def test_cihaz_kimligi_bozuk_dosyada_yeniden_uretir(tmp_path):
    (tmp_path / "cihaz.json").write_text("{bozuk", encoding="utf-8")

    kimlik = cihaz_kimligi(tmp_path)

    assert kimlik and cihaz_kimligi(tmp_path) == kimlik


# ---------------------------------------------------------------------------
# Gidiş-dönüş ve idempotency
# ---------------------------------------------------------------------------

def _dolu_cihaz(repo):
    """Her kayıt türünü ve çocuğu içeren örnek durum."""
    k1 = repo.add_calendar("Kişisel", "#3b82f6")
    k2 = repo.add_calendar("Ders", "#e0524a", visible=False)
    tek = _etkinlik(repo, k1, "tek", description="d", location="l")
    repo.add_reminder(tek.id, 15)
    seri = _etkinlik(repo, k2, "seri", rrule="FREQ=WEEKLY;BYDAY=TU", tzid=NY,
                     start_utc=ist(2026, 11, 3, 10), end_utc=ist(2026, 11, 3, 11),
                     exdate=(ist(2026, 11, 24, 10),))
    repo.cancel_occurrence(seri.id, ist(2026, 11, 10, 10))
    repo.move_occurrence(seri.id, ist(2026, 11, 17, 10), ist(2026, 11, 17, 12))
    repo.add_reminder(seri.id, 30)
    repo.add_task(Task(id=None, uid="gun", title="Gün planlı", plan_day=date(2026, 11, 5)))
    blok = repo.plan_task_slot(
        repo.add_task(Task(id=None, uid="saat", title="Saat planlı")).id,
        ist(2026, 11, 4, 14), ist(2026, 11, 4, 15), k1.id, IST,
    )
    repo.set_task_done(blok.id, True)
    repo.add_task(Task(id=None, uid="plansiz", title="Plansız"))
    olu = _etkinlik(repo, k1, "olu")
    repo.delete_event(olu.id)
    repo.delete_task(repo.add_task(Task(id=None, uid="olu-gorev", title="x")).id)


def test_gidis_donus_tum_kayit_turleri(a, b):
    _dolu_cihaz(a)

    rapor = _gonder(a, b)

    assert _durum(b) == _durum(a)
    assert rapor.as_dict()["total"] == {"added": 8, "updated": 0, "deleted": 0, "skipped": 0}
    assert rapor.added == {"calendar": 2, "event": 3, "task": 3}


def test_gidis_donus_etkinlik_ornekleri_ayni(a, b):
    _dolu_cihaz(a)
    _gonder(a, b)
    pencere = (ist(2026, 11, 1), ist(2027, 1, 31))

    def ozet(repo):
        return [(o.uid, o.start_utc, o.end_utc, o.title, o.is_override)
                for o in repo.occurrences(*pencere, include_hidden=True)]

    assert ozet(a) == ozet(b) and len(ozet(a)) > 5


def test_ayni_dosya_ikinci_kez_hicbir_seyi_degistirmez(a, b):
    _dolu_cihaz(a)
    metin = json_metni(_dosya(a))
    ice_aktar(b, metin)
    once = _ham(b)

    rapor = ice_aktar(b, metin)

    assert rapor.as_dict()["total"] == {"added": 0, "updated": 0, "deleted": 0, "skipped": 0}
    assert _ham(b) == once, "sequence dahil hiçbir satır değişmemeli"


def test_geri_gonderme_yankisi_yok(a, b):
    """a -> b -> a: b'nin dosyasını a'ya geri vermek hiçbir şeyi değiştirmez."""
    _dolu_cihaz(a)
    _gonder(a, b)
    once = _ham(a)

    rapor = _gonder(b, a)

    assert rapor.as_dict()["total"] == {"added": 0, "updated": 0, "deleted": 0, "skipped": 0}
    assert _ham(a) == once


def test_bytes_ve_bom_kabul_edilir(a, b):
    a.add_calendar("Kişisel", "#3b82f6")

    ice_aktar(b, b"\xef\xbb\xbf" + json_metni(_dosya(a)).encode("utf-8"))

    assert [c.name for c in b.list_calendars()] == ["Kişisel"]


def test_bilinmeyen_alanlar_yok_sayilir(a, b):
    a.add_calendar("Kişisel", "#3b82f6")
    d = _dosya(a)
    d["gelecek_alan"] = {"x": 1}
    d["calendars"][0]["yeni_ozellik"] = True

    rapor = ice_aktar(b, d)

    assert rapor.added["calendar"] == 1


# ---------------------------------------------------------------------------
# Son yazan kazanır
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("yon", ["a_b", "b_a"])
def test_dosya_yeniyse_yerel_degisir_her_iki_yonde(a, b, yon):
    _iki_cihaz_ortak(a, b)
    kaynak, hedef = (a, b) if yon == "a_b" else (b, a)
    ev = kaynak.get_event_by_uid("e1")
    kaynak.update_event(replace(ev, title="Yeni başlık"))
    kaynak.add_reminder(ev.id, 20)
    _damga(kaynak, "events", "e1", YENI)
    _damga(hedef, "events", "e1", ORTA)

    rapor = _gonder(kaynak, hedef)

    assert rapor.updated["event"] == 1
    assert _event_baslik(hedef, "e1") == "Yeni başlık"
    assert [r.minutes_before for r in hedef.list_reminders(hedef.get_event_by_uid("e1").id)] == [20]
    assert _guncelleme(hedef, "e1") == YENI, "içe aktarılan kaydın updated_at'i dosyadaki değer kalır"


@pytest.mark.parametrize("yon", ["a_b", "b_a"])
def test_dosya_eskiyse_yerel_kalir_her_iki_yonde(a, b, yon):
    _iki_cihaz_ortak(a, b)
    kaynak, hedef = (a, b) if yon == "a_b" else (b, a)
    kaynak.update_event(replace(kaynak.get_event_by_uid("e1"), title="Eski cihaz"))
    hedef.update_event(replace(hedef.get_event_by_uid("e1"), title="Yerel"))
    _damga(kaynak, "events", "e1", ORTA)
    _damga(hedef, "events", "e1", YENI)

    rapor = _gonder(kaynak, hedef)

    assert rapor.as_dict()["total"] == {"added": 0, "updated": 0, "deleted": 0, "skipped": 0}
    assert _event_baslik(hedef, "e1") == "Yerel"


def test_updated_at_esitse_yerel_kalir(a, b):
    _iki_cihaz_ortak(a, b)
    a.update_event(replace(a.get_event_by_uid("e1"), title="A"))
    b.update_event(replace(b.get_event_by_uid("e1"), title="B"))
    _damga(a, "events", "e1", ORTA)
    _damga(b, "events", "e1", ORTA)

    _gonder(a, b)

    assert _event_baslik(b, "e1") == "B"


def test_etkinlik_tek_birim_cocuklar_birlikte_degisir(a, b):
    """Kazanan etkinlik override ve hatırlatıcılarını da getirir, kaybedenin ki gider."""
    k = a.add_calendar("Kişisel", "#3b82f6")
    e = _etkinlik(a, k, "seri", rrule="FREQ=DAILY")
    _gonder(a, b)
    eb = b.get_event_by_uid("seri")
    b.add_reminder(eb.id, 5)
    b.cancel_occurrence(eb.id, ist(2026, 11, 4, 10))
    a.add_reminder(e.id, 99)
    a.move_occurrence(e.id, ist(2026, 11, 5, 10), ist(2026, 11, 5, 13))
    _damga(a, "events", "seri", YENI)
    _damga(b, "events", "seri", ORTA)

    _gonder(a, b)

    assert [r.minutes_before for r in b.list_reminders(eb.id)] == [99]
    ovl = b.list_overrides(eb.id)
    assert [(o.original_start_utc, o.cancelled) for o in ovl] == [(ist(2026, 11, 5, 10), False)]


def test_degismeyen_hatirlaticinin_tetiklenme_kaydi_korunur(a, b):
    """Hatırlatıcı farkla güncellenir: sil-ekle `reminder_fired`'i silip yeniden öttürürdü."""
    k = a.add_calendar("Kişisel", "#3b82f6")
    e = _etkinlik(a, k, "e1")
    a.add_reminder(e.id, 10)
    _gonder(a, b)
    eb = b.get_event_by_uid("e1")
    hat = b.list_reminders(eb.id)[0]
    assert b.mark_fired(hat.id, eb.start_utc)
    a.update_event(replace(e, title="Değişti"))
    _damga(a, "events", "e1", YENI)
    _damga(b, "events", "e1", ORTA)

    _gonder(a, b)

    assert _event_baslik(b, "e1") == "Değişti"
    assert b.fired_keys() == {(hat.id, eb.start_utc)}


def test_etkinlik_takvim_degistirince_hedef_takvim_uidyle_bulunur(a, b):
    k1 = a.add_calendar("Bir", "#3b82f6")
    k2 = a.add_calendar("İki", "#e0524a")
    e = _etkinlik(a, k1, "e1")
    _gonder(a, b)
    a.update_event(replace(e, calendar_id=k2.id))
    _damga(a, "events", "e1", YENI)
    _damga(b, "events", "e1", ORTA)

    _gonder(a, b)

    uid_b = b.conn.execute(
        "SELECT c.uid FROM events e JOIN calendars c ON c.id = e.calendar_id WHERE e.uid = 'e1'"
    ).fetchone()[0]
    assert uid_b == k2.uid


def test_takvim_son_yazan_kazanir(a, b):
    k = a.add_calendar("Kişisel", "#3b82f6")
    _gonder(a, b)
    a.update_calendar(replace(k, name="Yeniden adlı", color="#000000", visible=False))
    _damga(a, "calendars", k.uid, YENI)
    _damga(b, "calendars", k.uid, ORTA)

    rapor = _gonder(a, b)

    ayri = b.list_calendars()[0]
    assert (ayri.name, ayri.color, ayri.visible) == ("Yeniden adlı", "#000000", False)
    assert rapor.updated["calendar"] == 1
    assert _guncelleme(b, k.uid, "calendars") == YENI


def test_gorev_son_yazan_kazanir(a, b):
    a.add_calendar("Kişisel", "#3b82f6")
    g = a.add_task(Task(id=None, uid="g1", title="Eski"))
    _gonder(a, b)
    a.update_task(replace(g, title="Yeni"))
    a.set_task_done(g.id, True)
    _damga(a, "tasks", "g1", YENI)
    _damga(b, "tasks", "g1", ORTA)

    rapor = _gonder(a, b)

    yerel = b.get_task_by_uid("g1")
    assert (yerel.title, yerel.done) == ("Yeni", True) and rapor.updated["task"] == 1
    assert _guncelleme(b, "g1", "tasks") == YENI


# ---------------------------------------------------------------------------
# Silmeler
# ---------------------------------------------------------------------------

def _uzaktan_sil(a, b, uid, silme_zamani, yerel_guncelleme):
    """a'da etkinliği sil, mezar taşı zamanını sabitle; b'deki kaydın updated_at'ini ayarla."""
    ev = a.get_event_by_uid(uid)
    a.delete_event(ev.id)
    _mezar_zamani(a, "event", uid, silme_zamani)
    _damga(b, "events", uid, yerel_guncelleme)


@pytest.mark.parametrize(
    "silme, yerel, silinir",
    [(YENI, ORTA, True), (ORTA, ORTA, False), (ESKI, ORTA, False)],
    ids=["silme-yeni-silinir", "esit-kayit-kalir", "guncelleme-yeni-kayit-kalir"],
)
def test_dosyadaki_silme_yerel_kayitla_karsilastirilir(a, b, silme, yerel, silinir):
    _iki_cihaz_ortak(a, b)
    _uzaktan_sil(a, b, "e1", silme, yerel)

    rapor = _gonder(a, b)

    assert (b.get_event_by_uid("e1") is None) is silinir
    assert rapor.deleted["event"] == (1 if silinir else 0)
    if silinir:
        assert _mezarlar(b)[("event", "e1")] == silme, "mezar taşı dosyadaki deleted_at'i aynen taşır"
    else:
        assert ("event", "e1") not in _mezarlar(b)


def test_uzaktan_silme_yankilanmaz(a, b):
    _iki_cihaz_ortak(a, b)
    _uzaktan_sil(a, b, "e1", YENI, ORTA)
    _gonder(a, b)
    once = _ham(a)

    rapor = _gonder(b, a)

    assert rapor.as_dict()["total"] == {"added": 0, "updated": 0, "deleted": 0, "skipped": 0}
    assert _mezarlar(a) == _mezarlar(b)
    assert _ham(a) == once


def test_silinen_kayit_icin_hic_gormedigi_cihazda_da_mezar_tasi_tutulur(a, b):
    """c cihazı e1'i hiç görmedi; mezar taşını taşırsa silme üçüncü cihaza da ulaşır."""
    _iki_cihaz_ortak(a, b)
    _uzaktan_sil(a, b, "e1", YENI, ORTA)
    c = Repo.open(":memory:")

    _gonder(a, c)

    assert _mezarlar(c) == {("event", "e1"): YENI}
    c.close()


@pytest.mark.parametrize(
    "kayit, silme, canlanir",
    [(YENI, ORTA, True), (ORTA, ORTA, True), (ESKI, ORTA, False)],
    ids=["kayit-yeni-canlanir", "esit-kayit-kalir", "silme-yeni-silik-kalir"],
)
def test_yerel_silmeye_karsi_dosyadaki_canli_kayit(a, b, kayit, silme, canlanir):
    _iki_cihaz_ortak(a, b)
    b.delete_event(b.get_event_by_uid("e1").id)
    _mezar_zamani(b, "event", "e1", silme)
    _damga(a, "events", "e1", kayit)

    rapor = _gonder(a, b)

    assert (b.get_event_by_uid("e1") is not None) is canlanir
    assert rapor.added["event"] == (1 if canlanir else 0)
    assert (("event", "e1") in _mezarlar(b)) is not canlanir, "canlanınca mezar taşı kalkar"


def test_gorev_silme_ve_canlanma(a, b):
    a.add_calendar("Kişisel", "#3b82f6")
    g = a.add_task(Task(id=None, uid="g1", title="Rapor"))
    _gonder(a, b)
    a.delete_task(g.id)
    _mezar_zamani(a, "task", "g1", YENI)
    _damga(b, "tasks", "g1", ORTA)

    rapor = _gonder(a, b)

    assert b.get_task_by_uid("g1") is None and rapor.deleted["task"] == 1
    assert _mezarlar(b)[("task", "g1")] == YENI


def test_dosyada_hem_canli_hem_daha_yeni_silme_varsa_silme_kazanir(a, b):
    _iki_cihaz_ortak(a, b)
    d = _dosya(a)
    d["deleted"].append({"kind": "event", "uid": "e1", "deleted_at": YENI})
    _damga(a, "events", "e1", ORTA)
    d["events"][0]["updated_at"] = ORTA
    _damga(b, "events", "e1", ESKI)

    rapor = ice_aktar(b, d)

    assert b.get_event_by_uid("e1") is None
    assert rapor.deleted["event"] == 1 and rapor.updated["event"] == 0


def test_takvim_silme_icindeki_etkinlikleri_ve_mezar_taslarini_goturur(a, b):
    k = a.add_calendar("Kişisel", "#3b82f6")
    _etkinlik(a, k, "e1")
    _etkinlik(a, k, "e2")
    _gonder(a, b)
    a.delete_calendar(k.id)
    # dosyada olay olarak yalnızca e1'in kendi mezar taşı var; e2 takvimle gidecek
    a.conn.execute("DELETE FROM silinenler WHERE uid = 'e2'")
    _mezar_zamani(a, "calendar", k.uid, YENI)
    _mezar_zamani(a, "event", "e1", ORTA)
    _damga(b, "calendars", k.uid, ESKI)
    _damga(b, "events", "e1", ESKI)
    _damga(b, "events", "e2", ESKI)

    rapor = _gonder(a, b)

    assert b.list_calendars() == [] and b.list_events() == []
    assert rapor.deleted == {"calendar": 1, "event": 2, "task": 0}
    assert _mezarlar(b) == {
        ("calendar", k.uid): YENI, ("event", "e1"): ORTA, ("event", "e2"): YENI,
    }


def test_takvim_silme_takvim_yeniyse_kalir(a, b):
    k = a.add_calendar("Kişisel", "#3b82f6")
    _etkinlik(a, k, "e1")
    _gonder(a, b)
    a.delete_calendar(k.id)
    _mezar_zamani(a, "calendar", k.uid, ORTA)
    _damga(b, "calendars", k.uid, YENI)

    _gonder(a, b)

    assert [c.uid for c in b.list_calendars()] == [k.uid]
    assert b.get_event_by_uid("e1") is not None


# ---------------------------------------------------------------------------
# Takvim eşleşmesi ve yetim etkinlik
# ---------------------------------------------------------------------------

def test_ayni_adli_takvim_uid_degistirilerek_benimsenir(a, b):
    ka = a.add_calendar("Kişisel", "#3b82f6")
    _etkinlik(a, ka, "e1")
    kb = b.add_calendar("  kişisel ", "#000000")
    _etkinlik(b, kb, "yerel")

    rapor = _gonder(a, b)

    takvimler = b.list_calendars()
    assert [c.uid for c in takvimler] == [ka.uid] and takvimler[0].id == kb.id
    assert rapor.added["calendar"] == 0
    assert {e.uid for e in b.list_events(calendar_id=kb.id)} == {"e1", "yerel"}


def test_benimsenen_takvim_normal_kayit_kuralina_tabi(a, b):
    ka = a.add_calendar("Kişisel", "#3b82f6")
    b.add_calendar("kişisel", "#000000")
    _damga(a, "calendars", ka.uid, YENI)
    b.conn.execute("UPDATE calendars SET updated_at = ?", (ORTA,))

    rapor = _gonder(a, b)

    ayri = b.list_calendars()[0]
    assert (ayri.name, ayri.color) == ("Kişisel", "#3b82f6") and rapor.updated["calendar"] == 1


def test_ad_eslesmesi_ikinci_importta_ikilenmez(a, b):
    a.add_calendar("Kişisel", "#3b82f6")
    b.add_calendar("Kişisel", "#3b82f6")
    _gonder(a, b)

    rapor = _gonder(a, b)

    assert len(b.list_calendars()) == 1
    assert rapor.as_dict()["total"] == {"added": 0, "updated": 0, "deleted": 0, "skipped": 0}


def test_ad_eslesmesi_dosyada_kendi_uidsi_olan_takvimi_benimsemez(a, b):
    """Yerel takvim dosyada kendi uid'iyle varsa başka bir takvime kimlik verilmez."""
    k1 = a.add_calendar("İş", "#3b82f6")
    k2 = a.add_calendar("Iş", "#e0524a")  # casefold ile farklı: i/ı
    yerel = b.add_calendar("iş", "#000000")
    b.conn.execute("UPDATE calendars SET uid = ? WHERE id = ?", (k1.uid, yerel.id))

    _gonder(a, b)

    uidler = sorted(c.uid for c in b.list_calendars())
    assert uidler == sorted([k1.uid, k2.uid])


def test_ad_eslesmesi_farkli_adli_takvimi_benimsemez(a, b):
    a.add_calendar("Ders", "#3b82f6")
    b.add_calendar("İş", "#3b82f6")

    _gonder(a, b)

    assert sorted(c.name for c in b.list_calendars()) == ["Ders", "İş"]


def test_yetim_etkinlik_eklenmez_atlandi_sayilir(a, b):
    k = a.add_calendar("Kişisel", "#3b82f6")
    _etkinlik(a, k, "e1")
    d = _dosya(a)
    d["calendars"] = []

    rapor = ice_aktar(b, d)

    assert b.list_events() == [] and rapor.skipped["event"] == 1
    assert rapor.as_dict()["total"]["skipped"] == 1


# ---------------------------------------------------------------------------
# Görev <-> blok
# ---------------------------------------------------------------------------

def test_saat_planli_gorev_blogu_ile_baglanir(a, b):
    k = a.add_calendar("Kişisel", "#3b82f6")
    g = a.plan_task_slot(
        a.add_task(Task(id=None, uid="g1", title="Ders")).id,
        ist(2026, 11, 3, 10), ist(2026, 11, 3, 11), k.id, IST,
    )
    blok_uid = a.get_event(g.event_id).uid

    _gonder(a, b)

    gb = b.get_task_by_uid("g1")
    assert gb.event_id is not None and b.get_event(gb.event_id).uid == blok_uid
    assert gb.plan_day is None


def test_blok_bulunamazsa_gorev_plansiza_doner(a, b):
    k = a.add_calendar("Kişisel", "#3b82f6")
    a.plan_task_slot(
        a.add_task(Task(id=None, uid="g1", title="Ders")).id,
        ist(2026, 11, 3, 10), ist(2026, 11, 3, 11), k.id, IST,
    )
    d = _dosya(a)
    d["events"] = []

    ice_aktar(b, d)

    gb = b.get_task_by_uid("g1")
    assert (gb.event_id, gb.plan_day) == (None, None)


def test_blogu_silinen_gorev_yerelde_plansiza_doner(a, b):
    k = a.add_calendar("Kişisel", "#3b82f6")
    g = a.plan_task_slot(
        a.add_task(Task(id=None, uid="g1", title="Ders")).id,
        ist(2026, 11, 3, 10), ist(2026, 11, 3, 11), k.id, IST,
    )
    blok_uid = a.get_event(g.event_id).uid
    _gonder(a, b)
    a.delete_event(g.event_id)
    _mezar_zamani(a, "event", blok_uid, YENI)
    _damga(b, "events", blok_uid, ESKI)

    _gonder(a, b)

    gb = b.get_task_by_uid("g1")
    assert b.get_event_by_uid(blok_uid) is None
    assert (gb.event_id, gb.plan_day) == (None, None), "görev silinmez, plansız kalır"


def test_gun_planina_gecen_gorevin_blogu_silinir(a, b):
    k = a.add_calendar("Kişisel", "#3b82f6")
    g = a.plan_task_slot(
        a.add_task(Task(id=None, uid="g1", title="Ders")).id,
        ist(2026, 11, 3, 10), ist(2026, 11, 3, 11), k.id, IST,
    )
    blok_uid = a.get_event(g.event_id).uid
    _gonder(a, b)
    a.plan_task_day(g.id, date(2026, 11, 9))
    _mezar_zamani(a, "event", blok_uid, YENI)
    _damga(a, "tasks", "g1", YENI)
    _damga(b, "events", blok_uid, ESKI)
    _damga(b, "tasks", "g1", ESKI)

    _gonder(a, b)

    gb = b.get_task_by_uid("g1")
    assert str(gb.plan_day) == "2026-11-09" and gb.event_id is None
    assert b.get_event_by_uid(blok_uid) is None


def test_baska_goreve_bagli_blok_ikinci_goreve_baglanmaz(a, b):
    k = a.add_calendar("Kişisel", "#3b82f6")
    a.plan_task_slot(
        a.add_task(Task(id=None, uid="g1", title="Bir")).id,
        ist(2026, 11, 3, 10), ist(2026, 11, 3, 11), k.id, IST,
    )
    d = _dosya(a)
    ikinci = copy.deepcopy(next(t for t in d["tasks"] if t["uid"] == "g1"))
    ikinci["uid"] = "g2"
    d["tasks"].append(ikinci)  # aynı bloğa işaret eden ikinci görev

    ice_aktar(b, d)

    assert b.get_task_by_uid("g1").event_id is not None, "dosyada ilk gelen bloğu alır"
    assert b.get_task_by_uid("g2").event_id is None, "UNIQUE(event_id): ikincisi plansız kalır"


def test_tekrarli_etkinlige_baglanan_gorev_plansiz_olur(a, b):
    k = a.add_calendar("Kişisel", "#3b82f6")
    _etkinlik(a, k, "tekrarli", rrule="FREQ=DAILY")
    a.add_task(Task(id=None, uid="g1", title="Ders"))
    d = _dosya(a)
    d["tasks"][0]["event_uid"] = "tekrarli"  # AGENTS 68: blok tekrarlı olamaz

    ice_aktar(b, d)

    assert b.get_task_by_uid("g1").event_id is None


# ---------------------------------------------------------------------------
# Reddedilen dosyalar
# ---------------------------------------------------------------------------

def _temel_dosya(a):
    k = a.add_calendar("Kişisel", "#3b82f6")
    _etkinlik(a, k, "e1")
    a.add_task(Task(id=None, uid="g1", title="Rapor"))
    return _dosya(a)


def _degistir(yol, deger):
    def uygula(d):
        hedef = d
        for anahtar in yol[:-1]:
            hedef = hedef[anahtar]
        hedef[yol[-1]] = deger
        return d
    return uygula


BOZUKLAR = {
    "format-yanlis": _degistir(["format"], "baska"),
    "version-yok": lambda d: d.pop("version") and d,
    "version-metin": _degistir(["version"], "1"),
    "version-sifir": _degistir(["version"], 0),
    "takvimler-liste-degil": _degistir(["calendars"], {"a": 1}),
    "etkinlik-nesne-degil": _degistir(["events"], [1, 2]),
    "takvim-renk": _degistir(["calendars", 0, "color"], "kirmizi"),
    "takvim-ad-bos": _degistir(["calendars", 0, "name"], "  "),
    "takvim-visible-int": _degistir(["calendars", 0, "visible"], 1),
    "zaman-bicimi": _degistir(["events", 0, "start_utc"], "2026-11-03 07:00"),
    "zaman-mikrosaniye": _degistir(["events", 0, "end_utc"], "2026-11-03T08:00:00.5Z"),
    "zaman-imkansiz": _degistir(["events", 0, "end_utc"], "2026-13-45T08:00:00Z"),
    "tzid-gecersiz": _degistir(["events", 0, "tzid"], "Mars/Olympus"),
    "bitis-baslangictan-once": _degistir(["events", 0, "end_utc"], "2026-11-03T06:00:00Z"),
    "uid-bos": _degistir(["events", 0, "uid"], ""),
    "uid-sayi": _degistir(["events", 0, "uid"], 5),
    "tum-gun-gece-yarisi-degil": _degistir(["events", 0, "all_day"], True),
    "hatirlatici-negatif": _degistir(["events", 0, "reminders"], [-5]),
    "hatirlatici-metin": _degistir(["events", 0, "reminders"], ["10"]),
    "rdate-metin": _degistir(["events", 0, "rdate"], "2026-11-03T07:00:00Z"),
    "override-eksik-anahtar": _degistir(["events", 0, "overrides"], [{"cancelled": True}]),
    "gorev-baslik-bos": _degistir(["tasks", 0, "title"], ""),
    "gorev-plan-gunu-bozuk": _degistir(["tasks", 0, "plan_day"], "yarın"),
    "gorev-hem-gun-hem-blok": lambda d: d["tasks"][0].update(plan_day="2026-11-03", event_uid="e1") or d,
    "silinen-kind-bilinmeyen": _degistir(["deleted"], [{"kind": "x", "uid": "u", "deleted_at": ESKI}]),
    "silinen-zaman-bozuk": _degistir(["deleted"], [{"kind": "event", "uid": "u", "deleted_at": "dün"}]),
    "tekrarlayan-uid": lambda d: d["events"].append(copy.deepcopy(d["events"][0])) or d,
    "cok-yogun-seri": _degistir(["events", 0, "rrule"], "FREQ=SECONDLY;COUNT=2000000"),
    # e2e (takvim-mobil/tool/e2e) bulgusu: sınırsız çözülemeyen kural series_end'de çözülmüyordu,
    # içeri girer ve expand() her görünümde ValueError verirdi.
    "rrule-cozulemez-sinirsiz": _degistir(["events", 0, "rrule"], "FREQ=BOGUS;;;"),
    "rrule-cozulemez-sinirli": _degistir(["events", 0, "rrule"], "FREQ=DAILY;COUNT=x"),
    "rrule-gun-adi-gecersiz": _degistir(["events", 0, "rrule"], "FREQ=WEEKLY;BYDAY=XX"),
    # JSON yalnız vekil kaçışına izin verir; UTF-8'e yazılamaz (ham UnicodeEncodeError olurdu).
    "yalniz-vekil-karakter": _degistir(["events", 0, "title"], "x" + chr(0xD800) + "y"),
    # Sınırsız büyük dakika: SQLite INTEGER taşması ve `başlangıç - dakika` OverflowError'ı.
    "hatirlatici-sqlite-tasmasi": _degistir(["events", 0, "reminders"], [10**30]),
    "hatirlatici-10-yildan-fazla": _degistir(["events", 0, "reminders"], [10 * 365 * 24 * 60 + 1]),
}


@pytest.mark.parametrize("ad", list(BOZUKLAR))
def test_bozuk_dosya_reddedilir_hicbir_sey_degismez(a, b, ad):
    d = BOZUKLAR[ad](_temel_dosya(a))
    b.add_calendar("Başka", "#000000")
    once = _ham(b)

    with pytest.raises(SenkronHatasi) as hata:
        ice_aktar(b, d)

    assert hata.value.kod == "senkron_bozuk" and hata.value.param["ayrinti"]
    assert _ham(b) == once


@pytest.mark.parametrize("ham", ["", "{bozuk", "[]", "5", "null", b"\xff\xfe\x00"])
def test_json_olmayan_girdi_reddedilir(b, ham):
    with pytest.raises(SenkronHatasi) as hata:
        ice_aktar(b, ham)
    assert hata.value.kod == "senkron_bozuk"


def test_bilinenden_buyuk_surum_reddedilir_guncelle_der(a, b):
    d = _temel_dosya(a)
    d["version"] = 2
    once = _ham(b)

    with pytest.raises(SenkronHatasi) as hata:
        ice_aktar(b, d)

    assert hata.value.kod == "senkron_surum_yeni"
    assert "güncelle" in str(hata.value) and hata.value.param == {"dosya": 2, "uygulama": 1}
    assert _ham(b) == once


def test_hata_olunca_hicbir_sey_degismez_transaction_geri_alinir(a, b, monkeypatch):
    """Takvim ve etkinlikler yazıldıktan SONRA bir adım patlarsa hepsi geri alınır."""
    _dolu_cihaz(a)
    b.add_calendar("Mevcut", "#000000")
    once = _ham(b)

    def patla(*args, **kwargs):
        raise RuntimeError("disk doldu")

    monkeypatch.setattr(ice_modulu, "_gorev_birlestir", patla)
    with pytest.raises(RuntimeError, match="disk doldu"):
        _gonder(a, b)

    assert _ham(b) == once, "yarım birleşme kalmamalı"
    assert not b.conn.in_transaction

    monkeypatch.undo()
    _gonder(a, b)  # sonra normal içe aktarma çalışır
    assert len(b.list_calendars()) == 3


def test_rapor_sozluk_toplamlari(a, b):
    _dolu_cihaz(a)

    sozluk = _gonder(a, b).as_dict()

    assert set(sozluk) == {"added", "updated", "deleted", "skipped", "total"}
    assert sozluk["total"]["added"] == sum(sozluk["added"].values()) == 8


def test_uzaktan_gelen_kayit_yerel_id_cakismasindan_etkilenmez(a, b):
    """Yerel tamsayı id'ler cihazdan cihaza farklı: birleştirme yalnızca uid'e bakar."""
    ka = a.add_calendar("Ortak", "#3b82f6")
    for i in range(3):
        b.add_calendar(f"Yerel {i}", "#000000")
    _etkinlik(a, ka, "e1")

    _gonder(a, b)

    assert {c.name for c in b.list_calendars()} == {"Ortak", "Yerel 0", "Yerel 1", "Yerel 2"}
    assert b.get_calendar(b.get_event_by_uid("e1").calendar_id).uid == ka.uid


def test_sure_ve_override_bitisi_eksikse_hesaplanir(a, b):
    k = a.add_calendar("Kişisel", "#3b82f6")
    e = _etkinlik(a, k, "seri", rrule="FREQ=DAILY")
    d = _dosya(a)
    d["events"][0]["overrides"] = [{
        "original_start_utc": "2026-11-04T07:00:00Z", "cancelled": False,
        "new_start_utc": "2026-11-04T09:00:00Z", "new_end_utc": None,
        "new_title": None, "new_location": None,
    }]

    ice_aktar(b, d)

    ov = b.list_overrides(b.get_event_by_uid("seri").id)[0]
    assert ov.new_end_utc == ov.new_start_utc + timedelta(hours=1)
    assert e.id is not None


def test_hatirlatici_on_yil_siniri_dahil_kabul_edilir(a, b):
    k = a.add_calendar("Kişisel", "#3b82f6")
    _etkinlik(a, k, "e1")
    d = _dosya(a)
    d["events"][0]["reminders"] = [10 * 365 * 24 * 60]

    ice_aktar(b, d)

    assert [r.minutes_before for r in b.list_reminders(b.get_event_by_uid("e1").id)] == [10 * 365 * 24 * 60]


def test_takvim_adi_kenar_bosluklari_kirpilir_mobil_modeliyle_ayni(a, b):
    """Mobil takvim adını kırpıyor; kırpılmasaydı iki cihazın adı sonsuza dek ayrışırdı (eşit damga)."""
    a.add_calendar("Ders", "#3b82f6")
    d = _dosya(a)
    d["calendars"][0]["name"] = "  Ders  "

    ice_aktar(b, d)

    assert [c.name for c in b.list_calendars()] == ["Ders"]


def test_rdate_exdate_yinelenenler_tek_ve_sirali(a, b):
    k = a.add_calendar("Kişisel", "#3b82f6")
    _etkinlik(a, k, "seri", rrule="FREQ=DAILY")
    d = _dosya(a)
    d["events"][0]["exdate"] = ["2026-11-09T07:00:00Z", "2026-11-04T07:00:00Z", "2026-11-09T07:00:00Z"]
    d["events"][0]["rdate"] = ["2026-12-01T07:00:00Z", "2026-12-01T07:00:00Z"]

    ice_aktar(b, d)

    assert _dosya(b)["events"][0]["exdate"] == ["2026-11-04T07:00:00Z", "2026-11-09T07:00:00Z"]
    assert _dosya(b)["events"][0]["rdate"] == ["2026-12-01T07:00:00Z"]


# ---------------------------------------------------------------------------
# Güvenilmeyen dosya: kaynak tüketimi (güvenlik incelemesi v1.8.0)
# ---------------------------------------------------------------------------

def _tek_etkinlikli(a, **alanlar) -> dict:
    """Yalnız bir kez çağrılır: `a`ya takvim + etkinlik ekler, dosyasını döndürür."""
    k = a.add_calendar("Kişisel", "#3b82f6")
    _etkinlik(a, k, "e1")
    d = _dosya(a)
    d["events"][0].update(alanlar)
    return d


def test_cok_derin_ic_ice_yapi_kodlu_hatayla_reddedilir(a, b):
    """json.loads/doğrulama yığını taşıyordu: RecursionError yakalanmadan kopuyordu."""
    derin = '{"format": "takvim-sync", "version": 1, "x": ' + "[" * 100_000 + "]" * 100_000 + "}"

    with pytest.raises(SenkronHatasi) as hata:
        ice_aktar(b, derin)

    assert hata.value.kod == "senkron_bozuk" and b.list_calendars() == []


def test_hatirlatici_sayisi_sinirlidir(a, b):
    """~1 milyon farklı değerlik dizi (8 MB'a sığar) hatırlatıcı döngüsünü şişirirdi."""
    sinir = ice_modulu.MAKS_HATIRLATICI_SAYISI
    d = _tek_etkinlikli(a)

    d["events"][0]["reminders"] = list(range(sinir))
    ice_aktar(b, d)
    assert len(b.list_reminders(b.get_event_by_uid("e1").id)) == sinir

    d["events"][0]["reminders"] = list(range(sinir + 1))
    with Repo.open(":memory:") as c:
        with pytest.raises(SenkronHatasi, match="reminders"):
            ice_aktar(c, d)
        assert c.list_calendars() == []


@pytest.mark.parametrize("kural", [
    "FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30",
    "FREQ=SECONDLY;UNTIL=99991231T000000Z;BYMONTH=2;BYMONTHDAY=30",
])
def test_imkansiz_kural_dosyayi_hizla_reddeder(a, b, kural):
    """Eskiden 3-13 sn tarar, sonra her görünümde tekrar ederdi."""
    import time

    d = _tek_etkinlikli(a, rrule=kural)
    t0 = time.monotonic()
    with pytest.raises(SenkronHatasi, match="hiçbir tarihe"):
        ice_aktar(b, d)
    assert time.monotonic() - t0 < 1.0
    assert b.list_calendars() == []


@pytest.mark.parametrize("kural,bas,bit", [
    ("FREQ=HOURLY", "0001-01-02T00:00:00Z", "0001-01-02T01:00:00Z"),
    ("FREQ=SECONDLY", "2026-03-01T00:00:00Z", "2026-03-01T00:00:01Z"),
])
def test_uzak_baslangicli_yogun_seri_goruntuyu_dondurmaz(a, b, kural, bas, bit):
    """Dosya kabul edilir ama ay görünümü milisaniyeler sürer (eskiden 37-46 sn)."""
    import time
    from datetime import datetime

    ice_aktar(b, _tek_etkinlikli(a, rrule=kural, tzid="UTC", start_utc=bas, end_utc=bit))

    t0 = time.monotonic()
    b.occurrences(datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC))
    assert time.monotonic() - t0 < 2.0
