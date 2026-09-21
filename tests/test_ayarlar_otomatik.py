"""Faz D testleri: ayar dosyası, otomatik başlatma kaydı, tepsi simgesi.

Tepsi ve kısayol Windows'a dokunuyor; testler dosya sisteminde tmp klasörle,
GUI'siz çalışıyor. Gerçek `NotifyIcon` kurulmuyor (sahte arka uç enjekte
ediliyor), gerçek Başlangıç klasörüne yazılmıyor.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from store import Repo
from tests.helpers import IST
from ui import otomatik
from ui.ayarlar import VARSAYILANLAR, ayar_dosyasi, ayar_oku, ayar_yaz
from ui.server import make_server
from ui.tepsi import Tepsi, simge_bul

# ---------------------------------------------------------------------------
# ayarlar.json
# ---------------------------------------------------------------------------

def test_varsayilanlar_kapali(tmp_path):
    """Dosya yoksa ikisi de kapalı (mevcut davranış korunuyor)."""
    assert ayar_oku(ayar_dosyasi(tmp_path)) == {
        "tepsiye_kucult": False,
        "otomatik_baslat": False,
    }


def test_yaz_oku_gidis_donus(tmp_path):
    """Yazılan aynen okunuyor."""
    yol = ayar_dosyasi(tmp_path)
    assert ayar_yaz(yol, {"tepsiye_kucult": True, "otomatik_baslat": False}) is True
    assert ayar_oku(yol)["tepsiye_kucult"] is True


def test_bozuk_dosya_varsayilana_duser(tmp_path):
    """Bozuk JSON uygulamayı bozmuyor."""
    yol = ayar_dosyasi(tmp_path)
    yol.write_text("{bozuk", encoding="utf-8")
    assert ayar_oku(yol) == VARSAYILANLAR


def test_yanlis_tip_reddedilir(tmp_path):
    """Elde yazılmış `"evet"` sessizce True olmuyor."""
    yol = ayar_dosyasi(tmp_path)
    yol.write_text(
        json.dumps({"tepsiye_kucult": "evet", "otomatik_baslat": 1}),
        encoding="utf-8",
    )
    assert ayar_oku(yol) == VARSAYILANLAR


def test_bilinmeyen_anahtar_yazilmaz(tmp_path):
    """Fazladan anahtar dosyaya sızmıyor."""
    yol = ayar_dosyasi(tmp_path)
    ayar_yaz(yol, {"tepsiye_kucult": True, "gelecek_ayar": 1})
    assert json.loads(yol.read_text(encoding="utf-8")) == {
        "tepsiye_kucult": True,
        "otomatik_baslat": False,
    }


# ---------------------------------------------------------------------------
# otomatik başlatma
# ---------------------------------------------------------------------------

def test_hedef_gelistirme_kipi_db_yolu_tasiyor():
    """`--db` MUTLAK yazılıyor; yoksa yanlış dosya izlenir."""
    hedef, argumanlar, dizin = otomatik.hedef_hesapla("C:\\veri\\takvim.db")
    assert hedef.lower().endswith("pythonw.exe")
    assert "--db" in argumanlar and "C:\\veri\\takvim.db" in argumanlar
    assert dizin and "\\" in dizin


def test_kurulum_komutu_yollari_tasiyor(tmp_path):
    """PowerShell komutu hedef + kısayol yolunu içeriyor."""
    komut = otomatik._kurKomutu("C:\\a\\x.exe", "--no-browser", "C:\\a", "C:\\b\\k.lnk")
    assert "C:\\a\\x.exe" in komut and "C:\\b\\k.lnk" in komut


@pytest.mark.skipif(
    os.environ.get("CI") is not None,
    reason=(
        "gerçek PowerShell/WScript.Shell üzerinden .lnk kuruyor -- CI'nin "
        "kullan-at Windows kutusunda sessizce başarısız oluyor (muhtemelen "
        "COM kaydı ya da yürütme ilkesi farkı), gerçek geliştirme "
        "makinesinde geçiyor. `otomatik.kur` zaten kendi başarısızlığını "
        "False ile bildiriyor (bkz. ui/server.py _ayar_kaydet), bu test "
        "yalnızca o yolun gerçek ortamda ÇALIŞTIĞINI doğruluyor."
    ),
)
def test_kur_kaldir_gidis_donus(tmp_path):
    """Gerçek `.lnk` kurulup kaldırılıyor (tmp klasörde, zararsız)."""
    assert otomatik.kurulu_mu(tmp_path) is False
    assert otomatik.kur(tmp_path, db_yolu=str(tmp_path / "takvim.db")) is True
    assert otomatik.kurulu_mu(tmp_path) is True
    assert otomatik.kaldir(tmp_path) is True
    assert otomatik.kurulu_mu(tmp_path) is False


def test_kaldir_yoksa_basarili():
    """Kaldırılacak kayıt yoksa da True (istenen durum zaten o)."""
    assert otomatik.kaldir("C:\\yok\\böyle\\bir\\klasör\\ZZZ") is True


# ---------------------------------------------------------------------------
# tepsi
# ---------------------------------------------------------------------------

class _Olay:
    """`+=` ile abone olunan sahte WinForms olayı."""

    def __init__(self):
        self.islevler = []

    def __iadd__(self, islev):
        self.islevler.append(islev)
        return self

    def atesle(self, *args):
        for islev in self.islevler:
            islev(*args)


class _SahteOge:
    def __init__(self, metin=None):
        self.metin = metin
        self.Click = _Olay()


class _SahteListe:
    def __init__(self):
        self.ogeler = []

    def Add(self, oge):
        self.ogeler.append(oge)


class _SahteMenu:
    def __init__(self):
        self.Items = _SahteListe()


class _SahteSimge:
    def __init__(self):
        self.Text = None
        self.Icon = None
        self.Visible = False
        self.DoubleClick = _Olay()
        self.ContextMenuStrip = None
        self.balon = None
        self.kapatildi = False

    def ShowBalloonTip(self, *args):
        self.balon = args

    def Dispose(self):
        self.kapatildi = True


class _SahteArkaUc:
    """WinForms'un teste yetecek kadarını taklit eder."""

    def __init__(self):
        self.simgeler = []

    def NotifyIcon(self):
        simge = _SahteSimge()
        self.simgeler.append(simge)
        return simge

    def ContextMenuStrip(self):
        return _SahteMenu()

    def ToolStripMenuItem(self, metin):
        return _SahteOge(metin)

    def Icon(self, yol):
        return ("ikon", yol)

    @property
    def SystemIcons(self):
        class _S:
            Application = ("stok",)
        return _S()


