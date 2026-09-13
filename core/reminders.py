"""Hatırlatıcı mantığı — saf.

Hangi hatırlatıcının ne zaman tetikleneceğine burası karar verir; bildirimi
kimin nasıl göstereceğini bilmez. Böylece "uygulama üç gün kapalı kaldıysa ne
olmalı" gibi zor soruları saat, ekran ve işletim sistemi olmadan test
edebiliyoruz.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import Occurrence
from .timeutil import UTC, ensure_aware

__all__ = ["Reminder", "DueReminder", "due_reminders", "fire_key"]


@dataclass(frozen=True)
class Reminder:
    """Bir seriye bağlı hatırlatıcı: "başlamadan N dakika önce".

    Seriye bağlanır, her ÖRNEK için ayrı tetiklenir. `minutes_before=0`
    "tam başlarken" demektir; negatif değer kabul edilmez.
    """

    id: int | None
    event_id: int | None
    minutes_before: int

    def __post_init__(self) -> None:
        if self.minutes_before < 0:
            raise ValueError(
                f"minutes_before negatif olamaz: {self.minutes_before}"
            )


@dataclass(frozen=True)
class DueReminder:
    """Tetiklenmesi gereken hatırlatıcı + hangi örnek için."""

    reminder_id: int | None
    occurrence: Occurrence
    minutes_before: int
    fire_at_utc: datetime


def fire_key(reminder_id: int | None, occurrence: Occurrence) -> tuple:
    """Bir hatırlatıcı-örnek çiftinin tekil anahtarı.

    `reminder_fired` tablosunun UNIQUE kısıtıyla aynı ikili; mükerrer bildirim
    hem burada hem veritabanında engelleniyor.
    """
    return (reminder_id, occurrence.start_utc.astimezone(UTC))


def due_reminders(
    occurrences: list[Occurrence],
    reminders_by_event: dict[int | None, list[Reminder]],
    now: datetime,
    *,
    already_fired: set[tuple] | None = None,
) -> list[DueReminder]:
    """Şu an tetiklenmesi gereken hatırlatıcıları döndürür.

    Kural: `fire_at <= now` VE örnek henüz BİTMEMİŞ VE daha önce
    tetiklenmemiş.

    "Örnek henüz bitmemiş" koşulu bilinçli ve önemli. Uygulama bir hafta kapalı
    kalıp açıldığında geçmiş haftanın bütün hatırlatıcılarını arka arkaya
    göstermek işe yaramaz, sadece rahatsız eder. Buna karşılık 5 dakika sonra
    başlayacak bir toplantı, uygulama az önce açılmış olsa bile bildirilmeli --
    bu yüzden "gecikme penceresi" yerine "etkinlik hâlâ güncel mi" ölçütünü
    kullanıyoruz.

    Tüm gün etkinlikleri de dahildir: onların başlangıcı yerel gece yarısıdır,
    dolayısıyla "1 gün önce" gibi bir hatırlatıcı beklendiği gibi çalışır.

    Dönen liste tetiklenme anına göre sıralıdır.
    """
    ensure_aware(now, "now")
    now = now.astimezone(UTC)
    already_fired = already_fired or set()

    bulunan: list[DueReminder] = []
    for occ in occurrences:
        for reminder in reminders_by_event.get(occ.event_id, []):
            fire_at = occ.start_utc - timedelta(minutes=reminder.minutes_before)
            if fire_at > now:
                continue  # henüz zamanı gelmedi
            if occ.end_utc <= now:
                continue  # etkinlik bitmiş; geçmişi bildirmiyoruz
            if fire_key(reminder.id, occ) in already_fired:
                continue
            bulunan.append(
                DueReminder(
                    reminder_id=reminder.id,
                    occurrence=occ,
                    minutes_before=reminder.minutes_before,
                    fire_at_utc=fire_at,
                )
            )

    bulunan.sort(key=lambda d: (d.fire_at_utc, d.occurrence.start_utc, d.occurrence.uid))
    return bulunan


def next_fire_time(
    occurrences: list[Occurrence],
    reminders_by_event: dict[int | None, list[Reminder]],
    now: datetime,
) -> datetime | None:
    """Gelecekteki en yakın tetiklenme anı; yoksa None.

    Arka plan süreci bunu uyku süresini belirlemek için kullanıyor: sabit
    aralıkla yoklamak yerine bir sonraki işe kadar uyuyabilsin.
    """
    ensure_aware(now, "now")
    now = now.astimezone(UTC)

    adaylar = [
        occ.start_utc - timedelta(minutes=reminder.minutes_before)
        for occ in occurrences
        for reminder in reminders_by_event.get(occ.event_id, [])
        if occ.start_utc - timedelta(minutes=reminder.minutes_before) > now
    ]
    return min(adaylar) if adaylar else None
