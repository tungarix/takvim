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
