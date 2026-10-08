"""Otomatik yerel yedek.

Neden var: bütün veri `%LOCALAPPDATA%/Takvim/takvim.db` içinde TEK kopya
hâlinde duruyor. Kullanıcıya "yedeklemek için Dışa aktar'a bas" demek yeterli
değil, çünkü üretilen `.ics` bir yedek DEĞİL: hatırlatıcıları ve hangi
etkinliğin hangi takvime ait olduğunu taşımıyor. Dosyanın kendisinin kopyası
gerekiyor.

`sqlite3.Connection.backup()` kullanılıyor, dosyayı elle kopyalamak DEĞİL:
bağlantı açıkken düz kopyalama yarım yazılmış bir sayfayı yakalayabilir,
backup API'si ise tutarlı bir anlık görüntü veriyor ve bunu kilitlemeden
yapıyor.

Buradaki her şey SESSİZCE BAŞARISIZ OLUR. Yedek alamamak uygulamayı
açmamak için sebep değil; en kötü ihtimalle kullanıcı yedeksiz kalır ve bunu
günlükte görür.
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path

from .migrator import migrate

__all__ = [
    "ONCEKI_SAKLANAN",
    "SAKLANAN",
    "bozuk_veritabanini_degistir",
    "onceki_dosyalari",
    "son_saglam_yedek",
    "veritabani_bozuklugu",
    "yedek_al",
    "yedek_dosyalari",
    "yedek_klasoru",
    "yedekten_don",
]

# Kaç günlük yedek saklanacak. Yedi gün, "geçen hafta yanlışlıkla sildim"
# senaryosunu kurtarmaya yetiyor; daha fazlası disk ve karmaşa.
SAKLANAN = 7
# Kaç "geri yükleme öncesi" anlık görüntü saklanacak (`onceki-takvim-*.db`).
# Gün başına değil, DENEME başına bir tane oluştuğu için pencere daha küçük.
ONCEKI_SAKLANAN = 5


def yedek_klasoru(veri_dizini: str | Path) -> Path:
    """Yedeklerin durduğu klasör (veritabanının yanında)."""
    return Path(veri_dizini) / "yedek"


def yedek_dosyalari(klasor: str | Path) -> list[Path]:
    """Var olan yedekler, ESKİDEN YENİYE sıralı.

    Ad biçimi `takvim-YYYY-AA-GG.db` olduğu için alfabetik sıralama kronolojik
    sıralamayla aynı; dosya zaman damgasına güvenmiyoruz (kopyalama,
    senkronizasyon ve yedekten dönme damgayı bozar).
    """
    try:
        return sorted(Path(klasor).glob("takvim-*.db"))
    except OSError:
        return []


def yedek_al(baglanti: sqlite3.Connection, veri_dizini: str | Path, *, bugun: date) -> Path | None:
    """Veritabanının kopyasını alır; aldıysa dosya yolunu döndürür.

    Günde TEK dosya: aynı gün içinde uygulama beş kez açılırsa beş yedek değil,
    güncellenen tek bir yedek olur. Yoksa yedi kopyalık pencere, uygulamayı sık
    açan bir günde tek güne sıkışır ve "geçen hafta" kurtarılamaz hâle gelir.

    `bugun` dışarıdan veriliyor: testler tarihi ilerletebilsin diye.
    """
    try:
        # Bozuk veritabanının yedeği ALINMAZ. Günde tek dosya olduğu için bozuk
        # kopya o sabah alınmış sağlam yedeğin ÜZERİNE yazılıyordu, budama da
        # birkaç gün sonra eski sağlamları siliyordu: bozukluğu fark eden
        # kullanıcı dönebileceği hiçbir yedek bulamazdı. Paketli exe'de ölçüldü.
        if _bozukluk(baglanti) is not None:
            return None
        klasor = yedek_klasoru(veri_dizini)
        klasor.mkdir(parents=True, exist_ok=True)
        hedef = klasor / f"takvim-{bugun.isoformat()}.db"

        # Geçici ada yazıp sonra taşıyoruz: yedek alırken uygulama kapanırsa
        # geriye YARIM bir "yedek" kalmasın. Yarım yedek, yedeksiz olmaktan
        # kötüdür -- insan ona güvenir.
        # Ad süreç-özel (`pid` sonekli): ön yüzle otomatik başlatmanın arka
        # plan kopyası aynı gün yedek alırsa ortak temp dosyaya yazıp
        # birbirinin anlık görüntüsünü bozardı. Taşıma atomik, son kazananın
        # dosyası da tutarlı bir anlık görüntü.
        _eski_gecicileri_temizle(klasor, hedef.name)
        gecici = hedef.with_name(f"{hedef.name}.gecici-{os.getpid()}")
        kopya = sqlite3.connect(gecici)
        try:
            baglanti.backup(kopya)
        finally:
            # `with sqlite3.connect(...)` KAPATMAZ, yalnızca transaction'ı
            # yönetir. Dosya açık kalırsa Windows taşımaya izin vermiyor ve
            # yedek sessizce alınamıyordu.
            kopya.close()
        gecici.replace(hedef)

        _budama(klasor)
        return hedef
    except (sqlite3.Error, OSError):
        return None


def _eski_gecicileri_temizle(klasor: Path, hedef_ad: str) -> None:
    """Ölmüş süreçlerden kalan temp yedekleri siler.

    Yalnızca 1 SAATTEN ESKİLER: canlı bir süreç şu an yazıyor olabilir,
    onun dosyasına dokunmak o yedeği bozar. Normal yedek saniyeler sürdüğü
    için saatlik eşik fazlasıyla güvenli. Silinemeyen atlanıyor.
    """
    esik = time.time() - 3600
    try:
        adaylar = list(klasor.glob(f"{hedef_ad}.gecici-*"))
    except OSError:
        return
    for artik in adaylar:
        try:
            if artik.stat().st_mtime < esik:
                artik.unlink()
        except OSError:
            pass  # kilitli ya da arada silinmiş; bir dahaki sefere


def _budama(klasor: Path) -> list[Path]:
    """En eski yedekleri siler, `SAKLANAN` tanesini bırakır; silinenleri döndürür."""
    return _n_tanesini_birak(yedek_dosyalari(klasor), SAKLANAN)


def onceki_dosyalari(klasor: str | Path) -> list[Path]:
    """`yedekten_don`'un kenara aldığı `onceki-takvim-*.db` anlık görüntüleri.

    `yedek_dosyalari`'nin `takvim-*.db` deseniyle KASTEN eşleşmiyorlar (bkz.
    o fonksiyonun docstring'i); bu yüzden ayrı bir liste ve ayrı bir budama
    gerekiyor -- yoksa hiç budanmadan sonsuza kadar birikirler.
    """
    try:
        return sorted(Path(klasor).glob("onceki-takvim-*.db"))
    except OSError:
        return []


def _onceki_budama(klasor: Path) -> list[Path]:
    """En eski `onceki-takvim-*.db` anlık görüntülerini siler, `ONCEKI_SAKLANAN`
    tanesini bırakır.

    Günlük yedeklerden AYRI bir politika: bunlar gün başına değil, her
    "yedekten dön" denemesinde bir tane oluşuyor -- art arda birkaç yedek
    denenirse hızla birikebilir, o yüzden pencere daha küçük.
    """
    return _n_tanesini_birak(onceki_dosyalari(klasor), ONCEKI_SAKLANAN)


def _n_tanesini_birak(dosyalar: list[Path], n: int) -> list[Path]:
    """ESKİDEN YENİYE sıralı bir listenin en eskilerini siler, son `n` tanesini bırakır."""
    silinecek = dosyalar[: max(0, len(dosyalar) - n)]
    silinen = []
    for d in silinecek:
        try:
            d.unlink()
            silinen.append(d)
        except OSError:
            pass  # kilitli ya da izin yok; bir dahaki açılışta yine denenir
    return silinen


def yedekten_don(
    repo, db_yolu, ad: str, *, check_same_thread: bool = True, simdi: datetime | None = None
):
    """Seçili yedeği CANLI veritabanına yazar; AYNI depoyu döndürür.

    SQLite `backup` API'siyle, dosya DEĞİŞTİRMEKSİZİN: bağlantı açıkken
    dosya kopyalamak Windows'ta kilide takılıyor ve hatırlatıcı thread'i
    (ayrı bağlantı, aynı dosya) açıkken `replace` her zaman patlıyordu.
    Eski kod o hatayı YUTUP eski DB'yi "geri yüklendi" diye döndürüyordu.

    Sıra: yedeği doğrula -> mevcut hâli kenara al (`onceki-takvim-*.db`,
    `takvim-*.db` örüntüsünün DIŞINDA) -> yedeği canlı bağlantıya kopyala.
    Başarısızlıkta RuntimeError; ASLA sahte başarı yok. `check_same_thread`
    imza uyumu için duruyor (bağlantı yeniden açılmıyor, mevcut korunuyor).

    `simdi` dışarıdan verilebiliyor: testler saniye çözünürlüklü damgayı
    (`onceki-takvim-{...}.db`) art arda ilerletebilsin diye (`yedek_al`'ın
    `bugun` parametresiyle aynı desen).
    """
    if db_yolu is None or str(db_yolu) == ":memory:":
        raise ValueError("bellek veritabanına yedekten dönülemez")
    db = Path(db_yolu).resolve()
    klasor = yedek_klasoru(db.parent)
    gecerli = {p.name for p in yedek_dosyalari(klasor)}
    if ad not in gecerli:
        # Yol geçişine karşı liste-dışı her ad reddedilir (`../x` dahil).
        raise ValueError(f"yedek bulunamadı: {ad}")
    kaynak = klasor / ad

    try:
        kaynaga_baglanti = sqlite3.connect(str(kaynak))
    except sqlite3.Error as hata:
        raise RuntimeError(f"Yedek açılamadı ({kaynak.name}): {hata}") from hata
    try:
        sorun = _bozukluk(kaynaga_baglanti)
        if sorun is not None:
            raise RuntimeError(f"Yedek bozuk ({kaynak.name}): {sorun}")

        kenara: Path | None = None
        if db.exists():
            try:
                damga = (simdi or datetime.now()).strftime("%Y-%m-%d-%H%M%S")
                kenara = klasor / f"onceki-takvim-{damga}.db"
                kenara_baglanti = sqlite3.connect(str(kenara))
                try:
                    repo.conn.backup(kenara_baglanti)
                finally:
                    kenara_baglanti.close()
                # `takvim-*.db` deseniyle eşleşmediği için `_budama`'nın
                # dışında kalıyorlardı; budamazsak her denemede bir tam DB
                # kopyası kalıcı olarak birikir.
                _onceki_budama(klasor)
            except (sqlite3.Error, OSError):
                # Kenara alınamadı; geri dönüş yine denenir. Yarım kalmış
                # kenara dosyası varsa temizle ki "sağlam kenara" sanılmasın.
                try:
                    if kenara is not None and kenara.exists():
                        kenara.unlink()
                except OSError:
                    pass
                kenara = None

        try:
            # `sleep`: hedef başka bir bağlantı (hatırlatıcı thread'i)
            # tarafından anlık kilitliyse bekleyip yeniden dene.
            kaynaga_baglanti.backup(repo.conn, sleep=0.1)
        except Exception as hata:
            raise RuntimeError(
                f"Yedekten dönülemedi ({kaynak.name}): {hata}. "
                f"Yedek klasörü: {klasor}"
            ) from hata

        sorun = _bozukluk(repo.conn)
        if sorun is None:
            # Yedek, ondan SONRA gelen bir migration'dan önceki şemada olabilir
            # (yedek migration'dan önce alınıyor, AGENTS 55). Uygulama yeniden
            # başlamadan aynı bağlantıyla çalışmaya devam ettiği için şemayı
            # burada güncellemezsek ör. v1.5.0 öncesi bir yedeğe dönünce görev
            # listesi ve hatırlatıcılar "no such table: tasks" ile susar.
            try:
                migrate(repo.conn)
            except Exception as hata:
                sorun = f"şema güncellenemedi: {hata}"
        if sorun is not None:
            # Geri yazma yarım kaldıysa ya da şema güncellenemediyse kenaradaki
            # sağlam hâli geri koymayı dene; olmazsa yine de sessiz kalma.
            if kenara is not None and kenara.exists():
                try:
                    geri_baglanti = sqlite3.connect(str(kenara))
                    try:
                        geri_baglanti.backup(repo.conn, sleep=0.1)
                    finally:
                        geri_baglanti.close()
                except (sqlite3.Error, OSError):
                    pass
            raise RuntimeError(
                f"Yedekten dönülen veritabanı kullanılamıyor: {sorun}. "
                f"Yedek klasörü: {klasor}"
            )
        return repo
    finally:
        kaynaga_baglanti.close()


def _bozukluk(baglanti: sqlite3.Connection) -> str | None:
    """`PRAGMA quick_check` sorun bulursa ilk satırını, sağlamsa None döndürür.

    Yalnızca istisnayı yakalamak YETMEZ: bozuk ama açılabilen bir dosyada
    SQLite hata fırlatmıyor, sorunu SATIR olarak döndürüyor ("Tree 2 page 5
    cell 0: Offset ... out of range"). Sonuca bakmayan kontrol böyle bir
    yedeği sağlam sayıp canlı verinin üzerine yazıyordu.
    """
    try:
        satirlar = baglanti.execute("PRAGMA quick_check").fetchall()
    except sqlite3.Error as hata:
        return str(hata)
    return _denetim_sonucu(satirlar)


def _denetim_sonucu(satirlar: list) -> str | None:
    """`quick_check` satırlarından ilk gerçek sorunu çıkarır; sağlamsa None."""
    if [tuple(s) for s in satirlar] == [("ok",)]:
        return None
    # İlk satır "*** in database main ***" başlığıyla başlayabiliyor; kullanıcıya
    # gösterilecek olan altındaki ilk gerçek sorun.
    metin = "\n".join(str(s[0]) for s in satirlar)
    sorunlar = [s for s in metin.splitlines() if s.strip() and not s.startswith("***")]
    return sorunlar[0] if sorunlar else "bilinmeyen sonuç"


def veritabani_bozuklugu(yol: str | Path, *, bekleme: float = 5.0) -> str | None:
    """Dosya bozuksa sorunun ilk satırını, sağlamsa ya da yoksa None döndürür.

    Uygulama açılmadan ÖNCE, salt okunur bir bağlantıyla bakılıyor: bozuk dosyaya
    migration ya da yedek yazmadan karar verilsin diye.

    Kilit bozukluk SAYILMAZ (`OperationalError`, ör. "database is locked"):
    arka plan kopyası o an yazıyor olabilir, sağlam bir dosyayı "bozuk" deyip
    kenara almak verinin yarısını yedekte bırakmak olurdu. O durumda karar
    normal açılışa kalır. Veritabanı olmayan dosya ("file is not a database")
    ve bozuk sayfa ise `DatabaseError`'dur ya da satır olarak döner.
    """
    yol = Path(yol)
    try:
        if not yol.is_file() or yol.stat().st_size == 0:
            return None
    except OSError:
        return None
    try:
        baglanti = sqlite3.connect(f"{yol.resolve().as_uri()}?mode=ro", uri=True, timeout=bekleme)
    except sqlite3.Error:
        return None
    try:
        satirlar = baglanti.execute("PRAGMA quick_check").fetchall()
    except sqlite3.OperationalError:
        return None
    except sqlite3.DatabaseError as hata:
        return str(hata)
    finally:
        baglanti.close()
    return _denetim_sonucu(satirlar)


def son_saglam_yedek(klasor: str | Path) -> Path | None:
    """En YENİ sağlam günlük yedek; hiçbiri sağlam değilse None.

    Bozukluk ortaya çıkmadan önceki birkaç gün de bozuk kopya yedeklenmiş
    olabilir (bu koruma eklenmeden önceki sürümler bunu yapıyordu), bu yüzden
    en yeniye körü körüne güvenilmiyor; her aday tek tek denetleniyor.
    """
    for aday in sorted(yedek_dosyalari(klasor), key=lambda p: p.name, reverse=True):
        if veritabani_bozuklugu(aday) is None:
            return aday
    return None


def bozuk_veritabanini_degistir(db: str | Path, yedek: str | Path, *, simdi: datetime) -> Path:
    """Bozuk dosyayı SİLMEDEN kenara alır, yerine yedeğin kopyasını koyar.

    Kenara alınan dosyanın yolunu döndürür (`bozuk-takvim-<zaman>.db`, aynı
    klasörde): içinde yedekten sonra girilmiş veri olabilir ve ileride
    kurtarılmak istenebilir; silmek geri alınamaz.

    Sıra bilinçli: önce yedek GEÇİCİ ada kopyalanır ve sağlam olduğu yeniden
    doğrulanır, ancak sonra bozuk dosyaya dokunulur. Kopyalama yarıda kalırsa
    ortada yine bozuk ama yerinde duran bir dosya olur, hiç dosya değil.
    Bozuk dosyanın `-journal`/`-wal`/`-shm` eşleri de taşınır: yerinde kalan
    sıcak bir günlük, yeni dosyaya "geri alma" diye uygulanıp onu bozardı.
    """
    db = Path(db)
    yedek = Path(yedek)
    gecici = db.with_name(f"{db.name}.kurtarma-{os.getpid()}")
    kaynak = sqlite3.connect(f"{yedek.resolve().as_uri()}?mode=ro", uri=True)
    try:
        hedef = sqlite3.connect(gecici)
        try:
            kaynak.backup(hedef)
        finally:
            hedef.close()
    finally:
        kaynak.close()

    sorun = veritabani_bozuklugu(gecici)
    if sorun is not None:
        try:
            gecici.unlink()
        except OSError:
            pass
        raise RuntimeError(f"Yedek kopyalanırken bozuldu ({yedek.name}): {sorun}")

    on_ek = f"bozuk-{db.stem}-{simdi:%Y%m%d-%H%M%S}"
    kenara = db.with_name(f"{on_ek}{db.suffix}")
    db.replace(kenara)
    for es in ("-journal", "-wal", "-shm"):
        eski = db.with_name(db.name + es)
        if eski.exists():
            eski.replace(kenara.with_name(kenara.name + es))
    gecici.replace(db)
    return kenara
