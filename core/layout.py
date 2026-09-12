"""Çakışan etkinliklerin kolon yerleşimi.

Hafta/gün görünümünde aynı saate denk gelen etkinlikleri yan yana dizmek,
herkesin hafife aldığı ve sonra en çok acıtan kısım. Burada saf fonksiyon
olarak duruyor: piksel yok, koordinat yok, yan etki yok. UI'ya gömersen bir
daha test edemezsin.

Çıktı `(occurrence, kolon_indeksi, kolon_sayısı)` üçlüleri; UI bunlardan
genişlik = 1 / kolon_sayısı, sol = kolon_indeksi * genişlik hesaplar.
"""

from __future__ import annotations

from datetime import datetime

from .models import Occurrence

__all__ = ["layout"]


def _sort_key(occ: Occurrence) -> tuple:
    """Başlangıca göre sırala; eşitlikte uzun olan önce, sonra kararlı bir kırıcı.

    Kararlı sıralama şart: aynı girdi her çağrıda aynı kolonları üretmezse
    ekran her yeniden çizimde titrer.
    """
    return (
        occ.start_utc,
        -(occ.end_utc - occ.start_utc).total_seconds(),
        occ.uid,
        occ.title,
    )


def layout(occurrences: list[Occurrence]) -> list[tuple[Occurrence, int, int]]:
    """Occurrence'ları çakışmaya göre kolonlara yerleştirir.

    Algoritma:
    1. start'a göre sırala
    2. birbirine değen etkinlikleri cluster'lara ayır (yeni start, cluster'daki
       maksimum bitişten büyük veya eşitse yeni cluster başlar -- yani 10-11 ve
       11-12 ayrı cluster, ikisi de tam genişlik)
    3. her cluster içinde greedy: son elemanı çakışmayan İLK kolona koy
    4. (occurrence, kolon_indeksi, cluster'ın kolon sayısı) döndür

    all_day etkinlikleri burada ayıklanmaz; tüm gün şeridini ayırmak UI'nın
    işi, bu fonksiyon kendisine ne verilirse onu yerleştirir.
    """
    items = sorted(occurrences, key=_sort_key)
    result: list[tuple[Occurrence, int, int]] = []

    cluster: list[tuple[Occurrence, int]] = []
    column_ends: list[datetime] = []  # her kolonun son elemanının bitişi
    cluster_end: datetime | None = None

    def flush() -> None:
        """Biten cluster'ı, nihai kolon sayısıyla birlikte sonuca yazar."""
        if not cluster:
            return
        total = len(column_ends)
        for occ, column in cluster:
            result.append((occ, column, total))

    for occ in items:
        if cluster_end is not None and occ.start_utc >= cluster_end:
            # Bu etkinlik cluster'daki hiçbir şeyle çakışmıyor -> cluster kapandı.
            flush()
            cluster = []
            column_ends = []
            cluster_end = None

        column = None
        for index, end in enumerate(column_ends):
            if end <= occ.start_utc:
                column = index
                break
        if column is None:
            column_ends.append(occ.end_utc)
            column = len(column_ends) - 1
        else:
            column_ends[column] = occ.end_utc

        cluster.append((occ, column))
        cluster_end = occ.end_utc if cluster_end is None else max(cluster_end, occ.end_utc)

    flush()
    return result
