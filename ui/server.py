"""Yerel HTTP sunucusu.

Bilerek stdlib `http.server`: bu tek kullanıcılı, yalnızca localhost'a bağlanan
bir masaüstü uygulaması ve ihtiyacımız olan route'lar için fastapi + uvicorn +
starlette + pydantic zinciri ağır kaçıyor. Blueprint §5'in gerekçesi "web ön yüz"
idi (zaman ızgarası ve çakışma yerleşimi CSS'in doğal işi), sunucu çatısı değil.

Sunucu ince tutuldu: hafta/ay mantığı `ui/presenter.py`, zaman ayrıştırma
`core/quickadd.py`, dosya biçimleri `ics/` içinde ve hepsi HTTP'siz test ediliyor.
"""

from __future__ import annotations

import json
import mimetypes
from dataclasses import replace
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core import UTC, Event, parse_iso
from core.quickadd import parse_quick_add
from ics import export_repo, import_ics
from store import Repo, new_uid

from .presenter import day_payload, month_payload, week_payload

__all__ = ["serve", "make_server"]

STATIC = Path(__file__).resolve().parent / "static"
_MAKS_GOVDE = 8 * 1024 * 1024  # 8 MB: .ics içe aktarma için fazlasıyla yeterli


class _Handler(BaseHTTPRequestHandler):
    """Statik dosyalar + JSON API."""

    server_version = "Takvim/1.0"

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        """Varsayılan stderr gürültüsünü kısar."""
        if self.server.verbose:  # type: ignore[attr-defined]
            super().log_message(format, *args)

    # -- yardımcılar --------------------------------------------------------

    @property
    def repo(self) -> Repo:
        """Sunucuya bağlı depo."""
        return self.server.repo  # type: ignore[attr-defined]

    @property
    def tzid(self) -> str:
        """Uygulamanın varsayılan saat dilimi."""
        return self.server.tzid  # type: ignore[attr-defined]

    def _gonder(self, govde: bytes, tur: str, status: int = 200, ekler: dict | None = None) -> None:
        """Ham gövde yazar."""
        self.send_response(status)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(govde)))
        self.send_header("Cache-Control", "no-store")
        for ad, deger in (ekler or {}).items():
            self.send_header(ad, deger)
        self.end_headers()
        self.wfile.write(govde)

    def _json(self, payload, status: int = 200) -> None:
        """JSON gövde yazar."""
        self._gonder(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def _hata(self, mesaj: str, status: int = 400) -> None:
        """Hata gövdesi."""
        self._json({"error": mesaj}, status)

    def _govde(self) -> dict:
        """İstek gövdesini JSON olarak okur."""
        uzunluk = int(self.headers.get("Content-Length") or 0)
        if uzunluk > _MAKS_GOVDE:
            raise ValueError("gövde çok büyük")
        if uzunluk == 0:
            return {}
        return json.loads(self.rfile.read(uzunluk))

    def _metin_govde(self) -> str:
        """İstek gövdesini düz metin olarak okur (.ics içe aktarma)."""
        uzunluk = int(self.headers.get("Content-Length") or 0)
        if uzunluk > _MAKS_GOVDE:
            raise ValueError("gövde çok büyük")
        return self.rfile.read(uzunluk).decode("utf-8", errors="replace")

    def _tarih(self, sorgu: dict) -> date:
        """`?date=` parametresini çözer; yoksa bugün."""
        ham = (sorgu.get("date") or [date.today().isoformat()])[0]
        return date.fromisoformat(ham)

    def _statik(self, yol: str) -> None:
        """static/ altından dosya sunar; dizin dışına çıkışı engeller."""
        ad = "index.html" if yol in ("", "/") else yol.lstrip("/")
        hedef = (STATIC / ad).resolve()
        if not str(hedef).startswith(str(STATIC.resolve())) or not hedef.is_file():
            self._hata("bulunamadı", 404)
            return
        tur, _ = mimetypes.guess_type(str(hedef))
        self._gonder(hedef.read_bytes(), f"{tur or 'application/octet-stream'}; charset=utf-8")

    # -- GET ----------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        """Görünüm verileri, arama, dışa aktarma ve statik dosyalar."""
        parsed = urlparse(self.path)
        sorgu = parse_qs(parsed.query)
        yol = parsed.path

        try:
            if yol in ("/api/week", "/api/day", "/api/month"):
                uretici = {
                    "/api/week": week_payload,
                    "/api/day": day_payload,
                    "/api/month": month_payload,
                }[yol]
                self._json(uretici(self.repo, self._tarih(sorgu), self.tzid))
                return

            if yol == "/api/calendars":
                self._json({"calendars": [_takvim(c) for c in self.repo.list_calendars()]})
                return

            if yol == "/api/search":
                anahtar = (sorgu.get("q") or [""])[0]
                bulunan = self.repo.search_events(anahtar)
                self._json({"query": anahtar, "results": [_event_ozet(e) for e in bulunan]})
                return

            if yol == "/api/export":
                metin = export_repo(self.repo)
                self._gonder(
                    metin.encode("utf-8"),
                    "text/calendar; charset=utf-8",
                    ekler={"Content-Disposition": 'attachment; filename="takvim.ics"'},
                )
                return

            if yol.startswith("/api/"):
                self._hata("bulunamadı", 404)
                return

            self._statik(yol)
        except ValueError as exc:
            self._hata(str(exc))

    # -- POST ---------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802
        """Oluşturma, örnek düzeyi işlemler, görünürlük ve içe aktarma."""
        parsed = urlparse(self.path)
        parcalar = [p for p in parsed.path.split("/") if p]

        try:
            if parcalar == ["api", "events"]:
                self._etkinlik_olustur()
                return

            if parcalar == ["api", "occurrences", "cancel"]:
                self._ornek_iptal()
                return

            if parcalar == ["api", "occurrences", "move"]:
                self._ornek_kaydir()
                return

            if parcalar == ["api", "import"]:
                self._ics_iceri()
                return

            if (
                len(parcalar) == 4
                and parcalar[:2] == ["api", "calendars"]
                and parcalar[3] == "visible"
            ):
                self._gorunurluk(int(parcalar[2]))
                return

            self._hata("bulunamadı", 404)
        except (ValueError, KeyError) as exc:
            self._hata(str(exc))
        except LookupError as exc:
            self._hata(str(exc), 404)

    def do_PATCH(self) -> None:  # noqa: N802
        """PATCH /api/events/<id> — başlık/konum/açıklama günceller."""
        parsed = urlparse(self.path)
        parcalar = [p for p in parsed.path.split("/") if p]
        try:
            if len(parcalar) == 3 and parcalar[:2] == ["api", "events"]:
                self._etkinlik_guncelle(int(parcalar[2]))
                return
            self._hata("bulunamadı", 404)
        except (ValueError, KeyError) as exc:
            self._hata(str(exc))
        except LookupError as exc:
            self._hata(str(exc), 404)

    def do_DELETE(self) -> None:  # noqa: N802
        """DELETE /api/events/<id> — SERİNİN TAMAMINI siler."""
        parsed = urlparse(self.path)
        parcalar = [p for p in parsed.path.split("/") if p]
        if len(parcalar) == 3 and parcalar[:2] == ["api", "events"]:
            try:
                event_id = int(parcalar[2])
            except ValueError:
                self._hata("geçersiz id")
                return
            if self.repo.get_event(event_id) is None:
                self._hata("etkinlik bulunamadı", 404)
                return
            self.repo.delete_event(event_id)
            self._json({"deleted": event_id})
            return
        self._hata("bulunamadı", 404)

    # -- işlem gövdeleri ----------------------------------------------------

    def _etkinlik_olustur(self) -> None:
        """Hızlı ekleme metninden etkinlik yaratır.

        Ayrıştırma sonucunu da geri gönderiyoruz (`matched`): kullanıcı neyin
        zaman olarak tanındığını görsün. Tanınmayan ifade sessizce yanlış saate
        kaydedilmiş bir randevuya dönüşmesin.
        """
        govde = self._govde()
        metin = (govde.get("text") or "").strip()
        if not metin:
            raise ValueError("metin boş")

        takvimler = self.repo.list_calendars()
        if not takvimler:
            raise ValueError("önce bir takvim oluşturulmalı")
        takvim_id = govde.get("calendarId") or takvimler[0].id

        cozum = parse_quick_add(metin, now=datetime.now(UTC), tzid=self.tzid)
        kaydedilen = self.repo.add_event(
            Event(
                id=None,
                uid=new_uid(),
                calendar_id=int(takvim_id),
                title=cozum.title,
                start_utc=cozum.start_utc,
                end_utc=cozum.end_utc,
                tzid=cozum.tzid,
                all_day=cozum.all_day,
            )
        )
        self._json(
            {
                "event": _event_ozet(kaydedilen),
                "parsed": {
                    "title": cozum.title,
                    "matched": cozum.matched,
                    "allDay": cozum.all_day,
                    "startUtc": cozum.start_utc.isoformat(),
                    "endUtc": cozum.end_utc.isoformat(),
                },
            },
            201,
        )

    def _etkinlik_guncelle(self, event_id: int) -> None:
        """Metin alanlarını günceller; zaman alanlarına dokunmaz."""
        mevcut = self.repo.get_event(event_id)
        if mevcut is None:
            raise LookupError("etkinlik bulunamadı")
        govde = self._govde()
        yeni = replace(
            mevcut,
            title=(govde.get("title") or mevcut.title).strip() or mevcut.title,
            location=govde.get("location", mevcut.location) or None,
            description=govde.get("description", mevcut.description) or None,
        )
        self.repo.update_event(yeni)
        self._json({"event": _event_ozet(yeni)})

    def _ornek_iptal(self) -> None:
        """Serinin TEK örneğini iptal eder (diğerleri durur)."""
        govde = self._govde()
        event_id = int(govde["eventId"])
        orijinal = parse_iso(govde["originalStartUtc"])
        if self.repo.get_event(event_id) is None:
            raise LookupError("etkinlik bulunamadı")
        self.repo.cancel_occurrence(event_id, orijinal)
        self._json({"cancelled": govde["originalStartUtc"]})

    def _ornek_kaydir(self) -> None:
        """Serinin TEK örneğini başka bir ana taşır."""
        govde = self._govde()
        event_id = int(govde["eventId"])
        orijinal = parse_iso(govde["originalStartUtc"])
        yeni_bas = parse_iso(govde["newStartUtc"])
        yeni_bit = parse_iso(govde["newEndUtc"]) if govde.get("newEndUtc") else None
        if self.repo.get_event(event_id) is None:
            raise LookupError("etkinlik bulunamadı")
        kayit = self.repo.move_occurrence(event_id, orijinal, yeni_bas, yeni_bit)
        self._json(
            {
                "moved": {
                    "originalStartUtc": kayit.original_start_utc.isoformat(),
                    "newStartUtc": kayit.new_start_utc.isoformat(),
                    "newEndUtc": kayit.new_end_utc.isoformat() if kayit.new_end_utc else None,
                }
            }
        )

    def _ics_iceri(self) -> None:
        """Gövdedeki `.ics` metnini içe aktarır."""
        takvimler = self.repo.list_calendars()
        if not takvimler:
            raise ValueError("önce bir takvim oluşturulmalı")
        rapor = import_ics(
            self.repo,
            self._metin_govde(),
            calendar_id=takvimler[0].id,
            default_tzid=self.tzid,
        )
        self._json(
            {
                "added": rapor.added,
                "updated": rapor.updated,
                "skipped": rapor.skipped,
                "overrides": rapor.overrides,
                "errors": [{"uid": u, "reason": r} for u, r in rapor.errors],
                "warnings": list(rapor.warnings),
            }
        )

    def _gorunurluk(self, takvim_id: int) -> None:
        """Takvim görünürlüğünü değiştirir."""
        takvim = self.repo.get_calendar(takvim_id)
        if takvim is None:
            raise LookupError("takvim bulunamadı")
        gorunur = bool(self._govde().get("visible", True))
        self.repo.update_calendar(replace(takvim, visible=gorunur))
        self._json({"id": takvim_id, "visible": gorunur})


def _takvim(c) -> dict:
    """Calendar -> sözlük."""
    return {"id": c.id, "name": c.name, "color": c.color, "visible": c.visible}


def _event_ozet(e: Event) -> dict:
    """Event -> sözlük (arama sonucu ve oluşturma yanıtı için)."""
    return {
        "id": e.id,
        "uid": e.uid,
        "title": e.title,
        "calendarId": e.calendar_id,
        "startUtc": e.start_utc.isoformat(),
        "endUtc": e.end_utc.isoformat(),
        "allDay": e.all_day,
        "tzid": e.tzid,
        "location": e.location,
        "recurring": e.is_recurring,
    }


def make_server(repo: Repo, tzid: str, host: str = "127.0.0.1", port: int = 8765,
                verbose: bool = False) -> HTTPServer:
    """Sunucuyu kurar ama çalıştırmaz (testler bu hâlini kullanıyor).

    TEK THREAD'li `HTTPServer`, `ThreadingHTTPServer` DEĞİL. Sebebi:
    sqlite3 bağlantıları thread'e bağlıdır (`check_same_thread`), ve bağlantıyı
    başka bir thread'den kullanmak "SQLite objects created in a thread can only
    be used in that same thread" hatası verir. Tek kullanıcılı yerel bir
    uygulamada eşzamanlılık hiçbir şey kazandırmıyor, dolayısıyla sorunu
    kilitle yönetmek yerine ortadan kaldırıyoruz.

    `BaseHTTPRequestHandler` HTTP/1.0 konuştuğu için bağlantılar her yanıttan
    sonra kapanıyor; tarayıcının paralel istekleri birbirini bloke etmiyor.

    Buraya dönüp `ThreadingHTTPServer` yaparsan `store.connect()`'e
    `check_same_thread=False` geçmen ve erişimi kilitlemen gerekir.
    """
    httpd = HTTPServer((host, port), _Handler)
    httpd.repo = repo  # type: ignore[attr-defined]
    httpd.tzid = tzid  # type: ignore[attr-defined]
    httpd.verbose = verbose  # type: ignore[attr-defined]
    return httpd


def serve(repo: Repo, tzid: str, host: str = "127.0.0.1", port: int = 8765,
          verbose: bool = False) -> None:
    """Sunucuyu başlatır ve Ctrl+C'ye kadar çalıştırır."""
    httpd = make_server(repo, tzid, host, port, verbose)
    print(f"Takvim: http://{host}:{port}  (durdurmak için Ctrl+C)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nkapatılıyor...")
    finally:
        httpd.server_close()
