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

import json
import threading
import urllib.request

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


def test_silme_ve_geri_alma(page, sunucu):
    """Panelden sil, bildirimdeki 'Geri al'a bas: etkinlik ızgaraya geri döner.

    Silme ve geri alma AYRI davranışlar -- biri diğeri bozulmadan da
    bozulabilir (örn. `silmeyiGeriAl` yanlış gövde gönderirse blok geri
    gelmez ama silme yine "çalışıyormuş" gibi görünür).
    """
    page.goto(sunucu)
    page.wait_for_selector("#hizli-girdi")

    page.fill("#hizli-girdi", "bugün 14:00 silme testi")
    page.click("#hizli-form button[type=submit]")
    page.wait_for_selector(".blok:has-text('silme testi')")

    page.click(".blok:has-text('silme testi')")
    page.wait_for_selector("#panel:not([hidden])")
    page.click("#panel-islemler button:has-text('Sil')")
    page.wait_for_selector("#modal-baslik:has-text('Etkinliği sil')")
    page.click("#modal-tamam")

    # Silme gerçekten gerçekleşti: blok ızgaradan gitti.
    page.wait_for_selector(".blok:has-text('silme testi')", state="hidden")

    page.wait_for_selector("#bildirim button:has-text('Geri al')")
    assert page.is_visible("#bildirim button:has-text('Geri al')")
    page.click("#bildirim button:has-text('Geri al')")

    # Geri alma gerçekten çalıştı: blok yeniden ızgarada.
    page.wait_for_selector(".blok:has-text('silme testi')")


def test_tekrarli_seride_iki_silme_secenegi_gosterilir(page, sunucu):
    """Tekrarlı etkinlikte panel 'Bu örneği sil' VE 'Seriyi tamamen sil' gösterir.

    Tekrarsızda tek "Sil" düğmesi var (app.js islemleriCiz): tek/seri ayrımı
    kritik, kullanıcı bir dersi bu haftalık iptal etmekle dönem boyunca
    silmeyi karıştırmamalı.
    """
    page.goto(sunucu)
    page.wait_for_selector("#hizli-girdi")

    # "her gün": tarih ifadesi yok, başlangıç bugüne düşüyor (core/quickadd.py
    # `hedef_gun = gun or bugun`) -- testin hangi haftanın günü koştuğuna
    # bağlı kalmaması için "her salı" yerine bilerek bu seçildi.
    page.fill("#hizli-girdi", "her gün 10:00 ders")
    page.click("#hizli-form button[type=submit]")
    page.wait_for_selector(".blok:has-text('ders')")

    # Günlük seri bu haftanın birden çok gününde blok üretebilir; hangisi
    # olursa olsun aynı seriye ait, ilkine tıklamak yeterli.
    page.locator(".blok:has-text('ders')").first.click()
    page.wait_for_selector("#panel:not([hidden])")

    page.wait_for_selector("#panel-islemler button:has-text('Bu örneği sil')")
    assert page.is_visible("#panel-islemler button:has-text('Bu örneği sil')")
    assert page.is_visible("#panel-islemler button:has-text('Seriyi tamamen sil')")


def test_arama_olusturulan_etkinligi_bulur(page, sunucu):
    """Üst şeritteki arama kutusu, yeni oluşturulan etkinliği başlığıyla arama listesinde gösterir."""
    page.goto(sunucu)
    page.wait_for_selector("#hizli-girdi")

    page.fill("#hizli-girdi", "bugün 15:00 arama testi")
    page.click("#hizli-form button[type=submit]")
    page.wait_for_selector(".blok:has-text('arama testi')")

    page.click("#arama-ac-dugme")
    page.wait_for_selector("#arama-serit:not([hidden])")
    page.fill("#arama", "arama testi")

    # 220ms debounce + gerçek /api/search isteği (bkz. app.js aramaYap).
    page.wait_for_selector("#arama-listesi .arama-satir:has-text('arama testi')")
    assert "arama testi" in page.inner_text("#arama-listesi")


def test_panel_etkinlik_detaylarini_gosterir(page, sunucu):
    """Etkinliğe tıklayınca sağ panel açılır; başlık ve saat bilgisi GERÇEKTEN o etkinliğe ait."""
    page.goto(sunucu)
    page.wait_for_selector("#hizli-girdi")

    page.fill("#hizli-girdi", "bugün 16:00 panel testi")
    page.click("#hizli-form button[type=submit]")
    page.wait_for_selector(".blok:has-text('panel testi')")

    page.click(".blok:has-text('panel testi')")
    page.wait_for_selector("#panel:not([hidden])")

    # Sabit bir metin değil, bu etkinliğe özgü başlık VE saat -- yanlış
    # etkinliğin veya boş panelin de "geçer" olmasını önlüyor.
    icerik = page.inner_text("#panel-icerik")
    assert "panel testi" in icerik
    assert "Zaman" in icerik
    assert "16:00" in icerik


