/* Takvim ön yüzü.
 *
 * İş bölümü: çakışma yerleşimi core/layout.py'de, gün sınırları ve kırpma
 * ui/presenter.py'de, zaman ayrıştırma core/quickadd.py'de. Burada yalnızca
 * gelen sayıları piksele çeviriyoruz.
 *
 * dayMinutes her gün için ayrı geliyor: DST gününde 1380 veya 1500 olur ve
 * yüzdeleri ona bölmek ızgarayı o günlerde de doğru hizalıyor.
 */

const SAAT_YUKSEKLIK = 48; // CSS'teki --saat-yukseklik ile aynı olmalı
const AY_MAKS_BLOK = 3;    // ay hücresinde gösterilecek en fazla etkinlik

const durum = {
  gorunum: "week",
  anchor: bugunISO(),
  veri: null,
  secili: null,          // seçili occurrence (panel için)
  takvimGorunur: new Map(),
  kaydirildi: false,
};

const el = (id) => document.getElementById(id);

/* ---------- tarih yardımcıları ---------- */

function bugunISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function tarihKaydir(iso, gun) {
  const [y, m, d] = iso.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d));
  t.setUTCDate(t.getUTCDate() + gun);
  return t.toISOString().slice(0, 10);
}

function ayKaydir(iso, ay) {
  const [y, m] = iso.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1 + ay, 1));
  return t.toISOString().slice(0, 10);
}

function saatBicim(iso, tzid) {
  return new Intl.DateTimeFormat("tr-TR", {
    hour: "2-digit", minute: "2-digit", hour12: false, timeZone: tzid,
  }).format(new Date(iso));
}

function tarihBicim(iso, tzid) {
  return new Intl.DateTimeFormat("tr-TR", {
    weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: tzid,
  }).format(new Date(iso));
}

