"""Arayüz katmanı.

`ui/` -> `core/` ve `store/` import eder; tersi ASLA olmaz.
"""

from .presenter import week_bounds, week_payload, week_start
from .server import make_server, serve

__all__ = ["week_payload", "week_bounds", "week_start", "serve", "make_server"]
