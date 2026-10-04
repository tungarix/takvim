"""Hatırlatıcı mantığı, kalıcılığı ve arka plan turu.

Saat asla gerçek zamandan okunmuyor: `now` her testte parametre. Bir
hatırlatıcı testinin "bazen geçen" hâli, hatırlatıcının kendisinden beterdir.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

from core import (
    UTC,
    Event,
    Occurrence,
    Reminder,
    due_reminders,
    fire_key,
    next_fire_time,
)
from remind import daemon
from remind.daemon import _dil_coz, _temizlik, _temizlik_vakti_mi, run_forever, run_once
from remind.notifier import ConsoleNotifier, TkNotifier, pick_notifier
from store import Repo, new_uid
from tests.helpers import IST, ist


class YakalayanNotifier:
    """Gönderilenleri biriktiren sahte bildirim arka ucu."""

    def __init__(self) -> None:
        self.gonderilen: list[tuple[str, str]] = []

    def available(self) -> bool:
        return True

    def notify(self, title: str, body: str) -> bool:
        self.gonderilen.append((title, body))
        return True


@pytest.fixture
def repo():
    """Bellekte taze DB."""
    with Repo.open(":memory:") as r:
        yield r


@pytest.fixture
def ders(repo):
    """Görünür varsayılan takvim."""
    return repo.add_calendar("Ders", "#e0524a")


def _ekle(repo, takvim, baslik, start, end, *, rrule=None, all_day=False, location=None):
    """Kısa Event kurucusu."""
    return repo.add_event(
        Event(
            id=None, uid=new_uid(), calendar_id=takvim.id, title=baslik,
            start_utc=start, end_utc=end, tzid=IST, rrule=rrule, all_day=all_day,
            location=location,
        )
    )


def _occ(start, end, *, event_id=1, title="Ders", all_day=False):
    """Doğrudan Occurrence kurucusu (saf mantık testleri için)."""
    return Occurrence(
        event_id=event_id, uid=f"u{event_id}", title=title,
        start_utc=start, end_utc=end, all_day=all_day, tzid=IST, calendar_id=1,
    )


# ---------------------------------------------------------------------------
# Saf mantık
# ---------------------------------------------------------------------------

def test_vadesi_gelen_tetiklenir():
    """fire_at geçmişse ve etkinlik bitmemişse tetiklenir."""
    occ = _occ(ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0))
    reminders = {1: [Reminder(id=7, event_id=1, minutes_before=15)]}

    # 09:44 -> henüz değil, 09:45 -> tam vaktinde
    assert due_reminders([occ], reminders, ist(2026, 9, 14, 9, 44)) == []
    bulunan = due_reminders([occ], reminders, ist(2026, 9, 14, 9, 45))

    assert len(bulunan) == 1
    assert bulunan[0].reminder_id == 7
    assert bulunan[0].minutes_before == 15
    assert bulunan[0].fire_at_utc == ist(2026, 9, 14, 9, 45)


def test_bitmis_etkinlik_tetiklenmez():
    """Uygulama bir hafta kapalı kalıp açılınca geçmiş bildirim yağmuru olmamalı.

    Ölçüt "ne kadar geciktik" değil, "etkinlik hâlâ güncel mi". Böylece hem
    geçen haftanın toplantıları susuyor hem de 5 dakika sonra başlayacak bir
    toplantı, uygulama az önce açılmış olsa bile bildiriliyor.
    """
    gecmis = _occ(ist(2026, 9, 7, 10, 0), ist(2026, 9, 7, 11, 0))
    reminders = {1: [Reminder(id=1, event_id=1, minutes_before=15)]}

    assert due_reminders([gecmis], reminders, ist(2026, 9, 14, 12, 0)) == []


def test_devam_eden_etkinlik_hala_tetiklenir():
    """Başlamış ama bitmemiş etkinlik bildirilir (uygulama yeni açıldıysa)."""
    occ = _occ(ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0))
    reminders = {1: [Reminder(id=1, event_id=1, minutes_before=15)]}

    bulunan = due_reminders([occ], reminders, ist(2026, 9, 14, 10, 30))
    assert len(bulunan) == 1


def test_daha_once_tetiklenen_tekrarlanmaz():
    """already_fired içindeki çift atlanır."""
    occ = _occ(ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0))
    reminders = {1: [Reminder(id=1, event_id=1, minutes_before=15)]}
    simdi = ist(2026, 9, 14, 9, 50)

    assert len(due_reminders([occ], reminders, simdi)) == 1
    assert due_reminders(
        [occ], reminders, simdi, already_fired={fire_key(1, occ)}
    ) == []


def test_ayni_seride_birden_cok_hatirlatici():
    """Bir etkinliğe hem 1 gün hem 15 dakika önce konabilir."""
    occ = _occ(ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0))
    reminders = {
        1: [
            Reminder(id=1, event_id=1, minutes_before=1440),
            Reminder(id=2, event_id=1, minutes_before=15),
        ]
    }
    bulunan = due_reminders([occ], reminders, ist(2026, 9, 14, 9, 50))

    assert [d.minutes_before for d in bulunan] == [1440, 15], "erken olan önce"


def test_serinin_her_ornegi_ayri_tetiklenir():
    """Aynı hatırlatıcı, serinin her örneği için ayrı anahtar üretir."""
    a = _occ(ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0))
    b = _occ(ist(2026, 9, 15, 10, 0), ist(2026, 9, 15, 11, 0))

    assert fire_key(1, a) != fire_key(1, b)


def test_negatif_hatirlatici_reddedilir():
    """'Başladıktan sonra hatırlat' diye bir şey yok."""
    with pytest.raises(ValueError):
        Reminder(id=None, event_id=1, minutes_before=-5)


def test_next_fire_time_en_yakini_verir():
    """Arka plan süreci uyku süresini buna göre kısaltıyor."""
    occ = _occ(ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0))
    reminders = {
        1: [
            Reminder(id=1, event_id=1, minutes_before=60),
            Reminder(id=2, event_id=1, minutes_before=15),
        ]
    }
    assert next_fire_time([occ], reminders, ist(2026, 9, 14, 8, 0)) == ist(2026, 9, 14, 9, 0)
    assert next_fire_time([occ], reminders, ist(2026, 9, 14, 9, 30)) == ist(2026, 9, 14, 9, 45)
    assert next_fire_time([occ], reminders, ist(2026, 9, 14, 10, 0)) is None


# ---------------------------------------------------------------------------
# Kalıcılık
# ---------------------------------------------------------------------------

def test_hatirlatici_crud(repo, ders):
    """Ekle, listele, sil."""
    event = _ekle(repo, ders, "Ders", ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0))
    r15 = repo.add_reminder(event.id, 15)
    repo.add_reminder(event.id, 60)

    assert [r.minutes_before for r in repo.list_reminders(event.id)] == [60, 15]

    repo.delete_reminder(r15.id)
    assert [r.minutes_before for r in repo.list_reminders(event.id)] == [60]


def test_ayni_hatirlatici_iki_kez_eklenmez(repo, ders):
    """Aynı dakika değeri tekrar eklenirse mevcut kayıt döner."""
    event = _ekle(repo, ders, "Ders", ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0))
    ilk = repo.add_reminder(event.id, 15)
    ikinci = repo.add_reminder(event.id, 15)

    assert ilk.id == ikinci.id
    assert len(repo.list_reminders(event.id)) == 1


def test_etkinlik_silinince_hatirlaticilari_da_silinir(repo, ders):
    """CASCADE."""
    event = _ekle(repo, ders, "Ders", ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0))
    repo.add_reminder(event.id, 15)

    repo.delete_event(event.id)
    assert repo.all_reminders() == {}


def test_mark_fired_ikinci_kez_false(repo, ders):
    """Mükerrer bildirim veritabanı düzeyinde imkânsız."""
    event = _ekle(repo, ders, "Ders", ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0))
    r = repo.add_reminder(event.id, 15)

    assert repo.mark_fired(r.id, ist(2026, 9, 14, 10, 0)) is True
    assert repo.mark_fired(r.id, ist(2026, 9, 14, 10, 0)) is False
    assert fire_key(r.id, _occ(ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0))) in repo.fired_keys()


def test_prune_fired(repo, ders):
    """Eski tetiklenme kayıtları temizlenebiliyor."""
    event = _ekle(repo, ders, "Ders", ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0))
    r = repo.add_reminder(event.id, 15)
    repo.mark_fired(r.id, ist(2026, 9, 1, 10, 0))
    repo.mark_fired(r.id, ist(2026, 9, 20, 10, 0))

    assert repo.prune_fired(ist(2026, 9, 10)) == 1
    assert len(repo.fired_keys()) == 1


# ---------------------------------------------------------------------------
# Tetiklenme kayıtlarının budanması
# ---------------------------------------------------------------------------

def test_prune_fired_eski_kisa_ornegin_kaydi_silinir_yenisi_durur(repo, ders):
    """30 günden eski kısa örneklerin kaydı gider; yeni olanlar kalır."""
    event = _ekle(
        repo, ders, "Ders", ist(2026, 8, 1, 10, 0), ist(2026, 8, 1, 11, 0),
        rrule="FREQ=DAILY",
    )
    r = repo.add_reminder(event.id, 15)
    for gun in (ist(2026, 8, 1, 10), ist(2026, 8, 15, 10),
                ist(2026, 9, 10, 10), ist(2026, 9, 30, 10)):
        repo.mark_fired(r.id, gun)
    simdi = ist(2026, 10, 4, 12)

    assert repo.prune_fired(simdi - timedelta(days=30)) == 2
    assert repo.fired_keys() == {
        (r.id, ist(2026, 9, 10, 10)),
        (r.id, ist(2026, 9, 30, 10)),
    }


def test_prune_fired_bitisi_sinirdan_sonra_olan_ornek_durur(repo, ders):
    """Başlangıcı eski ama bitişi sınırı aşan örneğin kaydı silinmez.

    İki günlük etkinlik, sınır 4 Eylül 00:00: 23:30-00:30 örneği gece
    yarısını aşıyor (hâlâ güncel), 22:30-23:30 örneği ondan önce bitiyor.
    Yalnızca başlangıca bakan eski ölçüt ikisini de silerdi.
    """
    gece = _ekle(
        repo, ders, "Gece", ist(2026, 8, 1, 23, 30), ist(2026, 8, 2, 0, 30),
        rrule="FREQ=DAILY",
    )
    erken = _ekle(
        repo, ders, "Erken", ist(2026, 8, 1, 22, 30), ist(2026, 8, 1, 23, 30),
        rrule="FREQ=DAILY",
    )
    r_gece = repo.add_reminder(gece.id, 15)
    r_erken = repo.add_reminder(erken.id, 15)
    repo.mark_fired(r_gece.id, ist(2026, 9, 3, 23, 30))
    repo.mark_fired(r_erken.id, ist(2026, 9, 3, 22, 30))

    assert repo.prune_fired(ist(2026, 9, 4, 0, 0)) == 1
    assert repo.fired_keys() == {(r_gece.id, ist(2026, 9, 3, 23, 30))}


def test_prune_fired_suren_uzun_etkinligin_kaydi_silinmez(repo, ders):
    """90 günlük etkinliğin 40 gün önce başlamış, hâlâ süren örneği korunur.

    Yalnızca başlangıca bakan ölçüt bu kaydı silerdi; kayıt gidince örnek
    "tetiklenmemiş" görünüp yeniden bildirilirdi.
    """
    simdi = ist(2026, 10, 4, 12)
    baslangic = simdi - timedelta(days=40)
    event = _ekle(repo, ders, "Staj", baslangic, baslangic + timedelta(days=90))
    r = repo.add_reminder(event.id, 15)
    repo.mark_fired(r.id, baslangic)

    assert repo.prune_fired(simdi - timedelta(days=30)) == 0
    assert (r.id, baslangic) in repo.fired_keys()


def test_prune_fired_silinen_sayiyi_dondurur(repo, ders):
    """Dönüş değeri silinen kayıt sayısı; silinecek yoksa 0."""
    event = _ekle(
        repo, ders, "Ders", ist(2026, 8, 1, 10, 0), ist(2026, 8, 1, 11, 0),
        rrule="FREQ=DAILY",
    )
    r = repo.add_reminder(event.id, 15)
    for gun in (1, 2, 3):
        repo.mark_fired(r.id, ist(2026, 8, gun, 10))
    repo.mark_fired(r.id, ist(2026, 9, 30, 10))
    sinir = ist(2026, 9, 4)

    assert repo.prune_fired(sinir) == 3
    assert repo.prune_fired(sinir) == 0
    assert len(repo.fired_keys()) == 1


def test_budama_surerken_gunluk_tekrar_bildirimi_uretmez(repo, ders):
    """Uzun etkinlikte budama + yeni tur, aynı bildirimi yeniden göstermez.

    Gerçek senaryo: kayıt silinirse bir sonraki tur örneği "tetiklenmemiş"
    görür, bildirir ve kaydı yeniden yazar; ertesi günkü budama onu yine
    siler -- her gün tekrarlayan bildirim.
    """
    baslangic = ist(2026, 8, 25, 10, 0)
    event = _ekle(repo, ders, "Staj", baslangic, baslangic + timedelta(days=90))
    repo.add_reminder(event.id, 15)
    notifier = YakalayanNotifier()

    assert len(run_once(repo, IST, notifier, now=baslangic - timedelta(minutes=10))) == 1

    simdi = baslangic + timedelta(days=40)
    _temizlik(repo, simdi)

    assert run_once(repo, IST, notifier, now=simdi) == []
    assert len(notifier.gonderilen) == 1


class _PatlayanRepo:
    """Budaması her seferinde hata veren sahte depo (kilitli veritabanı)."""

    def prune_fired(self, before):
        raise sqlite3.OperationalError("database is locked")


def test_temizlik_hatayi_yutar_ve_sifir_dondurur(capsys):
    """Budama bir bakım işi: başarısız olması döngüyü öldürmemeli."""
    assert _temizlik(_PatlayanRepo(), ist(2026, 10, 4)) == 0
    assert "budanamadı" in capsys.readouterr().out


def test_temizlik_otuz_gun_oncesini_sinir_alir_ve_sayiyi_dondurur():
    """`_temizlik`, `prune_fired`'a `simdi - 30 gün`ü verir, sonucu iletir."""
    cagrilar = []

    class _Repo:
        def prune_fired(self, before):
            cagrilar.append(before)
            return 7

    simdi = ist(2026, 10, 4, 12)

    assert _temizlik(_Repo(), simdi) == 7
    assert cagrilar == [simdi - timedelta(days=30)]