function zemin(hex) {
  const n = parseInt(hex.replace("#", ""), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},0.22)`;
}

function kacir(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : s;
  return d.innerHTML;
}

function occAnahtar(occ) {
  return `${occ.uid}|${occ.startUtc}`;
}

/* ---------- ağ ---------- */

async function istek(yol, secenekler = {}) {
  const yanit = await fetch(yol, secenekler);
  const tur = yanit.headers.get("Content-Type") || "";
  const govde = tur.includes("json") ? await yanit.json() : await yanit.text();
  if (!yanit.ok) {
    throw new Error((govde && govde.error) || `sunucu ${yanit.status}`);
  }
  return govde;
}

/* ---------- uygulama içi soru/onay penceresi ---------- */

/* Tarayıcının `prompt()` ve `confirm()` kutuları yerine. Uygulama kendi
 * masaüstü penceresinde çalışıyor ve orada tarayıcı kutusu "Bu sayfayı şunu
 * diyor:" başlığıyla çıkıyor -- "bu bir uygulama" hissini bozan tek şey buydu.
 * Kendi kutumuz ayrıca hangi kabukta çalıştığımızdan bağımsız: WebView2,
 * tarayıcı geri düşüşü, hepsinde aynı davranıyor.
 *
 * Söz (Promise) döndürüyor; çağrı yerleri zaten `async`.
 */
let modalDurum = null;

function modalAcik() {
  return modalDurum !== null;
}

/* Tek çekirdek, üç kullanım: onay kutusu, tek satırlık soru ve çok alanlı
 * form. Açma/kapama, Esc/Enter, perdeye tıklama ve odağı geri verme TEK
 * yerde -- üç ayrı kopya olsaydı biri düzeltilip diğerleri unutulurdu. */
function modalAc({ baslik, metin = "", onay = "Tamam", tehlike = false, kur, oku, iptalDegeri }) {
  const perde = el("perde");
  const govde = el("modal-alanlar");
  const tamam = el("modal-tamam");
  const iptal = el("modal-iptal");
  const oncekiOdak = document.activeElement;

  el("modal-baslik").textContent = baslik;
  el("modal-metin").textContent = metin;
  govde.innerHTML = "";
  govde.hidden = true;
  tamam.textContent = onay;
  tamam.classList.toggle("tehlike", tehlike);
  tamam.classList.toggle("birincil", !tehlike);
  perde.hidden = false;

  const ilkOdak = kur ? kur(govde) : null;
  govde.hidden = govde.children.length === 0;
  (ilkOdak || tamam).focus();
  if (ilkOdak && ilkOdak.select) ilkOdak.select();

  return new Promise((cozumle) => {
    const bitir = (deger) => {
      perde.hidden = true;
      perde.removeEventListener("click", perdeTik);
      document.removeEventListener("keydown", tus, true);
      tamam.onclick = null;
      iptal.onclick = null;
      modalDurum = null;
      // Odağı geri ver: kutu kapanınca klavye kısayolları yine çalışsın.
      if (oncekiOdak && oncekiOdak.focus) oncekiOdak.focus();
      cozumle(deger);
    };
    const perdeTik = (e) => { if (e.target === perde) bitir(iptalDegeri); };
    /* YAKALAMA aşamasında dinliyoruz: aşağıdaki genel kısayol dinleyicisi
     * (g/h/a/t) modal açıkken arkadaki görünümü değiştirmesin. */
    const tus = (e) => {
      if (e.key === "Escape") {
        e.preventDefault(); e.stopPropagation(); bitir(iptalDegeri);
      } else if (e.key === "Enter" && !e.isComposing) {
        // Çok satırlı alanda Enter yeni satır demek; formu göndermemeli.
        if (e.target && e.target.tagName === "TEXTAREA") return;
        e.preventDefault(); e.stopPropagation(); bitir(oku());
      }
    };

    modalDurum = { kapat: () => bitir(iptalDegeri) };
    perde.addEventListener("click", perdeTik);
    document.addEventListener("keydown", tus, true);
    tamam.onclick = () => bitir(oku());
    iptal.onclick = () => bitir(iptalDegeri);
  });
}

/** Metin sorar; iptal edilirse null döner (prompt() ile aynı sözleşme). */
function sor(baslik, metin, varsayilan = "") {
  let girdi;
  return modalAc({
    baslik,
    metin,
    iptalDegeri: null,
    kur: (govde) => {
      girdi = document.createElement("input");
      girdi.type = "text";
      girdi.className = "modal-girdi";
      girdi.id = "modal-girdi";
      girdi.autocomplete = "off";
      girdi.value = varsayilan;
      govde.appendChild(girdi);
      return girdi;
    },
    oku: () => girdi.value,
  });
}

/** Evet/hayır sorar; confirm() ile aynı sözleşme. */
function onayla(baslik, metin, onay = "Tamam", tehlike = false) {
  return modalAc({ baslik, metin, onay, tehlike, iptalDegeri: false, oku: () => true });
}

/* Çok alanlı form kutusu.
 *
 * `alanlar`: [{ad, etiket, tur, deger, secenekler}] -- tur: metin | uzunmetin |
 * tarih | saat | secim. İptalde null, onayda {ad: değer} döner.
 *
 * Tarih ve saat için tarayıcının KENDİ girdilerini (`type=date/time`)
 * kullanıyoruz: yerel biçimi, klavye yazımını ve takvim açılır kutusunu
 * işletim sistemi hallediyor; kendi tarih seçicimizi yazmak bu uygulamanın
 * kazanacağı bir savaş değil.
 */
function modalForm(baslik, metin, alanlar, onay = "Kaydet") {
  const girdiler = {};
  return modalAc({
    baslik,
    metin,
    onay,
    iptalDegeri: null,
    kur: (govde) => {
      let ilk = null;
      alanlar.forEach((a) => {
        const satir = document.createElement("label");
        satir.className = "modal-alan" + (a.dar ? " dar" : "");
        const etiket = document.createElement("span");
        etiket.className = "modal-etiket";
        etiket.textContent = a.etiket;
        satir.appendChild(etiket);

        let g;
        if (a.tur === "uzunmetin") {
          g = document.createElement("textarea");
          g.rows = 2;
        } else if (a.tur === "secim") {
          g = document.createElement("select");
          (a.secenekler || []).forEach((s) => {
            const o = document.createElement("option");
            o.value = s.deger;
            o.textContent = s.etiket;
            g.appendChild(o);
          });
        } else {
          g = document.createElement("input");
          g.type =
            a.tur === "tarih" ? "date"
            : a.tur === "saat" ? "time"
            : a.tur === "renk" ? "color"
            : "text";
          g.autocomplete = "off";
        }
        g.className = "modal-girdi";
        g.value = a.deger == null ? "" : a.deger;
        if (a.devredisi) g.disabled = true;
        satir.appendChild(g);
        govde.appendChild(satir);
        girdiler[a.ad] = g;
        if (!ilk && !a.devredisi) ilk = g;
      });
      return ilk;
    },
    oku: () => {
      const sonuc = {};
      Object.entries(girdiler).forEach(([ad, g]) => { sonuc[ad] = g.value; });
      return sonuc;
    },
  });
}

let bildirimZaman = null;

/* Bildirim kutusu bir EYLEM taşıyabiliyor: silmenin yanına "Geri al".
 * Onay kutusu tek başına yetmiyor -- onay kutuları refleksle onaylanır ve
 * silme geri alınamaz bir işlem. Pencere 10 saniye açık kalıyor. */
function bildir(mesaj, hata = false, geriAl = null) {
  const kutu = el("bildirim");
  kutu.textContent = "";
  kutu.classList.toggle("hata", hata);

  const metin = document.createElement("span");
  metin.textContent = mesaj;
  kutu.appendChild(metin);

  if (geriAl) {
    const dugme = document.createElement("button");
    dugme.type = "button";
    dugme.className = "bildirim-dugme";
    dugme.textContent = "Geri al";
    dugme.onclick = () => { kutu.hidden = true; geriAl(); };
    kutu.appendChild(dugme);
  }

  kutu.hidden = false;
  clearTimeout(bildirimZaman);
  bildirimZaman = setTimeout(() => { kutu.hidden = true; }, hata ? 7000 : geriAl ? 10000 : 3500);
}

async function yukle() {
  try {
    durum.veri = await istek(`/api/${durum.gorunum}?date=${durum.anchor}`);
    durum.veri.calendars.forEach((c) => {
      if (!durum.takvimGorunur.has(c.id)) durum.takvimGorunur.set(c.id, c.visible);
    });
    ciz();
  } catch (hata) {
    bildir(`Veri alınamadı: ${hata.message}`, true);
  }
}

/* ---------- çizim ---------- */

function gorunurMu(occ) {
  return durum.takvimGorunur.get(occ.calendarId) !== false;
}

function ciz() {
  const veri = durum.veri;
  if (!veri) return;

  el("baslik").textContent = veri.label;
  el("tz-etiketi").textContent = veri.tzid;
  takvimleriCiz();

  document.querySelectorAll(".gorunum-dugme").forEach((b) => {
    b.classList.toggle("secili", b.dataset.gorunum === durum.gorunum);
  });

  const ayMi = durum.gorunum === "month";
  el("zaman-gorunum").hidden = ayMi;
  el("ay-gorunum").hidden = !ayMi;

  if (ayMi) ayCiz(veri);
  else zamanCiz(veri);
}

function takvimleriCiz() {
  const liste = el("takvim-listesi");
  liste.innerHTML = "";
  durum.veri.calendars.forEach((c) => {
    const gorunur = durum.takvimGorunur.get(c.id);
    const li = document.createElement("li");
    li.className = "takvim-satir" + (gorunur ? "" : " gizli");
    li.innerHTML =
      `<span class="renk-kutu"></span><span class="takvim-ad"></span>` +
      `<button type="button" class="takvim-dugme" data-is="duzenle" title="Düzenle">✎</button>` +
      `<button type="button" class="takvim-dugme" data-is="sil" title="Sil">×</button>`;
    li.querySelector(".renk-kutu").style.background = c.color;
    li.querySelector(".takvim-ad").textContent = c.name;
    li.title = gorunur ? "Gizle" : "Göster";
    li.onclick = () => gorunurlukDegistir(c.id, !gorunur);
    // Satırın kendisi görünürlüğü değiştiriyor; düğmeler onu TETİKLEMEMELİ.
    li.querySelector('[data-is="duzenle"]').onclick = (e) => {
      e.stopPropagation();
      takvimDuzenle(c);
    };
    li.querySelector('[data-is="sil"]').onclick = (e) => {
      e.stopPropagation();
      takvimSil(c);
    };
    liste.appendChild(li);
  });
}

/* ---------- takvim yönetimi ---------- */

/* Bu üçü uzun süre yoktu: kullanıcı ilk açılışta oluşan tek "Kişisel"
 * takvimine mahkûmdu. Renk ve gizle/göster özellikleri de o yüzden pratikte
 * ölüydü -- gizlenecek ikinci bir takvim olmuyordu. */

async function takvimEkle() {
  const s = await modalForm(
    "Yeni takvim",
    "",
    [
      { ad: "ad", etiket: "Ad", tur: "metin", deger: "" },
      { ad: "renk", etiket: "Renk", tur: "renk", deger: "#3b82f6" },
    ],
    "Oluştur",
  );
  if (s === null || !s.ad.trim()) return;
  await eylem(
    () => istek("/api/calendars", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: s.ad.trim(), color: s.renk }),
    }),
    `Takvim eklendi: ${s.ad.trim()}`,
  );
}

async function takvimDuzenle(c) {
  const s = await modalForm(
    "Takvimi düzenle",
    "",
    [
      { ad: "ad", etiket: "Ad", tur: "metin", deger: c.name },
      { ad: "renk", etiket: "Renk", tur: "renk", deger: c.color },
    ],
  );
  if (s === null || !s.ad.trim()) return;
  if (s.ad.trim() === c.name && s.renk === c.color) return;
  await eylem(
    () => istek(`/api/calendars/${c.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: s.ad.trim(), color: s.renk }),
    }),
    "Takvim güncellendi",
  );
}

async function takvimSil(c) {
  const tamam = await onayla(
    "Takvimi sil",
    `"${c.name}" ve İÇİNDEKİ TÜM ETKİNLİKLER silinecek. Bu geri alınamaz.`,
    "Takvimi sil",
    true,
  );
  if (!tamam) return;
  await eylem(
    () => istek(`/api/calendars/${c.id}`, { method: "DELETE" }),
    `Takvim silindi: ${c.name}`,
  );
}

async function gorunurlukDegistir(id, gorunur) {
  durum.takvimGorunur.set(id, gorunur);
  ciz();
  try {
    await istek(`/api/calendars/${id}/visible`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visible: gorunur }),
    });
  } catch {
    /* Görünürlük bir tercih; yazılamazsa ekran yine doğru. */
  }
}

/* ---------- zaman ızgarası (gün / hafta) ---------- */

