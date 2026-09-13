"""Son kullanıcı giriş noktası — PyInstaller bunu `.exe` hâline getiriyor.

Varsayılanlar son kullanıcıya göre: kalıcı veritabanı, hatırlatıcı açık,
tarayıcı otomatik açılıyor. Komut satırı bayrakları yine geçerli.
"""

from __future__ import annotations

import multiprocessing
import sys

from ui.__main__ import main

if __name__ == "__main__":
    # PyInstaller ile paketlenmiş uygulamada, bir alt süreç başlatılırsa
    # uygulamanın kendisi yeniden çalışır. Bu çağrı onu engelliyor.
    multiprocessing.freeze_support()
    sys.exit(main(["--reminder", *sys.argv[1:]]))
