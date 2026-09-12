"""Faz 2 kabul kriterleri: `.ics` içe aktarma.

Her test tek davranış ölçer; fixture'lar `tests/fixtures/` altında küçük `.ics`
parçalarıdır. Parse tuzakları DB'siz (`parse_ics`), yazma davranışları `Repo`
ile (`import_ics`) sınanır.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from core import UTC, Event, expand, from_wall_clock, to_local
from ics import import_ics, parse_ics
from store import Repo

IST = "Europe/Istanbul"
FIXTURES = Path(__file__).parent / "fixtures"


def _repo():
    """Bellekte taze DB + görünür takvim; kapatmayı çağırana bırakır."""
    repo = Repo.open(":memory:")
    takvim = repo.add_calendar("Test", "#111111")
    return repo, takvim


def _duvar(y, m, d, h=0, mi=0, tzid=IST):
    """Yerel duvar saatinden UTC an."""
    return from_wall_clock(datetime(y, m, d, h, mi), tzid)


# ---------------------------------------------------------------------------
# 1-3: temel zamanlar
# ---------------------------------------------------------------------------


def test_tek_seferlik_saatli_etkinlik():
    """TZID=Europe/Istanbul saatli etkinlik doğru ana çevrilir."""
    parsed, rapor = parse_ics(FIXTURES / "tek_saatli.ics", default_tzid=IST)

    assert rapor.errors == ()
    assert len(parsed) == 1
    event = parsed[0].event
    assert event.title == "Toplantı"
    assert event.tzid == IST
    assert event.all_day is False
    assert event.start_utc == datetime(2024, 6, 10, 7, 0, tzinfo=UTC)
    assert event.end_utc == datetime(2024, 6, 10, 8, 0, tzinfo=UTC)


def test_cok_gunlu_tumgun_dtend_dislayici():
    """DTSTART=10 + DTEND=13 DATE = 10,11,12 Haziran (3 gün), 13 dahil değil."""
    parsed, _ = parse_ics(FIXTURES / "tumgun_cokgun.ics", default_tzid=IST)

    event = parsed[0].event
    assert event.all_day is True
    assert event.duration == timedelta(days=3)
    assert to_local(event.start_utc, IST).date().isoformat() == "2024-06-10"
    assert to_local(event.end_utc, IST).date().isoformat() == "2024-06-13"


def test_dtend_yok_duration_var():
    """DTEND yoksa bitiş DURATION'dan hesaplanır."""
    parsed, _ = parse_ics(FIXTURES / "duration.ics", default_tzid=IST)

    event = parsed[0].event
    assert event.start_utc == datetime(2024, 6, 10, 7, 0, tzinfo=UTC)
    assert event.end_utc == datetime(2024, 6, 10, 8, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# 4-6: tekrar ve örnek geçersiz kılmaları
# ---------------------------------------------------------------------------


def test_haftalik_rrule_iki_exdate_satiri():
    """İki EXDATE satırı (biri virgüllü) toplanır: 1+2 = 3 dışlama."""
    parsed, _ = parse_ics(FIXTURES / "haftalik_exdate.ics", default_tzid=IST)

    event = parsed[0].event
    assert "FREQ=WEEKLY" in (event.rrule or "")
    assert len(event.exdate) == 3
    assert event.exdate[0] == datetime(2024, 6, 17, 7, 0, tzinfo=UTC)


def test_recurrence_id_kaydirma_expandde_gorunur():
    """RECURRENCE-ID ile kaydırılan örnek Override olur, expand'de taşınmış görünür."""
    repo, takvim = _repo()
    try:
        rapor = import_ics(repo, FIXTURES / "ornek_kaydirma.ics", calendar_id=takvim.id, default_tzid=IST)
        assert rapor.added == 1
        assert rapor.overrides == 1

        pencere = (_duvar(2024, 6, 17), _duvar(2024, 6, 18))
        bulunan = repo.occurrences(*pencere)
        assert len(bulunan) == 1
        assert bulunan[0].is_override is True
        assert to_local(bulunan[0].start_utc, IST).strftime("%H:%M") == "12:00"

        # Sonsuz seride series_end_utc NULL kalır.
        etkinlik = repo.get_event_by_uid("ornek-kaydirma-1")
        assert repo.metadata(etkinlik.id)["series_end_utc"] is None
    finally:
        repo.close()


def test_recurrence_id_iptal_override_cancelled():
    """RECURRENCE-ID + STATUS:CANCELLED -> Override(cancelled=True), örnek yok."""
    repo, takvim = _repo()
    try:
        rapor = import_ics(repo, FIXTURES / "ornek_iptal.ics", calendar_id=takvim.id, default_tzid=IST)
        assert rapor.overrides == 1

        pencere = (_duvar(2024, 6, 10), _duvar(2024, 6, 25))
        bulunan = repo.occurrences(*pencere)
        gunler = sorted(to_local(o.start_utc, IST).day for o in bulunan)
        assert gunler == [10, 24]
    finally:
        repo.close()


# ---------------------------------------------------------------------------
# 7-9: saat dilimi tuzakları
# ---------------------------------------------------------------------------


def test_windows_saat_dilimi_cevrilir():
    """TZID='Türkiye Standart Saati' IANA'ya çevrilir, uyarı yok."""
    parsed, rapor = parse_ics(FIXTURES / "windows_tz.ics", default_tzid=IST)

    event = parsed[0].event
    assert event.tzid == IST
    assert event.start_utc == datetime(2024, 6, 10, 7, 0, tzinfo=UTC)
    assert not any("bilinmiyor" in w for w in rapor.warnings)


def test_w_europe_windows_adi_berline_cevrilir():
    """TZID='W. Europe Standard Time' -> Europe/Berlin (farklı ofset kanıtlar)."""
    metin = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:w-europe-1\r\n"
        "DTSTART;TZID=W. Europe Standard Time:20240610T100000\r\n"
        "DTEND;TZID=W. Europe Standard Time:20240610T110000\r\n"
        "SUMMARY:X\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    parsed, _ = parse_ics(metin, default_tzid=IST)

    event = parsed[0].event
    assert event.tzid == "Europe/Berlin"
    # Berlin Haziran'da +2, İstanbul +3: aynı duvar saati farklı ana düşer.
    assert event.start_utc == datetime(2024, 6, 10, 8, 0, tzinfo=UTC)


def test_bilinmeyen_tz_defaulta_duser_uyari_uretir():
    """Bilinmeyen TZID sessizce UTC'ye değil default'a düşer ve uyarır."""
    parsed, rapor = parse_ics(FIXTURES / "bilinmeyen_tz.ics", default_tzid=IST)

    event = parsed[0].event
    assert event.tzid == IST
    assert event.start_utc == datetime(2024, 6, 10, 7, 0, tzinfo=UTC)
    assert any("Customized Time Zone" in w for w in rapor.warnings)


def test_kayan_zaman_defaultta_yorumlanir():
    """TZID'siz ve Z'siz zamanlar default dilimde yorumlanır, uyarı yok."""
    parsed, rapor = parse_ics(FIXTURES / "kayan.ics", default_tzid=IST)

    event = parsed[0].event
    assert event.tzid == IST
    assert event.start_utc == datetime(2024, 6, 10, 7, 0, tzinfo=UTC)
    assert rapor.warnings == ()


def test_utc_zamanlar_default_tzid_alir_an_dogru():
    """`Z` sonekli anlar doğru çevrilir, tzid hanesi default olur."""
    parsed, _ = parse_ics(FIXTURES / "utc.ics", default_tzid=IST)

    event = parsed[0].event
    assert event.tzid == IST
    assert event.start_utc == datetime(2024, 6, 10, 7, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# 10-11: bozuk kayıt ve VTODO
# ---------------------------------------------------------------------------


def test_bozuk_vevent_errors_kalani_aktarilir():
    """DTEND<DTSTART olan kayıt errors'a yazılır, sağlam kayıt içe aktarılır."""
    parsed, rapor = parse_ics(FIXTURES / "bozuk.ics", default_tzid=IST)
    assert len(parsed) == 1
    assert parsed[0].event.uid == "saglam-1"
    assert len(rapor.errors) == 1
    assert rapor.errors[0][0] == "bozuk-1"

    repo, takvim = _repo()
    try:
        irapor = import_ics(repo, FIXTURES / "bozuk.ics", calendar_id=takvim.id, default_tzid=IST)
        assert irapor.added == 1
        assert len(irapor.errors) == 1
        assert [e.uid for e in repo.list_events()] == ["saglam-1"]
    finally:
        repo.close()


def test_vtodo_atlanir_hata_yok():
    """VTODO/VTIMEZONE atlanır, hata sayılmaz."""
    parsed, rapor = parse_ics(FIXTURES / "vtodo.ics", default_tzid=IST)

    assert len(parsed) == 1
    assert parsed[0].event.uid == "vtodo-yaninda-1"
    assert rapor.errors == ()


# ---------------------------------------------------------------------------
# 12-14: yazma davranışları ve uçtan uca
# ---------------------------------------------------------------------------


def test_iki_kez_ice_aktarma_mukerrer_yok():
    """Aynı dosya iki kez: ikinci seferde added=0, tek satır."""
    repo, takvim = _repo()
    try:
        ilk = import_ics(repo, FIXTURES / "tek_saatli.ics", calendar_id=takvim.id, default_tzid=IST)
        ikinci = import_ics(repo, FIXTURES / "tek_saatli.ics", calendar_id=takvim.id, default_tzid=IST)

        assert ilk.added == 1
        assert ikinci.added == 0
        assert len(repo.list_events()) == 1
    finally:
        repo.close()


def test_sequence_kucukse_atlanir():
    """SEQUENCE eski dosya yeniyi ezmez."""
    repo, takvim = _repo()
    try:
        import_ics(repo, FIXTURES / "sira_v1.ics", calendar_id=takvim.id, default_tzid=IST)
        rapor = import_ics(repo, FIXTURES / "sira_v0.ics", calendar_id=takvim.id, default_tzid=IST)

        assert rapor.skipped == 1
        assert rapor.updated == 0
        assert repo.get_event_by_uid("sira-1").title == "Eski başlık"
    finally:
        repo.close()


def test_dry_run_db_degismez_rapor_doluyor():
    """dry_run=True yazmaz ama rapor yine sayar."""
    repo, takvim = _repo()
    try:
        rapor = import_ics(
            repo, FIXTURES / "tek_saatli.ics", calendar_id=takvim.id, default_tzid=IST, dry_run=True
        )

        assert rapor.added == 1
        assert repo.list_events() == []
    finally:
        repo.close()


def test_uctan_uca_hafta_sorgusu():
    """İçe aktar -> occurrences ile haftayı sorgula -> beklenen örnekler."""
    repo, takvim = _repo()
    try:
        import_ics(repo, FIXTURES / "e2e.ics", calendar_id=takvim.id, default_tzid=IST)

        bulunan = repo.occurrences(_duvar(2024, 6, 10), _duvar(2024, 6, 17))
        # Günlük COUNT=7 serisinden 7 + tekil toplantı = 8 örnek.
        assert len(bulunan) == 8
        onikisi = [o for o in bulunan if to_local(o.start_utc, IST).day == 12]
        assert sorted(o.title for o in onikisi) == ["Sabah dersi", "Öğleden sonra toplantısı"]

        # COUNT'lu seride seri sonu son örneğin bitişidir.
        seri = repo.get_event_by_uid("e2e-gunluk-1")
        assert repo.metadata(seri.id)["series_end_utc"] == _duvar(2024, 6, 16, 10)
    finally:
        repo.close()


# ---------------------------------------------------------------------------
# Ek tuzaklar: kararların çivisi
# ---------------------------------------------------------------------------


def test_naive_until_ham_saklanir():
    """Naive UNTIL dönüştürülmeden saklanır; `core` zaten normalize ediyor."""
    parsed, _ = parse_ics(FIXTURES / "naive_until.ics", default_tzid=IST)

    rrule = parsed[0].event.rrule or ""
    assert "UNTIL=20240612T100000" in rrule
    assert "UNTIL=20240612T100000Z" not in rrule

    # Seri yine de doğru genişler: 10, 11, 12 Haziran.
    ornekler = expand(parsed[0].event, [], _duvar(2024, 6, 10), _duvar(2024, 6, 13))
    assert [to_local(o.start_utc, IST).day for o in ornekler] == [10, 11, 12]


def test_thisandfuture_errorsa_yazilir():
    """RANGE=THISANDFUTURE modelde yok: hata sayılır, ana kayıt korunur."""
    parsed, rapor = parse_ics(FIXTURES / "thisandfuture.ics", default_tzid=IST)

    assert len(parsed) == 1
    assert parsed[0].overrides == ()
    assert len(rapor.errors) == 1
    assert "THISANDFUTURE" in rapor.errors[0][1]


def test_bitisiz_saatli_bir_saat_varsayilir():
    """DTEND ve DURATION yoksa (saatli) 1 saat varsayılır + uyarı üretilir."""
    parsed, rapor = parse_ics(FIXTURES / "endsiz.ics", default_tzid=IST)

    event = parsed[0].event
    assert event.end_utc - event.start_utc == timedelta(hours=1)
    assert any("1 saat" in w for w in rapor.warnings)


# ---------------------------------------------------------------------------
# ics_sequence: yerel revizyon sayacından ayrıldı (002 migration)
# ---------------------------------------------------------------------------


def test_yerel_duzenleme_sonrasi_yeniden_ice_aktarma_atlanmaz():
    """Elle düzenlenen etkinlik, aynı dosya tekrar aktarılınca güncellenmeli.

    Regresyon: `.ics` sürümü Repo'nun `sequence` sayacına yazıldığı sürece bir
    kez elle düzenlemek (sequence 0 -> 1) SEQUENCE'siz her dosyayı sonsuza dek
    "eski" yapıyordu ve içe aktarma sessizce düşüyordu.
    """
    repo, takvim = _repo()
    try:
        import_ics(repo, FIXTURES / "tek_saatli.ics", calendar_id=takvim.id, default_tzid=IST)
        kayit = repo.get_event_by_uid("tek-saatli-1")

        repo.update_event(replace(kayit, title="Elle değiştirdim"))
        assert repo.metadata(kayit.id)["sequence"] == 1, "yerel sayaç artmalı"
        assert repo.get_ics_sequence(kayit.id) == 0, ".ics sürümü sabit kalmalı"

        rapor = import_ics(
            repo, FIXTURES / "tek_saatli.ics", calendar_id=takvim.id, default_tzid=IST
        )

        assert rapor.skipped == 0
        assert rapor.updated == 1
        assert repo.get_event_by_uid("tek-saatli-1").title == "Toplantı"
    finally:
        repo.close()


def test_eskimis_dosya_atlanirken_uyari_uretir():
    """Gerçekten eski dosya atlanır ama SESSİZCE değil: sebebi rapora yazılır."""
    repo, takvim = _repo()
    try:
        import_ics(repo, FIXTURES / "sira_v1.ics", calendar_id=takvim.id, default_tzid=IST)
        rapor = import_ics(repo, FIXTURES / "sira_v0.ics", calendar_id=takvim.id, default_tzid=IST)

        assert rapor.skipped == 1
        assert rapor.updated == 0
        assert any(
            "sira-1" in uyari and "SEQUENCE" in uyari for uyari in rapor.warnings
        ), f"atlama gerekçesi raporlanmalı, alınan: {rapor.warnings}"
    finally:
        repo.close()


def test_elle_olusturulan_etkinlik_ice_aktarmayi_engellemez():
    """`ics_sequence` NULL ise karşılaştıracak sürüm yoktur; aktarma kabul edilir."""
    repo, takvim = _repo()
    try:
        repo.add_event(
            Event(
                id=None,
                uid="tek-saatli-1",
                calendar_id=takvim.id,
                title="Elle oluşturdum",
                start_utc=_duvar(2024, 6, 10, 9),
                end_utc=_duvar(2024, 6, 10, 10),
                tzid=IST,
            )
        )
        kayit = repo.get_event_by_uid("tek-saatli-1")
        assert repo.get_ics_sequence(kayit.id) is None

        rapor = import_ics(
            repo, FIXTURES / "tek_saatli.ics", calendar_id=takvim.id, default_tzid=IST
        )

        assert rapor.skipped == 0
        assert rapor.updated == 1
        assert repo.get_event_by_uid("tek-saatli-1").title == "Toplantı"
        assert repo.get_ics_sequence(kayit.id) == 0
    finally:
        repo.close()


def test_ice_aktarma_yerel_sayaci_ezmez():
    """İçe aktarma `sequence` kolonuna dokunmaz; iki alan bağımsız kalır."""
    repo, takvim = _repo()
    try:
        import_ics(repo, FIXTURES / "sira_v1.ics", calendar_id=takvim.id, default_tzid=IST)
        kayit = repo.get_event_by_uid("sira-1")

        meta = repo.metadata(kayit.id)
        assert meta["sequence"] == 0, "yeni kayıtta yerel sayaç 0"
        assert meta["ics_sequence"] == 1, "dosyadaki SEQUENCE ayrı kolonda"
    finally:
        repo.close()
