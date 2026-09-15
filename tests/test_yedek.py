"""Otomatik yedek.

Ölçülen davranış tek cümle: kullanıcı bir şeyi yanlışlıkla silerse geri
dönebileceği bir kopya var mı, ve yedek alma işi ters gittiğinde uygulama
yine de açılıyor mu.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from store import Repo, yedek_al, yedek_klasoru, yedekten_don
from store.yedek import SAKLANAN, yedek_dosyalari


def _depo(yol) -> Repo:
    """İçinde bir takvim olan gerçek dosya veritabanı."""
    repo = Repo.open(str(yol))
    repo.add_calendar("Kişisel", "#3b82f6")
    return repo


def test_yedek_alinir_ve_icerigi_okunabilir(tmp_path):
    """Yedek gerçek bir veritabanı; içindeki takvim geri okunabiliyor."""
    with _depo(tmp_path / "takvim.db") as repo:
        yol = yedek_al(repo.conn, tmp_path, bugun=date(2026, 9, 13))

    assert yol is not None and yol.exists()
    with Repo.open(str(yol)) as geri:
        assert [c.name for c in geri.list_calendars()] == ["Kişisel"]


def test_ayni_gun_ikinci_acilis_ikinci_dosya_yaratmaz(tmp_path):
    """Günde tek dosya.

    Yoksa uygulamayı bir günde beş kez açan kullanıcının yedi kopyalık
    penceresi tek güne sıkışır ve "geçen hafta" kurtarılamaz hâle gelir.
    """
    with _depo(tmp_path / "takvim.db") as repo:
        yedek_al(repo.conn, tmp_path, bugun=date(2026, 9, 13))
        repo.add_calendar("Ders", "#e0524a")
        yedek_al(repo.conn, tmp_path, bugun=date(2026, 9, 13))

    dosyalar = yedek_dosyalari(yedek_klasoru(tmp_path))
    assert len(dosyalar) == 1
    with Repo.open(str(dosyalar[0])) as geri:
        assert len(geri.list_calendars()) == 2, "aynı günün yedeği GÜNCELLENMELİ"


def test_yedi_gunden_fazlasi_budanir(tmp_path):
    """En eskiler silinir, en yeni yedi tanesi kalır."""
    with _depo(tmp_path / "takvim.db") as repo:
        for gun in range(1, 12):  # 11 gün
            yedek_al(repo.conn, tmp_path, bugun=date(2026, 9, gun))

    kalan = [d.name for d in yedek_dosyalari(yedek_klasoru(tmp_path))]

    assert len(kalan) == SAKLANAN
    assert kalan[0] == "takvim-2026-09-05.db", "en eskiler gitmeli"
    assert kalan[-1] == "takvim-2026-09-11.db", "en yeni durmalı"


def test_yedek_alinamazsa_istisna_atmaz(tmp_path):
    """Yedek alamamak uygulamayı AÇMAMAK için sebep değil.

    Yedek klasörünün yerinde bir DOSYA varsa klasör oluşturulamaz; bu,
    yazılamayan bir veri klasörünün test edilebilir karşılığı.
    """
    (tmp_path / "yedek").write_text("burası dosya, klasör değil", encoding="utf-8")

    with _depo(tmp_path / "takvim.db") as repo:
        assert yedek_al(repo.conn, tmp_path, bugun=date(2026, 9, 13)) is None


def test_yarim_yedek_birakilmaz(tmp_path):
    """Kopyalama sırasında ölürsek geriye yarım "yedek" kalmamalı.

    Yarım yedek yedeksizlikten kötüdür: insan ona güvenir. Bu yüzden geçici
    ada yazılıp sonra taşınıyor; burada da klasörde takvim-*.db adıyla
    yarım bir dosya kalmadığını doğruluyoruz.
    """
    with _depo(tmp_path / "takvim.db") as repo:
        yedek_al(repo.conn, tmp_path, bugun=date(2026, 9, 13))

    klasor = yedek_klasoru(tmp_path)
    assert not list(klasor.glob("*.gecici"))
    for d in yedek_dosyalari(klasor):
        sqlite3.connect(d).execute("PRAGMA quick_check").fetchone()  # bozuksa patlar


def test_yedekten_don_eski_hali_getirir(tmp_path):
    """Dönüş çalışıyor: sonradan eklenen takvim gidiyor, yedekteki duruyor."""
    db = tmp_path / "takvim.db"
    with _depo(db) as repo:
        yedek_al(repo.conn, tmp_path, bugun=date(2026, 9, 13))
        repo.add_calendar("Ders", "#e0524a")
        repo = yedekten_don(repo, str(db), "takvim-2026-09-13.db")
        assert [c.name for c in repo.list_calendars()] == ["Kişisel"]
        repo.close()


def test_yedekten_don_mevcut_hali_kenara_alir(tmp_path):
    """Dönüşten önce mevcut DB kenara alınıyor (dönüşün dönüşü mümkün)."""
    db = tmp_path / "takvim.db"
    with _depo(db) as repo:
        yedek_al(repo.conn, tmp_path, bugun=date(2026, 9, 13))
        repo = yedekten_don(repo, str(db), "takvim-2026-09-13.db")
        repo.close()
    kenara = list(yedek_klasoru(tmp_path).glob("onceki-takvim-*.db"))
    assert len(kenara) == 1
    with Repo.open(str(kenara[0])) as geri:
        assert [c.name for c in geri.list_calendars()] == ["Kişisel"]


def test_yedekten_don_liste_disi_adi_reddeder(tmp_path):
    """Yol geçişi (`../`) dahil liste-dışı her ad ValueError."""
    db = tmp_path / "takvim.db"
    with _depo(db) as repo:
        yedek_al(repo.conn, tmp_path, bugun=date(2026, 9, 13))
        for kotu in ("../takvim.db", "takvim-2026-09-13.db.gecici", ""):
            with pytest.raises(ValueError):
                yedekten_don(repo, str(db), kotu)
        repo.close()
    # Reddedilen denemeler DB'yi bozmadı:
    with Repo.open(str(db)) as geri:
        assert [c.name for c in geri.list_calendars()] == ["Kişisel"]


def test_yedekten_don_bellekte_reddedilir():
    """`:memory:`'de dosya yok; dönüş anlamsız."""
    with Repo.open(":memory:") as repo:
        with pytest.raises(ValueError):
            yedekten_don(repo, ":memory:", "takvim-2026-09-13.db")


def test_yedekten_don_ikinci_baglanti_acikken_calir(tmp_path):
    """Hatırlatıcı thread'i dosyayı açık tutarken dönüş sessizce yutulmasın."""
    db = tmp_path / "takvim.db"
    with _depo(db) as repo:
        yedek_al(repo.conn, tmp_path, bugun=date(2026, 9, 13))
        repo.add_calendar("Ders", "#e0524a")
        with Repo.open(str(db)) as ikinci:  # hatırlatıcı benzetimi
            repo = yedekten_don(repo, str(db), "takvim-2026-09-13.db")
            assert [c.name for c in repo.list_calendars()] == ["Kişisel"]
            assert [c.name for c in ikinci.list_calendars()] == ["Kişisel"]
        repo.close()
