"""Görev API'si ve ızgara verisi (`/api/tasks`, `taskId` işareti).

Görev ile blok arasındaki kurallar (`tests/test_gorevler.py`) burada HTTP
üzerinden, gerçek sunucuyla doğrulanıyor.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import date

import pytest

from store import Repo
from tests.helpers import IST, ist
from ui.presenter import gorev_payload, week_payload
from ui.server import make_server


@pytest.fixture
def repo():
    """Bellekte taze DB (sunucu thread'i için check_same_thread=False)."""
    with Repo.open(":memory:", check_same_thread=False) as r:
        yield r


@pytest.fixture
def sunucu(repo):
    """Bellek DB'li canlı sunucu; tek görünür takvim ("Ders")."""
    repo.add_calendar("Ders", "#e0524a")
    httpd = make_server(repo, IST, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _istek(temel, yontem, yol, govde=None):
    """(durum, gövde) döndürür; HTTP hatalarında da gövdeyi okur."""
    veri = json.dumps(govde).encode("utf-8") if govde is not None else None
    req = urllib.request.Request(
        temel + yol, method=yontem, data=veri,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req) as yanit:
            return yanit.status, json.loads(yanit.read().decode("utf-8"))
    except urllib.error.HTTPError as hata:
        return hata.code, json.loads(hata.read().decode("utf-8"))


def _ekle(temel, **govde):
    durum, yanit = _istek(temel, "POST", "/api/tasks", govde)
    assert durum == 201, yanit
    return yanit["task"]


def _liste(temel):
    return _istek(temel, "GET", "/api/tasks")[1]


# ---------------------------------------------------------------------------
# Oluşturma
# ---------------------------------------------------------------------------

def test_plansiz_gorev_olusur(sunucu):
    g = _ekle(sunucu, title="Rapor yaz", notes="taslak")

    assert (g["title"], g["notes"], g["plan"], g["day"], g["done"]) == (
        "Rapor yaz", "taslak", "yok", None, False)
    assert g["eventId"] is None and g["startMin"] is None


def test_gun_planli_gorev_saatsiz(sunucu):
    g = _ekle(sunucu, title="Bugün yap", plan="gun", date="2026-10-01")

    assert (g["plan"], g["day"], g["startMin"], g["eventId"]) == ("gun", "2026-10-01", None, None)


def test_saat_planli_gorev_blok_olusturur(sunucu, repo):
    g = _ekle(sunucu, title="Rapor", plan="saat", date="2026-10-01", minutes=14 * 60,
              endMinutes=15 * 60 + 30)

    assert (g["plan"], g["day"], g["startMin"], g["endMin"]) == ("saat", "2026-10-01", 840, 930)
    blok = repo.get_event(g["eventId"])
    assert (blok.title, blok.start_utc, blok.end_utc) == ("Rapor", ist(2026, 10, 1, 14), ist(2026, 10, 1, 15, 30))
    assert g["calendarId"] == blok.calendar_id


def test_saat_planinda_bitis_verilmezse_bir_saat(sunucu):
    g = _ekle(sunucu, title="Kısa", plan="saat", date="2026-10-01", minutes=600)

    assert (g["startMin"], g["endMin"]) == (600, 660)


def test_saat_planli_gorev_hatirlatici_alir(sunucu, repo):
    g = _ekle(sunucu, title="Toplantı hazırlığı", plan="saat", date="2026-10-01", minutes=600,
              reminderMinutes=[10, 60])

    assert sorted(r["minutesBefore"] for r in g["reminders"]) == [10, 60]
    assert sorted(r.minutes_before for r in repo.list_reminders(g["eventId"])) == [10, 60]


def test_bos_baslik_reddedilir_ve_hicbir_sey_yazilmaz(sunucu, repo):
    durum, yanit = _istek(sunucu, "POST", "/api/tasks", {"title": "  "})

    assert (durum, yanit["error_code"]) == (400, "baslik_bos")
    assert repo.list_tasks() == []


def test_gecersiz_plan_gorev_birakmaz(sunucu, repo):
    """Plan reddedilirse görev de eklenmemiş olmalı (yarım kayıt yok)."""
    durum, yanit = _istek(sunucu, "POST", "/api/tasks",
                          {"title": "x", "plan": "saat", "date": "2026-10-01",
                           "minutes": 900, "endMinutes": 800})

    assert (durum, yanit["error_code"]) == (400, "endminutes_sira")
    assert repo.list_tasks() == [] and repo.list_events() == []


def test_bilinmeyen_plan_kodlu_hata(sunucu):
    durum, yanit = _istek(sunucu, "POST", "/api/tasks", {"title": "x", "plan": "yarin"})

    assert (durum, yanit["error_code"], yanit["error_param"]) == (400, "bilinmeyen_plan", {"plan": "yarin"})


def test_hatirlatici_saatsiz_gorevde_reddedilir(sunucu, repo):
    """Bildirilecek bir an yok: sessizce yutmak yerine hata (kullanıcı kurduğunu sanmasın)."""
    durum, yanit = _istek(sunucu, "POST", "/api/tasks",
                          {"title": "x", "plan": "gun", "date": "2026-10-01", "reminderMinutes": 10})

    assert (durum, yanit["error_code"]) == (400, "gorev_hatirlatici_saat_ister")
    assert repo.list_tasks() == []


def test_negatif_hatirlatici_reddedilir_ve_gorev_kalmaz(sunucu, repo):
    durum, yanit = _istek(sunucu, "POST", "/api/tasks",
                          {"title": "x", "plan": "saat", "date": "2026-10-01", "minutes": 600,
                           "reminderMinutes": -5})

    assert (durum, yanit["error_code"]) == (400, "hatirlatici_negatif")
    assert repo.list_tasks() == [] and repo.list_events() == []


def test_negatif_hatirlatici_guncellemesi_baslik_degisikligini_de_geri_tutar(sunucu):
    """PATCH'te hepsi önce doğrulanır: reddedilen hatırlatıcı yüzünden ad yarım değişmiş kalmasın."""
    g = _ekle(sunucu, title="Eski", plan="saat", date="2026-10-01", minutes=600)

    durum, yanit = _istek(sunucu, "PATCH", f"/api/tasks/{g['id']}",
                          {"title": "Yeni", "reminderMinutes": -5})

    assert (durum, yanit["error_code"]) == (400, "hatirlatici_negatif")
    assert _liste(sunucu)["tasks"][0]["title"] == "Eski"


def test_plan_yazilamazsa_gorev_de_kalmaz(sunucu, repo, monkeypatch):
    """Doğrulamadan sonra bile plan yazımı patlayabilir: yarım görev bırakılmamalı."""
    def patla(*a, **k):
        raise ValueError("beklenmedik plan hatası")

    monkeypatch.setattr(repo, "plan_task_slot", patla)

    durum, _ = _istek(sunucu, "POST", "/api/tasks",
                      {"title": "x", "plan": "saat", "date": "2026-10-01", "minutes": 600})

    assert durum == 400 and repo.list_tasks() == []


def test_olmayan_takvime_blok_yazilmaz(sunucu, repo):
    durum, yanit = _istek(sunucu, "POST", "/api/tasks",
                          {"title": "x", "plan": "saat", "date": "2026-10-01", "minutes": 600,
                           "calendarId": 999})

    assert (durum, yanit["error_code"]) == (404, "takvim_bulunamadi")
    assert repo.list_tasks() == []


def test_blok_gorunur_takvime_yazilir(repo):
    """Alfabede başa düşen GİZLİ takvim varsayılan olmamalı (AGENTS 52 ile aynı tuzak)."""
    repo.add_calendar("Acil", "#000000", visible=False)
    gorunur = repo.add_calendar("Zaman", "#111111")
    httpd = make_server(repo, IST, host="127.0.0.1", port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        temel = f"http://127.0.0.1:{httpd.server_address[1]}"
        g = _ekle(temel, title="x", plan="saat", date="2026-10-01", minutes=600)
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert g["calendarId"] == gorunur.id


# ---------------------------------------------------------------------------
# Güncelleme
# ---------------------------------------------------------------------------

def test_kutu_isaretlenir_ve_geri_acilir(sunucu):
    g = _ekle(sunucu, title="x")

    kapali = _istek(sunucu, "PATCH", f"/api/tasks/{g['id']}", {"done": True})[1]["task"]
    acik = _istek(sunucu, "PATCH", f"/api/tasks/{g['id']}", {"done": False})[1]["task"]

    assert kapali["done"] is True and kapali["doneAt"] is not None
    assert acik["done"] is False and acik["doneAt"] is None


def test_patch_gonderilmeyen_alana_dokunmaz(sunucu):
    """Yalnızca `done` gönderilince başlık, not ve plan aynen kalmalı."""
    g = _ekle(sunucu, title="Ad", notes="not", plan="gun", date="2026-10-01")

    son = _istek(sunucu, "PATCH", f"/api/tasks/{g['id']}", {"done": True})[1]["task"]

    assert (son["title"], son["notes"], son["plan"], son["day"]) == ("Ad", "not", "gun", "2026-10-01")


def test_gunden_saate_planlanir(sunucu):
    g = _ekle(sunucu, title="x", plan="gun", date="2026-10-01")

    son = _istek(sunucu, "PATCH", f"/api/tasks/{g['id']}",
                 {"plan": "saat", "date": "2026-10-02", "minutes": 540})[1]["task"]

    assert (son["plan"], son["day"], son["startMin"]) == ("saat", "2026-10-02", 540)
    assert son["eventId"] is not None


def test_saatten_plansiza_donunce_blok_gider(sunucu, repo):
    g = _ekle(sunucu, title="x", plan="saat", date="2026-10-01", minutes=540)

    son = _istek(sunucu, "PATCH", f"/api/tasks/{g['id']}", {"plan": "yok"})[1]["task"]

    assert (son["plan"], son["eventId"]) == ("yok", None)
    assert repo.list_events() == []


def test_yeniden_adlandirma_blogu_da_adlandirir(sunucu, repo):
    g = _ekle(sunucu, title="Eski", plan="saat", date="2026-10-01", minutes=540)

    _istek(sunucu, "PATCH", f"/api/tasks/{g['id']}", {"title": "Yeni"})

    assert repo.get_event(g["eventId"]).title == "Yeni"


def test_bos_baslikla_guncelleme_hicbir_alani_degistirmez(sunucu):
    """Önce hepsi doğrulanıyor: reddedilen güncelleme yarısını uygulamış olmasın."""
    g = _ekle(sunucu, title="Ad")

    durum, yanit = _istek(sunucu, "PATCH", f"/api/tasks/{g['id']}", {"title": " ", "done": True})

    assert (durum, yanit["error_code"]) == (400, "baslik_bos")
    assert _liste(sunucu)["tasks"][0]["done"] is False


def test_olmayan_gorev_404(sunucu):
    durum, yanit = _istek(sunucu, "PATCH", "/api/tasks/99", {"done": True})
    assert (durum, yanit["error_code"]) == (404, "gorev_bulunamadi")
    assert _istek(sunucu, "DELETE", "/api/tasks/99")[0] == 404


# ---------------------------------------------------------------------------
# Silme ve geri alma
# ---------------------------------------------------------------------------

def test_silme_blogu_da_siler(sunucu, repo):
    g = _ekle(sunucu, title="x", plan="saat", date="2026-10-01", minutes=540)

    durum, yanit = _istek(sunucu, "DELETE", f"/api/tasks/{g['id']}")

    assert (durum, yanit["deleted"]) == (200, g["id"])
    assert repo.list_tasks() == [] and repo.list_events() == []


def test_silme_yaniti_geri_alma_icin_yeterli(sunucu):
    """Geri al = aynı özeti POST'lamak: plan, saat, takvim ve hatırlatıcı korunmalı."""
    g = _ekle(sunucu, title="Rapor", notes="taslak", plan="saat", date="2026-10-01",
              minutes=840, endMinutes=930, reminderMinutes=[15])
    ozet = _istek(sunucu, "DELETE", f"/api/tasks/{g['id']}")[1]["task"]

    yeniden = _ekle(sunucu, title=ozet["title"], notes=ozet["notes"], plan=ozet["plan"],
                    date=ozet["day"], minutes=ozet["startMin"], endMinutes=ozet["endMin"],
                    calendarId=ozet["calendarId"], done=ozet["done"],
                    reminderMinutes=[r["minutesBefore"] for r in ozet["reminders"]])

    assert (yeniden["title"], yeniden["notes"], yeniden["day"], yeniden["startMin"], yeniden["endMin"]) == (
        "Rapor", "taslak", "2026-10-01", 840, 930)
    assert [r["minutesBefore"] for r in yeniden["reminders"]] == [15]


# ---------------------------------------------------------------------------
# Liste
# ---------------------------------------------------------------------------

def test_liste_sirasi_acik_gunlu_gunsuz_sonra_tamamlanan(sunucu):
    plansiz = _ekle(sunucu, title="plansız")
    sonra = _ekle(sunucu, title="ikinci gün", plan="gun", date="2026-10-02")
    ogleden = _ekle(sunucu, title="öğleden sonra", plan="saat", date="2026-10-01", minutes=900)
    sabah = _ekle(sunucu, title="sabah", plan="saat", date="2026-10-01", minutes=540)
    gun_sonu = _ekle(sunucu, title="saatsiz aynı gün", plan="gun", date="2026-10-01")
    bitmis = _ekle(sunucu, title="bitmiş", plan="gun", date="2026-09-01")
    _istek(sunucu, "PATCH", f"/api/tasks/{bitmis['id']}", {"done": True})

    adlar = [g["title"] for g in _liste(sunucu)["tasks"]]

    # Aynı günde saatli olanlar önce (saate göre), saatsiz gün görevi sonra.
    assert adlar == ["sabah", "öğleden sonra", "saatsiz aynı gün", "ikinci gün", "plansız", "bitmiş"]
    assert {sabah["title"], ogleden["title"], sonra["title"], gun_sonu["title"], plansiz["title"]} <= set(adlar)


def test_bugun_uygulamanin_saat_dilimindedir(repo):
    """`today` istemcinin değil sunucunun tzid'inde: 21:30 UTC İstanbul'da ertesi gün 00:30."""
    from datetime import datetime

    from core import UTC

    yanit = gorev_payload(repo, IST, simdi=datetime(2026, 9, 30, 21, 30, tzinfo=UTC))

    assert yanit["today"] == "2026-10-01"


def test_surukleyince_listedeki_saat_guncellenir(sunucu, repo):
    """Izgarada sürüklemek override yazar; liste eski saati göstermemeli."""
    g = _ekle(sunucu, title="x", plan="saat", date="2026-10-01", minutes=840)
    repo.move_occurrence(g["eventId"], ist(2026, 10, 1, 14), ist(2026, 10, 1, 16))

    son = _liste(sunucu)["tasks"][0]

    assert (son["startMin"], son["endMin"]) == (960, 1020)


def test_gun_yerel_takvim_gunudur_utc_gunu_degil(sunucu):
    """00:30 İstanbul, UTC'de bir önceki gün 21:30: liste 'gün'ü yerel hesaplamalı (AGENTS 13)."""
    g = _ekle(sunucu, title="x", plan="saat", date="2026-10-01", minutes=30)

    assert (g["day"], g["startMin"]) == ("2026-10-01", 30)
    assert g["startUtc"].startswith("2026-09-30T21:30")


def test_gece_yarisini_asan_blokta_bitis_1440i_gecer(sunucu):
    g = _ekle(sunucu, title="x", plan="saat", date="2026-10-01", minutes=23 * 60 + 30, endMinutes=25 * 60)

    assert (g["startMin"], g["endMin"], g["day"]) == (1410, 1500, "2026-10-01")


# ---------------------------------------------------------------------------
# Izgara: blok görev olarak işaretlenir, saatsiz görev ızgarada YOKTUR
# ---------------------------------------------------------------------------

def _hafta_olaylari(repo, gun=date(2026, 10, 1)):
    yuk = week_payload(repo, gun, IST)
    return [e for d in yuk["days"] for e in d["timed"] + d["allDay"]]


def test_blok_izgarada_gorev_olarak_isaretlenir(sunucu, repo):
    g = _ekle(sunucu, title="Rapor", plan="saat", date="2026-10-01", minutes=840)

    (olay,) = _hafta_olaylari(repo)

    assert (olay["taskId"], olay["taskDone"], olay["title"]) == (g["id"], False, "Rapor")


def test_tamamlanan_blok_taskdone_gosterir(sunucu, repo):
    g = _ekle(sunucu, title="Rapor", plan="saat", date="2026-10-01", minutes=840)
    _istek(sunucu, "PATCH", f"/api/tasks/{g['id']}", {"done": True})

    (olay,) = _hafta_olaylari(repo)

    assert olay["taskDone"] is True


def test_siradan_etkinlikte_taskid_yok(sunucu, repo):
    _istek(sunucu, "POST", "/api/events", {"title": "Toplantı", "date": "2026-10-01", "minutes": 600})

    (olay,) = _hafta_olaylari(repo)

    assert "taskId" not in olay


def test_saatsiz_gorev_izgarada_gorunmez(sunucu, repo):
    """Karar: gün planlı görev tüm gün şeridine de düşmez; yalnızca listede durur."""
    _ekle(sunucu, title="Bugün yap", plan="gun", date="2026-10-01")
    _ekle(sunucu, title="Plansız")

    assert _hafta_olaylari(repo) == []


def test_ay_gorunumunde_de_blok_isaretlenir(sunucu, repo):
    from ui.presenter import month_payload

    g = _ekle(sunucu, title="Rapor", plan="saat", date="2026-10-01", minutes=840)

    olaylar = [e for d in month_payload(repo, date(2026, 10, 1), IST)["days"] for e in d["events"]]

    assert [e["taskId"] for e in olaylar] == [g["id"]]


def test_bloga_bagli_gorev_etkinlik_panelinden_yeniden_adlandirilinca_liste_degisir(sunucu):
    """PATCH /api/events/<id> (etkinlik paneli) görevi de günceller: iki ad ayrışmamalı."""
    g = _ekle(sunucu, title="Eski", plan="saat", date="2026-10-01", minutes=540)

    _istek(sunucu, "PATCH", f"/api/events/{g['eventId']}", {"title": "Panelden"})

    assert _liste(sunucu)["tasks"][0]["title"] == "Panelden"


def test_blok_silinince_gorev_listede_kalir_plansiz(sunucu):
    """Izgaradan blok silme (etkinlik sil) yapılacak işi kaybettirmemeli."""
    g = _ekle(sunucu, title="Rapor", plan="saat", date="2026-10-01", minutes=540)

    _istek(sunucu, "DELETE", f"/api/events/{g['eventId']}")

    (kalan,) = _liste(sunucu)["tasks"]
    assert (kalan["title"], kalan["plan"], kalan["eventId"]) == ("Rapor", "yok", None)
