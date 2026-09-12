"""Faz 3: hafta görünümü veri hazırlığı.

Hepsi HTTP'siz: `week_payload` düz sözlük döndürdüğü için sunucuyu ayağa
kaldırmadan test edilebiliyor.
"""

from __future__ import annotations

from datetime import date

import pytest

from core import Event
from store import Repo, new_uid
from tests.helpers import IST, NY, ist, ny
from ui.presenter import day_bounds, week_bounds, week_payload, week_start


@pytest.fixture
def repo():
    """Bellekte taze DB."""
    with Repo.open(":memory:") as r:
        yield r


@pytest.fixture
def ders(repo):
    """Görünür varsayılan takvim."""
    return repo.add_calendar("Ders", "#e0524a")


def _ekle(repo, takvim, baslik, start, end, *, tzid=IST, all_day=False, rrule=None):
    """Kısa Event kurucusu."""
    return repo.add_event(
        Event(
            id=None,
            uid=new_uid(),
            calendar_id=takvim.id,
            title=baslik,
            start_utc=start,
            end_utc=end,
            tzid=tzid,
            all_day=all_day,
            rrule=rrule,
        )
    )


def _gun(payload, tarih: str) -> dict:
    """Payload içinden bir günü seçer."""
    return next(g for g in payload["days"] if g["date"] == tarih)


# ---------------------------------------------------------------------------
# Hafta sınırları
# ---------------------------------------------------------------------------

def test_hafta_pazartesiden_baslar():
    """Haftanın herhangi bir günü aynı pazartesiye çözülür."""
    assert week_start(date(2024, 5, 8)) == date(2024, 5, 6)   # Çarşamba
    assert week_start(date(2024, 5, 6)) == date(2024, 5, 6)   # Pazartesi
    assert week_start(date(2024, 5, 12)) == date(2024, 5, 6)  # Pazar


def test_gun_siniri_dst_gununde_24_saat_degil():
    """DST geçiş gününde gün 23 saat sürer; sınır 'başlangıç + 24s' değil.

    10 Mart 2024, America/New_York: saatler ileri alınıyor.
    """
    from core import UTC

    baslangic, bitis = day_bounds(date(2024, 3, 10), NY)
    # UTC'ye çevirmeden çıkarma YAPMA: CPython aynı tzinfo nesnesine sahip iki
    # aware datetime'ı çıkarırken ofsetleri uygulamıyor ve 24 saat döndürüyor.
    gercek = (bitis.astimezone(UTC) - baslangic.astimezone(UTC)).total_seconds()
    assert gercek == 23 * 3600
    assert (bitis - baslangic).total_seconds() == 24 * 3600, "tuzağın kendisi"

    # İstanbul'da DST yok, gün 24 saat
    baslangic, bitis = day_bounds(date(2024, 3, 10), IST)
    gercek = (bitis.astimezone(UTC) - baslangic.astimezone(UTC)).total_seconds()
    assert gercek == 24 * 3600


def test_hafta_sinirlari_yedi_gun_kapsar():
    """Pencere pazartesi 00:00'dan ertesi pazartesi 00:00'a."""
    baslangic, bitis = week_bounds(date(2024, 5, 8), IST)
    assert baslangic == ist(2024, 5, 6)
    assert bitis == ist(2024, 5, 13)


# ---------------------------------------------------------------------------
# Payload yapısı
# ---------------------------------------------------------------------------

def test_payload_yedi_gun_dondurur(repo, ders):
    """Her hafta tam 7 gün, pazartesiden pazara."""
    payload = week_payload(repo, date(2024, 5, 8), IST)

    assert len(payload["days"]) == 7
    assert payload["days"][0]["date"] == "2024-05-06"
    assert payload["days"][6]["date"] == "2024-05-12"
    assert payload["days"][0]["dayName"] == "Pzt"
    assert payload["weekStart"] == "2024-05-06"


def test_dakika_alanlari_gun_basindan_sayilir(repo, ders):
    """startMin/endMin yerel gün başlangıcına göre."""
    _ekle(repo, ders, "Ders", ist(2024, 5, 6, 9, 30), ist(2024, 5, 6, 11, 0))
    payload = week_payload(repo, date(2024, 5, 6), IST)

    occ = _gun(payload, "2024-05-06")["timed"][0]
    assert occ["startMin"] == 9 * 60 + 30
    assert occ["endMin"] == 11 * 60
    assert _gun(payload, "2024-05-06")["dayMinutes"] == 24 * 60


