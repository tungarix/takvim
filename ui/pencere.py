"""Masaüstü penceresi — Takvim kendi penceresinde açılır, tarayıcıda değil.

Arayüz HTML/CSS/JS olarak yazıldı (blueprint §5: zaman ızgarası ve çakışma
yerleşimi CSS'in doğal işi). Ama son kullanıcı için "tarayıcıda açılan bir
sekme" ile "uygulama" aynı şey değil: adres çubuğu, sekme kalabalığı,
yanlışlıkla kapanan pencere, görev çubuğunda tarayıcının ikonu. Burası aynı
HTML'i Windows'un kendi WebView2 bileşeniyle, KENDİ penceresinde ve kendi
ikonuyla gösteriyor.

İki kısıt bu dosyanın biçimini belirliyor:

1. `webview.start()` ANA THREAD'de çalışmak zorunda ve geri dönmez. Bu yüzden
   HTTP sunucusu arka plan thread'ine taşındı (bkz. `ui/__main__.py`).
2. Pencere açılamayabilir (WebView2 çalışma zamanı yok, eski Windows, bozuk
   kurulum). O durumda uygulamayı ölü bırakmak yerine tarayıcıya düşüyoruz —
   eski davranış hâlâ orada, artık yalnızca yedek.

GUI gerektiren kısım tek bir fonksiyonda (`pencere_ac`) toplandı; geometri
hesabı saf fonksiyonlar hâlinde ayrı duruyor ki ekran olmadan test edilebilsin.
"""

from __future__ import annotations

import json
import sys
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "BASLIK",
    "Geometri",
    "VARSAYILAN",
    "ekrana_sigdir",
    "geometri_dosyasi",
    "geometri_oku",
    "geometri_yaz",
    "pencere_ac",
    "sanal_ekran",
    "webview2_surumu",
]

BASLIK = "Takvim"

# En küçük boyut: hafta ızgarası + kenar çubuğu + panel bu değerin altında
# üst üste biniyor. Kullanıcı pencereyi kullanılamaz hâle getiremesin.
EN_KUCUK = (940, 560)

# style.css'teki `--zemin` ile AYNI olmalı. Farklı olursa pencere açılırken
# sayfa yüklenene kadar beyaz bir kare parlıyor ve ucuz duruyor.
ZEMIN_RENK = "#0f1115"


@dataclass(frozen=True)
class Geometri:
    """Pencerenin boyutu ve isteğe bağlı konumu.

    `x`/`y` None ise pencereyi işletim sistemi ortalar; ilk açılışta istediğimiz
    de bu. Kayıtlı konum varsa onu kullanıyoruz.
    """

    genislik: int
    yukseklik: int
    x: int | None = None
    y: int | None = None
    buyutulmus: bool = False

    def __post_init__(self) -> None:
        """Boyutun anlamlı olduğunu doğrular."""
        if self.genislik <= 0 or self.yukseklik <= 0:
            raise ValueError("pencere boyutu pozitif olmalı")


VARSAYILAN = Geometri(1180, 760)


def geometri_dosyasi(veri_dizini: str | Path) -> Path:
    """Pencere konumunun saklandığı dosya.

    Veritabanının yanında duruyor: ikisi de "bu kullanıcının Takvim durumu".
    """
    return Path(veri_dizini) / "pencere.json"


