"""Faz 4: ay/gün görünümleri ve HTTP API.

Payload testleri saf (`presenter`), API testleri gerçek bir sunucu ayağa
kaldırıp HTTP konuşuyor -- route çözümü ve JSON sözleşmesi de kapsansın diye.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

import pytest

from core import Event
from store import Repo, new_uid
from tests.helpers import IST, ist
from ui.presenter import day_payload, month_payload, week_payload
from ui.server import make_server


@pytest.fixture
def repo():
    """Bellekte taze DB.

    `check_same_thread=False`: HTTP testleri sunucuyu arka plan thread'inde
    çalıştırıyor ama depo burada, ana thread'de kuruluyor. Sunucu tek thread'li
    olduğu için erişim yine sıralı -- kontrolü susturmak güvenli.
    """
    with Repo.open(":memory:", check_same_thread=False) as r:
        yield r


@pytest.fixture
def ders(repo):
    """Görünür varsayılan takvim."""
    return repo.add_calendar("Ders", "#e0524a")


def _ekle(repo, takvim, baslik, start, end, *, all_day=False, rrule=None):
    """Kısa Event kurucusu."""
    return repo.add_event(
        Event(
            id=None, uid=new_uid(), calendar_id=takvim.id, title=baslik,
            start_utc=start, end_utc=end, tzid=IST, all_day=all_day, rrule=rrule,
        )
    )


def _gun(payload, tarih: str) -> dict:
    """Payload içinden bir günü seçer."""
    return next(g for g in payload["days"] if g["date"] == tarih)


# ---------------------------------------------------------------------------
# Gün görünümü
# ---------------------------------------------------------------------------

def test_gun_payload_tek_gun(repo, ders):
    """Gün görünümü tek günlük ama hafta ile aynı yapıda."""
    _ekle(repo, ders, "Ders", ist(2026, 9, 8, 10, 0), ist(2026, 9, 8, 11, 0))
    payload = day_payload(repo, date(2026, 9, 8), IST)

    assert payload["view"] == "day"
    assert len(payload["days"]) == 1
    assert payload["days"][0]["date"] == "2026-09-08"
    assert payload["label"] == "8 Eylül 2026 Salı"
    assert [o["title"] for o in payload["days"][0]["timed"]] == ["Ders"]


def test_gun_payload_komsu_gunu_sizdirmaz(repo, ders):
    """Ertesi günün etkinliği gelmez."""
    _ekle(repo, ders, "Yarın", ist(2026, 9, 9, 10, 0), ist(2026, 9, 9, 11, 0))
    payload = day_payload(repo, date(2026, 9, 8), IST)

    assert payload["days"][0]["timed"] == []


# ---------------------------------------------------------------------------
# Ay görünümü
# ---------------------------------------------------------------------------

def test_ay_izgarasi_tam_haftalardan_olusur(repo, ders):
    """Eylül 2026: 1'i Salı, 30'u Çarşamba -> ızgara 31 Ağu - 4 Eki, 35 gün."""
    payload = month_payload(repo, date(2026, 9, 15), IST)

    assert payload["view"] == "month"
    assert payload["label"] == "Eylül 2026"
    assert payload["gridStart"] == "2026-08-31"
    assert payload["gridEnd"] == "2026-10-04"
    assert len(payload["days"]) == 35
    assert len(payload["days"]) % 7 == 0, "ızgara tam haftalardan oluşmalı"


def test_ay_izgarasi_sabit_alti_satir_degil(repo, ders):
    """Ay 5 haftaya sığıyorsa 6. satır çizilmez."""
    # Şubat 2027: 1'i Pazartesi, 28'i Pazar -> tam 4 hafta
    payload = month_payload(repo, date(2027, 2, 10), IST)

    assert len(payload["days"]) == 28
    assert payload["gridStart"] == "2027-02-01"
    assert payload["gridEnd"] == "2027-02-28"


def test_ay_komsu_gunleri_isaretlenir(repo, ders):
    """inMonth, ayın kendi günlerini komşu ay günlerinden ayırır."""
    payload = month_payload(repo, date(2026, 9, 15), IST)

    assert _gun(payload, "2026-08-31")["inMonth"] is False
    assert _gun(payload, "2026-09-01")["inMonth"] is True
    assert _gun(payload, "2026-10-01")["inMonth"] is False


def test_ay_tumgun_once_sonra_saate_gore(repo, ders):
    """Hücre içinde tüm gün ÜSTTE, saatliler saat sırasında.

    Ayırt edici vaka gece yarısını aşan etkinlik: dünden sarkan 23:00-01:00'in
    `start_utc`'si tüm gün etkinliğinin gece yarısından ÖNCE. Yalnızca
    başlangıca göre sıralasaydık o, tüm gün etkinliğinin üstüne çıkardı.
    """
    _ekle(repo, ders, "Öğleden sonra", ist(2026, 9, 8, 15, 0), ist(2026, 9, 8, 16, 0))
    _ekle(repo, ders, "Sabah", ist(2026, 9, 8, 9, 0), ist(2026, 9, 8, 10, 0))
    _ekle(repo, ders, "Dünden sarkan", ist(2026, 9, 7, 23, 0), ist(2026, 9, 8, 1, 0))
    _ekle(repo, ders, "Tatil", ist(2026, 9, 8), ist(2026, 9, 9), all_day=True)

    payload = month_payload(repo, date(2026, 9, 1), IST)
    assert [o["title"] for o in _gun(payload, "2026-09-08")["events"]] == [
        "Tatil", "Dünden sarkan", "Sabah", "Öğleden sonra"
    ]


def test_ay_komsu_ay_gunlerinin_etkinlikleri_de_gelir(repo, ders):
    """Izgaradaki komşu ay günleri boş görünmemeli."""
    _ekle(repo, ders, "Ağustos sonu", ist(2026, 8, 31, 10, 0), ist(2026, 8, 31, 11, 0))
    payload = month_payload(repo, date(2026, 9, 15), IST)

    assert [o["title"] for o in _gun(payload, "2026-08-31")["events"]] == ["Ağustos sonu"]


def test_ay_gizli_takvim_haric(repo, ders):
    """Görünürlük ay görünümünde de geçerli."""
    gizli = repo.add_calendar("Arşiv", "#666", visible=False)
    _ekle(repo, gizli, "Eski", ist(2026, 9, 8, 10, 0), ist(2026, 9, 8, 11, 0))
    payload = month_payload(repo, date(2026, 9, 1), IST)

    assert _gun(payload, "2026-09-08")["events"] == []


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------

@pytest.fixture
def sunucu(repo, ders):
    """Gerçek bir HTTP sunucusu, rastgele boş portta."""
    _ekle(repo, ders, "Algoritma", ist(2026, 9, 7, 10, 0), ist(2026, 9, 7, 12, 0),
          rrule="FREQ=WEEKLY;BYDAY=MO")
    httpd = make_server(repo, IST, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _get(temel: str, yol: str):
    """GET + JSON çözme."""
    with urllib.request.urlopen(temel + yol) as yanit:
        return json.loads(yanit.read().decode("utf-8"))


def _post(temel: str, yol: str, govde: dict, method: str = "POST"):
    """JSON gövdeli istek."""
    req = urllib.request.Request(
        temel + yol,
        method=method,
        data=json.dumps(govde, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req) as yanit:
        return json.loads(yanit.read().decode("utf-8"))


def test_api_gorunumler(sunucu):
    """Üç görünüm de doğru `view` alanıyla dönüyor."""
    assert _get(sunucu, "/api/week?date=2026-09-08")["view"] == "week"
    assert _get(sunucu, "/api/day?date=2026-09-08")["view"] == "day"
    assert _get(sunucu, "/api/month?date=2026-09-08")["view"] == "month"


def test_api_hizli_ekleme(sunucu):
    """POST /api/events metni ayrıştırıp kaydeder ve tanınanı bildirir."""
    sonuc = _post(sunucu, "/api/events", {"text": "9 eylül 2026 14:00 diş hekimi"})

    assert sonuc["event"]["title"] == "diş hekimi"
    assert sonuc["parsed"]["allDay"] is False
    assert "14:00" in sonuc["parsed"]["matched"]

    hafta = _get(sunucu, "/api/week?date=2026-09-09")
    basliklar = [o["title"] for g in hafta["days"] for o in g["timed"]]
    assert "diş hekimi" in basliklar


def test_api_hizli_ekleme_taninmayan_zamani_bildirir(sunucu):
    """Zaman tanınmadığında `matched` boş gelir; arayüz kullanıcıyı uyarabilsin."""
    sonuc = _post(sunucu, "/api/events", {"text": "doğum günü"})

    assert sonuc["parsed"]["matched"] == ""
    assert sonuc["parsed"]["allDay"] is True


def test_api_tek_ornek_iptali(sunucu):
    """Serinin tek örneği iptal edilince diğerleri kalır."""
    onceki = _get(sunucu, "/api/week?date=2026-09-14")
    occ = next(o for g in onceki["days"] for o in g["timed"] if o["title"] == "Algoritma")

    _post(sunucu, "/api/occurrences/cancel",
          {"eventId": occ["eventId"], "originalStartUtc": occ["startUtc"]})

    sonraki = _get(sunucu, "/api/week?date=2026-09-14")
    assert not any(o["title"] == "Algoritma" for g in sonraki["days"] for o in g["timed"])

    # Komşu hafta etkilenmemeli
    komsu = _get(sunucu, "/api/week?date=2026-09-21")
    assert any(o["title"] == "Algoritma" for g in komsu["days"] for o in g["timed"])


def test_api_tek_ornek_kaydirma(sunucu):
    """Kaydırılan örnek yeni saatinde ve override işaretiyle görünür."""
    hafta = _get(sunucu, "/api/week?date=2026-09-14")
    occ = next(o for g in hafta["days"] for o in g["timed"] if o["title"] == "Algoritma")

    _post(sunucu, "/api/occurrences/move", {
        "eventId": occ["eventId"],
        "originalStartUtc": occ["startUtc"],
        "newStartUtc": ist(2026, 9, 14, 16, 0).isoformat(),
    })

    sonraki = _get(sunucu, "/api/week?date=2026-09-14")
    tasinan = next(o for g in sonraki["days"] for o in g["timed"] if o["title"] == "Algoritma")
    assert tasinan["isOverride"] is True
    assert tasinan["startMin"] == 16 * 60


def test_api_baslik_guncelleme(sunucu):
    """PATCH başlığı değiştirir."""
    hafta = _get(sunucu, "/api/week?date=2026-09-07")
    occ = next(o for g in hafta["days"] for o in g["timed"])

    _post(sunucu, f"/api/events/{occ['eventId']}", {"title": "Veri Yapıları"}, method="PATCH")

    sonraki = _get(sunucu, "/api/week?date=2026-09-07")
    assert any(o["title"] == "Veri Yapıları" for g in sonraki["days"] for o in g["timed"])


def test_api_seri_silme(sunucu):
    """DELETE tüm seriyi kaldırır."""
    hafta = _get(sunucu, "/api/week?date=2026-09-07")
    occ = next(o for g in hafta["days"] for o in g["timed"])

    req = urllib.request.Request(f"{sunucu}/api/events/{occ['eventId']}", method="DELETE")
    urllib.request.urlopen(req).read()

    sonraki = _get(sunucu, "/api/week?date=2026-09-14")
    assert all(not g["timed"] for g in sonraki["days"])


def test_api_arama(sunucu):
    """Arama hoşgörülü: büyük/küçük harf ve Türkçe şapkalar önemsenmez.

    "ALGORITMA" (ASCII I ile) dilbilimsel olarak "algorıtma" demektir ve katı
    Türkçe küçültmeyle "Algoritma"yı bulamazdı. Aramada niyet eşleştirmek.
    """
    for sorgu in ("ALGORITMA", "algoritma", "ALGORİTMA", "ritma"):
        sonuc = _get(sunucu, f"/api/search?q={urllib.parse.quote(sorgu)}")["results"]
        assert [r["title"] for r in sonuc] == ["Algoritma"], f"{sorgu!r} bulamadı"

    assert _get(sunucu, "/api/search?q=yok")["results"] == []


def test_api_disa_aktarma(sunucu):
    """GET /api/export indirilebilir .ics döndürür."""
    with urllib.request.urlopen(sunucu + "/api/export") as yanit:
        govde = yanit.read().decode("utf-8")
        assert "text/calendar" in yanit.headers["Content-Type"]
        assert "attachment" in yanit.headers["Content-Disposition"]

    assert govde.startswith("BEGIN:VCALENDAR")
    assert "Algoritma" in govde


def test_api_ice_aktarma(sunucu):
    """POST /api/import gövdedeki .ics metnini alır."""
    ics_metni = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
        "UID:api-test-1\r\n"
        "DTSTART;TZID=Europe/Istanbul:20260908T140000\r\n"
        "DTEND;TZID=Europe/Istanbul:20260908T150000\r\n"
        "SUMMARY:İçe aktarılan\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    req = urllib.request.Request(
        sunucu + "/api/import", method="POST",
        data=ics_metni.encode("utf-8"),
        headers={"Content-Type": "text/calendar; charset=utf-8"},
    )
    with urllib.request.urlopen(req) as yanit:
        rapor = json.loads(yanit.read().decode("utf-8"))

    assert rapor["added"] == 1
    assert rapor["errors"] == []

    hafta = _get(sunucu, "/api/week?date=2026-09-08")
    assert any(o["title"] == "İçe aktarılan" for g in hafta["days"] for o in g["timed"])


def test_api_bozuk_istekler(sunucu):
    """Hatalı girdiler 4xx ve açıklayıcı gövde döndürür, sunucuyu düşürmez."""
    for yol in ("/api/week?date=bozuk", "/api/yok"):
        with pytest.raises(urllib.error.HTTPError) as hata:
            _get(sunucu, yol)
        assert 400 <= hata.value.code < 500

    with pytest.raises(urllib.error.HTTPError) as hata:
        _post(sunucu, "/api/events", {"text": "   "})
    assert hata.value.code == 400

    # Sunucu hâlâ ayakta
    assert _get(sunucu, "/api/week?date=2026-09-08")["view"] == "week"


def test_api_statik_dosya_disina_cikamaz(sunucu):
    """Dizin dolaşma denemesi 404 döner."""
    with pytest.raises(urllib.error.HTTPError) as hata:
        _get(sunucu, "/../pyproject.toml")
    assert hata.value.code == 404


# ---------------------------------------------------------------------------
# Override anahtarı: taşınmış örneği yeniden taşımak
# ---------------------------------------------------------------------------

def test_tasinmis_ornegin_orijinal_anahtari_korunur(repo, ders):
    """Override'lı örnekte `originalStartUtc`, `startUtc`'den FARKLIDIR.

    Regresyon: ön yüz `startUtc` gönderiyordu. Bir kez taşınmış örneği tekrar
    taşımak, var olan override'ı güncellemek yerine seriye ait olmayan ikinci
    bir kayıt yaratıyordu; `expand` onu hayalet sayıp atıyor ve kullanıcının
    değişikliği SESSİZCE kayboluyordu.
    """
    event = _ekle(
        repo, ders, "Ders", ist(2026, 9, 7, 9, 0), ist(2026, 9, 7, 10, 0),
        rrule="FREQ=WEEKLY;BYDAY=MO",
    )
    repo.move_occurrence(event.id, ist(2026, 9, 7, 9, 0), ist(2026, 9, 7, 15, 0))

    payload = week_payload(repo, date(2026, 9, 7), IST)
    occ = payload["days"][0]["timed"][0]

    assert occ["isOverride"] is True
    assert occ["startUtc"] != occ["originalStartUtc"], "taşınmış saat ile anahtar aynı olamaz"
    assert occ["originalStartUtc"] == ist(2026, 9, 7, 9, 0).isoformat()


def test_tasinmis_ornek_tekrar_tasinabilir(sunucu):
    """İki kez üst üste taşımak ikinci override yaratmaz, mevcudu günceller."""
    hafta = _get(sunucu, "/api/week?date=2026-09-07")
    occ = next(o for g in hafta["days"] for o in g["timed"] if o["title"] == "Algoritma")

    _post(sunucu, "/api/occurrences/move", {
        "eventId": occ["eventId"],
        "originalStartUtc": occ["originalStartUtc"],
        "newDate": "2026-09-07", "newMinutes": 15 * 60,
    })
    ara = _get(sunucu, "/api/week?date=2026-09-07")
    tasinan = next(o for g in ara["days"] for o in g["timed"] if o["title"] == "Algoritma")
    assert tasinan["startMin"] == 15 * 60

    # İkinci taşıma: anahtar hâlâ ORİJİNAL başlangıç
    _post(sunucu, "/api/occurrences/move", {
        "eventId": tasinan["eventId"],
        "originalStartUtc": tasinan["originalStartUtc"],
        "newDate": "2026-09-07", "newMinutes": 18 * 60,
    })
    son = _get(sunucu, "/api/week?date=2026-09-07")
    bloklar = [o for g in son["days"] for o in g["timed"] if o["title"] == "Algoritma"]

    assert len(bloklar) == 1, "ikinci override yaratılmamalı"
    assert bloklar[0]["startMin"] == 18 * 60


def test_tasinmis_ornek_iptal_edilebilir(sunucu):
    """Taşınmış örneği iptal etmek de orijinal anahtarla çalışır."""
    hafta = _get(sunucu, "/api/week?date=2026-09-07")
    occ = next(o for g in hafta["days"] for o in g["timed"] if o["title"] == "Algoritma")

    _post(sunucu, "/api/occurrences/move", {
        "eventId": occ["eventId"], "originalStartUtc": occ["originalStartUtc"],
        "newDate": "2026-09-07", "newMinutes": 15 * 60,
    })
    ara = _get(sunucu, "/api/week?date=2026-09-07")
    tasinan = next(o for g in ara["days"] for o in g["timed"] if o["title"] == "Algoritma")

    _post(sunucu, "/api/occurrences/cancel", {
        "eventId": tasinan["eventId"],
        "originalStartUtc": tasinan["originalStartUtc"],
    })
    son = _get(sunucu, "/api/week?date=2026-09-07")
    assert not any(o["title"] == "Algoritma" for g in son["days"] for o in g["timed"])


def test_surukleme_hedefi_tarih_dakika_ile_verilebilir(sunucu):
    """newDate + newMinutes sunucuda yerel saate çevrilir.

    Ön yüz saat dilimi matematiği yapmasın diye; JS'te "şu IANA diliminde şu
    duvar saati" kurmak güvenilir değil.
    """
    hafta = _get(sunucu, "/api/week?date=2026-09-07")
    occ = next(o for g in hafta["days"] for o in g["timed"])

    sonuc = _post(sunucu, "/api/occurrences/move", {
        "eventId": occ["eventId"], "originalStartUtc": occ["originalStartUtc"],
        "newDate": "2026-09-09", "newMinutes": 13 * 60 + 30,
    })
    # 13:30 Europe/Istanbul = 10:30 UTC
    assert sonuc["moved"]["newStartUtc"].startswith("2026-09-09T10:30")

    import pytest as _pytest
    with _pytest.raises(urllib.error.HTTPError):
        _post(sunucu, "/api/occurrences/move", {
            "eventId": occ["eventId"], "originalStartUtc": occ["originalStartUtc"],
            "newDate": "2026-09-09", "newMinutes": 2000,
        })


def test_hatirlatici_uclari(sunucu):
    """Hatırlatıcı eklenir, payload'da görünür, silinir."""
    hafta = _get(sunucu, "/api/week?date=2026-09-07")
    occ = next(o for g in hafta["days"] for o in g["timed"])
    assert occ["reminders"] == []

    sonuc = _post(sunucu, f"/api/events/{occ['eventId']}/reminders", {"minutesBefore": 15})
    rid = sonuc["reminder"]["id"]

    sonra = _get(sunucu, "/api/week?date=2026-09-07")
    occ2 = next(o for g in sonra["days"] for o in g["timed"])
    assert occ2["reminders"] == [{"id": rid, "minutesBefore": 15}]

    req = urllib.request.Request(f"{sunucu}/api/reminders/{rid}", method="DELETE")
    urllib.request.urlopen(req).read()

    son = _get(sunucu, "/api/week?date=2026-09-07")
    assert next(o for g in son["days"] for o in g["timed"])["reminders"] == []


