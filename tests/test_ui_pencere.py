"""Masaüstü penceresinin GUI'siz parçaları.

Pencerenin kendisi (WebView2) test edilemiyor: ekran ister ve `webview.start()`
ana thread'i kilitler. Bu yüzden karar veren mantık -- geometri okuma/yazma ve
ekran sınırına çekme -- saf fonksiyonlar hâlinde ayrı duruyor ve burada
ölçülüyor. Test edilen şey şu: kullanıcının penceresi bir daha AÇILDIĞINDA
ekranda ve kullanılabilir boyutta olacak mı.
"""

from __future__ import annotations

import json

import pytest

from ui.pencere import (
    EN_KUCUK,
    VARSAYILAN,
    Geometri,
    ekrana_sigdir,
    geometri_dosyasi,
    geometri_oku,
    geometri_yaz,
    sanal_ekran,
    webview2_surumu,
)

# Testlerde kullanılan sahte ekran: 1920x1080, tek monitör, sol üst köşe 0,0.
EKRAN = (0, 0, 1920, 1080)


def test_geometri_yazilip_geri_okunur(tmp_path):
    """Yazılan değerler aynen geri geliyor."""
    yol = tmp_path / "pencere.json"
    g = Geometri(1200, 800, 40, 60, buyutulmus=False)

    assert geometri_yaz(yol, g) is True
    assert geometri_oku(yol) == g


def test_buyutulmus_bayragi_korunur(tmp_path):
    """Tam ekran bırakılan pencere tam ekran açılsın."""
    yol = tmp_path / "pencere.json"
    geometri_yaz(yol, Geometri(1200, 800, 0, 0, buyutulmus=True))

    assert geometri_oku(yol).buyutulmus is True


def test_olmayan_dosya_none_dondurur(tmp_path):
    """İlk açılışta kayıt yok; varsayılana düşmeli."""
    assert geometri_oku(tmp_path / "yok.json") is None


def test_bozuk_dosya_uygulamayi_durdurmaz(tmp_path):
    """Yarım yazılmış JSON yüzünden uygulama açılmamazlık etmesin."""
    yol = tmp_path / "pencere.json"
    yol.write_text("{bu json deg", encoding="utf-8")

    assert geometri_oku(yol) is None


def test_eksik_alanli_dosya_none_dondurur(tmp_path):
    """Elle düzenlenmiş ya da eski sürümden kalan dosya reddedilir."""
    yol = tmp_path / "pencere.json"
    yol.write_text(json.dumps({"genislik": 1000}), encoding="utf-8")

    assert geometri_oku(yol) is None


def test_sifir_boyut_reddedilir():
    """Bozuk kayıt sessizce kabul edilip görünmez pencere açılmasın."""
    with pytest.raises(ValueError):
        Geometri(0, 800)


def test_gecerli_konum_oldugu_gibi_kalir():
    """Ekran içindeki pencereye dokunulmuyor."""
    g = Geometri(1200, 800, 100, 100)

    assert ekrana_sigdir(g, EKRAN) == g


def test_ekran_disindaki_konum_dusurulur():
    """İkinci monitör çıkarılınca pencere görünmeyen koordinatta açılmasın.

    Konum düşürülüyor (None), boyut korunuyor: işletim sistemi pencereyi
    ortalıyor ve kullanıcı penceresini geri buluyor.
    """
    g = Geometri(1200, 800, 3000, 200)  # artık var olmayan ikinci monitör
    sonuc = ekrana_sigdir(g, EKRAN)

    assert (sonuc.x, sonuc.y) == (None, None)
    assert (sonuc.genislik, sonuc.yukseklik) == (1200, 800)


def test_baslik_cubugu_ekranin_ustunde_kalamaz():
    """Negatif y penceresi sürüklenemez hâle getirir; konum düşürülür."""
    sonuc = ekrana_sigdir(Geometri(1200, 800, 100, -300), EKRAN)

    assert (sonuc.x, sonuc.y) == (None, None)


def test_kenardan_azicik_gorunen_pencere_kabul_edilmez():
    """Yalnızca birkaç piksel içeride kalan pencere de "kayıp" sayılır."""
    # 1920 genişlikte ekranda x=1900: sağdan yalnızca 20 px görünür.
    sonuc = ekrana_sigdir(Geometri(1200, 800, 1900, 100), EKRAN)

    assert sonuc.x is None


def test_kucuk_boyut_en_kucuge_cekilir():
    """Izgaranın üst üste bindiği boyutlarda açılmayı engelle."""
    sonuc = ekrana_sigdir(Geometri(200, 150), EKRAN)

    assert (sonuc.genislik, sonuc.yukseklik) == EN_KUCUK


def test_ekrandan_buyuk_pencere_kirpilir():
    """Çözünürlük düşmüşse pencere ekrana sığdırılır."""
    sonuc = ekrana_sigdir(Geometri(2400, 1600), (0, 0, 1366, 768))

    assert (sonuc.genislik, sonuc.yukseklik) == (1366, 768)


