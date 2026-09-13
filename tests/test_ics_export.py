"""Faz 5: `.ics` dışa aktarma.

En önemlisi gidiş-dönüş testleri: dışa aktardığımızı kendi içe aktarıcımızdan
geçirince aynı örnekleri üretmeliyiz. Taşınabilirlik iddiasının tek kanıtı bu.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from core import UTC, Event, to_local
from ics import export_repo, import_ics, write_file
from store import Repo, new_uid
from tests.helpers import IST, NY, ist, ny

DTSTAMP = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def repo():
    """Bellekte taze DB."""
    with Repo.open(":memory:") as r:
        yield r


@pytest.fixture
def ders(repo):
    """Varsayılan takvim."""
    return repo.add_calendar("Ders", "#c0392b")


def _ekle(repo, takvim, baslik, start, end, *, tzid=IST, all_day=False, rrule=None, **kw):
    """Kısa Event kurucusu."""
    return repo.add_event(
        Event(
            id=None, uid=new_uid(), calendar_id=takvim.id, title=baslik,
            start_utc=start, end_utc=end, tzid=tzid, all_day=all_day, rrule=rrule, **kw,
        )
    )


def _satirlar(metin: str) -> list[str]:
    """Katlanmış satırları açıp listeler (RFC 5545 line folding)."""
    acilmis: list[str] = []
    for satir in metin.splitlines():
        if satir.startswith(" ") and acilmis:
            acilmis[-1] += satir[1:]
        else:
            acilmis.append(satir)
    return acilmis


def _vevent_satirlari(metin: str) -> list[str]:
    """Yalnızca VEVENT bloklarının içindeki satırlar.

    Şart: VTIMEZONE blokları da DTSTART taşıyor ve dosyada VEVENT'ten ÖNCE
    geliyor; tüm belgede arama yapmak VTIMEZONE'un satırını yakalar.
    """
    iceride = False
    out: list[str] = []
    for satir in _satirlar(metin):
        if satir == "BEGIN:VEVENT":
            iceride = True
        if iceride:
            out.append(satir)
        if satir == "END:VEVENT":
            iceride = False
    return out


# ---------------------------------------------------------------------------
# Yapı
# ---------------------------------------------------------------------------

def test_vcalendar_iskeleti(repo, ders):
    """Geçerli bir VCALENDAR üretiliyor."""
    _ekle(repo, ders, "Toplantı", ist(2026, 9, 7, 10, 0), ist(2026, 9, 7, 11, 0))
    metin = export_repo(repo, dtstamp=DTSTAMP)

    assert metin.startswith("BEGIN:VCALENDAR")
    assert metin.rstrip().endswith("END:VCALENDAR")
    assert "VERSION:2.0" in metin
    assert "PRODID:-//Aktenak//Takvim 0.1//TR" in metin


def test_saatli_etkinlik_tzid_ile_yazilir(repo, ders):
    """UTC'ye ÇEVRİLMEZ: duvar saati + TZID parametresi.

    UTC'ye çevirseydik tekrarlı etkinliklerin duvar saati karşı tarafta DST
    geçişinde kayardı -- kendi düzelttiğimiz hatayı ihraç etmiş olurduk.
    """
    _ekle(repo, ders, "Ders", ist(2026, 9, 7, 10, 0), ist(2026, 9, 7, 11, 0))
    satirlar = _vevent_satirlari(export_repo(repo, dtstamp=DTSTAMP))

    dtstart = next(s for s in satirlar if s.startswith("DTSTART"))
    assert "TZID=Europe/Istanbul" in dtstart
    assert dtstart.endswith(":20260907T100000"), "yerel duvar saati yazılmalı"
    assert not dtstart.endswith("Z"), "UTC'ye çevrilmemeli"


def test_vtimezone_eklenir(repo, ders):
    """Kullanılan her dilim için VTIMEZONE bloğu."""
    _ekle(repo, ders, "İstanbul", ist(2026, 9, 7, 10, 0), ist(2026, 9, 7, 11, 0))
    _ekle(repo, ders, "New York", ny(2026, 9, 7, 10, 0), ny(2026, 9, 7, 11, 0), tzid=NY)
    metin = export_repo(repo, dtstamp=DTSTAMP)

    assert "TZID:Europe/Istanbul" in metin
    assert "TZID:America/New_York" in metin
    assert metin.count("BEGIN:VTIMEZONE") == 2


def test_tumgun_value_date_ve_dislayici_bitis(repo, ders):
    """Tüm gün: VALUE=DATE, DTEND dışlayıcı (10-12 Eylül -> DTEND 13)."""
    _ekle(repo, ders, "Tatil", ist(2026, 9, 10), ist(2026, 9, 13), all_day=True)
    satirlar = _vevent_satirlari(export_repo(repo, dtstamp=DTSTAMP))

    dtstart = next(s for s in satirlar if s.startswith("DTSTART"))
    dtend = next(s for s in satirlar if s.startswith("DTEND"))
    assert "VALUE=DATE" in dtstart and dtstart.endswith(":20260910")
    assert "VALUE=DATE" in dtend and dtend.endswith(":20260913")
    assert "TZID" not in dtstart, "DATE değerlerinde TZID olmaz"


def test_rrule_korunur(repo, ders):
    """RRULE olduğu gibi aktarılır."""
    _ekle(
        repo, ders, "Haftalık", ist(2026, 9, 7, 10, 0), ist(2026, 9, 7, 11, 0),
        rrule="FREQ=WEEKLY;BYDAY=MO,WE",
    )
    satirlar = _vevent_satirlari(export_repo(repo, dtstamp=DTSTAMP))

    rrule = next(s for s in satirlar if s.startswith("RRULE"))
    assert "FREQ=WEEKLY" in rrule
    assert "BYDAY=MO,WE" in rrule


def test_exdate_rdate_aktarilir(repo, ders):
    """Hariç ve ek tarihler dosyaya girer."""
    repo_event = repo.add_event(
        Event(
            id=None, uid=new_uid(), calendar_id=ders.id, title="Seri",
            start_utc=ist(2026, 9, 7, 10, 0), end_utc=ist(2026, 9, 7, 11, 0),
            tzid=IST, rrule="FREQ=DAILY",
            exdate=(ist(2026, 9, 9, 10, 0),), rdate=(ist(2026, 9, 20, 15, 0),),
        )
    )
    assert repo_event.id is not None
    satirlar = _vevent_satirlari(export_repo(repo, dtstamp=DTSTAMP))

    assert any(s.startswith("EXDATE") for s in satirlar)
    assert any(s.startswith("RDATE") for s in satirlar)


def test_override_recurrence_id_ile_yazilir(repo, ders):
    """Kaydırılan örnek aynı UID + RECURRENCE-ID ile ayrı VEVENT olur."""
    event = _ekle(
        repo, ders, "Ders", ist(2026, 9, 7, 10, 0), ist(2026, 9, 7, 11, 0), rrule="FREQ=DAILY"
    )
    repo.move_occurrence(event.id, ist(2026, 9, 9, 10, 0), ist(2026, 9, 9, 15, 0))
    satirlar = _vevent_satirlari(export_repo(repo, dtstamp=DTSTAMP))

    assert sum(1 for s in satirlar if s.startswith("BEGIN:VEVENT")) == 2
    assert any(s.startswith("RECURRENCE-ID") for s in satirlar)
    assert sum(1 for s in satirlar if s.startswith(f"UID:{event.uid}")) == 2


def test_iptal_edilen_ornek_status_cancelled(repo, ders):
    """İptal edilen örnek STATUS:CANCELLED taşır."""
    event = _ekle(
        repo, ders, "Ders", ist(2026, 9, 7, 10, 0), ist(2026, 9, 7, 11, 0), rrule="FREQ=DAILY"
    )
    repo.cancel_occurrence(event.id, ist(2026, 9, 9, 10, 0))
    metin = export_repo(repo, dtstamp=DTSTAMP)

    assert "STATUS:CANCELLED" in metin


def test_calendar_ids_filtresi(repo, ders):
    """Belirli takvimler aktarılabilir."""
    kisisel = repo.add_calendar("Kişisel", "#2980b9")
    _ekle(repo, ders, "Ders etkinliği", ist(2026, 9, 7, 10, 0), ist(2026, 9, 7, 11, 0))
    _ekle(repo, kisisel, "Kişisel etkinlik", ist(2026, 9, 7, 12, 0), ist(2026, 9, 7, 13, 0))

    metin = export_repo(repo, calendar_ids=[ders.id], dtstamp=DTSTAMP)
    assert "Ders etkinliği" in metin
    assert "Kişisel etkinlik" not in metin


def test_gizli_takvim_de_aktarilir(repo, ders):
    """Dışa aktarma bir YEDEK; ekran filtresi değil."""
    gizli = repo.add_calendar("Arşiv", "#666", visible=False)
    _ekle(repo, gizli, "Eski kayıt", ist(2026, 9, 7, 10, 0), ist(2026, 9, 7, 11, 0))

    assert "Eski kayıt" in export_repo(repo, dtstamp=DTSTAMP)


def test_dosyaya_yazma(repo, ders, tmp_path):
    """write_file diske yazar ve yolu döndürür."""
    _ekle(repo, ders, "Ders", ist(2026, 9, 7, 10, 0), ist(2026, 9, 7, 11, 0))
    hedef = write_file(repo, tmp_path / "takvim.ics")

    assert hedef.exists()
    assert hedef.read_text(encoding="utf-8").startswith("BEGIN:VCALENDAR")


def test_bos_takvim(repo):
    """Etkinlik yoksa yine geçerli bir VCALENDAR çıkar."""
    metin = export_repo(repo, dtstamp=DTSTAMP)
    assert "BEGIN:VCALENDAR" in metin
    assert "BEGIN:VEVENT" not in metin


# ---------------------------------------------------------------------------
# Gidiş-dönüş: asıl kanıt
# ---------------------------------------------------------------------------

def _pencere_ozeti(repo, baslangic, bitis, tzid=IST):
    """Bir penceredeki örnekleri karşılaştırılabilir metne çevirir."""
    return [
        (
            o.title,
            to_local(o.start_utc, tzid).strftime("%Y-%m-%d %H:%M"),
            to_local(o.end_utc, tzid).strftime("%Y-%m-%d %H:%M"),
            o.all_day,
            o.is_override,
        )
        for o in repo.occurrences(baslangic, bitis, include_hidden=True)
    ]


def test_gidis_donus_ayni_ornekleri_uretir(repo, tmp_path):
    """Demo veriyi dışa aktar, taze DB'ye içe aktar, hafta aynı olmalı."""
    from ui.demo import seed

    seed(repo, date(2026, 9, 7))
    dosya = write_file(repo, tmp_path / "yedek.ics")
    beklenen = _pencere_ozeti(repo, ist(2026, 9, 7), ist(2026, 9, 14))

    with Repo.open(":memory:") as yeni:
        hedef = yeni.add_calendar("İçe aktarılan", "#888")
        rapor = import_ics(yeni, dosya, calendar_id=hedef.id, default_tzid=IST)

        assert rapor.errors == (), f"içe aktarma hatasız olmalı: {rapor.errors}"
        assert _pencere_ozeti(yeni, ist(2026, 9, 7), ist(2026, 9, 14)) == beklenen


