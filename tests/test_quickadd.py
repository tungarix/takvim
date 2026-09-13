"""Faz 4: hızlı ekleme ayrıştırıcısı.

Referans an sabit: 13 Eylül 2026, Pazar, 10:00 Europe/Istanbul.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from core import to_local
from core.quickadd import parse_quick_add
from tests.helpers import IST, NY, ist

SIMDI = ist(2026, 9, 13, 10, 0)  # Pazar


def _coz(metin: str, tzid: str = IST):
    """Kısayol: sabit referans anla ayrıştırır."""
    return parse_quick_add(metin, now=SIMDI, tzid=tzid)


def _yerel(an, tzid=IST) -> str:
    """Okunur yerel damga."""
    return to_local(an, tzid).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Göreceli günler
# ---------------------------------------------------------------------------

def test_yarin_ve_saat():
    """Blueprint'teki örnek: 'yarın 14:00 diş hekimi'."""
    r = _coz("yarın 14:00 diş hekimi")

    assert r.title == "diş hekimi"
    assert _yerel(r.start_utc) == "2026-09-14 14:00"
    assert _yerel(r.end_utc) == "2026-09-14 15:00", "varsayılan süre 1 saat"
    assert r.all_day is False


def test_bugun_ve_obur_gun():
    """'bugün' ve 'öbür gün' doğru güne düşer."""
    assert _yerel(_coz("bugün 09:00 x").start_utc) == "2026-09-13 09:00"
    assert _yerel(_coz("öbür gün 09:00 x").start_utc) == "2026-09-15 09:00"


# ---------------------------------------------------------------------------
# Gün adları
# ---------------------------------------------------------------------------

def test_gun_adi_ileriye_bakar():
    """Pazar günü 'pazartesi' ertesi gündür."""
    assert _yerel(_coz("pazartesi 9da algoritma").start_utc) == "2026-09-14 09:00"
    assert _coz("pazartesi 9da algoritma").title == "algoritma"


def test_onumuzdeki_bir_hafta_ekler():
    """'önümüzdeki cuma' bu haftanınkini değil sonrakini kasteder."""
    bu_cuma = _yerel(_coz("cuma 10:00 x").start_utc)
    onumuzdeki = _yerel(_coz("önümüzdeki cuma 10:00 x").start_utc)

    assert bu_cuma == "2026-09-18 10:00"
    assert onumuzdeki == "2026-09-25 10:00"


def test_aynı_gun_adi_bugunu_verir():
    """Pazar günü 'pazar' bugündür."""
    assert _yerel(_coz("pazar 16:00 x").start_utc) == "2026-09-13 16:00"


# ---------------------------------------------------------------------------
# Açık tarihler
# ---------------------------------------------------------------------------

def test_gun_ay_adi():
    """'3 ekim 10:00 sınav'."""
    r = _coz("3 ekim 10:00 sınav")
    assert _yerel(r.start_utc) == "2026-10-03 10:00"
    assert r.title == "sınav"


def test_gecmis_tarih_gelecek_yila_kayar():
    """Yıl verilmemiş ve tarih geçmişse gelecek yıl kastedilmiştir."""
    r = _coz("3 ocak 10:00 x")  # referans Eylül 2026
    assert _yerel(r.start_utc) == "2027-01-03 10:00"


def test_sayisal_tarih_yil_ile():
    """'15.10.2026 09:00' saat sanılmamalı.

    Regresyon: tarih saatten önce çıkarılmazsa '15.10' saat 15:10 olarak
    okunuyordu ve başlıkta '.2026' artığı kalıyordu.
    """
    r = _coz("15.10.2026 09:00 vize")
    assert _yerel(r.start_utc) == "2026-10-15 09:00"
    assert r.title == "vize"


def test_gecersiz_sayisal_tarih_saat_olarak_okunur():
    """'13.30' tarih değil saattir; ayrıştırma iptal olmamalı.

    Regresyon: gün 13 / ay 30 geçersiz olunca tarih çözümü tamamen
    duruyordu ve 'önümüzdeki cuma' hiç görülmüyordu.
    """
    r = _coz("önümüzdeki cuma 13.30 kod gözden geçirme")
    assert _yerel(r.start_utc) == "2026-09-25 13:30"
    assert r.title == "kod gözden geçirme"


