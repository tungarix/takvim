"""Günlük döndürme testleri (`takvim_app._dondur`).

Eskiden sınır aşılınca dosya siliniyordu; şimdi kaydırılıyor. `_gunluge_yonlendir`
yalnızca paketlenmiş `.exe`'de çalıştığı için dönen mantık ayrı fonksiyonda ve
doğrudan test ediliyor.
"""

from pathlib import Path

from takvim_app import _MAKS_GUNLUK, _dondur


def _sisir(yol: Path, bayt: int = _MAKS_GUNLUK + 1) -> Path:
    yol.write_bytes(b"x" * bayt)
    return yol


def test_kucuk_dosya_dondurulmez(tmp_path: Path) -> None:
    yol = tmp_path / "takvim.log"
    yol.write_bytes(b"kucuk")
    _dondur(yol)
    assert yol.read_bytes() == b"kucuk"
    assert not (tmp_path / "takvim.log.1").exists()


def test_olmayan_dosya_sessiz_gecer(tmp_path: Path) -> None:
    _dondur(tmp_path / "takvim.log")  # hata fırlatmamalı


def test_buyuk_dosya_bire_kayar(tmp_path: Path) -> None:
    yol = _sisir(tmp_path / "takvim.log")
    _dondur(yol)
    assert not yol.exists()  # yeni açılışta sıfırdan oluşturulacak
    assert (tmp_path / "takvim.log.1").stat().st_size == _MAKS_GUNLUK + 1


def test_zincir_kayar_en_eski_duser(tmp_path: Path) -> None:
    yol = _sisir(tmp_path / "takvim.log")
    (tmp_path / "takvim.log.1").write_bytes(b"eski1")
    (tmp_path / "takvim.log.2").write_bytes(b"eski2")
    _dondur(yol)
    assert (tmp_path / "takvim.log.1").stat().st_size == _MAKS_GUNLUK + 1
    assert (tmp_path / "takvim.log.2").read_bytes() == b"eski1"
    assert not (tmp_path / "takvim.log.3").exists()  # en eski düştü, iz 3 dosyada
