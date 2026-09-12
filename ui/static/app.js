/* Hafta görünümü ön yüzü.
 *
 * Sunucu her gün için kolon (col/colCount) ve dakika (startMin/endMin) gönderir;
 * burada yalnızca yüzdeye çeviriyoruz. Çakışma yerleşimi core/layout.py'de,
 * yani burada yeniden hesaplanmıyor.
 *
 * dayMinutes her gün için ayrı geliyor: DST geçiş gününde 1380 veya 1500 olur.
 * Yüzdeleri ona böldüğümüz için ızgara o günlerde de doğru hizalanıyor.
 */

const durum = {
  anchor: bugunISO(),
  veri: null,
  seciliId: null,
  takvimGorunur: new Map(),
};

const el = {
  haftaEtiketi: document.getElementById("hafta-etiketi"),
  tzEtiketi: document.getElementById("tz-etiketi"),
  takvimListesi: document.getElementById("takvim-listesi"),
  izgaraBaslik: document.getElementById("izgara-baslik"),
  tumgunSerit: document.getElementById("tumgun-serit"),
  saatSutunu: document.getElementById("saat-sutunu"),
  gunler: document.getElementById("gunler"),
  kaydirma: document.getElementById("izgara-kaydirma"),
  panel: document.getElementById("panel"),
  panelIcerik: document.getElementById("panel-icerik"),
  panelKapat: document.getElementById("panel-kapat"),
  yukleniyor: document.getElementById("yukleniyor"),
};

/* ---------- yardımcılar ---------- */

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

/** UTC ISO metnini etkinliğin kendi diliminde "HH:MM" olarak biçimler. */
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

/** Rengi blok zemini için saydamlaştırır. */
function zemin(hex) {
  const n = parseInt(hex.replace("#", ""), 16);
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  return `rgba(${r},${g},${b},0.22)`;
}

function occAnahtar(occ) {
  return `${occ.uid}|${occ.startUtc}`;
}

/* ---------- veri ---------- */

async function haftaYukle(anchor) {
  el.yukleniyor.hidden = false;
  try {
    const yanit = await fetch(`/api/week?date=${anchor}`);
    if (!yanit.ok) throw new Error(`sunucu ${yanit.status}`);
    durum.veri = await yanit.json();
    durum.veri.calendars.forEach((c) => {
      if (!durum.takvimGorunur.has(c.id)) durum.takvimGorunur.set(c.id, c.visible);
    });
    ciz();
  } catch (hata) {
    gosterHata(hata.message);
  } finally {
    el.yukleniyor.hidden = true;
  }
}

async function gorunurlukDegistir(id, gorunur) {
  durum.takvimGorunur.set(id, gorunur);
  takvimleriCiz();
  ciz();
  try {
    await fetch(`/api/calendars/${id}/visible`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visible: gorunur }),
    });
  } catch {
    /* Görünürlük yalnızca bir tercih; yazılamazsa ekran yine doğru. */
  }
}

function gosterHata(mesaj) {
  el.gunler.innerHTML = `<div class="hata">Veri alınamadı: ${mesaj}</div>`;
}

/* ---------- çizim ---------- */

function takvimleriCiz() {
  if (!durum.veri) return;
  el.takvimListesi.innerHTML = "";
  durum.veri.calendars.forEach((c) => {
    const gorunur = durum.takvimGorunur.get(c.id);
    const li = document.createElement("li");
    li.className = "takvim-satir" + (gorunur ? "" : " gizli");
    li.innerHTML = `<span class="renk-kutu"></span><span class="takvim-ad"></span>`;
    li.querySelector(".renk-kutu").style.background = c.color;
    li.querySelector(".takvim-ad").textContent = c.name;
    li.title = gorunur ? "Gizle" : "Göster";
    li.onclick = () => gorunurlukDegistir(c.id, !gorunur);
    el.takvimListesi.appendChild(li);
  });
}

function gorunurMu(occ) {
  return durum.takvimGorunur.get(occ.calendarId) !== false;
}

