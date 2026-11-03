# Takvim senkron dosyası (`.takvimsync`) — biçim ve birleştirme kuralları

Masaüstü (Python) ve mobil (Flutter) Takvim bu belgedeki tek biçimi konuşur.
Ağ, hesap, sunucu yok: kullanıcı dosyayı kendisi taşır (Paylaş, USB, Drive,
Bluetooth). Her dışa aktarma **tam durumdur** (delta değil); içe aktarma dosyadaki
her kaydı yerelle birleştirir. Aynı dosyayı iki kez içe aktarmak hiçbir şeyi
değiştirmez (idempotent).

## 1. Dosya

UTF-8 JSON, uzantı `.takvimsync`. Anahtarlar İngilizce. Alt çizgili küçük harf.

```json
{
  "format": "takvim-sync",
  "version": 1,
  "created_at": "2026-11-02T10:00:00Z",
  "device": {"id": "<uuid>", "name": "Arda-PC", "app": "desktop 1.8.0"},
  "calendars": [
    {"uid": "…", "name": "Kişisel", "color": "#3b82f6", "visible": true,
     "updated_at": "2026-11-01T08:00:00Z"}
  ],
  "events": [
    {"uid": "…", "calendar_uid": "…", "title": "Toplantı",
     "description": null, "location": null,
     "start_utc": "2026-11-03T07:00:00Z", "end_utc": "2026-11-03T08:00:00Z",
     "tzid": "Europe/Istanbul", "all_day": false,
     "rrule": "FREQ=WEEKLY;BYDAY=MO", "rdate": [], "exdate": [],
     "reminders": [10, 60],
     "overrides": [
       {"original_start_utc": "2026-11-10T07:00:00Z", "cancelled": false,
        "new_start_utc": null, "new_end_utc": null,
        "new_title": null, "new_location": null}
     ],
     "created_at": "…", "updated_at": "…"}
  ],
  "tasks": [
    {"uid": "…", "title": "Rapor", "notes": null,
     "plan_day": "2026-11-03", "event_uid": null,
     "done_at": null, "created_at": "…", "updated_at": "…"}
  ],
  "deleted": [
    {"kind": "event", "uid": "…", "deleted_at": "2026-11-02T09:00:00Z"}
  ]
}
```

- Zamanlar her zaman UTC ve **sabit genişlikli** `YYYY-MM-DDTHH:MM:SSZ`
  (saniye hassasiyeti, mikrosaniye yok). `plan_day` `YYYY-MM-DD`.
- `rdate` / `exdate`: aynı biçimde zaman dizileri (masaüstünde virgüllü metin,
  dosyada dizi).
- `reminders`: dakika cinsinden "ne kadar önce" tamsayıları.
- `deleted[].kind`: `calendar` | `event` | `task`.
- Dosyaya **konmayanlar** (cihaza özel): `reminder_fired`, `silinen_seriler`
  (geri alma), `sequence`, `ics_sequence`, yerel `id`'ler, ayarlar.
- Bilinmeyen alanlar yok sayılır (ileri uyum). `version` bilinenden büyükse
  içe aktarma reddedilir ("uygulamayı güncelle").
- Görev `plan_day` ve `event_uid`'den en çok biri doludur (saat planlı görevin
  zaman bloğu `events` içinde normal bir etkinliktir, `event_uid` ona bakar).

## 2. Birleştirme (içe aktarma)

Anahtar her yerde `uid`'dir (yerel tamsayı id'ler cihazdan cihaza farklıdır).

**Sıra:** takvimler → etkinlikler → görevler → silinenler (en sonda
uygulanır, aşağıya bak).

**Kayıt kuralı (son yazan kazanır):** aynı `uid` için yerel `updated_at` ile
dosyadaki `updated_at` karşılaştırılır; dosyadaki *kesin olarak* yeniyse yerel
kayıt dosyadakiyle değiştirilir, eşit ya da eskiyse yerel kalır. Yerelde yoksa
eklenir. Etkinlik tek birimdir: `overrides` ve `reminders` etkinliğin parçasıdır,
ayrı ayrı birleşmez; etkinlik kazanırsa üçü birlikte değişir.

