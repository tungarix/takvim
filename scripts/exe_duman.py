"""Paketlenmiş `Takvim.exe`'yi geçici bir veritabanıyla açıp gerçekten çalıştığını sınar.

Release workflow'u derlemeden SONRA bunu çalıştırıyor: testler kaynak kodu
sınıyor, ama kullanıcıya giden şey `.exe`. Paketlemede bir veri dosyası
unutulursa (AGENTS 27) uygulama açılır ve boş sayfa gösterir; sürüm numarası
yükseltilmeyi unutulursa Ayarlar yanlış sürümü söyler. İkisi de testlerden
geçer, ancak exe çalıştırılınca görünür.

Kullanım:
    python scripts/exe_duman.py [--exe dist/Takvim.exe] [--etiket v1.5.0]

`--etiket` verilmezse `ETIKET` ortam değişkenine bakılır (workflow onu
yalnızca etiketli çalıştırmada doldurur); boşsa etiket karşılaştırması atlanır.
Çıkış kodu 0 = her şey yolunda, 1 = en az bir kontrol başarısız.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
BEKLEME_SN = 90  # soğuk başlatma: tek dosyalık exe önce kendini açıyor


def kaynak_surumu(kok: Path = KOK) -> str:
    """`ui/surum.py`'deki `SURUM`'u import etmeden okur (bağımlılık gerekmesin)."""
    metin = (kok / "ui" / "surum.py").read_text(encoding="utf-8")
    eslesme = re.search(r'^SURUM\s*=\s*"([^"]+)"', metin, re.MULTILINE)
    if eslesme is None:
        raise ValueError("ui/surum.py içinde SURUM bulunamadı")
    return eslesme.group(1)


def etiket_uyumu(etiket: str, surum: str) -> str | None:
    """Etiket `v<SURUM>` değilse açıklayıcı bir hata metni, uyumluysa None döndürür."""
    if etiket != f"v{surum}":
        return f"etiket {etiket!r} ama ui/surum.py {surum!r} diyor (beklenen v{surum})"
    return None


def son_migration(kok: Path = KOK) -> int:
    """`store/migrations/` içindeki en büyük numara: güncel şemanın `user_version`'ı."""
    numaralar = [
        int(p.name.split("_", 1)[0])
        for p in (kok / "store" / "migrations").glob("*.sql")
        if p.name.split("_", 1)[0].isdigit()
    ]
    if not numaralar:
        raise ValueError("store/migrations/ içinde migration yok")
    return max(numaralar)


def gercek_veri_izi() -> tuple[bool, float | None]:
    """Kullanıcının GERÇEK veritabanının var olup olmadığı ve son değişme zamanı.

    Deneme bu dosyaya dokunmamalı. Önce ve sonra alınan iz karşılaştırılıyor.
    """
    yol = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Takvim" / "takvim.db"
    try:
        return True, yol.stat().st_mtime
    except OSError:
        return False, None


def bos_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wifi_denemesi(deneme: Deneme) -> None:
    """Wi-Fi eşleştirme: paketli exe sertifika üretip TLS sunabiliyor mu.

    `cryptography` yalnızca eşleştirme başlatılınca içeriden import ediliyor
    (`senkron/wifi.py::sertifika_uret`): paketlemede eksik kalırsa uygulama
    açılır, her şey çalışır ve hata ilk gerçek kullanımda çıkar. Bu yüzden
    burada gerçekten başlatıp parmak izini TLS'ten okuyoruz. Makinede özel ağ
    yoksa (bağlantısız CI) atlanır: hata değil, sınanamadı.
    """
    durum, govde = deneme.istek("/api/senkron/wifi/baslat", {})
    yanit = json.loads(govde)
    if durum == 400 and yanit.get("error_code") in ("wifi_ag_yok", "wifi_ozel_ag_degil"):
        print(f"  atla Wi-Fi eşleştirme sınanamadı: özel ağ yok ({yanit['error_code']})")
        return
    deneme.kontrol(durum == 200, "Wi-Fi eşleştirme başladı", f"HTTP {durum} {yanit.get('error_code', '')}")
    if durum != 200:
        return
    try:
        baglam = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        baglam.check_hostname = False
        baglam.verify_mode = ssl.CERT_NONE
        with socket.create_connection((yanit["ip"], yanit["port"]), timeout=10) as ham:
            with baglam.wrap_socket(ham) as tls:
                der = tls.getpeercert(binary_form=True)
        parmak = base64.urlsafe_b64encode(hashlib.sha256(der).digest()).rstrip(b"=").decode()
        deneme.kontrol(parmak == yanit["parmak_izi"], "Wi-Fi sertifika parmak izi QR'dakiyle aynı")
    except OSError as hata:  # Güvenlik duvarı kendi IP'ye bağlantıyı kesmez, ama kesilirse belli olsun
        deneme.kontrol(False, "Wi-Fi sunucusuna TLS ile bağlanıldı", str(hata))
    finally:
        deneme.istek("/api/senkron/wifi/iptal", {})


