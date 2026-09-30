# Contributing · Katkıda bulunma

[English](#english) · [Türkçe](#türkçe)

Thanks for looking at Takvim. Bug reports, small fixes and well-argued
suggestions are all welcome, in English or Turkish. By taking part you agree to
follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security problems go through
the private channel in [SECURITY.md](SECURITY.md), not a public issue.

---

## English

### Before you write code

- **Open an issue first** for anything bigger than a typo or an obvious bug
  fix, so we can agree on the direction before you spend the time.
- **Scope is a decision, not an accident.** These are deliberately out of
  scope: a server or accounts, multi-device sync, attendees / invites / RSVP,
  a mobile app, and CalDAV. A pull request that adds one of them will be
  declined, however good the code is. Everything else is open for discussion.
- Bug reports: use the issue form and say which version you run
  (⚙ Settings shows "Takvim vX.Y.Z"). **Never attach your own `takvim.db`.**

### Set up (Windows)

Python 3.12 or newer. From PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m ui --demo --tarayici   # runs in a browser tab (handy for DevTools)
```

`python -m ui --demo --no-browser` starts only the local server. The
packaged app opens its own window instead; see the README's "Geliştirme"
section for building the `.exe`.

### Checks: the same ones CI runs

```powershell
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy core store
.venv\Scripts\python.exe -m pytest -q
node --check ui/static/app.js
```

The front-end smoke tests need a browser and are a separate group:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev,test-ui]"
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe -m pytest tests/test_frontend_smoke.py -q
```

A pull request should pass all of them. CI runs them for you on every push.

### Rules that matter

The full list, with the reasons, is in [AGENTS.md](AGENTS.md) (Turkish).
It is also the guide for AI coding agents. The ones you will meet first:

- **Architecture:** `core/` is pure logic. It never imports `store/`, `ics/`
  or `ui/`, and does no I/O. The other direction is fine.
- **Migrations are never edited.** A schema change is a new numbered file in
  `store/migrations/`, mirrored in `store/schema.sql` (a test enforces that
  the two match). New columns and tables go at the end.
- **Frozen dataclasses**, validation in `__post_init__`. No "check it later".
- **Comments, docstrings and test names are in Turkish**, and identifiers
  follow the naming already in the file you touch. Comments explain *why*, not
  *what*. Every public function gets type hints and a short docstring.
- **One test per behaviour.** For a critical path, break the line on purpose
  and check that a test turns red, then restore it (use a script that
  restores in a `finally`).

### Pull requests

- Keep them small and about one thing. Link the issue.
- Add a line under `## [Yayınlanmamış]` in [CHANGELOG.md](CHANGELOG.md) for
  anything a user would notice.
- Update the README or AGENTS.md if you change behaviour they describe.
- Don't commit `.venv/`, `*.db`, or local files such as `ornek.pid`.
- By contributing you agree that your work is released under the
  [MIT License](LICENSE).

---

## Türkçe

Takvim'e baktığın için sağ ol. Hata bildirimi, küçük düzeltme ve gerekçesi olan
öneri, Türkçe ya da İngilizce, hepsi hoş karşılanır. Katılırken
[Davranış Kuralları](CODE_OF_CONDUCT.md)'na uymayı kabul edersin. Güvenlik
sorunları herkese açık issue'ya değil, [SECURITY.md](SECURITY.md)'deki özel
kanala gider.

### Kod yazmadan önce

- Yazım hatası ya da bariz bir hata düzeltmesinden büyük her şey için **önce
  issue aç**; zamanını harcamadan yönü birlikte netleştirelim.
- **Kapsam bir karardır, kaza değil.** Bilerek kapsam dışı: sunucu ya da hesap,
  çoklu cihaz senkronu, katılımcı / davet / RSVP, mobil uygulama, CalDAV. Bunlardan
  birini ekleyen bir pull request kod ne kadar iyi olursa olsun kabul edilmez.
  Gerisi tartışmaya açık.
- Hata bildiriminde issue formunu kullan ve sürümünü yaz (⚙ Ayarlar'da "Takvim
  vX.Y.Z" yazar). **Kendi `takvim.db` dosyanı asla ekleme.**

### Kurulum (Windows)

Python 3.12 ya da üstü. PowerShell'den:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m ui --demo --tarayici   # tarayıcı sekmesinde açar (DevTools için pratik)
```

`python -m ui --demo --no-browser` yalnızca yerel sunucuyu başlatır. Paketli
uygulama ise kendi penceresinde açılır; `.exe` derlemek için README'deki
"Geliştirme" bölümüne bak.

### Kontroller: CI'ın çalıştırdıklarının aynısı

```powershell
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy core store
.venv\Scripts\python.exe -m pytest -q
node --check ui/static/app.js
```

Ön yüz duman testleri bir tarayıcı ister, ayrı bir grup:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev,test-ui]"
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe -m pytest tests/test_frontend_smoke.py -q
```

Pull request'in hepsini geçmeli. CI her push'ta bunları senin yerine çalıştırır.

### Önemli kurallar

Gerekçeleriyle tam liste [AGENTS.md](AGENTS.md)'de. Bu dosya AI kodlama
ajanları için de rehber. İlk karşılaşacakların:

- **Mimari:** `core/` saf mantıktır; `store/`, `ics/` ya da `ui/` import etmez,
  I/O yapmaz. Tersi serbest.
- **Migration'lar asla değiştirilmez.** Şema değişikliği, `store/migrations/`
  altında yeni numaralı bir dosyadır ve `store/schema.sql`'de aynen yansıtılır
  (bir test ikisinin aynı olmasını zorlar). Yeni kolon/tablo sona eklenir.
- **Frozen dataclass**, doğrulama `__post_init__` içinde. "Sonra kontrol
  ederiz" yok.
- **Yorumlar, docstring'ler ve test adları Türkçe**; tanımlayıcılar dokunduğun
  dosyadaki mevcut adlandırmayı izler. Yorum *neden*'i anlatır, *ne*'yi değil.
  Her public fonksiyonda tip ipucu ve kısa docstring olur.
- **Her davranış için ayrı test.** Kritik bir yolda ilgili satırı kasten boz,
  bir testin kırmızıya döndüğünü gör, sonra geri yükle (geri yüklemeyi `finally`
  ile yapan bir script kullan).

### Pull request'ler

- Küçük ve tek konulu tut. İlgili issue'yu bağla.
- Kullanıcının fark edeceği her değişiklik için [CHANGELOG.md](CHANGELOG.md)'de
  `## [Yayınlanmamış]` altına bir satır ekle.
- Tarif ettikleri davranışı değiştiriyorsan README ya da AGENTS.md'yi güncelle.
- `.venv/`, `*.db` ve `ornek.pid` gibi yerel dosyaları commit'leme.
- Katkıda bulunarak çalışmanın [MIT Lisansı](LICENSE) ile yayımlanmasını kabul
  edersin.
