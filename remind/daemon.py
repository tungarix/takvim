"""Hatırlatıcı arka plan süreci.

Uygulama kapalıyken de çalışması istendiği için ayrı bir süreç: `python -m remind`.
Takvim arayüzüyle aynı veritabanını okur, kendi bağlantısını açar.

Karar verme işi `core/reminders.py`'de, bildirim gösterme işi
`remind/notifier.py`'de. Burada yalnızca ikisini birleştiren döngü var --
ve döngünün tek zor kararı: bildirimi göstermeden ÖNCE tetiklendi olarak
işaretlemek.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta

from core import UTC, due_reminders, next_fire_time, to_local

from .notifier import Notifier

__all__ = ["run_once", "run_forever", "bildirim_metni"]

# Vadesi gelmemiş hatırlatıcıları da görebilmek için pencereyi ileri taşıyoruz.
# En uzun hatırlatıcı kadar + bir gün pay: tüm gün etkinliklerinin başlangıcı
# yerel gece yarısı olduğu için "1 gün önce" hatırlatıcısı geriye taşar.
_PAY = timedelta(days=1)

# `reminder_fired` tablosu için budama: kayıtlar 30 günden eskiyse (ve örnek
# de bitmişse, bkz. `Repo.prune_fired`) silinir. Her turda değil günde bir:
# tablo yavaş büyüyor, budamanın dakikada bir koşmasına gerek yok.
_KAYIT_OMRU = timedelta(days=30)
_TEMIZLIK_ARALIGI = 24 * 3600  # saniye, `time.monotonic` ile ölçülür

# Dil ya sabit bir metin ("tr"/"en") ya da her turda sorulan, argümansız bir
# çağrılabilir: uygulama açıkken kullanıcı Ayarlar'dan dili değiştirince
# bildirim dili de hemen uysun diye (bkz. `_dil_coz`).
DilKaynagi = str | Callable[[], str]


def _dil_coz(dil: DilKaynagi) -> str:
    """Dil kaynağını `"tr"` ya da `"en"`e çözer; hata ve geçersiz değerde `"tr"`.

    Çağrılabilir `ayarlar.json` okuyabilir ve o dosya elle bozulmuş, kilitli ya
    da yazılırken yarım olabilir. Dil okunamadı diye hatırlatıcı turunun
    patlaması kabul edilemez: bildirim hiç gelmemektense Türkçe (varsayılan dil)
    gelmesi yeğdir.
    """
    try:
        sonuc = dil() if callable(dil) else dil
    except Exception:
        return "tr"
    return sonuc if sonuc in ("tr", "en") else "tr"


def bildirim_metni(due, tzid: str, *, dil: str = "tr") -> tuple[str, str]:
    """Bir hatırlatıcıyı (başlık, gövde) metnine çevirir.

    `dil` arayüz ayarından geliyor (`ayarlar.json` → `remind/__main__.py`);
    bildirim toast'ı da arayüzün diliyle konuşmalı. Tarih/saat biçimi dile
    göre: TR `GG.AA.YYYY`, EN (GB sırası) `GG/AA/YYYY`; saatler iki dilde de
    24 saat (`%H:%M`).
    """
    ingilizce = dil == "en"
    occ = due.occurrence
    if occ.all_day:
        tarih = to_local(occ.start_utc, occ.tzid).strftime(
            "%d/%m/%Y" if ingilizce else "%d.%m.%Y"
        )
        ne_zaman = f"{'All day' if ingilizce else 'Tüm gün'} · {tarih}"
    else:
        bas = to_local(occ.start_utc, occ.tzid).strftime("%H:%M")
        bit = to_local(occ.end_utc, occ.tzid).strftime("%H:%M")
        ne_zaman = f"{bas} – {bit}"

    dk = due.minutes_before
    if ingilizce:
        if dk == 0:
            ne_kadar = "starting now"
        elif dk < 60:
            ne_kadar = f"in {dk} minute" if dk == 1 else f"in {dk} minutes"
        elif dk % 60 == 0:
            saat = dk // 60
            ne_kadar = f"in {saat} hour" if saat == 1 else f"in {saat} hours"
        else:
            ne_kadar = f"in {dk // 60} h {dk % 60} min"
    elif dk == 0:
        ne_kadar = "şimdi başlıyor"
    elif dk < 60:
        ne_kadar = f"{dk} dakika içinde"
    elif dk % 60 == 0:
        ne_kadar = f"{dk // 60} saat içinde"
    else:
        ne_kadar = f"{dk // 60} sa {dk % 60} dk içinde"

    govde = f"{ne_zaman} · {ne_kadar}"
    if occ.location:
        govde += f"\n{occ.location}"
    return occ.title, govde


def run_once(
    repo,
    tzid: str,
    notifier: Notifier,
    *,
    now: datetime | None = None,
    include_hidden: bool = False,
    dil: DilKaynagi = "tr",
) -> list:
    """Bir tur: vadesi geleni bul, işaretle, bildir. Gönderilenleri döndürür.

    `include_hidden=False`: gizlenen takvimin hatırlatıcıları da susar. Bir
    takvimi gizlemek "bunu şu an görmek istemiyorum" demektir; gürültüsünü
    sürdürmek bu niyetle çelişirdi.

    `dil` metin ya da argümansız çağrılabilir. Çağrılabilir her turda yeniden
    çözülüyor (yalnızca gösterilecek bir şey varsa: ayar dosyasını boşuna her
    dakika okumayalım), böylece dil değişikliği hemen bildirime yansır.

    İşaretleme bildirimden ÖNCE yapılıyor. Ters sırada olsaydı bildirim
    gösterilip süreç çökerse aynı hatırlatıcı bir dahaki turda yeniden
    gösterilirdi; kullanıcıyı döngüye sokmaktansa nadiren bir bildirimi
    kaçırmak yeğdir. `mark_fired` UNIQUE kısıtına dayandığı için iki süreç
    aynı anda çalışsa bile yalnızca biri True alır.
    """
    now = (now or datetime.now(UTC)).astimezone(UTC)
    reminders = repo.all_reminders(exclude_done_tasks=True)
    if not reminders:
        return []

    en_uzun = max(
        (r.minutes_before for liste in reminders.values() for r in liste), default=0
    )
    pencere_bas = now - _PAY
    pencere_bit = now + timedelta(minutes=en_uzun) + _PAY

    occurrences = repo.occurrences(
        pencere_bas, pencere_bit, include_hidden=include_hidden
    )
    vadesi_gelen = due_reminders(
        occurrences, reminders, now, already_fired=repo.fired_keys()
    )

    gonderilen = []
    if not vadesi_gelen:
        return gonderilen

    dil_kodu = _dil_coz(dil)
    # Bildirim arka ucunun kendi yazıları da olabilir (Tk düğmesi). `notify`
    # imzasına dil eklemek her arka ucu ve her sahte arka ucu kırardı; bu
    # yüzden isteğe bağlı bir `dil_ayarla` yöntemi: olan çağrılır, olmayan atlanır.
    dil_ayarla = getattr(notifier, "dil_ayarla", None)
    if callable(dil_ayarla):
        dil_ayarla(dil_kodu)

    for due in vadesi_gelen:
        if not repo.mark_fired(due.reminder_id, due.occurrence.start_utc):
            continue  # başka bir süreç önce davrandı
        baslik, govde = bildirim_metni(due, tzid, dil=dil_kodu)
        notifier.notify(baslik, govde)
        gonderilen.append(due)

    return gonderilen


def _temizlik(repo, simdi: datetime) -> int:
    """Eski tetiklenme kayıtlarını budar; silinen sayıyı döndürür, hatada 0.

    Budama bir bakım işi: başarısız olması (başka süreç kilidi tutuyor, disk
    dolu...) hatırlatıcı döngüsünü öldürmemeli. Bildirim görevi bakımdan önce
    gelir; kayıtlar bir sonraki denemede yine budanır.
    """
    try:
        return repo.prune_fired(simdi - _KAYIT_OMRU)
    except Exception as hata:  # döngü tek bir hatayla ölmesin
        print(f"  tetiklenme kayıtları budanamadı: {hata}")
        return 0


def _temizlik_vakti_mi(son: float | None, simdi: float) -> bool:
    """Budama zamanı geldi mi: hiç yapılmadıysa ya da aralık dolduysa.

    `son`/`simdi` `time.monotonic` değerleri: duvar saati değişse (saat dilimi,
    elle ayar, uyku) aralık bozulmasın.
    """
    return son is None or simdi - son >= _TEMIZLIK_ARALIGI


def run_forever(
    repo,
    tzid: str,
    notifier: Notifier,
    *,
    poll_seconds: int = 60,
    verbose: bool = False,
    dil: DilKaynagi = "tr",
) -> None:
    """Ctrl+C'ye kadar döner.

    Uyku süresi bir sonraki tetiklenme anına göre kısalıyor ama `poll_seconds`
    üst sınırını aşmıyor: veritabanı başka bir süreç (arayüz) tarafından
    değiştirilebildiği için sonsuza kadar uyumak yeni eklenen bir hatırlatıcıyı
    kaçırmak olurdu.

    `dil` metin ya da argümansız çağrılabilir (bkz. `run_once`): uzun yaşayan
    süreçte dil başlangıçta bir kez okunsaydı, kullanıcı uygulama açıkken
    Ayarlar'dan dili değiştirince bildirimler eski dilde kalırdı.

    Tetiklenme kayıtları döngü başlarken bir kez, sonra en fazla günde bir
    budanır (`_temizlik`).
    """
    print(f"Hatırlatıcı çalışıyor ({type(notifier).__name__}). Durdurmak için Ctrl+C.")
    son_temizlik: float | None = None
    try:
        while True:
            simdi = datetime.now(UTC)
            if _temizlik_vakti_mi(son_temizlik, time.monotonic()):
                _temizlik(repo, simdi)
                # Başarısız olsa da zaman damgası ilerliyor: kilitli bir veritabanında
                # her dakika aynı hatayı yazıp günlüğü doldurmayalım.
                son_temizlik = time.monotonic()
            try:
                gonderilen = run_once(repo, tzid, notifier, now=simdi, dil=dil)
                if verbose and gonderilen:
                    for due in gonderilen:
                        print(f"  bildirildi: {due.occurrence.title}")
            except Exception as hata:  # döngü tek bir hatayla ölmesin
                print(f"  hatırlatıcı turu başarısız: {hata}")

            uyku = poll_seconds
            try:
                sonraki = next_fire_time(
                    repo.occurrences(
                        simdi, simdi + timedelta(days=2), include_hidden=False
                    ),
                    repo.all_reminders(exclude_done_tasks=True),
                    simdi,
                )
                if sonraki is not None:
                    kalan = (sonraki - datetime.now(UTC)).total_seconds()
                    uyku = max(1, min(poll_seconds, int(kalan) + 1))
            except Exception:
                pass  # uyku hesabı başarısızsa varsayılan aralıkla devam

            time.sleep(uyku)
    except KeyboardInterrupt:
        print("\nhatırlatıcı durduruldu.")
