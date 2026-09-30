"""Görevler ve `.ics`: VTODO dışa/içe aktarma.

Görev saat planlıysa saati bağlı etkinlikte (blok) durur; dışa aktarıcı VTODO'ya
`X-TAKVIM-BLOK-UID` yazıyor ve içe aktarıcı görevi ikinci bir blok açmadan ona
bağlıyor. Gün planlıda yalnızca `DUE` (tarih) var.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from core import UTC, Task
from ics import export_repo, import_ics, parse_ics, parse_ics_tasks
from store import Repo, new_uid
from tests.helpers import IST, NY, ist

DTSTAMP = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)


@pytest.fixture
def repo():
    with Repo.open(":memory:") as r:
        yield r


@pytest.fixture
def kisisel(repo):
    return repo.add_calendar("Kişisel", "#3366cc")


def _gorev(**kw):
    kw.setdefault("id", None)
    kw.setdefault("uid", new_uid())
    kw.setdefault("title", "Rapor yaz")
    return Task(**kw)


def _ics(*bilesenler):
    """Verilen ham bileşen satırlarından tam bir VCALENDAR metni kurar."""
    return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Test//TR", *bilesenler, "END:VCALENDAR", ""])


def _vtodo(*satirlar):
    return "\r\n".join(["BEGIN:VTODO", *satirlar, "END:VTODO"])


_ACIK: list[Repo] = []


@pytest.fixture(autouse=True)
def _aktarilan_repolari_kapat():
    """`_yeni_repo_ile_aktar` depoyu döndürüyor (test onu sorguluyor): kapatma test sonunda."""
    yield
    while _ACIK:
        _ACIK.pop().close()


def _yeni_repo_ile_aktar(metin, **kw):
    """Boş bir depoya içe aktarır; (depo, rapor) döndürür."""
    r = Repo.open(":memory:")
    _ACIK.append(r)
    k = r.add_calendar("Hedef", "#111111")
    rapor = import_ics(r, metin, calendar_id=k.id, default_tzid=kw.pop("default_tzid", IST), **kw)
    return r, rapor


# ---------------------------------------------------------------------------
# Dışa aktarma
# ---------------------------------------------------------------------------

def test_plansiz_gorev_vtodo_olarak_yazilir(repo):
    repo.add_task(_gorev(uid="g1@t", title="Rapor yaz", notes="taslak"))

    metin = export_repo(repo, dtstamp=DTSTAMP)

    assert "BEGIN:VTODO" in metin and "UID:g1@t" in metin and "SUMMARY:Rapor yaz" in metin
    assert "DESCRIPTION:taslak" in metin and "STATUS:NEEDS-ACTION" in metin
    assert "DUE" not in metin and "DTSTART" not in metin, "plansız görevin zamanı yok"


def test_gun_planli_gorev_yalniz_due_tarihi_yazar(repo):
    """Saatsiz görev tüm gün etkinliği gibi değil, tarihli VTODO olarak yazılmalı."""
    repo.add_task(_gorev(uid="g1@t", plan_day=date(2026, 10, 1)))

    metin = export_repo(repo, dtstamp=DTSTAMP)

    assert "DUE;VALUE=DATE:20261001" in metin
    assert "BEGIN:VEVENT" not in metin


def test_tamamlanan_gorev_completed_isaretleri_yazar(repo):
    g = repo.add_task(_gorev(uid="g1@t"))
    repo.set_task_done(g.id, True, at=datetime(2026, 9, 29, 12, 30, tzinfo=UTC))

    metin = export_repo(repo, dtstamp=DTSTAMP)

    assert "STATUS:COMPLETED" in metin and "COMPLETED:20260929T123000Z" in metin
    assert "PERCENT-COMPLETE:100" in metin


def test_saat_planli_gorev_blok_saatini_ve_blok_uid_ini_yazar(repo, kisisel):
    g = repo.add_task(_gorev(uid="g1@t"))
    g = repo.plan_task_slot(g.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15, 30), kisisel.id, IST)
    blok = repo.get_event(g.event_id)

    metin = export_repo(repo, dtstamp=DTSTAMP)

    assert "DTSTART;TZID=Europe/Istanbul:20261001T140000" in metin
    assert "DUE;TZID=Europe/Istanbul:20261001T153000" in metin
    assert f"X-TAKVIM-BLOK-UID:{blok.uid}" in metin
    assert "BEGIN:VEVENT" in metin, "blok kendi VEVENT'i olarak da yazılır"


def test_surukleyerek_tasinan_blogun_gecerli_saati_yazilir(repo, kisisel):
    """Sürükleme override yazıyor; VTODO etkinlik satırındaki ESKİ saati yazmamalı."""
    g = repo.add_task(_gorev(uid="g1@t"))
    g = repo.plan_task_slot(g.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15), kisisel.id, IST)
    repo.move_occurrence(g.event_id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 16), ist(2026, 10, 1, 17))

    metin = export_repo(repo, dtstamp=DTSTAMP)

    assert "DTSTART;TZID=Europe/Istanbul:20261001T160000" in metin
    assert "DUE;TZID=Europe/Istanbul:20261001T170000" in metin


def test_takvim_suzgeciyle_disa_aktarmada_gorev_yok(repo, kisisel):
    """Görev takvime ait değil: yalnızca tam dışa aktarma (yedek) onları taşır."""
    repo.add_task(_gorev())

    assert "VTODO" not in export_repo(repo, calendar_ids=[kisisel.id], dtstamp=DTSTAMP)
    assert "VTODO" in export_repo(repo, dtstamp=DTSTAMP)


# ---------------------------------------------------------------------------
# Gidiş-dönüş
# ---------------------------------------------------------------------------

def _hepsini_kur(repo, kisisel):
    plansiz = repo.add_task(_gorev(uid="plansiz@t", title="Plansız iş", notes="not"))
    gun = repo.add_task(_gorev(uid="gun@t", title="Gün işi", plan_day=date(2026, 10, 3)))
    saat = repo.add_task(_gorev(uid="saat@t", title="Saatli iş"))
    saat = repo.plan_task_slot(saat.id, ist(2026, 10, 1, 14), ist(2026, 10, 1, 15, 30), kisisel.id, IST)
    bitmis = repo.add_task(_gorev(uid="bitti@t", title="Bitmiş iş"))
    repo.set_task_done(bitmis.id, True, at=datetime(2026, 9, 29, 12, 30, tzinfo=UTC))
    return plansiz, gun, saat, bitmis


def test_gidis_donus_gorevler_ayni_geri_gelir(repo, kisisel):
    _hepsini_kur(repo, kisisel)
    metin = export_repo(repo, dtstamp=DTSTAMP)

    # KASTEN farklı bir default_tzid: gün planlı görevin tarihi dilim kaymasın.
    yeni, rapor = _yeni_repo_ile_aktar(metin, default_tzid=NY)

    assert (rapor.tasks_added, rapor.errors) == (4, ())
    g = {t.uid: t for t in yeni.list_tasks()}
    assert (g["plansiz@t"].title, g["plansiz@t"].notes, g["plansiz@t"].plan) == ("Plansız iş", "not", "yok")
    assert (g["gun@t"].plan, g["gun@t"].plan_day) == ("gun", date(2026, 10, 3))
    assert g["bitti@t"].done_at == datetime(2026, 9, 29, 12, 30, tzinfo=UTC)


def test_gidis_donus_saat_planli_gorev_ikinci_blok_acmaz(repo, kisisel):
    """VTODO bloğun VEVENT'ine bağlanmalı: yoksa ızgarada aynı iş iki kez görünürdü."""
    _hepsini_kur(repo, kisisel)
    metin = export_repo(repo, dtstamp=DTSTAMP)

    yeni, _ = _yeni_repo_ile_aktar(metin)

    g = yeni.get_task_by_uid("saat@t")
    assert g.plan == "saat" and g.plan_day is None
    assert len(yeni.list_events()) == 1
    assert yeni.task_slots([g.event_id])[g.event_id] == (ist(2026, 10, 1, 14), ist(2026, 10, 1, 15, 30))


