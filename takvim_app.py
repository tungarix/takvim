"""Son kullanıcı giriş noktası — PyInstaller bunu `.exe` hâline getiriyor.

Varsayılanlar son kullanıcıya göre: kalıcı veritabanı, hatırlatıcı açık,
uygulama KENDİ PENCERESİNDE açılıyor (tarayıcı değil). Komut satırı bayrakları
yine geçerli.

`.exe` penceresiz derleniyor (`console=False`), yani ortada siyah bir konsol
yok — ama o zaman `stdout`/`stderr` de yok. Aşağıdaki `_gunluge_yonlendir()`
onların yerine bir günlük dosyası koyuyor: bir şey ters gittiğinde
"hiçbir şey olmadı" yerine elimizde okunacak bir iz kalsın.
"""

from __future__ import annotations

import multiprocessing
import os
import sys
from pathlib import Path

# Aynı anda tutulacak en fazla günlük boyutu. Uygulama aylarca açık kalabilir;
# sınırsız büyüyen bir dosya bırakmak kabul edilemez.
_MAKS_GUNLUK = 1 * 1024 * 1024  # 1 MB


def _gunluk_yolu() -> Path:
    """Günlük dosyasının yeri — veritabanıyla aynı klasör."""
    kok = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Takvim"
    kok.mkdir(parents=True, exist_ok=True)
    return kok / "takvim.log"


def _gunluge_yonlendir() -> None:
    """Penceresiz `.exe`de `stdout`/`stderr`i günlük dosyasına bağlar.

    İki şeyi birden çözüyor:

    1. Penceresiz derlemede akışlar `None` oluyor. Python 3.14 bunu hoş görüyor
       (`print` sessizce hiçbir şey yapmıyor) ama `--verbose` ile çalışan
       `http.server` doğrudan `sys.stderr.write` çağırıyor ve `AttributeError`
       veriyordu.
    2. Hata ayıklanacak bir şey olduğunda kullanıcıdan "ekranda ne yazıyordu"
       diye soramıyoruz; günlük dosyası bunun yerine geçiyor.

    Başarısız olursa SESSİZCE geçiyor: günlük tutamamak uygulamayı açmamak
    için sebep değil.
    """
    if not getattr(sys, "frozen", False):
        return
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        yol = _gunluk_yolu()
        if yol.exists() and yol.stat().st_size > _MAKS_GUNLUK:
            yol.unlink()
        akis = open(yol, "a", encoding="utf-8", errors="replace", buffering=1)
        sys.stdout = akis
        sys.stderr = akis
    except OSError:
        pass


if __name__ == "__main__":
    # PyInstaller ile paketlenmiş uygulamada, bir alt süreç başlatılırsa
    # uygulamanın kendisi yeniden çalışır. Bu çağrı onu engelliyor.
    multiprocessing.freeze_support()
    _gunluge_yonlendir()

    # İçe aktarma günlük yönlendirmesinden SONRA: `ui` ağacı açılırken oluşan
    # bir hata da dosyaya düşsün.
    from ui.__main__ import main

    sys.exit(main(["--reminder", *sys.argv[1:]]))