function ciz() {
  const veri = durum.veri;
  if (!veri) return;

  el.haftaEtiketi.textContent = veri.label;
  el.tzEtiketi.textContent = veri.tzid;
  takvimleriCiz();

  const bugun = bugunISO();

  /* --- gün başlıkları --- */
  el.izgaraBaslik.innerHTML = `<div></div>`;
  veri.days.forEach((g) => {
    const d = document.createElement("div");
    d.className = "gun-basligi" + (g.date === bugun ? " bugun" : "");
    d.innerHTML = `<div class="ad">${g.dayName}</div><div class="sayi">${g.dayNumber}</div>`;
    el.izgaraBaslik.appendChild(d);
  });

  /* --- tüm gün şeridi --- */
  el.tumgunSerit.innerHTML = `<div class="tumgun-etiket">tüm gün</div>`;
  veri.days.forEach((g) => {
    const hucre = document.createElement("div");
    hucre.className = "tumgun-hucre";
    g.allDay.filter(gorunurMu).forEach((occ) => {
      const blok = document.createElement("div");
      blok.className = "tumgun-blok";
      blok.textContent = occ.title;
      blok.style.background = zemin(occ.color);
      blok.style.borderLeftColor = occ.color;
      blok.onclick = () => panelAc(occ);
      hucre.appendChild(blok);
    });
    el.tumgunSerit.appendChild(hucre);
  });

  /* --- saat sütunu --- */
  el.saatSutunu.innerHTML = "";
  for (let s = 0; s < 24; s++) {
    const e = document.createElement("div");
    e.className = "saat-etiket";
    e.textContent = s === 0 ? "" : `${String(s).padStart(2, "0")}:00`;
    el.saatSutunu.appendChild(e);
  }

  /* --- gün sütunları --- */
  const yukseklik = 24 * 48; // saat başına 48px, CSS'teki --saat-yukseklik ile aynı
  el.gunler.innerHTML = "";
  el.gunler.style.height = `${yukseklik}px`;

  veri.days.forEach((g) => {
    const sutun = document.createElement("div");
    sutun.className = "gun-sutun" + (g.date === bugun ? " bugun" : "");

    for (let s = 1; s < 24; s++) {
      const c = document.createElement("div");
      c.className = "saat-cizgi";
      c.style.top = `${(s / 24) * 100}%`;
      sutun.appendChild(c);
    }

    g.timed.filter(gorunurMu).forEach((occ) => {
      sutun.appendChild(blokYap(occ, g));
    });

    if (g.date === bugun) {
      const simdi = simdiCizgi(g);
      if (simdi) sutun.appendChild(simdi);
    }

    el.gunler.appendChild(sutun);
  });

  ilkKaydir();
}

function blokYap(occ, gun) {
  const ustPct = (occ.startMin / gun.dayMinutes) * 100;
  const yukPct = Math.max(((occ.endMin - occ.startMin) / gun.dayMinutes) * 100, 1.1);
  const genPct = 100 / occ.colCount;

  const blok = document.createElement("div");
  blok.className = "blok";
  if (occ.endMin - occ.startMin <= 35) blok.classList.add("kisa");
  if (occAnahtar(occ) === durum.seciliId) blok.classList.add("secili");

  blok.style.top = `${ustPct}%`;
  blok.style.height = `${yukPct}%`;
  blok.style.left = `calc(${occ.col * genPct}% + 2px)`;
  blok.style.width = `calc(${genPct}% - 4px)`;
  blok.style.background = zemin(occ.color);
  blok.style.borderLeftColor = occ.color;

  const baslik = document.createElement("div");
  baslik.className = "b-baslik";
  baslik.textContent = occ.title;
  blok.appendChild(baslik);

  const saat = document.createElement("div");
  saat.className = "b-saat";
  saat.textContent =
    `${saatBicim(occ.startUtc, occ.tzid)}–${saatBicim(occ.endUtc, occ.tzid)}` +
    (occ.clipped ? " ⇥" : "");
  blok.appendChild(saat);

  if (occ.isOverride) {
    const rozet = document.createElement("div");
    rozet.className = "b-rozet";
    rozet.textContent = "· taşındı";
    blok.appendChild(rozet);
  }

  blok.onclick = () => panelAc(occ);
  return blok;
}

