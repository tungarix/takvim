"""`python -m ui` giriş noktası.

Örnek:
    .venv/Scripts/python.exe -m ui --demo
    .venv/Scripts/python.exe -m ui --db takvim.db --reminder

Son kullanıcı bunu masaüstündeki kısayoldan çalıştırıyor. Buradaki hata
yönetimi buna göre: pencere sessizce kapanıp geriye hiçbir şey bırakmasın.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import traceback
import webbrowser
from datetime import date
from pathlib import Path

from core.console import guvenli_konsol
from store import Repo

from .demo import TZID, seed
from .server import bos_port_bul, serve

def varsayilan_db() -> str:
    """Veritabanının varsayılan yeri.

    Paketlenmiş (.exe) çalışırken çalışma dizini uygulamanın kurulu olduğu yer
    olur ve orası yazılabilir olmayabilir (Program Files). Bu yüzden veriyi
    kullanıcının kendi uygulama veri klasörüne yazıyoruz. Geliştirme
    çalıştırmasında ise proje kökü daha pratik.
    """
    if getattr(sys, "frozen", False):
        kok = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Takvim"
        kok.mkdir(parents=True, exist_ok=True)
        return str(kok / "takvim.db")
    return "takvim.db"


def _hatirlatici_baslat(db: str, tzid: str) -> threading.Thread:
    """Hatırlatıcıyı arka plan thread'inde başlatır.

    Thread KENDİ `Repo`sunu açıyor, sunucununkini paylaşmıyor: sqlite3
    bağlantıları thread'e bağlı ve paylaşmak "created in a thread can only be
    used in that same thread" hatası verirdi. İki ayrı bağlantı SQLite'ta
    sorunsuz; mükerrer bildirimi zaten `reminder_fired` UNIQUE kısıtı
    engelliyor.

    Hatırlatıcı çökerse UYGULAMA ÇÖKMEZ: thread kendi hatasını yutup bildirir.
    Takvimi hiç görememek, hatırlatıcıyı kaybetmekten kötüdür.
    """

    def calis() -> None:
        try:
            from remind import pick_notifier, run_forever

            with Repo.open(db) as kendi_repo:
                run_forever(kendi_repo, tzid, pick_notifier())
        except Exception:
            print("Hatırlatıcı durdu (takvim çalışmaya devam ediyor):", flush=True)
            traceback.print_exc()

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


def _olumcul_hata(mesaj: str) -> None:
    """Kapanmadan önce hatayı GÖRÜNÜR kılar.

    Kısayol pencereyi küçültülmüş açıyor; bir istisna pencereyi kapatırsa
    kullanıcı ekranda hiçbir şey görmez ve haklı olarak "çalışmıyor" der.
    Konsola yazmak yetmediği için ayrıca bir uyarı penceresi gösteriyoruz.
    """
    print(f"\nHATA: {mesaj}\n", flush=True)
    try:
        import tkinter as tk
        from tkinter import messagebox

        kok = tk.Tk()
        kok.withdraw()
        messagebox.showerror("Takvim başlatılamadı", mesaj)
        kok.destroy()
    except Exception:
        # Ekran yoksa konsol çıktısı elimizdeki tek şey; kapanmadan bekletelim.
        try:
            input("Kapatmak için Enter'a bas...")
        except (EOFError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    """Komut satırını çözer ve sunucuyu başlatır."""
    guvenli_konsol()
    ayristirici = argparse.ArgumentParser(prog="ui", description="Takvim")
    ayristirici.add_argument(
        "--db", default=None, help="SQLite dosyası (varsayılan: takvim.db)"
    )
    ayristirici.add_argument("--tz", default=TZID, help="IANA saat dilimi")
    ayristirici.add_argument("--port", type=int, default=8765)
    ayristirici.add_argument("--host", default="127.0.0.1")
    ayristirici.add_argument("--demo", action="store_true", help="örnek veriyle doldur")
    ayristirici.add_argument(
        "--reminder", action="store_true", help="hatırlatıcıyı da başlat"
    )
    ayristirici.add_argument("--no-browser", action="store_true", help="tarayıcıyı açma")
    ayristirici.add_argument("--verbose", action="store_true")
    args = ayristirici.parse_args(argv)
    if args.db is None:
        args.db = varsayilan_db()

    try:
        return _calistir(args)
    except Exception as hata:  # son kullanıcıya boş ekran bırakma
        traceback.print_exc()
        _olumcul_hata(f"{type(hata).__name__}: {hata}")
        return 1


def _calistir(args) -> int:
    """Asıl akış; istisnalar `main` tarafından yakalanıyor."""
    if args.db != ":memory:":
        # Göreli yol kısayolun çalışma dizinine göre çözülür; mutlağa çevirip
        # hangi dosyanın açıldığını kesinleştiriyoruz.
        args.db = str(Path(args.db).resolve())

    repo = Repo.open(args.db)
    try:
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
                # Bellek DB'si her bağlantıda ayrı; hatırlatıcı thread'i bomboş
                # bir veritabanı görürdü. Sessizce çalışmıyor görünmesin.
                print(
                    "--reminder: bellek veritabanıyla çalışmaz, --db dosya ver",
                    flush=True,
                )
            else:
                _hatirlatici_baslat(args.db, args.tz)
                print("Hatırlatıcı arka planda çalışıyor.", flush=True)

        port = bos_port_bul(args.host, args.port)
        if port != args.port:
            print(f"{args.port} portu dolu, {port} kullanılıyor.", flush=True)

        def hazir(gercek_port: int) -> None:
            """Soket DİNLEMEYE BAŞLADIKTAN sonra tarayıcıyı aç.

            Daha önce tarayıcı `serve()` çağrılmadan açılıyordu; hızlı bir
            makinede henüz dinlemeyen porta gidip "siteye ulaşılamıyor"
            gösteriyordu. Son kullanıcı için bu "uygulama çalışmıyor" demek.
            """
            if not args.no_browser:
                webbrowser.open(f"http://{args.host}:{gercek_port}")

        print(f"Veritabanı: {args.db}", flush=True)
        serve(repo, args.tz, args.host, port, args.verbose, on_ready=hazir)
    finally:
        repo.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
