"""Bozuk veritabanı: yedekler korunur, açılışta son sağlam yedeğe dönülür.

İki gerçek sorundan çıktı (paketli exe'de ölçüldü):

1. Bozuk ama AÇILABİLEN bir veritabanıyla uygulama hiçbir şey demeden
   açılıyor ve günlük yedek, o sabahın SAĞLAM yedeğinin üstüne bozuk kopyayı
   yazıyordu. Birkaç gün sürse budama eski sağlamları da silerdi.
2. Veritabanı olmayan bir dosyada kullanıcı yalnızca ham hata metni görüyor,
   kurtarmak için dosyaları elle yeniden adlandırması gerekiyordu.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

import pytest

from store import Repo, yedek_al, yedek_klasoru
from store.yedek import (
    bozuk_veritabanini_degistir,
    son_saglam_yedek,
    veritabani_bozuklugu,
)
from tests.helpers import IST
from ui.kurtarma import KurtarmaReddedildi, bozuksa_kurtar
from ui.server import make_server

SIMDI = datetime(2026, 10, 8, 9, 30, 0)


def _takvim_db(yol: Path, takvim: str = "Kişisel") -> Path:
    """Takvim şemalı, içinde bir takvim olan sağlam dosya."""
    with Repo.open(str(yol)) as repo:
        repo.add_calendar(takvim, "#3b82f6")
    return yol


def _bozuk_ama_acilir(yol: Path) -> None:
    """Takvim tablolarına dokunmadan ek bir tablonun ağacını bozar.

    `test_yedek.py::test_bozuk_ama_acilabilen_yedek_reddedilir` ile aynı
    yöntem: iki hücrenin aynı çocuk sayfaya bakması her çalıştırmada aynı
    `quick_check` satırını üretiyor (hücre işaretçisi bozmak belirsiz).
    Dosya açılabilir kalıyor ve takvim tabloları okunabiliyor: tam da sessizce
    yedeklenen türden bozukluk.
    """
    baglanti = sqlite3.connect(yol)
    baglanti.execute("CREATE TABLE dolgu (a INTEGER PRIMARY KEY, b TEXT)")
    baglanti.executemany("INSERT INTO dolgu (b) VALUES (?)", [("x" * 200,) for _ in range(500)])
    baglanti.commit()
    sayfa = baglanti.execute("PRAGMA page_size").fetchone()[0]
    baglanti.close()
    veri = bytearray(yol.read_bytes())
    for ara in range(1, len(veri) // sayfa):
        if veri[ara * sayfa] != 0x05:
            continue
        if int.from_bytes(veri[ara * sayfa + 3 : ara * sayfa + 5], "big") < 2:
            continue
        ilk, ikinci = (
            ara * sayfa
            + int.from_bytes(veri[ara * sayfa + 12 + 2 * k : ara * sayfa + 14 + 2 * k], "big")
            for k in (0, 1)
        )
        veri[ikinci : ikinci + 4] = veri[ilk : ilk + 4]
        break
    yol.write_bytes(bytes(veri))
    assert veritabani_bozuklugu(yol) is not None, "önkoşul: dosya bozuk olmalı"


def _takvimler(yol: Path) -> list[str]:
    baglanti = sqlite3.connect(yol)
    try:
        return [r[0] for r in baglanti.execute("SELECT name FROM calendars ORDER BY name")]
    finally:
        baglanti.close()


def _yedek(klasor: Path, gun: str, *, takvim: str = "Kişisel", bozuk: bool = False) -> Path:
    klasor.mkdir(parents=True, exist_ok=True)
    yol = _takvim_db(klasor / f"takvim-{gun}.db", takvim)
    if bozuk:
        _bozuk_ama_acilir(yol)
    return yol


# --- veritabani_bozuklugu ---------------------------------------------------


def test_saglam_dosya_bozuk_sayilmaz(tmp_path):
    assert veritabani_bozuklugu(_takvim_db(tmp_path / "takvim.db")) is None


def test_olmayan_dosya_bozuk_sayilmaz(tmp_path):
    """İlk açılış: dosya yok, oluşturulacak. Kurtarma sorusu çıkmamalı."""
    assert veritabani_bozuklugu(tmp_path / "takvim.db") is None


def test_veritabani_olmayan_dosya_bozuk(tmp_path):
    yol = tmp_path / "takvim.db"
    yol.write_bytes(b"bu bir veritabani degil" * 100)
    assert veritabani_bozuklugu(yol) is not None


def test_bozuk_ama_acilabilen_dosya_bozuk(tmp_path):
    yol = _takvim_db(tmp_path / "takvim.db")
    _bozuk_ama_acilir(yol)
    assert veritabani_bozuklugu(yol) is not None


def test_kilitli_dosya_bozuk_sayilmaz(tmp_path):
    """Arka plan kopyası yazarken açılış sağlam dosyayı kenara ALMAMALI."""
    yol = _takvim_db(tmp_path / "takvim.db")
    kilitleyen = sqlite3.connect(yol, isolation_level=None)
    try:
        kilitleyen.execute("BEGIN EXCLUSIVE")
        assert veritabani_bozuklugu(yol, bekleme=0.1) is None
    finally:
        kilitleyen.execute("ROLLBACK")
        kilitleyen.close()


# --- yedek_al bozuk veritabanından yedek almaz ------------------------------


def test_bozuk_veritabani_sabahki_saglam_yedegin_ustune_yazilmaz(tmp_path):
    db = _takvim_db(tmp_path / "takvim.db")
    with Repo.open(str(db)) as repo:
        sabah = yedek_al(repo.conn, tmp_path, bugun=date(2026, 10, 8))
    assert sabah is not None
    saglam_bayt = sabah.read_bytes()

    _bozuk_ama_acilir(db)
    with Repo.open(str(db)) as repo:
        assert yedek_al(repo.conn, tmp_path, bugun=date(2026, 10, 8)) is None

    assert sabah.read_bytes() == saglam_bayt


def test_bozuk_veritabani_eski_yedekleri_budatmaz(tmp_path):
    klasor = yedek_klasoru(tmp_path)
    eskiler = [_yedek(klasor, f"2026-09-{g:02d}") for g in range(20, 30)]  # 10 dosya, sınır 7
    db = _takvim_db(tmp_path / "takvim.db")
    _bozuk_ama_acilir(db)
    with Repo.open(str(db)) as repo:
        yedek_al(repo.conn, tmp_path, bugun=date(2026, 10, 8))
    assert all(y.exists() for y in eskiler)


# --- son_saglam_yedek -------------------------------------------------------


def test_son_saglam_yedek_en_yeniyi_secer(tmp_path):
    klasor = yedek_klasoru(tmp_path)
    _yedek(klasor, "2026-10-05")
    yeni = _yedek(klasor, "2026-10-07")
    assert son_saglam_yedek(klasor) == yeni


def test_son_saglam_yedek_bozuk_en_yeniyi_atlar(tmp_path):
    """Koruma gelmeden önceki sürümler bozuk kopyayı yedeklemiş olabilir."""
    klasor = yedek_klasoru(tmp_path)
    saglam = _yedek(klasor, "2026-10-05")
    _yedek(klasor, "2026-10-07", bozuk=True)
    assert son_saglam_yedek(klasor) == saglam


def test_son_saglam_yedek_hicbiri_saglam_degilse_none(tmp_path):
    klasor = yedek_klasoru(tmp_path)
    _yedek(klasor, "2026-10-07", bozuk=True)
    assert son_saglam_yedek(klasor) is None


# --- bozuk_veritabanini_degistir --------------------------------------------


def test_degistir_yedegi_yerine_koyar_bozugu_saklar(tmp_path):
    db = _takvim_db(tmp_path / "takvim.db", "Bozulan")
    _bozuk_ama_acilir(db)
    bozuk_bayt = db.read_bytes()
    yedek = _yedek(yedek_klasoru(tmp_path), "2026-10-07", takvim="Yedekteki")

    kenara = bozuk_veritabanini_degistir(db, yedek, simdi=SIMDI)

    assert _takvimler(db) == ["Yedekteki"]
    assert veritabani_bozuklugu(db) is None
    assert kenara.name == "bozuk-takvim-20261008-093000.db"
    assert kenara.read_bytes() == bozuk_bayt


def test_degistir_bozugun_gunlugunu_de_tasir(tmp_path):
    """Yerinde kalan sıcak günlük yeni dosyaya 'geri alma' diye uygulanırdı."""
    db = _takvim_db(tmp_path / "takvim.db")
    _bozuk_ama_acilir(db)
    gunluk = tmp_path / "takvim.db-journal"
    gunluk.write_bytes(b"sicak gunluk")
    yedek = _yedek(yedek_klasoru(tmp_path), "2026-10-07")

    kenara = bozuk_veritabanini_degistir(db, yedek, simdi=SIMDI)

    assert not gunluk.exists()
    assert (tmp_path / (kenara.name + "-journal")).read_bytes() == b"sicak gunluk"


# --- bozuksa_kurtar (açılış akışı) ------------------------------------------


class _Kutu:
    """tkinter yerine geçen soru/bilgi kaydedici."""

    def __init__(self, cevap: bool | None) -> None:
        self.cevap = cevap
        self.sorular: list[str] = []
        self.bilgiler: list[str] = []

    def sor(self, baslik: str, mesaj: str) -> bool | None:
        self.sorular.append(mesaj)
        return self.cevap

    def bildir(self, baslik: str, mesaj: str) -> None:
        self.bilgiler.append(mesaj)


def _kurtar(tmp_path, kutu: _Kutu | None, dil: str = "tr"):
    return bozuksa_kurtar(
        str(tmp_path / "takvim.db"),
        veri_dizini=tmp_path,
        dil=dil,
        sor=kutu.sor if kutu else None,
        bildir=kutu.bildir if kutu else None,
        simdi=SIMDI,
    )


def test_saglam_veritabaninda_soru_sorulmaz(tmp_path):
    _takvim_db(tmp_path / "takvim.db")
    kutu = _Kutu(True)
    assert _kurtar(tmp_path, kutu) is None
    assert kutu.sorular == []


def test_evet_denince_son_saglam_yedege_donulur(tmp_path):
    db = _takvim_db(tmp_path / "takvim.db", "Bozulan")
    _bozuk_ama_acilir(db)
    _yedek(yedek_klasoru(tmp_path), "2026-10-07", takvim="Yedekteki")
    kutu = _Kutu(True)

    kenara = _kurtar(tmp_path, kutu)

    assert _takvimler(db) == ["Yedekteki"]
    assert kenara is not None and kenara.exists()
    assert "2026-10-07" in kutu.sorular[0]
    assert str(kenara) in kutu.bilgiler[0]


def test_hayir_denince_hicbir_dosyaya_dokunulmaz(tmp_path):
    db = _takvim_db(tmp_path / "takvim.db")
    _bozuk_ama_acilir(db)
    bozuk_bayt = db.read_bytes()
    _yedek(yedek_klasoru(tmp_path), "2026-10-07")

    with pytest.raises(KurtarmaReddedildi):
        _kurtar(tmp_path, _Kutu(False))

    assert db.read_bytes() == bozuk_bayt
    assert not list(tmp_path.glob("bozuk-*"))


def test_soru_sorulamiyorsa_dokunulmaz_ve_yol_soylenir(tmp_path):
    """Penceresiz arka plan kopyası (otomatik başlatma) kendi başına karar vermez."""
    db = _takvim_db(tmp_path / "takvim.db")
    _bozuk_ama_acilir(db)
    bozuk_bayt = db.read_bytes()
    _yedek(yedek_klasoru(tmp_path), "2026-10-07")

    with pytest.raises(RuntimeError, match="kısayolundan"):
        _kurtar(tmp_path, None)
    assert db.read_bytes() == bozuk_bayt


def test_saglam_yedek_yoksa_soru_sorulmaz_dokunulmaz(tmp_path):
    db = tmp_path / "takvim.db"
    db.write_bytes(b"bu bir veritabani degil" * 100)
    kutu = _Kutu(True)

    with pytest.raises(RuntimeError, match="sağlam bir yedek"):
        _kurtar(tmp_path, kutu)
    assert kutu.sorular == []
    assert db.read_bytes() == b"bu bir veritabani degil" * 100


def test_soru_ingilizce_arayuzde_ingilizce(tmp_path):
    db = _takvim_db(tmp_path / "takvim.db")
    _bozuk_ama_acilir(db)
    _yedek(yedek_klasoru(tmp_path), "2026-10-07")
    kutu = _Kutu(False)
    with pytest.raises(KurtarmaReddedildi):
        _kurtar(tmp_path, kutu, dil="en")
    assert "latest healthy backup" in kutu.sorular[0]


# --- "Şimdi yedekle" bozuk veritabanında yanıltmaz --------------------------


def test_simdi_yedekle_bozuk_veritabaninda_kendi_hata_kodunu_verir(tmp_path):
    db = _takvim_db(tmp_path / "takvim.db")
    _bozuk_ama_acilir(db)
    with Repo.open(str(db), check_same_thread=False) as repo:
        httpd = make_server(repo, IST, host="127.0.0.1", port=0, db_yolu=str(db))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            istek = urllib.request.Request(
                f"http://127.0.0.1:{httpd.server_address[1]}/api/backups",
                method="POST",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            )
            with pytest.raises(urllib.error.HTTPError) as hata:
                urllib.request.urlopen(istek)
            govde = json.loads(hata.value.read().decode("utf-8"))
        finally:
            httpd.shutdown()
            httpd.server_close()
    assert govde["error_code"] == "veritabani_bozuk"