# ---------------------------------------------------------------------------
# Saat biçimleri
# ---------------------------------------------------------------------------

def test_saat_onekli():
    """'saat 9' işaret sayılır."""
    r = _coz("salı saat 9 toplantı")
    assert _yerel(r.start_utc) == "2026-09-15 09:00"
    assert r.title == "toplantı"


def test_bulunma_eki():
    """'9da', '14'te' gibi ekler saat işaretidir."""
    assert _yerel(_coz("yarın 9da x").start_utc) == "2026-09-14 09:00"
    assert _yerel(_coz("yarın 14'te x").start_utc) == "2026-09-14 14:00"


def test_isaretsiz_sayi_saat_sayilmaz():
    """İşareti olmayan çıplak sayı saat DEĞİL.

    Bilinçli karar: '3 ekim 10 kişilik toplantı' gibi ifadelerde 10'u saat
    sanmaktansa zamanı bulamamış olmayı tercih ediyoruz. Yanlış saate sessizce
    kaydetmek, kaydetmemekten kötüdür.
    """
    r = _coz("yarın 14 diş hekimi")
    assert r.all_day is True
    assert "14" in r.title


# ---------------------------------------------------------------------------
# Aralık ve süre
# ---------------------------------------------------------------------------

def test_saat_araligi():
    """'15:30-17:00' başlangıç ve bitişi birlikte verir."""
    r = _coz("bugün 15:30-17:00 sprint planlama")
    assert _yerel(r.start_utc) == "2026-09-13 15:30"
    assert _yerel(r.end_utc) == "2026-09-13 17:00"
    assert r.title == "sprint planlama"


def test_gece_yarisini_asan_aralik():
    """Bitiş başlangıçtan küçükse ertesi güne sarkar."""
    r = _coz("23:00-01:00 gece nöbeti")
    assert _yerel(r.start_utc) == "2026-09-13 23:00"
    assert _yerel(r.end_utc) == "2026-09-14 01:00"


def test_sure_ifadesi():
    """'90 dakika' ve '2 saat' süreyi belirler."""
    assert _coz("perşembe 90 dakika 11:00 seminer").end_utc - _coz(
        "perşembe 90 dakika 11:00 seminer"
    ).start_utc == timedelta(minutes=90)

    r = _coz("öbür gün 2 saat 14:00 atölye")
    assert r.end_utc - r.start_utc == timedelta(hours=2)
    assert r.title == "atölye", "süre ve saat başlıktan temizlenmeli"


def test_sure_saat_onekiyle_cakismaz():
    """'2 saat 14:00' içindeki 'saat 14:00' deseni süreyi yutmamalı.

    Regresyon: süre saatten sonra çıkarılınca span'ler çakışıyor ve saat
    ifadesi başlıkta kalıyordu.
    """
    r = _coz("öbür gün 2 saat 14:00 atölye")
    assert _yerel(r.start_utc) == "2026-09-15 14:00"
    assert _yerel(r.end_utc) == "2026-09-15 16:00"


# ---------------------------------------------------------------------------
# Zaman bulunamayınca
# ---------------------------------------------------------------------------

def test_zaman_yoksa_tum_gun():
    """Saat yoksa bugünün tüm gün etkinliği, matched boş."""
    r = _coz("doğum günü")

    assert r.all_day is True
    assert r.title == "doğum günü"
    assert _yerel(r.start_utc) == "2026-09-13 00:00"
    assert _yerel(r.end_utc) == "2026-09-14 00:00"
    assert r.matched == "", "hiçbir zaman ifadesi tanınmadı"


def test_tarih_var_saat_yoksa_o_gunun_tum_gunu():
    """'çarşamba laboratuvar' -> çarşambanın tüm günü."""
    r = _coz("çarşamba laboratuvar")
    assert r.all_day is True
    assert _yerel(r.start_utc) == "2026-09-16 00:00"
    assert r.matched == "çarşamba"