function zamanCiz(veri) {
  const bugun = bugunISO();
  const tekGun = veri.days.length === 1;

  const baslikKap = el("izgara-baslik");
  const seritKap = el("tumgun-serit");
  const gunlerKap = el("gunler");
  [baslikKap, seritKap].forEach((e) => e.classList.toggle("tek-gun", tekGun));
  gunlerKap.classList.toggle("tek-gun", tekGun);

  baslikKap.innerHTML = `<div></div>`;
  veri.days.forEach((g) => {
    const d = document.createElement("div");
    d.className = "gun-basligi" + (g.date === bugun ? " bugun" : "");
    d.innerHTML = `<div class="ad">${g.dayName}</div><div class="sayi">${g.dayNumber}</div>`;
    baslikKap.appendChild(d);
  });

  seritKap.innerHTML = `<div class="tumgun-etiket">tüm gün</div>`;
  veri.days.forEach((g) => {
    const hucre = document.createElement("div");
    hucre.className = "tumgun-hucre";
    g.allDay.filter(gorunurMu).forEach((occ) => {
      const blok = document.createElement("div");
      blok.className = "tumgun-blok";
      blok.textContent = occ.title;
      blok.style.background = zemin(occ.color);
      blok.style.borderLeftColor = occ.color;
      blok.onclick = () => { if (!tumgunSurukleme.tasindi) panelAc(occ); };
      blok.addEventListener("pointerdown", (e) => tumgunBasla(e, blok, occ));
      hucre.appendChild(blok);
    });
    seritKap.appendChild(hucre);
  });

  const saatKap = el("saat-sutunu");
  saatKap.innerHTML = "";
  for (let s = 0; s < 24; s++) {
    const e = document.createElement("div");
    e.className = "saat-etiket";
    e.textContent = s === 0 ? "" : `${String(s).padStart(2, "0")}:00`;
    saatKap.appendChild(e);
  }

  gunlerKap.innerHTML = "";
  gunlerKap.style.height = `${24 * SAAT_YUKSEKLIK}px`;

  veri.days.forEach((g) => {
    const sutun = document.createElement("div");
    sutun.className = "gun-sutun" + (g.date === bugun ? " bugun" : "");

    for (let s = 1; s < 24; s++) {
      const c = document.createElement("div");
      c.className = "saat-cizgi";
      c.style.top = `${(s / 24) * 100}%`;
      sutun.appendChild(c);
    }

    // Boş bir saate tıklamak etkinlik oluşturur. Hangi haftaya bakıyorsan
    // etkinlik ORAYA düşer; hızlı ekleme kutusu ise her zaman bugünü referans
    // alıyor ve "sonraki haftaya nasıl eklerim" sorusu buradan çıkmıştı.
    sutun.addEventListener("click", (e) => izgaraTik(e, sutun, g));

    g.timed.filter(gorunurMu).forEach((occ) => sutun.appendChild(blokYap(occ, g)));

    if (g.date === bugun) {
      const simdi = new Date();
      const gecen = simdi.getHours() * 60 + simdi.getMinutes();
      if (gecen <= g.dayMinutes) {
        const c = document.createElement("div");
        c.className = "simdi-cizgi";
        c.style.top = `${(gecen / g.dayMinutes) * 100}%`;
        sutun.appendChild(c);
      }
    }

    gunlerKap.appendChild(sutun);
  });

  if (!durum.kaydirildi) {
    durum.kaydirildi = true;
    el("izgara-kaydirma").scrollTop = (7 / 24) * 24 * SAAT_YUKSEKLIK;
  }
}

function blokYap(occ, gun) {
  const genPct = 100 / occ.colCount;
  const blok = document.createElement("div");
  blok.className = "blok";
  if (occ.endMin - occ.startMin <= 35) blok.classList.add("kisa");
  if (durum.secili && occAnahtar(occ) === occAnahtar(durum.secili)) blok.classList.add("secili");

  blok.style.top = `${(occ.startMin / gun.dayMinutes) * 100}%`;
  blok.style.height = `${Math.max(((occ.endMin - occ.startMin) / gun.dayMinutes) * 100, 1.1)}%`;
  blok.style.left = `calc(${occ.col * genPct}% + 2px)`;
  blok.style.width = `calc(${genPct}% - 4px)`;
  blok.style.background = zemin(occ.color);
  blok.style.borderLeftColor = occ.color;

  blok.innerHTML =
    `<div class="b-baslik">${kacir(occ.title)}</div>` +
    `<div class="b-saat">${saatBicim(occ.startUtc, occ.tzid)}–${saatBicim(occ.endUtc, occ.tzid)}` +
    `${occ.clipped ? " ⇥" : ""}</div>` +
    (occ.isOverride ? `<div class="b-rozet">· taşındı</div>` : "");

  blok.onclick = () => { if (!surukleme.tasindi) panelAc(occ); };
  blok.addEventListener("pointerdown", (e) => surukleBasla(e, blok, occ, gun, "tasi"));

  // Alt kenarda boyutlandırma tutamağı: süreyi değiştirir, yeri değil.
  const tutamak = document.createElement("div");
  tutamak.className = "boyut-tutamagi";
  tutamak.addEventListener("pointerdown", (e) => {
    e.stopPropagation();
    surukleBasla(e, blok, occ, gun, "boyutlandir");
  });
  blok.appendChild(tutamak);

  return blok;
}

/* ---------- boş saate tıklayarak oluşturma ---------- */

// Oluştururken yarım saate yuvarlıyoruz. Sürüklemedeki 15 dakikadan kaba,
// çünkü burada niyet "şu civarda bir şey" -- saati sonradan sürükleyerek
// ince ayarlamak zaten mümkün.
const OLUSTUR_SNAP = 30;
const OLUSTUR_SURE = 60; // dakika

async function izgaraTik(e, sutun, gun) {
  // Etkinliğin üstüne tıklandıysa burası karışmasın: panel açılacak.
  if (e.target.closest(".blok")) return;
  // Sürüklemeden SONRA da bir tık olayı geliyor; onu oluşturma sanmayalım.
  if (surukleme.tasindi || tumgunSurukleme.tasindi) return;

  const kutu = sutun.getBoundingClientRect();
  const oran = (e.clientY - kutu.top) / kutu.height;
  let dakika = Math.floor((oran * gun.dayMinutes) / OLUSTUR_SNAP) * OLUSTUR_SNAP;
  dakika = Math.max(0, Math.min(dakika, gun.dayMinutes - OLUSTUR_SNAP));
  const bitis = Math.min(dakika + OLUSTUR_SURE, gun.dayMinutes);

  const s = await modalForm(
    "Yeni etkinlik",
    `${gun.dayNumber} ${gun.monthName} ${gun.dayName} · ${dakikaSaat(dakika)}–${dakikaSaat(bitis)}`,
    [
      { ad: "baslik", etiket: "Başlık", tur: "metin", deger: "" },
      /* Tekrar KAPALI bir liste: tekrar motoru baştan beri vardı ama
       * kullanıcının onu söyleyebileceği hiçbir yer yoktu; RFC 5545 kuralı
       * yazdırmak da bu uygulamanın işi değil. */
      /* Hangi takvime yazılacağı SORULUYOR: birden çok takvim olduğunda
       * sunucunun seçtiği varsayılan her zaman kullanıcının istediği olmuyor. */
      {
        ad: "takvim",
        etiket: "Takvim",
        tur: "secim",
        deger: String((durum.veri.calendars.find((c) => durum.takvimGorunur.get(c.id) !== false)
          || durum.veri.calendars[0] || {}).id || ""),
        secenekler: durum.veri.calendars.map((c) => ({ deger: String(c.id), etiket: c.name })),
      },
      {
        ad: "tekrar",
        etiket: "Tekrar",
        tur: "secim",
        deger: "yok",
        secenekler: [
          { deger: "yok", etiket: "Tekrarlanmasın" },
          { deger: "gunluk", etiket: "Her gün" },
          { deger: "haftalik", etiket: `Her hafta (${gun.dayName})` },
          { deger: "haftaici", etiket: "Hafta içi her gün" },
          { deger: "aylik", etiket: "Her ay" },
        ],
      },
    ],
    "Ekle",
  );
  if (s === null || !s.baslik.trim()) return;

  const ad = s.baslik.trim();
  await eylem(
    () => istek("/api/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // Tarih ve saat BURADA belli; sunucu metin ayrıştırmasın.
      body: JSON.stringify({
        title: ad,
        date: gun.date,
        minutes: dakika,
        endMinutes: bitis,
        tekrar: s.tekrar,
        calendarId: s.takvim ? Number(s.takvim) : undefined,
      }),
    }),
    `Eklendi: ${ad} (${gun.dayNumber} ${gun.monthName} ${dakikaSaat(dakika)})`,
  );
}

