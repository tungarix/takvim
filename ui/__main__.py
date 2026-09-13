"""`python -m ui` giriş noktası.

Örnek:
    .venv/Scripts/python.exe -m ui --demo
    .venv/Scripts/python.exe -m ui --db takvim.db --reminder
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from datetime import date

from core.console import guvenli_konsol
from store import Repo

from .demo import TZID, seed
from .server import serve


def _hatirlatici_baslat(db: str, tzid: str) -> threading.Thread:
    """Hatırlatıcıyı arka plan thread'inde başlatır.

    Thread KENDİ `Repo`sunu açıyor, sunucununkini paylaşmıyor: sqlite3
    bağlantıları thread'e bağlı ve paylaşmak "created in a thread can only be
    used in that same thread" hatası verirdi. İki ayrı bağlantı SQLite'ta
    sorunsuz; mükerrer bildirimi zaten `reminder_fired` UNIQUE kısıtı
    engelliyor.

    Ayrı süreç olarak da çalıştırılabilir (`python -m remind`); bu bayrak
    yalnızca "tek kısayolla her şey açılsın" kolaylığı için.
    """

    def calis() -> None:
        from remind import pick_notifier, run_forever

        with Repo.open(db) as kendi_repo:
            run_forever(kendi_repo, tzid, pick_notifier())

    thread = threading.Thread(target=calis, name="hatirlatici", daemon=True)
    thread.start()
    return thread


def varsayilan_takvim_saglat(repo) -> bool:
    """Hiç takvim yoksa varsayılan birini açar; açtıysa True döndürür.

    İlk açılışta takvim olmazsa hızlı ekleme "önce bir takvim oluşturulmalı"
    diye reddeder ve kullanıcı hiçbir şey yapamaz. Boş bir ekranla karşılamak
    yerine kullanılabilir bir uygulama veriyoruz.
    """
    if repo.list_calendars():
        return False
    repo.add_calendar("Kişisel", "#3b82f6")
    return True


def main(argv: list[str] | None = None) -> int:
    """Komut satırını çözer ve sunucuyu başlatır."""
    ayristirici = argparse.ArgumentParser(prog="ui", description="Takvim")
    ayristirici.add_argument("--db", default=":memory:", help="SQLite dosyası (varsayılan: bellek)")
    ayristirici.add_argument("--tz", default=TZID, help="IANA saat dilimi")
    ayristirici.add_argument("--port", type=int, default=8765)
    ayristirici.add_argument("--host", default="127.0.0.1")
    ayristirici.add_argument("--demo", action="store_true", help="örnek veriyle doldur")
    ayristirici.add_argument(
        "--reminder", action="store_true", help="hatırlatıcıyı da başlat"
    )
    ayristirici.add_argument("--no-browser", action="store_true", help="tarayıcıyı açma")
    ayristirici.add_argument("--verbose", action="store_true")
    guvenli_konsol()
    args = ayristirici.parse_args(argv)

    repo = Repo.open(args.db)
    if args.demo:
        if repo.list_calendars():
            print("--demo: veritabanı dolu, örnek veri eklenmedi", flush=True)
        else:
            seed(repo, date.today())
            print("--demo: örnek veri yazıldı", flush=True)
    elif varsayilan_takvim_saglat(repo):
        print("İlk açılış: 'Kişisel' takvimi oluşturuldu.", flush=True)

    if args.reminder:
        if args.db == ":memory:":
            # Bellek DB'si her bağlantıda ayrı; hatırlatıcı thread'i bomboş bir
            # veritabanı görürdü. Sessizce çalışmıyor görünmektense söylüyoruz.
            print("--reminder: bellek veritabanıyla çalışmaz, --db dosya ver", flush=True)
        else:
            _hatirlatici_baslat(args.db, args.tz)
            print("Hatırlatıcı arka planda çalışıyor.", flush=True)

    if not args.no_browser:
        webbrowser.open(f"http://{args.host}:{args.port}")

    try:
        serve(repo, args.tz, args.host, args.port, args.verbose)
    finally:
        repo.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
