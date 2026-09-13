"""Faz B API testleri: yedek listesi/dönüşü, seri bilgisi, anlık görüntülü silme.

HTTP üzerinden konuşuluyor ki route çözümü ve JSON sözleşmesi de kapsansın.
Veritabanı GERÇEK dosya: `yedekten_don` dosyayı değiştiriyor, bellekte anlamsız.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import date

import pytest

from core import Event
from store import Repo, new_uid, yedek_al
from tests.helpers import IST, ist
from ui.server import make_server


@pytest.fixture
def db(tmp_path):
    """Dosya veritabanı yolu (yedekler yanında duracak)."""
    return str(tmp_path / "takvim.db")


@pytest.fixture
def repo(db):
    """Dosya DB'si; sunucu thread'inden kullanılacağı için kilitsiz."""
    with Repo.open(db, check_same_thread=False) as r:
        yield r


@pytest.fixture
def ders(repo):
    """Görünür varsayılan takvim."""
    return repo.add_calendar("Ders", "#e0524a")


@pytest.fixture
def sunucu(repo, ders, db):
    """Gerçek HTTP sunucusu + dosya yolu (yedek uçları için şart)."""
    httpd = make_server(repo, IST, host="127.0.0.1", port=0, db_yolu=db)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _get(temel: str, yol: str):
    with urllib.request.urlopen(temel + yol) as yanit:
        return json.loads(yanit.read().decode("utf-8"))


def _post(temel: str, yol: str, govde: dict):
    req = urllib.request.Request(
        temel + yol,
        method="POST",
        data=json.dumps(govde, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req) as yanit:
        return json.loads(yanit.read().decode("utf-8"))


def _delete(temel: str, yol: str):
    req = urllib.request.Request(temel + yol, method="DELETE")
    with urllib.request.urlopen(req) as yanit:
        return json.loads(yanit.read().decode("utf-8"))


def _hata_kodu(temel: str, yol: str, govde: dict | None = None, method: str = "GET") -> int:
    req = urllib.request.Request(
        temel + yol,
        method=method,
        data=None if govde is None else json.dumps(govde).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as hata:
        return hata.code
    raise AssertionError(f"{method} {yol} hata vermedi")


def test_yedek_listesi_yeniden_eskiye(repo, ders, db, sunucu, tmp_path):
    """İki yedek: en yeni üstte, boyut bilgisiyle."""
    yedek_al(repo.conn, tmp_path, bugun=date(2026, 9, 12))
    yedek_al(repo.conn, tmp_path, bugun=date(2026, 9, 13))
    liste = _get(sunucu, "/api/backups")["backups"]
    assert [b["ad"] for b in liste] == ["takvim-2026-09-13.db", "takvim-2026-09-12.db"]
    assert all(b["boyut"] > 0 for b in liste)


def test_yedek_listesi_bos(repo, ders, sunucu):
    """Yedek yoksa boş liste (hata değil)."""
    assert _get(sunucu, "/api/backups") == {"backups": []}


def test_yedekten_donus_dosyayi_degistirir(repo, ders, db, sunucu, tmp_path):
    """Dönüş sonrası sonradan eklenen takvim yok; yanıt adı taşıyor."""
    yedek_al(repo.conn, tmp_path, bugun=date(2026, 9, 13))
    repo.add_calendar("Sonradan", "#000000")
    yanit = _post(sunucu, "/api/backups/restore", {"ad": "takvim-2026-09-13.db"})
    assert yanit == {"restored": "takvim-2026-09-13.db"}
    assert [c["name"] for c in _get(sunucu, "/api/calendars")["calendars"]] == ["Ders"]


def test_yedekten_donus_bilinmeyen_ad_400(repo, ders, sunucu):
    """Liste-dışı ad 400 (yol geçişi dahil)."""
    assert _post_hata(sunucu, "/api/backups/restore", {"ad": "../takvim.db"}) == 400
    assert _post_hata(sunucu, "/api/backups/restore", {"ad": ""}) == 400


def _post_hata(temel: str, yol: str, govde: dict) -> int:
    return _hata_kodu(temel, yol, govde, "POST")


def test_seri_bilgisi_sayi_dondurur(repo, ders, sunucu):
    """Onay kutusu verisi HTTP'den geliyor."""
    ev = repo.add_event(Event(
        id=None, uid=new_uid(), calendar_id=ders.id, title="Algoritma",
        start_utc=ist(2026, 9, 7, 10, 0), end_utc=ist(2026, 9, 7, 11, 0),
        tzid=IST, rrule="FREQ=WEEKLY;BYDAY=MO",
    ))
    bilgi = _get(sunucu, f"/api/series_info?event_id={ev.id}")
    assert bilgi["title"] == "Algoritma" and bilgi["sonsuz"] is True
    assert bilgi["ornek_sayisi"] > 100


def test_seri_bilgisi_kayitsiz_404(sunucu):
    """Kayıtsız id 404."""
    assert _hata_kodu(sunucu, "/api/series_info?event_id=999") == 404


def test_silme_anlik_goruntulu_ve_geri_alinabilir(repo, ders, sunucu):
    """DELETE yanıtı geri alma taşıyor; restore_last diriltiyor."""
    ev = repo.add_event(Event(
        id=None, uid=new_uid(), calendar_id=ders.id, title="Algoritma",
        start_utc=ist(2026, 9, 7, 10, 0), end_utc=ist(2026, 9, 7, 11, 0),
        tzid=IST, rrule="FREQ=WEEKLY;BYDAY=MO",
    ))
    silme = _delete(sunucu, f"/api/events/{ev.id}")
    assert silme == {"deleted": ev.id, "title": "Algoritma", "geri_alinabilir": True}
    assert _get(sunucu, "/api/search?q=Algoritma")["results"] == []

    geri = _post(sunucu, "/api/events/restore_last", {})
    assert geri["title"] == "Algoritma"
    assert len(_get(sunucu, "/api/search?q=Algoritma")["results"]) == 1


def test_bos_geri_alma_404(sunucu):
    """Geri alınacak silme yoksa 404."""
    assert _post_hata(sunucu, "/api/events/restore_last", {}) == 404
