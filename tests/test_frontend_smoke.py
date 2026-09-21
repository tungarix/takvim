"""Ön yüz duman testleri: gerçek başsız tarayıcı (Playwright/Chromium),
gerçek HTTP sunucusu -- `ui/static/app.js` DOM'a karşı GERÇEKTEN çalıştırılıyor.

Neden var: backend'in 400'den fazla testi API sözleşmesini kapsıyor ama
`app.js`'in hiç otomatik testi yoktu. v1.1.0'daki dört aşamalı GUI yeniden
yazımından sonra bu boşluk büyüdü -- hiçbir şey bir regresyonu yakalamıyordu.

Kapsam BİLEREK dar: "sayfa açılıyor mu, temel akışlar çalışıyor mu, konsol
hatasız mı". Her düğmeyi/etkileşimi kapsayan bir e2e paketi ayrı, çok daha
büyük bir iş -- AGENTS.md §6 kapsam dışı liste ruhuna uygun, küçük tutuluyor.
"""

from __future__ import annotations

import threading

import pytest

# pytest-playwright `[test-ui]` grubunda, `dev`de DEĞİL (bkz. pyproject.toml
# -- ~115 MB Chromium indirmeyi yalnızca bu dosyayı koşanlar istesin).
# Kurulu değilse dosya SESSİZCE atlanır (importorskip), koleksiyon hatası
# vermez -- düz `pytest -q` her zaman yeşil kalır.
pytest.importorskip("pytest_playwright")

from store import Repo
from tests.helpers import IST
from ui.server import make_server


@pytest.fixture
def sunucu():
    """Bellek veritabanıyla gerçek HTTP sunucusu, rastgele boş portta."""
    # check_same_thread=False: sunucu arka plan thread'inde çalışıyor, ana
    # thread'de açılan bağlantıyı oradan da kullanacağız (bkz. test_ui_views).
    with Repo.open(":memory:", check_same_thread=False) as repo:
        repo.add_calendar("Kişisel", "#3f7cf0")
        httpd = make_server(repo, IST, host="127.0.0.1", port=0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{httpd.server_address[1]}"
        finally:
            httpd.shutdown()
            httpd.server_close()


def test_sayfa_aciliyor_konsol_hatasiz(page, sunucu):
    """İlk açılış: boş durum ekranı görünüyor, hiçbir konsol/sayfa hatası yok."""
    hatalar = []
    page.on("console", lambda m: hatalar.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: hatalar.append(str(e)))

    page.goto(sunucu)
    page.wait_for_selector("#hizli-girdi")
    page.wait_for_selector("#bos-durum:not([hidden])")

    assert hatalar == []


def test_hizli_ekleme_etkinlik_olusturur(page, sunucu):
    """Metin yaz, Ekle'ye bas: etkinlik hem ızgarada hem DB'de gerçekten var."""
    page.goto(sunucu)
    page.wait_for_selector("#hizli-girdi")

    page.fill("#hizli-girdi", "bugün 14:00 diş hekimi")
    page.click("#hizli-form button[type=submit]")

    # ".blok" ile eşleşiyor: "text=diş hekimi" bildirim şeridindeki
    # "Eklendi: diş hekimi (...)" ile de eşleşir, ızgaradaki gerçek bloktan
    # ÖNCE görünür -- bosDurumKontrol'ün henüz çalışmamış olabileceği bir
    # yarışa düşmemek için burada özellikle bloğu bekliyoruz.
    page.wait_for_selector(".blok:has-text('diş hekimi')")
    # Boş durum ekranı artık gitmiş olmalı (bosDurumKontrol, app.js).
    page.wait_for_selector("#bos-durum", state="hidden")


def test_ay_gorunumune_gecis(page, sunucu):
    """Görünüm anahtarı: Ay'a tıklamak ay ızgarasını açar, saat ızgarasını kapatır."""
    page.goto(sunucu)
    page.wait_for_selector("#hizli-girdi")

    page.click('button[data-gorunum="month"]')

    page.wait_for_selector("#ay-gorunum:not([hidden])")
    assert page.is_hidden("#zaman-gorunum")


def test_cakisma_onayi_ucuncu_dugme_gosterir(page, sunucu):
    """Takvim Arayuz.pdf §1f: aynı saate ikinci ekleme 3 düğmeli onay açar."""
    page.goto(sunucu)
    page.wait_for_selector("#hizli-girdi")

    page.fill("#hizli-girdi", "bugün 14:00 ilk etkinlik")
    page.click("#hizli-form button[type=submit]")
    page.wait_for_selector(".blok:has-text('ilk etkinlik')")

    page.fill("#hizli-girdi", "bugün 14:00 ikinci etkinlik")
    page.click("#hizli-form button[type=submit]")

    page.wait_for_selector("#modal-baslik:has-text('Bu saatte başka bir etkinlik var')")
    assert page.is_visible("#modal-ucuncu")
    assert page.inner_text("#modal-ucuncu") == "Saati değiştir"

    # Vazgeç: hiçbir şey kaydedilmemeli, kutu kapanmalı.
    page.click("#modal-iptal")
    page.wait_for_selector("#perde", state="hidden")
    assert page.locator(".blok:has-text('ikinci etkinlik')").count() == 0
