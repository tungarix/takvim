"""Wi-Fi eşleştirme sunucusunu tek komutla bağımsız başlatır (YALNIZ geliştirme).

Mobil istemciyi (`..\\takvim-mobil`) masaüstü arayüzü olmadan uçtan uca denemek için:
sertifika + token + bağlantı yazdırılır, istemci bağlanır, telefondan gelen `POST`
otomatik ONAYLANIR (gerçek uygulamada burada masaüstü onay penceresi var). exe'ye
GİRMEZ; üretim kodunun özel-IP kuralını gevşetmez, yalnızca `--test-ip` ile bu
betiğe özel bir istisna tanır.

    .venv\\Scripts\\python.exe scripts/wifi_sunucu_dene.py                    # gerçek özel ağ IP'si
    .venv\\Scripts\\python.exe scripts/wifi_sunucu_dene.py --test-ip 127.0.0.1 # loopback

Veritabanı: `--db` verilmezse geçici klasörde örnek verili taze bir DB (gerçek
%LOCALAPPDATA%\\Takvim\\takvim.db'ye DOKUNULMAZ). Oturum 3 dakikada ya da ilk
`POST`'tan sonra kapanır; Ctrl+C ile de çıkılır.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from senkron import WifiYonetici
from store import Repo
from ui.demo import seed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--test-ip", help="özel ağ yerine bu IP'ye bağlan (ör. 127.0.0.1)")
    ap.add_argument("--db", help="kullanılacak veritabanı (varsayılan: geçici örnek DB)")
    args = ap.parse_args(argv)

    gecici = None
    if args.db:
        db = args.db
    else:
        gecici = tempfile.TemporaryDirectory(prefix="takvim-wifi-dene-")
        db = str(Path(gecici.name) / "takvim.db")
        with Repo.open(db) as repo:
            seed(repo, date.today())

    @contextmanager
    def depo_ac():
        repo = Repo.open(db)
        try:
            yield repo
        finally:
            repo.close()

    ayar: dict = {}
    if args.test_ip:
        ayar = {"ip_bul": lambda: args.test_ip, "test_ipleri": frozenset({args.test_ip})}
    yonetici = WifiYonetici(
        depo_ac=depo_ac, cihaz_adi="Takvim-dene", cihaz_id="wifi-sunucu-dene",
        uygulama="desktop dene", **ayar,
    )
    try:
        bilgi = yonetici.baslat()
        print(f"Adres: {bilgi['ip']}:{bilgi['port']}")
        print(f"Parmak izi (f): {bilgi['parmak_izi']}")
        print(f"Bağlantı: {bilgi['baglanti']}")
        print("Telefondan gelen POST otomatik onaylanır. Durdurmak için Ctrl+C.", flush=True)
        onaylandi = False
        while True:
            d = yonetici.durum()
            if d["asama"] == "onay_bekliyor" and not onaylandi:
                print(f"POST geldi: {d['ozet']}; onaylanıyor.", flush=True)
                yonetici.karar(True)
                onaylandi = True
            if d["asama"] == "bitti":
                print(f"Oturum bitti: {d['sonuc']}  rapor={d['rapor']}")
                return 0 if d["sonuc"] == "birlestirildi" else 1
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 130
    finally:
        yonetici.kapat()
        if gecici is not None:
            gecici.cleanup()


if __name__ == "__main__":
    sys.exit(main())