class Deneme:
    """Çalışan exe'ye istek atan, sonuçları toplayan küçük yardımcı."""

    def __init__(self, port: int) -> None:
        self.temel = f"http://127.0.0.1:{port}"
        self.hatalar: list[str] = []

    def istek(self, yol: str, govde: dict | None = None) -> tuple[int, bytes]:
        veri = None if govde is None else json.dumps(govde).encode("utf-8")
        istek = urllib.request.Request(
            self.temel + yol,
            data=veri,
            method="GET" if govde is None else "POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(istek, timeout=15) as yanit:
                return yanit.status, yanit.read()
        except urllib.error.HTTPError as hata:
            return hata.code, hata.read()

    def kontrol(self, kosul: bool, ad: str, ayrinti: str = "") -> None:
        print(("  ok   " if kosul else "  HATA ") + ad + (f" ({ayrinti})" if ayrinti else ""))
        if not kosul:
            self.hatalar.append(ad + (f": {ayrinti}" if ayrinti else ""))


def _hazir_bekle(deneme: Deneme, surec: subprocess.Popen) -> dict | None:
    bitis = time.monotonic() + BEKLEME_SN
    while time.monotonic() < bitis:
        if surec.poll() is not None:
            return None  # exe kendiliğinden kapandı
        try:
            durum, govde = deneme.istek("/api/ayarlar")
            if durum == 200:
                return json.loads(govde)
        except OSError:
            pass
        time.sleep(0.5)
    return None


def _kapat(surec: subprocess.Popen) -> None:
    """Exe'yi alt süreçleriyle birlikte kapatır.

    Tek dosyalık PyInstaller exe'si bir önyükleyici + asıl süreçten oluşuyor;
    yalnızca önyükleyiciyi sonlandırmak asıl süreci (ve dinlediği portu) açık
    bırakır.
    """
    if surec.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(surec.pid)],
                capture_output=True,
                check=False,
            )
        else:
            surec.kill()
    try:
        surec.wait(timeout=15)
    except subprocess.TimeoutExpired:
        surec.kill()


def eski_surum_kur(db: Path, gecici: Path) -> int:
    """Yükseltme senaryosu: bir ÖNCEKİ şemada, içinde bir takvim olan DB kurar.

    Boş bir dosya "yeni kurulum" sayılır ve yedeklenmez (AGENTS 55); yedeğin
    migration'dan ÖNCE alındığını ancak gerçekten yükseltilecek bir DB gösterir.
    Önceki şemanın kendisi geçici bir klasöre kopyalanan migration dosyalarıyla
    kurulur: şema bilgisi burada ikinci kez yazılmıyor.
    """
    adimlar = sorted((KOK / "store" / "migrations").glob("[0-9]*.sql"))
    kopya = gecici / "eski-migrations"
    kopya.mkdir()
    for yol in adimlar[:-1]:
        (kopya / yol.name).write_bytes(yol.read_bytes())
    sys.path.insert(0, str(KOK))
    from store.migrator import migrate

    baglanti = sqlite3.connect(db)
    try:
        surum = migrate(baglanti, kopya)
        baglanti.execute(
            "INSERT INTO calendars (name, color, visible, created_at) "
            "VALUES ('Yükseltme denemesi', '#3b82f6', 1, '2026-01-01T00:00:00Z')"
        )
        baglanti.commit()
    finally:
        baglanti.close()
    return surum


