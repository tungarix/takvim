"""Senkron dosyası (`.takvimsync`) İÇE aktarma: yerel veriyle birleştirme.

Kurallar `docs/senkron.md` §2'de; burası onun kodu. Özet: anahtar `uid`, kayıt
düzeyinde SON YAZAN KAZANIR (`updated_at`), silmeler mezar taşıyla (`silinenler`)
yürür, hepsi TEK transaction (hata olursa hiçbir şey değişmez) ve aynı dosyayı
ikinci kez içe aktarmak hiçbir şeyi değiştirmez.

İki yapısal karar:

- Dosya önce SAF olarak ayrıştırılıp doğrulanır (`_ayristir`, DB'ye dokunmaz);
  bozuk bir kayıt dosyanın TAMAMINI reddeder. Kayıt kayıt atlamak, yarım
  birleşmiş bir veritabanı demek: ikinci içe aktarmada farklı sonuç çıkardı.
- Yazım `repo.conn` üzerinden ham SQL: `updated_at` dosyadaki değere sabitlenmeli
  ve mezar taşı `deleted_at`'i dosyadakiyle aynı yazılmalı, Repo ikisini de
  "şimdi" yazıyor. Şemadaki tetikleyiciler (006) çocuk yazımlarında etkinliğin
  `updated_at`'ini ve silmede mezar taşını ŞİMDİ olarak yazar; bu yüzden her
  kayıt için önce asıl yazım, SONRA zaman damgası düzeltmesi yapılır.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import date, datetime

from core import Event, Override, Task, next_rule_start, parse_iso
from core.recurrence import series_end_sayili
from store import Repo
from store.repo import _event_ekle, _event_guncelle, _to_db, _tx

from .disa import BICIM, SURUM

__all__ = ["SenkronHatasi", "SenkronRaporu", "ice_aktar"]

TURLER = ("calendar", "event", "task")

# Hatırlatıcı en çok 10 yıl önce: daha büyüğü `başlangıç - dakika` hesabında OverflowError verip
# hatırlatıcı döngüsünü her turda düşürürdü (dosyada sınır yok, uygulamalar bunu reddeder).
MAKS_HATIRLATICI = 10 * 365 * 24 * 60
# Etkinlik başına hatırlatıcı sayısı: gerçek kullanım bir elinin parmakları kadar; sınırsız
# dizi (8 MB'a sığan ~1 milyon değer) hatırlatıcı döngüsünü her turda şişirirdi.
MAKS_HATIRLATICI_SAYISI = 1000
# CPU bütçesi (token sahibi/kötü niyetli dosya doğrulamayı saniyelerce meşgul etmesin): bir dosyadaki
# etkinlik sayısı ve SINIRLI (COUNT/UNTIL) serilerin doğrulamada sayılan örneklerinin TOPLAMI.
# Ölçüm (bu makine): ~2,2 µs/örnek => 500.000 örnek ~1,1 sn en kötü durumda; gerçek kullanıcı verisi
# (5000 etkinlik, çoğu tek, birkaç yüz seri x 50-400 örnek) bunun çok altında kalır. Sınırsız seriler
# (COUNT/UNTIL'siz) örnek SAYILMAZ: doğrulamada üretilmezler.
MAKS_ETKINLIK = 20_000
MAKS_TOPLAM_ORNEK = 500_000

_ZAMAN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_RENK = re.compile(r"^#[0-9a-fA-F]{6}$")


class SenkronHatasi(ValueError):
    """Senkron dosyası reddedildi; hiçbir şey değişmedi.

    `kod`/`param` sunucunun hata gövdesine gidiyor (`ui/server.py::_yakala`
    bu iki alana bakıyor), ön yüz `hata_<kod>` şablonunu kullanıyor.
    """

    def __init__(self, kod: str, mesaj: str, param: dict | None = None) -> None:
        super().__init__(mesaj)
        self.kod = kod
        self.param = param


def _bozuk(ayrinti: str) -> SenkronHatasi:
    return SenkronHatasi(
        "senkron_bozuk", f"senkron dosyası geçersiz: {ayrinti}", {"ayrinti": ayrinti}
    )


@dataclass
class SenkronRaporu:
    """İçe aktarma sonucu: sonuca (`added`...) ve türe (takvim/etkinlik/görev) göre sayılar.

    `skipped` yalnızca yetim etkinlikler (takvimi yerelde olmayan): veri kaybı
    değil, kullanıcıya söylenmesi gereken bir şey.
    """

    added: dict[str, int] = field(default_factory=lambda: dict.fromkeys(TURLER, 0))
    updated: dict[str, int] = field(default_factory=lambda: dict.fromkeys(TURLER, 0))
    deleted: dict[str, int] = field(default_factory=lambda: dict.fromkeys(TURLER, 0))
    skipped: dict[str, int] = field(default_factory=lambda: dict.fromkeys(TURLER, 0))

    def as_dict(self) -> dict:
        """JSON'a hazır hâl; her sonucun toplamı `total` altında."""
        sonuclar = {
            "added": self.added,
            "updated": self.updated,
            "deleted": self.deleted,
            "skipped": self.skipped,
        }
        return {**sonuclar, "total": {ad: sum(s.values()) for ad, s in sonuclar.items()}}