def test_temizlik_vakti_mi_ilk_seferde_ve_gunde_bir():
    """Hiç yapılmadıysa hemen; sonra yalnızca 24 saat dolunca."""
    gun = 24 * 3600

    assert _temizlik_vakti_mi(None, 0.0) is True
    assert _temizlik_vakti_mi(100.0, 100.0 + gun - 1) is False
    assert _temizlik_vakti_mi(100.0, 100.0 + gun) is True


class _SahteZaman:
    """`remind.daemon.time` yerine geçer: gerçekten uyumaz, sahte saati ilerletir.

    `sleep` her çağrıda `adim` saniye ilerletir ve `tur` kadar uyuduktan sonra
    `KeyboardInterrupt` fırlatır; `run_forever`in beklediği tek çıkış bu.
    `uykuda(n)` n'inci uykudan hemen önce çağrılır (turlar arası olay
    yaratmak için).
    """

    def __init__(self, adim: float, tur: int, uykuda=None) -> None:
        self.simdi = 1_000.0
        self.adim = adim
        self.tur = tur
        self.uykuda = uykuda
        self.uyku_sayisi = 0

    def monotonic(self) -> float:
        return self.simdi

    def sleep(self, saniye: float) -> None:
        self.uyku_sayisi += 1
        if self.uykuda is not None:
            self.uykuda(self.uyku_sayisi)
        if self.uyku_sayisi >= self.tur:
            raise KeyboardInterrupt
        self.simdi += self.adim


