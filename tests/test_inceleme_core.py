"""Kod incelemesi bulguları (core/ + senkron/ice.py): her hata için bir regresyon testi."""

from __future__ import annotations

from datetime import time, timedelta

import pytest

from core import Event, Override, expand, free_slots, to_local
from core.quickadd import parse_quick_add
from senkron import SenkronHatasi, durum_uret, ice_aktar, json_metni
from store import Repo
from tests.helpers import IST, NY, ist, make_event, make_occ, ny

SIMDI = ist(2026, 11, 10, 9, 0)


def _coz(metin: str):
    return parse_quick_add(metin, now=SIMDI, tzid=IST)


def _yerel(an) -> str:
    return to_local(an, IST).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# 1) "1.5 saat" süredir, tarih değil
# ---------------------------------------------------------------------------

def test_ondalikli_sure_tarih_sanilmaz():
    r = _coz("toplantı 14:00 1.5 saat")
    assert r.all_day is False
    assert r.title == "toplantı"
    assert _yerel(r.start_utc) == "2026-11-10 14:00"
    assert r.end_utc - r.start_utc == timedelta(minutes=90)


def test_ondalikli_sure_tek_basina_tum_gun_kalir():
    r = _coz("2.5 saat çalış")
    assert r.all_day is True
    assert r.title == "çalış"
    assert _yerel(r.start_utc).startswith("2026-11-10")


def test_ondalikli_sure_gercek_tarihi_bozmaz():
    r = _coz("1.5 saat toplantı 15.12.2026 14:00")
    assert _yerel(r.start_utc) == "2026-12-15 14:00"
    assert r.end_utc - r.start_utc == timedelta(minutes=90)


# ---------------------------------------------------------------------------
# 2) İşaretsiz çıplak sayı çifti saat aralığı değildir
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "metin, baslik",
    [
        ("5-10 sayfa oku", "5-10 sayfa oku"),
        ("3 ile 5 kişi görüşme", "3 ile 5 kişi görüşme"),
        ("kitap 10-12. bölüm", "kitap 10-12. bölüm"),
    ],
)
def test_cıplak_sayi_araligi_saat_degil(metin, baslik):
    r = _coz(metin)
    assert r.all_day is True
    assert r.matched == ""
    assert r.title == baslik


@pytest.mark.parametrize(
    "metin, bas, bit",
    [
        ("10-12 arası toplantı", "10:00", "12:00"),
        ("yarın 10:00-12 toplantı", "10:00", "12:00"),
        ("saat 9-10 toplantı", "09:00", "10:00"),
        ("9'da-10 toplantı", "09:00", "10:00"),
        ("15:30-17:00 toplantı", "15:30", "17:00"),
    ],
)
def test_isaretli_aralik_calismaya_devam_eder(metin, bas, bit):
    r = _coz(metin)
    assert r.all_day is False
    assert _yerel(r.start_utc)[-5:] == bas
    assert _yerel(r.end_utc)[-5:] == bit


# ---------------------------------------------------------------------------
# 3) Tekrarlı tüm gün etkinlik DST'de ertesi güne taşmaz
# ---------------------------------------------------------------------------

def _gunluk_tum_gun():
    return make_event(
        ny(2026, 3, 1), ny(2026, 3, 2), tzid=NY, rrule="FREQ=DAILY", all_day=True
    )


def test_tum_gun_seri_ilkbahar_gecisinde_gun_sinirinda_biter():
    ev = _gunluk_tum_gun()
    sonuc = expand(ev, [], ny(2026, 3, 8), ny(2026, 3, 9))
    assert len(sonuc) == 1
    assert sonuc[0].end_utc == ny(2026, 3, 9)  # 23 saat sonra, 9 Mart 00:00 EDT


def test_tum_gun_seri_ertesi_gun_penceresinde_cift_gorunmez():
    ev = _gunluk_tum_gun()
    sonuc = expand(ev, [], ny(2026, 3, 9), ny(2026, 3, 10))
    assert [o.start_utc for o in sonuc] == [ny(2026, 3, 9)]


def test_tum_gun_seri_sonbahar_gecisinde_gunu_doldurur():
    ev = _gunluk_tum_gun()
    sonuc = expand(ev, [], ny(2026, 11, 1), ny(2026, 11, 2))
    assert sonuc[0].end_utc == ny(2026, 11, 2)  # 25 saatlik gün


# ---------------------------------------------------------------------------
# 4) Yalnız new_end_utc'li, orijinalden önce biten override
# ---------------------------------------------------------------------------

def test_override_yalniz_bitis_orijinalden_once_reddedilir():
    s = ist(2026, 11, 10, 9)
    with pytest.raises(ValueError):
        Override(1, s + timedelta(days=1), new_end_utc=s)


def test_override_yalniz_bitis_gecerliyse_kabul_ve_iptalde_atlanir():
    s = ist(2026, 11, 10, 9)
    Override(1, s, new_end_utc=s + timedelta(hours=2))
    Override(1, s + timedelta(days=1), cancelled=True, new_end_utc=s)  # iptal: bakılmaz


def test_senkron_dosyasinda_bozuk_override_bozuk_dosya_hatasi_verir():
    with Repo.open(":memory:") as a, Repo.open(":memory:") as b:
        k = a.add_calendar("Kişisel", "#3b82f6")
        a.add_event(Event(
            id=None, uid="seri", calendar_id=k.id, title="Seri", tzid=IST,
            start_utc=ist(2026, 11, 3, 10), end_utc=ist(2026, 11, 3, 11),
            rrule="FREQ=DAILY",
        ))
        d = durum_uret(a, cihaz_id="x", cihaz_adi="x", uygulama="test")
        d["events"][0]["overrides"] = [{
            "original_start_utc": "2026-11-05T07:00:00Z", "cancelled": False,
            "new_start_utc": None, "new_end_utc": "2026-11-04T07:00:00Z",
            "new_title": None, "new_location": None,
        }]
        with pytest.raises(SenkronHatasi) as hata:
            ice_aktar(b, json_metni(d))
        assert hata.value.kod == "senkron_bozuk"
        assert b.get_event_by_uid("seri") is None


# ---------------------------------------------------------------------------
# 5) free_slots DST gününde gerçek süreyle ölçer
# ---------------------------------------------------------------------------

def _dst_gunu_olusumlari():
    return [
        make_occ(ny(2026, 3, 8, 0), ny(2026, 3, 8, 1), tzid=NY, uid="a"),
        make_occ(ny(2026, 3, 8, 4), ny(2026, 3, 8, 5), tzid=NY, uid="b"),
    ]


def test_free_slots_ilkbahar_boslugu_gercek_sureyle_elenir():
    # 01:00 EST - 04:00 EDT arası gerçekte 2 saat; duvar farkı 3 saat.
    slots = free_slots(_dst_gunu_olusumlari(), time(0, 0), time(5, 0), 150, NY)
    assert slots == []


def test_free_slots_ilkbahar_boslugu_yeterliyse_kalir():
    slots = free_slots(_dst_gunu_olusumlari(), time(0, 0), time(5, 0), 120, NY)
    assert len(slots) == 1
    assert slots[0][0] == ny(2026, 3, 8, 1) and slots[0][1] == ny(2026, 3, 8, 4)