# ---------------------------------------------------------------------------
# Yeniden boyutlandırma ve tüm gün taşıma
# ---------------------------------------------------------------------------

def test_yeniden_boyutlandirma(sunucu):
    """newEndMinutes süreyi değiştirir, başlangıcı bırakır."""
    hafta = _get(sunucu, "/api/week?date=2026-09-07")
    occ = next(o for g in hafta["days"] for o in g["timed"] if o["title"] == "Algoritma")
    assert (occ["startMin"], occ["endMin"]) == (10 * 60, 12 * 60)

    _post(sunucu, "/api/occurrences/move", {
        "eventId": occ["eventId"], "originalStartUtc": occ["originalStartUtc"],
        "newDate": "2026-09-07", "newMinutes": 10 * 60, "newEndMinutes": 11 * 60,
    })

    sonra = _get(sunucu, "/api/week?date=2026-09-07")
    yeni = next(o for g in sonra["days"] for o in g["timed"] if o["title"] == "Algoritma")
    assert (yeni["startMin"], yeni["endMin"]) == (10 * 60, 11 * 60)
    assert yeni["isOverride"] is True


def test_boyutlandirma_gecersiz_degerleri_reddeder(sunucu):
    """Bitiş başlangıçtan küçük olamaz, iki günü aşamaz."""
    hafta = _get(sunucu, "/api/week?date=2026-09-07")
    occ = next(o for g in hafta["days"] for o in g["timed"])

    for bitis in (9 * 60, 10 * 60, 49 * 60):
        with pytest.raises(urllib.error.HTTPError) as hata:
            _post(sunucu, "/api/occurrences/move", {
                "eventId": occ["eventId"], "originalStartUtc": occ["originalStartUtc"],
                "newDate": "2026-09-07", "newMinutes": 10 * 60, "newEndMinutes": bitis,
            })
        assert hata.value.code == 400


