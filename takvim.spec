# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller yapılandırması — tek dosyalık Takvim.exe.

Veri dosyaları ELLE eklenmek zorunda: PyInstaller yalnızca import edilen
modülleri toplar, `ui/static/*` ve `store/migrations/*.sql` ise dosya olarak
okunuyor. Unutulurlarsa uygulama açılır ama boş bir sayfa gösterir ya da
migration bulunamadı diye ölür.

pywebview'in kendi dosyaları (WebView2 köprü DLL'leri ve enjekte ettiği JS)
ELLE EKLENMİYOR: paket kendi PyInstaller hook'unu getiriyor
(`webview/__pyinstaller/hook-webview.py`) ve `webview/lib` + `webview/js`
klasörlerini o topluyor. pythonnet tarafı da aynı şekilde (`hook-clr.py`,
`hook-clr_loader.py`). Buraya elle eklemek mükerrer dosya üretirdi.
"""

a = Analysis(
    ["takvim_app.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("ui/static", "ui/static"),
        ("store/migrations", "store/migrations"),
        ("store/schema.sql", "store"),
        # Tepsi simgesi dosya olarak okunuyor (ui/tepsi.py `simge_bul`);
        # import edilmiyor, yazılmazsa tepsi stok ikonla çalışır.
        ("takvim.ico", "."),
    ],
    hiddenimports=[
        # zoneinfo tzdata'yı dinamik okur; PyInstaller import göremez.
        "tzdata",
        # Hatırlatıcı ve hata penceresi tkinter'a düşebiliyor.
        "tkinter",
        "tkinter.messagebox",
        # pywebview arka ucunu çalışma anında seçiyor (webview/guilib.py);
        # statik analiz bu yolu göremeyebilir, açıkça yazıyoruz.
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
        "clr",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "_pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Takvim",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # PENCERESİZ: uygulama artık kendi masaüstü penceresinde açılıyor, arkasında
    # siyah bir konsol durması onu "çalıştırılmış bir script" gibi gösteriyordu.
    # Konsol gidince `stdout`/`stderr` de gidiyor; yerine günlük dosyası
    # konuyor (bkz. `takvim_app._gunluge_yonlendir`).
    console=False,
    disable_windowed_traceback=False,
    icon="takvim.ico",
)