def test_run_forever_ilk_turda_ve_gunde_bir_budar(repo, monkeypatch):
    """12 saatlik 3 turda iki budama: ilk tur ve 24. saat; 12. saatte yok."""
    cagrilar = []
    repo.prune_fired = lambda before: cagrilar.append(before) or 0
    monkeypatch.setattr(daemon, "time", _SahteZaman(adim=12 * 3600, tur=3))

    run_forever(repo, IST, YakalayanNotifier())

    assert len(cagrilar) == 2
    simdi = datetime.now(UTC)
    assert all(abs((simdi - timedelta(days=30)) - c) < timedelta(minutes=5) for c in cagrilar)


def test_run_forever_budama_patlarsa_dongu_surer_ve_her_turda_denenmez(repo, monkeypatch):
    """Budama hatası döngüyü öldürmez ve dakikada bir aynı hata basılmaz."""
    cagrilar = []

    def patlayan(before):
        cagrilar.append(before)
        raise sqlite3.OperationalError("database is locked")

    repo.prune_fired = patlayan
    sahte = _SahteZaman(adim=60, tur=3)
    monkeypatch.setattr(daemon, "time", sahte)

    run_forever(repo, IST, YakalayanNotifier())

    assert sahte.uyku_sayisi == 3, "üç tur da dönmeli"
    assert len(cagrilar) == 1, "başarısız budama bir sonraki 24 saate kadar tekrarlanmaz"


