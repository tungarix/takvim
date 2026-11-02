"""Senkron uyum fixture'ını üretir (mobil uygulama doğrulama için kullanıyor).

Üç şey yazar (varsayılan: `docs/`):

- `senkron-ornek.takvimsync`: sabit, elle kurulmuş örnek durum (2 takvim; tek
  seferlik, haftalık tekrarlı, tüm gün ve saat dilimi farklı etkinlikler;
  override'lı bir seri; hatırlatıcılı etkinlik; plansız / gün planlı / saat
  planlı görev; silinenler). Dosya `senkron.durum_uret` çıktısıdır: masaüstü
  aynı durumu tam bu bayt'larla üretir.
- `senkron-ornek-olusumlar.json`: aynı dosya temiz bir veritabanına içe aktarılıp
  `Repo.occurrences` ile 2026-11-01..2027-01-31 penceresi için hesaplanan
  örnekler. Mobil uygulama kendi içe aktarmasından sonra kendi örnek
  hesabını bununla karşılaştırır.

Elle düzenleme yok: durum aşağıdaki `ornek_durum()`'da, çıktılar onun
sonucu. Kural değişirse betiği yeniden çalıştır (`tests/test_senkron_ornek.py`
dosyaların güncel olduğunu denetler):

    .venv\\Scripts\\python.exe scripts/senkron_ornek_uret.py
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from core import UTC, from_wall_clock
from senkron import durum_uret, ice_aktar, json_metni
from store import Repo

DOSYA_ADI = "senkron-ornek.takvimsync"
OLUSUM_ADI = "senkron-ornek-olusumlar.json"

IST = "Europe/Istanbul"
NY = "America/New_York"
_ZAMAN = "%Y-%m-%dT%H:%M:%SZ"
_AD_ALANI = uuid.UUID("6b6d5f74-6b76-4d6e-8c0a-7b5d0a1e0001")  # sabit: uid'ler hep aynı

# Pencere: UTC, bitiş HARİÇ (yarı açık aralık, AGENTS §4).
PENCERE = ("2026-11-01T00:00:00Z", "2027-02-01T00:00:00Z")


def _uid(ad: str, *, etkinlik: bool = True) -> str:
    """Ada göre kararlı uid (tekrar çalıştırınca değişmesin)."""
    uid = str(uuid.uuid5(_AD_ALANI, ad))
    return f"{uid}@takvim.local" if etkinlik else uid


def _yerel(tzid: str, y: int, m: int, d: int, sa: int = 0, dk: int = 0) -> str:
    """Duvar saatinden sabit genişlikli UTC metni (elle UTC hesabı yok)."""
    return from_wall_clock(datetime(y, m, d, sa, dk), tzid).strftime(_ZAMAN)


def _etkinlik(ad: str, takvim: str, baslik: str, bas: str, bit: str, tzid: str = IST, **ek) -> dict:
    """Dosyadaki etkinlik kaydı; belirtilmeyen alanlar varsayılan."""
    return {
        "uid": _uid(ad),
        "calendar_uid": _uid(takvim, etkinlik=False),
        "title": baslik,
        "description": ek.get("description"),
        "location": ek.get("location"),
        "start_utc": bas,
        "end_utc": bit,
        "tzid": tzid,
        "all_day": ek.get("all_day", False),
        "rrule": ek.get("rrule"),
        "rdate": ek.get("rdate", []),
        "exdate": ek.get("exdate", []),
        "reminders": ek.get("reminders", []),
        "overrides": ek.get("overrides", []),
        "created_at": "2026-10-20T08:00:00Z",
        "updated_at": ek.get("updated_at", "2026-10-25T09:30:00Z"),
    }


def _gorev(ad: str, baslik: str, **ek) -> dict:
    return {
        "uid": _uid(ad),
        "title": baslik,
        "notes": ek.get("notes"),
        "plan_day": ek.get("plan_day"),
        "event_uid": _uid(ek["blok"]) if "blok" in ek else None,
        "done_at": ek.get("done_at"),
        "created_at": "2026-10-21T08:00:00Z",
        "updated_at": ek.get("updated_at", "2026-10-26T09:00:00Z"),
    }


def ornek_durum() -> dict:
    """Elle kurulmuş örnek durum (dosyanın tam içeriği, cihaz alanları hariç)."""
    kisisel, ders = "takvim-kisisel", "takvim-ders"
    etkinlikler = [
        # tek seferlik + iki hatırlatıcı
        _etkinlik(
            "dis-hekimi", kisisel, "Diş hekimi",
            _yerel(IST, 2026, 11, 5, 14), _yerel(IST, 2026, 11, 5, 15),
            description="Kontrol randevusu", location="Nişantaşı Klinik",
            reminders=[30, 1440],
        ),
        # tüm gün, üç gün sürüyor (UTC'de 21:00'den 21:00'e)
        _etkinlik(
            "tatil", kisisel, "Tatil",
            _yerel(IST, 2026, 12, 24), _yerel(IST, 2026, 12, 27), all_day=True,
        ),
        # haftalık tekrar + hariç tutulan tarih + hatırlatıcı
        _etkinlik(
            "haftalik-toplanti", kisisel, "Haftalık toplantı",
            _yerel(IST, 2026, 11, 2, 10), _yerel(IST, 2026, 11, 2, 11),
            rrule="FREQ=WEEKLY;BYDAY=MO", reminders=[10],
            exdate=[_yerel(IST, 2026, 11, 16, 10)],
        ),
        # farklı saat dilimi: DTSTART yaz saatinde (EDT), pencerenin ilk günü
        # (1 Kasım) ABD yaz saati bitiyor; duvar saati 09:30'da kalmalı, UTC
        # 13:30'dan 14:30'a kaymalı (AGENTS 1).
        _etkinlik(
            "ny-standup", kisisel, "New York standup",
            _yerel(NY, 2026, 10, 26, 9, 30), _yerel(NY, 2026, 10, 26, 10), tzid=NY,
            rrule="FREQ=WEEKLY;BYDAY=MO,WE",
        ),
        # gece yarısını aşan tek seferlik
        _etkinlik(
            "proje-teslimi", kisisel, "Proje teslimi",
            _yerel(IST, 2027, 1, 15, 23), _yerel(IST, 2027, 1, 16, 1),
        ),
        # pencerenin DIŞINDA: hesaplamada görünmemeli
        _etkinlik(
            "pencere-disi", kisisel, "Pencere dışı",
            _yerel(IST, 2027, 3, 1, 10), _yerel(IST, 2027, 3, 1, 11),
        ),
        # override'lı seri: biri iptal, biri taşınmış + başlık/konum değişmiş
        _etkinlik(
            "algoritmalar", ders, "Algoritmalar",
            _yerel(IST, 2026, 11, 3, 9), _yerel(IST, 2026, 11, 3, 10, 30),
            rrule="FREQ=WEEKLY;BYDAY=TU;UNTIL=20270112T000000Z",
            location="A101", reminders=[15],
            overrides=[
                {
                    "original_start_utc": _yerel(IST, 2026, 11, 17, 9), "cancelled": True,
                    "new_start_utc": None, "new_end_utc": None,
                    "new_title": None, "new_location": None,
                },
                {
                    "original_start_utc": _yerel(IST, 2026, 11, 24, 9), "cancelled": False,
                    "new_start_utc": _yerel(IST, 2026, 11, 26, 11),
                    "new_end_utc": _yerel(IST, 2026, 11, 26, 12, 30),
                    "new_title": "Algoritmalar (telafi)", "new_location": "B204",
                },
            ],
        ),
        # saat planlı görevin zaman bloğu: başlık/açıklama görevle aynı (AGENTS 69)
        _etkinlik(
            "blok-sunum", kisisel, "Sunum hazırla",
            _yerel(IST, 2026, 11, 6, 16), _yerel(IST, 2026, 11, 6, 17, 30),
            description="Slaytları bitir",
        ),
    ]
    return {
        "calendars": [
            {"uid": _uid(kisisel, etkinlik=False), "name": "Kişisel", "color": "#3b82f6",
             "visible": True, "updated_at": "2026-10-20T08:00:00Z"},
            {"uid": _uid(ders, etkinlik=False), "name": "Ders", "color": "#e0524a",
             "visible": True, "updated_at": "2026-10-20T08:00:00Z"},
        ],
        "events": etkinlikler,
        "tasks": [
            _gorev("gorev-plansiz", "Rapor yaz", notes="Taslak yeterli"),
            _gorev("gorev-gun", "Market alışverişi", plan_day="2026-11-04"),
            _gorev("gorev-saat", "Sunum hazırla", notes="Slaytları bitir", blok="blok-sunum"),
            _gorev("gorev-bitti", "Faturayı öde", done_at="2026-10-27T18:00:00Z"),
        ],
        "deleted": [
            {"kind": "event", "uid": _uid("silinen-etkinlik"), "deleted_at": "2026-10-30T12:00:00Z"},
            {"kind": "task", "uid": _uid("silinen-gorev"), "deleted_at": "2026-10-31T12:00:00Z"},
        ],
    }


def _sirala(durum: dict) -> dict:
    """`durum_uret`'in sıralamasıyla (uid / kind+uid) aynı."""
    return {
        "calendars": sorted(durum["calendars"], key=lambda k: k["uid"]),
        "events": sorted(durum["events"], key=lambda k: k["uid"]),
        "tasks": sorted(durum["tasks"], key=lambda k: k["uid"]),
        "deleted": sorted(durum["deleted"], key=lambda k: (k["kind"], k["uid"])),
    }


