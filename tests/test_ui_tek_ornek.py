"""Tek örnek kilidi.

Ölçülen davranış: kısayola ikinci kez tıklamak ikinci bir Takvim AÇMAMALI.
Açarsa aynı veritabanına iki süreç yazar ve kullanıcı iki ayrı pencerede
farklı şeyler görür.
"""

from __future__ import annotations

import os
import sys

import pytest

from ui.tek_ornek import kilit_adi, kilit_al, pencereyi_one_al, pid_oku, pid_yaz


def _benzersiz_yol(ad: str) -> str:
    """Bu test SÜRECİNE özel sahte veritabanı yolu.

    Mutex adı işletim sistemi genelinde: sabit bir yol kullanırsak aynı anda
    çalışan İKİNCİ bir test koşusu (paralel ajan, açık bir IDE) kilidi önce
    alır ve testler sebepsiz kırmızıya döner. Bir kez yaşandı.
    """
    return f"C:/Takvim/test-{os.getpid()}-{ad}.db"


def test_ayni_veritabani_ayni_kilit():
    """Aynı veriye giden iki çalıştırma aynı kilidi paylaşır."""
    assert kilit_adi(r"C:\Users\x\Takvim\takvim.db") == kilit_adi(
        r"C:\Users\x\Takvim\takvim.db"
    )


def test_farkli_veritabani_farkli_kilit():
    """`--db deneme.db` ile ikinci bir örnek açmak meşru; engellenmemeli."""
    assert kilit_adi("takvim.db") != kilit_adi("deneme.db")


def test_kilit_adi_buyuk_kucuk_harf_ayirmaz():
    """Windows dosya yolları harf duyarsız; kilit de öyle olmalı.

    Olmazsa kısayol `C:\\Users\\...` , elle çalıştırma `c:\\users\\...` yazdığı
    için iki AYRI kilit alınır ve tek örnek garantisi sessizce kaybolur.
    """
    assert kilit_adi(r"C:\Takvim\takvim.db") == kilit_adi(r"c:\takvim\TAKVIM.DB")


def test_kilit_adi_ters_bolu_icermez():
    """Mutex adında `\\` ayraç anlamına geliyor; yol doğrudan konamaz."""
    ad = kilit_adi(r"C:\Users\Arda\Takvim\takvim.db")

    assert ad.startswith("Local\\")
    assert "\\" not in ad[len("Local\\") :]


@pytest.mark.skipif(sys.platform != "win32", reason="mutex yalnızca Windows'ta")
def test_ikinci_kilit_reddedilir():
    """Aynı ad ikinci kez alınamaz — tek örneğin dayandığı davranış bu."""
    ad = kilit_adi(_benzersiz_yol("ikinci-kilit"))

    ilk, tutamak = kilit_al(ad)
    ikinci, _ = kilit_al(ad)

    assert ilk is True
    assert ikinci is False
    assert tutamak  # tutamağı bırakmıyoruz: süreç boyunca kilit bizde


@pytest.mark.skipif(sys.platform != "win32", reason="mutex yalnızca Windows'ta")
def test_farkli_ad_ayri_kilit():
    """Farklı veritabanları birbirini engellemiyor."""
    ilk, _ = kilit_al(kilit_adi(_benzersiz_yol("a")))
    ikinci, _ = kilit_al(kilit_adi(_benzersiz_yol("b")))

    assert (ilk, ikinci) == (True, True)


def test_pencere_bulununca_true():
    """Var olan pencere bulunuyor (Win32 çağrısı sahte listeyle atlanıyor)."""
    sahte = lambda: [(1, "Bir Başka Program", 10), (2, "Takvim", 11)]  # noqa: E731

    assert pencereyi_one_al("Takvim", listele=sahte) is True


def test_pencere_yoksa_false():
    """Pencere henüz açılmamışsa çağıran sessizce devam edebilsin."""
    sahte = lambda: [(1, "Bir Başka Program", 10)]  # noqa: E731

    assert pencereyi_one_al("Takvim", listele=sahte) is False


def test_baslik_tam_eslesmeli():
    """"Takvim Yedekleme" gibi başka bir pencereyi öne almayalım."""
    sahte = lambda: [(1, "Takvim Yedekleme", 10), (2, "Takvimler", 11)]  # noqa: E731

    assert pencereyi_one_al("Takvim", listele=sahte) is False


def test_listeleme_patlarsa_false():
    """Win32 erişilemezse tek örnek kontrolü uygulamayı düşürmesin."""

    def patla():
        raise OSError("erişilemedi")

    assert pencereyi_one_al("Takvim", listele=patla) is False


def test_pid_yazilip_okunur(tmp_path):
    """Çalışan örnek kendi süreç numarasını bırakıyor."""
    import os

    assert pid_yaz(tmp_path) is True
    assert pid_oku(tmp_path) == os.getpid()


def test_pid_yoksa_none(tmp_path):
    """İlk açılışta kayıt yok; çağıran başlığa göre aramaya düşebilir."""
    assert pid_oku(tmp_path) is None


def test_bozuk_pid_dosyasi_none(tmp_path):
    """Yarım yazılmış dosya yüzünden ikinci açılış patlamasın."""
    (tmp_path / "ornek.pid").write_text("abc", encoding="utf-8")

    assert pid_oku(tmp_path) is None


def test_ayni_baslikli_baska_surec_one_alinmaz():
    """Veri klasörünü açan Explorer penceresinin başlığı da "Takvim" oluyor.

    Süreç numarası verildiğinde yalnızca BİZİM pencereye bakılmalı; yoksa
    kısayola ikinci tık Takvim'i değil Explorer'ı öne alıyor.
    """
    sahte = lambda: [(1, "Takvim", 999), (2, "Takvim", 1234)]  # noqa: E731

    assert pencereyi_one_al("Takvim", pid=1234, listele=sahte) is True
    assert pencereyi_one_al("Takvim", pid=555, listele=sahte) is False
