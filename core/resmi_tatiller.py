"""Türkiye resmi tatilleri: saf veri + saf sorgu (DB, dosya, ekran bilmez).

Tatiller KULLANICI VERİSİ DEĞİLDİR: veritabanına yazılmaz, `.ics`/senkrona girmez,
düzenlenmez. Sunum katmanı gün hücresine yalnız okunur şerit olarak koyar.

Kapsam: sabit ulusal günler (2429 sayılı Kanun) HER yıl için kuraldan; dini bayramlar
yalnızca aşağıdaki tabloda olan yıllar için (2024-2035, bazı yıllar eksik). Tablonun
kapsamadığı yılda dini bayram GÖSTERİLMEZ -- uydurma tarih göstermektense eksik
bırakmak doğru. 2024-2027 Diyanet takvimiyle uyumlu; 2028+ hesaplamaya dayalı
tahmindir ve Diyanet açıklayınca 1 gün kayabilir. Kaynaklar çelişen bayramlar
(Ramazan 2028-2030, Kurban 2030) kasten dışarıda. Hükümetin köprü günüyle tatili
uzatması dahil değil. Arife = öğleden sonra yarım gün.

Mobil uygulama AYNI tabloyu kullanır; adlar ve tarihler değişirse ikisi birlikte güncellenir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

__all__ = ["Tatil", "resmi_tatiller"]


@dataclass(frozen=True)
class Tatil:
    tarih: date
    ad_tr: str
    ad_en: str
    yarim_gun: bool
    tur: str  # "ulusal" | "dini"


# (ay, gün, ad_tr, ad_en, yarım gün)
_SABIT: tuple[tuple[int, int, str, str, bool], ...] = (
    (1, 1, "Yılbaşı", "New Year's Day", False),
    (4, 23, "Ulusal Egemenlik ve Çocuk Bayramı", "National Sovereignty and Children's Day", False),
    (5, 1, "Emek ve Dayanışma Günü", "Labour and Solidarity Day", False),
    (5, 19, "Atatürk'ü Anma, Gençlik ve Spor Bayramı", "Commemoration of Atatürk, Youth and Sports Day", False),
    (7, 15, "Demokrasi ve Milli Birlik Günü", "Democracy and National Unity Day", False),
    (8, 30, "Zafer Bayramı", "Victory Day", False),
    (10, 28, "Cumhuriyet Bayramı Arifesi", "Eve of Republic Day", True),
    (10, 29, "Cumhuriyet Bayramı", "Republic Day", False),
)

# (tarih, ad_tr, ad_en, yarım gün)
_DINI: tuple[tuple[str, str, str, bool], ...] = (
    ("2024-04-09", 'Ramazan Bayramı Arifesi', 'Eve of Eid al-Fitr', True),
    ("2024-04-10", 'Ramazan Bayramı 1. Gün', 'Eid al-Fitr Day 1', False),
    ("2024-04-11", 'Ramazan Bayramı 2. Gün', 'Eid al-Fitr Day 2', False),
    ("2024-04-12", 'Ramazan Bayramı 3. Gün', 'Eid al-Fitr Day 3', False),
    ("2024-06-15", 'Kurban Bayramı Arifesi', 'Eve of Eid al-Adha', True),
    ("2024-06-16", 'Kurban Bayramı 1. Gün', 'Eid al-Adha Day 1', False),
    ("2024-06-17", 'Kurban Bayramı 2. Gün', 'Eid al-Adha Day 2', False),
    ("2024-06-18", 'Kurban Bayramı 3. Gün', 'Eid al-Adha Day 3', False),
    ("2024-06-19", 'Kurban Bayramı 4. Gün', 'Eid al-Adha Day 4', False),
    ("2025-03-29", 'Ramazan Bayramı Arifesi', 'Eve of Eid al-Fitr', True),
    ("2025-03-30", 'Ramazan Bayramı 1. Gün', 'Eid al-Fitr Day 1', False),
    ("2025-03-31", 'Ramazan Bayramı 2. Gün', 'Eid al-Fitr Day 2', False),
    ("2025-04-01", 'Ramazan Bayramı 3. Gün', 'Eid al-Fitr Day 3', False),
    ("2025-06-05", 'Kurban Bayramı Arifesi', 'Eve of Eid al-Adha', True),
    ("2025-06-06", 'Kurban Bayramı 1. Gün', 'Eid al-Adha Day 1', False),
    ("2025-06-07", 'Kurban Bayramı 2. Gün', 'Eid al-Adha Day 2', False),
    ("2025-06-08", 'Kurban Bayramı 3. Gün', 'Eid al-Adha Day 3', False),
    ("2025-06-09", 'Kurban Bayramı 4. Gün', 'Eid al-Adha Day 4', False),
    ("2026-03-19", 'Ramazan Bayramı Arifesi', 'Eve of Eid al-Fitr', True),
    ("2026-03-20", 'Ramazan Bayramı 1. Gün', 'Eid al-Fitr Day 1', False),
    ("2026-03-21", 'Ramazan Bayramı 2. Gün', 'Eid al-Fitr Day 2', False),
    ("2026-03-22", 'Ramazan Bayramı 3. Gün', 'Eid al-Fitr Day 3', False),
    ("2026-05-26", 'Kurban Bayramı Arifesi', 'Eve of Eid al-Adha', True),
    ("2026-05-27", 'Kurban Bayramı 1. Gün', 'Eid al-Adha Day 1', False),
    ("2026-05-28", 'Kurban Bayramı 2. Gün', 'Eid al-Adha Day 2', False),
    ("2026-05-29", 'Kurban Bayramı 3. Gün', 'Eid al-Adha Day 3', False),
    ("2026-05-30", 'Kurban Bayramı 4. Gün', 'Eid al-Adha Day 4', False),
    ("2027-03-08", 'Ramazan Bayramı Arifesi', 'Eve of Eid al-Fitr', True),
    ("2027-03-09", 'Ramazan Bayramı 1. Gün', 'Eid al-Fitr Day 1', False),
    ("2027-03-10", 'Ramazan Bayramı 2. Gün', 'Eid al-Fitr Day 2', False),
    ("2027-03-11", 'Ramazan Bayramı 3. Gün', 'Eid al-Fitr Day 3', False),
    ("2027-05-15", 'Kurban Bayramı Arifesi', 'Eve of Eid al-Adha', True),
    ("2027-05-16", 'Kurban Bayramı 1. Gün', 'Eid al-Adha Day 1', False),
    ("2027-05-17", 'Kurban Bayramı 2. Gün', 'Eid al-Adha Day 2', False),
    ("2027-05-18", 'Kurban Bayramı 3. Gün', 'Eid al-Adha Day 3', False),
    ("2027-05-19", 'Kurban Bayramı 4. Gün', 'Eid al-Adha Day 4', False),
    ("2028-05-04", 'Kurban Bayramı Arifesi', 'Eve of Eid al-Adha', True),
    ("2028-05-05", 'Kurban Bayramı 1. Gün', 'Eid al-Adha Day 1', False),
    ("2028-05-06", 'Kurban Bayramı 2. Gün', 'Eid al-Adha Day 2', False),
    ("2028-05-07", 'Kurban Bayramı 3. Gün', 'Eid al-Adha Day 3', False),
    ("2028-05-08", 'Kurban Bayramı 4. Gün', 'Eid al-Adha Day 4', False),
    ("2029-04-23", 'Kurban Bayramı Arifesi', 'Eve of Eid al-Adha', True),
    ("2029-04-24", 'Kurban Bayramı 1. Gün', 'Eid al-Adha Day 1', False),
    ("2029-04-25", 'Kurban Bayramı 2. Gün', 'Eid al-Adha Day 2', False),
    ("2029-04-26", 'Kurban Bayramı 3. Gün', 'Eid al-Adha Day 3', False),
    ("2029-04-27", 'Kurban Bayramı 4. Gün', 'Eid al-Adha Day 4', False),
    ("2030-02-03", 'Ramazan Bayramı Arifesi', 'Eve of Eid al-Fitr', True),
    ("2030-02-04", 'Ramazan Bayramı 1. Gün', 'Eid al-Fitr Day 1', False),
    ("2030-02-05", 'Ramazan Bayramı 2. Gün', 'Eid al-Fitr Day 2', False),
    ("2030-02-06", 'Ramazan Bayramı 3. Gün', 'Eid al-Fitr Day 3', False),
    ("2031-01-23", 'Ramazan Bayramı Arifesi', 'Eve of Eid al-Fitr', True),
    ("2031-01-24", 'Ramazan Bayramı 1. Gün', 'Eid al-Fitr Day 1', False),
    ("2031-01-25", 'Ramazan Bayramı 2. Gün', 'Eid al-Fitr Day 2', False),
    ("2031-01-26", 'Ramazan Bayramı 3. Gün', 'Eid al-Fitr Day 3', False),
    ("2031-04-01", 'Kurban Bayramı Arifesi', 'Eve of Eid al-Adha', True),
    ("2031-04-02", 'Kurban Bayramı 1. Gün', 'Eid al-Adha Day 1', False),
    ("2031-04-03", 'Kurban Bayramı 2. Gün', 'Eid al-Adha Day 2', False),
    ("2031-04-04", 'Kurban Bayramı 3. Gün', 'Eid al-Adha Day 3', False),
    ("2031-04-05", 'Kurban Bayramı 4. Gün', 'Eid al-Adha Day 4', False),
    ("2032-01-13", 'Ramazan Bayramı Arifesi', 'Eve of Eid al-Fitr', True),
    ("2032-01-14", 'Ramazan Bayramı 1. Gün', 'Eid al-Fitr Day 1', False),
    ("2032-01-15", 'Ramazan Bayramı 2. Gün', 'Eid al-Fitr Day 2', False),
    ("2032-01-16", 'Ramazan Bayramı 3. Gün', 'Eid al-Fitr Day 3', False),
    ("2032-03-21", 'Kurban Bayramı Arifesi', 'Eve of Eid al-Adha', True),
    ("2032-03-22", 'Kurban Bayramı 1. Gün', 'Eid al-Adha Day 1', False),
    ("2032-03-23", 'Kurban Bayramı 2. Gün', 'Eid al-Adha Day 2', False),
    ("2032-03-24", 'Kurban Bayramı 3. Gün', 'Eid al-Adha Day 3', False),
    ("2032-03-25", 'Kurban Bayramı 4. Gün', 'Eid al-Adha Day 4', False),
    ("2033-01-01", 'Ramazan Bayramı Arifesi', 'Eve of Eid al-Fitr', True),
    ("2033-01-02", 'Ramazan Bayramı 1. Gün', 'Eid al-Fitr Day 1', False),
    ("2033-01-03", 'Ramazan Bayramı 2. Gün', 'Eid al-Fitr Day 2', False),
    ("2033-01-04", 'Ramazan Bayramı 3. Gün', 'Eid al-Fitr Day 3', False),
    ("2033-03-10", 'Kurban Bayramı Arifesi', 'Eve of Eid al-Adha', True),
    ("2033-03-11", 'Kurban Bayramı 1. Gün', 'Eid al-Adha Day 1', False),
    ("2033-03-12", 'Kurban Bayramı 2. Gün', 'Eid al-Adha Day 2', False),
    ("2033-03-13", 'Kurban Bayramı 3. Gün', 'Eid al-Adha Day 3', False),
    ("2033-03-14", 'Kurban Bayramı 4. Gün', 'Eid al-Adha Day 4', False),
    ("2033-12-22", 'Ramazan Bayramı Arifesi', 'Eve of Eid al-Fitr', True),
    ("2033-12-23", 'Ramazan Bayramı 1. Gün', 'Eid al-Fitr Day 1', False),
    ("2033-12-24", 'Ramazan Bayramı 2. Gün', 'Eid al-Fitr Day 2', False),
    ("2033-12-25", 'Ramazan Bayramı 3. Gün', 'Eid al-Fitr Day 3', False),
    ("2034-02-28", 'Kurban Bayramı Arifesi', 'Eve of Eid al-Adha', True),
    ("2034-03-01", 'Kurban Bayramı 1. Gün', 'Eid al-Adha Day 1', False),
    ("2034-03-02", 'Kurban Bayramı 2. Gün', 'Eid al-Adha Day 2', False),
    ("2034-03-03", 'Kurban Bayramı 3. Gün', 'Eid al-Adha Day 3', False),
    ("2034-03-04", 'Kurban Bayramı 4. Gün', 'Eid al-Adha Day 4', False),
    ("2034-12-11", 'Ramazan Bayramı Arifesi', 'Eve of Eid al-Fitr', True),
    ("2034-12-12", 'Ramazan Bayramı 1. Gün', 'Eid al-Fitr Day 1', False),
    ("2034-12-13", 'Ramazan Bayramı 2. Gün', 'Eid al-Fitr Day 2', False),
    ("2034-12-14", 'Ramazan Bayramı 3. Gün', 'Eid al-Fitr Day 3', False),
    ("2035-02-17", 'Kurban Bayramı Arifesi', 'Eve of Eid al-Adha', True),
    ("2035-02-18", 'Kurban Bayramı 1. Gün', 'Eid al-Adha Day 1', False),
    ("2035-02-19", 'Kurban Bayramı 2. Gün', 'Eid al-Adha Day 2', False),
    ("2035-02-20", 'Kurban Bayramı 3. Gün', 'Eid al-Adha Day 3', False),
    ("2035-02-21", 'Kurban Bayramı 4. Gün', 'Eid al-Adha Day 4', False),
    ("2035-11-30", 'Ramazan Bayramı Arifesi', 'Eve of Eid al-Fitr', True),
    ("2035-12-01", 'Ramazan Bayramı 1. Gün', 'Eid al-Fitr Day 1', False),
    ("2035-12-02", 'Ramazan Bayramı 2. Gün', 'Eid al-Fitr Day 2', False),
    ("2035-12-03", 'Ramazan Bayramı 3. Gün', 'Eid al-Fitr Day 3', False),
)


def resmi_tatiller(baslangic: date, bitis: date) -> list[Tatil]:
    """[baslangic, bitis] (ikisi de dahil) aralığındaki tatiller, tarihe göre sıralı.

    Aynı güne iki kayıt düşebilir (örn. 2029-04-23: Ulusal Egemenlik + Kurban arifesi);
    o gün tam gün tatil yarım günlüğün ÖNÜNDE gelir.
    """
    sonuc: list[Tatil] = []
    for yil in range(baslangic.year, bitis.year + 1):
        for ay, gun, tr, en, yarim in _SABIT:
            sonuc.append(Tatil(date(yil, ay, gun), tr, en, yarim, "ulusal"))
    for tarih, tr, en, yarim in _DINI:
        sonuc.append(Tatil(date.fromisoformat(tarih), tr, en, yarim, "dini"))
    secili = [t for t in sonuc if baslangic <= t.tarih <= bitis]
    secili.sort(key=lambda t: (t.tarih, t.yarim_gun))
    return secili