# ---------------------------------------------------------------------------
# Arka plan turu
# ---------------------------------------------------------------------------

def test_run_once_bildirir_ve_isaretler(repo, ders):
    """Bir tur: bildirim gönderilir ve tekrar gönderilmez."""
    event = _ekle(
        repo, ders, "Algoritma", ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0),
        location="A101",
    )
    repo.add_reminder(event.id, 15)
    notifier = YakalayanNotifier()

    gonderilen = run_once(repo, IST, notifier, now=ist(2026, 9, 14, 9, 50))
    assert len(gonderilen) == 1
    assert len(notifier.gonderilen) == 1
    baslik, govde = notifier.gonderilen[0]
    assert baslik == "Algoritma"
    assert "10:00" in govde and "A101" in govde

    # İkinci tur sessiz
    assert run_once(repo, IST, notifier, now=ist(2026, 9, 14, 9, 51)) == []
    assert len(notifier.gonderilen) == 1


def test_run_once_tekrarli_seride_her_ornegi_ayri_bildirir(repo, ders):
    """Günlük ders, her gün ayrı bildirilir."""
    event = _ekle(
        repo, ders, "Koşu", ist(2026, 9, 14, 7, 0), ist(2026, 9, 14, 8, 0),
        rrule="FREQ=DAILY",
    )
    repo.add_reminder(event.id, 10)
    notifier = YakalayanNotifier()

    run_once(repo, IST, notifier, now=ist(2026, 9, 14, 6, 50))
    run_once(repo, IST, notifier, now=ist(2026, 9, 15, 6, 50))

    assert len(notifier.gonderilen) == 2


