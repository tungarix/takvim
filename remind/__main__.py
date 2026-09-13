"""`python -m remind` giriş noktası.

Örnek:
    .venv/Scripts/python.exe -m remind --db takvim.db
    .venv/Scripts/python.exe -m remind --db takvim.db --once --notifier console
    .venv/Scripts/python.exe -m remind --test
"""

from __future__ import annotations

import argparse
import sys

from core.console import guvenli_konsol
from store import Repo

from .daemon import run_forever, run_once
from .notifier import pick_notifier


def main(argv: list[str] | None = None) -> int:
    """Komut satırını çözer ve hatırlatıcıyı çalıştırır."""
    ap = argparse.ArgumentParser(prog="remind", description="Takvim hatırlatıcısı")
    ap.add_argument("--db", default="takvim.db", help="SQLite dosyası")
    ap.add_argument("--tz", default="Europe/Istanbul", help="IANA saat dilimi")
    ap.add_argument("--poll", type=int, default=60, help="en uzun yoklama aralığı (sn)")
    ap.add_argument(
        "--notifier", default="auto", choices=["auto", "toast", "tk", "console"]
    )
    ap.add_argument("--once", action="store_true", help="tek tur çalış ve çık")
    ap.add_argument("--test", action="store_true", help="örnek bildirim gösterip çık")
    ap.add_argument("--verbose", action="store_true")
    guvenli_konsol()
    args = ap.parse_args(argv)

    notifier = pick_notifier(args.notifier)

    if args.test:
        ok = notifier.notify(
            "Takvim hatırlatıcı testi", "Bunu görüyorsan bildirimler çalışıyor."
        )
        print(f"{type(notifier).__name__}: {'gönderildi' if ok else 'BAŞARISIZ'}")
        return 0 if ok else 1

    with Repo.open(args.db) as repo:
        if args.once:
            gonderilen = run_once(repo, args.tz, notifier)
            print(f"{len(gonderilen)} hatırlatıcı gönderildi.")
            return 0
        run_forever(repo, args.tz, notifier, poll_seconds=args.poll, verbose=args.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
