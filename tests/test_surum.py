"""Uygulama sürümünün tek kaynağı: `ui/surum.py`."""

from __future__ import annotations

from importlib.metadata import version

from ui.surum import SURUM


def test_paket_surumu_ui_surum_dosyasindan_gelir():
    """pyproject sürümü `ui.surum.SURUM`'dan okumalı; yoksa ekrandaki sürüm paketinkinden kayar.

    Kurulu paketin metadata'sına bakıyor: `pip install -e .` sonrası geçerli
    (CI her çalıştırmada kuruyor).
    """
    assert version("takvim") == SURUM