def test_run_once_gizli_takvimi_susturur(repo):
    """Takvimi gizlemek gürültüsünü de susturur."""
    gizli = repo.add_calendar("Arşiv", "#666", visible=False)
    event = _ekle(repo, gizli, "Eski", ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0))
    repo.add_reminder(event.id, 15)
    notifier = YakalayanNotifier()

    assert run_once(repo, IST, notifier, now=ist(2026, 9, 14, 9, 50)) == []
    assert notifier.gonderilen == []


def test_run_once_hatirlatici_yoksa_sorgu_yapmaz(repo, ders):
    """Hiç hatırlatıcı yoksa tur erken çıkar."""
    _ekle(repo, ders, "Ders", ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0))
    assert run_once(repo, IST, YakalayanNotifier(), now=ist(2026, 9, 14, 9, 50)) == []


def test_run_once_iptal_edilen_ornek_bildirilmez(repo, ders):
    """Bu haftalık iptal edilen ders hatırlatılmaz."""
    event = _ekle(
        repo, ders, "Ders", ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0),
        rrule="FREQ=DAILY",
    )
    repo.add_reminder(event.id, 15)
    repo.cancel_occurrence(event.id, ist(2026, 9, 14, 10, 0))
    notifier = YakalayanNotifier()

    assert run_once(repo, IST, notifier, now=ist(2026, 9, 14, 9, 50)) == []


