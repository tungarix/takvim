"""Mobil uygulamanın doğrulama için kullandığı uyum fixture'ı (`docs/senkron-ornek*`).

Fixture bir kez üretilip bırakılmış bir dosya değil, `scripts/senkron_ornek_uret.py`'nin
çıktısı: kural ya da biçim değişince betik yeniden çalıştırılmazsa mobil geliştirici
eski bir şeye karşı doğrular. Bu test o kayması yakalıyor.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from senkron import ice_aktar
from store import Repo

KOK = Path(__file__).resolve().parent.parent
DOCS = KOK / "docs"
_spec = importlib.util.spec_from_file_location("senkron_ornek_uret", KOK / "scripts" / "senkron_ornek_uret.py")
assert _spec is not None and _spec.loader is not None
uretici = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(uretici)


@pytest.fixture
def olusumlar():
    return json.loads((DOCS / uretici.OLUSUM_ADI).read_text(encoding="utf-8"))


def test_fixture_dosyalari_betigin_ciktisiyla_ayni(tmp_path):
    """Elle düzenlenmiş ya da bayat fixture: betiği yeniden çalıştır."""
    uretilen = uretici.uret(tmp_path)

    for yol in uretilen:
        # git (autocrlf) Windows'ta çalışma kopyasını CRLF yapabiliyor: satır
        # sonlarından bağımsız karşılaştır (splitlines CR/LF/CRLF'yi aynı sayar).
        commitli = (DOCS / yol.name).read_bytes().splitlines()
        assert yol.read_bytes().splitlines() == commitli, (
            f"{yol.name} güncel değil: scripts/senkron_ornek_uret.py'yi çalıştır"
        )


def test_fixture_betigi_her_calistirmada_ayni_baytlari_uretir(tmp_path):
    ilk = [y.read_bytes() for y in uretici.uret(tmp_path / "bir")]
    ikinci = [y.read_bytes() for y in uretici.uret(tmp_path / "iki")]

    assert ilk == ikinci


def test_fixture_icerigi_istenen_kapsami_tasiyor():
    d = json.loads((DOCS / uretici.DOSYA_ADI).read_text(encoding="utf-8"))
    etkinlikler = {e["title"]: e for e in d["events"]}

    assert len(d["calendars"]) == 2
    assert etkinlikler["Diş hekimi"]["rrule"] is None, "tek seferlik"
    assert etkinlikler["Haftalık toplantı"]["rrule"].startswith("FREQ=WEEKLY"), "haftalık tekrarlı"
    assert etkinlikler["Tatil"]["all_day"] is True, "tüm gün"
    assert etkinlikler["New York standup"]["tzid"] == "America/New_York", "farklı saat dilimi"
    assert etkinlikler["Algoritmalar"]["overrides"], "override'lı seri"
    assert etkinlikler["Diş hekimi"]["reminders"], "hatırlatıcılı"
    gorevler = {g["title"]: g for g in d["tasks"]}
    assert gorevler["Rapor yaz"]["plan_day"] is None and gorevler["Rapor yaz"]["event_uid"] is None
    assert gorevler["Market alışverişi"]["plan_day"] == "2026-11-04"
    assert gorevler["Sunum hazırla"]["event_uid"] == etkinlikler["Sunum hazırla"]["uid"]
    assert gorevler["Faturayı öde"]["done_at"]
    assert {s["kind"] for s in d["deleted"]} == {"event", "task"}


def test_fixture_temiz_veritabanina_aktarilir_ve_ikinci_kez_degistirmez():
    metin = (DOCS / uretici.DOSYA_ADI).read_text(encoding="utf-8")
    with Repo.open(":memory:") as repo:
        rapor = ice_aktar(repo, metin)
        ikinci = ice_aktar(repo, metin)

        assert rapor.added == {"calendar": 2, "event": 8, "task": 4}
        assert rapor.as_dict()["total"] == {"added": 14, "updated": 0, "deleted": 0, "skipped": 0}
        assert ikinci.as_dict()["total"] == {"added": 0, "updated": 0, "deleted": 0, "skipped": 0}
        assert len(repo.conn.execute("SELECT * FROM silinenler").fetchall()) == 2


def test_olusumlar_dosyasi_beklenen_durumlari_gosteriyor(olusumlar):
    ornekler = olusumlar["occurrences"]

    def baslik(ad):
        return [o for o in ornekler if o["title"] == ad]


    assert olusumlar["window"] == {"start_utc": "2026-11-01T00:00:00Z", "end_utc": "2027-02-01T00:00:00Z"}
    assert baslik("Pencere dışı") == [], "pencere dışındaki etkinlik hesaba girmez"
    # exdate: 16 Kasım Pazartesi toplantısı yok; öncesi ve sonrası var
    toplanti = [o["start_utc"] for o in baslik("Haftalık toplantı")]
    assert "2026-11-16T07:00:00Z" not in toplanti and "2026-11-09T07:00:00Z" in toplanti
    # iptal override'ı: örnek listede yok, `cancelled` listesinde var
    assert olusumlar["cancelled"] == [{
        "event_uid": baslik("Algoritmalar")[0]["event_uid"], "original_start_utc": "2026-11-17T06:00:00Z",
    }]
    assert "2026-11-17T06:00:00Z" not in [o["start_utc"] for o in baslik("Algoritmalar")]
    # taşınmış örnek: yeni saat + yeni başlık + özgün konum anahtarı
    telafi = baslik("Algoritmalar (telafi)")
    assert [(o["start_utc"], o["is_override"], o["location"], o["original_start_utc"]) for o in telafi] == [
        ("2026-11-26T08:00:00Z", True, "B204", "2026-11-24T06:00:00Z")
    ]
    # DST: 1 Kasım'da ABD yaz saati bitti, duvar saati 09:30 kalır, UTC 14:30
    assert {o["start_utc"][11:] for o in baslik("New York standup")} == {"14:30:00Z"}
    # tüm gün: üç gün, UTC'de yerel gece yarısından gece yarısına
    assert [(o["start_utc"], o["end_utc"], o["all_day"]) for o in baslik("Tatil")] == [
        ("2026-12-23T21:00:00Z", "2026-12-26T21:00:00Z", True)
    ]
