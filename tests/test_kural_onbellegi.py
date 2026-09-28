"""Kural kümesi önbelleği (core/recurrence.py).

Önbellek yalnızca hız için var: sonucu ASLA değiştirmemeli, thread'ler
arasında paylaşılmamalı ve yoğun bir seriyi kalıcı olarak tutmamalı.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import timedelta

import pytest

from core import Override, expand, recurrence
from tests.helpers import IST, NY, ist, make_event, ny


@pytest.fixture(autouse=True)
def bos_onbellek():
    """Her test boş önbellekle başlasın; önceki testin kümesi sızmasın."""
    vars(recurrence._yerel).clear()
    yield
    vars(recurrence._yerel).clear()


def _onbelleksiz(event, overrides, bas, bit):
    """Aynı çağrı, boş önbellekli yeni bir thread'de.

    Ana thread'in (ısınmış) önbelleğine dokunmadan referans sonuç üretir.
    """
    sonuc = []
    t = threading.Thread(target=lambda: sonuc.append(expand(event, overrides, bas, bit)))
    t.start()
    t.join()
    return sonuc[0]


def _haftalik_ny():
    """Pazartesi 09:00 (New York), 2025'ten beri: pencere DST geçişini (8 Mart 2026) içeriyor."""
    return make_event(ny(2025, 1, 6, 9), ny(2025, 1, 6, 10), tzid=NY, rrule="FREQ=WEEKLY")


def test_ayni_seri_ikinci_renderda_yeniden_kurulmaz(monkeypatch):
    """Önbelleğin varlık sebebi: seri her render'da DTSTART'tan kurulup yürünmesin."""
    kurulan = []
    asil = recurrence._ruleset
    monkeypatch.setattr(recurrence, "_ruleset", lambda e: kurulan.append(e) or asil(e))
    event = make_event(ist(2024, 1, 1, 9), ist(2024, 1, 1, 10), rrule="FREQ=DAILY")

    expand(event, [], ist(2026, 9, 28), ist(2026, 10, 5))
    expand(event, [], ist(2026, 10, 5), ist(2026, 10, 12))

    assert len(kurulan) == 1


@pytest.mark.parametrize(
    "degisiklik",
    [
        pytest.param({"rrule": "FREQ=DAILY"}, id="rrule"),
        pytest.param(
            {"start_utc": ny(2025, 1, 7, 9), "end_utc": ny(2025, 1, 7, 10)}, id="start_utc"
        ),
        pytest.param({"tzid": IST}, id="tzid"),
        pytest.param({"rdate": (ny(2026, 3, 11, 9),)}, id="rdate"),
        pytest.param({"exdate": (ny(2026, 3, 9, 9),)}, id="exdate"),
    ],
)
def test_kural_alani_degisince_eski_kume_kullanilmaz(degisiklik):
    """`_ruleset`'in okuduğu her alan anahtarda olmalı; yoksa düzenlenen seri eski hâliyle çizilir."""
    taban = _haftalik_ny()
    degismis = replace(taban, **degisiklik)
    bas, bit = ny(2026, 3, 1), ny(2026, 3, 29)
    taban_sonucu = expand(taban, [], bas, bit)  # önbelleği eski kümeyle ısıtır
    beklenen = _onbelleksiz(degismis, [], bas, bit)
    assert beklenen != taban_sonucu, "değişiklik sonucu etkilemeli, yoksa test bir şey ölçmez"

    assert expand(degismis, [], bas, bit) == beklenen


def test_her_thread_kendi_kumesini_kullanir():
    """Sunucu ve hatırlatıcı thread'i aynı kümeyi PAYLAŞMAMALI.

    dateutil'in önbellekli yinelemesi tükenince kilidini bırakmıyor; paylaşılan
    bir kümede bekleyen thread sonsuza dek kilitlenebilir.
    """
    event = make_event(ist(2024, 1, 1, 9), ist(2024, 1, 1, 10), rrule="FREQ=DAILY")
    ana = recurrence._onbellekli_ruleset(event)
    diger = []
    t = threading.Thread(target=lambda: diger.append(recurrence._onbellekli_ruleset(event)))
    t.start()
    t.join()

    assert diger[0] is not ana


