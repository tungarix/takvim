"""Migration mekanizması ve şema kayması (drift) kontrolü."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from store import connect, current_version, migrate
from store.migrator import MIGRATIONS_DIR, available

SCHEMA_SQL = Path(__file__).resolve().parents[1] / "store" / "schema.sql"


def _schema_of(conn: sqlite3.Connection) -> list[tuple]:
    """DB'nin tablo/indeks tanımlarını karşılaştırılabilir biçimde döndürür."""
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    return [tuple(r) for r in rows]


def test_bos_db_migrate_edilir():
    """Sıfırdan DB kurulur ve user_version son sürüme ayarlanır."""
    conn = connect(":memory:")
    assert current_version(conn) == 0

    version = migrate(conn)
    beklenen = max(v for v, _ in available())

    assert version == beklenen
    assert current_version(conn) == beklenen
    tablolar = {name for _, name, _ in _schema_of(conn)}
    assert {"calendars", "events", "event_overrides"} <= tablolar


def test_migrate_idempotent():
    """İkinci çağrı hiçbir şey yapmaz, patlamaz."""
    conn = connect(":memory:")
    ilk = migrate(conn)
    ikinci = migrate(conn)

    assert ilk == ikinci
    assert current_version(conn) == ilk


def test_schema_sql_migrationlarla_ayni():
    """store/schema.sql ile migrations/ aynı şemayı üretmeli.

    İki doğruluk kaynağı olmasın diye: biri güncellenip diğeri unutulursa
    bu test kırılır.
    """
    migrated = connect(":memory:")
    migrate(migrated)

    reference = connect(":memory:")
    reference.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))

    assert _schema_of(migrated) == _schema_of(reference)


def test_basarisiz_migration_surumu_artirmaz(tmp_path: Path):
    """Yarıda kalan bir adım user_version'ı ilerletmez; tekrar denenebilir."""
    (tmp_path / "001_ok.sql").write_text("CREATE TABLE a (id INTEGER);", encoding="utf-8")
    (tmp_path / "002_bozuk.sql").write_text("CREATE TABLE bu gecerli degil(", encoding="utf-8")

    conn = connect(":memory:")
    with pytest.raises(sqlite3.Error):
        migrate(conn, tmp_path)

    assert current_version(conn) == 1, "001 uygulandı, 002 geri alındı"
    assert conn.execute("SELECT count(*) FROM a").fetchone()[0] == 0


def test_gecersiz_migration_adi_reddedilir(tmp_path: Path):
    """NNN_ad.sql dışındaki adlar sessizce atlanmaz, hata verir."""
    (tmp_path / "ilk.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(ValueError, match="NNN_ad.sql"):
        available(tmp_path)


def test_migration_dosyalari_sirali_ve_tekil():
    """Gerçek migrations/ dizini geçerli ve çakışmasız."""
    found = available(MIGRATIONS_DIR)
    versions = [v for v, _ in found]

    assert versions == sorted(versions)
    assert len(set(versions)) == len(versions)
    assert versions[0] == 1