def test_matched_taninan_ifadeyi_bildirir():
    """Arayüz kullanıcıya neyin tanındığını gösterebilsin."""
    r = _coz("yarın 14:00 diş hekimi")
    assert "yarın" in r.matched and "14:00" in r.matched


def test_bos_metin_reddedilir():
    """Boş girdi sessizce bir şey üretmez."""
    with pytest.raises(ValueError):
        _coz("   ")


def test_baslik_yoksa_yer_tutucu():
    """Sadece zaman verilmişse başlık boş kalmaz."""
    assert _coz("yarın 14:00").title == "(Başlıksız)"


# ---------------------------------------------------------------------------
# Saat dilimi
# ---------------------------------------------------------------------------

def test_farkli_dilimde_yorumlanir():
    """Duvar saati verilen dilimde yorumlanır."""
    r = parse_quick_add("yarın 14:00 standup", now=SIMDI, tzid=NY)

    assert r.tzid == NY
    assert to_local(r.start_utc, NY).strftime("%Y-%m-%d %H:%M") == "2026-09-14 14:00"
    # 14:00 EDT = 18:00 UTC
    assert r.start_utc.strftime("%H:%M") == "18:00"


def test_gecersiz_dilim_reddedilir():
    """Bozuk tzid erken patlar."""
    with pytest.raises(ValueError):
        parse_quick_add("yarın 14:00 x", now=SIMDI, tzid="Mars/Olympus")


# ---------------------------------------------------------------------------
# Bulunma eki başlığı yemesin
# ---------------------------------------------------------------------------

def test_saat_eki_sonraki_kelimeyi_yemez():
    """Regresyon: "11:30 tasarim" -> başlık "sarim" oluyordu.

    Bulunma eki deseni (`de|da|te|ta`) rakamla arasında boşluğa izin verince,
    ardından gelen kelimenin ilk iki harfini ek sanıp yiyordu. Türkçede bu
    harflerle başlayan kelime bol: tasarım, test, deneme, davet, tatil...
    Uygulamayı elle denerken çıktı.
    """
    r = _coz("yarın 10:00-11:30 tasarım görüşmesi")

    assert r.title == "tasarım görüşmesi"
    assert _yerel(r.start_utc) == "2026-09-14 10:00"
    assert _yerel(r.end_utc) == "2026-09-14 11:30"


@pytest.mark.parametrize(
    "metin, beklenen",
    [
        ("yarın 14:00 test", "test"),
        ("yarın 14:00 deneme", "deneme"),
        ("yarın 14:00 davet yemeği", "davet yemeği"),
        ("yarın 14:00 tatil planı", "tatil planı"),
        ("bugün 13:00-14:00 dava hazırlığı", "dava hazırlığı"),
        ("bugün 09:00-10:00 değerlendirme", "değerlendirme"),
    ],
)
def test_de_da_te_ta_ile_baslayan_basliklar(metin, beklenen):
    """Bu harflerle başlayan başlıklar bozulmadan geçmeli."""
    assert _coz(metin).title == beklenen


def test_bitisik_ek_hala_saat_isareti():
    """Düzeltme, gerçek ekleri bozmamalı: ek rakama BİTİŞİK olduğunda geçerli."""
    assert _yerel(_coz("yarın 9da toplantı").start_utc) == "2026-09-14 09:00"
    assert _coz("yarın 9da toplantı").title == "toplantı"

    assert _yerel(_coz("yarın 14'te diş hekimi").start_utc) == "2026-09-14 14:00"
    assert _coz("yarın 14'te diş hekimi").title == "diş hekimi"

    assert _yerel(_coz("yarın saat 9 toplantı").start_utc) == "2026-09-14 09:00"
    assert _coz("yarın saat 9 toplantı").title == "toplantı"


# ---------------------------------------------------------------------------
# "gelecek hafta salı" ailesi (elle kullanırken çıktı)
# ---------------------------------------------------------------------------