def test_gidis_donus_dst_koruyor(repo):
    """New York'ta günlük 09:00, gidiş-dönüşten sonra da 09:00 kalmalı.

    Dışa aktarırken UTC'ye çevirseydik bu test geçiş haftasında kırılırdı.
    """
    takvim = repo.add_calendar("NY", "#111")
    _ekle(
        repo, takvim, "Standup", ny(2026, 3, 1, 9, 0), ny(2026, 3, 1, 10, 0),
        tzid=NY, rrule="FREQ=DAILY",
    )
    metin = export_repo(repo, dtstamp=DTSTAMP)

    with Repo.open(":memory:") as yeni:
        hedef = yeni.add_calendar("İçe", "#222")
        # default_tzid KASTEN farklı (İstanbul). Dilim bilgisi dosyadaki TZID'den
        # gelmek ZORUNDA; varsayılanla aynı verseydik, dışa aktarma UTC'ye
        # düşse bile test kazara geçerdi.
        rapor = import_ics(yeni, metin, calendar_id=hedef.id, default_tzid=IST)
        assert rapor.errors == ()
        assert yeni.list_events()[0].tzid == NY, "TZID dosyadan okunmalı"

        # 8 Mart 2026 DST geçişi; öncesi ve sonrası 09:00 kalmalı
        occs = yeni.occurrences(ny(2026, 3, 6), ny(2026, 3, 11), include_hidden=True)
        yerel = [to_local(o.start_utc, NY).strftime("%m-%d %H:%M") for o in occs]

        assert yerel == [
            "03-06 09:00", "03-07 09:00", "03-08 09:00", "03-09 09:00", "03-10 09:00"
        ]
        # UTC karşılığı geçişte kaymalı: kayma yoksa dilim bilgisi kaybolmuştur
        utc = {o.start_utc.strftime("%H:%M") for o in occs}
        assert len(utc) == 2, f"DST geçişi UTC'de görünmeli, alınan: {utc}"