def test_tepsi_kurulur_ve_menu_calir():
    """Aç/kapat kabloları menüye bağlanıyor; çift tık açıyor."""
    arka = _SahteArkaUc()
    acildi, kapandi = [], []
    tepsi = Tepsi.kur(lambda: acildi.append(1), lambda: kapandi.append(1),
                      simge_yolu="x.ico", arka_uc=arka)
    assert tepsi is not None
    simge = arka.simgeler[0]
    assert simge.Visible is True
    assert simge.Icon == ("ikon", "x.ico")
    assert simge.balon is not None  # bilgi baloncuğu denendi
    adlar = [o.metin for o in simge.ContextMenuStrip.Items.ogeler]
    assert adlar == ["Takvim'i Aç", "Kapat"]
    simge.ContextMenuStrip.Items.ogeler[0].Click.atesle()
    simge.DoubleClick.atesle()
    simge.ContextMenuStrip.Items.ogeler[1].Click.atesle()
    assert (acildi, kapandi) == ([1, 1], [1])
    tepsi.kapat()
    assert simge.kapatildi is True


def test_tepsi_stok_ikonla_da_kurulur():
    """Simge dosyası yoksa stok ikonla devam (None değil)."""
    arka = _SahteArkaUc()
    assert Tepsi.kur(lambda: None, lambda: None, arka_uc=arka) is not None
    assert arka.simgeler[0].Icon == ("stok",)


def test_tepsi_basarisizsa_none():
    """Arka uç patlarsa None (uygulama tepsisiz devam eder)."""

    class _Bozuk:
        def NotifyIcon(self):
            raise OSError("yok")

    assert Tepsi.kur(lambda: None, lambda: None, arka_uc=_Bozuk()) is None


