"""Migration mekanizması.

Uygulanan sürüm SQLite'ın kendi `PRAGMA user_version` alanında tutulur; ayrı
bir tablo açmaya gerek yok. Migration dosyaları `migrations/NNN_ad.sql`
biçiminde, sıra numarasına göre uygulanır.

Kural: uygulanmış bir migration DEĞİŞTİRİLMEZ. Şema değişikliği yeni bir
dosyadır. Aksi hâlde iki makinedeki DB sessizce farklılaşır.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

__all__ = ["MIGRATIONS_DIR", "available", "current_version", "migrate"]

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_NAME_RE = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


def available(directory: Path | None = None) -> list[tuple[int, Path]]:
    """Diskteki migration dosyalarını (sürüm, yol) olarak sıralı döndürür."""
    directory = directory or MIGRATIONS_DIR
    found: list[tuple[int, Path]] = []
    for path in sorted(directory.glob("*.sql")):
        match = _NAME_RE.match(path.name)
        if not match:
            raise ValueError(
                f"Migration adı NNN_ad.sql biçiminde olmalı: {path.name}"
            )
        found.append((int(match.group(1)), path))

    versions = [v for v, _ in found]
    if len(set(versions)) != len(versions):
        raise ValueError(f"Yinelenen migration sürümü: {versions}")
    return found


def current_version(conn: sqlite3.Connection) -> int:
    """DB'ye uygulanmış son migration sürümü (hiç yoksa 0)."""
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection, directory: Path | None = None) -> int:
    """Bekleyen migrationları sırayla uygular; ulaşılan sürümü döndürür.

    Her adım kendi transaction'ında: DDL yarıda kalırsa user_version artmaz,
    yani bir sonraki çalıştırma aynı adımı baştan dener.
    """
    version = current_version(conn)
    for target, path in available(directory):
        if target <= version:
            continue
        sql = path.read_text(encoding="utf-8")
        # BEGIN/COMMIT script'in İÇİNDE olmak zorunda: executescript, kendisinden
        # önce açılmış bir transaction'ı örtük olarak commit ediyor, yani dışarıya
        # sarmak koruma sağlamıyor.
        #
        # PRAGMA parametre kabul etmiyor; target dosya adından gelen doğrulanmış
        # bir tamsayı, enjeksiyon yüzeyi yok.
        script = f"""BEGIN;
{sql}
PRAGMA user_version = {target:d};
COMMIT;"""
        try:
            conn.executescript(script)
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        version = target
    return version
