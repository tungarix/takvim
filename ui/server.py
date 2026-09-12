"""Yerel HTTP sunucusu.

Bilerek stdlib `http.server`: bu tek kullanıcılı, yalnızca localhost'a bağlanan
bir masaüstü uygulaması ve ihtiyacımız olan dört route için fastapi + uvicorn +
starlette + pydantic zinciri ağır kaçıyor. Blueprint §5'in gerekçesi "web ön yüz"
idi (zaman ızgarası ve çakışma yerleşimi CSS'in doğal işi), sunucu çatısı değil.
API büyürse (Faz 4: hızlı ekleme, arama) FastAPI'ye geçmek route'ları taşımaktan
ibaret.

Sunucu ince tutuldu: hafta mantığı `ui/presenter.py` içinde ve HTTP'siz test
ediliyor.
"""

from __future__ import annotations

import json
import mimetypes
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from store import Repo

from .presenter import week_payload

__all__ = ["serve", "make_server"]

STATIC = Path(__file__).resolve().parent / "static"


class _Handler(BaseHTTPRequestHandler):
    """Statik dosyalar + küçük bir JSON API.

    `repo` ve `tzid` sunucu nesnesinden okunuyor.
    """

    server_version = "Takvim/0.1"

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        """Varsayılan stderr gürültüsünü kısar."""
        if self.server.verbose:  # type: ignore[attr-defined]
            super().log_message(format, *args)

    # -- yardımcılar --------------------------------------------------------

    def _json(self, payload: dict, status: int = 200) -> None:
        """JSON gövde yazar."""
        govde = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(govde)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(govde)

    def _hata(self, mesaj: str, status: int = 400) -> None:
        """Hata gövdesi."""
        self._json({"error": mesaj}, status)

    def _statik(self, yol: str) -> None:
        """static/ altından dosya sunar; dizin dışına çıkışı engeller."""
        ad = "index.html" if yol in ("", "/") else yol.lstrip("/")
        hedef = (STATIC / ad).resolve()
        if not str(hedef).startswith(str(STATIC.resolve())) or not hedef.is_file():
            self._hata("bulunamadı", 404)
            return
        tur, _ = mimetypes.guess_type(str(hedef))
        veri = hedef.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{tur or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(veri)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(veri)

    # -- route'lar ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        """GET /api/week, GET /api/calendars ve statik dosyalar."""
        parsed = urlparse(self.path)
        sorgu = parse_qs(parsed.query)

        if parsed.path == "/api/week":
            ham = (sorgu.get("date") or [date.today().isoformat()])[0]
            try:
                anchor = date.fromisoformat(ham)
            except ValueError:
                self._hata(f"geçersiz tarih: {ham!r}")
                return
            payload = week_payload(
                self.server.repo,  # type: ignore[attr-defined]
                anchor,
                self.server.tzid,  # type: ignore[attr-defined]
            )
            self._json(payload)
            return

        if parsed.path == "/api/calendars":
            takvimler = self.server.repo.list_calendars()  # type: ignore[attr-defined]
            self._json(
                {
                    "calendars": [
                        {"id": c.id, "name": c.name, "color": c.color, "visible": c.visible}
                        for c in takvimler
                    ]
                }
            )
            return

        if parsed.path.startswith("/api/"):
            self._hata("bulunamadı", 404)
            return

        self._statik(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        """POST /api/calendars/<id>/visible — takvim görünürlüğünü değiştirir."""
        parsed = urlparse(self.path)
        parcalar = [p for p in parsed.path.split("/") if p]

        if len(parcalar) == 4 and parcalar[:2] == ["api", "calendars"] and parcalar[3] == "visible":
            try:
                takvim_id = int(parcalar[2])
            except ValueError:
                self._hata("geçersiz takvim id")
                return
            uzunluk = int(self.headers.get("Content-Length") or 0)
            try:
                govde = json.loads(self.rfile.read(uzunluk) or b"{}")
            except json.JSONDecodeError:
                self._hata("gövde JSON değil")
                return
            gorunur = bool(govde.get("visible", True))

            repo = self.server.repo  # type: ignore[attr-defined]
            takvim = repo.get_calendar(takvim_id)
            if takvim is None:
                self._hata("takvim bulunamadı", 404)
                return
            from dataclasses import replace

            repo.update_calendar(replace(takvim, visible=gorunur))
            self._json({"id": takvim_id, "visible": gorunur})
            return

        self._hata("bulunamadı", 404)


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