def test_boyutlandirma_gece_yarisini_asabilir(sunucu):
    """newEndMinutes 24*60'ı aşabilir: etkinlik ertesi güne sarkabilir."""
    hafta = _get(sunucu, "/api/week?date=2026-09-07")
    occ = next(o for g in hafta["days"] for o in g["timed"])

    sonuc = _post(sunucu, "/api/occurrences/move", {
        "eventId": occ["eventId"], "originalStartUtc": occ["originalStartUtc"],
        "newDate": "2026-09-07", "newMinutes": 22 * 60, "newEndMinutes": 25 * 60,
    })
    # 08.09 01:00 Europe/Istanbul = 07.09 22:00 UTC
    assert sonuc["moved"]["newEndUtc"].startswith("2026-09-07T22:00")


def test_tumgun_baska_gune_tasinir(repo, ders, sunucu):
    """Tüm gün etkinliği gün birimiyle taşınır ve süresini korur."""
    olay = _ekle(repo, ders, "Tatil", ist(2026, 9, 8), ist(2026, 9, 10), all_day=True)

    hafta = _get(sunucu, "/api/week?date=2026-09-07")
    occ = next(o for g in hafta["days"] for o in g["allDay"])

    _post(sunucu, "/api/occurrences/move", {
        "eventId": occ["eventId"], "originalStartUtc": occ["originalStartUtc"],
        "newDate": "2026-09-10", "newMinutes": 0,
    })

    sonra = _get(sunucu, "/api/week?date=2026-09-07")
    gunler = [g["date"] for g in sonra["days"] if g["allDay"]]
    assert gunler == ["2026-09-10", "2026-09-11"], "2 günlük süre korunmalı"
    assert olay.id is not None