**Silme kuralı:** yerelde `uid` var, dosyadaki `deleted` listesinde de var ve
`deleted_at` yerel `updated_at`'ten **kesin olarak** yeniyse yerel kayıt silinir.
Tersi (kayıt güncellemesi silmeden yeni) ise kayıt kalır, silme yok sayılır ve
yerel silme kaydı (varsa) kaldırılır. Yerelde silme kaydı olan ama dosyada canlı
gelen kayıt için aynı karşılaştırma yapılır (kayıt `updated_at` >= `deleted_at` ise
canlanır; yani eşitlikte kayıt yaşar). Eşitlikte **kayıt kalır** (veri kaybetmemek için).

**Silinen kayıtlar (mezar taşları):** her cihaz `deleted_at` ile sildiklerini
kalıcı tutar (budama yok; satırlar çok küçük). İçe aktarma, uzaktan gelen silmeyi
uygularken yerel mezar taşına **dosyadaki `deleted_at`'i aynen yazar** (şimdi
değil), yoksa silme cihazlar arasında sonsuz yankılanır. Aynı şekilde içe
aktarılan kaydın yerel `updated_at`'i **dosyadaki değer** olarak saklanır
(şimdi değil).

**Takvim eşleşmesi:** önce `uid` ile. Bulunamazsa ve yerelde aynı `name` (büyük/
küçük harf duyarsız, kenar boşlukları kırpılmış) varsa o takvim **uid'ini
dosyadakine çevirerek benimsenir** (iki cihazda ayrı oluşturulan varsayılan
"Kişisel" takvimi böylece ikilenmez); ad/renk/görünürlük normal kayıt
kuralına tabidir. Takvim silinince içindeki etkinlikler de gider (masaüstünde
CASCADE; mobil aynısını yapar ve her biri için mezar taşı yazar).

**Yetim etkinlik:** `calendar_uid` içe aktarma sonunda yerelde yoksa (takvim
silinmiş) etkinlik eklenmez; sayaçta "atlandı" olarak raporlanır.

**Görev ↔ blok:** görevler etkinliklerden sonra uygulanır. `event_uid` yerelde
bulunamazsa görev plansıza döner (`plan_day` ve `event_uid` ikisi de null).
Zaman bloğu etkinliği silinirse görev yerelde de plansıza döner (mevcut
kural).

**Doğrulama (iki taraf da uygular, tek kayıt bozuksa dosya reddedilir):** yinelenen uid, `#rrggbb` olmayan renk, gece yarısı olmayan tüm gün etkinlik, çözülemeyen RRULE, on yıldan büyük hatırlatıcı, aynı örneğe birden çok override, tekrarlı/tüm gün etkinliğe bağlı görev (görev plansıza döner). Takvim adı kenar boşluklarından kırpılır; `rdate`/`exdate` tekilleştirilir.

**Zaman farkı:** iki cihazın saati birbirinden farklıysa "son yazan" yanılabilir;
bu sınır kabul edilmiştir (v1'de çözülmez). Kullanıcıya belgede söylenir.

**Sonuç raporu:** içe aktarma `{added, updated, deleted, skipped}` ve türe göre
(takvim/etkinlik/görev) sayıları döner; arayüz bunu özet olarak gösterir.
Hata olursa **hiçbir şey değişmez** (tek transaction / tek atomik yazma).

## 3. Masaüstü gereksinimleri (migration 006)

Şema bu biçimi taşımak için eksik: takvimde `uid` ve `updated_at` yok, silmeler
iz bırakmıyor. Migration `006_senkron.sql` (ELLE değiştirilmez kuralı: yeni
dosya; `schema.sql` aynalanır, test zorlar):

- `calendars.uid` (mevcut satırlara `lower(hex(randomblob(16)))`, ardından
  UNIQUE index) ve `calendars.updated_at`.
- `silinenler(kind, uid, deleted_at, PRIMARY KEY(kind, uid))`.
- Tetikleyiciler (Repo kodu değişmeden tüm silme yollarını yakalar):
  `AFTER DELETE` → `calendars/events/tasks` için `INSERT OR REPLACE INTO
  silinenler`; `AFTER INSERT` → aynı uid'in mezar taşını siler (geri alma ve
  yeniden ekleme); `event_overrides` ve `reminders` ekleme/güncelleme/silme →
  ana etkinliğin `updated_at`'ini şimdiye çeker; `UPDATE calendars` →
  `updated_at` şimdi.
- `Repo.add_calendar` uid üretir; `Calendar` modeline `uid` eklenir.
- `restore_last_deleted` (geri al) geri yüklenen etkinliğin `updated_at`'ini
  şimdiye çekmeli (yoksa diğer cihazdaki silme kazanır).