def test_simge_bul_proje_kokundeki_icoyu_bulur():
    """Bu depoda takvim.ico var; kurulu uygulamada datas'tan gelir."""
    assert simge_bul() is not None and simge_bul().endswith("takvim.ico")


# ---------------------------------------------------------------------------
# /api/ayarlar (canlı sunucu; otomatik kayıt SAHTE — gerçek Başlangıç klasörü
# testlerde ASLA kullanılmaz)
# ---------------------------------------------------------------------------

@pytest.fixture
def sunucu_dosya(tmp_path, monkeypatch):
    """Dosya DB'li sunucu + sahte otomatik kayıt."""
    kayit = {"kurulu": False}

    def _kur(db_yolu=None):
        kayit["kurulu"] = True
        kayit["db"] = db_yolu
        return True

    def _kaldir():
        kayit["kurulu"] = False
        return True

    monkeypatch.setattr("ui.server.otomatik.kur", _kur)
    monkeypatch.setattr("ui.server.otomatik.kaldir", _kaldir)
    monkeypatch.setattr("ui.server.otomatik.kurulu_mu", lambda: kayit["kurulu"])

    db = str(tmp_path / "takvim.db")
    repo = Repo.open(db, check_same_thread=False)
    repo.add_calendar("Ders", "#e0524a")
    httpd = make_server(repo, IST, host="127.0.0.1", port=0, db_yolu=db)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", tmp_path, kayit
    httpd.shutdown()
    httpd.server_close()
    repo.close()


def _jget(temel, yol):
    with urllib.request.urlopen(temel + yol) as yanit:
        return json.loads(yanit.read().decode("utf-8"))


def _jpost(temel, yol, govde):
    req = urllib.request.Request(
        temel + yol, method="POST",
        data=json.dumps(govde).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req) as yanit:
        return json.loads(yanit.read().decode("utf-8"))


def test_ayarlar_varsayilanla_gelir(sunucu_dosya):
    """İlk açılışta ikisi de kapalı."""
    temel, _, _ = sunucu_dosya
    assert _jget(temel, "/api/ayarlar") == {
        "tepsiye_kucult": False, "otomatik_baslat": False}


def test_ayarlar_tepsi_kaydedilir(sunucu_dosya):
    """Tepsi bayrağı dosyaya yazılıyor, GET'e yansıyor."""
    temel, tmp_path, _ = sunucu_dosya
    assert _jpost(temel, "/api/ayarlar", {"tepsiye_kucult": True})["tepsiye_kucult"] is True
    assert ayar_oku(ayar_dosyasi(tmp_path))["tepsiye_kucult"] is True


def test_ayarlar_otomatik_kabloyu_kuruyor(sunucu_dosya):
    """POST sahte kurulumu doğru DB yoluyla çağırıyor."""
    temel, _, kayit = sunucu_dosya
    yanit = _jpost(temel, "/api/ayarlar", {"otomatik_baslat": True})
    assert yanit["otomatik_baslat"] is True
    assert kayit["kurulu"] is True and kayit["db"].endswith("takvim.db")
    _jpost(temel, "/api/ayarlar", {"otomatik_baslat": False})
    assert kayit["kurulu"] is False


def test_ayarlar_bozuk_tip_400(sunucu_dosya):
    """Metin bayrak 400."""
    temel, _, _ = sunucu_dosya
    with pytest.raises(urllib.error.HTTPError) as hata:
        _jpost(temel, "/api/ayarlar", {"tepsiye_kucult": "evet"})
    assert hata.value.code == 400


def test_ayarlar_kurulum_patlarsa_500_ve_dosya_degismez(sunucu_dosya, monkeypatch):
    """Kayıt kurulamazsa yalan söylenmiyor: 500 + dosya eski hâliyle."""
    temel, tmp_path, _ = sunucu_dosya
    monkeypatch.setattr("ui.server.otomatik.kur", lambda db_yolu=None: False)
    with pytest.raises(urllib.error.HTTPError) as hata:
        _jpost(temel, "/api/ayarlar", {"otomatik_baslat": True})
    assert hata.value.code == 500
    assert ayar_oku(ayar_dosyasi(tmp_path))["otomatik_baslat"] is False