# ---------------------------------------------------------------------------
# Ayrıştırma ve doğrulama (saf; DB'ye dokunmaz)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Etkinlik:
    event: Event          # calendar_id=None; yazarken doldurulur
    calendar_uid: str
    reminders: tuple[int, ...]
    overrides: tuple[Override, ...]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class _Takvim:
    uid: str
    name: str
    color: str
    visible: bool
    updated_at: str


@dataclass(frozen=True)
class _Gorev:
    uid: str
    task: Task            # id/event_id=None; başlık/not model tarafından normalize
    event_uid: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class _Dosya:
    takvimler: list[_Takvim]
    etkinlikler: list[_Etkinlik]
    gorevler: list[_Gorev]
    silinenler: dict[tuple[str, str], str]


def _zaman(deger: object, ad: str) -> str:
    """Sabit genişlikli UTC metni (`YYYY-MM-DDTHH:MM:SSZ`) bekler."""
    if not isinstance(deger, str) or not _ZAMAN.match(deger):
        raise _bozuk(f"{ad}: UTC zamanı (YYYY-MM-DDTHH:MM:SSZ) bekleniyor")
    try:
        datetime.strptime(deger, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise _bozuk(f"{ad}: geçersiz tarih") from None
    return deger


def _metin(h: dict, ad: str, *, bos_olamaz: bool = False, bos_olabilir: bool = False) -> str | None:
    """Alanı metin olarak okur; `bos_olabilir` ise None kabul eder."""
    deger = h.get(ad)
    if deger is None and bos_olabilir:
        return None
    if not isinstance(deger, str) or (bos_olamaz and not deger.strip()):
        raise _bozuk(f"{ad}: metin bekleniyor")
    return deger


def _bool(h: dict, ad: str, varsayilan: bool | None = None) -> bool:
    """Alanı true/false olarak okur (0/1 KABUL EDİLMEZ)."""
    deger = h.get(ad, varsayilan)
    if not isinstance(deger, bool):
        raise _bozuk(f"{ad}: true/false bekleniyor")
    return deger


def _zaman_listesi(deger: object, ad: str) -> tuple[datetime, ...]:
    """`rdate`/`exdate`: zaman metinleri dizisi (yoksa boş)."""
    if deger is None:
        return ()
    if not isinstance(deger, list):
        raise _bozuk(f"{ad}: dizi bekleniyor")
    return tuple(sorted({parse_iso(_zaman(z, ad)) for z in deger}))  # yinelenenler tek (mobil de öyle)


def _kayitlar(dosya: dict, ad: str) -> list[dict]:
    """Üst düzey liste alanı (yoksa boş); elemanlar nesne olmalı."""
    liste = dosya.get(ad, [])
    if not isinstance(liste, list) or not all(isinstance(k, dict) for k in liste):
        raise _bozuk(f"{ad}: nesne dizisi bekleniyor")
    return liste


def _takvim_ayristir(h: dict) -> _Takvim:
    renk = _metin(h, "color", bos_olamaz=True)
    if renk is None or not _RENK.match(renk):
        raise _bozuk("color: #rrggbb bekleniyor")  # AGENTS 54: CSS'e giriyor
    return _Takvim(
        uid=_metin(h, "uid", bos_olamaz=True) or "",
        name=(_metin(h, "name", bos_olamaz=True) or "").strip(),  # mobil modeli de kırpar
        color=renk,
        visible=_bool(h, "visible", True),
        updated_at=_zaman(h.get("updated_at"), "updated_at"),
    )


def _override_ayristir(h: dict, sure) -> Override:
    bas = h.get("new_start_utc")
    bit = h.get("new_end_utc")
    yeni_bas = parse_iso(_zaman(bas, "new_start_utc")) if bas is not None else None
    yeni_bit = parse_iso(_zaman(bit, "new_end_utc")) if bit is not None else None
    if yeni_bas is not None and yeni_bit is None:
        yeni_bit = yeni_bas + sure  # Repo.put_override ile aynı: aday sorgusu bitişi bilmeli
    return Override(
        event_id=None,
        original_start_utc=parse_iso(_zaman(h.get("original_start_utc"), "original_start_utc")),
        cancelled=_bool(h, "cancelled", False),
        new_start_utc=yeni_bas,
        new_end_utc=yeni_bit,
        new_title=_metin(h, "new_title", bos_olabilir=True),
        new_location=_metin(h, "new_location", bos_olabilir=True),
    )


def _etkinlik_ayristir(h: dict, butce: list[int]) -> _Etkinlik:
    uid = _metin(h, "uid", bos_olamaz=True) or ""
    guncelleme = _zaman(h.get("updated_at"), "updated_at")
    olusturma = _zaman(h["created_at"], "created_at") if "created_at" in h else guncelleme
    rrule = h.get("rrule") or None
    if rrule is not None and not isinstance(rrule, str):
        raise _bozuk("rrule: metin bekleniyor")
    event = Event(  # tzid, bitiş>başlangıç, tüm gün, rrule burada doğrulanır
        id=None,
        uid=uid,
        calendar_id=None,
        title=_metin(h, "title") or "",
        start_utc=parse_iso(_zaman(h.get("start_utc"), "start_utc")),
        end_utc=parse_iso(_zaman(h.get("end_utc"), "end_utc")),
        tzid=_metin(h, "tzid", bos_olamaz=True) or "",
        all_day=_bool(h, "all_day", False),
        rrule=rrule,
        rdate=_zaman_listesi(h.get("rdate"), "rdate"),
        exdate=_zaman_listesi(h.get("exdate"), "exdate"),
        description=_metin(h, "description", bos_olabilir=True),
        location=_metin(h, "location", bos_olabilir=True),
    )
    _, ornek = series_end_sayili(event)  # çok yoğun seri (TKV-API-001) burada ValueError verir
    butce[0] += ornek
    if butce[0] > MAKS_TOPLAM_ORNEK:
        raise _bozuk(f"seriler toplamda çok yoğun: en çok {MAKS_TOPLAM_ORNEK} örnek")
    if rrule is not None:
        # Sınırsız bozuk kural series_end'de çözülmüyor; içeri girerse expand() her görünümde
        # patlar ve o ay bir daha açılamaz. Burada çöz, çözülmezse dosyayı reddet (AGENTS 87).
        try:
            next_rule_start(event, event.start_utc)
        except ValueError:
            raise _bozuk(f"rrule çözülemedi ({uid}): {rrule}") from None
    hatirlaticilar = h.get("reminders", [])
    if isinstance(hatirlaticilar, list) and len(hatirlaticilar) > MAKS_HATIRLATICI_SAYISI:
        raise _bozuk(f"reminders: en çok {MAKS_HATIRLATICI_SAYISI} hatırlatıcı ({uid})")
    if not isinstance(hatirlaticilar, list) or not all(
        isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= MAKS_HATIRLATICI for d in hatirlaticilar
    ):
        raise _bozuk(f"reminders: 0..{MAKS_HATIRLATICI} arası tamsayı dizisi bekleniyor")
    ham_override = h.get("overrides", [])
    if not isinstance(ham_override, list) or not all(isinstance(o, dict) for o in ham_override):
        raise _bozuk("overrides: nesne dizisi bekleniyor")
    override_ler = tuple(_override_ayristir(o, event.duration) for o in ham_override)
    anahtarlar = [o.original_start_utc for o in override_ler]
    if len(set(anahtarlar)) != len(anahtarlar):
        raise _bozuk(f"overrides: aynı örnek iki kez ({uid})")
    return _Etkinlik(
        event=event,
        calendar_uid=_metin(h, "calendar_uid", bos_olamaz=True) or "",
        reminders=tuple(sorted(set(hatirlaticilar))),
        overrides=override_ler,
        created_at=olusturma,
        updated_at=guncelleme,
    )


def _gorev_ayristir(h: dict) -> _Gorev:
    guncelleme = _zaman(h.get("updated_at"), "updated_at")
    olusturma = _zaman(h["created_at"], "created_at") if "created_at" in h else guncelleme
    gun = _metin(h, "plan_day", bos_olabilir=True)
    event_uid = _metin(h, "event_uid", bos_olabilir=True)
    if gun is not None and event_uid is not None:
        raise _bozuk("görevde plan_day ve event_uid birlikte dolu olamaz")
    bitis = h.get("done_at")
    task = Task(  # başlık boş olamaz, not/başlık kırpılır
        id=None,
        uid=_metin(h, "uid", bos_olamaz=True) or "",
        title=_metin(h, "title") or "",
        notes=_metin(h, "notes", bos_olabilir=True),
        plan_day=date.fromisoformat(gun) if gun is not None else None,
        done_at=parse_iso(_zaman(bitis, "done_at")) if bitis is not None else None,
    )
    return _Gorev(
        uid=task.uid, task=task, event_uid=event_uid,
        created_at=olusturma, updated_at=guncelleme,
    )


def _vekilsiz(deger: object) -> bool:
    """Metinlerde yalnız (eşsiz) vekil karakter YOK mu. JSON, yalnız vekil kaçışına (U+D800..DFFF) izin veriyor ama UTF-8'e
    yazılamaz: kayıt sırasında ham UnicodeEncodeError olurdu."""
    if isinstance(deger, str):
        try:
            deger.encode("utf-8")
        except UnicodeEncodeError:
            return False
        return True
    if isinstance(deger, dict):
        return all(_vekilsiz(k) and _vekilsiz(v) for k, v in deger.items())
    if isinstance(deger, list):
        return all(_vekilsiz(v) for v in deger)
    return True


def _tekil(uidler: list[str], ad: str) -> None:
    if len(set(uidler)) != len(uidler):
        raise _bozuk(f"{ad}: aynı uid iki kez")


def _ayristir(kaynak: str | bytes | dict) -> _Dosya:
    """Dosyayı doğrular ve ayrıştırır; sorun varsa `SenkronHatasi`."""
    if isinstance(kaynak, dict):
        dosya: object = kaynak
    else:
        try:
            dosya = json.loads(
                kaynak.decode("utf-8-sig") if isinstance(kaynak, bytes) else kaynak
            )
        except ValueError:  # JSONDecodeError ve UnicodeDecodeError ikisi de ValueError
            raise _bozuk("JSON olarak okunamadı") from None
    if not isinstance(dosya, dict) or dosya.get("format") != BICIM:
        raise _bozuk(f'"format": "{BICIM}" bekleniyor')
    if not _vekilsiz(dosya):
        raise _bozuk("geçersiz Unicode (yalnız vekil karakter)")
    surum = dosya.get("version")
    if not isinstance(surum, int) or isinstance(surum, bool) or surum < 1:
        raise _bozuk("version: pozitif tamsayı bekleniyor")
    if surum > SURUM:
        raise SenkronHatasi(
            "senkron_surum_yeni",
            f"dosya sürümü {surum} bu uygulamanın bildiğinden ({SURUM}) yeni: "
            "uygulamayı güncelle",
            {"dosya": surum, "uygulama": SURUM},
        )
    try:
        takvimler = [_takvim_ayristir(h) for h in _kayitlar(dosya, "calendars")]
        ham_etkinlikler = _kayitlar(dosya, "events")
        if len(ham_etkinlikler) > MAKS_ETKINLIK:
            raise _bozuk(f"events: en çok {MAKS_ETKINLIK} etkinlik")
        butce = [0]
        etkinlikler = [_etkinlik_ayristir(h, butce) for h in ham_etkinlikler]
        gorevler = [_gorev_ayristir(h) for h in _kayitlar(dosya, "tasks")]
        silinenler: dict[tuple[str, str], str] = {}
        for h in _kayitlar(dosya, "deleted"):
            tur = h.get("kind")
            if tur not in TURLER:
                raise _bozuk("deleted.kind: calendar | event | task bekleniyor")
            anahtar = (tur, _metin(h, "uid", bos_olamaz=True) or "")
            zaman = _zaman(h.get("deleted_at"), "deleted_at")
            silinenler[anahtar] = max(zaman, silinenler.get(anahtar, ""))
    except SenkronHatasi:
        raise
    except (ValueError, OverflowError) as hata:  # model doğrulaması (tzid, aralık, başlık, yoğun seri...)
        raise _bozuk(str(hata)) from hata
    _tekil([t.uid for t in takvimler], "calendars")
    _tekil([e.event.uid for e in etkinlikler], "events")
    _tekil([g.uid for g in gorevler], "tasks")
    return _Dosya(takvimler, etkinlikler, gorevler, silinenler)


# ---------------------------------------------------------------------------
# Birleştirme (tek transaction içinde)
# ---------------------------------------------------------------------------

def _yeni_mi(yerel: str | None, dosyadaki: str) -> bool:
    """Dosyadaki zaman yerelden KESİN olarak yeni mi (yerelde zaman yoksa evet)."""
    return yerel is None or dosyadaki > yerel


def _mezar(conn: sqlite3.Connection, tur: str, uid: str) -> str | None:
    satir = conn.execute(
        "SELECT deleted_at FROM silinenler WHERE kind = ? AND uid = ?", (tur, uid)
    ).fetchone()
    return satir["deleted_at"] if satir else None


def _silinmis_mi(dosya: _Dosya, conn: sqlite3.Connection, tur: str, uid: str, zaman: str) -> bool:
    """Kayıt (`zaman`) bir mezar taşından KESİN eskiyse True: canlanmamalı.

    Hem dosyanın kendi `deleted` listesine hem yerel mezar taşına bakar.
    Eşitlikte kayıt kalır (veri kaybetmemek için, docs/senkron.md §2).
    """
    for mezar in (dosya.silinenler.get((tur, uid)), _mezar(conn, tur, uid)):
        if mezar is not None and zaman < mezar:
            return True
    return False


def _takvim_birlestir(conn: sqlite3.Connection, dosya: _Dosya, rapor: SenkronRaporu) -> None:
    dosyadaki_uidler = {t.uid for t in dosya.takvimler}
    for t in dosya.takvimler:
        yerel = conn.execute(
            "SELECT id, updated_at FROM calendars WHERE uid = ?", (t.uid,)
        ).fetchone()
        if yerel is None:
            # Ad eşleşmesi: iki cihazda ayrı açılmış varsayılan takvim ikilenmesin.
            # Dosyada kendi uid'iyle karşılığı olan yerel takvim benimsenmez.
            ad = t.name.strip().casefold()
            for aday in conn.execute(
                "SELECT id, name, uid, updated_at FROM calendars ORDER BY id"
            ).fetchall():
                if aday["uid"] not in dosyadaki_uidler and aday["name"].strip().casefold() == ad:
                    conn.execute("UPDATE calendars SET uid = ? WHERE id = ?", (t.uid, aday["id"]))
                    yerel = aday
                    break
        if yerel is None:
            if _silinmis_mi(dosya, conn, "calendar", t.uid, t.updated_at):
                continue
            conn.execute(
                "INSERT INTO calendars (name, color, visible, created_at, uid, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (t.name, t.color, int(t.visible), t.updated_at, t.uid, t.updated_at),
            )
            rapor.added["calendar"] += 1
        elif _yeni_mi(yerel["updated_at"], t.updated_at):
            if _silinmis_mi(dosya, conn, "calendar", t.uid, t.updated_at):
                continue
            conn.execute(
                "UPDATE calendars SET name = ?, color = ?, visible = ? WHERE id = ?",
                (t.name, t.color, int(t.visible), yerel["id"]),
            )
            # UPDATE tetikleyicisi updated_at'i "şimdi" yazdı; dosyadaki değere çek.
            conn.execute(
                "UPDATE calendars SET updated_at = ? WHERE id = ?", (t.updated_at, yerel["id"])
            )
            rapor.updated["calendar"] += 1


def _etkinlik_yaz(conn: sqlite3.Connection, e: _Etkinlik, takvim_id: int, event_id: int | None) -> None:
    """Etkinliği ve çocuklarını (hatırlatıcı + override) yazar; zaman damgasını sabitler."""
    event = replace(e.event, calendar_id=takvim_id)
    if event_id is None:
        event_id = _event_ekle(conn, event, e.updated_at)
    else:
        _event_guncelle(conn, replace(event, id=event_id))
    # Hatırlatıcılar FARKLA güncellenir: sil-yeniden-ekle `reminder_fired`'i de
    # CASCADE ile silerdi ve değişmeyen hatırlatıcı bu hafta ötmüş örnekler için
    # yeniden öterdi (AGENTS 23).
    mevcut = {
        r["minutes_before"]: r["id"]
        for r in conn.execute("SELECT id, minutes_before FROM reminders WHERE event_id = ?", (event_id,))
    }
    for dakika, hat_id in mevcut.items():
        if dakika not in e.reminders:
            conn.execute("DELETE FROM reminders WHERE id = ?", (hat_id,))
    for dakika in e.reminders:
        if dakika not in mevcut:
            conn.execute(
                "INSERT INTO reminders (event_id, minutes_before, created_at) VALUES (?, ?, ?)",
                (event_id, dakika, e.updated_at),
            )
    conn.execute("DELETE FROM event_overrides WHERE event_id = ?", (event_id,))
    for ov in e.overrides:
        conn.execute(
            "INSERT INTO event_overrides (event_id, original_start_utc, cancelled,"
            " new_start_utc, new_end_utc, new_title, new_location) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event_id, _to_db(ov.original_start_utc), int(ov.cancelled),
                _to_db(ov.new_start_utc), _to_db(ov.new_end_utc), ov.new_title, ov.new_location,
            ),
        )
    # Çocuk tetikleyicileri updated_at'i "şimdi" yaptı; dosyadaki değere çek.
    conn.execute(
        "UPDATE events SET created_at = ?, updated_at = ? WHERE id = ?",
        (e.created_at, e.updated_at, event_id),
    )


