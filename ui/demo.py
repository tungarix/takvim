"""Demo verisi: UI'yı boş ekranla açmamak için.

Gerçek veri `.ics` içe aktarmadan gelir (Faz 2); bu yalnızca arayüzü görmek ve
ölçmek için. Kasten çakışan, gece yarısını aşan ve tüm gün etkinlikler içeriyor —
ızgaranın zor hâllerini gözle görebilmek için.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from core import Event, from_wall_clock
from store import Repo, new_uid

__all__ = ["seed"]

TZID = "Europe/Istanbul"


def _an(gun: date, saat: int, dakika: int = 0) -> datetime:
    """Yerel duvar saatinden UTC an."""
    return from_wall_clock(datetime(gun.year, gun.month, gun.day, saat, dakika), TZID)


def seed(repo: Repo, anchor: date | None = None) -> None:
    """Verilen haftaya örnek takvim ve etkinlikler yazar."""
    anchor = anchor or date.today()
    pazartesi = anchor - timedelta(days=anchor.weekday())

    ders = repo.add_calendar("Ders", "#e0524a")
    kisisel = repo.add_calendar("Kişisel", "#3b82f6")
    aktenak = repo.add_calendar("Aktenak", "#10b981")
    repo.add_calendar("Arşiv", "#6b7280", visible=False)

    def ekle(takvim, baslik, gun_offset, bas, bit, **kw):
        gun = pazartesi + timedelta(days=gun_offset)
        bitis_gun = gun + timedelta(days=1) if bit <= bas else gun
        return repo.add_event(
            Event(
                id=None,
                uid=new_uid(),
                calendar_id=takvim.id,
                title=baslik,
                start_utc=_an(gun, bas),
                end_utc=_an(bitis_gun, bit),
                tzid=TZID,
                **kw,
            )
        )

    # Haftalık dersler -- ikisi kasten çakışıyor (kolon yerleşimi görünsün)
    ekle(ders, "Algoritma", 0, 9, 11, rrule="FREQ=WEEKLY;BYDAY=MO")
    ekle(ders, "Fizik II", 0, 10, 12, rrule="FREQ=WEEKLY;BYDAY=MO")
    ekle(ders, "Lineer Cebir", 0, 10, 11, rrule="FREQ=WEEKLY;BYDAY=MO")
    ekle(ders, "Veri Yapıları", 2, 13, 15, rrule="FREQ=WEEKLY;BYDAY=WE")
    ekle(ders, "Laboratuvar", 4, 14, 17, rrule="FREQ=WEEKLY;BYDAY=FR")

    # Günlük alışkanlık
    ekle(kisisel, "Koşu", 0, 7, 8, rrule="FREQ=DAILY")

    # Gece yarısını aşan: iki günde de görünmeli
    ekle(kisisel, "Gece nöbeti", 5, 23, 1)

    # Çok günlü tüm gün
    repo.add_event(
        Event(
            id=None,
            uid=new_uid(),
            calendar_id=kisisel.id,
            title="Bahar tatili",
            start_utc=_an(pazartesi + timedelta(days=2), 0),
            end_utc=_an(pazartesi + timedelta(days=5), 0),
            tzid=TZID,
            all_day=True,
        )
    )

    # Tek seferlikler
    ekle(aktenak, "Sprint planlama", 1, 11, 12, location="Toplantı odası")
    ekle(aktenak, "Kod gözden geçirme", 3, 16, 17)
    ekle(kisisel, "Diş hekimi", 3, 9, 10, location="Kadıköy")

    # Serinin tek örneğini kaydır: override rozeti görünsün.
    # Başlığa göre arıyoruz: list_events() start_utc'ye göre sıralı olduğu için
    # [0] "Koşu" gelir ve override seriye ait olmayan bir ana denk gelip
    # sessizce yok sayılırdı.
    algoritma = next(e for e in repo.list_events() if e.title == "Algoritma")
    repo.move_occurrence(
        algoritma.id,
        _an(pazartesi, 9),
        _an(pazartesi, 15),
    )
