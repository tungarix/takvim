"""Senkron dosyası (`.takvimsync`) DIŞA aktarma: cihazın TAM durumu.

Biçim ve birleştirme kuralları: `docs/senkron.md`. Dışa aktarma delta değil
tam durumdur; içe aktaran taraf dosyadaki her kaydı kendi verisiyle
birleştirir (`ice.py`), bu yüzden hangi dosyanın hangisinden sonra geldiği
önemsiz.

`core/` burayı import etmez; tersi serbest (AGENTS §2). Okuma `repo.conn`
üzerinden ham SELECT: Repo'nun modeli `updated_at`'i, `uid` eşleşmelerini ve
mezar taşlarını taşımıyor, dosya ise bunların hepsini istiyor.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from core import UTC
from store import Repo

__all__ = ["BICIM", "SURUM", "cihaz_kimligi", "durum_uret", "json_metni", "UZANTI"]

BICIM = "takvim-sync"
# Dosyadaki `version`. İçe aktarma bundan BÜYÜK sürümü reddeder.
SURUM = 1
UZANTI = ".takvimsync"

_ZAMAN_BICIMI = "%Y-%m-%dT%H:%M:%SZ"


def _liste(metin: str | None) -> list[str]:
    """Virgüllü zaman metnini (rdate/exdate) diziye çevirir; boşsa []."""
    return [parca for parca in metin.split(",") if parca] if metin else []


def cihaz_kimligi(dizin: str | Path | None) -> str:
    """Bu kurulumun sabit kimliği: veri klasöründeki `cihaz.json`.

    Dosyada yoksa üretip yazar. `ayarlar.json`'a konmadı: orası yalnızca BİLİNEN
    anahtarları yazıyor ve ayar testleri sözlüğün tamamına kilitli. Klasör yoksa
    ya da yazılamıyorsa (bellek DB'si, salt okunur disk) her çağrıda yeni kimlik
    döner; kimlik içe aktarmada kullanılmıyor, yalnızca dosyada bilgi.
    """
    if dizin is not None:
        yol = Path(dizin) / "cihaz.json"
        try:
            kimlik = json.loads(yol.read_text(encoding="utf-8"))["id"]
            if isinstance(kimlik, str) and kimlik:
                return kimlik
        except (OSError, ValueError, KeyError, TypeError):
            pass
    kimlik = str(uuid.uuid4())
    if dizin is not None:
        try:
            yol.write_text(json.dumps({"id": kimlik}), encoding="utf-8")
        except OSError:
            pass
    return kimlik


def durum_uret(
    repo: Repo,
    *,
    cihaz_id: str,
    cihaz_adi: str,
    uygulama: str,
    simdi: datetime | None = None,
) -> dict:
    """Veritabanının tam durumunu senkron dosyası sözlüğü olarak üretir.

    Sıralama `uid`'e göre (id'ye değil): iki cihazın aynı veriyi farklı sırayla
    eklemiş olması dosyayı değiştirmesin; aynı durum her zaman aynı çıktıyı verir
    (uyum fixture'ı ve gidiş-dönüş testi buna dayanıyor). `simdi` testlerde
    sabitlenir.
    """
    conn = repo.conn
    olusturma = (simdi or datetime.now(UTC)).astimezone(UTC).strftime(_ZAMAN_BICIMI)

    takvimler = [
        {
            "uid": r["uid"],
            "name": r["name"],
            "color": r["color"],
            "visible": bool(r["visible"]),
            "updated_at": r["updated_at"] or r["created_at"],
        }
        for r in conn.execute("SELECT * FROM calendars ORDER BY uid")
    ]

    # Çocuklar tek sorguda, etkinlik başına ayrı sorgu (N+1) atmadan.
    hatirlaticilar: dict[int, list[int]] = defaultdict(list)
    for r in conn.execute(
        "SELECT event_id, minutes_before FROM reminders ORDER BY minutes_before"
    ):
        hatirlaticilar[r["event_id"]].append(r["minutes_before"])
    override_ler: dict[int, list[dict]] = defaultdict(list)
    for r in conn.execute("SELECT * FROM event_overrides ORDER BY original_start_utc"):
        override_ler[r["event_id"]].append(
            {
                "original_start_utc": r["original_start_utc"],
                "cancelled": bool(r["cancelled"]),
                "new_start_utc": r["new_start_utc"],
                "new_end_utc": r["new_end_utc"],
                "new_title": r["new_title"],
                "new_location": r["new_location"],
            }
        )

    etkinlikler = [
        {
            "uid": r["uid"],
            "calendar_uid": r["calendar_uid"],
            "title": r["title"],
            "description": r["description"],
            "location": r["location"],
            "start_utc": r["start_utc"],
            "end_utc": r["end_utc"],
            "tzid": r["tzid"],
            "all_day": bool(r["all_day"]),
            "rrule": r["rrule"],
            "rdate": _liste(r["rdate"]),
            "exdate": _liste(r["exdate"]),
            "reminders": hatirlaticilar.get(r["id"], []),
            "overrides": override_ler.get(r["id"], []),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in conn.execute(
            "SELECT e.*, c.uid AS calendar_uid FROM events e "
            "JOIN calendars c ON c.id = e.calendar_id ORDER BY e.uid"
        )
    ]

    gorevler = [
        {
            "uid": r["uid"],
            "title": r["title"],
            "notes": r["notes"],
            "plan_day": r["plan_day"],
            "event_uid": r["event_uid"],
            "done_at": r["done_at"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in conn.execute(
            "SELECT t.*, e.uid AS event_uid FROM tasks t "
            "LEFT JOIN events e ON e.id = t.event_id ORDER BY t.uid"
        )
    ]

    silinenler = [
        {"kind": r["kind"], "uid": r["uid"], "deleted_at": r["deleted_at"]}
        for r in conn.execute("SELECT * FROM silinenler ORDER BY kind, uid")
    ]

    return {
        "format": BICIM,
        "version": SURUM,
        "created_at": olusturma,
        "device": {"id": cihaz_id, "name": cihaz_adi, "app": uygulama},
        "calendars": takvimler,
        "events": etkinlikler,
        "tasks": gorevler,
        "deleted": silinenler,
    }


def json_metni(durum: dict) -> str:
    """Senkron durumunu dosyaya yazılacak UTF-8 JSON metnine çevirir."""
    return json.dumps(durum, ensure_ascii=False, indent=2) + "\n"