def _etkinlik_birlestir(conn: sqlite3.Connection, dosya: _Dosya, rapor: SenkronRaporu) -> None:
    for e in dosya.etkinlikler:
        uid = e.event.uid
        yerel = conn.execute("SELECT id, updated_at FROM events WHERE uid = ?", (uid,)).fetchone()
        if yerel is not None and not _yeni_mi(yerel["updated_at"], e.updated_at):
            continue
        if _silinmis_mi(dosya, conn, "event", uid, e.updated_at):
            continue
        takvim = conn.execute("SELECT id FROM calendars WHERE uid = ?", (e.calendar_uid,)).fetchone()
        if takvim is None:
            rapor.skipped["event"] += 1  # yetim: takvimi yerelde yok (silinmiş)
            continue
        _etkinlik_yaz(conn, e, takvim["id"], yerel["id"] if yerel else None)
        (rapor.updated if yerel else rapor.added)["event"] += 1


def _blok_id(conn: sqlite3.Connection, g: _Gorev) -> int | None:
    """Görevin bağlanacağı yerel blok; uygun değilse None (görev plansız kalır)."""
    if g.event_uid is None:
        return None
    blok = conn.execute(
        "SELECT id, rrule, rdate, all_day FROM events WHERE uid = ?", (g.event_uid,)
    ).fetchone()
    if blok is None or blok["rrule"] or blok["rdate"] or blok["all_day"]:
        return None  # yok ya da blok olamayacak etkinlik (AGENTS 68)
    baska = conn.execute(
        "SELECT 1 FROM tasks WHERE event_id = ? AND uid != ?", (blok["id"], g.uid)
    ).fetchone()
    return None if baska else blok["id"]


