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
import json
import os
import re
import socket
import sqlite3
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
                for dosya in ("app.js", "i18n.js", "style.css"):
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
                deneme.kontrol(
                    any((Path(gecici) / "yedek").glob("takvim-*.db")),
                    "açılış yedeği alındı",
                )
        finally:
            _kapat(surec)
        hatalar += deneme.hatalar

    sonra = gercek_veri_izi()
    dokunulmadi = once == sonra
    print(("  ok   " if dokunulmadi else "  HATA ") + "gerçek veritabanına dokunulmadı")
    if not dokunulmadi:
        hatalar.append(f"gerçek veritabanı değişti: önce {once}, sonra {sonra}")
    return hatalar


def main(argv: list[str] | None = None) -> int:
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
