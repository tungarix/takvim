"""Kod incelemesi bulguları: bildirim kaçırma (19) ve tüm gün seri dışa aktarma (20)."""

from __future__ import annotations

from datetime import datetime

import pytest

from core import UTC, Event, to_local
from ics import export_repo, import_ics
from remind.notifier import _ps_kacir
from store import Repo, new_uid
from tests.helpers import IST, NY, ist

DTSTAMP = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
TIRNAKLAR = [chr(c) for c in (0x27, 0x2018, 0x2019, 0x201A, 0x201B)]


@pytest.mark.parametrize("tirnak", TIRNAKLAR)
def test_ps_kacir_tum_tirnak_benzerlerini_ikiye_katlar(tirnak):
    """Bulgu 19: tipografik kesme işareti PowerShell dizesini kapatamaz."""
    assert _ps_kacir(f"Ali{tirnak}nin") == f"Ali{tirnak}{tirnak}nin"


def test_ps_kacir_enjeksiyon_dizesi_tirnaksiz_kalmaz():
    """Kötü niyetli başlıktaki her tırnak çift: tek başına tırnak kalmamalı."""
    sonuc = _ps_kacir(f"x{chr(0x2019)}; Remove-Item *; {chr(0x2018)}y")
    for tirnak in TIRNAKLAR[1:]:
        assert sonuc.count(tirnak) % 2 == 0


def test_ps_kacir_xml_gecersiz_kontrol_karakterlerini_ayiklar():
    """Bulgu 19: XML'de geçersiz karakter LoadXml'i patlatıp hatırlatıcıyı kaybettirir."""
    assert _ps_kacir("a\x00b\x0bc\x1fd￾e") == "abcde"
    assert _ps_kacir("a\tb\nc\rd") == "a\tb\nc\rd"  # geçerli olanlar kalır


@pytest.fixture
def repo():
    """Bellekte taze DB."""
    with Repo.open(":memory:") as r:
        yield r


def _gunler(repo, tzid):
    """Pencere içindeki tüm gün örneklerinin yerel başlangıç günleri."""
    occs = repo.occurrences(ist(2026, 3, 1), ist(2026, 3, 20), include_hidden=True)
    return sorted(to_local(o.start_utc, tzid).strftime("%m-%d") for o in occs)


def _tum_gun_seri(repo):
    takvim = repo.add_calendar("Tatil", "#111")
    event = repo.add_event(
        Event(
            id=None, uid=new_uid(), calendar_id=takvim.id, title="Nöbet",
            start_utc=ist(2026, 3, 3), end_utc=ist(2026, 3, 4), tzid=IST, all_day=True,
            rrule="FREQ=DAILY;COUNT=7", exdate=(ist(2026, 3, 5),),
        )
    )
    repo.cancel_occurrence(event.id, ist(2026, 3, 4))
    repo.move_occurrence(event.id, ist(2026, 3, 6), ist(2026, 3, 8), ist(2026, 3, 9))
    return event


def test_tum_gun_seride_exdate_ve_recurrence_id_date_yazilir(repo):
    """Bulgu 20: DTSTART DATE ise EXDATE/RECURRENCE-ID/override DTSTART'ı da DATE olmalı."""
    _tum_gun_seri(repo)
    metin = export_repo(repo, dtstamp=DTSTAMP)

    assert "EXDATE;VALUE=DATE:20260305" in metin
    assert "RECURRENCE-ID;VALUE=DATE:20260304" in metin
    assert "RECURRENCE-ID;VALUE=DATE:20260306" in metin
    assert "T210000Z" not in metin  # hiçbir yerde UTC saat kalmamalı


@pytest.mark.parametrize("hedef_tzid", [IST, NY])
def test_tum_gun_seri_farkli_default_tzid_ile_gidis_donus(repo, hedef_tzid):
    """Bulgu 20: silinen/iptal/taşınan günler hangi default_tzid ile alınırsa alınsın aynı."""
    _tum_gun_seri(repo)
    beklenen = _gunler(repo, IST)
    # 3,7,8(taşınan 6'nın yeni yeri),9 ... : 4 iptal, 5 exdate, 6 taşındı
    assert beklenen == ["03-03", "03-07", "03-08", "03-08", "03-09"]
    metin = export_repo(repo, dtstamp=DTSTAMP)

    with Repo.open(":memory:") as yeni:
        hedef = yeni.add_calendar("İçe", "#222")
        rapor = import_ics(yeni, metin, calendar_id=hedef.id, default_tzid=hedef_tzid)
        assert rapor.errors == ()
        gelen = yeni.list_events()[0]
        assert gelen.tzid == hedef_tzid
        occs = yeni.occurrences(
            gelen.start_utc.replace(year=2026, month=2, day=25),
            gelen.start_utc.replace(year=2026, month=3, day=25),
            include_hidden=True,
        )
        gunler = sorted(to_local(o.start_utc, hedef_tzid).strftime("%m-%d") for o in occs)
        assert gunler == beklenen