def test_ayni_dosya_ikinci_kez_gorev_kopyalamaz(repo, kisisel):
    _hepsini_kur(repo, kisisel)
    metin = export_repo(repo, dtstamp=DTSTAMP)
    yeni, ilk = _yeni_repo_ile_aktar(metin)

    ikinci = import_ics(yeni, metin, calendar_id=yeni.list_calendars()[0].id, default_tzid=IST)

    assert (ilk.tasks_added, ikinci.tasks_added, ikinci.tasks_skipped) == (4, 0, 4)
    assert len(yeni.list_tasks()) == 4


def test_var_olan_gorev_ezilmez(repo, kisisel):
    """Görevlerde SEQUENCE yok: aynı UID'li dosya elle yapılmış düzenlemeyi silmemeli."""
    repo.add_task(_gorev(uid="g1@t", title="Dosyadaki ad"))
    metin = export_repo(repo, dtstamp=DTSTAMP)
    yeni, _ = _yeni_repo_ile_aktar(metin)
    g = yeni.get_task_by_uid("g1@t")
    yeni.update_task(_gorev(id=g.id, uid="g1@t", title="Elle değiştirdim"))

    import_ics(yeni, metin, calendar_id=yeni.list_calendars()[0].id, default_tzid=IST)

    assert yeni.get_task_by_uid("g1@t").title == "Elle değiştirdim"