# ---------------------------------------------------------------------------
# İlk açılış
# ---------------------------------------------------------------------------

def test_ilk_acilista_varsayilan_takvim(repo):
    """Takvim yoksa bir tane açılır: boş ekranla karşılamıyoruz.

    Takvimsiz bir veritabanında hızlı ekleme "önce bir takvim oluşturulmalı"
    diye reddediyor; kullanıcı ilk açılışta hiçbir şey yapamazdı.
    """
    from ui.__main__ import varsayilan_takvim_saglat

    assert repo.list_calendars() == []
    assert varsayilan_takvim_saglat(repo) is True
    assert [c.name for c in repo.list_calendars()] == ["Kişisel"]


def test_mevcut_takvim_varsa_dokunmaz(repo, ders):
    """İkinci açılışta yeni takvim eklenmez."""
    from ui.__main__ import varsayilan_takvim_saglat

    assert varsayilan_takvim_saglat(repo) is False
    assert len(repo.list_calendars()) == 1


# ---------------------------------------------------------------------------
# Başlatma sağlamlığı (son kullanıcı)
# ---------------------------------------------------------------------------

def test_bos_port_bulunur():
    """Port doluysa bir sonraki boş port seçilir.

    Regresyon: dolu portta uygulama "Address already in use" ile ölüyor ve
    kısayolun küçültülmüş penceresi kapanıp geriye hiçbir açıklama bırakmıyordu.
    """
    import socket

    from ui.server import bos_port_bul

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as mesgul:
        mesgul.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        mesgul.bind(("127.0.0.1", 0))
        mesgul.listen(1)
        dolu = mesgul.getsockname()[1]

        secilen = bos_port_bul("127.0.0.1", dolu)
        assert secilen != dolu
        assert dolu < secilen <= dolu + 20


