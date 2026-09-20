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

__all__ = [
    "ONCEKI_SAKLANAN",
    "SAKLANAN",
    "onceki_dosyalari",
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
        try:
            kaynaga_baglanti.execute("PRAGMA quick_check").fetchone()
        except sqlite3.Error as hata:
            raise RuntimeError(f"Yedek bozuk ({kaynak.name}): {hata}") from hata

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

        try:
            repo.conn.execute("PRAGMA quick_check").fetchone()
        except sqlite3.Error as hata:
            # Geri yazma yarım kaldıysa kenaradaki sağlam hâli geri koymayı
            # dene; olmazsa yine de sessiz kalma.
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
                f"Yedekten dönülen veritabanı bozuk: {hata}. "
                f"Yedek klasörü: {klasor}"
            ) from hata
        return repo
    finally:
        kaynaga_baglanti.close()
