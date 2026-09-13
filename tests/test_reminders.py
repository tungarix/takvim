"""Hatırlatıcı mantığı, kalıcılığı ve arka plan turu.

Saat asla gerçek zamandan okunmuyor: `now` her testte parametre. Bir
hatırlatıcı testinin "bazen geçen" hâli, hatırlatıcının kendisinden beterdir.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from core import Event, Occurrence, Reminder, due_reminders, fire_key, next_fire_time
from remind.daemon import bildirim_metni, run_once
from remind.notifier import ConsoleNotifier, pick_notifier
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
