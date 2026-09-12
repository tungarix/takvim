"""Faz 0 kabul kriteri 11: kolon yerleşimi."""

from __future__ import annotations

from core import layout
from tests.helpers import ist, make_occ


def test_uclu_tam_cakisma_uc_kolon():
    """Aynı saatteki 3 etkinlik 3 ayrı kolona, hepsi kolon_sayısı=3 ile."""
    occs = [
        make_occ(ist(2024, 5, 6, 10, 0), ist(2024, 5, 6, 11, 0), uid=f"e{i}")
        for i in range(3)
    ]
    yerlesim = layout(occs)

    assert [(c, n) for _, c, n in yerlesim] == [(0, 3), (1, 3), (2, 3)]


def test_art_arda_gelen_iki_etkinlik_tek_kolon():
    """10-11 ve 11-12 çakışmaz: ikisi de tam genişlik (kolon_sayısı=1)."""
    occs = [
        make_occ(ist(2024, 5, 6, 10, 0), ist(2024, 5, 6, 11, 0), uid="a"),
        make_occ(ist(2024, 5, 6, 11, 0), ist(2024, 5, 6, 12, 0), uid="b"),
    ]
    yerlesim = layout(occs)

    assert [(o.uid, c, n) for o, c, n in yerlesim] == [("a", 0, 1), ("b", 0, 1)]


def test_kismi_cakisma_kolonu_yeniden_kullanir():
    """Kapanan kolon yeniden kullanılır; cluster genişliği gereksiz büyümez.

    A 10-12, B 10:30-11:30 (2 kolon), C 12-13 A ile de B ile de çakışmıyor
    ama cluster A'nın bitişine kadar sürdüğü için... aslında sürmüyor:
    C'nin başlangıcı cluster'ın maksimum bitişine eşit, yeni cluster açılır.
    """
    occs = [
        make_occ(ist(2024, 5, 6, 10, 0), ist(2024, 5, 6, 12, 0), uid="a"),
        make_occ(ist(2024, 5, 6, 10, 30), ist(2024, 5, 6, 11, 30), uid="b"),
        make_occ(ist(2024, 5, 6, 12, 0), ist(2024, 5, 6, 13, 0), uid="c"),
    ]
    yerlesim = {o.uid: (c, n) for o, c, n in layout(occs)}

    assert yerlesim["a"] == (0, 2)
    assert yerlesim["b"] == (1, 2)
    assert yerlesim["c"] == (0, 1), "Yeni cluster tam genişlik olmalı"


def test_zincirleme_cakisma_tek_cluster():
    """A-B çakışıyor, B-C çakışıyor, A-C çakışmıyor: üçü TEK cluster.

    C, A'nın kapattığı kolonu geri alır; bu yüzden 3 değil 2 kolon yeter.
    """
    occs = [
        make_occ(ist(2024, 5, 6, 10, 0), ist(2024, 5, 6, 11, 0), uid="a"),
        make_occ(ist(2024, 5, 6, 10, 30), ist(2024, 5, 6, 12, 0), uid="b"),
        make_occ(ist(2024, 5, 6, 11, 0), ist(2024, 5, 6, 11, 30), uid="c"),
    ]
    yerlesim = {o.uid: (c, n) for o, c, n in layout(occs)}

    assert yerlesim["a"] == (0, 2)
    assert yerlesim["b"] == (1, 2)
    assert yerlesim["c"] == (0, 2), "A'nın kolonu serbest kalmıştı"


def test_bos_liste():
    """Boş girdi boş çıktı."""
    assert layout([]) == []


def test_siralama_kararli():
    """Girdi sırası değişse de yerleşim aynı olmalı; ekran titremesin."""
    a = make_occ(ist(2024, 5, 6, 10, 0), ist(2024, 5, 6, 12, 0), uid="a")
    b = make_occ(ist(2024, 5, 6, 10, 0), ist(2024, 5, 6, 11, 0), uid="b")

    ileri = [(o.uid, c, n) for o, c, n in layout([a, b])]
    geri = [(o.uid, c, n) for o, c, n in layout([b, a])]

    assert ileri == geri
    assert ileri[0][0] == "a", "Eşit başlangıçta uzun olan önce gelir"


def test_tum_occurrencelar_dondurulur():
    """Hiçbir örnek yerleşimde kaybolmaz."""
    occs = [
        make_occ(ist(2024, 5, 6, 9 + i, 0), ist(2024, 5, 6, 10 + i, 0), uid=f"e{i}")
        for i in range(5)
    ]
    assert len(layout(occs)) == 5