def test_dry_run_gorevi_yazmaz_ama_sayar(repo, kisisel):
    _hepsini_kur(repo, kisisel)
    metin = export_repo(repo, dtstamp=DTSTAMP)

    yeni, rapor = _yeni_repo_ile_aktar(metin, dry_run=True)

    assert rapor.tasks_added == 4
    assert yeni.list_tasks() == [] and yeni.list_events() == []


# ---------------------------------------------------------------------------
# Yabancı VTODO'lar
# ---------------------------------------------------------------------------

def test_fixture_vtodo_gorev_olarak_alinir_etkinlik_sayisi_degismez():
    """Eski sözleşme: parse_ics VTODO'yu hâlâ atlıyor; import_ics ise görev olarak yazıyor."""
    from tests.test_ics_import import FIXTURES

    yeni, rapor = _yeni_repo_ile_aktar((FIXTURES / "vtodo.ics").read_text(encoding="utf-8"))

    assert (rapor.added, rapor.tasks_added, rapor.errors) == (1, 1, ())
    (g,) = yeni.list_tasks()
    assert (g.uid, g.title) == ("gorev-1", "Yapılacak iş")
    assert len(parse_ics(FIXTURES / "vtodo.ics", default_tzid=IST)[0]) == 1


def test_due_utc_yerel_gune_cevrilir():
    """23:00Z İstanbul'da ertesi gün 02:00: tarih kısmını olduğu gibi almak görevi bir gün erkene kaydırırdı."""
    metin = _ics(_vtodo("UID:g1", "SUMMARY:Gece işi", "DUE:20261001T230000Z"))

    (pg,), _ = parse_ics_tasks(metin, default_tzid=IST)

    assert pg.task.plan_day == date(2026, 10, 2)


def test_due_tarih_degeri_oldugu_gibi_alinir():
    metin = _ics(_vtodo("UID:g1", "SUMMARY:x", "DUE;VALUE=DATE:20261001"))

    (pg,), _ = parse_ics_tasks(metin, default_tzid=NY)

    assert pg.task.plan_day == date(2026, 10, 1)


def test_due_yoksa_dtstart_kullanilir_ikisi_de_yoksa_plansiz():
    a = parse_ics_tasks(_ics(_vtodo("UID:a", "SUMMARY:a", "DTSTART;VALUE=DATE:20261005")), default_tzid=IST)[0][0]
    b = parse_ics_tasks(_ics(_vtodo("UID:b", "SUMMARY:b")), default_tzid=IST)[0][0]

    assert a.task.plan_day == date(2026, 10, 5) and b.task.plan_day is None


