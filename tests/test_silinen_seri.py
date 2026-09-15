"""Seri silme güvencesi: anlık görüntü + geri alma + onay sayısı.

Kural: tek test tek davranış. Bellek DB'si yeterli (dosya işleri test_yedek'te).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core import UTC, Override
from store import Repo, new_uid
from tests.helpers import IST, ist, make_event


@pytest.fixture
def repo():
    """Her test için bellekte taze, migrate edilmiş bir DB."""
    with Repo.open(":memory:") as r:
        yield r


@pytest.fixture
def ders(repo):
    """Varsayılan görünür takvim."""
    return repo.add_calendar("Ders", "#c0392b")


def _seri(ders, **kwargs):
    """Haftalık seri kurar ve kaydeder."""
    kwargs.setdefault("event_id", None)
    kwargs.setdefault("uid", new_uid())
    kwargs.setdefault("calendar_id", ders.id)
    kwargs.setdefault("rrule", "FREQ=WEEKLY;BYDAY=MO")
    return make_event(
        kwargs.pop("start", ist(2026, 9, 7, 10, 0)),
        kwargs.pop("end", ist(2026, 9, 7, 11, 0)),
        **kwargs,
    )


def _pencere():
    bas = datetime(2026, 9, 1, tzinfo=UTC)
    return bas, bas + timedelta(days=60)


def test_snapshot_geri_alma_ornekleri_korur(repo, ders):
    """Sil + geri al: örnek kümesi birebir aynı."""
    ev = repo.add_event(_seri(ders, title="Algoritma"))
    repo.put_override(
        Override(event_id=ev.id, original_start_utc=ist(2026, 9, 14, 10, 0),
                 new_start_utc=ist(2026, 9, 14, 12, 0))
    )
    repo.cancel_occurrence(ev.id, ist(2026, 9, 21, 10, 0))
    bas, bit = _pencere()
    once = [(o.start_utc, o.end_utc, o.title) for o in repo.occurrences(bas, bit)]

    repo.snapshot_and_delete(ev.id)
    assert repo.occurrences(bas, bit) == []

    diriltilen = repo.restore_last_deleted()
    assert diriltilen is not None
    sonra = [(o.start_utc, o.end_utc, o.title) for o in repo.occurrences(bas, bit)]
    assert sonra == once


def test_snapshot_hatirlatici_ve_fired_korur(repo, ders):
    """Hatırlatıcılar ve fired geçmişi geri geliyor; mükerrer bildirim yok."""
    ev = repo.add_event(_seri(ders))
    hat = repo.add_reminder(ev.id, 10)
    repo.mark_fired(hat.id, ist(2026, 9, 7, 10, 0))

    repo.snapshot_and_delete(ev.id)
    diriltilen = repo.restore_last_deleted()

    assert [h.minutes_before for h in repo.list_reminders(diriltilen.id)] == [10]
    # fired geçmişi de dirildi: aynı occurrence için kayıt duruyor, id'ler
    # yenilense bile mükerrer bildirim olmayacak.
    assert len(repo.fired_keys()) == 1
    (yeni_hat_id, baslangic), = repo.fired_keys()
    assert baslangic == ist(2026, 9, 7, 10, 0)
    assert repo.mark_fired(yeni_hat_id, baslangic) is False


def test_ikinci_silme_birinciyi_ezer(repo, ders):
    """Geri alma tek adımlı: ikinci silme birincinin snapshot'ını siler."""
    bir = repo.add_event(_seri(ders, title="Bir"))
    iki = repo.add_event(_seri(ders, title="İki"))
    repo.snapshot_and_delete(bir.id)
    repo.snapshot_and_delete(iki.id)

    assert repo.son_silinen()["title"] == "İki"
    assert repo.restore_last_deleted().title == "İki"
    assert repo.restore_last_deleted() is None  # Bir artık alınamaz
    assert repo.get_event(bir.id) is None


def test_bos_geri_alma_none(repo):
    """Hiç silme yoksa geri alma None (404'e dönüşecek)."""
    assert repo.son_silinen() is None
    assert repo.restore_last_deleted() is None