def test_ay_blogu_klavyeyle_acilir(page, sunucu):
    """Ay görünümündeki etkinlik <button>: Tab/odak + Enter panel açmalı.

    Eskiden `<div onclick>`'ti, yalnızca fareyle tıklanabiliyordu -- klavye ya
    da ekran okuyucu kullanan biri ay görünümünde HİÇBİR etkinliği açamıyordu.
    Aynı düzeltmenin bir parçası: dar hücrede kırpılan başlık artık `title`
    (araç ipucu) olarak da yazılıyor.
    """
    page.goto(sunucu)
    page.wait_for_selector("#hizli-girdi")

    page.fill("#hizli-girdi", "bugün 10:00 ay klavye testi")
    page.click("#hizli-form button[type=submit]")
    page.wait_for_selector(".blok:has-text('ay klavye testi')")

    page.click('button[data-gorunum="month"]')
    page.wait_for_selector("#ay-gorunum:not([hidden])")

    blok = page.locator(".ay-blok:has-text('ay klavye testi')")
    blok.wait_for()
    assert "ay klavye testi" in (blok.get_attribute("title") or "")
    blok.focus()
    page.keyboard.press("Enter")

    page.wait_for_selector("#panel:not([hidden])")
    assert "ay klavye testi" in page.inner_text("#panel-icerik")


def test_ay_daha_klavyeyle_gun_listesini_acar(page, sunucu):
    """`AY_MAKS_BLOK`'u (3) aşan günde "+N daha" da <button>: Enter ile açılır.

    Aynı erişilebilirlik düzeltmesinin ikinci parçası -- ayrıca kutunun
    konumu artık tıklama olayının clientX/clientY'si DEĞİL, düğmenin kendi
    `getBoundingClientRect()`'i (bkz. app.js `gunListesiAc`): klavyeyle
    tetiklenen bir `click`'te clientX/clientY 0'dır, eskiden kutuyu ekranın
    sol üst köşesine fırlatırdı.
    """
    page.goto(sunucu)
    page.wait_for_selector("#hizli-girdi")

    for saat in ("08", "09", "10", "11"):
        page.fill("#hizli-girdi", f"bugün {saat}:00 daha testi {saat}")
        page.click("#hizli-form button[type=submit]")
        page.wait_for_selector(f".blok:has-text('daha testi {saat}')")

    page.click('button[data-gorunum="month"]')
    page.wait_for_selector("#ay-gorunum:not([hidden])")

    daha = page.locator(".ay-daha")
    daha.wait_for()
    daha.focus()
    page.keyboard.press("Enter")

    page.wait_for_selector("#gun-listesi")
    icerik = page.inner_text("#gun-listesi")
    for saat in ("08", "09", "10", "11"):
        assert f"daha testi {saat}" in icerik


def test_gun_listesi_satirina_tiklamak_paneli_acar(page, sunucu):
    """Gün listesindeki bir satıra tıklamak panelde DOĞRU etkinliği açmalı.

    Liste satırı da <button>; yanlış etkinliğin (ya da boş panelin) "geçer"
    sayılmaması için birden fazla adayın olduğu bir günde ölçülüyor.
    """
    page.goto(sunucu)
    page.wait_for_selector("#hizli-girdi")

    for saat in ("08", "09", "10", "11"):
        page.fill("#hizli-girdi", f"bugün {saat}:00 liste testi {saat}")
        page.click("#hizli-form button[type=submit]")
        page.wait_for_selector(f".blok:has-text('liste testi {saat}')")

    page.click('button[data-gorunum="month"]')
    page.wait_for_selector("#ay-gorunum:not([hidden])")
    page.click(".ay-daha")
    page.wait_for_selector("#gun-listesi")

    page.click(".gl-satir:has-text('liste testi 08')")
    page.wait_for_selector("#panel:not([hidden])")
    assert "liste testi 08" in page.inner_text("#panel-icerik")