/* ---------- sürükle-bırak ---------- */

/* Hedef, SUNUCUYA tarih + gün başından dakika olarak gönderilir. JS'te
 * "şu IANA diliminde şu duvar saati" kurmak güvenilir değil; sunucuda
 * from_wall_clock zaten var ve test edilmiş. Izgara da zaten yerel dakika ile
 * çalıştığı için elimizdeki iki değer doğrudan bunlar.
 */

const SNAP = 15; // dakika
const ESIK = 4;  // px: bu kadar oynamadan sürükleme başlamaz (tık kaybolmasın)

const surukleme = { aktif: false, tasindi: false };

function surukleBasla(e, blok, occ, gun, kip = "tasi") {
  if (e.button !== 0 || occ.allDay) return;
  const blokKutu = blok.getBoundingClientRect();
  Object.assign(surukleme, {
    aktif: true,
    tasindi: false,
    kip,
    blok,
    occ,
    kaynakGun: gun,
    baslangicX: e.clientX,
    baslangicY: e.clientY,
    tutmaOfseti: e.clientY - blokKutu.top,
    sure: occ.endMin - occ.startMin,
    hedefGun: gun,
    hedefDakika: occ.startMin,
    hedefBitisDakika: occ.endMin,
  });
  /* `preventDefault` ŞART. Basılı tutup sürüklemek tarayıcının kendi
   * davranışlarını tetikliyor: bloğun içindeki metni SEÇMEK, seçili metnin
   * üstünden başlayınca da işletim sisteminin sürükle-bırak işlemini
   * başlatmak. İkincisi başlarsa tarayıcı `pointercancel` atıp fare
   * olaylarını kendine alıyor; `surukleBitir` sürüklemenin ORTASINDA
   * çalışıyor ve hedef hâlâ kaynak gün olduğu için "değişmedi" deyip geri
   * alıyor. Kullanıcı açısından sonuç: bloğu yan güne bırakıyorsun, hiçbir
   * şey olmuyor.
   *
   * BURAYA `setPointerCapture` DA EKLEME: bloğu hedef kolona taşımak için
   * `appendChild` kullanıyoruz, yakalanmış bir öğe DOM'da yer değiştirince
   * yakalama düşüyor ve aynı erken bitirme riski doğuyor. Pencere dışına
   * çıkan imleç sorunu bu riske değmez. */
  e.preventDefault();
  e.stopPropagation();
}

/** Boyutlandırma: başlangıç sabit, yalnızca bitiş oynar. */
function boyutlandirHareket(e) {
  const sutun = surukleme.blok.parentElement;
  const kutu = sutun.getBoundingClientRect();
  const gun = surukleme.kaynakGun;

  const oran = (e.clientY - kutu.top) / kutu.height;
  let bitis = Math.round((oran * gun.dayMinutes) / SNAP) * SNAP;
  // En az bir dilim; gece yarısını aşmaya izin veriyoruz (sunucu 48 saate
  // kadar kabul ediyor), ama ızgara tek gün çizdiği için burada sınırlıyoruz.
  bitis = Math.max(surukleme.occ.startMin + SNAP, Math.min(bitis, gun.dayMinutes));

  surukleme.hedefBitisDakika = bitis;
  surukleme.blok.style.height =
    `${((bitis - surukleme.occ.startMin) / gun.dayMinutes) * 100}%`;
  const saatEl = surukleme.blok.querySelector(".b-saat");
  if (saatEl) {
    saatEl.textContent =
      `${dakikaSaat(surukleme.occ.startMin)}–${dakikaSaat(bitis)}`;
  }
}

function dakikaSaat(dk) {
  const s = Math.floor(dk / 60) % 24;
  return `${String(s).padStart(2, "0")}:${String(dk % 60).padStart(2, "0")}`;
}

function surukleHareket(e) {
  if (!surukleme.aktif) return;
  if (
    !surukleme.tasindi &&
    Math.abs(e.clientY - surukleme.baslangicY) < ESIK &&
    Math.abs(e.clientX - surukleme.baslangicX) < ESIK
  ) {
    return;
  }
  surukleme.tasindi = true;
  surukleme.blok.classList.add("suruklenen");

  if (surukleme.kip === "boyutlandir") {
    boyutlandirHareket(e);
    return;
  }

  const sutunlar = [...document.querySelectorAll(".gun-sutun")];
  let indeks = sutunlar.findIndex((s) => {
    const k = s.getBoundingClientRect();
    return e.clientX >= k.left && e.clientX < k.right;
  });
  if (indeks < 0) indeks = sutunlar.indexOf(surukleme.blok.parentElement);
  const hedefGun = durum.veri.days[indeks];
  if (!hedefGun) return;

  const kutu = sutunlar[indeks].getBoundingClientRect();
  const oran = (e.clientY - kutu.top - surukleme.tutmaOfseti) / kutu.height;
  let dakika = Math.round((oran * hedefGun.dayMinutes) / SNAP) * SNAP;
  dakika = Math.max(0, Math.min(dakika, hedefGun.dayMinutes - SNAP));

  surukleme.hedefGun = hedefGun;
  surukleme.hedefDakika = dakika;

  if (surukleme.blok.parentElement !== sutunlar[indeks]) {
    sutunlar[indeks].appendChild(surukleme.blok);
  }
  surukleme.blok.style.top = `${(dakika / hedefGun.dayMinutes) * 100}%`;
  const saatEl = surukleme.blok.querySelector(".b-saat");
  if (saatEl) {
    saatEl.textContent = `${dakikaSaat(dakika)}–${dakikaSaat(dakika + surukleme.sure)}`;
  }
}

async function surukleBitir() {
  if (!surukleme.aktif) return;
  const { tasindi, kip, occ, kaynakGun, hedefGun, hedefDakika, hedefBitisDakika } = surukleme;
  surukleme.aktif = false;
  if (surukleme.blok) surukleme.blok.classList.remove("suruklenen");
  if (!tasindi) return;

  // Tık olayı sürüklemeden SONRA da ateşleniyor; panel açılmasın diye bayrağı
  // bir tur sonra temizliyoruz.
  setTimeout(() => { surukleme.tasindi = false; }, 0);

  const boyutlandirma = kip === "boyutlandir";
  const degismedi = boyutlandirma
    ? hedefBitisDakika === occ.endMin
    : hedefGun.date === kaynakGun.date && hedefDakika === occ.startMin;
  if (degismedi) {
    await yukle(); // önizlemeyi geri al
    return;
  }

  const govde = boyutlandirma
    ? {
        eventId: occ.eventId,
        originalStartUtc: occ.originalStartUtc,
        newDate: kaynakGun.date,
        newMinutes: occ.startMin,
        newEndMinutes: hedefBitisDakika,
      }
    : {
        eventId: occ.eventId,
        originalStartUtc: occ.originalStartUtc,
        newDate: hedefGun.date,
        newMinutes: hedefDakika,
      };

  try {
    await istek("/api/occurrences/move", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(govde),
    });
    bildir(
      boyutlandirma
        ? `Süre değişti: ${occ.title} → ${dakikaSaat(occ.startMin)}–${dakikaSaat(hedefBitisDakika)}`
        : `Taşındı: ${occ.title} → ${dakikaSaat(hedefDakika)}`,
    );
  } catch (hata) {
    bildir(hata.message, true);
  }
  await yukle();
}