def test_gelecek_hafta_sali_sonraki_haftaya_duser():
    """'gelecek hafta salı' bu haftanın salısına DEĞİL, sonrakine.

    Desende niteleyiciden sonra 'hafta' yoktu: ifade hiç tanınmıyor, tarih
    sessizce bu haftanın salısına düşüyor ve 'gelecek hafta' başlıkta
    kalıyordu. Kullanıcı 22 Eylül'e yazdığını sanıp 15 Eylül'e yazıyordu.
    """
    r = _coz("gelecek hafta salı 14:00 toplantı")

    assert _yerel(r.start_utc) == "2026-09-22 14:00"
    assert r.title == "toplantı"


def test_onumuzdeki_hafta_da_ayni():
    """'önümüzdeki hafta salı' de aynı şekilde çözülmeli."""
    assert _yerel(_coz("önümüzdeki hafta salı 14:00 x").start_utc) == "2026-09-22 14:00"


def test_bu_hafta_sali_ayni_haftada_kalir():
    """'bu hafta salı' yakındaki salı; 'hafta' eklenmesi anlamı kaydırmasın."""
    assert _yerel(_coz("bu hafta salı 14:00 x").start_utc) == "2026-09-15 14:00"


def test_turkce_harfsiz_onumuzdeki():
    """Şapkasız yazan kullanıcı da doğru güne yazabilmeli.

    'haftaya sali' ve 'gelecek carsamba' zaten çalışıyordu ama 'onumuzdeki'
    desende yoktu: tarih bir hafta geriye kayıyor, üstelik kelime başlıkta
    kalıyordu ("onumuzdeki toplanti").
    """
    r = _coz("onumuzdeki sali 14:00 toplanti")

    assert _yerel(r.start_utc) == "2026-09-22 14:00"
    assert r.title == "toplanti"


def test_hafta_kelimesi_tek_basina_baslikta_kalir():
    """'hafta' yalnızca niteleyiciyle birlikte yutulur, tek başına değil."""
    r = _coz("salı 14:00 hafta değerlendirmesi")

    assert _yerel(r.start_utc) == "2026-09-15 14:00"
    assert r.title == "hafta değerlendirmesi"


# ---------------------------------------------------------------------------
# Tekrar ("her salı 10:00 ders")
# ---------------------------------------------------------------------------

def test_her_sali_haftalik_seri_kurar():
    """Tekrar motoru baştan beri vardı, söyleyecek yer yoktu.

    Öncesinde "her" sessizce başlığa yapışıyor ("her ders") ve tek seferlik
    bir etkinlik oluşuyordu: kullanıcı dönem boyu dersini kurduğunu sanıp tek
    bir kayıt alıyordu.
    """
    r = _coz("her salı 10:00 ders")

    assert r.rrule == "FREQ=WEEKLY"
    assert r.title == "ders"
    assert _yerel(r.start_utc) == "2026-09-15 10:00", "ilk salıdan başlamalı"


def test_her_gun_gunluk():
    """"her gün 07:00 koşu" günlük seri."""
    r = _coz("her gün 07:00 koşu")

    assert r.rrule == "FREQ=DAILY"
    assert r.title == "koşu"


def test_hafta_ici_bes_gun():
    """"hafta içi" pazartesi-cuma demek; hafta sonu dahil değil."""
    r = _coz("hafta içi 09:00 mesai")

    assert r.rrule == "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
    assert r.title == "mesai"


def test_her_ay_tarihle_birlikte():
    """"her ay 1 ekim 10:00 kira": tarih de tekrar da tanınmalı."""
    r = _coz("her ay 1 ekim 10:00 kira")

    assert r.rrule == "FREQ=MONTHLY"
    assert _yerel(r.start_utc) == "2026-10-01 10:00"
    assert r.title == "kira"


def test_tekrarsiz_ifade_rrule_uretmez():
    """Niteliksiz "salı 10:00 ders" tek seferlik kalmalı."""
    assert _coz("salı 10:00 ders").rrule is None


def test_turkce_harfsiz_tekrar():
    """"her carsamba" da çalışmalı."""
    r = _coz("her carsamba 14:00 toplanti")

    assert r.rrule == "FREQ=WEEKLY"
    assert _yerel(r.start_utc) == "2026-09-16 14:00"


def test_her_kelimesi_baslikta_kalmiyor():
    """"her" tanındıysa başlıktan kesilmeli."""
    assert "her" not in _coz("her salı 10:00 ders").title.lower()