def _gorev_birlestir(conn: sqlite3.Connection, dosya: _Dosya, rapor: SenkronRaporu) -> None:
    for g in dosya.gorevler:
        yerel = conn.execute("SELECT id, updated_at FROM tasks WHERE uid = ?", (g.uid,)).fetchone()
        if yerel is not None and not _yeni_mi(yerel["updated_at"], g.updated_at):
            continue
        if _silinmis_mi(dosya, conn, "task", g.uid, g.updated_at):
            continue
        alanlar = (
            g.task.title,
            g.task.notes,
            g.task.plan_day.isoformat() if g.task.plan_day else None,
            _blok_id(conn, g),
            _to_db(g.task.done_at),
            g.created_at,
            g.updated_at,
        )
        if yerel is None:
            conn.execute(
                "INSERT INTO tasks (title, notes, plan_day, event_id, done_at, created_at,"
                " updated_at, uid) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (*alanlar, g.uid),
            )
            rapor.added["task"] += 1
        else:
            conn.execute(
                "UPDATE tasks SET title = ?, notes = ?, plan_day = ?, event_id = ?, done_at = ?,"
                " created_at = ?, updated_at = ? WHERE id = ?",
                (*alanlar, yerel["id"]),
            )
            rapor.updated["task"] += 1


def _mezar_yaz(conn: sqlite3.Connection, tur: str, uid: str, zaman: str, *, kesin: bool) -> None:
    """Mezar taşını yazar. `kesin`: silme az önce yapıldı, tetikleyicinin "şimdi"sini
    dosyadaki değerle ez; değilse yalnızca daha YENİ bir silme varsa güncelle."""
    kosul = "" if kesin else " WHERE excluded.deleted_at > silinenler.deleted_at"
    conn.execute(
        "INSERT INTO silinenler (kind, uid, deleted_at) VALUES (?, ?, ?) "
        f"ON CONFLICT(kind, uid) DO UPDATE SET deleted_at = excluded.deleted_at{kosul}",
        (tur, uid, zaman),
    )


