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

let bildirimZaman = null;
function bildir(mesaj, hata = false) {
  const kutu = el("bildirim");
  kutu.textContent = mesaj;
  kutu.classList.toggle("hata", hata);
  kutu.hidden = false;
  clearTimeout(bildirimZaman);
  bildirimZaman = setTimeout(() => { kutu.hidden = true; }, hata ? 7000 : 3500);
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
    li.innerHTML = `<span class="renk-kutu"></span><span class="takvim-ad"></span>`;
    li.querySelector(".renk-kutu").style.background = c.color;
    li.querySelector(".takvim-ad").textContent = c.name;
    li.title = gorunur ? "Gizle" : "Göster";
    li.onclick = () => gorunurlukDegistir(c.id, !gorunur);
    liste.appendChild(li);
  });
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

function islemleriCiz(occ) {
  const kap = el("panel-islemler");
  kap.innerHTML = "";

  const ekle = (metin, tehlike, islev) => {
    const b = document.createElement("button");
    b.className = "islem-dugme" + (tehlike ? " tehlike" : "");
    b.textContent = metin;
    b.onclick = islev;
    kap.appendChild(b);
  };

  ekle("Başlığı değiştir", false, async () => {
    const yeni = prompt("Yeni başlık:", occ.title);
    if (yeni === null || !yeni.trim()) return;
    await eylem(
      () => istek(`/api/events/${occ.eventId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: yeni.trim() }),
      }),
      "Başlık güncellendi",
    );
  });

  (occ.reminders || []).forEach((r) => {
    ekle(`⏰ ${hatirlaticiMetni(r.minutesBefore)} — kaldır`, false, async () => {
      await eylem(
        () => istek(`/api/reminders/${r.id}`, { method: "DELETE" }),
        "Hatırlatıcı kaldırıldı",
      );
    });
  });

  ekle("Hatırlatıcı ekle", false, async () => {
    const ham = prompt(
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
  ekle("Bu örneği sil", true, async () => {
    if (!confirm(`"${occ.title}" — yalnızca bu örnek silinecek. Devam?`)) return;
    await eylem(
      () => istek("/api/occurrences/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ eventId: occ.eventId, originalStartUtc: occ.originalStartUtc }),
      }),
      "Bu örnek silindi",
    );
  });

  ekle("Seriyi tamamen sil", true, async () => {
    if (!confirm(`"${occ.title}" — TÜM seri silinecek. Bu geri alınamaz. Devam?`)) return;
    await eylem(
      () => istek(`/api/events/${occ.eventId}`, { method: "DELETE" }),
      "Seri silindi",
    );
  });
}

function hatirlaticiMetni(dakika) {
  if (dakika === 0) return "tam başlarken";
  if (dakika % 1440 === 0) return `${dakika / 1440} gün önce`;
  if (dakika % 60 === 0) return `${dakika / 60} saat önce`;
  return `${dakika} dakika önce`;
}

async function eylem(islev, basariMesaji) {
  try {
    await islev();
    bildir(basariMesaji);
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
el("panel-kapat").onclick = panelKapat;
el("disa-aktar").onclick = () => { window.location.href = "/api/export"; };

document.querySelectorAll(".gorunum-dugme").forEach((b) => {
  b.onclick = () => { durum.gorunum = b.dataset.gorunum; yukle(); };
});

document.addEventListener("keydown", (e) => {
  // Yazarken kısayollar devreye girmesin
  if (["INPUT", "TEXTAREA"].includes(e.target.tagName)) {
    if (e.key === "Escape") e.target.blur();
    return;
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

yukle();