def test_dst_gununde_dayminutes_farkli(repo):
    """DST gününde dayMinutes 1380; ön yüz yüzdeleri buna böler."""
    takvim = repo.add_calendar("NY", "#111")
    _ekle(repo, takvim, "Standup", ny(2024, 3, 10, 9, 0), ny(2024, 3, 10, 10, 0), tzid=NY)
    payload = week_payload(repo, date(2024, 3, 10), NY)

    gun = _gun(payload, "2024-03-10")
    assert gun["dayMinutes"] == 23 * 60


# ---------------------------------------------------------------------------
# Tüm gün / saatli ayrımı
# ---------------------------------------------------------------------------

def test_tumgun_ayri_seride(repo, ders):
    """Tüm gün etkinliği ızgaraya değil üst şeride gider."""
    _ekle(repo, ders, "Tatil", ist(2024, 5, 8), ist(2024, 5, 10), all_day=True)
    payload = week_payload(repo, date(2024, 5, 6), IST)

    assert [o["title"] for o in _gun(payload, "2024-05-08")["allDay"]] == ["Tatil"]
    assert _gun(payload, "2024-05-08")["timed"] == []
    assert _gun(payload, "2024-05-09")["allDay"], "ikinci günde de görünmeli"
    assert _gun(payload, "2024-05-10")["allDay"] == [], "bitiş günü dışlayıcı"


# ---------------------------------------------------------------------------
# Gece yarısını aşan etkinlik
# ---------------------------------------------------------------------------

def test_gece_yarisini_asan_iki_gunde_kirpilir(repo, ders):
    """23:00-01:00 iki günde görünür, her günde yalnızca o güne düşen parçasıyla.

    Panelin doğru saati gösterebilmesi için startUtc/endUtc GERÇEK sınırları
    taşımaya devam eder; yalnızca startMin/endMin kırpılır.
    """
    _ekle(repo, ders, "Nöbet", ist(2024, 5, 6, 23, 0), ist(2024, 5, 7, 1, 0))
    payload = week_payload(repo, date(2024, 5, 6), IST)

    ilk = _gun(payload, "2024-05-06")["timed"][0]
    ikinci = _gun(payload, "2024-05-07")["timed"][0]

    assert ilk["startMin"] == 23 * 60
    assert ilk["endMin"] == 24 * 60, "ilk gün gece yarısında kesilmeli"
    assert ikinci["startMin"] == 0
    assert ikinci["endMin"] == 60, "ikinci gün gece yarısında başlamalı"

    # Gerçek sınırlar korunuyor
    assert ilk["startUtc"] == ikinci["startUtc"]
    assert ilk["clipped"] is True and ikinci["clipped"] is True


def test_gun_icindeki_etkinlik_kirpilmis_isaretlenmez(repo, ders):
    """Tamamen gün içindeki etkinlikte clipped=False."""
    _ekle(repo, ders, "Ders", ist(2024, 5, 6, 9, 0), ist(2024, 5, 6, 10, 0))
    payload = week_payload(repo, date(2024, 5, 6), IST)

    assert _gun(payload, "2024-05-06")["timed"][0]["clipped"] is False


# ---------------------------------------------------------------------------
# Kolon yerleşimi
# ---------------------------------------------------------------------------

def test_cakisan_etkinlikler_kolonlara_dagilir(repo, ders):
    """core.layout() sonucu payload'a col/colCount olarak geçer."""
    _ekle(repo, ders, "A", ist(2024, 5, 6, 10, 0), ist(2024, 5, 6, 12, 0))
    _ekle(repo, ders, "B", ist(2024, 5, 6, 10, 30), ist(2024, 5, 6, 11, 30))
    payload = week_payload(repo, date(2024, 5, 6), IST)

    bloklar = {o["title"]: (o["col"], o["colCount"]) for o in _gun(payload, "2024-05-06")["timed"]}
    assert bloklar == {"A": (0, 2), "B": (1, 2)}


