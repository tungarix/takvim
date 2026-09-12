"""Faz 1 kabul kriterleri: CRUD, CASCADE ve iki parçalı aralık sorgusu."""

from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from core import Calendar, Override, to_local
from store import Repo, new_uid
from store.repo import _to_db
from tests.helpers import IST, ist, make_event


@pytest.fixture
def repo():
    """Her test için bellekte taze, migrate edilmiş bir DB."""
    with Repo.open(":memory:") as r:
        yield r


@pytest.fixture
def ders(repo) -> Calendar:
    """Varsayılan görünür takvim."""
    return repo.add_calendar("Ders", "#c0392b")


def _event(ders, **kwargs):
    """Kaydedilmeye hazır (id'siz) Event."""
    kwargs.setdefault("event_id", None)
    kwargs.setdefault("uid", new_uid())
    kwargs.setdefault("calendar_id", ders.id)
    return make_event(
        kwargs.pop("start", ist(2024, 5, 6, 10, 0)),
        kwargs.pop("end", ist(2024, 5, 6, 11, 0)),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Takvim
# ---------------------------------------------------------------------------

def test_takvim_crud(repo):
    """Ekle, oku, güncelle, sil."""
    cal = repo.add_calendar("Kişisel", "#2980b9")
    assert cal.id is not None
    assert repo.get_calendar(cal.id) == cal

    repo.update_calendar(Calendar(id=cal.id, name="Özel", color="#000", visible=False))
    guncel = repo.get_calendar(cal.id)
    assert (guncel.name, guncel.color, guncel.visible) == ("Özel", "#000", False)

    repo.delete_calendar(cal.id)
    assert repo.get_calendar(cal.id) is None


def test_takvim_listesi_gizlileri_filtreler(repo):
    """include_hidden=False görünmeyenleri eler."""
    repo.add_calendar("Görünür", "#111")
    repo.add_calendar("Gizli", "#222", visible=False)

    assert len(repo.list_calendars()) == 2
    assert [c.name for c in repo.list_calendars(include_hidden=False)] == ["Görünür"]


# ---------------------------------------------------------------------------
# Etkinlik
# ---------------------------------------------------------------------------

def test_etkinlik_gidis_donus(repo, ders):
    """Tüm alanlar DB'den aynı şekilde geri gelir."""
    event = _event(
        ders,
        title="Fizik II",
        location="A101",
        description="Vize haftası",
        rrule="FREQ=WEEKLY;BYDAY=MO",
        rdate=(ist(2024, 6, 1, 10, 0),),
        exdate=(ist(2024, 5, 20, 10, 0),),
    )
    kaydedilen = repo.add_event(event)

    assert kaydedilen.id is not None
    okunan = repo.get_event(kaydedilen.id)
    assert okunan == kaydedilen
    assert okunan.rdate == (ist(2024, 6, 1, 10, 0),)
    assert okunan.exdate == (ist(2024, 5, 20, 10, 0),)
    assert repo.get_event_by_uid(event.uid) == kaydedilen


def test_uid_tekil(repo, ders):
    """Aynı UID ikinci kez yazılamaz (.ics mükerrer içe aktarma koruması)."""
    uid = new_uid()
    repo.add_event(_event(ders, uid=uid))
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_event(_event(ders, uid=uid))


def test_series_end_yazarken_hesaplanir(repo, ders):
    """series_end_utc RRULE'dan türetilir; sonsuz seride NULL kalır."""
    sinirli = repo.add_event(_event(ders, rrule="FREQ=DAILY;COUNT=5"))
    sonsuz = repo.add_event(_event(ders, rrule="FREQ=DAILY"))
    tekrarsiz = repo.add_event(_event(ders))

    assert repo.metadata(sinirli.id)["series_end_utc"] == ist(2024, 5, 10, 11, 0)
    assert repo.metadata(sonsuz.id)["series_end_utc"] is None
    assert repo.metadata(tekrarsiz.id)["series_end_utc"] == ist(2024, 5, 6, 11, 0)


def test_update_sequence_artirir_ve_series_end_yeniler(repo, ders):
    """Güncelleme sequence'i artırır ve seri sonunu yeniden hesaplar."""
    from dataclasses import replace

    event = repo.add_event(_event(ders, rrule="FREQ=DAILY;COUNT=5"))
    assert repo.metadata(event.id)["sequence"] == 0

    repo.update_event(replace(event, rrule="FREQ=DAILY;COUNT=10", title="Yeni ad"))

    meta = repo.metadata(event.id)
    assert meta["sequence"] == 1
    assert meta["series_end_utc"] == ist(2024, 5, 15, 11, 0)
    assert repo.get_event(event.id).title == "Yeni ad"


def test_olmayan_etkinligi_guncelleme(repo, ders):
    """Var olmayan id sessizce yutulmaz."""
    from dataclasses import replace

    hayalet = replace(_event(ders), id=999)
    with pytest.raises(LookupError):
        repo.update_event(hayalet)


# ---------------------------------------------------------------------------
# CASCADE
# ---------------------------------------------------------------------------

def test_takvim_silinince_etkinlikleri_de_silinir(repo, ders):
    """ON DELETE CASCADE -- PRAGMA foreign_keys açık olmasa sessizce çalışmazdı."""
    repo.add_event(_event(ders))
    assert len(repo.list_events()) == 1

    repo.delete_calendar(ders.id)
    assert repo.list_events() == []


def test_etkinlik_silinince_overrideleri_de_silinir(repo, ders):
    """Override'lar etkinliğe bağlı; öksüz kalmazlar."""
    event = repo.add_event(_event(ders, rrule="FREQ=DAILY"))
    repo.cancel_occurrence(event.id, ist(2024, 5, 7, 10, 0))
    assert len(repo.list_overrides(event.id)) == 1

    repo.delete_event(event.id)
    assert repo.list_overrides(event.id) == []


# ---------------------------------------------------------------------------
# İki parçalı aralık sorgusu -- Faz 1'in asıl meselesi
# ---------------------------------------------------------------------------

def test_uc_yil_once_baslayan_seri_bu_hafta_bulunur(repo, ders):
    """Serinin başlangıcı pencerenin çok öncesinde olsa bile örnekleri bulunur.

    Faz 1'in varlık sebebi bu: tekrarlı etkinlik DB'de TEK satır ve o satırın
    start_utc'si 2021'de. Basit bir BETWEEN sorgusu hiçbir şey döndürmez.
    """
    repo.add_event(
        _event(
            ders,
            start=ist(2021, 9, 14, 9, 0),  # Salı
            end=ist(2021, 9, 14, 10, 0),
            rrule="FREQ=WEEKLY;BYDAY=TU",
            title="Algoritma",
        )
    )

    ws, we = ist(2024, 5, 6), ist(2024, 5, 13)
    bulunan = repo.occurrences(ws, we)

    assert len(bulunan) == 1
    assert to_local(bulunan[0].start_utc, IST).strftime("%Y-%m-%d %H:%M") == "2024-05-07 09:00"
    assert bulunan[0].title == "Algoritma"

    # Naif sorgunun neden yetmediğini kayda geçiriyoruz.
    naif = repo.conn.execute(
        "SELECT count(*) FROM events WHERE start_utc BETWEEN ? AND ?",
        (_to_db(ws), _to_db(we)),
    ).fetchone()[0]
    assert naif == 0, "Basit BETWEEN bu etkinliği bulamaz; iki parçalı sorgunun sebebi bu"


def test_biten_seri_aday_degil(repo, ders):
    """series_end_utc pencereden önceyse etkinlik hiç açılmaz."""
    repo.add_event(
        _event(
            ders,
            start=ist(2021, 9, 14, 9, 0),
            end=ist(2021, 9, 14, 10, 0),
            rrule="FREQ=WEEKLY;BYDAY=TU;UNTIL=20211231T060000Z",
        )
    )
    assert repo.occurrences(ist(2024, 5, 6), ist(2024, 5, 13)) == []


def test_tekrarsiz_etkinlik_pencereye_gore_elenir(repo, ders):
    """Tek seferlik etkinlikler yalnızca kesiştikleri pencerede döner."""
    repo.add_event(_event(ders, start=ist(2024, 5, 8, 10, 0), end=ist(2024, 5, 8, 11, 0)))

    assert len(repo.occurrences(ist(2024, 5, 6), ist(2024, 5, 13))) == 1
    assert repo.occurrences(ist(2024, 5, 13), ist(2024, 5, 20)) == []


def test_gizli_takvim_varsayilan_olarak_haric(repo):
    """Görünürlük kontrolü sorgu seviyesinde."""
    gizli = repo.add_calendar("Gizli", "#333", visible=False)
    repo.add_event(_event(gizli))

    pencere = (ist(2024, 5, 6), ist(2024, 5, 13))
    assert repo.occurrences(*pencere) == []
    assert len(repo.occurrences(*pencere, include_hidden=True)) == 1


def test_calendar_ids_filtresi(repo, ders):
    """Yalnızca istenen takvimler döner."""
    kisisel = repo.add_calendar("Kişisel", "#2980b9")
    repo.add_event(_event(ders, title="Ders"))
    repo.add_event(_event(kisisel, title="Spor"))

    pencere = (ist(2024, 5, 6), ist(2024, 5, 13))
    assert len(repo.occurrences(*pencere)) == 2
    assert [o.title for o in repo.occurrences(*pencere, calendar_ids=[ders.id])] == ["Ders"]
    assert repo.occurrences(*pencere, calendar_ids=[]) == []


def test_occurrences_sirali(repo, ders):
    """Farklı etkinliklerden gelen örnekler birlikte sıralanır."""
    repo.add_event(_event(ders, start=ist(2024, 5, 8, 14, 0), end=ist(2024, 5, 8, 15, 0), title="Geç"))
    repo.add_event(_event(ders, start=ist(2024, 5, 8, 9, 0), end=ist(2024, 5, 8, 10, 0), title="Erken"))

    bulunan = repo.occurrences(ist(2024, 5, 6), ist(2024, 5, 13))
    assert [o.title for o in bulunan] == ["Erken", "Geç"]


# ---------------------------------------------------------------------------
# Override kalıcılığı
# ---------------------------------------------------------------------------

def test_iptal_edilen_ornek_sorguda_yok(repo, ders):
    """cancelled override DB'den okunup expand'e uygulanıyor."""
    event = repo.add_event(
        _event(ders, start=ist(2024, 5, 6, 10, 0), end=ist(2024, 5, 6, 11, 0), rrule="FREQ=DAILY")
    )
    repo.cancel_occurrence(event.id, ist(2024, 5, 8, 10, 0))

    bulunan = repo.occurrences(ist(2024, 5, 6), ist(2024, 5, 13))
    gunler = {to_local(o.start_utc, IST).day for o in bulunan}

    assert len(bulunan) == 6
    assert 8 not in gunler


def test_move_occurrence_bitisi_hesaplayip_yazar(repo, ders):
    """new_end_utc verilmezse süreden hesaplanıp DB'ye YAZILIR.

    Aday sorgusu override'ın kapladığı aralığı SQL'de bilebilsin diye; aksi
    hâlde COALESCE ile tahmin yürütmek gerekirdi.
    """
    event = repo.add_event(
        _event(ders, start=ist(2024, 5, 6, 10, 0), end=ist(2024, 5, 6, 11, 0), rrule="FREQ=DAILY")
    )
    repo.move_occurrence(event.id, ist(2024, 5, 8, 10, 0), ist(2024, 5, 8, 15, 0))

    kayit = repo.list_overrides(event.id)[0]
    assert kayit.new_end_utc == ist(2024, 5, 8, 16, 0)

    tasinan = [o for o in repo.occurrences(ist(2024, 5, 6), ist(2024, 5, 13)) if o.is_override]
    assert len(tasinan) == 1
    assert tasinan[0].duration == timedelta(hours=1)


def test_put_override_ayni_ornegi_gunceller(repo, ders):
    """Aynı (event_id, original_start) için ikinci yazım ekleme değil güncelleme."""
    event = repo.add_event(_event(ders, rrule="FREQ=DAILY"))
    hedef = ist(2024, 5, 8, 10, 0)

    repo.cancel_occurrence(event.id, hedef)
    repo.move_occurrence(event.id, hedef, ist(2024, 5, 8, 16, 0))

    kayitlar = repo.list_overrides(event.id)
    assert len(kayitlar) == 1
    assert kayitlar[0].cancelled is False
    assert kayitlar[0].new_start_utc == ist(2024, 5, 8, 16, 0)


def test_override_silinince_ornek_seriye_doner(repo, ders):
    """delete_override sonrası örnek yeniden görünür."""
    event = repo.add_event(
        _event(ders, start=ist(2024, 5, 6, 10, 0), end=ist(2024, 5, 6, 11, 0), rrule="FREQ=DAILY")
    )
    hedef = ist(2024, 5, 8, 10, 0)
    repo.cancel_occurrence(event.id, hedef)
    assert len(repo.occurrences(ist(2024, 5, 6), ist(2024, 5, 13))) == 6

    repo.delete_override(event.id, hedef)
    assert len(repo.occurrences(ist(2024, 5, 6), ist(2024, 5, 13))) == 7


def test_biten_seriden_pencereye_tasinan_ornek_bulunur(repo, ders):
    """Serisi 2023'te bitmiş bir etkinliğin örneği 2024'e taşınmışsa bulunmalı.

    Aday sorgusu yalnızca seri sınırlarına baksaydı bu etkinlik hiç açılmazdı;
    override tablosunu da tarayan ikinci sorgunun sebebi bu.
    """
    event = repo.add_event(
        _event(
            ders,
            start=ist(2023, 1, 3, 9, 0),  # Salı
            end=ist(2023, 1, 3, 10, 0),
            rrule="FREQ=WEEKLY;BYDAY=TU;UNTIL=20230630T060000Z",
            title="Telafi",
        )
    )
    repo.move_occurrence(event.id, ist(2023, 6, 27, 9, 0), ist(2024, 5, 8, 14, 0))

    bulunan = repo.occurrences(ist(2024, 5, 6), ist(2024, 5, 13))

    assert len(bulunan) == 1
    assert bulunan[0].is_override is True
    assert to_local(bulunan[0].start_utc, IST).strftime("%Y-%m-%d %H:%M") == "2024-05-08 14:00"


def test_seriye_ait_olmayan_override_yok_sayilir(repo, ders):
    """DB'de duran hayalet override ekrana örnek basmaz."""
    event = repo.add_event(
        _event(
            ders,
            start=ist(2023, 1, 3, 9, 0),
            end=ist(2023, 1, 3, 10, 0),
            rrule="FREQ=WEEKLY;BYDAY=TU;UNTIL=20230630T060000Z",
        )
    )
    # 09:30 diye bir örnek serinin içinde yok
    repo.put_override(
        Override(
            event_id=event.id,
            original_start_utc=ist(2023, 6, 27, 9, 30),
            new_start_utc=ist(2024, 5, 8, 14, 0),
            new_end_utc=ist(2024, 5, 8, 15, 0),
        )
    )
    assert repo.occurrences(ist(2024, 5, 6), ist(2024, 5, 13)) == []


# ---------------------------------------------------------------------------
# Depolama biçimi
# ---------------------------------------------------------------------------

def test_zaman_metni_sabit_genislikte(repo, ders):
    """Sözlük sırası kronolojik sırayla örtüşmeli; mikrosaniye yazılmaz."""
    event = repo.add_event(_event(ders))
    raw = repo.conn.execute(
        "SELECT start_utc, end_utc FROM events WHERE id = ?", (event.id,)
    ).fetchone()

    assert raw["start_utc"] == "2024-05-06T07:00:00Z"
    assert len(raw["start_utc"]) == len(raw["end_utc"]) == 20
    assert raw["start_utc"] < raw["end_utc"]