_TABLO = {"calendar": "calendars", "event": "events", "task": "tasks"}


def _silmeleri_uygula(conn: sqlite3.Connection, dosya: _Dosya, rapor: SenkronRaporu) -> None:
    # Görev -> etkinlik -> takvim: etkinlikler kendi zamanlarıyla ayrı ayrı
    # silinsin, takvimin CASCADE'i yalnızca dosyada adı geçmeyenlere kalsın.
    sirali = sorted(dosya.silinenler.items(), key=lambda kv: (TURLER.index(kv[0][0]) * -1, kv[0][1]))
    for (tur, uid), zaman in sirali:
        tablo = _TABLO[tur]
        yerel = conn.execute(f"SELECT id, updated_at FROM {tablo} WHERE uid = ?", (uid,)).fetchone()
        if yerel is None:
            _mezar_yaz(conn, tur, uid, zaman, kesin=False)
        elif zaman > (yerel["updated_at"] or ""):
            gidecekler = []
            if tur == "calendar":
                gidecekler = [
                    r["uid"] for r in conn.execute(
                        "SELECT uid FROM events WHERE calendar_id = ?", (yerel["id"],)
                    )
                ]
            conn.execute(f"DELETE FROM {tablo} WHERE id = ?", (yerel["id"],))
            _mezar_yaz(conn, tur, uid, zaman, kesin=True)
            for olu in gidecekler:  # CASCADE'le gidenler de takvimin silinme anını taşısın
                _mezar_yaz(conn, "event", olu, zaman, kesin=True)
            rapor.deleted[tur] += 1
            rapor.deleted["event"] += len(gidecekler)
        else:
            # Kayıt silmeden yeni: kalır, yerel mezar taşı (varsa) kalkar.
            conn.execute("DELETE FROM silinenler WHERE kind = ? AND uid = ?", (tur, uid))


