"""Zaman dönüşümlerinin TEK doğruluk kaynağı.

Kural: bu modülün dışına asla naive (saat dilimi bilgisi olmayan) datetime
sızmaz. Naive girdiyi kabul eden tek fonksiyon `from_wall_clock` -- adı niyeti
açıkça söylediği için "bu naive değeri yerel saat sayıyorum" varsayımı sessiz
kalmıyor. Diğer tüm public fonksiyonlar naive girdide ValueError fırlatır.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = [
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

UTC = timezone.utc  # noqa: UP017 -- `datetime.UTC` eşdeğeri ama bu ad modülün
# kamusal API'si; tek doğruluk kaynağı burada kalmalı, dağılmamalı.


@cache
def get_tz(tzid: str) -> ZoneInfo:
    """IANA adından ZoneInfo üretir; geçersiz/bilinmeyen adda ValueError.

    Sonuç cache'lenir: ZoneInfo örneği oluşturmak dosya okuması demek ve
    expand() sıcak yolda bunu çok sık çağırıyor.
    """
    if not isinstance(tzid, str) or not tzid.strip():
        raise ValueError(f"tzid boş olamaz, alınan: {tzid!r}")
    try:
        return ZoneInfo(tzid)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"Geçersiz IANA saat dilimi: {tzid!r}. "
            "Windows'ta bu hata tzdata paketi kurulu değilse de görülür."
        ) from exc
    except (ValueError, OSError) as exc:  # bozuk anahtar, mutlak yol vb.
        raise ValueError(f"Geçersiz IANA saat dilimi: {tzid!r}") from exc


def is_valid_tzid(tzid: str) -> bool:
    """tzid geçerli bir IANA adı mı."""
    try:
        get_tz(tzid)
    except ValueError:
        return False
    return True


def ensure_aware(dt: datetime, name: str = "dt") -> datetime:
    """Aware datetime'ı olduğu gibi döndürür; naive ise ValueError fırlatır."""
    if not isinstance(dt, datetime):
        raise ValueError(f"{name} bir datetime olmalı, alınan: {type(dt).__name__}")
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(
            f"{name} naive (saat dilimsiz). Yerel saat varsayımı yapmıyoruz; "
            "niyet buysa from_wall_clock() kullan."
        )
    return dt


def to_utc(dt: datetime, tzid: str) -> datetime:
    """Aware datetime'ı UTC'ye çevirir.

    `tzid` burada dönüşümü değiştirmez (aware bir değerin UTC karşılığı zaten
    tektir); etkinliğin beyan ettiği saat diliminin geçerliliğini doğrulamak
    için alınır -- böylece bozuk tzid veriyi yazmadan önce patlar.
    """
    ensure_aware(dt)
    get_tz(tzid)
    return dt.astimezone(UTC)


def to_local(dt: datetime, tzid: str) -> datetime:
    """Aware datetime'ı verilen saat dilimine çevirir."""
    ensure_aware(dt)
    return dt.astimezone(get_tz(tzid))


def from_wall_clock(dt: datetime, tzid: str) -> datetime:
    """Naive duvar saatini (ör. kullanıcının girdiği 14:00) UTC'ye çevirir.

    Sisteme naive değer sokan tek kapı burası. Aware girdi hata verir: yanlış
    fonksiyonu çağırmışsındır.

    DST uyarısı: ilkbahar geçişinde var olmayan bir duvar saati verilirse
    (ör. America/New_York'ta 02:30) zoneinfo geçiş öncesi ofseti kullanır;
    sonbaharda tekrarlanan saatte `fold=0` yani ilk geçiş seçilir.
    """
    if not isinstance(dt, datetime):
        raise ValueError(f"dt bir datetime olmalı, alınan: {type(dt).__name__}")
    if dt.tzinfo is not None:
        raise ValueError(
            "from_wall_clock naive datetime bekler; aware değer için to_utc() kullan."
        )
    return dt.replace(tzinfo=get_tz(tzid)).astimezone(UTC)


def parse_iso(s: str) -> datetime:
    """ISO 8601 metnini aware datetime'a çevirir; ofset yoksa ValueError."""
    if not isinstance(s, str):
        raise ValueError(f"parse_iso metin bekler, alınan: {type(s).__name__}")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"ISO 8601 olarak okunamadı: {s!r}") from exc
    if dt.tzinfo is None:
        raise ValueError(f"ISO metni saat dilimi/ofset içermiyor: {s!r}")
    return dt


def format_iso(dt: datetime) -> str:
    """Aware datetime'ı ISO 8601 metnine çevirir; UTC ise 'Z' soneki kullanır.

    Verilen ofseti korur, zorla UTC'ye çevirmez -- kalıcılık katmanı
    `format_iso(to_utc(dt, tzid))` diyerek UTC'yi kendisi garanti eder.
    """
    ensure_aware(dt)
    out = dt.isoformat()
    return out[:-6] + "Z" if out.endswith("+00:00") else out
