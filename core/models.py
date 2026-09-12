"""Çekirdek veri tipleri.

Hepsi frozen dataclass: bir Occurrence üretildikten sonra kimse onu
değiştiremez. Doğrulama __post_init__ içinde, yani bozuk bir Event'i
oluşturmak imkânsız -- "sonra kontrol ederiz" diye bir aşama yok.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .timeutil import UTC, ensure_aware, get_tz

__all__ = ["Calendar", "Event", "Override", "Occurrence"]

_ONE_DAY = timedelta(days=1)


def _to_utc_tuple(values: Iterable[datetime] | None, name: str) -> tuple[datetime, ...]:
    """Datetime dizisini UTC'ye normalize edilmiş tuple'a çevirir.

    Blueprint bu alanları `list[datetime]` diye tanımlıyor; frozen dataclass'ta
    mutable default ve hash'lenemezlik sorun çıkardığı için içeride tuple'a
    çeviriyoruz. Çağıran taraf yine list geçebilir.
    """
    if values is None:
        return ()
    out = []
    for i, v in enumerate(values):
        out.append(ensure_aware(v, f"{name}[{i}]").astimezone(UTC))
    return tuple(sorted(out))


@dataclass(frozen=True, slots=True)
class Calendar:
    """Renk ve görünürlük taşıyan takvim kabı (Ders, Kişisel, Aktenak...)."""

    id: int | None
    name: str
    color: str
    visible: bool = True


@dataclass(frozen=True, slots=True)
class Event:
    """Takvimdeki tek bir kayıt. Tekrarlı seri de DB'de/bellekte TEK Event'tir.

    start_utc/end_utc her zaman UTC'ye normalize edilir; tzid ise etkinliğin
    "duvar saati" hangi dilimde sabit kalacağını söyler. Tekrar genişletmesi
    UTC'de değil tzid'de yapılır, yoksa DST geçişinde saat kayar.
    """

    id: int | None
    uid: str
    calendar_id: int | None
    title: str
    start_utc: datetime
    end_utc: datetime
    tzid: str
    all_day: bool = False
    rrule: str | None = None
    rdate: tuple[datetime, ...] = ()
    exdate: tuple[datetime, ...] = ()
    description: str | None = None
    location: str | None = None

    def __post_init__(self) -> None:
        set_ = object.__setattr__  # frozen dataclass'ta normalize etmenin yolu

        set_(self, "start_utc", ensure_aware(self.start_utc, "start_utc").astimezone(UTC))
        set_(self, "end_utc", ensure_aware(self.end_utc, "end_utc").astimezone(UTC))
        if self.end_utc <= self.start_utc:
            raise ValueError(
                f"end_utc > start_utc olmalı (uid={self.uid!r}): "
                f"{self.start_utc.isoformat()} -> {self.end_utc.isoformat()}"
            )

        tz = get_tz(self.tzid)  # geçersiz IANA adı burada patlar

        set_(self, "rdate", _to_utc_tuple(self.rdate, "rdate"))
        set_(self, "exdate", _to_utc_tuple(self.exdate, "exdate"))

        if self.rrule is not None:
            rrule = self.rrule.strip()
            if not rrule:
                raise ValueError("rrule boş metin olamaz; tekrar yoksa None kullan")
            set_(self, "rrule", rrule)

        if self.all_day:
            # "Tam gün katı" kontrolünü UTC süresi üzerinden yapmak yanlış olur:
            # DST'li bir dilimde bir tam gün 23 veya 25 saat sürer. Ölçüt yerel
            # gece yarısı olmak; o sağlanınca süre zaten tam sayıda takvim günü.
            start_local = self.start_utc.astimezone(tz)
            end_local = self.end_utc.astimezone(tz)
            for label, local in (("start", start_local), ("end", end_local)):
                if (local.hour, local.minute, local.second, local.microsecond) != (0, 0, 0, 0):
                    raise ValueError(
                        f"all_day etkinlikte {label} yerel gece yarısı olmalı "
                        f"({self.tzid}): {local.isoformat()}"
                    )

    @property
    def duration(self) -> timedelta:
        """Tek bir örneğin süresi; tekrarlı seride her örnek bu süreyi korur."""
        return self.end_utc - self.start_utc

    @property
    def is_recurring(self) -> bool:
        """Seri mi (RRULE veya ek RDATE var mı)."""
        return bool(self.rrule) or bool(self.rdate)


@dataclass(frozen=True, slots=True)
class Override:
    """RFC 5545'teki RECURRENCE-ID karşılığı: serinin tek bir örneğini değiştirir.

    `original_start_utc` hedeflenen örneğin ORİJİNAL başlangıcıdır -- kaydırılmış
    hâli değil. Kaydırdıktan sonra bile örneği bu anahtarla buluruz.
    """

    event_id: int | None
    original_start_utc: datetime
    cancelled: bool = False
    new_start_utc: datetime | None = None
    new_end_utc: datetime | None = None
    new_title: str | None = None
    new_location: str | None = None

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(
            self,
            "original_start_utc",
            ensure_aware(self.original_start_utc, "original_start_utc").astimezone(UTC),
        )
        for name in ("new_start_utc", "new_end_utc"):
            value = getattr(self, name)
            if value is not None:
                set_(self, name, ensure_aware(value, name).astimezone(UTC))
        if (
            self.new_start_utc is not None
            and self.new_end_utc is not None
            and self.new_end_utc < self.new_start_utc
        ):
            raise ValueError("new_end_utc, new_start_utc'den önce olamaz")


@dataclass(frozen=True, slots=True)
class Occurrence:
    """Serinin pencere içinde somutlaşmış tek örneği. Hiçbir zaman saklanmaz.

    location/description blueprint'in alan listesinde yok ama Override
    new_location taşıyor ve etkinlik paneli bunları gösteriyor; taşımazsak
    override'ın yarısı yolda kayboluyor.
    """

    event_id: int | None
    uid: str
    title: str
    start_utc: datetime
    end_utc: datetime
    all_day: bool
    tzid: str
    calendar_id: int | None
    is_override: bool = False
    location: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "start_utc", ensure_aware(self.start_utc, "start_utc").astimezone(UTC))
        set_(self, "end_utc", ensure_aware(self.end_utc, "end_utc").astimezone(UTC))
        # Event'ten gevşek: bir override sıfır süreli örnek üretebilir,
        # bunu hata sayıp expand()'i patlatmak istemiyoruz.
        if self.end_utc < self.start_utc:
            raise ValueError(
                f"end_utc < start_utc (uid={self.uid!r}): "
                f"{self.start_utc.isoformat()} -> {self.end_utc.isoformat()}"
            )

    @property
    def duration(self) -> timedelta:
        """Örneğin süresi."""
        return self.end_utc - self.start_utc

    def local_start(self) -> datetime:
        """Başlangıcın etkinliğin kendi saat dilimindeki karşılığı."""
        return self.start_utc.astimezone(get_tz(self.tzid))

    def local_end(self) -> datetime:
        """Bitişin etkinliğin kendi saat dilimindeki karşılığı."""
        return self.end_utc.astimezone(get_tz(self.tzid))
