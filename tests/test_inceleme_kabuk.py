"""Kabuk incelemesi düzeltmeleri: Wi-Fi yanıt kopması, exe deneme betiği, tek örnek öne alma."""

from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import struct
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from senkron import durum_uret, json_metni
from senkron import wifi as wifi_modulu
from senkron.wifi import WifiOturumu, _Istek
from store import Repo
from ui import tek_ornek

KOK = Path(__file__).resolve().parent.parent


# -- Bulgu 21: yanıt yazımı koparsa oturum 'bitti' olmalı --------------------------------------


@pytest.fixture
def oturum(tmp_path):
    yol = str(tmp_path / "takvim.db")
    with Repo.open(yol) as repo:
        repo.add_calendar("Kişisel", "#3b82f6")

    @contextmanager
    def ac():
        repo = Repo.open(yol)
        try:
            yield repo
        finally:
            repo.close()

    o = WifiOturumu(
        ip="127.0.0.1", depo_ac=ac, cihaz_adi="Test PC", cihaz_id="cihaz-1",
        uygulama="desktop test", gunluk=lambda _m: None, test_ipleri=frozenset({"127.0.0.1"}),
    )
    o.baslat()
    yield o
    o.bitir("iptal")


class _KopanIstek(_Istek):
    """Yanıt yazımı her zaman kopan istek (`__init__` ağ gerektirir: atlanır)."""

    def __init__(self, oturum: WifiOturumu, govde: bytes = b"") -> None:
        self._o = oturum
        self.headers = {"Content-Length": str(len(govde))}
        self.rfile = SimpleNamespace(read=lambda n: govde)
        self.wfile = SimpleNamespace(closed=False)

    @property
    def _oturum(self) -> WifiOturumu:
        return self._o

    def _sayaci_durdur(self) -> None:
        pass

    def _yanit(self, kod, govde, ekler=None) -> None:
        raise BrokenPipeError("istemci gitti")


def _gecerli_govde(oturum: WifiOturumu) -> bytes:
    with oturum.depo_ac() as repo:
        return json_metni(durum_uret(repo, cihaz_id="tel", cihaz_adi="Tel", uygulama="t")).encode("utf-8")


def test_birlestirmede_200_yaniti_koparsa_oturum_biter(oturum):
    oturum.faz = "isleniyor"
    with pytest.raises(BrokenPipeError):
        _KopanIstek(oturum)._birlestir(_gecerli_govde(oturum))
    assert oturum.faz == "bitti" and oturum.sonuc == "birlestirildi"
    assert not oturum.yetkili_mi("Bearer " + oturum._token)


def test_birlestirmede_400_yaniti_koparsa_oturum_biter(oturum):
    oturum.faz = "isleniyor"
    with pytest.raises(BrokenPipeError):
        _KopanIstek(oturum)._birlestir(b"{}")
    assert oturum.faz == "bitti" and oturum.sonuc == "hata"


def test_birlestirmede_500_yaniti_koparsa_oturum_biter(oturum, monkeypatch):
    def patla(repo, govde):
        raise RuntimeError("beklenmeyen")

    monkeypatch.setattr(wifi_modulu, "ice_aktar", patla)
    oturum.faz = "isleniyor"
    with pytest.raises(BrokenPipeError):
        _KopanIstek(oturum)._birlestir(b"{}")
    assert oturum.faz == "bitti" and oturum.sonuc == "hata"


@pytest.mark.parametrize(("karar", "sonuc"), [("red", "reddedildi"), ("zaman", "zaman_asimi")])
def test_ret_ve_zaman_asimi_yaniti_koparsa_oturum_biter(oturum, monkeypatch, karar, sonuc):
    govde = _gecerli_govde(oturum)
    monkeypatch.setattr(oturum, "onay_iste", lambda ozet: karar)
    with pytest.raises(BrokenPipeError):
        _KopanIstek(oturum, govde)._durum_al()
    assert oturum.faz == "bitti" and oturum.sonuc == sonuc


# -- Bulgu 22: deneme betiği zorunlu --sha256'yı vermeli ----------------------------------------


def test_exe_denemesi_yeni_exe_ye_sha256_verir(tmp_path, monkeypatch):
    ozel = importlib.util.spec_from_file_location("exe_guncelleme_dene", KOK / "scripts" / "exe_guncelleme_dene.py")
    betik = importlib.util.module_from_spec(ozel)
    ozel.loader.exec_module(betik)

    exe = tmp_path / "Takvim.exe"
    baslik = bytearray(0x100)
    struct.pack_into("<I", baslik, 0x3C, 0x80)
    baslik[0x80:0x84] = b"PE\0\0"
    exe.write_bytes(bytes(baslik))

    cagrilar: list[tuple[list[str], bytes]] = []

    def sahte_popen(komut, **kw):
        cagrilar.append((komut, Path(komut[0]).read_bytes()))
        return SimpleNamespace(pid=1, poll=lambda: 0)

    monkeypatch.setattr(betik.subprocess, "Popen", sahte_popen)
    monkeypatch.setattr(betik.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=""))
    monkeypatch.setattr(betik, "_bekle", lambda *a, **k: True)
    monkeypatch.setattr(betik.time, "sleep", lambda s: None)
    monkeypatch.setattr(betik, "_yolla_calisan", lambda yol: [])
    monkeypatch.setattr(betik, "_yolu_oldur", lambda yol: None)

    betik.calistir(exe)

    komut, yeni_bayt = next((k, b) for k, b in cagrilar if "--guncelle-tamamla" in k)
    assert komut[komut.index("--sha256") + 1] == hashlib.sha256(yeni_bayt).hexdigest()


# -- Bulgu 23: büyütülmüş pencere ikinci tıkta küçülmemeli --------------------------------------


@pytest.mark.parametrize(("simge_durumunda", "restore_beklenir"), [(False, False), (True, True)])
def test_one_getir_yalniz_simge_durumundaysa_restore_eder(monkeypatch, simge_durumunda, restore_beklenir):
    cagrilar: list[int] = []
    user32 = SimpleNamespace(
        ShowWindow=lambda h, komut: cagrilar.append(komut),
        IsIconic=lambda h: 1 if simge_durumunda else 0,
        SetForegroundWindow=lambda h: 1,
        SwitchToThisWindow=lambda h, f: None,
    )
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32), raising=False)
    assert tek_ornek._one_getir(123) is True
    assert 5 in cagrilar  # SW_SHOW her durumda (tepsideki gizli pencere)
    assert (9 in cagrilar) is restore_beklenir
