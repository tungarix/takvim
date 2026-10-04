"""Hatırlatıcının dili: giriş noktaları dili ayar dosyasından HER TURDA okur.

Gerçek hata: paketlenmiş `.exe` (`takvim_app.py` hep `--reminder` ile açar)
hatırlatıcı thread'ine dil vermiyordu; kullanıcı Ayarlar'dan İngilizceyi seçse
de bildirimler Türkçe çıkıyordu. `remind/__main__.py` ise dili yalnızca
başlangıçta bir kez okuyordu.

Gerçek `ayarlar.json`a (`%LOCALAPPDATA%\\Takvim`) hiçbir test dokunmaz: her test
kendi `tmp_path`'ini kullanır.
"""

from __future__ import annotations

import json

import pytest

import remind
import remind.__main__ as remind_main
from remind.notifier import ConsoleNotifier
from tests.helpers import IST
from ui.__main__ import _dil_okuyucu, _hatirlatici_baslat


def _ayar_yaz(klasor, icerik) -> None:
    """`klasor/ayarlar.json`a ham içerik yazar (bozuk dosya da taklit edilebilsin)."""
    yol = klasor / "ayarlar.json"
    if isinstance(icerik, bytes):
        yol.write_bytes(icerik)
    elif isinstance(icerik, str):
        yol.write_text(icerik, encoding="utf-8")
    else:
        yol.write_text(json.dumps(icerik), encoding="utf-8")


# ---------------------------------------------------------------------------
# ui/__main__.py: _dil_okuyucu
# ---------------------------------------------------------------------------

def test_dil_okuyucu_ayarlarda_en_ise_en(tmp_path):
    """`ayarlar.json` "en" derken okuyucu "en" döner."""
    _ayar_yaz(tmp_path, {"dil": "en"})

    assert _dil_okuyucu(str(tmp_path / "takvim.db"))() == "en"


def test_dil_okuyucu_dosya_yoksa_tr(tmp_path):
    """Hiç ayar dosyası yoksa Türkçe (ayarsız açılış)."""
    assert _dil_okuyucu(str(tmp_path / "takvim.db"))() == "tr"


@pytest.mark.parametrize(
    "bozuk",
    [
        "bu json degil {",              # sözdizimi hatası
        "[1, 2, 3]",                    # geçerli JSON ama sözlük değil
        '{"dil": "de"}',                # kapalı kümenin dışında
        '{"dil": 5}',                   # yanlış tip
        b"\xff\xfe\x00 {\"dil\": \"en\"}",  # geçersiz UTF-8 baytları
    ],
)
def test_dil_okuyucu_bozuk_dosyada_tr(tmp_path, bozuk):
    """Bozuk ayar hatırlatıcı turunu patlatmaz, Türkçe döner."""
    _ayar_yaz(tmp_path, bozuk)

    assert _dil_okuyucu(str(tmp_path / "takvim.db"))() == "tr"


def test_dil_okuyucu_her_cagrida_dosyayi_yeniden_okur(tmp_path):
    """Uygulama açıkken dil değişirse okuyucu yeni değeri verir."""
    oku = _dil_okuyucu(str(tmp_path / "takvim.db"))
    _ayar_yaz(tmp_path, {"dil": "en"})
    assert oku() == "en"

    _ayar_yaz(tmp_path, {"dil": "tr"})
    assert oku() == "tr"

    _ayar_yaz(tmp_path, {"dil": "en"})
    assert oku() == "en"


def test_dil_okuyucu_bellek_db_sabit_tr():
    """`:memory:` için ayar klasörü yok; gerçek kullanıcı klasörüne bakılmaz."""
    assert _dil_okuyucu(":memory:")() == "tr"


# ---------------------------------------------------------------------------
# ui/__main__.py: _hatirlatici_baslat thread'i run_forever'a dili OKUYUCU olarak verir
# ---------------------------------------------------------------------------

def test_hatirlatici_baslat_dili_okuyucu_olarak_verir(tmp_path, monkeypatch):
    """Thread `run_forever`a sabit değil, her turda okuyan bir dil verir.

    Gerçek hatanın kendisi: eskiden `run_forever(repo, tzid, pick_notifier())`
    çağrılıyordu, dil hiç verilmiyordu. `run_forever` ve `pick_notifier`
    sahte; thread'in onlara ne verdiği ölçülüyor.
    """
    _ayar_yaz(tmp_path, {"dil": "en"})
    yakalanan: dict = {}

    def sahte_run_forever(repo, tzid, notifier, **kwargs):
        yakalanan["tzid"] = tzid
        yakalanan["notifier"] = notifier
        yakalanan["kwargs"] = kwargs

    def sahte_pick_notifier(tercih="auto", dil="tr"):
        yakalanan["pick_dil"] = dil
        return ConsoleNotifier()

    monkeypatch.setattr(remind, "run_forever", sahte_run_forever)
    monkeypatch.setattr(remind, "pick_notifier", sahte_pick_notifier)

    thread = _hatirlatici_baslat(str(tmp_path / "takvim.db"), IST)
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert yakalanan["tzid"] == IST
    assert yakalanan["pick_dil"] == "en", "Tk düğmesi başlangıç dilini almalı"
    dil = yakalanan["kwargs"]["dil"]
    assert callable(dil), "metin değil, her turda çağrılacak okuyucu verilmeli"
    assert dil() == "en"
    _ayar_yaz(tmp_path, {"dil": "tr"})
    assert dil() == "tr", "dosya değişince okuyucu yeni dili vermeli"


# ---------------------------------------------------------------------------
# remind/__main__.py: _dil_oku ve main
# ---------------------------------------------------------------------------

def test_remind_dil_oku_en(tmp_path):
    """`python -m remind` yerel okuyucusu da "en"i okuyor."""
    _ayar_yaz(tmp_path, {"dil": "en"})

    assert remind_main._dil_oku(str(tmp_path / "takvim.db")) == "en"


@pytest.mark.parametrize(
    "bozuk",
    [None, "bu json degil {", "[1, 2, 3]", '"en"', '{"dil": "de"}', b"\xff\xfe\x00"],
)
def test_remind_dil_oku_bozuk_ya_da_yoksa_tr(tmp_path, bozuk):
    """Dosya yok / bozuk / sözlük değil: istisna yok, Türkçe."""
    if bozuk is not None:
        _ayar_yaz(tmp_path, bozuk)

    assert remind_main._dil_oku(str(tmp_path / "takvim.db")) == "tr"


def test_remind_main_run_forever_a_dili_okuyucu_olarak_verir(tmp_path, monkeypatch):
    """`python -m remind` döngüye başlangıç dilini değil, okuyucuyu verir."""
    _ayar_yaz(tmp_path, {"dil": "en"})
    yakalanan: dict = {}

    def sahte_run_forever(repo, tzid, notifier, **kwargs):
        yakalanan["kwargs"] = kwargs

    monkeypatch.setattr(remind_main, "run_forever", sahte_run_forever)
    monkeypatch.setattr(
        remind_main, "pick_notifier", lambda tercih="auto", dil="tr": ConsoleNotifier()
    )

    kod = remind_main.main(["--db", str(tmp_path / "takvim.db"), "--notifier", "console"])

    assert kod == 0
    dil = yakalanan["kwargs"]["dil"]
    assert callable(dil), "metin değil, her turda dosyayı okuyan çağrılabilir"
    assert dil() == "en"
    _ayar_yaz(tmp_path, {"dil": "tr"})
    assert dil() == "tr"