def test_buyuyen_kume_onbellekte_tutulmaz(monkeypatch):
    """Pencereye varana dek çok örnek yürüyen seri kalıcı tutulmamalı (TKV-API-001)."""
    monkeypatch.setattr(recurrence, "_ONBELLEK_MAKS_ORNEK", 50)
    event = make_event(ist(2025, 1, 1, 9), ist(2025, 1, 1, 10), rrule="FREQ=DAILY")

    expand(event, [], ist(2026, 1, 1), ist(2026, 1, 8))  # ~365 örnek yürür

    assert recurrence._kural_anahtari(event) not in recurrence._yerel.kumeler


def test_onbellek_dolunca_en_eski_kume_duser(monkeypatch):
    """Önbellek sınırsız büyümemeli: sınır aşılınca en uzun süre KULLANILMAYAN düşer.

    İlk seri üçüncüden önce yeniden çiziliyor; en eski EKLENENİ atan bir
    önbellek (FIFO) onu atardı, sık bakılan seri her seferinde baştan kurulurdu.
    """
    monkeypatch.setattr(recurrence, "_ONBELLEK_KURAL", 2)
    a, b, c = (
        make_event(ist(2026, 1, gun, 9), ist(2026, 1, gun, 10), rrule="FREQ=WEEKLY")
        for gun in (5, 6, 7)
    )
    for event in (a, b, a, c):
        expand(event, [], ist(2026, 2, 1), ist(2026, 2, 8))

    assert list(recurrence._yerel.kumeler) == [
        recurrence._kural_anahtari(a),
        recurrence._kural_anahtari(c),
    ]


def test_onbellekli_sonuc_onbelleksizle_birebir_ayni():
    """İleri/geri/uzağa gezinirken ısınmış önbellek, boş önbellekle aynı örnekleri vermeli."""
    haftalik = replace(_haftalik_ny(), exdate=(ny(2026, 3, 9, 9),))
    tasinan = Override(
        event_id=1,
        original_start_utc=ny(2025, 6, 2, 9),  # geçen yıldan bu haftaya taşındı
        new_start_utc=ny(2026, 3, 18, 14),
        new_end_utc=ny(2026, 3, 18, 15),
    )
    iptal = Override(event_id=1, original_start_utc=ny(2026, 3, 16, 9), cancelled=True)
    seriler = [
        (haftalik, [tasinan, iptal]),
        (make_event(ist(2024, 1, 1, 8), ist(2024, 1, 1, 9), rrule="FREQ=DAILY",
                    event_id=2, uid="gunluk"), []),
        (make_event(ny(2025, 1, 31, 18), ny(2025, 1, 31, 19), tzid=NY,
                    rrule="FREQ=MONTHLY;BYDAY=-1FR", event_id=3, uid="aylik"), []),
        (make_event(ist(2025, 9, 1, 7, 30), ist(2025, 9, 1, 8), rrule="FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
                    rdate=(ist(2026, 3, 14, 7, 30),), event_id=4, uid="haftaici"), []),
        (make_event(ist(2025, 1, 1, 23), ist(2025, 1, 1, 23) + timedelta(hours=2),
                    rrule="FREQ=DAILY", event_id=5, uid="gece"), []),
        (make_event(ist(2026, 2, 2, 10), ist(2026, 2, 2, 11), rrule="FREQ=WEEKLY;COUNT=10",
                    event_id=6, uid="sayili"), []),
    ]
    pencereler = [
        (ny(2026, 3, 2), ny(2026, 3, 9)),    # DST haftası
        (ny(2026, 3, 9), ny(2026, 3, 16)),   # ileri
        (ny(2026, 2, 23), ny(2026, 3, 2)),   # geri
        (ny(2026, 3, 1), ny(2026, 4, 1)),    # ay
        (ny(2027, 6, 1), ny(2027, 6, 8)),    # uzak gelecek
        (ny(2025, 6, 1), ny(2025, 6, 8)),    # geçmişe dönüş (taşınanın eski yeri)
        (ny(2026, 3, 15), ny(2026, 3, 22)),  # taşınan + iptal edilen
        (ny(2026, 4, 1), ny(2026, 5, 1)),    # sayılı seri bittikten sonra
    ]

    farklar = []
    for bas, bit in pencereler:
        for event, overrides in seriler:
            gercek = expand(event, overrides, bas, bit)
            if gercek != _onbelleksiz(event, overrides, bas, bit):
                farklar.append((event.uid, bas.date()))

    assert farklar == []
