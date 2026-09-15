"""Seri bölme (`split_series`, RFC 5545 RANGE=THISANDFUTURE karşılığı).

`[..., split)` eski seride kalır, `[split, ...)` yeni seriye taşınır.
Kural: tek test tek davranış.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from core import UTC, Override, instance_starts
from store import Repo, new_uid
from tests.helpers import ist, make_event


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
    kwargs.setdefault("event_id", None)
    kwargs.setdefault("uid", new_uid())
    kwargs.setdefault("calendar_id", ders.id)
    kwargs.setdefault("rrule", "FREQ=WEEKLY;BYDAY=MO")
    return make_event(
        kwargs.pop("start", ist(2026, 9, 7, 10, 0)),
        kwargs.pop("end", ist(2026, 9, 7, 11, 0)),
        **kwargs,
    )


def _baslangiclar(repo, event_id, bas, bit):
    return sorted(
        o.start_utc for o in repo.occurrences(bas, bit) if o.event_id == event_id
    )


def test_instance_starts_iptal_edileni_de_sayar(repo, ders):
    """Kural düzeyi liste: iptal override'ı sayıyı eksiltmez."""
    ev = repo.add_event(_seri(ders, rrule="FREQ=WEEKLY;BYDAY=MO;COUNT=4"))
    repo.cancel_occurrence(ev.id, ist(2026, 9, 14, 10, 0))
    assert len(instance_starts(repo.get_event(ev.id))) == 4


def test_instance_starts_sonsuzda_before_sart():
    """Sonsuz seride `before` yoksa ValueError (liste bitmez)."""
    with pytest.raises(ValueError):
        instance_starts(make_event(ist(2026, 9, 7, 10, 0), ist(2026, 9, 7, 11, 0),
                                   rrule="FREQ=WEEKLY;BYDAY=MO"))


def test_instance_starts_before_siniri(repo, ders):
    """`before` eşitliği hariç tutuyor."""
    ev = repo.add_event(_seri(ders, rrule="FREQ=WEEKLY;BYDAY=MO;COUNT=4"))
    once = instance_starts(repo.get_event(ev.id), before=ist(2026, 9, 14, 10, 0))
    assert len(once) == 1  # yalnızca 7 Eylül


def test_bolme_ornekleri_ikiye_ayirir(repo, ders):
    """Bölmeden önceki örnekler eskide, sonrakiler yenide; toplam korunur."""
    ev = repo.add_event(_seri(ders))
    bas = datetime(2026, 9, 1, tzinfo=UTC)
    bit = datetime(2026, 11, 1, tzinfo=UTC)
    toplam_once = len(repo.occurrences(bas, bit))
    sonuc = repo.split_series(ev.id, ist(2026, 9, 21, 10, 0))
    assert sonuc["eski_id"] == ev.id and sonuc["yeni_id"] != ev.id
    tum = repo.occurrences(bas, bit)
    assert len(tum) == toplam_once
    assert _baslangiclar(repo, ev.id, bas, bit)[-1] < ist(2026, 9, 21, 10, 0)
    assert _baslangiclar(repo, sonuc["yeni_id"], bas, bit)[0] == ist(2026, 9, 21, 10, 0)


def test_bolme_sinirsiza_until_ekler(repo, ders):
    """Sınırsız serinin eskisine UNTIL geliyor, yenisi sınırsız kalıyor."""
    ev = repo.add_event(_seri(ders))
    sonuc = repo.split_series(ev.id, ist(2026, 9, 21, 10, 0))
    eski = repo.get_event(ev.id)
    yeni = repo.get_event(sonuc["yeni_id"])
    assert "UNTIL=" in (eski.rrule or "") and "COUNT=" not in (eski.rrule or "")
    assert "UNTIL=" not in (yeni.rrule or "") and yeni.rrule == "FREQ=WEEKLY;BYDAY=MO"


def test_bolme_countu_paylastirir(repo, ders):
    """COUNT=10, 4. örnekten bölününce 3 + 7 oluyor."""
    ev = repo.add_event(_seri(ders, rrule="FREQ=WEEKLY;BYDAY=MO;COUNT=10"))
    sonuc = repo.split_series(ev.id, ist(2026, 9, 28, 10, 0))
    assert "COUNT=3" in (repo.get_event(ev.id).rrule or "")
    assert "COUNT=7" in (repo.get_event(sonuc["yeni_id"]).rrule or "")