def test_hepsi_doluysa_aciklayici_hata():
    """Boş port bulunamazsa sessizce ölmüyor, anlaşılır hata veriyor."""
    from ui.server import bos_port_bul

    with pytest.raises(OSError, match="boş port yok"):
        bos_port_bul("127.0.0.1", 80, deneme=0)


def test_tarayici_soket_baglandiktan_sonra_acilir(repo, ders):
    """`on_ready` çağrıldığında port GERÇEKTEN dinleniyor olmalı.

    Regresyon: tarayıcı `serve()` çağrılmadan açılıyordu ve hızlı bir makinede
    henüz dinlemeyen porta gidip "siteye ulaşılamıyor" gösteriyordu.
    """
    import socket
    import threading

    from ui.server import make_server, serve

    sonuc = {}
    hazir_olay = threading.Event()

    def hazir(port):
        # Bağlantı kurulabiliyorsa soket dinliyordur.
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                sonuc["dinliyor"] = True
        except OSError:
            sonuc["dinliyor"] = False
        sonuc["port"] = port
        hazir_olay.set()

    thread = threading.Thread(
        target=lambda: serve(repo, IST, "127.0.0.1", 0, False, on_ready=hazir),
        daemon=True,
    )
    thread.start()
    assert hazir_olay.wait(timeout=10), "on_ready çağrılmadı"

    assert sonuc["dinliyor"] is True, "on_ready anında port dinlemiyordu"
    assert sonuc["port"] > 0


