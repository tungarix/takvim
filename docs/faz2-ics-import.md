# Faz 2 — `.ics` içe aktarma

> Bu faz senin varsayımlarını kıracak faz. Gerçek veriyle çarpışmadan bittiğini
> düşünme.

Önce [AGENTS.md](../AGENTS.md) oku — özellikle §3 (bozulmaması gereken
davranışlar) ve §1 (PowerShell'de `&&` yok).

---

## Hedef

Google Calendar / Outlook'tan dışa aktarılmış bir `.ics` dosyasını okuyup
mevcut `Event` / `Override` modellerine çevirmek ve `store.Repo` üzerinden
kaydetmek.

Yeni bağımlılık: `icalendar` (önceden onaylı). Başkasını eklemeden önce sor.

---

## Yapı

```
ics/
  __init__.py
  importer.py
  windows_tz.py      # Windows saat dilimi adı -> IANA eşlemesi
tests/
  test_ics_import.py
  fixtures/          # küçük .ics örnekleri
```

`ics/` hem `core/` hem `store/` import edebilir. `core/` bunların hiçbirini
import edemez.

---

## API

Ayrıştırmayı yazmadan ayır: **parse saf olsun, DB'yi bilmesin.** Böylece
tuzakların tamamını veritabanı olmadan test edebilirsin.

```python
@dataclass(frozen=True)
class ParsedEvent:
    event: Event                 # calendar_id=None, id=None
    overrides: tuple[Override, ...]

@dataclass(frozen=True)
class ImportReport:
    added: int
    updated: int
    skipped: int
    overrides: int
    errors: tuple[tuple[str, str], ...]    # (uid, sebep)
    warnings: tuple[str, ...]

def parse_ics(source: str | Path, *, default_tzid: str) -> tuple[list[ParsedEvent], ImportReport]:
    """Saf: .ics metnini modellere çevirir, DB'ye dokunmaz."""

def import_ics(repo: Repo, source: str | Path, *, calendar_id: int,
               default_tzid: str, dry_run: bool = False) -> ImportReport:
    """Ayrıştırır ve kaydeder. UID zaten varsa günceller (mükerrer kayıt yok)."""
```

**Tek bir bozuk VEVENT tüm içe aktarmayı düşürmesin.** Hatayı `errors`'a yaz,
kalanına devam et. Sessizce yutma da — rapor kullanıcıya gösterilecek.

---

## Gerçek veride seni bekleyen tuzaklar

Bunları bilerek listeliyorum; her biri en az bir testi hak ediyor.

**1. Tüm gün etkinliklerde `DTEND` DIŞLAYICI.**
`DTSTART;VALUE=DATE:20240610` + `DTEND;VALUE=DATE:20240613` = 10, 11, 12
Haziran, yani **3 gün**. 13'ü dahil değil. Modelimiz zaten bitişi dışlayıcı
gece yarısı olarak saklıyor, dolayısıyla doğrudan eşleşiyor — ama bu klasik
hatadır, testle çivile.

**2. `DTEND` hiç olmayabilir.**
`DURATION` varsa ondan hesapla. İkisi de yoksa: `VALUE=DATE` ise +1 gün,
`DATE-TIME` ise RFC'ye göre sıfır süre — ama `Event` sıfır süreyi reddediyor.
Kararını ver, gerekçeyi yorumda yaz, teste bağla.

**3. `TZID` her zaman IANA adı değil.**
Outlook `TZID="Türkiye Standart Saati"` veya `"W. Europe Standard Time"`
yazar. Sıra: (a) IANA olarak dene, (b) `windows_tz.py` tablosundan çevir,
(c) `default_tzid`'e düş ve **uyarı üret**. Sessizce UTC'ye düşme — `core/`
tekrarları tzid'de genişlettiği için yanlış tzid, DST'de saat kaydırır.

**4. Kayan (floating) zamanlar.** `TZID` yok, `Z` yok → `default_tzid`'de yorumla.

**5. UTC zamanlar (`Z` soneki).** Anı doğru ama etkinliğin *beyan edilmiş*
dilimi yok. `tzid` olarak `default_tzid` ver; `start_utc` zaten doğru.

**6. `RECURRENCE-ID` → `Override`.**
Aynı `UID`'li VEVENT'ler tek seriyi tarif eder: biri ana kayıt, diğerleri
örnek geçersiz kılmaları. `UID`'e göre grupla. `RECURRENCE-ID` değeri
**orijinal başlangıçtır** (`original_start_utc`). `RANGE=THISANDFUTURE`
nadir ve bizim modelde karşılığı yok — desteklemiyorsan `errors`'a yaz.

**7. `STATUS:CANCELLED`** olan örnek → `Override(cancelled=True)`.

**8. `EXDATE`/`RDATE` birden çok satırda ve her satırda virgüllü** olabilir.
Hepsini topla. Dikkat: `core.Event` bunları UTC'ye normalize edip sıralıyor.

**9. Naive `UNTIL`.** `core/recurrence.py` bunu zaten normalize ediyor —
RRULE metnini **ham hâliyle sakla**, kendin dönüştürmeye kalkma.

**10. VEVENT dışındaki bileşenler** (`VTODO`, `VJOURNAL`, `VFREEBUSY`,
`VTIMEZONE`) atlanmalı, hata sayılmamalı.

**11. Aynı `UID` ikinci kez içe aktarılırsa güncelleme olmalı.**
`repo.get_event_by_uid()` var. `SEQUENCE` daha küçükse atla (`skipped`).

**12. `DTSTART` sonrası `DTEND`.** Bozuk kayıtlar var; `Event.__post_init__`
`ValueError` fırlatır. Yakala, `errors`'a yaz, diğerlerine devam et.

---

## Kabul kriterleri

Her biri ayrı test. Küçük `.ics` parçalarını `tests/fixtures/` altına koy.

- [ ] Tek seferlik saatli etkinlik, `TZID=Europe/Istanbul`
- [ ] Çok günlü tüm gün etkinlik → `DTEND` dışlayıcı doğrulanıyor (3 gün)
- [ ] `DTEND` yok, `DURATION` var
- [ ] Haftalık `RRULE` + iki `EXDATE`
- [ ] `RECURRENCE-ID` ile tek örnek kaydırma → `Override`, `expand()` sonucunda görünüyor
- [ ] `RECURRENCE-ID` + `STATUS:CANCELLED` → `Override(cancelled=True)`
- [ ] Windows saat dilimi adı → IANA'ya çevriliyor
- [ ] Bilinmeyen saat dilimi → `default_tzid`'e düşüyor **ve uyarı üretiyor**
- [ ] Kayan (TZID'siz) zaman → `default_tzid`'de yorumlanıyor
- [ ] Bozuk VEVENT (`DTEND < DTSTART`) → `errors`'a yazılıyor, kalanı içe aktarılıyor
- [ ] `VTODO` içeren dosya → atlanıyor, hata yok
- [ ] Aynı dosyayı iki kez içe aktarma → ikinci seferde `added=0`, mükerrer kayıt yok
- [ ] `dry_run=True` → DB değişmiyor, rapor yine doluyor
- [ ] Uçtan uca: içe aktar → `repo.occurrences()` ile bir haftayı sorgula → beklenen örnekler

---

## Gerçek veri ile sına

Kabul kriterleri geçtikten sonra **asıl test bu**:

1. Google Calendar → Ayarlar → Takvimi dışa aktar → `.ics`
2. Ders programını içe aktar
3. `repo.occurrences()` ile bir haftayı sorgula, Google'daki hafta görünümüyle
   **karşılaştır**
4. Uyuşmayan her şey bir bug veya eksik varsayım — bulduklarını buraya not düş

`series_end_utc`'nin gerçek verilerde doğru hesaplandığını ayrıca kontrol et:
sonsuz serilerde `NULL`, `UNTIL`/`COUNT` olanlarda son örneğin bitişi.

`DTSTART`'tan önceye düşen bir `RDATE` ile karşılaşırsan: bu, AGENTS.md §4'te
yazılı bilinen sınır. `events` tablosuna `series_start_utc` ekleyen bir
`002_*.sql` migration yaz ve `_candidate_events()`'i güncelle — sessizce geçme.

---

## Bitirirken

- `.\.venv\Scripts\python.exe -m pytest` — 84 mevcut testin hiçbiri kırılmamalı
- Yeni testler dahil tam sayıyı raporla
- README'yi güncelle: Faz 2 durumu, varsa yeni kasıtlı kararlar ve bilinen sınırlar