def _olusumlar(repo: Repo) -> dict:
    """İçe aktarılmış veritabanından pencere için örnekleri çıkarır."""
    baslangic = datetime.strptime(PENCERE[0], _ZAMAN).replace(tzinfo=UTC)
    bitis = datetime.strptime(PENCERE[1], _ZAMAN).replace(tzinfo=UTC)

    def bicim(t: datetime) -> str:
        return t.astimezone(UTC).strftime(_ZAMAN)

    takvim_uid = {c.id: c.uid for c in repo.list_calendars()}
    ornekler = [
        {
            "event_uid": o.uid,
            "calendar_uid": takvim_uid[o.calendar_id],
            "title": o.title,
            "start_utc": bicim(o.start_utc),
            "end_utc": bicim(o.end_utc),
            "all_day": o.all_day,
            "location": o.location,
            "is_override": o.is_override,
            "original_start_utc": bicim(o.series_slot_utc),
        }
        for o in repo.occurrences(baslangic, bitis)
    ]
    iptaller = [
        {"event_uid": e.uid, "original_start_utc": bicim(ov.original_start_utc)}
        for e in repo.list_events()
        for ov in repo.list_overrides(e.id)
        if ov.cancelled and baslangic <= ov.original_start_utc < bitis
    ]
    return {
        "aciklama": (
            "senkron-ornek.takvimsync temiz bir veritabanına içe aktarılıp Repo.occurrences "
            "ile hesaplandı. window UTC ve bitiş HARİÇ. occurrences iptal edilmemiş "
            "örnekleri taşır (is_override: taşınmış/başlığı değişmiş örnek; "
            "original_start_utc seri içindeki özgün yeri); cancelled penceredeki "
            "iptal override'ları (exdate ile dışlananlar ve pencere dışı olanlar "
            "hiçbirinde yok). Tüm görünür takvimler dahil."
        ),
        "window": {"start_utc": PENCERE[0], "end_utc": PENCERE[1]},
        "occurrences": ornekler,
        "cancelled": sorted(iptaller, key=lambda k: (k["event_uid"], k["original_start_utc"])),
    }