/* ---------- tüm gün şeridinde sürükleme ---------- */

/* Saatli bloklardan ayrı bir yol: tüm gün etkinliğinin başlangıcı yerel gece
 * yarısı, yani taşıma GÜN birimindedir. newMinutes=0 gönderiyoruz ve süreyi
 * move_occurrence koruyor.
 */

const tumgunSurukleme = { aktif: false, tasindi: false };

function tumgunBasla(e, blok, occ) {
  if (e.button !== 0) return;
  Object.assign(tumgunSurukleme, {
    aktif: true, tasindi: false, blok, occ,
    baslangicX: e.clientX, hedefTarih: null,
  });
  // Metin seçimi ve işletim sisteminin sürükle-bırakı devreye girmesin;
  // gerekçe `surukleBasla` içinde yazılı.
  e.preventDefault();
}

function tumgunHareket(e) {
  if (!tumgunSurukleme.aktif) return;
  if (!tumgunSurukleme.tasindi && Math.abs(e.clientX - tumgunSurukleme.baslangicX) < ESIK) {
    return;
  }
  tumgunSurukleme.tasindi = true;
  tumgunSurukleme.blok.classList.add("suruklenen");

  const hucreler = [...document.querySelectorAll(".tumgun-hucre")];
  const indeks = hucreler.findIndex((h) => {
    const k = h.getBoundingClientRect();
    return e.clientX >= k.left && e.clientX < k.right;
  });
  if (indeks < 0) return;
  const gun = durum.veri.days[indeks];
  if (!gun) return;
  tumgunSurukleme.hedefTarih = gun.date;
  if (tumgunSurukleme.blok.parentElement !== hucreler[indeks]) {
    hucreler[indeks].appendChild(tumgunSurukleme.blok);
  }
}

async function tumgunBitir() {
  if (!tumgunSurukleme.aktif) return;
  const { tasindi, occ, hedefTarih } = tumgunSurukleme;
  tumgunSurukleme.aktif = false;
  if (tumgunSurukleme.blok) tumgunSurukleme.blok.classList.remove("suruklenen");
  if (!tasindi) return;
  setTimeout(() => { tumgunSurukleme.tasindi = false; }, 0);

  if (!hedefTarih) { await yukle(); return; }

  try {
    await istek("/api/occurrences/move", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        eventId: occ.eventId,
        originalStartUtc: occ.originalStartUtc,
        newDate: hedefTarih,
        newMinutes: 0,
      }),
    });
    bildir(`Taşındı: ${occ.title} → ${hedefTarih}`);
  } catch (hata) {
    bildir(hata.message, true);
  }
  await yukle();
}

document.addEventListener("pointermove", tumgunHareket);
document.addEventListener("pointerup", tumgunBitir);
document.addEventListener("pointercancel", tumgunBitir);

document.addEventListener("pointermove", surukleHareket);
document.addEventListener("pointerup", surukleBitir);
document.addEventListener("pointercancel", surukleBitir);

/* ---------- ay görünümü ---------- */

function ayCiz(veri) {
  const bugun = bugunISO();

  const basliklar = el("ay-basliklar");
  basliklar.innerHTML = "";
  veri.dayNames.forEach((ad) => {
    const d = document.createElement("div");
    d.textContent = ad;
    basliklar.appendChild(d);
  });

  const izgara = el("ay-izgara");
  izgara.innerHTML = "";
  veri.days.forEach((g) => {
    const hucre = document.createElement("div");
    hucre.className =
      "ay-hucre" + (g.inMonth ? "" : " disarida") + (g.date === bugun ? " bugun" : "");

    const no = document.createElement("div");
    no.className = "ay-gun-no";
    no.textContent = g.dayNumber;
    hucre.appendChild(no);

    const gorunurler = g.events.filter(gorunurMu);
    gorunurler.slice(0, AY_MAKS_BLOK).forEach((occ) => {
      const blok = document.createElement("div");
      blok.className = "ay-blok";
      blok.textContent = occ.allDay
        ? occ.title
        : `${saatBicim(occ.startUtc, occ.tzid)} ${occ.title}`;
      blok.style.background = zemin(occ.color);
      blok.style.borderLeftColor = occ.color;
      blok.onclick = (e) => { e.stopPropagation(); panelAc(occ); };
      hucre.appendChild(blok);
    });

    if (gorunurler.length > AY_MAKS_BLOK) {
      const daha = document.createElement("div");
      daha.className = "ay-daha";
      daha.textContent = `+${gorunurler.length - AY_MAKS_BLOK} daha`;
      daha.onclick = (e) => { e.stopPropagation(); gunListesiAc(g, gorunurler, e); };
      hucre.appendChild(daha);
    }

    // Hücreye tıklayınca o günün gün görünümüne geç
    hucre.onclick = () => { durum.gorunum = "day"; durum.anchor = g.date; yukle(); };
    izgara.appendChild(hucre);
  });
}

/* ---------- ay görünümü: gün listesi açılır penceresi ---------- */

/* "+N daha" tıklanınca gün görünümüne atlamak, kullanıcıyı bulunduğu yerden
 * koparıyordu. Bunun yerine o günün tamamını yerinde gösteriyoruz.
 */

function gunListesiKapat() {
  const eski = el("gun-listesi");
  if (eski) eski.remove();
}

function gunListesiAc(gun, occurrences, olay) {
  gunListesiKapat();

  const kutu = document.createElement("div");
  kutu.className = "gun-listesi";
  kutu.id = "gun-listesi";

  const baslik = document.createElement("div");
  baslik.className = "gl-baslik";
  baslik.textContent = new Intl.DateTimeFormat("tr-TR", {
    weekday: "long", day: "numeric", month: "long",
  }).format(new Date(`${gun.date}T12:00:00`));
  kutu.appendChild(baslik);

  occurrences.forEach((occ) => {
    const satir = document.createElement("div");
    satir.className = "gl-satir";
    satir.style.borderLeftColor = occ.color;
    satir.style.background = zemin(occ.color);
    satir.textContent = occ.allDay
      ? occ.title
      : `${saatBicim(occ.startUtc, occ.tzid)} ${occ.title}`;
    satir.onclick = () => { gunListesiKapat(); panelAc(occ); };
    kutu.appendChild(satir);
  });

  const gunDugme = document.createElement("button");
  gunDugme.className = "gl-gun-dugme";
  gunDugme.textContent = "Gün görünümünde aç";
  gunDugme.onclick = () => {
    gunListesiKapat();
    durum.gorunum = "day";
    durum.anchor = gun.date;
    yukle();
  };
  kutu.appendChild(gunDugme);

  document.body.appendChild(kutu);

  // Ekran dışına taşmasın
  const k = kutu.getBoundingClientRect();
  const x = Math.min(olay.clientX, window.innerWidth - k.width - 12);
  const y = Math.min(olay.clientY, window.innerHeight - k.height - 12);
  kutu.style.left = `${Math.max(8, x)}px`;
  kutu.style.top = `${Math.max(8, y)}px`;

  setTimeout(() => {
    document.addEventListener("click", gunListesiKapat, { once: true });
  }, 0);
}

/* ---------- etkinlik paneli ---------- */