def test_run_once_kaydirilan_ornegi_yeni_saatinde_bildirir(repo, ders):
    """Örnek taşındıysa hatırlatıcı da yeni saate göre çalışır."""
    event = _ekle(
        repo, ders, "Ders", ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0),
        rrule="FREQ=DAILY",
    )
    repo.add_reminder(event.id, 15)
    repo.move_occurrence(event.id, ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 16, 0))
    notifier = YakalayanNotifier()

    assert run_once(repo, IST, notifier, now=ist(2026, 9, 14, 9, 50)) == []
    gonderilen = run_once(repo, IST, notifier, now=ist(2026, 9, 14, 15, 50))
    assert len(gonderilen) == 1
    assert "16:00" in notifier.gonderilen[0][1]


def test_uygulama_uzun_kapali_kaldiktan_sonra_sel_yok(repo, ders):
    """Bir hafta kapalı kalıp açılınca yalnızca güncel olan bildirilir."""
    event = _ekle(
        repo, ders, "Koşu", ist(2026, 9, 7, 7, 0), ist(2026, 9, 7, 8, 0),
        rrule="FREQ=DAILY",
    )
    repo.add_reminder(event.id, 10)
    notifier = YakalayanNotifier()

    # 14 Eylül 06:55: yalnızca o günkü örnek güncel
    gonderilen = run_once(repo, IST, notifier, now=ist(2026, 9, 14, 6, 55))

    assert len(gonderilen) == 1
    assert len(notifier.gonderilen) == 1


# ---------------------------------------------------------------------------
# Bildirim metni
# ---------------------------------------------------------------------------

def test_bildirim_metni_saatli(repo, ders):
    """Saatli etkinlikte aralık ve kalan süre yazılır."""
    event = _ekle(
        repo, ders, "Ders", ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 30),
        location="B204",
    )
    repo.add_reminder(event.id, 90)
    notifier = YakalayanNotifier()
    run_once(repo, IST, notifier, now=ist(2026, 9, 14, 8, 30))

    baslik, govde = notifier.gonderilen[0]
    assert baslik == "Ders"
    assert "10:00 – 11:30" in govde
    assert "1 sa 30 dk içinde" in govde
    assert "B204" in govde


def test_bildirim_metni_tumgun(repo, ders):
    """Tüm gün etkinliğinde saat aralığı yerine tarih yazılır."""
    event = _ekle(repo, ders, "Tatil", ist(2026, 9, 14), ist(2026, 9, 15), all_day=True)
    repo.add_reminder(event.id, 0)
    notifier = YakalayanNotifier()
    run_once(repo, IST, notifier, now=ist(2026, 9, 14, 0, 1))

    _, govde = notifier.gonderilen[0]
    assert "Tüm gün" in govde
    assert "14.09.2026" in govde
    assert "şimdi başlıyor" in govde


# ---------------------------------------------------------------------------
# Bildirim arka uçları
# ---------------------------------------------------------------------------

def test_console_notifier_her_yerde_calisir(capsys):
    """Son çare arka ucu her ortamda kullanılabilir."""
    n = ConsoleNotifier()
    assert n.available() is True
    assert n.notify("Başlık", "Gövde") is True
    assert "Başlık" in capsys.readouterr().out


def test_pick_notifier_secim(capsys):
    """Açık tercih edilebiliyor, bilinmeyen ad reddediliyor."""
    assert isinstance(pick_notifier("console"), ConsoleNotifier)
    with pytest.raises(ValueError):
        pick_notifier("sihirli")


