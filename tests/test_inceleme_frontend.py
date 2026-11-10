"""Kod incelemesi ön yüz bulguları (11-18) için regresyon testleri.

`ui/presenter.py` testi HTTP/tarayıcısız çalışır. Geri kalanı gerçek Chromium
ister (Playwright, `[test-ui]` grubu): kurulu değilse o testler atlanır.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from core import Event
from store import Repo, new_uid
from tests.helpers import IST, ist
from ui.presenter import week_payload

# ---------------------------------------------------------------------------
# Bulgu 13: presenter `clippedStart`
# ---------------------------------------------------------------------------

def test_clipped_start_yalniz_baslangici_kirpilan_parcada_dogru():
    """Gece yarısını aşan etkinlikte yalnız ikinci gün parçası clippedStart olur."""
    with Repo.open(":memory:") as repo:
        takvim = repo.add_calendar("Ders", "#e0524a")
        repo.add_event(Event(
            id=None, uid=new_uid(), calendar_id=takvim.id, title="Nöbet",
            start_utc=ist(2024, 5, 6, 22, 0), end_utc=ist(2024, 5, 7, 2, 0), tzid=IST,
        ))
        payload = week_payload(repo, date(2024, 5, 6), IST)
    gun = {g["date"]: g for g in payload["days"]}
    assert gun["2024-05-06"]["timed"][0]["clippedStart"] is False
    assert gun["2024-05-07"]["timed"][0]["clippedStart"] is True


# ---------------------------------------------------------------------------
# Tarayıcı testleri
# ---------------------------------------------------------------------------

pytest.importorskip("pytest_playwright")

from ui.server import make_server


@pytest.fixture
def sunucu_repo():
    """(url, repo): testin kendi etkinliğini doğrudan DB'ye yazabilmesi için."""
    with Repo.open(":memory:", check_same_thread=False) as repo:
        repo.add_calendar("Kişisel", "#3f7cf0")
        httpd = make_server(repo, IST, host="127.0.0.1", port=0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{httpd.server_address[1]}", repo
        finally:
            httpd.shutdown()
            httpd.server_close()


def _bugun():
    return datetime.now(ZoneInfo(IST))


def _etkinlik(repo, baslik, bas, bit, *, tum_gun=False):
    takvim = repo.list_calendars()[0]
    repo.add_event(Event(
        id=None, uid=new_uid(), calendar_id=takvim.id, title=baslik,
        start_utc=bas, end_utc=bit, tzid=IST, all_day=tum_gun,
    ))


def _bugun_etkinligi(repo, baslik="Deneme", saat=12):
    b = _bugun()
    _etkinlik(repo, baslik, ist(b.year, b.month, b.day, saat, 0), ist(b.year, b.month, b.day, saat + 1, 0))


def _blok_ac(page, url, baslik="Deneme"):
    page.goto(url)
    page.wait_for_selector(f".blok:has-text('{baslik}')")
    page.click(f".blok:has-text('{baslik}')")
    page.wait_for_selector("#panel:not([hidden])")


# -- Bulgu 11/12: modalda Enter düğmenin kendi eylemini yapar -----------------

def test_modalda_iptal_dugmesinde_enter_onay_vermez(page, sunucu_repo):
    page.goto(sunucu_repo[0])
    page.wait_for_selector("#hizli-girdi")
    page.evaluate("window.__s = 'bekliyor'; onayla('Sil?', 'm', 'Sil', true).then((v) => { window.__s = v; })")
    page.focus("#modal-iptal")
    page.keyboard.press("Enter")
    page.wait_for_function("window.__s !== 'bekliyor'")
    assert page.evaluate("window.__s") is False


def test_sor_kutusunda_iptalde_enter_null_doner(page, sunucu_repo):
    page.goto(sunucu_repo[0])
    page.wait_for_selector("#hizli-girdi")
    page.evaluate("window.__s = 'bekliyor'; sor('Ad?', 'm', 'yazilan').then((v) => { window.__s = v; })")
    page.focus("#modal-iptal")
    page.keyboard.press("Enter")
    page.wait_for_function("window.__s !== 'bekliyor'")
    assert page.evaluate("window.__s") is None


def test_modal_govdesindeki_dugmede_enter_o_dugmeyi_calistirir(page, sunucu_repo):
    page.goto(sunucu_repo[0])
    page.wait_for_selector("#hizli-girdi")
    page.evaluate(
        """window.__s = 'bekliyor';
        modalAc({ baslik: 'x', iptalDegeri: null, oku: () => 'oku',
          kur: (g, bitir) => {
            const d = document.createElement('button'); d.id = 'govde-dugme';
            d.onclick = () => bitir('dugme'); g.appendChild(d); return d;
          } }).then((v) => { window.__s = v; })"""
    )
    page.keyboard.press("Enter")  # ilk odak gövde düğmesinde
    page.wait_for_function("window.__s !== 'bekliyor'")
    assert page.evaluate("window.__s") == "dugme"


# -- Bulgu 17: yeniden girişli modalAc ----------------------------------------

def test_modal_cift_acilinca_ilki_iptal_edilir_dinleyici_sizmaz(page, sunucu_repo):
    page.goto(sunucu_repo[0])
    page.wait_for_selector("#hizli-girdi")
    page.evaluate(
        """window.__r = [];
        sor('bir', 'm').then((v) => window.__r.push(['1', v]));
        sor('iki', 'm').then((v) => window.__r.push(['2', v]));"""
    )
    page.keyboard.press("Escape")
    page.wait_for_function("window.__r.length === 2")
    page.keyboard.press("Escape")  # sızan dinleyici olsaydı ikinci kez tetiklenirdi
    page.wait_for_timeout(100)
    assert page.evaluate("window.__r") == [["1", None], ["2", None]]
    assert page.evaluate("document.getElementById('perde').hidden") is True
    assert page.evaluate("modalAcik()") is False


# -- Bulgu 15/16: genel kısayollar --------------------------------------------

def test_panel_kapat_dugmesinde_enter_duzenleme_acmaz(page, sunucu_repo):
    url, repo = sunucu_repo
    _bugun_etkinligi(repo)
    _blok_ac(page, url)
    page.focus("#panel-kapat")
    page.keyboard.press("Enter")
    page.wait_for_selector("#panel", state="hidden")
    assert page.evaluate("document.getElementById('perde').hidden") is True


def test_secili_metinde_ctrl_c_uygulama_panosuna_almaz(page, sunucu_repo):
    url, repo = sunucu_repo
    _bugun_etkinligi(repo)
    _blok_ac(page, url)
    page.evaluate(
        """const r = document.createRange();
        r.selectNodeContents(document.getElementById('panel-icerik'));
        const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);"""
    )
    page.keyboard.press("Control+c")
    page.keyboard.press("Control+x")
    page.wait_for_timeout(100)
    assert page.evaluate("durum.pano") is None
    assert page.evaluate("document.getElementById('perde').hidden") is True  # kes() silme sormadı


# -- Bulgu 13: gece yarısını aşan etkinlik ------------------------------------

def test_kirpilmis_blokta_boyut_tutamagi_yok(page, sunucu_repo):
    url, repo = sunucu_repo
    b = _bugun()
    s = b + timedelta(days=1)
    _etkinlik(repo, "Nöbet", ist(b.year, b.month, b.day, 22, 0), ist(s.year, s.month, s.day, 2, 0))
    page.goto(url)
    page.wait_for_selector(".blok:has-text('Nöbet')")
    assert page.locator(".blok:has-text('Nöbet') .boyut-tutamagi").count() == 0


def test_baslangici_kirpilmis_parca_surukleme_baslatmaz(page, sunucu_repo):
    page.goto(sunucu_repo[0])
    page.wait_for_selector("#hizli-girdi")
    aktif = page.evaluate(
        """(() => {
          surukleBasla({ button: 0, clientX: 0, clientY: 0, preventDefault() {} },
            document.body, { clippedStart: true, startMin: 0, endMin: 120, allDay: false }, { date: '2026-01-01' });
          return surukleme.aktif;
        })()"""
    )
    assert aktif is False


# -- Bulgu 14: 24 saati aşan etkinliğin süresi --------------------------------

_UZUN_OCC = (
    "{ eventId: 1, originalStartUtc: '2026-11-09T07:00:00+00:00', startUtc: '2026-11-09T07:00:00+00:00', "
    "endUtc: '2026-11-11T09:00:00+00:00', tzid: 'Europe/Istanbul', title: 'Uzun', allDay: false, "
    "recurring: false, calendarId: 1, reminders: [] }"
)


def _istegi_yakala(page):
    page.evaluate(
        """window.__g = [];
        istek = async (y, o) => { window.__g.push([y, o && o.body ? JSON.parse(o.body) : null]); return { event: { id: 9 } }; };"""
    )


def test_duzenlemede_50_saatlik_etkinlik_suresi_korunur(page, sunucu_repo):
    page.goto(sunucu_repo[0])
    page.wait_for_selector("#hizli-girdi")
    _istegi_yakala(page)
    page.evaluate(f"etkinligiDuzenle({_UZUN_OCC})")
    page.fill("#modal-alanlar input[type=date]", "2026-11-10")
    page.click("#modal-tamam")
    page.wait_for_function("window.__g.length >= 1")
    govde = next(g[1] for g in page.evaluate("window.__g") if g[0] == "/api/occurrences/move")
    assert govde["newEndMinutes"] - govde["newMinutes"] == 50 * 60


def test_silmeyi_geri_alma_50_saatlik_etkinligin_suresini_korur(page, sunucu_repo):
    page.goto(sunucu_repo[0])
    page.wait_for_selector("#hizli-girdi")
    _istegi_yakala(page)
    page.evaluate(f"silmeyiGeriAl({_UZUN_OCC})")
    page.wait_for_function("window.__g.length >= 1")
    govde = next(g[1] for g in page.evaluate("window.__g") if g[0] == "/api/events")
    assert govde["endMinutes"] - govde["minutes"] == 50 * 60


# -- Bulgu 18: tüm gün bloğu aynı güne bırakılınca istek yok ------------------

def test_tumgun_ayni_gune_birakinca_istek_gitmez(page, sunucu_repo):
    url, repo = sunucu_repo
    b = _bugun()
    gun = ist(b.year, b.month, b.day)
    _etkinlik(repo, "Doğum günü", gun, gun + timedelta(days=1), tum_gun=True)
    istekler = []
    page.on("request", lambda r: istekler.append(r.url) if "/api/occurrences/move" in r.url else None)
    page.goto(url)
    page.wait_for_selector(".tumgun-blok")
    kutu = page.locator(".tumgun-blok").first.bounding_box()
    x, y = kutu["x"] + 10, kutu["y"] + kutu["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 4, y)
    page.mouse.move(x + 8, y)
    page.mouse.up()
    page.wait_for_timeout(300)
    assert istekler == []
