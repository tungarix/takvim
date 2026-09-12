"""`python -m ui` giriş noktası.

Örnek:
    .venv/Scripts/python.exe -m ui --demo
    .venv/Scripts/python.exe -m ui --db takvim.db
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from datetime import date

from store import Repo

from .demo import TZID, seed
from .server import serve


def main(argv: list[str] | None = None) -> int:
    """Komut satırını çözer ve sunucuyu başlatır."""
    ayristirici = argparse.ArgumentParser(prog="ui", description="Takvim hafta görünümü")
    ayristirici.add_argument("--db", default=":memory:", help="SQLite dosyası (varsayılan: bellek)")
    ayristirici.add_argument("--tz", default=TZID, help="IANA saat dilimi")
    ayristirici.add_argument("--port", type=int, default=8765)
    ayristirici.add_argument("--host", default="127.0.0.1")
    ayristirici.add_argument("--demo", action="store_true", help="örnek veriyle doldur")
    ayristirici.add_argument("--no-browser", action="store_true", help="tarayıcıyı açma")
    ayristirici.add_argument("--verbose", action="store_true")
    args = ayristirici.parse_args(argv)

    repo = Repo.open(args.db)
    if args.demo:
        if repo.list_calendars():
            print("--demo: veritabanı dolu, örnek veri eklenmedi")
        else:
            seed(repo, date.today())
            print("--demo: örnek veri yazıldı")

    if not args.no_browser:
        webbrowser.open(f"http://{args.host}:{args.port}")

    try:
        serve(repo, args.tz, args.host, args.port, args.verbose)
    finally:
        repo.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