def test_ps_kacirma_enjeksiyona_kapali():
    """Tek tırnak ve XML karakterleri PowerShell script'ini bozamaz."""
    from remind.notifier import _ps_kacir

    assert _ps_kacir("O'Brien") == "O''Brien"
    assert _ps_kacir("<b>&</b>") == "&lt;b&gt;&amp;&lt;/b&gt;"
    # Sıra doğru: & önce kaçırılıp sonra tekrar kaçırılmamalı
    assert "&amp;amp;" not in _ps_kacir("a & b")


def test_bayat_anlik_goruntude_de_mukerrer_bildirim_yok(repo, ders):
    """İki süreç yarışırsa bile hatırlatıcı yalnızca bir kez gösterilir.

    `due_reminders` zaten `fired_keys()` ile eliyor, ama o anlık görüntü
    BAYAT olabilir: iki `remind` süreci aynı anda çalışıyorsa ikisi de
    "tetiklenmemiş" görüp bildirime geçer. İkinci savunma hattı
    `mark_fired`'ın dönüş değeri -- UNIQUE kısıtı sayesinde yalnızca biri
    True alır.

    Burada bayat anlık görüntüyü `fired_keys`'i boş döndürerek taklit
    ediyoruz; tek koruma `mark_fired` kalıyor.
    """
    event = _ekle(repo, ders, "Ders", ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0))
    repo.add_reminder(event.id, 15)
    notifier = YakalayanNotifier()

    repo.fired_keys = lambda: set()  # her turda "hiç tetiklenmemiş" de

    run_once(repo, IST, notifier, now=ist(2026, 9, 14, 9, 50))
    run_once(repo, IST, notifier, now=ist(2026, 9, 14, 9, 51))

    assert len(notifier.gonderilen) == 1, "ikinci tur mark_fired ile durdurulmalı"


# ---------------------------------------------------------------------------
# Bildirim dili: metin ya da her turda çözülen çağrılabilir
# ---------------------------------------------------------------------------

def _bir_vadesi_gelen(repo, ders, baslik="Algoritma"):
    """14 Eylül 10:00 etkinliği + 15 dk hatırlatıcı; 09:50'de vadesi gelir."""
    event = _ekle(repo, ders, baslik, ist(2026, 9, 14, 10, 0), ist(2026, 9, 14, 11, 0))
    repo.add_reminder(event.id, 15)
    return event


@pytest.mark.parametrize(
    ("kaynak", "beklenen"),
    [
        ("en", "en"),
        ("tr", "tr"),
        ("de", "tr"),  # tanınmayan değer sessizce Türkçe
        (None, "tr"),
        (lambda: "en", "en"),
        (lambda: "tr", "tr"),
        (lambda: "fr", "tr"),
        (lambda: None, "tr"),
    ],
)
def test_dil_coz_metin_ve_cagrilabilir(kaynak, beklenen):
    """Metin de çağrılabilir de çözülüyor; geçersiz değer Türkçeye düşüyor."""
    assert _dil_coz(kaynak) == beklenen


def test_dil_coz_cagrilabilir_patlarsa_turkce():
    """Ayar okuma hatası bildirimi engellemez: Türkçe varsayılan."""

    def patlayan():
        raise PermissionError("ayarlar.json kilitli")

    assert _dil_coz(patlayan) == "tr"


def test_run_once_dil_metni_hala_calisir(repo, ders):
    """Eski imza: `dil="en"` metni bildirimi İngilizce kurar."""
    _bir_vadesi_gelen(repo, ders)
    notifier = YakalayanNotifier()

    run_once(repo, IST, notifier, now=ist(2026, 9, 14, 9, 50), dil="en")

    assert "in 15 minutes" in notifier.gonderilen[0][1]


