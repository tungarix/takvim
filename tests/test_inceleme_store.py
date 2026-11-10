"""Kod incelemesi bulguları: store/migrator.py."""

from __future__ import annotations

import sqlite3

import pytest

from store import connect, current_version, migrate, migrator
from store.migrator import available


def test_eszamanli_migration_bayat_surumle_catismaz(tmp_path, monkeypatch):
    """İkinci süreç sürümü bayat okuyup birincinin uyguladığı adımı yeniden
    çalıştırırsa açılış 'already exists' ile düşmemeli (bulgu 6)."""
    yol = tmp_path / "t.db"
    a = connect(yol)
    b = connect(yol)
    son = available()[-1][0]

    gercek = migrator.current_version
    cagri = {"n": 0}

    def bayat(conn):
        # B'nin BEGIN'den önceki ilk okuması: A henüz bitmemiş gibi 0.
        cagri["n"] += 1
        return 0 if cagri["n"] == 1 else gercek(conn)

    # A tam migrate eder; B ondan SONRA bayat sürümle devam eder.
    assert migrate(a) == son
    monkeypatch.setattr(migrator, "current_version", bayat)
    assert migrate(b) == son
    assert gercek(b) == son
    a.close()
    b.close()


def test_gercek_migration_hatasi_yutulmaz(tmp_path):
    """Sürüm ilerlemediyse hata aynen yükselmeli."""
    d = tmp_path / "m"
    d.mkdir()
    (d / "001_bozuk.sql").write_text("CREATE TABLE x (", encoding="utf-8")
    conn = connect(tmp_path / "t.db")
    with pytest.raises(sqlite3.OperationalError):
        migrate(conn, d)
    assert current_version(conn) == 0
    conn.close()