def test_bolme_untilde_eski_kisalir_yeni_korunur(repo, ders):
    """UNTIL'li seride eski sınır bölmeye çekiliyor, yeni orijinali tutuyor."""
    ev = repo.add_event(
        _seri(ders, rrule="FREQ=WEEKLY;BYDAY=MO;UNTIL=20261231T000000Z"))
    sonuc = repo.split_series(ev.id, ist(2026, 9, 21, 10, 0))
    eski = repo.get_event(ev.id).rrule or ""
    yeni = repo.get_event(sonuc["yeni_id"]).rrule or ""
    assert "UNTIL=20260921T065959Z" in eski  # 21.09 10:00 +03:00 = 07:00Z, -1sn
    assert eski.count("UNTIL=") == 1  # çift UNTIL yazılmıyor
    assert "UNTIL=20261231T000000Z" in yeni


def test_bolme_baslik_degisimini_yeniye_yazar(repo, ders):
    """Başlık değişimi yalnızca yeni seride."""
    ev = repo.add_event(_seri(ders, title="Algoritma"))
    sonuc = repo.split_series(ev.id, ist(2026, 9, 21, 10, 0), title="Veri Yapıları")
    assert repo.get_event(ev.id).title == "Algoritma"
    assert repo.get_event(sonuc["yeni_id"]).title == "Veri Yapıları"


def test_bolme_override_dagitir(repo, ders):
    """Öncekiler eskide, sonrakiler (iptal dahil) yenide."""
    ev = repo.add_event(_seri(ders))
    repo.put_override(Override(
        event_id=ev.id, original_start_utc=ist(2026, 9, 14, 10, 0),
        new_start_utc=ist(2026, 9, 14, 12, 0)))
    repo.cancel_occurrence(ev.id, ist(2026, 9, 28, 10, 0))
    sonuc = repo.split_series(ev.id, ist(2026, 9, 21, 10, 0))
    eski_ov = repo.list_overrides(ev.id)
    yeni_ov = repo.list_overrides(sonuc["yeni_id"])
    assert [o.original_start_utc for o in eski_ov] == [ist(2026, 9, 14, 10, 0)]
    assert [o.original_start_utc for o in yeni_ov] == [ist(2026, 9, 28, 10, 0)]
    assert yeni_ov[0].cancelled is True


def test_bolme_hatirlatici_kopyalar_fired_tasir(repo, ders):
    """Hatırlatıcılar kopyalanıyor; bölme sonrası fired yeni id'ye taşınıyor."""
    ev = repo.add_event(_seri(ders))
    hat = repo.add_reminder(ev.id, 30)
    repo.mark_fired(hat.id, ist(2026, 9, 7, 10, 0))   # bölmeden önce
    repo.mark_fired(hat.id, ist(2026, 9, 28, 10, 0))  # bölmeden sonra
    sonuc = repo.split_series(ev.id, ist(2026, 9, 21, 10, 0))
    yeni_hatlar = repo.list_reminders(sonuc["yeni_id"])
    assert [h.minutes_before for h in yeni_hatlar] == [30]
    # Yeni hatırlatıcıda 28 Eylül ÖTMÜŞ sayılıyor (mükerrer bildirim yok):
    assert repo.mark_fired(yeni_hatlar[0].id, ist(2026, 9, 28, 10, 0)) is False
    # Eski hatırlatıcıda 7 Eylül duruyor:
    assert repo.mark_fired(hat.id, ist(2026, 9, 7, 10, 0)) is False


def test_bolme_ilk_ornekten_reddedilir(repo, ders):
    """İlk örnekten bölünemez (eski seri boş kalırdı)."""
    ev = repo.add_event(_seri(ders))
    with pytest.raises(ValueError):
        repo.split_series(ev.id, ist(2026, 9, 7, 10, 0))


def test_bolme_ornek_olmayan_noktadan_reddedilir(repo, ders):
    """Kurala uymayan tarih bölme noktası olamaz."""
    ev = repo.add_event(_seri(ders))
    with pytest.raises(ValueError):
        repo.split_series(ev.id, ist(2026, 9, 8, 10, 0))  # salı, seri pazartesi


def test_bolme_tekrarsizda_reddedilir(repo, ders):
    """Tek seferlik bölünemez."""
    ev = repo.add_event(_seri(ders, rrule=None))
    with pytest.raises(ValueError):
        repo.split_series(ev.id, ist(2026, 9, 7, 10, 0))