def uret(cikti_dizini: str | Path) -> tuple[Path, Path]:
    """İki dosyayı yazar; yolları döndürür. Çıktı her çalıştırmada bayt bayt aynı."""
    hedef = Path(cikti_dizini)
    hedef.mkdir(parents=True, exist_ok=True)
    el_yapimi = _sirala(ornek_durum())

    with Repo.open(":memory:") as repo:
        rapor = ice_aktar(repo, {"format": "takvim-sync", "version": 1, **el_yapimi})
        if rapor.as_dict()["total"]["skipped"]:
            raise RuntimeError("örnek durumda yetim kayıt var")
        durum = durum_uret(
            repo,
            cihaz_id="00000000-0000-4000-8000-000000000001",
            cihaz_adi="Ornek-PC",
            uygulama="desktop 1.8.0",
            simdi=datetime(2026, 11, 2, 10, 0, 0, tzinfo=UTC),
        )
        # Elle kurulan durum masaüstünün üreteceği kanonik biçimde olmalı;
        # değilse (ör. alan eksik/fazla) fixture mobile yanlış şey öğretir.
        if {k: durum[k] for k in el_yapimi} != el_yapimi:
            raise RuntimeError("örnek durum, içe-dışa aktarmadan sonra değişti (kanonik değil)")
        olusumlar = _olusumlar(repo)

    dosya, olusum = hedef / DOSYA_ADI, hedef / OLUSUM_ADI
    dosya.write_text(json_metni(durum), encoding="utf-8", newline="\n")
    olusum.write_text(
        json.dumps(olusumlar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return dosya, olusum


def main() -> int:
    ayristirici = argparse.ArgumentParser(description="Senkron uyum fixture'ını üretir")
    ayristirici.add_argument("--cikti", default=str(KOK / "docs"), help="çıktı klasörü")
    args = ayristirici.parse_args()
    for yol in uret(args.cikti):
        print(yol)
    return 0


if __name__ == "__main__":
    sys.exit(main())