function simdiCizgi(gun) {
  const simdi = new Date();
  const gecen = (simdi.getHours() * 60 + simdi.getMinutes());
  if (gecen < 0 || gecen > gun.dayMinutes) return null;
  const c = document.createElement("div");
  c.className = "simdi-cizgi";
  c.style.top = `${(gecen / gun.dayMinutes) * 100}%`;
  return c;
}

/** İlk çizimde 07:00 civarına kaydır; gece saatleri boşuna yer kaplamasın. */
let kaydirildi = false;
function ilkKaydir() {
  if (kaydirildi) return;
  kaydirildi = true;
  el.kaydirma.scrollTop = (7 / 24) * (24 * 48);
}

/* ---------- etkinlik paneli ---------- */

function panelAc(occ) {
  durum.seciliId = occAnahtar(occ);
  const takvim = durum.veri.calendars.find((c) => c.id === occ.calendarId);

  const satirlar = [];
  const zaman = occ.allDay
    ? tarihBicim(occ.startUtc, occ.tzid)
    : `${tarihBicim(occ.startUtc, occ.tzid)}<br>${saatBicim(occ.startUtc, occ.tzid)} – ${saatBicim(occ.endUtc, occ.tzid)}`;
  satirlar.push(["Zaman", zaman]);

  if (takvim) {
    satirlar.push([
      "Takvim",
      `<span class="p-takvim"><span class="renk-kutu" style="background:${takvim.color}"></span>${takvim.name}</span>`,
    ]);
  }
  if (occ.location) satirlar.push(["Konum", metinKacir(occ.location)]);
  satirlar.push(["Dilim", occ.tzid]);

  const rozetler = [];
  if (occ.allDay) rozetler.push(`<span class="rozet">tüm gün</span>`);
  if (occ.isOverride) rozetler.push(`<span class="rozet override">seriden taşındı</span>`);
  if (occ.clipped) rozetler.push(`<span class="rozet">gece yarısını aşıyor</span>`);
  if (rozetler.length) satirlar.push(["Durum", rozetler.join(" ")]);

  let html = `<div class="p-baslik">${metinKacir(occ.title)}</div>`;
  html += satirlar
    .map(([e, d]) => `<div class="p-satir"><div class="p-etiket">${e}</div><div class="p-deger">${d}</div></div>`)
    .join("");
  if (occ.description) {
    html += `<div class="p-satir"><div class="p-etiket">Açıklama</div><div class="p-deger p-aciklama">${metinKacir(occ.description)}</div></div>`;
  }

  el.panelIcerik.innerHTML = html;
  el.panel.hidden = false;
  ciz();
}

function panelKapat() {
  durum.seciliId = null;
  el.panel.hidden = true;
  ciz();
}

function metinKacir(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

/* ---------- olaylar ---------- */

document.getElementById("onceki").onclick = () => {
  durum.anchor = tarihKaydir(durum.veri ? durum.veri.weekStart : durum.anchor, -7);
  haftaYukle(durum.anchor);
};
document.getElementById("sonraki").onclick = () => {
  durum.anchor = tarihKaydir(durum.veri ? durum.veri.weekStart : durum.anchor, 7);
  haftaYukle(durum.anchor);
};
document.getElementById("bugun").onclick = () => {
  durum.anchor = bugunISO();
  haftaYukle(durum.anchor);
};
el.panelKapat.onclick = panelKapat;

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") panelKapat();
  if (e.key === "ArrowLeft") document.getElementById("onceki").click();
  if (e.key === "ArrowRight") document.getElementById("sonraki").click();
  if (e.key === "t" || e.key === "T") document.getElementById("bugun").click();
});

haftaYukle(durum.anchor);