def test_gece_yarisini_asan_ertesi_gunu_daraltmaz(repo, ders):
    """Kırpma layout'tan ÖNCE yapılır.

    Dünden sarkan 23:00-01:00 ile bugün 09:00'daki ders çakışmıyor; kırpma
    yapılmasaydı ikisi aynı cluster'a düşüp sabahı yarım genişliğe indirirdi.
    """
    _ekle(repo, ders, "Nöbet", ist(2024, 5, 6, 23, 0), ist(2024, 5, 7, 1, 0))
    _ekle(repo, ders, "Sabah dersi", ist(2024, 5, 7, 9, 0), ist(2024, 5, 7, 10, 0))
    payload = week_payload(repo, date(2024, 5, 6), IST)

    ikinci_gun = {o["title"]: o["colCount"] for o in _gun(payload, "2024-05-07")["timed"]}
    assert ikinci_gun == {"Nöbet": 1, "Sabah dersi": 1}


# ---------------------------------------------------------------------------
# Takvim görünürlüğü ve renk
# ---------------------------------------------------------------------------

def test_gizli_takvim_varsayilan_olarak_yok(repo, ders):
    """Gizli takvimin etkinliği payload'a girmez ama takvim listesinde durur."""
    gizli = repo.add_calendar("Arşiv", "#666", visible=False)
    _ekle(repo, gizli, "Eski", ist(2024, 5, 6, 9, 0), ist(2024, 5, 6, 10, 0))
    payload = week_payload(repo, date(2024, 5, 6), IST)

    assert _gun(payload, "2024-05-06")["timed"] == []
    assert {c["name"] for c in payload["calendars"]} == {"Ders", "Arşiv"}

    dahil = week_payload(repo, date(2024, 5, 6), IST, include_hidden=True)
    assert len(_gun(dahil, "2024-05-06")["timed"]) == 1


def test_renk_takvimden_gelir(repo, ders):
    """Her blok kendi takviminin rengini taşır."""
    _ekle(repo, ders, "Ders", ist(2024, 5, 6, 9, 0), ist(2024, 5, 6, 10, 0))
    payload = week_payload(repo, date(2024, 5, 6), IST)

    assert _gun(payload, "2024-05-06")["timed"][0]["color"] == "#e0524a"


# ---------------------------------------------------------------------------
# Tekrar ve override
# ---------------------------------------------------------------------------

def test_haftalik_seri_dogru_gune_dusor(repo, ders):
    """2021'de başlayan seri 2024 haftasında görünür (store'un iki parçalı sorgusu)."""
    _ekle(
        repo, ders, "Algoritma",
        ist(2021, 9, 14, 9, 0), ist(2021, 9, 14, 11, 0),
        rrule="FREQ=WEEKLY;BYDAY=TU",
    )
    payload = week_payload(repo, date(2024, 5, 6), IST)

    assert [o["title"] for o in _gun(payload, "2024-05-07")["timed"]] == ["Algoritma"]
    assert _gun(payload, "2024-05-06")["timed"] == []


def test_override_isaretlenir(repo, ders):
    """Kaydırılan örnek isOverride=True ile gelir; panel rozeti buna bakıyor."""
    event = _ekle(
        repo, ders, "Ders", ist(2024, 5, 6, 9, 0), ist(2024, 5, 6, 10, 0), rrule="FREQ=DAILY"
    )
    repo.move_occurrence(event.id, ist(2024, 5, 8, 9, 0), ist(2024, 5, 8, 15, 0))
    payload = week_payload(repo, date(2024, 5, 6), IST)

    tasinan = _gun(payload, "2024-05-08")["timed"][0]
    assert tasinan["isOverride"] is True
    assert tasinan["startMin"] == 15 * 60


# ---------------------------------------------------------------------------
# Başlık
# ---------------------------------------------------------------------------

def test_hafta_etiketi_ay_icinde():
    """Aynı ay: '6 - 12 Mayıs 2024'."""
    from ui.presenter import _hafta_etiketi

    assert _hafta_etiketi(date(2024, 5, 6)) == "6 - 12 Mayıs 2024"


def test_hafta_etiketi_ay_asarken():
    """Ay sınırında iki ay da yazılır."""
    from ui.presenter import _hafta_etiketi

    assert _hafta_etiketi(date(2024, 4, 29)) == "29 Nisan - 5 Mayıs 2024"


def test_hafta_etiketi_yil_asarken():
    """Yıl sınırında iki yıl da yazılır."""
    from ui.presenter import _hafta_etiketi

    assert _hafta_etiketi(date(2024, 12, 30)) == "30 Aralık 2024 - 5 Ocak 2025"