function panelAc(occ) {
  durum.secili = occ;
  const takvim = durum.veri.calendars.find((c) => c.id === occ.calendarId);

  const satirlar = [];
  satirlar.push([
    "Zaman",
    occ.allDay
      ? tarihBicim(occ.startUtc, occ.tzid)
      : `${tarihBicim(occ.startUtc, occ.tzid)}<br>${saatBicim(occ.startUtc, occ.tzid)} – ${saatBicim(occ.endUtc, occ.tzid)}`,
  ]);
  if (takvim) {
    satirlar.push([
      "Takvim",
      `<span class="p-takvim"><span class="renk-kutu" style="background:${takvim.color}"></span>${kacir(takvim.name)}</span>`,
    ]);
  }
  if (occ.location) satirlar.push(["Konum", kacir(occ.location)]);
  satirlar.push(["Dilim", kacir(occ.tzid)]);

  const rozetler = [];
  if (occ.allDay) rozetler.push(`<span class="rozet">tüm gün</span>`);
  if (occ.isOverride) rozetler.push(`<span class="rozet override">seriden taşındı</span>`);
  if (occ.clipped) rozetler.push(`<span class="rozet">gece yarısını aşıyor</span>`);
  if (rozetler.length) satirlar.push(["Durum", rozetler.join(" ")]);

  if (occ.reminders && occ.reminders.length) {
    satirlar.push([
      "Hatırlatıcı",
      occ.reminders
        .map((r) => `<span class="rozet">${hatirlaticiMetni(r.minutesBefore)}</span>`)
        .join(" "),
    ]);
  }

  let html = `<div class="p-baslik">${kacir(occ.title)}</div>`;
  html += satirlar
    .map(([e, d]) => `<div class="p-satir"><div class="p-etiket">${e}</div><div class="p-deger">${d}</div></div>`)
    .join("");
  if (occ.description) {
    html += `<div class="p-satir"><div class="p-etiket">Açıklama</div><div class="p-deger p-aciklama">${kacir(occ.description)}</div></div>`;
  }
  el("panel-icerik").innerHTML = html;

  islemleriCiz(occ);
  el("panel").hidden = false;
  ciz();
}

/* Etkinlik işlemleri AYRI fonksiyonlar: hem paneldeki düğmeler hem klavye
 * kısayolları aynı kodu çağırsın. İkiye ayrılsalardı onay metni bir yerde
 * güncellenip diğerinde unutulurdu -- silme gibi geri alınamaz bir işlemde
 * bu kabul edilemez. */

/** ISO andını etkinliğin KENDİ saat diliminde `YYYY-AA-GG` yapar. */
function yerelTarihISO(iso, tzid) {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric", month: "2-digit", day: "2-digit", timeZone: tzid,
  }).format(new Date(iso));
}

/** ISO andını etkinliğin KENDİ saat diliminde `SS:DD` yapar. */
function yerelSaatISO(iso, tzid) {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: tzid,
  }).format(new Date(iso));
}

function dakikayaCevir(ss_dd) {
  const [s, d] = (ss_dd || "0:0").split(":").map(Number);
  return s * 60 + d;
}

/* Etkinliği çok alanlı formla düzenler.
 *
 * Bunun var olmasının sebebi: bir etkinliğin SAATİNİ değiştirmenin tek yolu
 * bloğu sürüklemekti ve sürükleme yalnızca ekrandaki günler arasında çalışıyor
 * (ay görünümünde hiç yok). "Sonraki haftaya nasıl taşırım" sorusunun cevabı
 * buydu. Sunucu tarafı zaten hazırdı: konum/açıklama için PATCH, tarih/saat
 * için `/api/occurrences/move`.
 */