@pytest.mark.parametrize(
    "satirlar",
    [
        ("STATUS:COMPLETED",),
        ("COMPLETED:20260929T123000Z",),
        ("PERCENT-COMPLETE:100",),
    ],
)
def test_uc_tamamlanma_isaretinden_biri_yeter(satirlar):
    """Üreticiler birini yazıp ötekini unutabiliyor."""
    metin = _ics(_vtodo("UID:g1", "SUMMARY:x", *satirlar))

    (pg,), _ = parse_ics_tasks(metin, default_tzid=IST)

    assert pg.task.done


def test_tamamlanma_zamani_completed_dan_gelir():
    metin = _ics(_vtodo("UID:g1", "SUMMARY:x", "STATUS:COMPLETED", "COMPLETED:20260929T123000Z"))

    (pg,), _ = parse_ics_tasks(metin, default_tzid=IST)

    assert pg.task.done_at == datetime(2026, 9, 29, 12, 30, tzinfo=UTC)


def test_devam_eden_gorev_acik_sayilir():
    metin = _ics(_vtodo("UID:g1", "SUMMARY:x", "STATUS:IN-PROCESS", "PERCENT-COMPLETE:40"))

    (pg,), _ = parse_ics_tasks(metin, default_tzid=IST)

    assert not pg.task.done


def test_iptal_edilen_vtodo_atlanir():
    metin = _ics(_vtodo("UID:g1", "SUMMARY:x", "STATUS:CANCELLED"))

    parsed, rapor = parse_ics_tasks(metin, default_tzid=IST)

    assert parsed == [] and rapor.skipped == 1


def test_tekrarli_vtodo_tek_seferlik_alinir_uyari_yazar():
    """Görevler tekrarlanamaz: sessizce indirgemek yerine söylenmeli."""
    metin = _ics(_vtodo("UID:g1", "SUMMARY:Spor", "RRULE:FREQ=WEEKLY", "DUE;VALUE=DATE:20261006"))

    (pg,), rapor = parse_ics_tasks(metin, default_tzid=IST)

    assert pg.task.plan_day == date(2026, 10, 6)
    assert any("tekrarlı görev" in u for u in rapor.warnings)


def test_uidsiz_vtodo_hata_olarak_raporlanir_digerleri_surer():
    metin = _ics(_vtodo("SUMMARY:uidsiz"), _vtodo("UID:g2", "SUMMARY:tamam"))

    parsed, rapor = parse_ics_tasks(metin, default_tzid=IST)

    assert [p.task.uid for p in parsed] == ["g2"]
    assert rapor.errors == (("(uid-yok)", "UID yok, VTODO atlandı"),)


def test_ozetsiz_vtodo_basliksiz_yer_tutucu_alir():
    (pg,), _ = parse_ics_tasks(_ics(_vtodo("UID:g1")), default_tzid=IST)

    assert pg.task.title == "(Başlıksız)"


def test_ayni_uid_iki_vtodo_ilki_alinir():
    metin = _ics(_vtodo("UID:g1", "SUMMARY:ilk"), _vtodo("UID:g1", "SUMMARY:ikinci"))

    parsed, rapor = parse_ics_tasks(metin, default_tzid=IST)

    assert [p.task.title for p in parsed] == ["ilk"]
    assert any("birden çok VTODO" in u for u in rapor.warnings)


def test_okunamayan_kaynak_gorev_raporunu_bos_birakir():
    """Okunamama hatasını `parse_ics` raporluyor; ikisi birden bildirmesin."""
    parsed, rapor = parse_ics_tasks("bu bir takvim değil", default_tzid=IST)

    assert parsed == [] and rapor.errors == ()


# ---------------------------------------------------------------------------
# Blok bağlama uç durumları
# ---------------------------------------------------------------------------