def geometri_oku(yol: str | Path) -> Geometri | None:
    """Kayıtlı geometriyi okur; yoksa ya da bozuksa None.

    ASLA istisna fırlatmaz. Bozuk bir ayar dosyası yüzünden uygulamanın
    açılmaması kabul edilemez; varsayılan boyutla açılmak her zaman daha iyi.

    `utf-8-sig` ile okuyoruz: Windows araçları (PowerShell'in `Out-File`ı,
    Not Defteri) dosyanın başına BOM koyuyor ve `json.loads` onu görünce
    patlıyor. Sonuç sessiz: pencere her açılışta varsayılan boyuta dönüyor ve
    kimse sebebini anlamıyor. Elle düzenlenmiş bir dosyada yaşandı.
    """
    try:
        ham = json.loads(Path(yol).read_text(encoding="utf-8-sig"))
        return Geometri(
            genislik=int(ham["genislik"]),
            yukseklik=int(ham["yukseklik"]),
            x=None if ham.get("x") is None else int(ham["x"]),
            y=None if ham.get("y") is None else int(ham["y"]),
            buyutulmus=bool(ham.get("buyutulmus", False)),
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def geometri_yaz(yol: str | Path, g: Geometri) -> bool:
    """Geometriyi diske yazar; başardıysa True.

    Hata YUTULUYOR: bu, kapanış yolunda çağrılıyor ve yazılamayan bir dosya
    yüzünden kapanışta hata penceresi göstermek saçma olur. En kötü ihtimalle
    pencere bir dahaki sefere varsayılan boyutta açılır.
    """
    try:
        hedef = Path(yol)
        hedef.parent.mkdir(parents=True, exist_ok=True)
        hedef.write_text(
            json.dumps(
                {
                    "genislik": g.genislik,
                    "yukseklik": g.yukseklik,
                    "x": g.x,
                    "y": g.y,
                    "buyutulmus": g.buyutulmus,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def ekrana_sigdir(
    g: Geometri,
    sinir: tuple[int, int, int, int] | None,
    monitorde_mi=None,
) -> Geometri:
    """Geometriyi ekranın içine çeker.

    `sinir` = (sol, üst, genişlik, yükseklik), tüm monitörleri kapsayan sanal
    ekran. Gerekli, çünkü kayıtlı konum GEÇERSİZ olabilir: ikinci monitör
    çıkarılmış, çözünürlük düşmüş ya da dizüstü docking'ten ayrılmış olabilir.
    O durumda pencere görünmeyen bir koordinatta açılır ve kullanıcı için
    uygulama "açılmıyor" demektir.

    Kural: pencerenin başlık çubuğu görünür kalmalı. Yalnızca köşesi ekrana
    değen bir pencereyi de kabul etmiyoruz; en az `PAY` kadarı içeride olmalı.

    `monitorde_mi(x, y)`: o noktada GERÇEKTEN bir monitör var mı. Sanal ekran
    tek bir dikdörtgen ve monitörler dikdörtgen dizilmemişse (örneğin üstte
    kaydırılmış ikinci monitör) bu dikdörtgen ÖLÜ ALAN içerir; yalnızca sınıra
    bakmak o ölü alandaki bir konumu "geçerli" sayar ve pencere hiçbir ekranda
    görünmez. Verilmezse yalnızca sınır kontrolü yapılıyor (testler ve
    Windows dışı).
    """
    genislik = max(g.genislik, EN_KUCUK[0])
    yukseklik = max(g.yukseklik, EN_KUCUK[1])

    if sinir is None:
        return Geometri(genislik, yukseklik, g.x, g.y, g.buyutulmus)

    sol, ust, e_genislik, e_yukseklik = sinir
    # Ekran penceremizden küçükse (küçük dizüstü, uzak masaüstü) boyutu kırp.
    genislik = min(genislik, max(e_genislik, 1))
    yukseklik = min(yukseklik, max(e_yukseklik, 1))

    if g.x is None or g.y is None:
        return Geometri(genislik, yukseklik, None, None, g.buyutulmus)

    PAY = 120  # px: bu kadarı görünür değilse pencere "kayıp" sayılır
    sag, alt = sol + e_genislik, ust + e_yukseklik
    yatay_tamam = g.x + genislik - PAY >= sol and g.x + PAY <= sag
    # Başlık çubuğu ekranın üstünden yukarı taşarsa pencere sürüklenemez hâle
    # gelir; bu yüzden üst sınırda pay yok, tam içeride olmalı.
    dikey_tamam = g.y >= ust and g.y + PAY <= alt

    # Başlık çubuğunun ortasına yakın bir nokta: pencerenin kullanıcı tarafından
    # tutulabilecek yeri burası. Orada monitör yoksa pencere kayıptır.
    gercek_monitor = True
    if monitorde_mi is not None:
        gercek_monitor = bool(monitorde_mi(g.x + min(PAY, genislik // 2), g.y + 8))

    if yatay_tamam and dikey_tamam and gercek_monitor:
        return Geometri(genislik, yukseklik, g.x, g.y, g.buyutulmus)
    # Konum kullanılamaz: işletim sistemi ortalasın.
    return Geometri(genislik, yukseklik, None, None, g.buyutulmus)


def monitorde_mi(x: int, y: int) -> bool:
    """Verilen noktada gerçekten bir monitör var mı.

    `MonitorFromPoint(..., MONITOR_DEFAULTTONULL)` nokta hiçbir ekrana
    düşmüyorsa NULL döndürüyor — sanal ekranın dikdörtgeni içindeki ölü alanı
    yalnızca bu ayırt edebiliyor. Sorgulanamazsa "evet" diyoruz: kararsız
    kaldığımızda kullanıcının kayıtlı konumunu bozmuyoruz.
    """
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        class _NOKTA(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        # MONITOR_DEFAULTTONULL = 0
        return bool(ctypes.windll.user32.MonitorFromPoint(_NOKTA(x, y), 0))  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError):
        return True


def sanal_ekran() -> tuple[int, int, int, int] | None:
    """Tüm monitörleri kapsayan dikdörtgen; okunamazsa None.

    Win32 `GetSystemMetrics` sabitleri: 76-79 sanal ekranın sol/üst/en/boy'u.
    Tek monitörde birincil ekranla aynı, çok monitörde hepsini kapsıyor.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        al = ctypes.windll.user32.GetSystemMetrics  # type: ignore[attr-defined]
        sinir = (al(76), al(77), al(78), al(79))
        return sinir if sinir[2] > 0 and sinir[3] > 0 else None
    except (AttributeError, OSError):
        return None


# WebView2 çalışma zamanının kayıt defterindeki kimliği (Microsoft'un sabit
# GUID'i). Sürüm burada yazılı değilse bileşen kurulu değil demektir.
_WEBVIEW2_ISTEMCI = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def webview2_surumu() -> str | None:
    """Kurulu WebView2 sürümü; yoksa None.

    Bu kontrol ŞART, çünkü pywebview çalışma zamanını bulamazsa istisna
    ATMIYOR: sessizce eski Internet Explorer motoruna (mshtml) düşüyor ve
    kullanıcı bembeyaz, boş bir pencere görüyor — uygulamanın hiç açılmaması
    kadar kötü, üstelik nedeni de belli değil. Önceden bakıp yok ise
    tarayıcıya düşmek daha dürüst.

    Windows 11'de bileşen işletim sistemiyle birlikte geliyor; bu yol pratikte
    yalnızca eski Windows 10 kurulumlarında devreye giriyor.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None

    # Üç yer de geçerli: makine geneli (64 bit Windows'ta WOW6432Node altında),
    # yalnızca bu kullanıcı için kurulmuş olabilir, ya da 32 bit Windows'ta
    # WOW6432Node ara katmanı olmadan.
    for kok, yol in (
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\{_WEBVIEW2_ISTEMCI}"),
        (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\{_WEBVIEW2_ISTEMCI}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\{_WEBVIEW2_ISTEMCI}"),
    ):
        try:
            with winreg.OpenKey(kok, yol) as anahtar:
                surum, _ = winreg.QueryValueEx(anahtar, "pv")
            if surum and surum not in ("0.0.0.0", ""):
                return str(surum)
        except OSError:
            continue
    return None


def pencere_ac(
    url: str,
    veri_dizini: str | Path,
    tepsi_istendi: Callable[[], bool] | None = None,
) -> None:
    """Pencereyi açar ve KAPANANA KADAR geri dönmez.

    Ana thread'de çağrılmalı. `webview.start()` GUI döngüsü; pencere kapanınca
    dönüyor ve uygulama da o zaman bitiyor.

    `tepsi_istendi` her kapanışta çağrılıyor (sabit bayrak değil): kullanıcı
    ayarı ortadan değiştirirse yeniden başlatma gerekmez. True ise X pencereyi
    GİZLİYOR ve tepsiye simge koyuyor; tepsi kurulamazsa normal kapanıyor
    (kapanmayan pencere, tepsisiz kalmaktan kötü).

    `ImportError`/`Exception` YUKARI aktarılıyor: geri düşüşe (tarayıcı) karar
    vermek çağıranın işi, bu fonksiyonun değil.
    """
    if sys.platform == "win32" and webview2_surumu() is None:
        raise RuntimeError(
            "WebView2 çalışma zamanı bulunamadı. "
            "Windows 11'de hazır gelir; eski sürümlerde "
            "https://go.microsoft.com/fwlink/p/?LinkId=2124703 adresinden kurulabilir."
        )

    import webview

    # .ics dışa aktarma `Content-Disposition: attachment` ile geliyor, yani
    # WebView2 için bu bir İNDİRME. pywebview indirmeleri VARSAYILAN OLARAK
    # İPTAL ediyor (`ALLOW_DOWNLOADS: False`): açmazsak "Dışa aktar" düğmesi
    # hiçbir şey yapmıyormuş gibi görünür. Açınca Windows'un kendi "farklı
    # kaydet" penceresi çıkıyor — masaüstü uygulamasından beklenen davranış.
    webview.settings["ALLOW_DOWNLOADS"] = True

    yol = geometri_dosyasi(veri_dizini)
    g = ekrana_sigdir(geometri_oku(yol) or VARSAYILAN, sanal_ekran(), monitorde_mi)

    pencere = webview.create_window(
        BASLIK,
        url,
        width=g.genislik,
        height=g.yukseklik,
        x=g.x,
        y=g.y,
        min_size=EN_KUCUK,
        maximized=g.buyutulmus,
        background_color=ZEMIN_RENK,
        # Metin seçimi AÇIK: pywebview varsayılanı `body`ye `user-select: none`
        # enjekte ediyor ve bu, hızlı ekleme kutusundaki metni de seçilemez
        # yapıyor. Sürükleme davranışını uygulamanın kendi CSS'i zaten yönetiyor.
        text_select=True,
    )

    # Pencere durumu olaylardan izleniyor: `state` özelliği yerine bunu
    # kullanıyoruz, çünkü kapanış anında büyütülmüş pencerenin ölçüsü ekran
    # boyutuna eşit çıkar ve bir dahaki açılışta pencere ekranı kaplar.
    durum = {"buyutulmus": g.buyutulmus}
    pencere.events.maximized += lambda: durum.__setitem__("buyutulmus", True)
    pencere.events.restored += lambda: durum.__setitem__("buyutulmus", False)

    def kapanirken() -> bool | None:
        """Kapanmadan önce geometriyi kaydeder.

        `closing` olayı kilitli çalışıyor (senkron), yani pencere yok olmadan
        önce ölçüleri okuyabiliyoruz. Normal kapanışta None dönüyoruz; tepsi
        modunda pencereyi gizleyip `False` döndürüyoruz (kapanmayı İPTAL eder).
        """
        try:
            if durum["buyutulmus"]:
                # Büyütülmüşken ölçü almak ekran boyutunu verir; eski kayıtlı
                # boyutu koruyup yalnızca bayrağı güncelliyoruz.
                onceki = geometri_oku(yol) or VARSAYILAN
                yeni = Geometri(onceki.genislik, onceki.yukseklik, onceki.x, onceki.y, True)
            else:
                yeni = Geometri(pencere.width, pencere.height, pencere.x, pencere.y, False)
            geometri_yaz(yol, yeni)
        except Exception:  # kapanışı hiçbir şey engellemesin
            pass
        if tepsi_istendi is not None and not gercek_kapanis["istendi"]:
            try:
                isteniyor = bool(tepsi_istendi())
            except Exception:
                isteniyor = False  # ayar okunamadı: güvenli tarafta kal
            if isteniyor:
                from .tepsi import Tepsi, simge_bul

                tepsi = Tepsi.kur(
                    pencere.show, gercek_kapat, simge_yolu=simge_bul()
                )
                if tepsi is None:
                    return None  # simge kurulamadı: normal kapan
                tutamac["tepsi"] = tepsi
                try:
                    pencere.hide()
                except Exception:
                    tutamac["tepsi"] = None
                    return None
                return False
        if tutamac["tepsi"] is not None:
            tutamac["tepsi"].kapat()
            tutamac["tepsi"] = None
        return None

    def gercek_kapat() -> None:
        """Tepsi menüsünden "Kapat": bayrağı koyup pencereyi yıkıyor."""
        gercek_kapanis["istendi"] = True
        if tutamac["tepsi"] is not None:
            tutamac["tepsi"].kapat()
            tutamac["tepsi"] = None
        try:
            pencere.destroy()
        except Exception:
            pass

    gercek_kapanis = {"istendi": False}
    tutamac: dict = {"tepsi": None}

    pencere.events.closing += kapanirken

    # Pencere bir kez GÖRÜNDÜ mü? Çağıran, pencere açılamazsa tarayıcıya
    # düşüyor; ama `webview.start()` pencere kapanana kadar dönmediği için
    # KAPANIŞ sırasında çıkan bir hata da buradan kaçardı ve kullanıcı
    # uygulamayı kapattıktan sonra karşısında bir tarayıcı sekmesi bulurdu.
    gosterildi = threading.Event()
    pencere.events.shown += gosterildi.set

    def gorununce() -> None:
        """Pencere KÜÇÜLTÜLMÜŞ açıldıysa geri getirir.

        Masaüstü kısayolu süreci "küçültülmüş" başlatma stiliyle çalıştırabiliyor
        -- eski sürümde arkadaki konsol penceresi göze batmasın diye böyle
        kurulmuştu. O stil işletim sistemi tarafından UYGULAMA PENCERESİNE de
        uygulanıyor: kullanıcı kısayola tıklıyor ve ekranda hiçbir şey
        açılmıyor, yalnızca görev çubuğunda bir simge beliriyor. Bu tam olarak
        "uygulama çalışmıyor" demek ve kısayolu düzeltmek yetmez: kopyalanmış
        ya da elle oluşturulmuş bir kısayol aynı tuzağa düşer.

        Kullanıcının kendi bıraktığı büyütülmüş durumu ezmemek için yalnızca o
        beklenmiyorken geri getiriyoruz.
        """
        if durum["buyutulmus"]:
            return
        try:
            pencere.restore()
        except Exception:
            pass

    pencere.events.shown += gorununce

    # `private_mode=False` + `storage_path`: WebView2 kendi çalışma klasörünü
    # her açılışta sıfırdan kurmasın. Uygulama verisi zaten SQLite'ta; buradaki
    # klasör yalnızca WebView2'nin önbelleği. İKİSİ BİRLİKTE VERİLMEZ:
    # `private_mode=True` iken verilen klasörü pywebview SİLİYOR.
    depo = Path(veri_dizini) / "webview"
    try:
        depo.mkdir(parents=True, exist_ok=True)
        depo_yolu: str | None = str(depo)
    except OSError:
        depo_yolu = None  # yazılamıyorsa pywebview geçici klasöre düşsün

    try:
        webview.start(debug=False, private_mode=depo_yolu is None, storage_path=depo_yolu)
    except Exception:
        if not gosterildi.is_set():
            raise  # hiç açılamadı: çağıran tarayıcıya düşsün
        # Pencere görünmüştü; bu bir kapanış hatası. Kullanıcı uygulamayı
        # kapattı, geriye tarayıcı açmak yanlış olur — yalnızca günlüğe yaz.
        traceback.print_exc()