def test_ekran_sinirlari_okunamazsa_konum_korunur():
    """Win32'ye ulaşılamayan ortamda kayıt olduğu gibi kullanılır."""
    g = Geometri(1200, 800, 100, 100)

    assert ekrana_sigdir(g, None) == g


def test_sol_ust_kosesi_negatif_sanal_ekran():
    """Sol taraftaki ikinci monitör negatif koordinatlı olur; geçerlidir.

    Windows sanal ekranda birincil monitörün solundaki monitör eksi x ile
    gösteriliyor; bu konumu "ekran dışı" sayarsak çift monitör kullanan
    kullanıcının penceresi her açılışta birincil ekrana zıplar.
    """
    sinir = (-1920, 0, 3840, 1080)  # solda ikinci bir 1920'lik monitör
    g = Geometri(1200, 800, -1800, 50)

    assert ekrana_sigdir(g, sinir) == g


def test_varsayilan_geometri_en_kucukten_buyuk():
    """Varsayılan boyut kendi alt sınırımızı geçmiş olmalı."""
    assert VARSAYILAN.genislik >= EN_KUCUK[0]
    assert VARSAYILAN.yukseklik >= EN_KUCUK[1]


def test_geometri_dosyasi_veri_dizininde(tmp_path):
    """Pencere kaydı veritabanının yanında duruyor."""
    assert geometri_dosyasi(tmp_path).parent == tmp_path


def test_sanal_ekran_ya_dortlu_ya_none():
    """Gerçek ortamda çağrılabilir olduğunu doğrular (sözleşme testi)."""
    sonuc = sanal_ekran()

    assert sonuc is None or (len(sonuc) == 4 and sonuc[2] > 0 and sonuc[3] > 0)


def test_webview2_surumu_metin_ya_none():
    """Kurulu değilse None, kuruluysa sürüm metni döner."""
    sonuc = webview2_surumu()

    assert sonuc is None or isinstance(sonuc, str)


def test_olu_alandaki_konum_reddedilir():
    """Sanal ekran dikdörtgeninin içi ama hiçbir monitörün üstü değil.

    İki monitör dikdörtgen dizilmediğinde (üstte kaydırılmış ikinci ekran)
    sanal ekranın sınırlayıcı kutusu BOŞ alan içeriyor. Yalnızca sınıra bakmak
    o boşluktaki konumu geçerli sayar ve pencere hiçbir ekranda görünmez.
    """
    sinir = (0, -1080, 3840, 2160)  # sağ üstte ikinci monitör
    sol_ustte_monitor_yok = lambda x, y: not (x < 1920 and y < 0)

    sonuc = ekrana_sigdir(Geometri(1180, 760, 200, -900), sinir, sol_ustte_monitor_yok)

    assert (sonuc.x, sonuc.y) == (None, None)


def test_monitor_varsa_konum_korunur():
    """Sonda "evet" diyorsa kayıtlı konum aynen kullanılır."""
    sinir = (0, -1080, 3840, 2160)
    g = Geometri(1180, 760, 2000, -900)

    assert ekrana_sigdir(g, sinir, lambda x, y: True) == g


def test_monitorde_mi_gercek_ortamda_calisir():
    """Win32 sondası çağrılabilir ve mantıklı cevap veriyor."""
    from ui.pencere import monitorde_mi

    # Birincil ekranın sol üst köşesi her kurulumda bir monitöre düşer.
    assert monitorde_mi(10, 10) is True


def test_dpi_farkindaligi_gercek_ortamda_calisir():
    """Süreç DPI farkındalığı Windows'ta yalnızca BİR KEZ ayarlanabilir;
    ikinci çağrı da çökmeden mantıklı bir cevap vermeli (zaten ayarlı
    durumunu sınar)."""
    from ui.pencere import dpi_farkindaligini_ac

    assert isinstance(dpi_farkindaligini_ac(), bool)
    assert isinstance(dpi_farkindaligini_ac(), bool)


def test_bom_ile_yazilmis_dosya_okunur(tmp_path):
    """Windows araçları dosyanın başına BOM koyuyor; kayıt kaybolmasın.

    PowerShell'in `Out-File -Encoding utf8`ı ve Not Defteri BOM yazıyor.
    Düz `utf-8` ile okurken `json.loads` patlıyor ve pencere her açılışta
    varsayılana dönüyordu -- hata mesajı da yok, sessizce.
    """
    yol = tmp_path / "pencere.json"
    yol.write_bytes(
        b"\xef\xbb\xbf"
        + json.dumps({"genislik": 1002, "yukseklik": 648, "x": 140, "y": 96}).encode("utf-8")
    )

    okunan = geometri_oku(yol)

    assert okunan is not None
    assert (okunan.genislik, okunan.yukseklik, okunan.x, okunan.y) == (1002, 648, 140, 96)
