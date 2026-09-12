"""Faz 0 kabul kriteri 12 ve çakışma tespiti."""

from __future__ import annotations

from datetime import time

from core import conflicts, free_slots, overlaps, to_local
from tests.helpers import IST, ist, make_occ


def _yerel(slots):
    """Slot listesini okunur '09:00-12:00' metinlerine çevirir."""
    return [
        f"{to_local(a, IST):%H:%M}-{to_local(b, IST):%H:%M}" for a, b in slots
    ]


# ---------------------------------------------------------------------------
# overlaps / conflicts
# ---------------------------------------------------------------------------

def test_overlaps_yari_acik():
    """Uç uca gelen etkinlikler çakışmaz."""
    a = make_occ(ist(2024, 5, 6, 10, 0), ist(2024, 5, 6, 11, 0), uid="a")
    b = make_occ(ist(2024, 5, 6, 11, 0), ist(2024, 5, 6, 12, 0), uid="b")
    c = make_occ(ist(2024, 5, 6, 10, 30), ist(2024, 5, 6, 11, 30), uid="c")

    assert overlaps(a, b) is False
    assert overlaps(a, c) is True
    assert overlaps(c, a) is True, "Simetrik olmalı"


def test_conflicts_tum_ciftleri_bulur():
    """Üçlü tam çakışmada 3 çift döner."""
    occs = [
        make_occ(ist(2024, 5, 6, 10, 0), ist(2024, 5, 6, 11, 0), uid=f"e{i}")
        for i in range(3)
    ]
    ciftler = conflicts(occs)

    assert len(ciftler) == 3
    assert all(overlaps(a, b) for a, b in ciftler)


def test_conflicts_cakismayanlari_dondurmez():
    """Peş peşe gelen etkinlikler çakışma sayılmaz."""
    occs = [
        make_occ(ist(2024, 5, 6, 9 + i, 0), ist(2024, 5, 6, 10 + i, 0), uid=f"e{i}")
        for i in range(4)
    ]
    assert conflicts(occs) == []


# ---------------------------------------------------------------------------
# 12. free_slots
# ---------------------------------------------------------------------------

def test_free_slots_tek_etkinlikli_gun():
    """12:00-13:00 etkinliği olan günde önce ve sonra iki slot kalır."""
    occs = [make_occ(ist(2024, 5, 6, 12, 0), ist(2024, 5, 6, 13, 0), uid="a")]
    slots = free_slots(occs, time(9, 0), time(17, 0), 30, IST)

    assert _yerel(slots) == ["09:00-12:00", "13:00-17:00"]


def test_free_slots_min_sureden_kisa_araligi_atar():
    """İki etkinlik arasındaki 15 dakika, min_minutes=30 ile slot sayılmaz."""
    occs = [
        make_occ(ist(2024, 5, 6, 9, 0), ist(2024, 5, 6, 12, 0), uid="a"),
        make_occ(ist(2024, 5, 6, 12, 15), ist(2024, 5, 6, 17, 0), uid="b"),
    ]
    assert free_slots(occs, time(9, 0), time(17, 0), 30, IST) == []

    gevsek = free_slots(occs, time(9, 0), time(17, 0), 15, IST)
    assert _yerel(gevsek) == ["12:00-12:15"]


def test_free_slots_all_day_mesgul_saymaz():
    """Tüm gün etkinliği günü kapatmaz; sadece saatli olan meşgul eder."""
    occs = [
        make_occ(ist(2024, 5, 6), ist(2024, 5, 7), uid="dogum-gunu", all_day=True),
        make_occ(ist(2024, 5, 6, 12, 0), ist(2024, 5, 6, 13, 0), uid="a"),
    ]
    slots = free_slots(occs, time(9, 0), time(17, 0), 30, IST)

    assert _yerel(slots) == ["09:00-12:00", "13:00-17:00"]


def test_free_slots_cakisan_etkinlikleri_birlestirir():
    """Üst üste binen meşgul aralıklar tek blok sayılır."""
    occs = [
        make_occ(ist(2024, 5, 6, 10, 0), ist(2024, 5, 6, 12, 0), uid="a"),
        make_occ(ist(2024, 5, 6, 11, 0), ist(2024, 5, 6, 13, 0), uid="b"),
    ]
    slots = free_slots(occs, time(9, 0), time(17, 0), 30, IST)

    assert _yerel(slots) == ["09:00-10:00", "13:00-17:00"]


def test_free_slots_gun_penceresi_disini_kirpar():
    """07:00-10:00 etkinliği gün penceresine (09:00-) kırpılır."""
    occs = [make_occ(ist(2024, 5, 6, 7, 0), ist(2024, 5, 6, 10, 0), uid="a")]
    slots = free_slots(occs, time(9, 0), time(17, 0), 30, IST)

    assert _yerel(slots) == ["10:00-17:00"]


def test_free_slots_bos_girdi():
    """Meşgul örnek yoksa hangi güne bakacağımızı bilemeyiz: boş liste."""
    assert free_slots([], time(9, 0), time(17, 0), 30, IST) == []
