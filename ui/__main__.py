"""`python -m ui` giriş noktası.

Örnek:
    .venv/Scripts/python.exe -m ui --demo
    .venv/Scripts/python.exe -m ui --db takvim.db --reminder
    .venv/Scripts/python.exe -m ui --tarayici      # pencere yerine tarayıcı
    .venv/Scripts/python.exe -m ui --no-browser    # yalnızca sunucu

Son kullanıcı bunu masaüstündeki kısayoldan çalıştırıyor ve uygulama KENDİ
PENCERESİNDE açılıyor (bkz. `ui/pencere.py`). Buradaki hata yönetimi buna göre:
pencere sessizce kapanıp geriye hiçbir şey bırakmasın.

Sıralama önemli ve bilinçli:

    tek örnek kilidi -> depo -> hatırlatıcı -> sunucu (arka plan thread) -> pencere (ana thread)

`webview.start()` ana thread'de çalışmak ZORUNDA ve pencere kapanana kadar geri
dönmüyor; bu yüzden HTTP sunucusu arka plana taşındı. Depo `check_same_thread=
False` ile açılıyor, çünkü bağlantıyı burada kurup sunucu thread'inde
kullanıyoruz — erişim yine SIRALI, sunucu tek thread'li (bkz. `make_server`).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import threading
import traceback
import webbrowser
from datetime import date
from pathlib import Path

from core.console import guvenli_konsol
from store import Repo, yedek_al, yedek_klasoru

from .ayarlar import ayar_dosyasi, ayar_oku
from .demo import TZID, seed
from .pencere import BASLIK, pencere_ac
from .server import bos_port_bul, make_server, serve
from .tek_ornek import kilit_adi, kilit_al, pencereyi_one_al, pid_oku, pid_yaz


def varsayilan_db() -> str:
    """Veritabanının varsayılan yeri.

    Paketlenmiş (.exe) çalışırken çalışma dizini uygulamanın kurulu olduğu yer
    olur ve orası yazılabilir olmayabilir (Program Files). Bu yüzden veriyi
    kullanıcının kendi uygulama veri klasörüne yazıyoruz. Geliştirme
    çalıştırmasında ise proje kökü daha pratik.
    """
    if getattr(sys, "frozen", False):
        kok = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Takvim"
        try:
            kok.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Veri klasörü oluşturulamıyor: yönlendirilmiş LOCALAPPDATA, disk
            # kotası, kurum ilkesi. Uygulamayı hiç açmamaktansa geçici klasöre
            # düşüyoruz -- veri kalıcı olmaz ama takvim çalışır ve kullanıcı
            # neden olduğunu günlükte görür.
            import tempfile

            print("Veri klasörü açılamadı; geçici klasöre düşülüyor.", flush=True)
            kok = Path(tempfile.gettempdir()) / "Takvim"
            kok.mkdir(parents=True, exist_ok=True)
        return str(kok / "takvim.db")
    return "takvim.db"


def veri_dizini(db: str) -> Path:
    """Pencere konumu ve WebView2 önbelleği için yazılabilir klasör.

    Veritabanının YANINDA: ikisi de "bu kullanıcının Takvim durumu" ve o klasör
    yazılabilir olduğu zaten kanıtlanmış oluyor (DB oraya yazılıyor).
    """
    if db == ":memory:":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Takvim"
    return Path(db).resolve().parent


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

    Uygulama penceresiz (`console=False`) paketleniyor; bir istisna açılışı
    keserse kullanıcı ekranda HİÇBİR ŞEY görmez ve haklı olarak "çalışmıyor"
    der. Konsola yazmak yetmediği için ayrıca bir uyarı penceresi gösteriyoruz.
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
        # `Exception`ın tamamı yakalanıyor: penceresiz paketlenmiş uygulamada
        # `input()` stdin olmadığı için `RuntimeError` atıyor ve o hata buradan
        # kaçarsa hata mesajını göstermeye çalışırken yeni bir hata doğuyor.
        try:
            input("Kapatmak için Enter'a bas...")
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    """Komut satırını çözer ve uygulamayı başlatır."""
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
    ayristirici.add_argument(
        "--tarayici", action="store_true", help="masaüstü penceresi yerine tarayıcıda aç"
    )
    ayristirici.add_argument(
        "--no-browser",
        action="store_true",
        help="ne pencere ne tarayıcı; yalnızca sunucuyu çalıştır",
    )
    ayristirici.add_argument(
        "--coklu",
        action="store_true",
        help="tek örnek kilidini atla (aynı anda ikinci bir örnek aç)",
    )
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

    # Mutex tutamağı işletim sistemine ait; süreç bitene kadar açık kalıyor ve
    # kilidi o tutuyor. Burada bir değişkende tutmamızın tek sebebi, gerekirse
    # açıkça kapatabilmek ve kilidin nerede alındığının okunur olması.
    # `--no-browser` kilit ALMAZ: o kip penceresiz bir arka plan kopyasıdır
    # (otomatik başlatma `--no-browser --reminder` ile çalışıyor) ve kilidi
    # alsaydı sonradan tıklanan kısayol "zaten açık" deyip kapanırdı — ortada
    # öne alınacak bir pencere olmadığı hâlde. Arka plan kopyaları birbirini
    # engellemiyor; mükerrer bildirimi `reminder_fired` UNIQUE kısıtı, port
    # çakışmasını `bos_port_bul` çözüyor.
    if not args.coklu and args.db != ":memory:" and not args.no_browser:
        alindi, _kilit = kilit_al(kilit_adi(args.db))
        if not alindi:
            print("Takvim zaten açık; var olan pencere öne alınıyor.", flush=True)
            # Süreç numarasıyla arıyoruz: aynı başlığı taşıyan başka bir
            # pencereyi (örneğin veri klasörünü açan Explorer) öne almayalım.
            pencereyi_one_al(BASLIK, pid=pid_oku(veri_dizini(args.db)))
            return 0
        pid_yaz(veri_dizini(args.db))

    # Sunucu yalnızca `--no-browser`da ana thread'de çalışıyor; pencereli
    # çalıştırmada arka plan thread'ine geçiyor ve bağlantı burada kurulduğu
    # için sqlite3'ün thread kontrolünü kapatmamız gerekiyor. Sunucu TEK
    # THREAD'li olduğundan erişim yine sıralı (bkz. `make_server`).
    try:
        repo = Repo.open(args.db, check_same_thread=args.no_browser)
    except sqlite3.DatabaseError as hata:
        # Bozuk ya da okunamayan veritabanı: kullanıcıya çıkış yolunu göster.
        # "Veritabanı bozuk" mesajı tek başına çaresizlik, yedeklerin yeri
        # kurtarma demek.
        raise RuntimeError(
            f"Veritabanı açılamadı: {hata}. "
            f"Yedekler burada: {yedek_klasoru(veri_dizini(args.db))}"
        ) from hata

    try:
        # Yedek EN BAŞTA alınıyor: bir sonraki adımda migration çalışabilir ve
        # migration'dan önceki hâlin kopyası, işler ters giderse geri dönülecek
        # tek nokta.
        if args.db != ":memory:":
            alinan = yedek_al(repo.conn, veri_dizini(args.db), bugun=date.today())
            print(f"Yedek: {alinan}" if alinan else "Yedek alınamadı (takvim çalışıyor).", flush=True)

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

        print(f"Veritabanı: {args.db}", flush=True)

        if args.no_browser:
            # Ön yüz yok: sunucu ana thread'de, Ctrl+C'ye kadar. Testler ve
            # "başka bir tarayıcıdan bağlanayım" durumu için. DB yolu da
            # geçiliyor ki Yedekler ve Ayarlar uçları çalışsın.
            serve(
                repo, args.tz, args.host, port, args.verbose,
                db_yolu=None if args.db == ":memory:" else args.db,
            )
            return 0

        return _onyuzle_calistir(args, repo, port)
    finally:
        repo.close()


def _onyuzle_calistir(args, repo, port: int) -> int:
    """Sunucuyu arka planda, ön yüzü ana thread'de çalıştırır.

    Ön yüz (pencere ya da tarayıcı) kapanınca sunucu durduruluyor ve süreç
    bitiyor. Sıra önemli: sunucu DİNLEMEYE başlamadan pencereyi açarsak
    WebView2 boş sayfa gösterir ve kullanıcı "açılmıyor" der.
    """
    httpd = make_server(
        repo,
        args.tz,
        args.host,
        port,
        args.verbose,
        # Bellek DB'sinde yedekten dönüş anlamsız; uçlar boş/ret dönüyor.
        db_yolu=None if args.db == ":memory:" else args.db,
    )
    gercek_port = httpd.server_address[1]
    url = f"http://{args.host}:{gercek_port}"
    print(f"Takvim: {url}", flush=True)

    sunucu = threading.Thread(target=httpd.serve_forever, name="sunucu", daemon=True)
    sunucu.start()
    try:
        _onyuz_ac(url, veri_dizini(args.db), args.tarayici)
    finally:
        # `shutdown()` BAŞKA bir thread'den çağrılmalı — serve_forever döngüsü
        # sunucu thread'inde dönüyor, oradan çağırmak kilitlenirdi.
        httpd.shutdown()
        httpd.server_close()
        sunucu.join(timeout=3)
    return 0


def _onyuz_ac(url: str, dizin: Path, tarayici_zorla: bool) -> None:
    """Ön yüzü açar ve KAPANANA kadar bloklar.

    Pencere açılamazsa (WebView2 çalışma zamanı yok, eski Windows, bozuk
    kurulum) uygulamayı ölü bırakmıyoruz: tarayıcıya düşüyoruz. Kullanıcı için
    "çirkin ama çalışıyor", "hiç açılmıyor"dan iyidir.
    """
    sebep = ""
    if not tarayici_zorla:
        try:
            # Tepsi kararı her kapanışta dosyadan okunuyor: ayar değişince
            # yeniden başlatma gerekmiyor. Okuma patlarsa pencere normal kapanır.
            ayar_yolu = ayar_dosyasi(dizin)
            pencere_ac(url, dizin, tepsi_istendi=lambda: bool(ayar_oku(ayar_yolu).get("tepsiye_kucult", False)))
            return
        except Exception as hata:
            traceback.print_exc()
            sebep = str(hata) or type(hata).__name__
            print(f"Masaüstü penceresi açılamadı; tarayıcıya düşülüyor. ({sebep})", flush=True)

    webbrowser.open(url)
    _tarayici_bekle(url, sebep)


def _tarayici_bekle(url: str, sebep: str = "") -> None:
    """Tarayıcı geri düşüşünde süreci ayakta tutar.

    Tarayıcı ayrı bir süreç: sekmeyi kapatmak sunucuyu durdurmaz. Penceresiz
    paketlenmiş uygulamada geriye görünmez bir süreç kalmasın diye küçük bir
    denetim penceresi gösteriyoruz — kapatınca uygulama da kapanıyor.
    """
    try:
        import tkinter as tk

        kok = tk.Tk()
        kok.title(BASLIK)
        kok.resizable(False, False)
        tk.Label(
            kok,
            padx=24,
            pady=16,
            justify="left",
            text=(
                "Takvim tarayıcıda açıldı:\n"
                f"{url}\n\n"
                + (f"Sebep: {sebep}\n\n" if sebep else "")
                + "Bu pencereyi kapatınca uygulama da kapanır."
            ),
        ).pack()
        tk.Button(kok, text="Takvim'i kapat", command=kok.destroy, padx=12).pack(pady=(0, 16))
        kok.mainloop()
    except Exception:
        # Ekran/tkinter yoksa (başsız çalıştırma) sonsuza kadar bekle: Ctrl+C
        # ya da süreci sonlandırmak tek çıkış.
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print("\nkapatılıyor...", flush=True)


if __name__ == "__main__":
    sys.exit(main())
