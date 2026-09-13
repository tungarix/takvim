# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller yapılandırması — tek dosyalık Takvim.exe.

Veri dosyaları ELLE eklenmek zorunda: PyInstaller yalnızca import edilen
modülleri toplar, `ui/static/*` ve `store/migrations/*.sql` ise dosya olarak
okunuyor. Unutulurlarsa uygulama açılır ama boş bir sayfa gösterir ya da
migration bulunamadı diye ölür.
"""

a = Analysis(
    ["takvim_app.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("ui/static", "ui/static"),
        ("store/migrations", "store/migrations"),
        ("store/schema.sql", "store"),
    ],
    hiddenimports=[
        # zoneinfo tzdata'yı dinamik okur; PyInstaller import göremez.
        "tzdata",
        # Hatırlatıcı ve hata penceresi tkinter'a düşebiliyor.
        "tkinter",
        "tkinter.messagebox",
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
    console=True,
    disable_windowed_traceback=False,
    icon="takvim.ico",
)