def test_olmayan_etkinlik_lookuperror(repo):
    """Kayıtlı olmayan id'de snapshot alınmaz."""
    with pytest.raises(LookupError):
        repo.snapshot_and_delete(999)


def test_takvim_silinmisse_snapshot_saklanir(repo, ders):
    """Takvim arada silindiyse geri alma patlamaz: açık hata + snapshot durur."""
    ev = repo.add_event(_seri(ders))
    repo.snapshot_and_delete(ev.id)
    repo.delete_calendar(ders.id)
    with pytest.raises(LookupError):
        repo.restore_last_deleted()
    assert repo.son_silinen() is not None  # yeniden deneme şansı duruyor


def test_id_doluysa_yeni_id_verilir(repo, ders):
    """Araya aynı id'li kayıt girdiyse çocuklar yeni id'ye bağlanır."""
    ev = repo.add_event(_seri(ders))
    repo.put_override(
        Override(event_id=ev.id, original_start_utc=ist(2026, 9, 14, 10, 0),
                 new_start_utc=ist(2026, 9, 14, 12, 0))
    )
    eski_id = ev.id
    repo.snapshot_and_delete(eski_id)
    # Araya giren kayıt eski id'yi kapıyor:
    repo.conn.execute(
        "INSERT INTO events (id, uid, calendar_id, title, start_utc, end_utc,"
        " tzid, all_day, sequence, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (eski_id, new_uid(), ders.id, "Araya giren",
         "2026-09-07T07:00:00Z", "2026-09-07T08:00:00Z",
         IST, 0, 0, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    diriltilen = repo.restore_last_deleted()
    assert diriltilen.id != eski_id
    bas, bit = _pencere()
    ornekler = [o for o in repo.occurrences(bas, bit) if o.event_id == diriltilen.id]
    assert len(ornekler) > 1  # seri gerçekten dirildi
    assert any(o.is_override for o in ornekler)  # override yeni id'ye bağlandı


def test_uid_cakismasinda_yeni_uid(repo, ders):
    """Aynı UID yeniden yazıldıysa diriltilen yeni UID alır (UNIQUE patlamaz)."""
    uid = new_uid()
    ev = repo.add_event(_seri(ders, uid=uid, title="Algoritma"))
    repo.snapshot_and_delete(ev.id)
    repo.add_event(_seri(ders, uid=uid, title="Yeniden yazılan"))
    diriltilen = repo.restore_last_deleted()
    assert diriltilen.uid != uid
    assert len(repo.search_events("Algoritma")) + len(repo.search_events("Yeniden")) == 2


def test_series_info_sayi_ve_sonsuz(repo, ders):
    """Onay kutusu verisi: 2 yıllık pencerede sayı + sonsuz bayrağı."""
    ev = repo.add_event(_seri(ders, title="Algoritma"))
    bilgi = repo.series_info(ev.id)
    assert bilgi["title"] == "Algoritma"
    assert bilgi["recurring"] is True
    assert bilgi["sonsuz"] is True
    assert bilgi["ornek_sayisi"] > 100  # haftalık × 2 yıl


def test_series_info_tekrarsiz(repo, ders):
    """Tek seferlikte sayı 1, sonsuz False."""
    ev = repo.add_event(_seri(ders, rrule=None))
    bilgi = repo.series_info(ev.id)
    assert (bilgi["ornek_sayisi"], bilgi["sonsuz"], bilgi["recurring"]) == (1, False, False)


def test_series_info_olmayan_404(repo):
    """Kayıtsız id LookupError (sunucuda 404 olacak)."""
    with pytest.raises(LookupError):
        repo.series_info(999)


def test_series_info_sonlu_seride_gercek_toplam(repo, ders):
    """5 yıllık günlük seri 2 yıllık pencereye sığmaz; sayı eksik gösterilmemeli."""
    ev = repo.add_event(_seri(
        ders, rrule="FREQ=DAILY;COUNT=1826"))  # ~5 yıl
    bilgi = repo.series_info(ev.id)
    assert bilgi["sonsuz"] is False
    assert bilgi["ornek_sayisi"] == 1826