def calistir(exe: Path, etiket: str) -> list[str]:
    """Bütün kontrolleri yapar, başarısız olanların listesini döndürür."""
    surum = kaynak_surumu()
    hatalar: list[str] = []
    if etiket:
        sorun = etiket_uyumu(etiket, surum)
        print(("  HATA " + sorun) if sorun else f"  ok   etiket {etiket} = ui/surum.py")
        if sorun:
            hatalar.append(sorun)
    if not exe.is_file():
        return [*hatalar, f"exe bulunamadı: {exe}"]

    once = gercek_veri_izi()
    # `ignore_cleanup_errors`: sonlandırılan exe dosya tutamağını bir an geç
    # bırakabiliyor; temizlenemeyen geçici klasör denemeyi başarısız saymaz.
    with tempfile.TemporaryDirectory(prefix="takvim-duman-", ignore_cleanup_errors=True) as gecici:
        db = Path(gecici) / "takvim.db"
        eski_surum = eski_surum_kur(db, Path(gecici))
        port = bos_port()
        deneme = Deneme(port)
        surec = subprocess.Popen(
            [str(exe), "--no-browser", "--db", str(db), "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            ayar = _hazir_bekle(deneme, surec)
            deneme.kontrol(ayar is not None, f"exe {BEKLEME_SN} sn içinde yanıt verdi")
            if ayar is not None:
                deneme.kontrol(
                    ayar.get("surum") == surum,
                    "exe'nin bildirdiği sürüm ui/surum.py ile aynı",
                    f"exe {ayar.get('surum')!r}, kaynak {surum!r}",
                )

                durum, sayfa = deneme.istek("/")
                deneme.kontrol(durum == 200 and b"app.js" in sayfa, "ana sayfa paketli")
                for dosya in ("app.js", "i18n.js", "style.css", "qrcode.js"):
                    durum, icerik = deneme.istek("/" + dosya)
                    deneme.kontrol(durum == 200 and len(icerik) > 1000, f"{dosya} paketli")

                durum, _ = deneme.istek("/api/events", {"text": "yarın 10:00 duman testi"})
                deneme.kontrol(durum in (200, 201), "hızlı ekleme ile etkinlik yazıldı", f"HTTP {durum}")
                durum, _ = deneme.istek("/api/tasks", {"title": "duman görevi"})
                deneme.kontrol(durum in (200, 201), "görev yazıldı", f"HTTP {durum}")
                durum, ics = deneme.istek("/api/export")
                metin = ics.decode("utf-8", "replace")
                deneme.kontrol(
                    durum == 200 and "duman testi" in metin and "BEGIN:VTODO" in metin,
                    ".ics dışa aktarma etkinliği ve görevi içeriyor",
                )

                wifi_denemesi(deneme)

                # `with sqlite3.connect(...)` bağlantıyı KAPATMAZ; açık kalırsa
                # Windows geçici klasörü silmeye izin vermiyor.
                baglanti = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                try:
                    surum_db = baglanti.execute("PRAGMA user_version").fetchone()[0]
                finally:
                    baglanti.close()
                beklenen = son_migration()
                deneme.kontrol(
                    surum_db == beklenen,
                    "şema güncel",
                    f"user_version {surum_db}, son migration {beklenen}",
                )
                yedekler = sorted((Path(gecici) / "yedek").glob("takvim-*.db"))
                deneme.kontrol(bool(yedekler), "açılış yedeği alındı")
                if yedekler:
                    # Yedek migration'dan ÖNCE alınmalı: eski şemada ve veri duruyor.
                    yedek_baglanti = sqlite3.connect(f"file:{yedekler[-1]}?mode=ro", uri=True)
                    try:
                        yedek_surum = yedek_baglanti.execute("PRAGMA user_version").fetchone()[0]
                    finally:
                        yedek_baglanti.close()
                    deneme.kontrol(
                        yedek_surum == eski_surum,
                        "yedek migration'dan önceki şemada",
                        f"yedek user_version {yedek_surum}, beklenen {eski_surum}",
                    )
                baglanti = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                try:
                    takvim_sayisi = baglanti.execute(
                        "SELECT COUNT(*) FROM calendars WHERE name = 'Yükseltme denemesi'"
                    ).fetchone()[0]
                finally:
                    baglanti.close()
                deneme.kontrol(takvim_sayisi == 1, "yükseltmede mevcut veri korundu")
        finally:
            _kapat(surec)
        hatalar += deneme.hatalar

    sonra = gercek_veri_izi()
    dokunulmadi = once == sonra
    print(("  ok   " if dokunulmadi else "  HATA ") + "gerçek veritabanına dokunulmadı")
    if not dokunulmadi:
        hatalar.append(f"gerçek veritabanı değişti: önce {once}, sonra {sonra}")
    return hatalar


def _konsolu_hazirla() -> None:
    """Çıktıyı UTF-8'e sabitler; yazılamayan karakter hata değil `?` olur.

    GitHub'ın Windows runner'ında konsol cp1252: Türkçe "ı" yazdırılırken
    `UnicodeEncodeError` betiği çökertiyordu (v1.6.0'ın ilk denemesi). Exe
    sağlamken sürümü durduran şey testin kendi çıktısı olmamalı.
    """
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _konsolu_hazirla()
    ayristirici = argparse.ArgumentParser(description="Takvim.exe duman testi")
    ayristirici.add_argument("--exe", type=Path, default=KOK / "dist" / "Takvim.exe")
    ayristirici.add_argument("--etiket", default=os.environ.get("ETIKET", ""))
    args = ayristirici.parse_args(argv)

    print(f"Takvim.exe duman testi: {args.exe}")
    hatalar = calistir(args.exe, args.etiket.strip())
    if hatalar:
        print(f"\n{len(hatalar)} kontrol başarısız:")
        for hata in hatalar:
            print(f"  - {hata}")
        return 1
    print("\nHepsi geçti.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