def test_run_once_dil_cagrilabilirini_her_turda_yeniden_cozer(repo, ders):
    """Çağrılabilir her turda sorulur: ilk bildirim "tr", sonraki "en"."""
    secili = ["tr"]
    notifier = YakalayanNotifier()

    _bir_vadesi_gelen(repo, ders, "Birinci")
    run_once(repo, IST, notifier, now=ist(2026, 9, 14, 9, 50), dil=lambda: secili[0])
    # Kullanıcı turlar arasında dili değiştiriyor, ikinci bir etkinlik de vadesine geliyor.
    secili[0] = "en"
    _bir_vadesi_gelen(repo, ders, "İkinci")
    run_once(repo, IST, notifier, now=ist(2026, 9, 14, 9, 51), dil=lambda: secili[0])

    assert [b for b, _ in notifier.gonderilen] == ["Birinci", "İkinci"]
    assert "15 dakika içinde" in notifier.gonderilen[0][1]
    assert "in 15 minutes" in notifier.gonderilen[1][1]


def test_run_once_dil_cagrilabilir_patlarsa_turkce_bildirir(repo, ders):
    """Dil okunamasa da bildirim kaybolmaz ve tur patlamaz."""
    _bir_vadesi_gelen(repo, ders)
    notifier = YakalayanNotifier()

    def patlayan():
        raise OSError("disk okunamadı")

    gonderilen = run_once(
        repo, IST, notifier, now=ist(2026, 9, 14, 9, 50), dil=patlayan
    )

    assert len(gonderilen) == 1
    assert "15 dakika içinde" in notifier.gonderilen[0][1]


def test_run_once_bildirim_arka_ucuna_dili_bildirir(repo, ders):
    """`dil_ayarla`sı olan arka uca çözülen dil verilir (Tk düğmesi için)."""

    class _DilliNotifier(YakalayanNotifier):
        def __init__(self) -> None:
            super().__init__()
            self.diller: list[str] = []

        def dil_ayarla(self, dil: str) -> None:
            self.diller.append(dil)

    _bir_vadesi_gelen(repo, ders)
    notifier = _DilliNotifier()

    run_once(repo, IST, notifier, now=ist(2026, 9, 14, 9, 50), dil=lambda: "en")

    assert notifier.diller == ["en"]


def test_tk_notifier_dil_ayarla_ve_run_once_ile_guncellenir(repo, ders):
    """Gerçek `TkNotifier`ın düğme dili tur başında güncellenir.

    Pencere açmamak için `notify` sahte; ölçülen yalnızca `dil` alanı.
    """

    class _PencereAcmayanTk(TkNotifier):
        def notify(self, title: str, body: str) -> bool:
            return True

    tk = _PencereAcmayanTk(dil="tr")
    tk.dil_ayarla("en")
    assert tk.dil == "en"

    _bir_vadesi_gelen(repo, ders)
    tk2 = _PencereAcmayanTk(dil="tr")
    run_once(repo, IST, tk2, now=ist(2026, 9, 14, 9, 50), dil=lambda: "en")

    assert tk2.dil == "en"


def test_run_forever_dil_cagrilabilirini_her_turda_cozer(repo, ders, monkeypatch):
    """Uygulama açıkken dil değişirse ikinci turun bildirimi yeni dilde olur.

    Gerçek hata: paketlenmiş `.exe`de hatırlatıcı thread'i `run_forever`a dil
    VERMİYORDU, bildirimler Ayarlar'daki dile bakmadan hep Türkçeydi.
    """
    simdi = datetime.now(UTC).replace(microsecond=0)

    def etkinlik(baslik):
        e = _ekle(
            repo, ders, baslik, simdi + timedelta(minutes=10), simdi + timedelta(minutes=70)
        )
        repo.add_reminder(e.id, 15)

    etkinlik("Birinci")
    secili = ["tr"]
    notifier = YakalayanNotifier()

    def uykuda(sayi):
        if sayi == 1:
            secili[0] = "en"  # kullanıcı Ayarlar'dan dili değiştirdi
            etkinlik("İkinci")

    monkeypatch.setattr(daemon, "time", _SahteZaman(adim=60, tur=2, uykuda=uykuda))

    run_forever(repo, IST, notifier, dil=lambda: secili[0])

    assert [b for b, _ in notifier.gonderilen] == ["Birinci", "İkinci"]
    assert "15 dakika içinde" in notifier.gonderilen[0][1]
    assert "in 15 minutes" in notifier.gonderilen[1][1]
