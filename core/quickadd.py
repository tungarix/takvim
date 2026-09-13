"""Hızlı ekleme: "yarın 14:00 diş hekimi" -> Event alanları.

Saf fonksiyon: girdi metin + referans an, çıktı veri. DB, ekran, I/O yok.

Tasarım ilkesi: **tahmin etme, tanı.** Tanımadığı bir zaman ifadesini
uydurmaktansa tüm gün etkinliği üretip `matched` alanını boş bırakıyor;
arayüz bunu kullanıcıya "zaman bulunamadı" diye gösterebiliyor. Yanlış saate
sessizce kaydedilen bir randevu, kaydedilmemiş randevudan beterdir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .timeutil import from_wall_clock, get_tz

__all__ = ["QuickAdd", "parse_quick_add"]

VARSAYILAN_SURE = timedelta(hours=1)

_GUNLER = {
    "pazartesi": 0, "salı": 1, "sali": 1, "çarşamba": 2, "carsamba": 2,
    "perşembe": 3, "persembe": 3, "cuma": 4, "cumartesi": 5, "pazar": 6,
}

_AYLAR = {
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5,
    "haziran": 6, "temmuz": 7, "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9,
    "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
}

# Saat: "14:00", "14.30", "9da", "14'te", "saat 9"
# Bulunma eki rakama BİTİŞİK olmak zorunda ("9da", "14'te"). Araya boşluk
# koyarsak desen, ardından gelen kelimenin ilk iki harfini ek sanıp yiyor:
# "11:30 tasarim" -> saat 11:30 + ek "ta", başlık "sarim" kalıyordu. "test",
# "deneme", "davet", "tatil" gibi çok yaygın kelimeler de bozuluyordu.
_SAAT = r"(?:saat\s*)?(\d{1,2})(?:[:.](\d{2}))?(?:['’]?(?:de|da|te|ta)\b)?"
_ARALIK_RE = re.compile(rf"\b{_SAAT}\s*(?:-|–|—|ile)\s*{_SAAT}(?:\s*arası)?", re.I)
# Tek saat: işaret ŞART (iki nokta, nokta, ek, veya "saat" öneki).
# İşaretsiz çıplak sayıyı saat saymıyoruz; "3 ekim" gibi ifadelerle çakışır.
_TEK_SAAT_RE = re.compile(
    r"\b(?:saat\s*(\d{1,2})(?:[:.](\d{2}))?"
    r"|(\d{1,2})[:.](\d{2})"
    r"|(\d{1,2})['’]?(?:de|da|te|ta))\b",
    re.I,
)
_SURE_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(saat|saatlik|dakika|dk|dakikalık)\b", re.I)
_GUN_SAYI_AY_RE = re.compile(
    rf"\b(\d{{1,2}})\s+({'|'.join(_AYLAR)})(?:\s+(\d{{4}}))?\b", re.I
)
_SAYISAL_TARIH_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")
_GUN_ADI_RE = re.compile(
    rf"\b(?:(önümüzdeki|gelecek|haftaya|bu)\s+)?({'|'.join(_GUNLER)})\b", re.I
)
_GORECELI_RE = re.compile(r"\b(bugün|bugun|yarın|yarin|öbür gün|obur gun|dün|dun)\b", re.I)


@dataclass(frozen=True)
class QuickAdd:
    """Hızlı ekleme ayrıştırmasının sonucu.

    `matched` tanınan zaman ifadesidir; boşsa hiçbir zaman bilgisi
    bulunamamıştır ve sonuç bugünün tüm gün etkinliğidir. Arayüz bunu
    kullanıcıya göstererek sessiz yanlış kaydı önlüyor.
    """

    title: str
    start_utc: datetime
    end_utc: datetime
    all_day: bool
    tzid: str
    matched: str = ""


def _kucult(metin: str) -> str:
    """Türkçe duyarlı küçültme ('I'->'ı', 'İ'->'i')."""
    return metin.replace("I", "ı").replace("İ", "i").lower()


def _saat_dakika(saat: str | None, dakika: str | None) -> tuple[int, int] | None:
    """Yakalanan grupları (saat, dakika) çiftine çevirir; geçersizse None."""
    if saat is None:
        return None
    s = int(saat)
    d = int(dakika) if dakika else 0
    if not (0 <= s <= 23 and 0 <= d <= 59):
        return None
    return s, d


def _tarih_coz(metin: str, bugun: date) -> tuple[date | None, tuple[int, int] | None]:
    """Metindeki tarih ifadesini çözer; (tarih, kapsanan aralık) döndürür."""
    m = _GORECELI_RE.search(metin)
    if m:
        kelime = _kucult(m.group(1))
        fark = {
            "bugün": 0, "bugun": 0,
            "yarın": 1, "yarin": 1,
            "öbür gün": 2, "obur gun": 2,
            "dün": -1, "dun": -1,
        }[kelime]
        return bugun + timedelta(days=fark), m.span()

    m = _GUN_SAYI_AY_RE.search(metin)
    if m:
        gun = int(m.group(1))
        ay = _AYLAR[_kucult(m.group(2))]
        yil = int(m.group(3)) if m.group(3) else bugun.year
        try:
            aday = date(yil, ay, gun)
        except ValueError:
            return None, None  # "32 ocak": ay adı açık, tarih bozuk
        # Yıl verilmediyse ve tarih geçmişteyse gelecek yılı kastediyordur.
        if m.group(3) is None and aday < bugun:
            try:
                aday = date(yil + 1, ay, gun)
            except ValueError:
                pass
        return aday, m.span()

    m = _SAYISAL_TARIH_RE.search(metin)
    if m:
        gun, ay = int(m.group(1)), int(m.group(2))
        ham_yil = m.group(3)
        yil = bugun.year
        if ham_yil:
            yil = int(ham_yil)
            if yil < 100:
                yil += 2000
        try:
            aday = date(yil, ay, gun)
        except ValueError:
            # "13.30" bir tarih değil saat; sayısal deseni geçip gün adına bak.
            aday = None
        if aday is None:
            m = None
        elif ham_yil is None and aday < bugun:
            try:
                aday = date(yil + 1, ay, gun)
            except ValueError:
                pass
        if m is not None:
            return aday, m.span()

    m = _GUN_ADI_RE.search(metin)
    if m:
        hedef = _GUNLER[_kucult(m.group(2))]
        ileri = (hedef - bugun.weekday()) % 7
        nitel = _kucult(m.group(1) or "")
        if nitel in ("önümüzdeki", "gelecek", "haftaya"):
            # "önümüzdeki salı": bu hafta salıysa bile BİR SONRAKİ salı.
            ileri = ileri + 7 if ileri != 0 else 7
        elif ileri == 0:
            # Nitelemesiz ve bugünse "bugün" kastediliyor sayıyoruz.
            ileri = 0
        return bugun + timedelta(days=ileri), m.span()

    return None, None


def _sure_coz(metin: str) -> tuple[timedelta | None, tuple[int, int] | None]:
    """'2 saat', '90 dakika', '1.5 saat' ifadesini süreye çevirir."""
    m = _SURE_RE.search(metin)
    if not m:
        return None, None
    sayi = float(m.group(1).replace(",", "."))
    birim = _kucult(m.group(2))
    if birim.startswith("saat"):
        return timedelta(hours=sayi), m.span()
    return timedelta(minutes=sayi), m.span()


def _maskele(metin: str, span: tuple[int, int] | None) -> str:
    """Verilen aralığı aynı uzunlukta boşlukla değiştirir.

    İndisler bozulmasın diye kesmiyoruz: tarih ifadesi metinden çıkarılmış gibi
    davranırken, sonradan bulunan saatin span'i hâlâ orijinal metne uyuyor.
    """
    if not span:
        return metin
    bas, bit = span
    return metin[:bas] + " " * (bit - bas) + metin[bit:]


def _kes(metin: str, araliklar: list[tuple[int, int]]) -> str:
    """Verilen aralıkları metinden çıkarıp kalanı temizler."""
    parcalar = []
    son = 0
    for bas, bit in sorted(a for a in araliklar if a):
        if bas < son:  # üst üste binen yakalama
            continue
        parcalar.append(metin[son:bas])
        son = bit
    parcalar.append(metin[son:])
    kalan = " ".join(" ".join(parcalar).split())
    # Baştaki/sondaki bağlaç ve noktalama artıkları
    kalan = re.sub(r"^(?:de|da|te|ta|ile|arası|saat)\b\s*", "", kalan, flags=re.I)
    return kalan.strip(" ,;:-–—")


def parse_quick_add(
    metin: str,
    *,
    now: datetime,
    tzid: str,
    varsayilan_sure: timedelta = VARSAYILAN_SURE,
) -> QuickAdd:
    """Serbest metni etkinlik alanlarına çevirir.

    `now` referans andır (aware); "yarın" ona göre hesaplanır. Test edilebilir
    olması için parametre -- içeride `datetime.now()` çağırmıyoruz.

    Zaman bulunamazsa sonuç, tarih verilmişse o günün, verilmemişse bugünün
    TÜM GÜN etkinliğidir ve `matched` boş kalır.
    """
    if not metin or not metin.strip():
        raise ValueError("Boş metin ayrıştırılamaz")

    get_tz(tzid)  # geçersiz dilim erken patlasın
    bugun = now.astimezone(get_tz(tzid)).date()
    ham = metin.strip()

    araliklar: list[tuple[int, int] | None] = []
    yakalanan: list[str] = []

    # Sıra önemli ve her adım bir öncekini maskeliyor:
    #   tarih -> süre -> saat aralığı -> tek saat
    # "15.10.2026" içindeki "15.10" saat sanılmasın diye tarih önce;
    # "2 saat 14:00" içindeki "saat 14:00" deseni süreyle çakışmasın diye
    # süre saatten önce.

    # 1) Tarih
    gun, gun_aralik = _tarih_coz(ham, bugun)
    if gun_aralik:
        araliklar.append(gun_aralik)
        yakalanan.append(ham[gun_aralik[0]:gun_aralik[1]].strip())
    maskeli = _maskele(ham, gun_aralik)

    # 2) Süre
    sure, sure_aralik = _sure_coz(maskeli)
    if sure_aralik:
        araliklar.append(sure_aralik)
        yakalanan.append(ham[sure_aralik[0]:sure_aralik[1]].strip())
        maskeli = _maskele(maskeli, sure_aralik)

    # 3) Saat aralığı ("14:00-16:00") tek saatten ÖNCE denenmeli.
    baslangic_sd: tuple[int, int] | None = None
    bitis_sd: tuple[int, int] | None = None
    m = _ARALIK_RE.search(maskeli)
    if m:
        baslangic_sd = _saat_dakika(m.group(1), m.group(2))
        bitis_sd = _saat_dakika(m.group(3), m.group(4))
        if baslangic_sd and bitis_sd:
            araliklar.append(m.span())
            yakalanan.append(ham[m.start():m.end()].strip())
        else:
            baslangic_sd = bitis_sd = None

    # 4) Tek saat
    if baslangic_sd is None:
        m = _TEK_SAAT_RE.search(maskeli)
        if m:
            for saat_g, dk_g in ((1, 2), (3, 4), (5, None)):
                if m.group(saat_g) is not None:
                    baslangic_sd = _saat_dakika(
                        m.group(saat_g), m.group(dk_g) if dk_g else None
                    )
                    break
            if baslangic_sd:
                araliklar.append(m.span())
                yakalanan.append(ham[m.start():m.end()].strip())

    baslik = _kes(ham, [a for a in araliklar if a]) or "(Başlıksız)"
    hedef_gun = gun or bugun

    if baslangic_sd is None:
        # Zaman yok -> tüm gün. Uydurmak yerine bunu söylüyoruz.
        start = from_wall_clock(datetime.combine(hedef_gun, datetime.min.time()), tzid)
        end = from_wall_clock(
            datetime.combine(hedef_gun + timedelta(days=1), datetime.min.time()), tzid
        )
        return QuickAdd(baslik, start, end, True, tzid, " ".join(yakalanan).strip())

    s, d = baslangic_sd
    start = from_wall_clock(datetime(hedef_gun.year, hedef_gun.month, hedef_gun.day, s, d), tzid)

    if bitis_sd is not None:
        bs, bd = bitis_sd
        bitis_gun = hedef_gun
        if (bs, bd) <= (s, d):
            # "23:00-01:00": bitiş ertesi güne sarkıyor.
            bitis_gun = hedef_gun + timedelta(days=1)
        end = from_wall_clock(
            datetime(bitis_gun.year, bitis_gun.month, bitis_gun.day, bs, bd), tzid
        )
    else:
        end = start + (sure or varsayilan_sure)

    return QuickAdd(baslik, start, end, False, tzid, " ".join(yakalanan).strip())