# ---------------------------------------------------------------------------
# Kaynak denetimi (yalnızca Takvim penceresinden gelen yazma istekleri)
# ---------------------------------------------------------------------------

def _yazma_istegi(temel: str, basliklar: dict):
    """Verilen başlıklarla bir POST dener; HTTP durum kodunu döndürür."""
    req = urllib.request.Request(
        temel + "/api/events",
        method="POST",
        data=json.dumps({"text": "yarın 10:00 deneme"}).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8", **basliklar},
    )
    try:
        with urllib.request.urlopen(req) as yanit:
            return yanit.status
    except urllib.error.HTTPError as hata:
        return hata.code


def test_baska_siteden_gelen_yazma_reddedilir(sunucu):
    """Kullanıcının açtığı bir web sayfası takvime etkinlik EKLEYEMEZ.

    Sunucu yalnızca 127.0.0.1'i dinliyor ama bu yetmiyor: tarayıcı, hedef
    localhost olsa bile isteği GÖNDERİYOR (CORS yalnızca yanıtı okumayı
    engelliyor). Uygulama artık kendi penceresinde çalıştığına göre meşru
    yazma istekleri yalnızca oradan gelir.
    """
    assert _yazma_istegi(sunucu, {"Origin": "https://kotu-site.example"}) == 403


def test_capraz_site_isaretli_istek_reddedilir(sunucu):
    """`Sec-Fetch-Site: cross-site` tek başına yeter."""
    assert _yazma_istegi(sunucu, {"Sec-Fetch-Site": "cross-site"}) == 403