def test_klavye_kisayollari_gorunum_degistirir(page, sunucu):
    """`g`/`h`/`a` tuşları, odak bir yazı kutusunda DEĞİLKEN görünüm değiştirmeli.

    Kısayolların kendisi kadar önemli olan: modal/yazı kutusu kapalıyken bu
    üçü gerçekten gün/hafta/ay ızgaraları arasında geçiş yaptırıyor mu --
    yalnızca tuşa basıp bir şey patlamadığını görmek yetmez.
    """
    page.goto(sunucu)
    page.wait_for_selector("#hizli-girdi")

    # Odağı girdi kutusundan al: yazı kutusundayken kısayollar devre dışı.
    page.click("#baslik")

    page.keyboard.press("a")
    page.wait_for_selector("#ay-gorunum:not([hidden])")
    assert "secili" in page.get_attribute('button[data-gorunum="month"]', "class")

    page.keyboard.press("g")
    page.wait_for_selector("#zaman-gorunum:not([hidden])")
    assert "secili" in page.get_attribute('button[data-gorunum="day"]', "class")

    # "week" da "day" ile aynı #zaman-gorunum kabını kullanıyor (zaten
    # görünür), o yüzden konteynerin görünürlüğünü değil DOĞRUDAN düğmenin
    # "secili" sınıfını bekliyoruz -- yoksa yukle()/ciz() asenkron zincirinin
    # bitmesini beklemeden assert çalışıp yarış koşuluna düşüyor (CI'da
    # görüldü: yerel makinede zamanlama farkıyla gizleniyordu).
    page.keyboard.press("h")
    page.wait_for_selector('button[data-gorunum="week"].secili')
    assert "secili" in page.get_attribute('button[data-gorunum="week"]', "class")


def test_kopyala_yapistir_bos_saate_tiklayinca_calisir(page, sunucu):
    """Ctrl+C ile kopyalanan etkinlik, boş bir saate TIKLAYINCA (Ctrl+V basmadan)
    da yapıştırılmalı -- `izgaraTik`'in "pano doluysa tıklama yapıştırır" akışı
    (AGENTS.md #63).
    """
    page.goto(sunucu)
    page.wait_for_selector("#hizli-girdi")

    page.fill("#hizli-girdi", "bugün 09:00 kopya testi")
    page.click("#hizli-form button[type=submit]")
    page.wait_for_selector(".blok:has-text('kopya testi')")

    page.click(".blok:has-text('kopya testi')")
    page.wait_for_selector("#panel:not([hidden])")

    page.keyboard.press("Control+c")
    page.wait_for_selector("#bildirim:has-text('kopyalandı')")

    # Etkinliğin OLMADIĞI bir gün sütununa tıkla: hangi saate denk gelirse
    # gelsin, pano doluyken her tıklama yapıştırır -- belirli bir saat önemli
    # değil, önemli olan "aynı hafta içinde boş bir sütun".
    page.locator(".gun-sutun:not(:has(.blok))").first.click()

    page.wait_for_selector("#bildirim:has-text('yapıştırıldı')")
    # Pano tek seferlik: bir orijinal + bir yapıştırılan kopya, üçüncüsü yok.
    assert page.locator(".blok:has-text('kopya testi')").count() == 2


def test_arama_escape_ile_kapanir(page, sunucu):
    """Arama kutusunda Escape'e basmak şeridi kapatmalı (app.js `#arama` keydown).

    Genel Escape kısayolundan AYRI bir dinleyici: arama şeridi açıkken Escape
    hem paneli/panoyu temizleyen genel kısayolla çakışmamalı hem de arka
    plandaki görünümü değiştirmemeli.
    """
    page.goto(sunucu)
    page.wait_for_selector("#hizli-girdi")

    page.click("#arama-ac-dugme")
    page.wait_for_selector("#arama-serit:not([hidden])")

    page.click("#arama")
    page.keyboard.press("Escape")

    page.wait_for_selector("#arama-serit", state="hidden")


def test_arama_sonucu_klavyeyle_acilir(page, sunucu):
    """Arama listesindeki bir sonuç <button>: Tab/odak + Enter o tarihe götürmeli.

    Eskiden `<li onclick>`'ti, yalnızca fareyle tıklanabiliyordu -- aynı sınıf
    hata ay görünümündeki bloklarda da vardı (bkz. test_ay_blogu_klavyeyle_acilir),
    burada arama sonuçları için aynı düzeltme: `<li>` yalnızca çerçeve, asıl
    tıklanabilir yüzey içindeki `<button>`.
    """
    page.goto(sunucu)
    page.wait_for_selector("#hizli-girdi")

    page.fill("#hizli-girdi", "haftaya salı 15:00 klavye arama testi")
    page.click("#hizli-form button[type=submit]")
    page.wait_for_selector("#bildirim:has-text('Eklendi')")

    page.click("#arama-ac-dugme")
    page.wait_for_selector("#arama-serit:not([hidden])")
    page.fill("#arama", "klavye arama testi")

    sonuc = page.locator(".arama-satir:has-text('klavye arama testi')")
    sonuc.wait_for()
    sonuc.focus()
    page.keyboard.press("Enter")

    # Sonuca gitmek haftayı değiştirir: bloğun ızgarada GERÇEKTEN göründüğü,
    # yalnızca tıklamanın "patlamadığı" değil, doğrulanıyor.
    page.wait_for_selector(".blok:has-text('klavye arama testi')")


