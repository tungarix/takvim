"""Uygulama sürümü — TEK kaynak.

`pyproject.toml` sürümü buradan okuyor (`[tool.setuptools.dynamic]`). `.exe`
de bu modülü import ederek görüyor: paket metadata'sı PyInstaller'a
taşınmadığı için `importlib.metadata` paketlenmiş uygulamada çalışmazdı.
Yeni sürümde YALNIZCA burayı değiştir.
"""

SURUM = "1.6.0"