def dogrula(kaynak: str | bytes | dict) -> dict[str, int]:
    """Dosyayı YAZMADAN doğrular; kayıt sayılarını verir (Wi-Fi onay penceresi).

    `ice_aktar`ın doğrulamasının AYNISI (`_ayristir`, aynı `RecursionError` çevirisi):
    onay penceresinin gösterdiği dosya ile sonra birleştirilen dosya aynı kuraldan
    geçmiş olsun. Bozuksa `SenkronHatasi`, hiçbir şeye dokunulmaz.
    """
    try:
        dosya = _ayristir(kaynak)
    except RecursionError:
        raise _bozuk("iç içe yapı çok derin") from None
    return {
        "calendars": len(dosya.takvimler),
        "events": len(dosya.etkinlikler),
        "tasks": len(dosya.gorevler),
        "deleted": len(dosya.silinenler),
    }


def ice_aktar(repo: Repo, kaynak: str | bytes | dict) -> SenkronRaporu:
    """Senkron dosyasını yerel veriyle birleştirir; sayıları döndürür.

    `SenkronHatasi` (bozuk dosya, bilinmeyen büyük sürüm) ya da herhangi bir
    veritabanı hatası fırlatırsa TEK transaction geri alınır: hiçbir şey
    değişmez. Aynı dosya ikinci kez içe aktarılınca tüm sayılar sıfırdır ve veri
    değişmez (kayıtlar yalnızca KESİN olarak yeniyse yazılıyor).
    """
    try:
        dosya = _ayristir(kaynak)
    except RecursionError:  # iç içe yüzlerce katman: json.loads/doğrulama yığını taşırır
        raise _bozuk("iç içe yapı çok derin") from None
    rapor = SenkronRaporu()
    with _tx(repo.conn):
        _takvim_birlestir(repo.conn, dosya, rapor)
        _etkinlik_birlestir(repo.conn, dosya, rapor)
        _gorev_birlestir(repo.conn, dosya, rapor)
        _silmeleri_uygula(repo.conn, dosya, rapor)
    return rapor