@pytest.fixture
def sunucu_en(tmp_path):
    """Dili `en` olan dosya DB'li sunucu.

    `:memory:` DB'de `ayarlar.json` yok, dil dosyaya yazılamıyor -- o yüzden
    İngilizce ön yüz testi dosya DB'si istiyor. Dil sayfa açılmadan ÖNCE
    API'den yazılıyor; açılış `baslat()` içinde okuyup tek seferde çiziyor.
    """
    from ui.server import make_server as _kur

    db = str(tmp_path / "takvim.db")
    with Repo.open(db, check_same_thread=False) as repo:
        repo.add_calendar("Kişisel", "#3f7cf0")
        httpd = _kur(repo, IST, host="127.0.0.1", port=0, db_yolu=db)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            temel = f"http://127.0.0.1:{httpd.server_address[1]}"
            req = urllib.request.Request(
                temel + "/api/ayarlar", method="POST",
                data=json.dumps({"dil": "en"}).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            with urllib.request.urlopen(req):
                pass
            yield temel
        finally:
            httpd.shutdown()
            httpd.server_close()


def test_dil_en_statik_metinler(page, sunucu_en):
    """Dil `en` iken sabit arayüz metinleri İngilizce çiziliyor."""
    page.goto(sunucu_en)
    page.wait_for_selector("#hizli-girdi")

    assert page.inner_text("#bugun") == "Today"
    assert page.get_attribute("#hizli-girdi", "placeholder") == \
        "Quick add in Turkish: yarın 14:00 diş hekimi"
    # `.kb-metin` CSS ile büyük harfe çevriliyor (`text-transform`), o yüzden
    # küçük harfe indirip karşılaştırıyoruz -- test CSS'i değil DİLİ ölçüyor.
    assert page.inner_text(".kb-metin").lower() == "calendars"
    dugmeler = page.locator(".gorunum-dugme").all_inner_texts()
    assert dugmeler == ["Day", "Week", "Month"]
    assert page.inner_text(".bd-baslik") == "Calendar ready"


def test_dil_en_dinamik_akis(page, sunucu_en):
    """Dil `en` iken bildirim + panel + ayarlar kutusu İngilizce.

    Hızlı ekleme cümlesi hâlâ TÜRKÇE (ayrıştırıcı değişmedi): İngilizce
    arayüzde Türkçe cümleyle etkinlik kurulabildiği de burada kilitleniyor.
    """
    hatalar = []
    page.on("console", lambda m: hatalar.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: hatalar.append(str(e)))

    page.goto(sunucu_en)
    page.wait_for_selector("#hizli-girdi")

    page.fill("#hizli-girdi", "bugün 14:00 english test")
    page.click("#hizli-form button[type=submit]")
    page.wait_for_selector(".blok:has-text('english test')")
    page.wait_for_selector("#bildirim:has-text('Added:')")

    page.locator(".blok:has-text('english test')").first.click()
    page.wait_for_selector("#panel-icerik:has-text('Time')")
    assert "14:00" in page.inner_text("#panel-icerik")

    page.click("#ayarlar")
    page.wait_for_selector("#modal-baslik:has-text('Settings')")
    page.wait_for_selector("#modal-alanlar:has-text('Language')")
    page.click("#modal-iptal")

    assert hatalar == []


def test_ayarlar_select_metin_kutuya_sigiyor(page, sunucu):
    """Açılır kutulardaki metin satır kutusuna sığmalı.

    `select.modal-girdi` sabit 32px yükseklikteydi: 8px padding + 1px kenarlık
    düşünce 13px metne 14px içerik kalıyor, satır kutusu (~16px) taşıyordu --
    çıkıntılı harfler (Q, g, p) kutu sınırına dayanıyordu. `scrollWidth`
    `select`te kör olduğu için içerik/satır yükseklikleri karşılaştırılıyor.
    """
    page.goto(sunucu)
    page.wait_for_selector("#hizli-girdi")

    page.click("#ayarlar")
    page.wait_for_selector("#perde:not([hidden])")

    sigmayan = page.evaluate("""() => {
      const kotu = [];
      document.querySelectorAll("#modal-alanlar select").forEach((s) => {
        const cs = getComputedStyle(s);
        let satir = parseFloat(cs.lineHeight);
        if (Number.isNaN(satir)) satir = parseFloat(cs.fontSize) * 1.2;
        const icerik = s.clientHeight
          - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom)
          - parseFloat(cs.borderTopWidth) - parseFloat(cs.borderBottomWidth);
        if (satir > icerik + 0.5) kotu.push([s.value, satir, icerik]);
      });
      return kotu;
    }""")
    assert sigmayan == []