def _blok_ve_gorev(blok_ekstra=(), gorev_blok_uid="blok@t"):
    vevent = "\r\n".join([
        "BEGIN:VEVENT", "UID:blok@t", "DTSTART;TZID=Europe/Istanbul:20261001T140000",
        "DTEND;TZID=Europe/Istanbul:20261001T153000", "SUMMARY:Blok", *blok_ekstra, "END:VEVENT",
    ])
    todo = _vtodo("UID:g1", "SUMMARY:Blok", "DUE;VALUE=DATE:20261001",
                  f"X-TAKVIM-BLOK-UID:{gorev_blok_uid}")
    return _ics(vevent, todo)


def test_blok_bulunursa_gorev_ona_baglanir():
    yeni, _ = _yeni_repo_ile_aktar(_blok_ve_gorev())

    g = yeni.get_task_by_uid("g1")

    assert g.plan == "saat" and g.event_id == yeni.get_event_by_uid("blok@t").id


def test_blok_yoksa_gorev_gun_planina_duser():
    """Bağ kopuyor ama veri kaybolmuyor: DUE'daki gün korunur."""
    yeni, rapor = _yeni_repo_ile_aktar(_blok_ve_gorev(gorev_blok_uid="baska@t"))

    g = yeni.get_task_by_uid("g1")

    assert (g.plan, g.plan_day, rapor.errors) == ("gun", date(2026, 10, 1), ())


def test_tekrarli_bloga_baglanmaz():
    yeni, _ = _yeni_repo_ile_aktar(_blok_ve_gorev(blok_ekstra=("RRULE:FREQ=DAILY",)))

    g = yeni.get_task_by_uid("g1")

    assert (g.plan, g.plan_day) == ("gun", date(2026, 10, 1))


def test_baska_gorevin_blogu_ikinci_goreve_baglanmaz():
    """Bir bloğa tek görev (UNIQUE): ikinci VTODO gün planına düşmeli, içe aktarma patlamamalı."""
    vevent = "\r\n".join(["BEGIN:VEVENT", "UID:blok@t", "DTSTART;TZID=Europe/Istanbul:20261001T140000",
                          "DTEND;TZID=Europe/Istanbul:20261001T153000", "SUMMARY:Blok", "END:VEVENT"])
    a = _vtodo("UID:g1", "SUMMARY:a", "DUE;VALUE=DATE:20261001", "X-TAKVIM-BLOK-UID:blok@t")
    b = _vtodo("UID:g2", "SUMMARY:b", "DUE;VALUE=DATE:20261001", "X-TAKVIM-BLOK-UID:blok@t")

    yeni, rapor = _yeni_repo_ile_aktar(_ics(vevent, a, b))

    assert (yeni.get_task_by_uid("g1").plan, yeni.get_task_by_uid("g2").plan) == ("saat", "gun")
    assert rapor.errors == ()


def test_etkinlik_sayilari_gorevlerden_etkilenmez():
    """Önizleme 'N yeni etkinlik' derken görevleri saymamalı: alanlar ayrı."""
    _, rapor = _yeni_repo_ile_aktar(_blok_ve_gorev())

    assert (rapor.added, rapor.tasks_added) == (1, 1)


def test_uzun_etkinlik_ve_gorev_ayni_dosyada_kayit_sirasi_onemli_degil():
    """VTODO dosyada VEVENT'ten ÖNCE olsa da bağlanmalı (etkinlikler önce kaydediliyor)."""
    vevent = "\r\n".join(["BEGIN:VEVENT", "UID:blok@t", "DTSTART;TZID=Europe/Istanbul:20261001T140000",
                          "DTEND;TZID=Europe/Istanbul:20261001T153000", "SUMMARY:Blok", "END:VEVENT"])
    todo = _vtodo("UID:g1", "SUMMARY:Blok", "X-TAKVIM-BLOK-UID:blok@t")

    yeni, _ = _yeni_repo_ile_aktar(_ics(todo, vevent))

    assert yeni.get_task_by_uid("g1").plan == "saat"

