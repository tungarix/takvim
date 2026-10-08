"""`scripts/exe_duman.py`'nin exe'ye ihtiyaç duymayan yardımcıları.

Exe'yi çalıştıran kısım release workflow'unda sınanıyor; burada yalnızca
kararı veren saf parçalar var: yanlış karar ya sürümü yanlış etiketle yayımlar
ya da sağlam bir sürümü durdurur.
"""

import importlib.util
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("exe_duman", KOK / "scripts" / "exe_duman.py")
assert _spec is not None and _spec.loader is not None
exe_duman = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(exe_duman)


def test_kaynak_surumu_surum_dosyasiyla_ayni():
    from ui.surum import SURUM

    assert exe_duman.kaynak_surumu() == SURUM


def test_etiket_v_onekli_surumle_uyumlu():
    assert exe_duman.etiket_uyumu("v1.5.0", "1.5.0") is None


def test_etiket_farkli_surumde_reddedilir():
    sorun = exe_duman.etiket_uyumu("v1.5.1", "1.5.0")
    assert sorun is not None and "v1.5.0" in sorun


def test_v_oneki_olmayan_etiket_reddedilir():
    assert exe_duman.etiket_uyumu("1.5.0", "1.5.0") is not None


def test_son_migration_migrasyon_klasorundeki_en_buyuk_numara():
    from store.migrator import migrate
    from store.repo import Repo

    with Repo.open(":memory:") as repo:
        migrate(repo.conn)
        user_version = repo.conn.execute("PRAGMA user_version").fetchone()[0]
    assert exe_duman.son_migration() == user_version


def test_gercek_veri_izi_dosya_yokken(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert exe_duman.gercek_veri_izi() == (False, None)


def test_gercek_veri_izi_dosya_degisince_degisir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    db = tmp_path / "Takvim" / "takvim.db"
    db.parent.mkdir()
    db.write_bytes(b"x")
    once = exe_duman.gercek_veri_izi()
    import os

    os.utime(db, (once[1] + 10, once[1] + 10))
    assert once[0] is True and exe_duman.gercek_veri_izi() != once


def test_olmayan_exe_hata_dondurur(tmp_path):
    hatalar = exe_duman.calistir(tmp_path / "yok.exe", "")
    assert any("exe bulunamadı" in h for h in hatalar)