def test_gidis_donus_override_koruyor(repo, ders):
    """Kaydırma ve iptal gidiş-dönüşte hayatta kalır."""
    event = _ekle(
        repo, ders, "Ders", ist(2026, 9, 7, 10, 0), ist(2026, 9, 7, 11, 0), rrule="FREQ=DAILY"
    )
    repo.move_occurrence(event.id, ist(2026, 9, 9, 10, 0), ist(2026, 9, 9, 15, 0))
    repo.cancel_occurrence(event.id, ist(2026, 9, 10, 10, 0))
    metin = export_repo(repo, dtstamp=DTSTAMP)

    with Repo.open(":memory:") as yeni:
        hedef = yeni.add_calendar("İçe", "#222")
        rapor = import_ics(yeni, metin, calendar_id=hedef.id, default_tzid=IST)
        assert rapor.errors == ()

        ozet = _pencere_ozeti(yeni, ist(2026, 9, 7), ist(2026, 9, 12))
        saatler = [s for _, s, _, _, _ in ozet]

        assert "2026-09-09 15:00" in saatler, "kaydırma korunmalı"
        assert "2026-09-09 10:00" not in saatler
        assert not any(s.startswith("2026-09-10") for s in saatler), "iptal korunmalı"


def test_gidis_donus_tumgun_koruyor(repo, ders):
    """Çok günlü tüm gün etkinliği gün sayısını korur."""
    _ekle(repo, ders, "Tatil", ist(2026, 9, 9), ist(2026, 9, 12), all_day=True)
    metin = export_repo(repo, dtstamp=DTSTAMP)

    with Repo.open(":memory:") as yeni:
        hedef = yeni.add_calendar("İçe", "#222")
        import_ics(yeni, metin, calendar_id=hedef.id, default_tzid=IST)

        gelen = yeni.list_events()[0]
        assert gelen.all_day is True
        assert gelen.start_utc == ist(2026, 9, 9)
        assert gelen.end_utc == ist(2026, 9, 12), "3 gün, bitiş dışlayıcı"