def test_bolme_cok_kurallida_reddedilir(repo, ders):
    """Birden çok RRULE satırı olan seri bölünemez (sayım belirsiz)."""
    ev = repo.add_event(_seri(ders, rrule="FREQ=WEEKLY;BYDAY=MO\nFREQ=DAILY;COUNT=3"))
    with pytest.raises(ValueError):
        repo.split_series(ev.id, ist(2026, 9, 14, 10, 0))


def test_bolme_rdate_serisini_ayirir(repo, ders):
    """RRULE'suz (RDATE) seri tarihlere göre ikiye ayrılıyor."""
    ev = repo.add_event(_seri(
        ders, rrule=None,
        rdate=(ist(2026, 9, 14, 10, 0), ist(2026, 9, 21, 10, 0))))
    sonuc = repo.split_series(ev.id, ist(2026, 9, 14, 10, 0))
    assert repo.get_event(ev.id).rdate == ()
    # 14 Eylül yeni DTSTART (tekrarsız yazılmıyor), 21 Eylül RDATE taşınıyor:
    assert repo.get_event(sonuc["yeni_id"]).rdate == (ist(2026, 9, 21, 10, 0),)


def test_bolme_count_exdate_kaybetmez(repo, ders):
    """COUNT + EXDATE: iptal edilmiş örnek de sayaçta durur, örnek kaybolmaz."""
    ev = repo.add_event(_seri(
        ders, rrule="FREQ=WEEKLY;BYDAY=MO;COUNT=5",
        exdate=(ist(2026, 9, 7, 10, 0),)))
    bas = datetime(2026, 9, 1, tzinfo=UTC)
    bit = datetime(2026, 11, 1, tzinfo=UTC)
    once = sorted(o.start_utc for o in repo.occurrences(bas, bit))
    assert len(once) == 4
    sonuc = repo.split_series(ev.id, ist(2026, 9, 21, 10, 0))
    sonra = sorted(o.start_utc for o in repo.occurrences(bas, bit))
    assert sonra == once
    assert "COUNT=2" in (repo.get_event(ev.id).rrule or "")
    assert "COUNT=3" in (repo.get_event(sonuc["yeni_id"]).rrule or "")


def test_bolme_rdate_noktasinda_carsamba_kaybolmaz(repo, ders):
    """BYDAY'li kural + Çarşamba RDATE'ten bölünce Çarşamba durur, Pazartesiler kalır."""
    ev = repo.add_event(_seri(
        ders, rrule="FREQ=WEEKLY;BYDAY=MO",
        rdate=(ist(2026, 9, 9, 10, 0),)))
    bas = datetime(2026, 9, 1, tzinfo=UTC)
    bit = datetime(2026, 10, 15, tzinfo=UTC)
    once = sorted(o.start_utc for o in repo.occurrences(bas, bit))
    sonuc = repo.split_series(ev.id, ist(2026, 9, 9, 10, 0))
    sonra = sorted(o.start_utc for o in repo.occurrences(bas, bit))
    assert sonra == once
    assert ist(2026, 9, 9, 10, 0) in sonra
    assert sonuc["yeni_id"] != ev.id


def test_bolme_rdate_noktasinda_gun_kaymaz(repo, ders):
    """BYDAY'siz kural + RDATE'ten bölünce kalan günler kaymaz (Pazartesi kalır)."""
    ev = repo.add_event(_seri(
        ders, rrule="FREQ=WEEKLY",
        rdate=(ist(2026, 9, 9, 10, 0),)))
    bas = datetime(2026, 9, 1, tzinfo=UTC)
    bit = datetime(2026, 10, 15, tzinfo=UTC)
    once = sorted(o.start_utc for o in repo.occurrences(bas, bit))
    sonuc = repo.split_series(ev.id, ist(2026, 9, 9, 10, 0))
    sonra = sorted(o.start_utc for o in repo.occurrences(bas, bit))
    assert sonra == once
    yeni = repo.get_event(sonuc["yeni_id"])
    assert "BYDAY=MO" in (yeni.rrule or "")


def test_bolme_olmayan_etkinlikte_404luk(repo):
    """Kayıtsız id LookupError (sunucuda 404 olacak)."""
    with pytest.raises(LookupError):
        repo.split_series(999, ist(2026, 9, 21, 10, 0))