def test_kendi_penceremizden_gelen_yazma_gecer(sunucu):
    """Uygulamanın kendi istekleri (aynı kaynak) engellenmiyor."""
    durum = _yazma_istegi(
        sunucu, {"Origin": sunucu, "Sec-Fetch-Site": "same-origin"}
    )

    assert durum == 201  # oluşturuldu


def test_basliksiz_istek_gecer(sunucu):
    """Testler ve komut satırı araçları bu başlıkları göndermiyor."""
    assert _yazma_istegi(sunucu, {}) == 201


def test_gorunum_okumasi_denetimden_etkilenmez(sunucu):
    """Denetim yalnızca YAZMA yollarında; görünüm sorguları eskisi gibi."""
    assert _get(sunucu, "/api/week?date=2026-09-08")["view"] == "week"


# ---------------------------------------------------------------------------
# Izgarada boş saate tıklayarak oluşturma (tarih ve saat belli)
# ---------------------------------------------------------------------------

def test_tiklayarak_olusturma_tam_o_gune_yazar(sunucu):
    """Boş saate tıklama ayrıştırma YAPMADAN verilen güne ve saate yazar.

    Hızlı ekleme kutusu her zaman BUGÜNÜ referans alıyor; ızgarada başka bir
    haftaya bakan kullanıcı oraya etkinlik ekleyemiyordu. Tıklama yolunda gün
    ve dakika zaten belli, metinden tarih çıkarmaya çalışmıyoruz.
    """
    sonuc = _post(
        sunucu,
        "/api/events",
        {"title": "diş hekimi", "date": "2026-09-24", "minutes": 14 * 60},
    )

    assert sonuc["event"]["title"] == "diş hekimi"
    assert sonuc["event"]["startUtc"].startswith("2026-09-24T11:00")  # 14:00 İstanbul
    assert sonuc["event"]["endUtc"].startswith("2026-09-24T12:00"), "varsayılan 1 saat"


def test_tiklayarak_olusturmada_baslik_ayristirilmaz(sunucu):
    """Başlıkta tarih geçse bile etkinlik TIKLANAN güne yazılır.

    Metni ayrıştırsaydık "3 ekim toplantısı" adlı bir etkinlik 3 Ekim'e
    kaçardı; kullanıcı ise 24 Eylül'e tıklamıştı.
    """
    sonuc = _post(
        sunucu,
        "/api/events",
        {"title": "3 ekim toplantısı", "date": "2026-09-24", "minutes": 9 * 60},
    )

    assert sonuc["event"]["title"] == "3 ekim toplantısı"
    assert sonuc["event"]["startUtc"].startswith("2026-09-24")


def test_tiklayarak_olusturmada_bitis_verilebilir(sunucu):
    """Sürükleyerek değil, tıklayarak da uzun etkinlik oluşturulabilsin."""
    sonuc = _post(
        sunucu,
        "/api/events",
        {"title": "atölye", "date": "2026-09-24", "minutes": 600, "endMinutes": 780},
    )

    assert sonuc["event"]["startUtc"].startswith("2026-09-24T07:00")  # 10:00
    assert sonuc["event"]["endUtc"].startswith("2026-09-24T10:00")   # 13:00


def test_tiklayarak_olusturmada_baslik_zorunlu(sunucu):
    """Boş başlıkla "adsız" bir etkinlik oluşmasın."""
    with pytest.raises(urllib.error.HTTPError) as hata:
        _post(sunucu, "/api/events", {"title": "   ", "date": "2026-09-24", "minutes": 600})

    assert hata.value.code == 400


def test_tiklayarak_olusturmada_dakika_gun_icinde_olmali(sunucu):
    """Bozuk bir dakika değeri sessizce başka güne taşmasın."""
    with pytest.raises(urllib.error.HTTPError) as hata:
        _post(sunucu, "/api/events", {"title": "x", "date": "2026-09-24", "minutes": 2000})

    assert hata.value.code == 400


def test_tiklayarak_olusturmada_bitis_baslangictan_sonra_olmali(sunucu):
    """Ters aralık reddedilir."""
    with pytest.raises(urllib.error.HTTPError) as hata:
        _post(
            sunucu,
            "/api/events",
            {"title": "x", "date": "2026-09-24", "minutes": 600, "endMinutes": 500},
        )

    assert hata.value.code == 400


def test_hizli_ekleme_yolu_bozulmadi(sunucu):
    """`text` biçimi eskisi gibi çalışıyor (iki yol aynı uçta)."""
    sonuc = _post(sunucu, "/api/events", {"text": "haftaya salı 14:00 toplantı"})

    assert sonuc["event"]["title"] == "toplantı"
    assert "salı" in sonuc["parsed"]["matched"]


# ---------------------------------------------------------------------------
# Silme: tekrarsız etkinlikte GERÇEKTEN silme
# ---------------------------------------------------------------------------

