"""Hatırlatıcı arka plan süreci.

`remind/` -> `core/` ve `store/` import eder; tersi ASLA olmaz.
Uygulama kapalıyken de çalışabilsin diye arayüzden ayrı bir süreç.
"""

from .daemon import bildirim_metni, run_forever, run_once
from .notifier import (
    ConsoleNotifier,
    Notifier,
    TkNotifier,
    WindowsToastNotifier,
    pick_notifier,
)

__all__ = [
    "run_once",
    "run_forever",
    "bildirim_metni",
    "Notifier",
    "pick_notifier",
    "ConsoleNotifier",
    "TkNotifier",
    "WindowsToastNotifier",
]