async function etkinligiDuzenle(occ) {
  const eskiTarih = yerelTarihISO(occ.startUtc, occ.tzid);
  const eskiBas = yerelSaatISO(occ.startUtc, occ.tzid);
  const eskiBit = yerelSaatISO(occ.endUtc, occ.tzid);

  const alanlar = [
    { ad: "baslik", etiket: "Başlık", tur: "metin", deger: occ.title },
    { ad: "tarih", etiket: "Tarih", tur: "tarih", deger: eskiTarih },
  ];
  if (!occ.allDay) {
    alanlar.push(
      { ad: "baslangic", etiket: "Başlangıç", tur: "saat", deger: eskiBas, dar: true },
      { ad: "bitis", etiket: "Bitiş", tur: "saat", deger: eskiBit, dar: true },
    );
  }
  alanlar.push(
    { ad: "konum", etiket: "Konum", tur: "metin", deger: occ.location || "" },
    { ad: "aciklama", etiket: "Açıklama", tur: "uzunmetin", deger: occ.description || "" },
  );

  const s = await modalForm(
    "Etkinliği düzenle",
    occ.recurring
      ? "Tekrarlı seri: başlık, konum ve açıklama TÜM seriyi, tarih ve saat yalnızca BU örneği etkiler."
      : "",
    alanlar,
  );
  if (s === null) return;

  const yeniBaslik = (s.baslik || "").trim();
  if (!yeniBaslik) {
    bildir("Başlık boş olamaz", true);
    return;
  }

  const yama = {};
  if (yeniBaslik !== occ.title) yama.title = yeniBaslik;
  if ((s.konum || "") !== (occ.location || "")) yama.location = s.konum.trim() || null;
  if ((s.aciklama || "") !== (occ.description || "")) yama.description = s.aciklama.trim() || null;

  const saatDegisti = !occ.allDay && (s.baslangic !== eskiBas || s.bitis !== eskiBit);
  const tasindi = s.tarih !== eskiTarih || saatDegisti;

  if (!Object.keys(yama).length && !tasindi) return; // hiçbir şey değişmedi

  await eylem(async () => {
    if (Object.keys(yama).length) {
      await istek(`/api/events/${occ.eventId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(yama),
      });
    }
    if (tasindi) {
      const govde = {
        eventId: occ.eventId,
        originalStartUtc: occ.originalStartUtc,
        newDate: s.tarih,
        newMinutes: 0,
      };
      if (!occ.allDay) {
        const bas = dakikayaCevir(s.baslangic);
        let bit = dakikayaCevir(s.bitis);
        // Bitiş başlangıçtan küçükse gece yarısını aşıyordur: ertesi güne taşı.
        if (bit <= bas) bit += 24 * 60;
        govde.newMinutes = bas;
        govde.newEndMinutes = bit;
      }
      await istek("/api/occurrences/move", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(govde),
      });
    }
  }, "Etkinlik güncellendi");
}

/** Tekrarlıda bu örneği iptal eder, tekrarsızda etkinliği SİLER. */
async function ornegiSil(occ) {
  const tamam = await onayla(
    occ.recurring ? "Bu örneği sil" : "Etkinliği sil",
    occ.recurring
      ? `"${occ.title}" — yalnızca bu örnek silinecek, serinin geri kalanı kalır.`
      : `"${occ.title}" silinecek.`,
    "Sil",
    true,
  );
  if (!tamam) return;
  await eylem(
    () => istek("/api/occurrences/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ eventId: occ.eventId, originalStartUtc: occ.originalStartUtc }),
    }),
    occ.recurring ? "Bu örnek silindi" : "Silindi",
    // Tüm gün etkinliğinde geri alma YOK: yeniden oluşturma yolu saatli
    // etkinlik kuruyor ve sessizce yanlış bir şey geri getirmek, geri
    // getirmemekten kötü.
    occ.allDay ? null : () => silmeyiGeriAl(occ),
  );
}

/* Silmeyi geri alır.
 *
 * İki farklı iş: tekrarlı seride kayıt hiç silinmedi, yalnızca iptal
 * override'ı yazıldı -- onu kaldırmak yetiyor. Tekrarsızda kayıt gerçekten
 * gitti, elimizdeki örnek verisinden YENİDEN kuruyoruz (yeni id alır).
 * Hatırlatıcılar ve konum/açıklama da geri geliyor.
 */
async function silmeyiGeriAl(occ) {
  if (occ.recurring) {
    await eylem(
      () => istek("/api/occurrences/restore", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ eventId: occ.eventId, originalStartUtc: occ.originalStartUtc }),
      }),
      "Geri alındı",
    );
    return;
  }

  const tarih = yerelTarihISO(occ.startUtc, occ.tzid);
  const bas = dakikayaCevir(yerelSaatISO(occ.startUtc, occ.tzid));
  let bit = dakikayaCevir(yerelSaatISO(occ.endUtc, occ.tzid));
  if (bit <= bas) bit += 24 * 60;

  await eylem(async () => {
    const yanit = await istek("/api/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: occ.title,
        date: tarih,
        minutes: bas,
        endMinutes: bit,
        calendarId: occ.calendarId,
      }),
    });
    const yeniId = yanit.event.id;
    if (occ.location || occ.description) {
      await istek(`/api/events/${yeniId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ location: occ.location, description: occ.description }),
      });
    }
    for (const r of occ.reminders || []) {
      await istek(`/api/events/${yeniId}/reminders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ minutesBefore: r.minutesBefore }),
      });
    }
  }, "Geri alındı");
}

/** Seriyi tamamen siler. Sayı ONAYDAN ÖNCE sunucudan geliyor (`series_info`);
 * geri alma sunucu anlık görüntüsünden diriliyor (override + hatırlatıcı +
 * fired geçmişi dahil), istemcinin yeniden kurmasından değil. */
async function seriyiSil(occ) {
  let bilgi;
  try {
    bilgi = await istek(`/api/series_info?event_id=${occ.eventId}`);
  } catch (hata) {
    bildir(hata.message, true);
    return;
  }
  const kapsam = bilgi.recurring
    ? (bilgi.sonsuz
      ? `Sonsuz seri — önümüzdeki 2 yılda ${bilgi.ornek_sayisi} örnek`
      : `${bilgi.ornek_sayisi} örnek (2 yıllık pencerede)`)
    : "Tek seferlik etkinlik";
  const tamam = await onayla(
    "Seriyi tamamen sil",
    `"${bilgi.title}" — ${kapsam} silinecek.`,
    "Seriyi sil",
    true,
  );
  if (!tamam) return;
  await eylem(
    () => istek(`/api/events/${occ.eventId}`, { method: "DELETE" }),
    `"${bilgi.title}" silindi`,
    () => eylem(
      () => istek("/api/events/restore_last", { method: "POST" }),
      "Seri geri alındı",
    ),
  );
}

/* Yedek listesi + geri yükleme. Seçim kutusu `modalForm`un `secim` türü;
 * çift onay var (seçim + tehlike onayı): dosyanın üstüne yazma geri alınabilir
 * olsa da (kenara alınıyor) kullanıcının ne yaptığını bilmesi şart. Sonunda
 * tam sayfa yenileme: takvimler dahil her şey değişmiş olabilir. */
async function yedekleriAc() {
  let veri;
  try {
    veri = await istek("/api/backups");
  } catch (hata) {
    bildir(hata.message, true);
    return;
  }
  if (!veri.backups.length) {
    bildir("Henüz yedek yok — yedek her açılışta alınır.");
    return;
  }
  const secim = await modalForm("Yedekten dön",
    "Seçili yedek CANLI veritabanının üstüne yazılır. Mevcut hâl önce yedek " +
    "klasörüne kenara alınır (onceki-takvim-….db).",
    [{
      ad: "yedek",
      etiket: "Yedek",
      tur: "secim",
      deger: veri.backups[0].ad,
      secenekler: veri.backups.map((b) => ({
        deger: b.ad,
        etiket: `${b.ad} (${(b.boyut / 1024).toFixed(1)} KB)`,
      })),
    }],
    "Geri yükle");
  if (!secim) return;
  const tamam = await onayla(
    "Yedekten dön",
    `"${secim.yedek}" geri yüklenecek, sayfa yeniden yüklenir.`,
    "Geri yükle",
    true,
  );
  if (!tamam) return;
  try {
    await istek("/api/backups/restore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ad: secim.yedek }),
    });
    window.location.reload();
  } catch (hata) {
    bildir(hata.message, true);
  }
}

function islemleriCiz(occ) {
  const kap = el("panel-islemler");
  kap.innerHTML = "";

  const ekle = (metin, tehlike, islev, kisayol) => {
    const b = document.createElement("button");
    b.className = "islem-dugme" + (tehlike ? " tehlike" : "");
    b.textContent = metin;
    // Kısayolu düğmenin üstünde göster: klavye kısayolu ancak keşfedilebilirse
    // işe yarar.
    if (kisayol) b.title = `Kısayol: ${kisayol}`;
    b.onclick = islev;
    kap.appendChild(b);
  };

  ekle("Düzenle", false, () => etkinligiDuzenle(occ), "F2 · Enter");

  (occ.reminders || []).forEach((r) => {
    ekle(`⏰ ${hatirlaticiMetni(r.minutesBefore)} — kaldır`, false, async () => {
      await eylem(
        () => istek(`/api/reminders/${r.id}`, { method: "DELETE" }),
        "Hatırlatıcı kaldırıldı",
      );
    });
  });

  ekle("Hatırlatıcı ekle", false, async () => {
    const ham = await sor(
      "Hatırlatıcı ekle",
      "Kaç dakika önce hatırlatılsın?\n(0 = tam başlarken, 1440 = 1 gün önce)",
      "15",
    );
    if (ham === null) return;
    const dakika = parseInt(ham, 10);
    if (Number.isNaN(dakika) || dakika < 0) {
      bildir("Geçerli bir dakika değeri gir", true);
      return;
    }
    await eylem(
      () => istek(`/api/events/${occ.eventId}/reminders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ minutesBefore: dakika }),
      }),
      `Hatırlatıcı eklendi: ${hatirlaticiMetni(dakika)}`,
    );
  });

  // Tekrarlı serilerde tek örnek / tüm seri ayrımı kritik: kullanıcı bir
  // dersi bu haftalık iptal etmekle dönem boyunca silmeyi karıştırmamalı.
  // Klavyede de aynı ayrım var: Del tek örnek, Shift+Del tüm seri.
  // TEKRARSIZ etkinlikte iki düğme göstermek anlamsız ve korkutucu: tek "Sil".
  if (occ.recurring) {
    ekle("Bu örneği sil", true, () => ornegiSil(occ), "Del");
    ekle("Seriyi tamamen sil", true, () => seriyiSil(occ), "Shift+Del");
  } else {
    ekle("Sil", true, () => ornegiSil(occ), "Del");
  }
}

function hatirlaticiMetni(dakika) {
  if (dakika === 0) return "tam başlarken";
  if (dakika % 1440 === 0) return `${dakika / 1440} gün önce`;
  if (dakika % 60 === 0) return `${dakika / 60} saat önce`;
  return `${dakika} dakika önce`;
}

async function eylem(islev, basariMesaji, geriAl = null) {
  try {
    await islev();
    bildir(basariMesaji, false, geriAl);
    panelKapat();
    await yukle();
  } catch (hata) {
    bildir(hata.message, true);
  }
}

function panelKapat() {
  durum.secili = null;
  el("panel").hidden = true;
  ciz();
}

/* ---------- hızlı ekleme ---------- */

/* Enter'ı AÇIKÇA ele alıyoruz. Tek girdili bir formda tarayıcının "örtük
 * submit" davranışı garanti değil ve bu kutuda Enter birincil etkileşim --
 * yazıp Enter'a basınca hiçbir şey olmaması, uygulamanın bozuk olduğu
 * anlamına gelir. `requestSubmit()` normal submit olayını tetikliyor, yani
 * iş yine tek yerde: aşağıdaki `onsubmit`.
 */
el("hizli-girdi").addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || e.isComposing) return;
  e.preventDefault(); // örtük submit de ateşlenip iki kez göndermesin
  const form = el("hizli-form");
  if (form.requestSubmit) form.requestSubmit();
  else form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
});

