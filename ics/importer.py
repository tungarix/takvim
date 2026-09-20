"""`.ics` içe aktarma: ayrıştırma (saf) + kaydetme.

Ayrım bilinçli: `parse_ics` DB'yi bilmez, böylece gerçek veri tuzaklarının
tamamı veritabanı olmadan test edilebilir. `import_ics` ayrıştırır ve
`store.Repo` üzerinden kaydeder; UID zaten varsa günceller.

`core/` burayı import etmez; tersi serbest (mimari kuralı, bkz. AGENTS.md §2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from icalendar import Calendar

from core.models import Event, Override
from core.timeutil import UTC, from_wall_clock, get_tz

from .windows_tz import resolve_windows_tz

__all__ = ["ParsedEvent", "ImportReport", "parse_ics", "import_ics"]

_UID_YOK = "(uid-yok)"
_BASSIZ = "(Başlıksız)"


@dataclass(frozen=True)
class ParsedEvent:
    """Tek UID'nin ayrıştırılmış karşılığı: ana kayıt + örnek geçersiz kılmaları.

    `event` ve `overrides` henüz kaydedilmemiş hâldedir (`id=None`,
    `calendar_id=None`, `event_id=None`); `import_ics` yazarken doldurur.
    `sequence` RFC 5545 SEQUENCE'dir (yoksa 0): içe aktarma sırasında DB'deki
    değerle karşılaştırıp eski güncellemenin yeniyi ezmesini önler.
    """

    event: Event
    overrides: tuple[Override, ...] = ()
    sequence: int = 0


@dataclass(frozen=True)
class ImportReport:
    """İçe aktarma sonucu: kullanıcıya gösterilecek özet.

    `errors` (`uid`, sebep) çiftleridir; tek bozuk VEVENT kalanı düşürmez.
    `warnings` serbest metindir (bilinmeyen saat dilimi, varsayılan süre...).
    `overrides` yazılan (veya `dry_run` ise yazılacak olan) override sayısıdır.
    """

    added: int = 0
    updated: int = 0
    skipped: int = 0
    overrides: int = 0
    errors: tuple[tuple[str, str], ...] = ()
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Kaynak yükleme
# ---------------------------------------------------------------------------


def _to_calendar(source: str | Path) -> Calendar:
    """`source` bir `Path`SE dosyadan, `str`SE METİN olarak takvim kurar.

    `str` ASLA dosya yolu olarak YORUMLANMAZ (güvenlik denetimi TKV-API-003).
    Önce yalnızca kendi `BEGIN:VCALENDAR` sezgimizi kaldırmıştık, ama `str`'i
    doğrudan `Calendar.from_ical`e vermek YETMİYORDU: `icalendar` paketinin
    KENDİ `from_ical`'ı da satır sonu TAŞIMAYAN bir `str`'i diskte dosya olarak
    arıyor (`Path(st).is_file()` -- paketin kaynağında elle doğrulandı). Yani
    tek satırlık, saldırganın diskte var olduğunu bildiği bir yol string'i
    hâlâ okunup `/api/export` ile dışarı sızabiliyordu; bunu da uçtan uca
    kanıtladık. Çözüm: `str`'i BAYT'a çeviriyoruz -- paket yalnızca `str`
    girdiyi yol olarak deniyor, `bytes`'ı ASLA (kaynakta `elif isinstance(st,
    str)` şartı `bytes`'ı hiç kapsamıyor). Türkçe karakterler için UTF-8
    yuvarlanıp geri geliyor, doğrulandı.

    Python içinden gerçekten dosya okutmak isteyen çağıran açıkça `Path`
    geçirsin -- testler ve `import_ics`'in dosya tabanlı kullanımları zaten
    öyle yapıyor, davranışları DEĞİŞMEDİ.
    """
    if isinstance(source, Path):
        return Calendar.from_ical(source)
    if isinstance(source, str):
        return Calendar.from_ical(source.encode("utf-8"))
    raise ValueError(f"source str veya Path olmalı, alınan: {type(source).__name__}")


def _resolve_tzid(
    tzid_raw: str | None,
    default_tzid: str,
    warnings: list[str],
    uid: str,
    alan: str,
) -> str:
    """Bildirilen TZID'i IANA adına çevirir.

    Sıra: (a) IANA olarak dene, (b) Windows tablosundan çevir, (c) default'a
    düş ve uyarı üret. Sessizce UTC'ye düşmek yok: `core/` tekrarları tzid'de
    genişlettiği için yanlış tzid DST'de saat kaydırır.
    """
    if not tzid_raw:
        return default_tzid
    ham = tzid_raw.strip()
    if not ham:
        return default_tzid
    try:
        get_tz(ham)
        return ham
    except ValueError:
        pass
    cevrilmis = resolve_windows_tz(ham)
    if cevrilmis is not None:
        try:
            get_tz(cevrilmis)
            return cevrilmis
        except ValueError:
            pass
    warnings.append(f"({uid}) {alan} saat dilimi {ham!r} bilinmiyor, {default_tzid!r} varsayıldı")
    return default_tzid


def _tek_ham(comp, ad: str, uid: str, warnings: list[str]):
    """Tekil beklenen özelliğin ham değerini döndürür; listeyse sonuncuyu alır.

    Bozuk üreticiler aynı özelliği iki kez yazabiliyor (çift DTSTART). İlkini
    sessizce ezmek yerine sonuncuyu alıp uyarı üretiyoruz.
    """
    if ad not in comp:
        return None
    ham = comp[ad]
    if isinstance(ham, list):
        warnings.append(f"({uid}) {ad} iki kez yazılmış, sonuncusu alındı")
        return ham[-1] if ham else None
    return ham


def _dt_degeri(ham):
    """Ham `vDDDTypes` taşıyıcısından `date`/`datetime` çıkarır."""
    if ham is None:
        return None
    if hasattr(ham, "dt"):
        return ham.dt
    return ham


def _tzid_parami(ham) -> str | None:
    """Ham özelliğin TZID parametresi (yoksa None)."""
    params = getattr(ham, "params", None)
    if not params:
        return None
    try:
        deger = params.get("TZID")
    except Exception:
        return None
    return str(deger) if deger is not None else None


def _an_to_utc(
    deger: datetime,
    tzid_raw: str | None,
    default_tzid: str,
    warnings: list[str],
    uid: str,
    alan: str,
) -> tuple[datetime, str]:
    """Aware/naive datetime'tan (UTC an, kullanılacak tzid) üretir.

    Duvar saati korunur: IANA adı geçerliyse o dilimde, Windows adıysa çevrilen
    dilimde, bilinmiyorsa `default_tzid`'de yorumlanır. UTC (`Z` sonekli) anlar
    zaten tektir; tzid olarak `default_tzid` verilir (tuzak 5).
    """
    if deger.tzinfo is not None and deger.tzinfo.utcoffset(deger) is not None:
        if tzid_raw:
            tzid = _resolve_tzid(tzid_raw, default_tzid, warnings, uid, alan)
            # Duvar saatini bildirilen dilimde yeniden yorumluyoruz: icalendar
            # geçerli IANA adında doğru tzinfo'yu zaten takmış oluyor, ama
            # Windows adında naive bırakıyor; tek yoldan gitmek iki hâli de
            # aynı kapıdan geçiriyor.
            duvar = deger.replace(tzinfo=None)
            return from_wall_clock(duvar, tzid), tzid
        return deger.astimezone(UTC), default_tzid
    duvar = deger.replace(tzinfo=None)
    if tzid_raw:
        tzid = _resolve_tzid(tzid_raw, default_tzid, warnings, uid, alan)
    else:
        # Kayan zaman (tuzak 4): uyarısız, default dilimde yorumlanır.
        tzid = default_tzid
    return from_wall_clock(duvar, tzid), tzid


def _metin(comp, ad: str) -> str | None:
    """SUMMARY/DESCRIPTION/LOCATION gibi metin özellikleri; boşsa None."""
    if ad not in comp:
        return None
    try:
        cozulmus = comp.decoded(ad)
    except Exception:
        try:
            cozulmus = str(comp[ad])
        except Exception:
            return None
    if cozulmus is None:
        return None
    if isinstance(cozulmus, bytes):
        try:
            cozulmus = cozulmus.decode("utf-8")
        except Exception:
            cozulmus = cozulmus.decode("utf-8", errors="replace")
    metin = str(cozulmus).strip()
    return metin if metin else None


def _sequence(comp) -> int:
    """SEQUENCE yoksa/bozuksa 0: çoğu üretici ilk sürümde yazmıyor."""
    if "SEQUENCE" not in comp:
        return 0
    try:
        return int(comp.decoded("SEQUENCE"))
    except Exception:
        try:
            ham = comp["SEQUENCE"]
            if isinstance(ham, list):
                ham = ham[-1]
            return int(str(ham))
        except Exception:
            return 0


def _status(comp) -> str | None:
    """STATUS büyük harfle; yoksa None."""
    if "STATUS" not in comp:
        return None
    try:
        return str(comp.decoded("STATUS")).strip().upper() or None
    except Exception:
        try:
            return str(comp["STATUS"]).strip().upper() or None
        except Exception:
            return None


def _sure(comp) -> timedelta | None:
    """DURATION timedelta olarak; yoksa None."""
    if "DURATION" not in comp:
        return None
    try:
        deger = comp.decoded("DURATION")
    except Exception:
        return None
    if isinstance(deger, timedelta):
        return deger
    return None


def _rrule_metin(comp) -> str | None:
    """RRULE ham metni; naive UNTIL'e dokunulmaz (`core` normalize ediyor).

    `to_ical()` UNTIL'i geldiği gibi (Z'li veya naive) yazar, o yüzden ham hâl
    korunmuş olur (tuzak 9).
    """
    if "RRULE" not in comp:
        return None
    ham = comp["RRULE"]
    parcalar: list[str] = []
    hamlar = ham if isinstance(ham, list) else [ham]
    for parcada in hamlar:
        try:
            parcalar.append(parcada.to_ical().decode("utf-8", errors="replace").strip())
        except Exception:
            continue
    metin = "\n".join(p for p in parcalar if p).strip()
    return metin or None


def _liste_topla(comp, ad: str) -> list:
    """EXDATE/RDATE ham taşıyıcılarını liste olarak döndürür.

    Tek satır tek `vDDDLists`, birden çok satır `vDDDLists` listesidir; ayrıca
    virgüllü değerler tek taşıyıcıda birden çok `dts` olur (tuzak 8).
    """
    if ad not in comp:
        return []
    ham = comp[ad]
    return list(ham) if isinstance(ham, list) else [ham]


def _utc_listesi(
    comp,
    ad: str,
    event_tzid: str,
    default_tzid: str,
    warnings: list[str],
    uid: str,
) -> list[datetime]:
    """EXDATE/RDATE değerlerini UTC an listesine çevirir.

    Yüzen (naive, TZID'siz) değerler serinin kendi diliminde yorumlanır: bunlar
    serinin örneklerine gönderme yapıyor, `default_tzid`'den bağımsız olmalı ki
    dışlama isabet etsin. Bilinmeyen TZID'de uyarıyla seri dilimine düşülür.
    UTC (`Z`) anlar olduğu gibi alınır. DATE değerleri seri diliminde gece
    yarısı sayılır.
    """
    cikti: list[datetime] = []
    for dis in _liste_topla(comp, ad):
        dis_tzid = _tzid_parami(dis)
        icler = list(dis.dts) if hasattr(dis, "dts") else [dis]
        for ic in icler:
            deger = _dt_degeri(ic)
            if deger is None:
                continue
            ic_tzid = _tzid_parami(ic) or dis_tzid
            if isinstance(deger, datetime):
                if deger.tzinfo is not None and deger.tzinfo.utcoffset(deger) is not None:
                    cikti.append(deger.astimezone(UTC))
                else:
                    duvar = deger.replace(tzinfo=None)
                    if ic_tzid:
                        try:
                            get_tz(ic_tzid)
                            tzid = ic_tzid
                        except ValueError:
                            cevrilmis = resolve_windows_tz(ic_tzid)
                            if cevrilmis is not None:
                                try:
                                    get_tz(cevrilmis)
                                    tzid = cevrilmis
                                except ValueError:
                                    warnings.append(
                                        f"({uid}) {ad} saat dilimi {ic_tzid!r} bilinmiyor, "
                                        f"etkinlik dilimi {event_tzid!r} varsayıldı"
                                    )
                                    tzid = event_tzid
                            else:
                                warnings.append(
                                    f"({uid}) {ad} saat dilimi {ic_tzid!r} bilinmiyor, "
                                    f"etkinlik dilimi {event_tzid!r} varsayıldı"
                                )
                                tzid = event_tzid
                    else:
                        tzid = event_tzid
                    cikti.append(from_wall_clock(duvar, tzid))
            elif isinstance(deger, date):
                cikti.append(from_wall_clock(datetime(deger.year, deger.month, deger.day), event_tzid))
            # else: tanınmayan tür sessizce atlanır mı? Hayır: veri kaybı
            # olmasın diye uyarı üretiyoruz.
            else:
                warnings.append(f"({uid}) {ad} değeri anlaşılamadı, atlandı: {deger!r}")
    return cikti


def _baslangic_bitisi(
    comp,
    default_tzid: str,
    warnings: list[str],
    uid: str,
) -> tuple[datetime, datetime, str, bool]:
    """DTSTART/DTEND/DURATION üçlüsünden (start_utc, end_utc, tzid, all_day).

    Kararlar (gerekçeleriyle):
    - Tüm gün: DATE türü belirler; bitiş dışlayıcı gece yarısıdır, doğrudan
      eşleşir (tuzak 1).
    - DTEND yok + DURATION var: ondan hesaplanır (tuzak 2).
    - İkisi de yok + DATE: +1 gün (tek günlük etkinlik).
    - İkisi de yok + DATE-TIME: RFC sıfır süre der ama `Event` sıfır süreyi
      reddeder; veri kaybetmek yerine Google'ın yeni etkinlik varsayılanı gibi
      1 saat alınıp uyarı üretilir.
    """
    dtstart_ham = _tek_ham(comp, "DTSTART", uid, warnings)
    if dtstart_ham is None:
        raise ValueError("DTSTART yok")
    dtstart_deger = _dt_degeri(dtstart_ham)
    if dtstart_deger is None:
        raise ValueError("DTSTART okunamadı")
    dtstart_tzid = _tzid_parami(dtstart_ham)

    dtend_ham = _tek_ham(comp, "DTEND", uid, warnings)
    dtend_deger = _dt_degeri(dtend_ham) if dtend_ham is not None else None
    sure = _sure(comp)

    baslangic_is_date = isinstance(dtstart_deger, date) and not isinstance(dtstart_deger, datetime)
    bitis_is_date = isinstance(dtend_deger, date) and not isinstance(dtend_deger, datetime)

    if baslangic_is_date != (dtend_deger is not None and bitis_is_date) and dtend_deger is not None:
        # Biri DATE biri DATE-TIME: RFC'ye aykırı karışım, sessizce yarım
        # yorumlamak yerine hata sayıyoruz.
        raise ValueError("DTSTART ve DTEND türleri uyumsuz (DATE / DATE-TIME karışık)")

    if baslangic_is_date:
        all_day = True
        tzid = default_tzid
        start_utc = from_wall_clock(
            datetime(dtstart_deger.year, dtstart_deger.month, dtstart_deger.day), tzid
        )
        if dtend_deger is not None:
            end_utc = from_wall_clock(
                datetime(dtend_deger.year, dtend_deger.month, dtend_deger.day), tzid
            )
        elif sure is not None:
            end_utc = start_utc + sure
        else:
            end_utc = start_utc + timedelta(days=1)
        return start_utc, end_utc, tzid, all_day

    # Saatli etkinlik
    if not isinstance(dtstart_deger, datetime):
        raise ValueError("DTSTART okunamadı")
    start_utc, tzid = _an_to_utc(dtstart_deger, dtstart_tzid, default_tzid, warnings, uid, "DTSTART")

    if dtend_deger is not None:
        if not isinstance(dtend_deger, datetime):
            raise ValueError("DTSTART ve DTEND türleri uyumsuz (DATE / DATE-TIME karışık)")
        dtend_tzid = _tzid_parami(dtend_ham)
        # Bitiş anı kendi TZID'iyle çözülür; tzid hanesi başlangıcın dilimini
        # taşır (görünüm ve tekrar genişletmesi ona göre yapılır).
        if dtend_deger.tzinfo is not None and dtend_deger.tzinfo.utcoffset(dtend_deger) is not None:
            if dtend_tzid:
                bitis_tzid = _resolve_tzid(dtend_tzid, default_tzid, warnings, uid, "DTEND")
                end_utc = from_wall_clock(dtend_deger.replace(tzinfo=None), bitis_tzid)
            else:
                end_utc = dtend_deger.astimezone(UTC)
        else:
            duvar = dtend_deger.replace(tzinfo=None)
            if dtend_tzid:
                bitis_tzid = _resolve_tzid(dtend_tzid, default_tzid, warnings, uid, "DTEND")
            else:
                bitis_tzid = default_tzid
            end_utc = from_wall_clock(duvar, bitis_tzid)
    elif sure is not None:
        end_utc = start_utc + sure
    else:
        end_utc = start_utc + timedelta(hours=1)
        warnings.append(
            f"({uid}) DTEND ve DURATION yok, süre 1 saat varsayıldı "
            "(RFC sıfır süre der ama model sıfır süreyi reddediyor)"
        )
    return start_utc, end_utc, tzid, False


# ---------------------------------------------------------------------------
# Saf ayrıştırma
# ---------------------------------------------------------------------------


def parse_ics(source: str | Path, *, default_tzid: str) -> tuple[list[ParsedEvent], ImportReport]:
    """`.ics` metnini modellere çevirir, DB'ye dokunmaz.

    Aynı UID'li VEVENT'ler tek seriyi tarif eder: RECURRENCE-ID'siz olan ana
    kayıt, diğerleri örnek geçersiz kılmalarıdır. Bozuk tekil VEVENT raporun
    `errors` hanesine yazılır, kalanına devam edilir. VEVENT dışındaki
    bileşenler (VTODO, VJOURNAL, VFREEBUSY, VTIMEZONE) atlanır, hata sayılmaz.
    """
    try:
        get_tz(default_tzid)
    except ValueError as exc:
        raise ValueError(f"default_tzid geçersiz: {default_tzid!r}") from exc

    try:
        takvim = _to_calendar(source)
    except Exception as exc:
        rapor = ImportReport(errors=((_UID_YOK, f"dosya okunamadı: {exc}"),))
        return [], rapor

    tum_veventler = [c for c in takvim.walk() if getattr(c, "name", None) == "VEVENT"]

    # UID'ye göre grupla; dosya sırası korunur (rapor ve sonuç deterministik).
    sira: list[str] = []
    ana_kayitlar: dict[str, list] = {}
    ornekler: dict[str, list] = {}

    errors: list[tuple[str, str]] = []
    warnings: list[str] = []
    atlanan = 0

    for comp in tum_veventler:
        uid_ham = _metin(comp, "UID")
        uid = uid_ham.strip() if uid_ham else ""
        if not uid:
            errors.append((_UID_YOK, "UID yok, VEVENT atlandı"))
            continue
        if uid not in ana_kayitlar and uid not in ornekler:
            sira.append(uid)
        hedef = ornekler if "RECURRENCE-ID" in comp else ana_kayitlar
        hedef.setdefault(uid, []).append(comp)

    parsed: list[ParsedEvent] = []

    for uid in sira:
        ana_liste = ana_kayitlar.get(uid, [])
        ornek_liste = ornekler.get(uid, [])

        if not ana_liste:
            # Ana kayıtsız RECURRENCE-ID tek başına anlamsız; sessizce
            # düşerse kullanıcı neden örneğin gelmediğini anlayamaz.
            errors.append((uid, "ana kayıt (RECURRENCE-ID'siz VEVENT) yok, örnek atlandı"))
            continue

        # Aynı UID ile birden çok ana kayıt: RFC'de SEQUENCE en büyük olan
        # güncel sayılır; diğerleri atlanır (uyarıyla, sessizce değil).
        secilen = ana_liste[0]
        secilen_seq = _sequence(secilen)
        for aday in ana_liste[1:]:
            aday_seq = _sequence(aday)
            if aday_seq > secilen_seq:
                secilen, secilen_seq = aday, aday_seq
        if len(ana_liste) > 1:
            atlanan += len(ana_liste) - 1
            warnings.append(f"({uid}) aynı UID ile {len(ana_liste)} ana kayıt var, SEQUENCE en büyük olan alındı")

        if (_status(secilen) or "") == "CANCELLED":
            # Serinin tamamı iptal edilmiş: olay yok, hata da yok.
            atlanan += 1
            continue

        try:
            start_utc, end_utc, tzid, all_day = _baslangic_bitisi(secilen, default_tzid, warnings, uid)
        except ValueError as exc:
            errors.append((uid, f"zaman okunamadı: {exc}"))
            continue

        baslik = _metin(secilen, "SUMMARY") or _BASSIZ
        aciklama = _metin(secilen, "DESCRIPTION")
        konum = _metin(secilen, "LOCATION")
        rrule = _rrule_metin(secilen)
        try:
            rdate = tuple(_utc_listesi(secilen, "RDATE", tzid, default_tzid, warnings, uid))
            exdate = tuple(_utc_listesi(secilen, "EXDATE", tzid, default_tzid, warnings, uid))
        except ValueError as exc:
            errors.append((uid, f"RDATE/EXDATE okunamadı: {exc}"))
            continue

        try:
            event = Event(
                id=None,
                uid=uid,
                calendar_id=None,
                title=baslik,
                start_utc=start_utc,
                end_utc=end_utc,
                tzid=tzid,
                all_day=all_day,
                rrule=rrule,
                rdate=rdate,
                exdate=exdate,
                description=aciklama,
                location=konum,
            )
        except ValueError as exc:
            # Örn. DTEND < DTSTART (tuzak 12): bu kayıt gider, kalan sürer.
            errors.append((uid, str(exc)))
            continue

        # Bilinen sınır (AGENTS.md §4): DTSTART'tan önceye düşen RDATE aday
        # sorgusuyla bulunamaz. Sessizce geçmek yerine uyarıyoruz.
        for ek in event.rdate:
            if ek < event.start_utc:
                warnings.append(
                    f"({uid}) RDATE DTSTART'tan önce ({ek.isoformat()}), "
                    "aralık sorgusu bu örneği bulamayabilir (bilinen sınır)"
                )
                break

        overrides: list[Override] = []
        for comp in ornek_liste:
            rid_ham = _tek_ham(comp, "RECURRENCE-ID", uid, warnings)
            if rid_ham is None:
                errors.append((uid, "RECURRENCE-ID okunamadı, örnek atlandı"))
                continue
            rid_params = getattr(rid_ham, "params", {}) or {}
            try:
                menzil = str(rid_params.get("RANGE", "")).strip().upper()
            except Exception:
                menzil = ""
            if menzil == "THISANDFUTURE":
                # Modelde karşılığı yok; sessizce tek örneğe indirgemek veri
                # kaybını gizlerdi, o yüzden hata sayıyoruz (tuzak 6).
                errors.append((uid, "RANGE=THISANDFUTURE desteklenmiyor, örnek atlandı"))
                continue
            rid_deger = _dt_degeri(rid_ham)
            if rid_deger is None:
                errors.append((uid, "RECURRENCE-ID okunamadı, örnek atlandı"))
                continue
            try:
                if isinstance(rid_deger, datetime):
                    rid_tzid = _tzid_parami(rid_ham)
                    orijinal, _ = _an_to_utc(rid_deger, rid_tzid, default_tzid, warnings, uid, "RECURRENCE-ID")
                elif isinstance(rid_deger, date):
                    orijinal = from_wall_clock(
                        datetime(rid_deger.year, rid_deger.month, rid_deger.day), event.tzid
                    )
                else:
                    errors.append((uid, "RECURRENCE-ID okunamadı, örnek atlandı"))
                    continue
            except ValueError as exc:
                errors.append((uid, f"RECURRENCE-ID okunamadı: {exc}"))
                continue

            durum = _status(comp) or ""
            if durum == "CANCELLED":
                try:
                    overrides.append(
                        Override(event_id=None, original_start_utc=orijinal, cancelled=True)
                    )
                except ValueError as exc:
                    errors.append((uid, str(exc)))
                continue

            # Kaydırılmış / yeniden adlandırılmış örnek.
            yeni_baslangic: datetime | None = None
            yeni_bitis: datetime | None = None
            try:
                if "DTSTART" in comp:
                    ys_ham = _tek_ham(comp, "DTSTART", uid, warnings)
                    ys_deger = _dt_degeri(ys_ham)
                    if isinstance(ys_deger, datetime):
                        yeni_baslangic, _ = _an_to_utc(
                            ys_deger, _tzid_parami(ys_ham), default_tzid, warnings, uid, "DTSTART"
                        )
                    elif isinstance(ys_deger, date):
                        yeni_baslangic = from_wall_clock(
                            datetime(ys_deger.year, ys_deger.month, ys_deger.day), event.tzid
                        )
                if "DTEND" in comp and yeni_baslangic is not None:
                    ye_ham = _tek_ham(comp, "DTEND", uid, warnings)
                    ye_deger = _dt_degeri(ye_ham)
                    if isinstance(ye_deger, datetime):
                        if ye_deger.tzinfo is not None and ye_deger.tzinfo.utcoffset(ye_deger) is not None:
                            ye_tzid = _tzid_parami(ye_ham)
                            if ye_tzid:
                                bitis_tzid = _resolve_tzid(ye_tzid, default_tzid, warnings, uid, "DTEND")
                                yeni_bitis = from_wall_clock(ye_deger.replace(tzinfo=None), bitis_tzid)
                            else:
                                yeni_bitis = ye_deger.astimezone(UTC)
                        else:
                            duvar = ye_deger.replace(tzinfo=None)
                            ye_tzid = _tzid_parami(ye_ham)
                            bitis_tzid = (
                                _resolve_tzid(ye_tzid, default_tzid, warnings, uid, "DTEND")
                                if ye_tzid
                                else default_tzid
                            )
                            yeni_bitis = from_wall_clock(duvar, bitis_tzid)
                    elif isinstance(ye_deger, date):
                        yeni_bitis = from_wall_clock(
                            datetime(ye_deger.year, ye_deger.month, ye_deger.day), event.tzid
                        )
                elif "DURATION" in comp and yeni_baslangic is not None:
                    sure2 = _sure(comp)
                    if sure2 is not None:
                        yeni_bitis = yeni_baslangic + sure2
                # DTEND de DURATION da yoksa bitiş None kalır: süre seriden
                # miras alınır (`core.expand` ve `store.put_override` böyle
                # çalışıyor), o yüzden burada uydurmuyoruz.
            except ValueError as exc:
                errors.append((uid, f"örnek zamanı okunamadı: {exc}"))
                continue

            o_baslik = _metin(comp, "SUMMARY")
            o_konum = _metin(comp, "LOCATION")
            yeni_baslik = o_baslik if (o_baslik is not None and o_baslik != event.title) else None
            yeni_konum = o_konum if (o_konum is not None and o_konum != event.location) else None
            try:
                overrides.append(
                    Override(
                        event_id=None,
                        original_start_utc=orijinal,
                        cancelled=False,
                        new_start_utc=yeni_baslangic,
                        new_end_utc=yeni_bitis,
                        new_title=yeni_baslik,
                        new_location=yeni_konum,
                    )
                )
            except ValueError as exc:
                errors.append((uid, str(exc)))
                continue

        overrides.sort(key=lambda o: o.original_start_utc)
        parsed.append(ParsedEvent(event=event, overrides=tuple(overrides), sequence=secilen_seq))

    toplam_override = sum(len(p.overrides) for p in parsed)
    rapor = ImportReport(
        added=len(parsed),
        updated=0,
        skipped=atlanan,
        overrides=toplam_override,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )
    return parsed, rapor


# ---------------------------------------------------------------------------
# Kaydetme
# ---------------------------------------------------------------------------


def _eskimis_mi(gelen: int, kayitli: int | None) -> bool:
    """Gelen `.ics` sürümü DB'dekinden eski mi (yani atlanmalı mı).

    `kayitli is None` = bu etkinlik daha önce `.ics`'ten içe aktarılmamış
    (elle oluşturulmuş ya da 002 migration'ından önce yazılmış). Karşılaştıracak
    bir sürüm olmadığı için içe aktarma KABUL edilir; aksi hâlde elle
    oluşturulmuş bir kayıt aynı UID'yi taşıdığında güncelleme sessizce düşerdi.
    """
    return kayitli is not None and int(gelen) < int(kayitli)


def import_ics(
    repo,
    source: str | Path,
    *,
    calendar_id: int,
    default_tzid: str,
    dry_run: bool = False,
) -> ImportReport:
    """Ayrıştırır ve kaydeder. UID zaten varsa günceller (mükerrer kayıt yok).

    `SEQUENCE` daha küçükse atlanır (`skipped`): eski bir dışa aktarma, yeni
    hâli ezmez. `dry_run=True` DB'yi değiştirmez ama rapor yine dolar.
    """
    try:
        get_tz(default_tzid)
    except ValueError as exc:
        raise ValueError(f"default_tzid geçersiz: {default_tzid!r}") from exc
    if repo.get_calendar(calendar_id) is None:
        raise ValueError(f"Takvim bulunamadı: id={calendar_id}")

    from dataclasses import replace

    parsed, on_rapor = parse_ics(source, default_tzid=default_tzid)

    eklenen = 0
    guncellenen = 0
    atlanan = int(on_rapor.skipped)
    yazilan_override = 0
    hatalar: list[tuple[str, str]] = list(on_rapor.errors)
    uyarilar: list[str] = list(on_rapor.warnings)

    for p in parsed:
        uid = p.event.uid
        mevcut = repo.get_event_by_uid(uid)
        if mevcut is None:
            if dry_run:
                eklenen += 1
                yazilan_override += len(p.overrides)
                continue
            try:
                kaydedilen = repo.add_event(replace(p.event, calendar_id=calendar_id))
                repo.set_ics_sequence(kaydedilen.id, p.sequence)
                for ov in p.overrides:
                    repo.put_override(replace(ov, event_id=kaydedilen.id))
                eklenen += 1
                yazilan_override += len(p.overrides)
            except Exception as exc:
                hatalar.append((uid, f"kaydedilemedi: {exc}"))
            continue

        # UID var: SEQUENCE karşılaştırması (tuzak 11). Karşılaştırma
        # `ics_sequence`'e bakar, `sequence`'e DEĞİL -- ikincisi Repo'nun yerel
        # revizyon sayacı ve elle yapılan her düzenlemede artıyor; ona baksaydık
        # bir kez elle düzenlenen etkinlik bir daha hiç güncellenemezdi.
        kayitli_seq = repo.get_ics_sequence(mevcut.id)
        if _eskimis_mi(p.sequence, kayitli_seq):
            atlanan += 1
            uyarilar.append(
                f"({uid}) dosyadaki SEQUENCE={p.sequence}, kayıtlı sürüm "
                f"{kayitli_seq}; daha eski olduğu için atlandı"
            )
            continue
        if dry_run:
            guncellenen += 1
            yazilan_override += len(p.overrides)
            continue
        try:
            # Güncelleme MEVCUT takvimde kalır: içe aktarma hedefi yalnızca YENİ
            # kayıtlar için. Eskiden hedef takvime taşınıyordu ve kullanıcı
            # fark etmeden etkinlik takvim değiştiriyordu.
            repo.update_event(replace(p.event, id=mevcut.id, calendar_id=mevcut.calendar_id))
            repo.set_ics_sequence(mevcut.id, p.sequence)
            # Override senkronu: kaynakta artık olmayan geçersiz kılma
            # DB'de öksüz kalmasın, yoksa silinen örnek geri gelmez.
            eskiler = repo.list_overrides(mevcut.id)
            yeniler = {o.original_start_utc for o in p.overrides}
            for eski in eskiler:
                if eski.original_start_utc not in yeniler:
                    repo.delete_override(mevcut.id, eski.original_start_utc)
            for ov in p.overrides:
                repo.put_override(replace(ov, event_id=mevcut.id))
            guncellenen += 1
            yazilan_override += len(p.overrides)
        except Exception as exc:
            hatalar.append((uid, f"güncellenemedi: {exc}"))

    return ImportReport(
        added=eklenen,
        updated=guncellenen,
        skipped=atlanan,
        overrides=yazilan_override,
        errors=tuple(hatalar),
        warnings=tuple(uyarilar),
    )