def test_tekrarsiz_etkinlik_silinince_aramadan_ve_yedekten_de_gidiyor(sunucu):
    """"Sil" dediğimiz şey gerçekten silinmeli.

    Eskiden tekrarsız etkinlikte de "iptal edildi" override'ı yazılıyordu:
    etkinlik ızgaradan kayboluyor ama aramada çıkmaya ve `.ics` dışa
    aktarmasına ETKİN olarak yazılmaya devam ediyordu. Kullanıcı sildiğini
    sanıyor, yedeğinden geri yüklediğinde etkinlik diriliyordu.
    """
    olusan = _post(
        sunucu, "/api/events",
        {"title": "tek seferlik toplantı", "date": "2026-09-24", "minutes": 600},
    )["event"]

    _post(
        sunucu,
        "/api/occurrences/cancel",
        {"eventId": olusan["id"], "originalStartUtc": olusan["startUtc"]},
    )

    ara = urllib.parse.quote("tek seferlik")
    assert _get(sunucu, f"/api/search?q={ara}")["results"] == []
    with urllib.request.urlopen(sunucu + "/api/export") as yanit:
        assert "tek seferlik toplantı" not in yanit.read().decode("utf-8")


def test_tekrarli_seride_tek_ornek_iptali_seriyi_BIRAKIYOR(sunucu):
    """Tekrarlıda davranış değişmedi: yalnız o örnek gider, seri kalır.

    Bu testin kırmızıya dönmesi, tekrarsız düzeltmesinin seriyi de silmeye
    başladığı anlamına gelir -- dönem boyu ders programını götüren hata.
    """
    hafta = _get(sunucu, "/api/week?date=2026-09-07")
    ornek = next(o for g in hafta["days"] for o in g["timed"] if o["title"] == "Algoritma")

    _post(
        sunucu,
        "/api/occurrences/cancel",
        {"eventId": ornek["eventId"], "originalStartUtc": ornek["originalStartUtc"]},
    )

    # O hafta gitti...
    bu_hafta = _get(sunucu, "/api/week?date=2026-09-07")
    assert not [o for g in bu_hafta["days"] for o in g["timed"] if o["title"] == "Algoritma"]
    # ...ama seri duruyor.
    sonraki = _get(sunucu, "/api/week?date=2026-09-14")
    assert [o for g in sonraki["days"] for o in g["timed"] if o["title"] == "Algoritma"]


def test_yukte_recurring_bayragi_var(sunucu):
    """Arayüz "bu örnek / tüm seri" ayrımını bu bayrakla gösteriyor."""
    _post(sunucu, "/api/events", {"title": "tekil", "date": "2026-09-24", "minutes": 540})
    hafta = _get(sunucu, "/api/week?date=2026-09-07")
    tekrarli = next(o for g in hafta["days"] for o in g["timed"] if o["title"] == "Algoritma")
    eylul24 = _get(sunucu, "/api/week?date=2026-09-24")
    tekil = next(o for g in eylul24["days"] for o in g["timed"] if o["title"] == "tekil")

    assert tekrarli["recurring"] is True
    assert tekil["recurring"] is False


# ---------------------------------------------------------------------------
# Tekrarlı etkinlik oluşturma
# ---------------------------------------------------------------------------

def test_tiklayarak_haftalik_seri_olusturma(sunucu):
    """Izgaraya tıklayıp "her hafta" seçmek gerçek bir seri kuruyor."""
    sonuc = _post(
        sunucu,
        "/api/events",
        {"title": "yoga", "date": "2026-09-16", "minutes": 1080, "tekrar": "haftalik"},
    )

    assert sonuc["event"]["recurring"] is True
    # Üç hafta sonra da orada mı
    ileri = _get(sunucu, "/api/week?date=2026-10-07")
    assert [o for g in ileri["days"] for o in g["timed"] if o["title"] == "yoga"]


def test_metinden_tekrarli_etkinlik(sunucu):
    """"her salı 10:00 ders" hızlı ekleme kutusundan da seri kuruyor."""
    sonuc = _post(sunucu, "/api/events", {"text": "her salı 10:00 ders"})

    assert sonuc["event"]["recurring"] is True
    assert sonuc["event"]["title"] == "ders"


def test_bilinmeyen_tekrar_reddedilir(sunucu):
    """Tanınmayan tekrar sessizce "tekrarsız"a düşmemeli.

    Sessizce tek seferlik olan bir ders programı, hiç oluşturulmamış olandan
    kötüdür: kullanıcı kurduğunu sanır.
    """
    with pytest.raises(urllib.error.HTTPError) as hata:
        _post(
            sunucu,
            "/api/events",
            {"title": "x", "date": "2026-09-16", "minutes": 600, "tekrar": "her yarım saat"},
        )

    assert hata.value.code == 400
