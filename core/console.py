"""Konsol çıktısının kodlamasını güvene alır.

Windows konsolu varsayılan olarak cp1254 (Türkçe) ya da cp437 kullanıyor.
Basılamayan tek bir karakter `UnicodeEncodeError` fırlatır ve bu, hatırlatıcı
döngüsü gibi uzun yaşayan bir süreci ÖLDÜREBİLİR. Bir etkinlik başlığı
yüzünden hatırlatıcının susması kabul edilemez, o yüzden akışları
`errors="replace"` ile yeniden yapılandırıyoruz: bozuk görünmek, çökmekten
iyidir.
"""

from __future__ import annotations

import sys


def guvenli_konsol() -> None:
    """stdout/stderr'i UTF-8 + replace ile yeniden yapılandırır."""
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            # Yönlendirilmiş ya da sarmalanmış akış; olduğu gibi bırak.
            pass