el("hizli-form").onsubmit = async (e) => {
  e.preventDefault();
  const girdi = el("hizli-girdi");
  const metin = girdi.value.trim();
  if (!metin) return;

  try {
    const sonuc = await istek("/api/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: metin }),
    });
    girdi.value = "";
    const p = sonuc.parsed;
    // Neyin zaman olarak tanındığını SÖYLÜYORUZ. Tanınmayan ifade sessizce
    // yanlış saate kaydedilmiş bir randevuya dönüşmesin.
    bildir(
      p.matched
        ? `Eklendi: ${p.title} (${p.matched})`
        : `Eklendi: ${p.title} — zaman ifadesi tanınmadı, tüm gün olarak kaydedildi`,
      !p.matched,
    );
    await yukle();
  } catch (hata) {
    bildir(hata.message, true);
  }
};

/* ---------- arama ---------- */

let aramaZaman = null;
el("arama").oninput = (e) => {
  const anahtar = e.target.value.trim();
  clearTimeout(aramaZaman);
  aramaZaman = setTimeout(() => aramaYap(anahtar), 220);
};

async function aramaYap(anahtar) {
  const bolum = el("arama-bolum");
  const liste = el("arama-listesi");
  if (!anahtar) {
    bolum.hidden = true;
    return;
  }
  try {
    const sonuc = await istek(`/api/search?q=${encodeURIComponent(anahtar)}`);
    liste.innerHTML = "";
    if (!sonuc.results.length) {
      liste.innerHTML = `<li class="arama-bos">Sonuç yok</li>`;
    }
    sonuc.results.forEach((ev) => {
      const takvim = durum.veri.calendars.find((c) => c.id === ev.calendarId);
      const li = document.createElement("li");
      li.className = "arama-satir";
      li.style.borderLeftColor = takvim ? takvim.color : "#6b7280";
      li.innerHTML =
        `<div>${kacir(ev.title)}${ev.recurring ? " ↻" : ""}</div>` +
        `<div class="a-tarih">${tarihBicim(ev.startUtc, ev.tzid)}</div>`;
      // Sonuca tıklayınca o tarihe git
      li.onclick = () => {
        durum.anchor = new Intl.DateTimeFormat("en-CA", { timeZone: ev.tzid })
          .format(new Date(ev.startUtc));
        yukle();
      };
      liste.appendChild(li);
    });
    bolum.hidden = false;
  } catch (hata) {
    bildir(hata.message, true);
  }
}

/* ---------- gezinme ---------- */

function kaydir(yon) {
  if (durum.gorunum === "month") {
    durum.anchor = ayKaydir(durum.veri ? durum.veri.anchor : durum.anchor, yon);
  } else {
    const adim = durum.gorunum === "day" ? 1 : 7;
    durum.anchor = tarihKaydir(durum.veri ? durum.veri.weekStart : durum.anchor, yon * adim);
  }
  yukle();
}

el("onceki").onclick = () => kaydir(-1);
el("sonraki").onclick = () => kaydir(1);
el("bugun").onclick = () => { durum.anchor = bugunISO(); yukle(); };
el("takvim-ekle").onclick = takvimEkle;
el("panel-kapat").onclick = panelKapat;
el("disa-aktar").onclick = () => { window.location.href = "/api/export"; };
el("yedekler").onclick = yedekleriAc;

document.querySelectorAll(".gorunum-dugme").forEach((b) => {
  b.onclick = () => { durum.gorunum = b.dataset.gorunum; yukle(); };
});

document.addEventListener("keydown", (e) => {
  // Soru kutusu açıkken arkadaki görünüm değişmesin: "Sil?" kutusundayken
  // "a" harfine basmak ay görünümüne atlıyordu.
  if (modalAcik()) return;

  /* Değiştirici tuşlu birleşimler bizim değil: Ctrl+A (tümünü seç),
   * Ctrl+H, Ctrl+T gibi birleşimleri kaçırırsak kullanıcı metni seçemez
   * ya da beklediği davranış yerine görünüm değişir. Tek harflik
   * kısayollar yalnızca ÇIPLAK basıldığında geçerli. */
  if (e.ctrlKey || e.altKey || e.metaKey) return;

  // Yazarken kısayollar devreye girmesin. Del ve Backspace için bu ŞART:
  // hızlı ekleme kutusunda yazarken Del etkinlik silmemeli, harf silmeli.
  if (["INPUT", "TEXTAREA"].includes(e.target.tagName)) {
    if (e.key === "Escape") e.target.blur();
    return;
  }

  /* Seçili etkinlik üzerinde çalışan kısayollar. "Seçili" = paneli açık olan
   * etkinlik; kullanıcı ona zaten tıklamış durumda.
   *
   * Del ile Shift+Del ayrımı paneldeki iki düğmenin aynısı: tek örnek mi, tüm
   * seri mi. İkisi de ONAY SORUYOR -- klavyeyle çalışmak silmeyi hızlandırır,
   * geri alınamaz hale getirmez. */
  const secili = durum.secili;
  if (secili) {
    if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      (e.shiftKey && secili.recurring ? seriyiSil : ornegiSil)(secili);
      return;
    }
    if (e.key === "F2" || e.key === "Enter") {
      e.preventDefault();
      etkinligiDuzenle(secili);
      return;
    }
  }
  const kisayollar = {
    Escape: () => { gunListesiKapat(); panelKapat(); },
    ArrowLeft: () => kaydir(-1),
    ArrowRight: () => kaydir(1),
    t: () => { durum.anchor = bugunISO(); yukle(); },
    g: () => { durum.gorunum = "day"; yukle(); },
    h: () => { durum.gorunum = "week"; yukle(); },
    a: () => { durum.gorunum = "month"; yukle(); },
  };
  const islev = kisayollar[e.key] || kisayollar[e.key.toLowerCase()];
  if (islev) { e.preventDefault(); islev(); }
});

/* ---------- canlı tazeleme ---------- */

/* Bu uygulama gün boyu açık duruyor (hatırlatıcı zaten yalnızca açıkken
 * çalışıyor). Hiçbir zamanlayıcı yoktu ve bunun iki görünür sonucu vardı:
 * kırmızı "şimdi" çizgisi ÇİZİLDİĞİ ANDA donuyordu, öğleden sonra ekrana
 * bakınca hâlâ sabahı gösteriyordu; gece yarısı geçince de dünkü sütun
 * "bugün" olarak işaretli kalıyordu. Uygulamanın canlı değil ekran görüntüsü
 * gibi durmasının sebebi buydu.
 */
const TAZELE_ARALIK = 30 * 1000;

function simdiCizgisiniTazele() {
  const cizgi = document.querySelector(".simdi-cizgi");
  if (!cizgi || !durum.veri || !durum.veri.days) return;
  const gun = durum.veri.days.find((g) => g.date === bugunISO());
  if (!gun) return;
  const simdi = new Date();
  cizgi.style.top = `${((simdi.getHours() * 60 + simdi.getMinutes()) / gun.dayMinutes) * 100}%`;
}

function canliBaslat() {
  let sonGun = bugunISO();
  setInterval(() => {
    // Kullanıcı bir şeyin ortasındaysa ekranın altını oymayalım.
    if (surukleme.aktif || tumgunSurukleme.aktif || modalAcik()) return;

    const gun = bugunISO();
    if (gun !== sonGun) {
      sonGun = gun;
      /* Gece yarısı geçti: "bugün" vurgusu ve şimdi çizgisi başka güne ait.
       * `durum.anchor`a DOKUNMUYORUZ: kullanıcı başka bir haftaya bakıyor
       * olabilir ve ekranı altından kaydırmak kabalık olur. Yeniden çizmek
       * yeterli, "Bugün" düğmesi zaten bir tık uzakta. */
      yukle();
      return;
    }
    simdiCizgisiniTazele();
  }, TAZELE_ARALIK);
}

yukle();
canliBaslat();
