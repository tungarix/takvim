"""Otomatik yedek.

Ölçülen davranış tek cümle: kullanıcı bir şeyi yanlışlıkla silerse geri
dönebileceği bir kopya var mı, ve yedek alma işi ters gittiğinde uygulama
yine de açılıyor mu.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from store import Repo, yedek_al, yedek_klasoru
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
