"""Takvim uygulamasının saf mantık çekirdeği.

KURAL: `core/` hiçbir zaman `store/` veya `ui/` import etmez. Tersi serbest.
Bu tek kural, ileride bu motoru başka bir uygulamaya taşımayı mümkün kılan şey.

Bu paket disk, veritabanı ve ekran hakkında hiçbir şey bilmez; girdisi veri,
çıktısı veridir.
"""

from .layout import layout
from .models import Calendar, Event, Occurrence, Override
from .query import conflicts, free_slots, overlaps
from .quickadd import QuickAdd, parse_quick_add
from .recurrence import expand, instance_starts, series_end
from .reminders import DueReminder, Reminder, due_reminders, fire_key, next_fire_time
from .timeutil import (
    UTC,
    ensure_aware,
    format_iso,
    from_wall_clock,
    get_tz,
    is_valid_tzid,
    parse_iso,
    to_local,
    to_utc,
)

__all__ = [
    # modeller
    "Calendar",
    "Event",
    "Occurrence",
    "Override",
    # tekrar
    "expand",
    "instance_starts",
    "series_end",
    # yerleşim ve sorgu
    "layout",
    "overlaps",
    "conflicts",
    "free_slots",
    # hızlı ekleme
    "QuickAdd",
    "parse_quick_add",
    # hatırlatıcı
    "Reminder",
    "DueReminder",
    "due_reminders",
    "next_fire_time",
    "fire_key",
    # zaman
    "UTC",
    "get_tz",
    "is_valid_tzid",
    "ensure_aware",
    "to_utc",
    "to_local",
    "from_wall_clock",
    "parse_iso",
    "format_iso",
]
