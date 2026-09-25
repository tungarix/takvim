/* Takvim ön yüzü.
 *
 * İş bölümü: çakışma yerleşimi core/layout.py'de, gün sınırları ve kırpma
 * ui/presenter.py'de, zaman ayrıştırma core/quickadd.py'de. Burada yalnızca
 * gelen sayıları piksele çeviriyoruz.
 *
 * dayMinutes her gün için ayrı geliyor: DST gününde 1380 veya 1500 olur ve
 * yüzdeleri ona bölmek ızgarayı o günlerde de doğru hizalıyor.
 */

// Varsayılan saat yüksekliği; CANLI değer durum.saatYukseklik'te (Ctrl+Scroll
// değiştirir). CSS'teki --saat-yukseklik bununla EŞİTLENİYOR (ciz() her
// çağrıda yazıyor) -- ikisi elle aynı tutulan iki sabit değil, biri diğerini
// besliyor.
const SAAT_YUKSEKLIK_VARSAYILAN = 48;
const SAAT_YUKSEKLIK_MIN = 24;
const SAAT_YUKSEKLIK_MAKS = 160;
const SAAT_YAKINLASTIR_ADIM = 4; // px/saat, her Ctrl+Scroll notch'unda
const AY_MAKS_BLOK = 3;    // ay hücresinde gösterilecek en fazla etkinlik

const durum = {
  gorunum: "week",
  anchor: bugunISO(),
  veri: null,
  // Arayüz dili: "tr" (varsayılan) | "en". Açılışta `/api/ayarlar`dan okunuyor
  // (`ayarlar.json` → `dil`); `t()` buraya bakıyor, `yerel()` Intl yerini seçiyor.
  dil: "tr",
  secili: null,          // seçili occurrence (panel için)
  takvimGorunur: new Map(),
  kaydirildi: false,
  pano: null,             // Ctrl+C/X ile kopyalanan etkinliğin özeti (yapıştırma için)
  imlecSaat: null,        // fare gün/hafta ızgarasında hangi boş saatin üzerinde ({date, minutes})
  saatYukseklik: SAAT_YUKSEKLIK_VARSAYILAN, // Ctrl+Scroll ile büyür/küçülür
  // Kenar çubuğundaki mini ay takvimi hangi ayı gösteriyor (ISO, ayın 1'i).
  // yukle() her çağrıldığında anchor'ın ayına senkronlanır -- mt-onceki/
  // mt-sonraki bunu yukle() ÇAĞIRMADAN değiştirir, yani ana görünümü
  // etkilemeden ileri geri gezilebiliyor.
  miniAy: bugunISO().slice(0, 7) + "-01",
  // Boş durum ekranının AÇILMASI yalnızca GERÇEK ilk açılışta bir şans
  // buluyor: ciz() ilk kez çalıştığında bu false'a düşüyor, kontrolü bir
  // daha hiç açmıyor -- kullanıcı gezinip boş bir haftaya denk gelse bile
  // "karşılama ekranı" yeniden çıkmasın. KAPANMASI ayrı: bir kez açıldıysa,
  // sonraki her yukle()'de veri artık boş değilse kapatılıyor (kullanıcı
  // "Etkinlik ekle"den bir şey oluşturunca ekranda asılı kalmasın diye).
  ilkYuklemeKaldi: true,
};

const el = (id) => document.getElementById(id);

/* ---------- dil ---------- */

// `i18n.js` (`TR`/`EN`) `index.html`de BUNDAN ÖNCE yükleniyor. `t()` her
// çağrıda aktif dile bakıyor -- dil değişince sayfa zaten yeniden yükleniyor,
// o yüzden önbellek yok.
function t(anahtar, params) {
  const sozluk = durum.dil === "en" ? EN : TR;
  let s = sozluk[anahtar];
  if (s === undefined) s = TR[anahtar];
  if (s === undefined) return anahtar;
  if (Array.isArray(s)) return s;
  if (params && typeof params === "object") {
    for (const [k, v] of Object.entries(params)) {
      s = s.split(`{${k}}`).join(String(v));
    }
  }
  return s;
}

// Tarih/saat BİÇİMİ için yer: en-GB (24 saat, gün-önce sırası) TR'ye en yakın
// İngilizce yer; en-US 12 saat + ay-önce yapıyor. ISO ÜRETEN `en-CA`/`en-GB`
// çağrıları (`yerelTarihISO`/`yerelSaatISO`) dile DEĞİL, makine biçimine bağlı,
// onlara dokunulmuyor.
function yerel() {
  return durum.dil === "en" ? "en-GB" : "tr-TR";
}

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
  return new Intl.DateTimeFormat(yerel(), {
    hour: "2-digit", minute: "2-digit", hour12: false, timeZone: tzid,
  }).format(new Date(iso));
}

function tarihBicim(iso, tzid) {
  return new Intl.DateTimeFormat(yerel(), {
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
    throw hataUret(govde, yanit.status);
  }
  return govde;
}

/* Sunucu hatasını DİLDE mesaja çevirir.

 * Sunucu `{"error": <Türkçe>, "error_code": <kod>, "error_param": {...}}`
 * dönüyor (`error` eski sözleşme, aynen duruyor). Kodu BİLİYORSAK `t()` ile
 * çeviriyoruz; bilmiyorsak (kodsuz eski yol, ağ hatası) ham metni gösteriyoruz
 * -- çevrilemeyen bir hata, hiç gösterilmeyen bir hatadan iyidir. Burası TEK
 * yer olduğu için her `bildir(hata.message, true)` çağrısı otomatik çeviriyor,
 * çağrı yerlerine dokunmaya gerek yok. */
function hataUret(govde, status) {
  const kod = govde && govde.error_code;
  if (kod && TR[`hata_${kod}`] !== undefined) {
    const param = (govde && govde.error_param) || {};
    const hata = new Error(t(`hata_${kod}`, typeof param === "object" ? param : { deger: param }));
    hata.code = kod;
    return hata;
  }
  const ham = (govde && govde.error) || t("hata_sunucu", { kod: status });
  const hata = new Error(ham);
  if (kod) hata.code = kod;
  return hata;
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
 * yerde -- üç ayrı kopya olsaydı biri düzeltilip diğerleri unutulurdu.
 *
 * `ucuncu`: isteğe bağlı üçüncü düğme ({etiket, anahtar}) -- şimdilik tek
 * kullanıcısı çakışma onayı (Takvim Arayuz.pdf §1f: "Yine de kaydet / Saati
 * değiştir / Vazgeç"). Tıklanınca formdaki DEĞERLER kaybolmadan (`oku()` yine
 * çağrılıyor) sonuca `{[anahtar]: true}` ekleniyor -- çağıran taraf hangi
 * düğmeye basıldığını böyle ayırt ediyor. */
function modalAc({ baslik, metin = "", onay = t("tamam"), tehlike = false, kur, oku, iptalDegeri, ucuncu = null, genislik = null }) {
  const perde = el("perde");
  const govde = el("modal-alanlar");
  const tamam = el("modal-tamam");
  const iptal = el("modal-iptal");
  const ucuncuDugme = el("modal-ucuncu");
  const oncekiOdak = document.activeElement;

  el("modal-baslik").textContent = baslik;
  el("modal-metin").textContent = metin;
  govde.innerHTML = "";
  govde.hidden = true;
  tamam.textContent = onay;
  tamam.classList.toggle("tehlike", tehlike);
  tamam.classList.toggle("birincil", !tehlike);
  ucuncuDugme.hidden = !ucuncu;
  if (ucuncu) ucuncuDugme.textContent = ucuncu.etiket;
  // Varsayılan 420px; çok alanlı ya da liste içeren kutular (yeni etkinlik
  // çakışması, yedekler) Takvim Arayuz.pdf §1j'deki 460/540px'i burada geçer.
  el("modal").style.width = genislik ? `min(${genislik}px, calc(100vw - 48px))` : "";
  perde.hidden = false;

  return new Promise((cozumle) => {
    const bitir = (deger) => {
      perde.hidden = true;
      perde.removeEventListener("click", perdeTik);
      document.removeEventListener("keydown", tus, true);
      tamam.onclick = null;
      iptal.onclick = null;
      ucuncuDugme.onclick = null;
      modalDurum = null;
      // Odağı geri ver: kutu kapanınca klavye kısayolları yine çalışsın.
      if (oncekiOdak && oncekiOdak.focus) oncekiOdak.focus();
      cozumle(deger);
    };
    // `kur`e de veriliyor: yedekler listesi gibi satır başına kendi eylemi
    // olan içerikler (bkz. yedekleriAc), tamam/iptal'i beklemeden kutuyu
    // doğrudan bu değerle kapatabilsin.
    const ilkOdak = kur ? kur(govde, bitir) : null;
    govde.hidden = govde.children.length === 0;
    (ilkOdak || tamam).focus();
    if (ilkOdak && ilkOdak.select) ilkOdak.select();

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
      } else if (e.key === "Tab") {
        // Odak kutunun DIŞINA kaçmasın: `perde` tıklamayla kapatıyor ama
        // Tab'ı hiç sınırlamıyor -- sınırlamadan arkadaki (perdenin altında
        // görsel olarak gizli) düğmelere geçilebiliyordu; klavye kullanıcısı
        // ekranda görünmeyen bir yere odaklanıp "neredeyim" diye kalıyordu.
        const odaklanabilirler = Array.from(
          el("modal").querySelectorAll('button, input, textarea, select, [tabindex]:not([tabindex="-1"])'),
        ).filter((n) => !n.disabled && n.offsetParent !== null);
        if (odaklanabilirler.length === 0) return;
        const ilkNode = odaklanabilirler[0];
        const sonNode = odaklanabilirler[odaklanabilirler.length - 1];
        if (e.shiftKey && document.activeElement === ilkNode) {
          e.preventDefault(); sonNode.focus();
        } else if (!e.shiftKey && document.activeElement === sonNode) {
          e.preventDefault(); ilkNode.focus();
        }
      }
    };

    modalDurum = { kapat: () => bitir(iptalDegeri) };
    perde.addEventListener("click", perdeTik);
    document.addEventListener("keydown", tus, true);
    tamam.onclick = () => bitir(oku());
    iptal.onclick = () => bitir(iptalDegeri);
    if (ucuncu) {
      ucuncuDugme.onclick = () => bitir({ ...(oku ? oku() : {}), [ucuncu.anahtar]: true });
    }
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
function onayla(baslik, metin, onay = t("tamam"), tehlike = false) {
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
function modalForm(baslik, metin, alanlar, onay = t("kaydet"), ucuncu = null, genislik = null) {
  const girdiler = {};
  return modalAc({
    baslik,
    metin,
    onay,
    iptalDegeri: null,
    ucuncu,
    genislik,
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

// Ekran okuyucu bildirim kutusunun `hidden` değişimini KENDİLİĞİNDEN fark
// etmiyor -- canlı bölge (aria-live) olmadan "Etkinlik eklendi" ya da
// "Veri alınamadı" gibi mesajlar yalnızca görsel kalıyor, klavye/ekran
// okuyucu kullanan biri ne olduğunu hiç duymuyor. `atomic` olmadan da
// yalnızca DEĞİŞEN düğüm (ör. sonradan eklenen "Geri al" düğmesi) okunur,
// mesaj metni değil.
el("bildirim").setAttribute("aria-live", "polite");
el("bildirim").setAttribute("aria-atomic", "true");

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
    dugme.textContent = t("geri_al");
    dugme.onclick = () => { kutu.hidden = true; geriAl(); };
    kutu.appendChild(dugme);
  }

  kutu.hidden = false;
  clearTimeout(bildirimZaman);
  bildirimZaman = setTimeout(() => { kutu.hidden = true; }, hata ? 7000 : geriAl ? 10000 : 3500);
}

async function yukle() {
  // Mini takvim ana görünümü İZLİYOR: anchor'ı değiştiren her yol (gezinme,
  // Bugün, arama sonucuna tıklama...) buraya çıkıyor, o yüzden tek yerde
  // senkron yetiyor. Mini takvimin KENDİ ay gezinmesi (mt-onceki/sonraki)
  // yukle()'yi hiç çağırmıyor, o yüzden burada ezilmiyor.
  durum.miniAy = durum.anchor.slice(0, 7) + "-01";
  try {
    durum.veri = await istek(`/api/${durum.gorunum}?date=${durum.anchor}`);
    durum.veri.calendars.forEach((c) => {
      if (!durum.takvimGorunur.has(c.id)) durum.takvimGorunur.set(c.id, c.visible);
    });
    ciz();
  } catch (hata) {
    bildir(t("veri_alinamadi", { ayrinti: hata.message }), true);
  }
}

/* ---------- çizim ---------- */

function gorunurMu(occ) {
  return durum.takvimGorunur.get(occ.calendarId) !== false;
}

function ciz() {
  const veri = durum.veri;
  if (!veri) return;

  // Yapıştırma hedefi (imlecSaat) her yeniden çizimde GEÇERSİZ sayılıyor:
  // görünüm ya da tarih değişmiş olabilir ve fare hiç kıpırdamamış olsa
  // bile eski hedef artık ekranda görünmeyen/anlamsız bir günü işaret
  // edebilir (örn. "h" ile hafta görünümündeyken fareyi kıpırdatmadan "a"ya
  // basıp ay görünümüne geçmek). Geçerliyse zaten ilk mousemove'da yeniden
  // dolacak; sessizce yanlış bir güne yapıştırmaktansa Ctrl+V'nin "hedef
  // yok" demesi çok daha güvenli.
  durum.imlecSaat = null;

  el("baslik").textContent = veri.label;
  el("tz-etiketi-tam").textContent = veri.tzid;
  // Ray modunda (kenar çubuğu 56px'e inince) tam IANA adı sığmıyor; son
  // parçadan (şehir) kaba bir kısaltma -- kusursuz değil ama araç ipucu
  // (title) her zaman tam adı taşıyor, bilgi kaybolmuyor.
  const sehir = veri.tzid.split("/").pop().replace(/_/g, " ");
  el("tz-etiketi-kisa").textContent = sehir.slice(0, 3).toUpperCase();
  el("tz-etiketi-kisa").title = veri.tzid;
  takvimleriCiz();
  miniAyCiz();
  bosDurumKontrol(veri);

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
      `<button type="button" class="takvim-dugme" data-is="duzenle" title="${kacir(t("duzenle"))}">✎</button>` +
      `<button type="button" class="takvim-dugme" data-is="sil" title="${kacir(t("sil"))}">×</button>`;
    li.querySelector(".renk-kutu").style.background = c.color;
    li.querySelector(".takvim-ad").textContent = c.name;
    li.title = gorunur ? t("gizle") : t("goster");
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

/* ---------- boş durum (yalnızca gerçek ilk açılış) ---------- */

/** Hafta/gün `days[i]` = {timed,allDay}; ay `days[i]` = {events}. */
function veriBosMu(veri) {
  if (!veri.days) return true;
  return veri.days.every((g) =>
    (g.timed || []).length === 0 &&
    (g.allDay || []).length === 0 &&
    (g.events || []).length === 0
  );
}

function bosDurumKontrol(veri) {
  if (!durum.ilkYuklemeKaldi) {
    // Karar zaten verildi (açıldı ya da açılmadı). Açıldıysa ve veri artık
    // boş değilse (kullanıcı bir şey ekledi/içe aktardı) kapatıyoruz;
    // aksi hâlde dokunmuyoruz -- boş bir haftaya gezinmek onu KAPATMAZ.
    if (!el("bos-durum").hidden && !veriBosMu(veri)) el("bos-durum").hidden = true;
    return;
  }
  durum.ilkYuklemeKaldi = false;
  // "Gerçek ilk açılış" ikili sinyal: tek, varsayılan adlı takvim VE
  // görünen pencerede hiç etkinlik yok. Yalnızca ikinciye bakmak, aktif
  // bir kullanıcının sakin bir haftaya denk gelmesini "kurulum" sanardı.
  // Ad dile göre ("Kişisel"/"Personal"), ikisi de varsayılan adı.
  const ilkKurulumGibi =
    veri.calendars.length === 1 &&
    (veri.calendars[0].name === "Kişisel" || veri.calendars[0].name === "Personal");
  el("bos-durum").hidden = !(ilkKurulumGibi && veriBosMu(veri));
}

/* ---------- mini ay takvimi (kenar çubuğu) ---------- */

/* Saf tarih aritmetiği -- sunucuya hiç sormuyor (`veri.days` gibi bir
 * occurrence listesi gerekmiyor, yalnızca hangi günün hangi haftanın
 * hangi sütununa düştüğü lazım). `durum.miniAy` ayın 1'i, ISO. */
function miniAyCiz() {
  const [yil, ay] = durum.miniAy.split("-").map(Number);
  el("mt-ay-adi").textContent = new Date(Date.UTC(yil, ay - 1, 1))
    .toLocaleDateString(yerel(), { month: "long", year: "numeric", timeZone: "UTC" });

  const kap = el("mt-gunler");
  kap.innerHTML = "";
  // Gün harfleri ve tam adlar dile göre (`i18n.js`); tek harf çakışması her
  // iki dilde de var (Salı/Perşembe, Tue/Thu), title her zaman tam adı taşıyor.
  const harfler = t("gun_harfleri");
  const gunAdlari = t("gun_adlari");
  harfler.forEach((h, i) => {
    const e = document.createElement("div");
    e.className = "mt-gun-adi";
    e.textContent = h;
    // Salı/Cuma ile Perşembe/Cumartesi tek harfte ayırt edilemiyor;
    // ekran okuyucu tam adı duysun diye.
    e.title = gunAdlari[i];
    kap.appendChild(e);
  });

  const ayBasi = new Date(Date.UTC(yil, ay - 1, 1));
  const haftaGunu = (ayBasi.getUTCDay() + 6) % 7; // Pazartesi=0 tabanlı
  const izgaraBasi = new Date(ayBasi);
  izgaraBasi.setUTCDate(izgaraBasi.getUTCDate() - haftaGunu);

  const bugun = bugunISO();
  for (let i = 0; i < 42; i++) {
    const g = new Date(izgaraBasi);
    g.setUTCDate(g.getUTCDate() + i);
    const iso = g.toISOString().slice(0, 10);
    const b = document.createElement("button");
    b.type = "button";
    b.className = "mt-gun" +
      (iso.slice(0, 7) !== durum.miniAy.slice(0, 7) ? " mt-disarida" : "") +
      (iso === bugun ? " mt-bugun" : "") +
      (iso === durum.anchor ? " mt-secili" : "");
    b.textContent = String(g.getUTCDate());
    b.title = tarihBicim(g.toISOString(), "UTC");
    // Ay dışı bir güne tıklamak o ayı da açsın -- Google Calendar'daki gibi;
    // yukle() zaten miniAy'i yeni anchor'ın ayına senkronluyor.
    b.onclick = () => { durum.anchor = iso; yukle(); };
    kap.appendChild(b);
  }
}

el("mt-onceki").onclick = () => { durum.miniAy = ayKaydir(durum.miniAy, -1); miniAyCiz(); };
el("mt-sonraki").onclick = () => { durum.miniAy = ayKaydir(durum.miniAy, 1); miniAyCiz(); };

/* ---------- takvim yönetimi ---------- */

/* Bu üçü uzun süre yoktu: kullanıcı ilk açılışta oluşan tek "Kişisel"
 * takvimine mahkûmdu. Renk ve gizle/göster özellikleri de o yüzden pratikte
 * ölüydü -- gizlenecek ikinci bir takvim olmuyordu. */

async function takvimEkle() {
  const s = await modalForm(
    t("yeni_takvim"),
    "",
    [
      { ad: "ad", etiket: t("ad"), tur: "metin", deger: "" },
      { ad: "renk", etiket: t("renk"), tur: "renk", deger: "#3b82f6" },
    ],
    t("olustur"),
  );
  if (s === null || !s.ad.trim()) return;
  await eylem(
    () => istek("/api/calendars", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: s.ad.trim(), color: s.renk }),
    }),
    t("takvim_eklendi", { ad: s.ad.trim() }),
  );
}

async function takvimDuzenle(c) {
  const s = await modalForm(
    t("takvim_duzenle"),
    "",
    [
      { ad: "ad", etiket: t("ad"), tur: "metin", deger: c.name },
      { ad: "renk", etiket: t("renk"), tur: "renk", deger: c.color },
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
    t("takvim_guncellendi"),
  );
}

async function takvimSil(c) {
  const tamam = await onayla(
    t("takvim_sil_baslik"),
    t("takvim_sil_metin", { ad: c.name }),
    t("takvim_sil_baslik"),
    true,
  );
  if (!tamam) return;
  await eylem(
    () => istek(`/api/calendars/${c.id}`, { method: "DELETE" }),
    t("takvim_silindi", { ad: c.name }),
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

  seritKap.innerHTML = `<div class="tumgun-etiket">${kacir(t("rozet_tumgun"))}</div>`;
  veri.days.forEach((g) => {
    const hucre = document.createElement("div");
    hucre.className = "tumgun-hucre";
    g.allDay.filter(gorunurMu).forEach((occ) => {
      const blok = document.createElement("div");
      blok.className = "tumgun-blok";
      blok.textContent = occ.title;
      // Şerit dar olunca başlık CSS ile kırpılıyor (ellipsis); tam metin
      // araç ipucunda kalsın.
      blok.title = occ.title;
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
  gunlerKap.style.height = `${24 * durum.saatYukseklik}px`;
  // Saat etiketleri (.saat-etiket) yüksekliğini CSS değişkeninden okuyor;
  // ızgara ile aynı ölçekte kalsınlar diye burada senkronize ediyoruz.
  document.documentElement.style.setProperty("--saat-yukseklik", `${durum.saatYukseklik}px`);

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

    // Ctrl+V'nin hedefi: fareyle üzerinde durulan boş saat. Tıklama değil
    // TAKİP -- kullanıcı imleci nereye götürürse yapıştırma da oraya gider,
    // eski bir tıklamayı "hatırlamak" gerekmiyor. Bir etkinliğin üzerindeyken
    // hedef yok (izgaraTik'teki ".blok" kaçışıyla aynı mantık).
    sutun.addEventListener("mousemove", (e) => {
      if (e.target.closest(".blok")) { durum.imlecSaat = null; return; }
      durum.imlecSaat = { date: g.date, dayMinutes: g.dayMinutes, minutes: sutunDakika(e, sutun, g) };
    });
    sutun.addEventListener("mouseleave", () => { durum.imlecSaat = null; });

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
    el("izgara-kaydirma").scrollTop = (7 / 24) * 24 * durum.saatYukseklik;
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

  // b-konum HER ZAMAN markup'ta, ama yalnızca çok yakınlaştırıldığında
  // (>=100px/saat) CSS ile gösteriliyor -- bkz. "1i" (Ctrl+Scroll uçları,
  // Takvim Arayuz.pdf): 24px'te başlık+saat, 160px'te +konum/takvim.
  blok.innerHTML =
    `<div class="b-baslik">${kacir(occ.title)}</div>` +
    `<div class="b-saat">${saatBicim(occ.startUtc, occ.tzid)}–${saatBicim(occ.endUtc, occ.tzid)}` +
    `${occ.clipped ? " ⇥" : ""}</div>` +
    (occ.location ? `<div class="b-konum">${kacir(occ.location)}</div>` : "") +
    (occ.isOverride ? `<div class="b-rozet">${kacir(t("rozet_tasindi_kisa"))}</div>` : "");

  // Sıkışık yakınlaştırmada ya da kısa etkinlikte başlık CSS ile kırpılabiliyor
  // (.kisa, [data-yogunluk]); imleci üzerine getirince tam başlık ve saat yine
  // de görünsün diye tarayıcının kendi araç ipucuna (title) da yazıyoruz.
  blok.title = `${occ.title} · ${saatBicim(occ.startUtc, occ.tzid)}–${saatBicim(occ.endUtc, occ.tzid)}`;

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

// Oluştururken yarım saate yuvarlıyoruz. Sürüklemedeki SNAP'ten (5 dk) daha
// kaba, çünkü burada niyet "şu civarda bir şey" -- saati sonradan
// sürükleyerek ince ayarlamak zaten mümkün.
const OLUSTUR_SNAP = 30;
const OLUSTUR_SURE = 60; // dakika

/** Fare/işaretçi konumunu sütun içinde yarım saate yuvarlanmış dakikaya çevirir.
 * Hem tıklayıp oluşturma (izgaraTik) hem yapıştırma hedefi takibi bunu kullanıyor
 * -- ikisi AYNI ızgarada AYNI yuvarlamayı görmeli, yoksa fareyle durduğun yerle
 * tıklayınca açılan saat birbirini tutmaz. */
function sutunDakika(e, sutun, gun) {
  const kutu = sutun.getBoundingClientRect();
  const oran = (e.clientY - kutu.top) / kutu.height;
  let dakika = Math.floor((oran * gun.dayMinutes) / OLUSTUR_SNAP) * OLUSTUR_SNAP;
  return Math.max(0, Math.min(dakika, gun.dayMinutes - OLUSTUR_SNAP));
}

async function izgaraTik(e, sutun, gun) {
  // Etkinliğin üstüne tıklandıysa burası karışmasın: panel açılacak.
  if (e.target.closest(".blok")) return;
  // Sürüklemeden SONRA da bir tık olayı geliyor; onu oluşturma sanmayalım.
  if (surukleme.tasindi || tumgunSurukleme.tasindi) return;

  const dakika = sutunDakika(e, sutun, gun);

  /* Panoda bir şey varsa TIKLAMA = YAPIŞTIRMA: "Yeni etkinlik" kutusu
   * araya girmiyor, kullanıcı tam tıkladığı saate düşen sonucu görüyor.
   * Ctrl+V (imleci götür, tuşa bas) hâlâ AYRICA çalışıyor -- bu yalnızca
   * "kopyaladıktan sonra tıklamak da yapıştırsın" isteğini karşılıyor.
   * TEK SEFERLİK: panoyaYaz başarılı yazımdan sonra durum.pano'yu kendi
   * temizliyor, bir sonraki tıklama otomatik olarak normal "yeni etkinlik"
   * akışına döner -- art arda tıklayınca sonsuza kadar aynı etkinliğin
   * kopyalanması kafa karıştırıyordu (kullanıcı bildirimi). Tekrar
   * yapıştırmak için yeniden kopyalamak (Ctrl+C) gerekir. */
  if (durum.pano) {
    panoyaYaz(gun.date, dakika);
    return;
  }

  const bitis = Math.min(dakika + OLUSTUR_SURE, gun.dayMinutes);

  /* Çakışma uyarısı ENGELLEMEZ, BİLGİLENDİRİR: kullanıcı saati bilerek
   * üst üste koyuyor olabilir. Tekrarlı seçimde yalnızca İLK aralık
   * denetleniyor; serinin devamı kullanıcının sorumluluğunda. */
  let uyari = "";
  try {
    const c = await istek(`/api/conflicts?date=${gun.date}&start=${dakika}&end=${bitis}`);
    if (c.conflicts.length) {
      uyari = t("cakisma_onek", {
        liste: c.conflicts.map((x) =>
          `${x.title} (${saatBicim(x.startUtc, x.tzid)}–${saatBicim(x.endUtc, x.tzid)})`
        ).join(", "),
      });
    }
  } catch {
    // Uyarı alınamazsa oluşturma engellenmez; sessiz devam.
  }

  const s = await modalForm(
    t("yeni_etkinlik"),
    uyari + `${gun.dayNumber} ${gun.monthName} ${gun.dayName} · ${dakikaSaat(dakika)}–${dakikaSaat(bitis)}`,
    [
      { ad: "baslik", etiket: t("baslik_etiket"), tur: "metin", deger: "" },
      /* Tekrar KAPALI bir liste: tekrar motoru baştan beri vardı ama
       * kullanıcının onu söyleyebileceği hiçbir yer yoktu; RFC 5545 kuralı
       * yazdırmak da bu uygulamanın işi değil. */
      /* Hangi takvime yazılacağı SORULUYOR: birden çok takvim olduğunda
       * sunucunun seçtiği varsayılan her zaman kullanıcının istediği olmuyor. */
      {
        ad: "takvim",
        etiket: t("p_takvim"),
        tur: "secim",
        deger: String((durum.veri.calendars.find((c) => durum.takvimGorunur.get(c.id) !== false)
          || durum.veri.calendars[0] || {}).id || ""),
        secenekler: durum.veri.calendars.map((c) => ({ deger: String(c.id), etiket: c.name })),
      },
      {
        ad: "tekrar",
        etiket: t("tekrar_etiket"),
        tur: "secim",
        deger: "yok",
        secenekler: [
          { deger: "yok", etiket: t("tekrar_yok") },
          { deger: "gunluk", etiket: t("tekrar_gunluk") },
          { deger: "haftalik", etiket: t("tekrar_haftalik", { gun: gun.dayName }) },
          { deger: "haftaici", etiket: t("tekrar_haftaici") },
          { deger: "aylik", etiket: t("tekrar_aylik") },
        ],
      },
    ],
    t("ekle"),
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
    t("eklendi_tarihli", {
      baslik: ad, gun: gun.dayNumber, ay: gun.monthName, saat: dakikaSaat(dakika),
    }),
  );
}

/* ---------- sürükle-bırak ---------- */

/* Hedef, SUNUCUYA tarih + gün başından dakika olarak gönderilir. JS'te
 * "şu IANA diliminde şu duvar saati" kurmak güvenilir değil; sunucuda
 * from_wall_clock zaten var ve test edilmiş. Izgara da zaten yerel dakika ile
 * çalıştığı için elimizdeki iki değer doğrudan bunlar.
 */

const SNAP = 5; // dakika -- eskiden 15'ti, kullanıcı isteğiyle inceltildi
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
        ? t("sure_degisti", {
            baslik: occ.title,
            aralik: `${dakikaSaat(occ.startMin)}–${dakikaSaat(hedefBitisDakika)}`,
          })
        : t("tasindi", { baslik: occ.title, hedef: dakikaSaat(hedefDakika) }),
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
    bildir(t("tasindi", { baslik: occ.title, hedef: hedefTarih }));
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
      // <button>: eskiden <div onclick>'ti -- yalnızca fareyle açılabiliyordu.
      // Ay hücresi dar olduğu için başlık sık sık CSS ile kırpılıyor, o yüzden
      // tam metni ayrıca title'a (araç ipucu) da yazıyoruz.
      const blok = document.createElement("button");
      blok.type = "button";
      blok.className = "ay-blok";
      const metin = occ.allDay
        ? occ.title
        : `${saatBicim(occ.startUtc, occ.tzid)} ${occ.title}`;
      blok.textContent = metin;
      blok.title = metin;
      blok.style.background = zemin(occ.color);
      blok.style.borderLeftColor = occ.color;
      blok.onclick = (e) => { e.stopPropagation(); panelAc(occ); };
      hucre.appendChild(blok);
    });

    if (gorunurler.length > AY_MAKS_BLOK) {
      // <button>: "Gün görünümünde aç" (gl-gun-dugme) gibi klavyeyle de
      // erişilebilsin -- fare olayının clientX/clientY'si yerine düğmenin
      // KENDİ konumu kullanılıyor (bkz. gunListesiAc), o yüzden burada olay
      // değil düğmenin kendisi veriliyor.
      const daha = document.createElement("button");
      daha.type = "button";
      daha.className = "ay-daha";
      daha.textContent = t("daha", { n: gorunurler.length - AY_MAKS_BLOK });
      daha.onclick = (e) => { e.stopPropagation(); gunListesiAc(g, gorunurler, daha); };
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

/** `ankraj`: kutuyu konumlandırmak için kullanılan eleman ("+N daha" düğmesi).
 * Eskiden tıklama olayının clientX/clientY'si kullanılıyordu; bu, düğme artık
 * klavyeyle (Enter/Space) de tetiklenebildiği için yanlıştı -- klavye
 * kaynaklı bir `click` olayında clientX/clientY 0'dır ve kutu ekranın sol üst
 * köşesine fırlardı. Düğmenin KENDİ konumu tetikleme yönteminden bağımsız. */
function gunListesiAc(gun, occurrences, ankraj) {
  gunListesiKapat();

  const kutu = document.createElement("div");
  kutu.className = "gun-listesi";
  kutu.id = "gun-listesi";

  const baslik = document.createElement("div");
  baslik.className = "gl-baslik";
  baslik.textContent = new Intl.DateTimeFormat(yerel(), {
    weekday: "long", day: "numeric", month: "long",
  }).format(new Date(`${gun.date}T12:00:00`));
  kutu.appendChild(baslik);

  occurrences.forEach((occ) => {
    // <button>: eskiden <div onclick>'ti, yalnızca fareyle açılabiliyordu --
    // "Gün görünümünde aç" zaten düğmeydi, satırlar da aynı klavye erişimini
    // hak ediyor.
    const satir = document.createElement("button");
    satir.type = "button";
    satir.className = "gl-satir";
    satir.style.borderLeftColor = occ.color;
    satir.style.background = zemin(occ.color);
    const metin = occ.allDay
      ? occ.title
      : `${saatBicim(occ.startUtc, occ.tzid)} ${occ.title}`;
    satir.textContent = metin;
    satir.title = metin;
    satir.onclick = () => { gunListesiKapat(); panelAc(occ); };
    kutu.appendChild(satir);
  });

  const gunDugme = document.createElement("button");
  gunDugme.type = "button";
  gunDugme.className = "gl-gun-dugme";
  gunDugme.textContent = t("gun_gorunumunde_ac");
  gunDugme.onclick = () => {
    gunListesiKapat();
    durum.gorunum = "day";
    durum.anchor = gun.date;
    yukle();
  };
  kutu.appendChild(gunDugme);

  document.body.appendChild(kutu);

  // Ekran dışına taşmasın; "+N daha" düğmesinin hemen altına açılır.
  const ankrajKutu = ankraj.getBoundingClientRect();
  const k = kutu.getBoundingClientRect();
  const x = Math.min(ankrajKutu.left, window.innerWidth - k.width - 12);
  const y = Math.min(ankrajKutu.bottom + 4, window.innerHeight - k.height - 12);
  kutu.style.left = `${Math.max(8, x)}px`;
  kutu.style.top = `${Math.max(8, y)}px`;

  // Odağı içeri taşı: modalAc de aynısını yapıyor (bkz. orada `ilkOdak`) --
  // klavyeyle (Enter) açan biri odağın "+N daha" düğmesinde kalıp kutunun
  // tab sırasında nerede olduğunu aramak zorunda kalmasın.
  const ilkOdak = kutu.querySelector(".gl-satir, .gl-gun-dugme");
  if (ilkOdak) ilkOdak.focus();

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
    t("p_zaman"),
    occ.allDay
      ? tarihBicim(occ.startUtc, occ.tzid)
      : `${tarihBicim(occ.startUtc, occ.tzid)}<br>${saatBicim(occ.startUtc, occ.tzid)} – ${saatBicim(occ.endUtc, occ.tzid)}`,
  ]);
  if (takvim) {
    satirlar.push([
      t("p_takvim"),
      `<span class="p-takvim"><span class="renk-kutu" style="background:${takvim.color}"></span>${kacir(takvim.name)}</span>`,
    ]);
  }
  if (occ.location) satirlar.push([t("p_konum"), kacir(occ.location)]);
  satirlar.push([t("p_dilim"), kacir(occ.tzid)]);

  const rozetler = [];
  if (occ.allDay) rozetler.push(`<span class="rozet">${kacir(t("rozet_tumgun"))}</span>`);
  if (occ.isOverride) rozetler.push(`<span class="rozet override">${kacir(t("rozet_tasindi"))}</span>`);
  if (occ.clipped) rozetler.push(`<span class="rozet">${kacir(t("rozet_gece"))}</span>`);
  if (rozetler.length) satirlar.push([t("p_durum"), rozetler.join(" ")]);

  if (occ.reminders && occ.reminders.length) {
    satirlar.push([
      t("p_hatirlatici"),
      occ.reminders
        .map((r) => `<span class="rozet">${kacir(hatirlaticiMetni(r.minutesBefore))}</span>`)
        .join(" "),
    ]);
  }

  let html = `<div class="p-baslik">${kacir(occ.title)}</div>`;
  html += satirlar
    .map(([e, d]) => `<div class="p-satir"><div class="p-etiket">${e}</div><div class="p-deger">${d}</div></div>`)
    .join("");
  if (occ.description) {
    html += `<div class="p-satir"><div class="p-etiket">${kacir(t("p_aciklama"))}</div><div class="p-deger p-aciklama">${kacir(occ.description)}</div></div>`;
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
    { ad: "baslik", etiket: t("baslik_etiket"), tur: "metin", deger: occ.title },
    { ad: "tarih", etiket: t("tarih_etiket"), tur: "tarih", deger: eskiTarih },
  ];
  if (!occ.allDay) {
    alanlar.push(
      { ad: "baslangic", etiket: t("baslangic"), tur: "saat", deger: eskiBas, dar: true },
      { ad: "bitis", etiket: t("bitis"), tur: "saat", deger: eskiBit, dar: true },
    );
  }
  alanlar.push(
    { ad: "konum", etiket: t("p_konum"), tur: "metin", deger: occ.location || "" },
    { ad: "aciklama", etiket: t("p_aciklama"), tur: "uzunmetin", deger: occ.description || "" },
  );

  const s = await modalForm(
    t("etkinlik_duzenle"),
    occ.recurring
      ? t("etkinlik_duzenle_aciklama")
      : "",
    alanlar,
  );
  if (s === null) return;

  const yeniBaslik = (s.baslik || "").trim();
  if (!yeniBaslik) {
    bildir(t("istemci_baslik_bos"), true);
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
  }, t("etkinlik_guncellendi"));
}

/** Tekrarlıda bu örneği iptal eder, tekrarsızda etkinliği SİLER. */
async function ornegiSil(occ) {
  const tamam = await onayla(
    occ.recurring ? t("sil_ornek_baslik") : t("sil_etkinlik_baslik"),
    occ.recurring
      ? t("sil_ornek_metin", { baslik: occ.title })
      : t("sil_etkinlik_metin", { baslik: occ.title }),
    t("sil"),
    true,
  );
  if (!tamam) return;
  await eylem(
    () => istek("/api/occurrences/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ eventId: occ.eventId, originalStartUtc: occ.originalStartUtc }),
    }),
    occ.recurring ? t("ornek_silindi") : t("silindi"),
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
      t("geri_alindi"),
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
  }, t("geri_alindi"));
}

/* ---------- pano: kopyala / kes / yapıştır / çoğalt / geri al ---------- */

/* Yapıştırılan kopya HER ZAMAN tekrarsız TEK bir etkinlik -- kaynak
 * tekrarlıysa bile. "Boş saate tıkla" akışı zaten böyle çalışıyor (tekrar
 * seçimi kullanıcıya soruluyor, biz onun yerine karar vermiyoruz) ve
 * yapıştırmanın "bu seriye bir örnek daha ekle" sanılması daha kötü bir
 * yanlış anlaşılma olurdu.
 *
 * Tüm gün etkinlikler şimdilik KAPSAM DIŞI: "boş saate tıkla" akışının süre
 * birimi dakika, tüm gün etkinliğinki gün -- ikisini tek bir pano nesnesinde
 * doğru taşımak ayrı bir iş, burada yarım yapıp yanlış süreyle sessizce
 * yapıştırmaktansa açıkça reddetmek daha güvenli. */
function panoyaKopyala(occ) {
  if (occ.allDay) {
    bildir(t("tumgun_kopyalanamaz"), true);
    return false;
  }
  durum.pano = {
    title: occ.title,
    location: occ.location || "",
    description: occ.description || "",
    calendarId: occ.calendarId,
    durationMin: Math.round((new Date(occ.endUtc) - new Date(occ.startUtc)) / 60000),
    reminders: (occ.reminders || []).map((r) => r.minutesBefore),
  };
  return true;
}

function kopyala() {
  if (!durum.secili) { bildir(t("kopya_sec"), true); return; }
  if (panoyaKopyala(durum.secili)) {
    bildir(t("kopyalandi", { baslik: durum.secili.title }));
  }
}

/* Kes = kopyala + sil. Silme kısmı için YENİ bir yol AÇMIYORUZ: aynı
 * ornegiSil çağrılıyor, yani aynı onay kutusu ve aynı "Geri al" zaten var.
 * Seri kesme yok (Shift+Ctrl+X gibi bir şey de) -- yapıştırma zaten hep tek
 * örnek ürettiği için "seriyi kes" kavramının karşılığı olmazdı. */
function kes() {
  if (!durum.secili) { bildir(t("kes_sec"), true); return; }
  if (!panoyaKopyala(durum.secili)) return;
  ornegiSil(durum.secili);
}

/** Panodaki etkinliği verilen tarih/dakikaya yazar; "Geri al" yeni kaydı siler. */
async function panoyaYaz(tarih, baslangicDk) {
  const p = durum.pano;
  const bitisDk = Math.min(baslangicDk + p.durationMin, 48 * 60);
  let yeniId = null;
  await eylem(
    async () => {
      const yanit = await istek("/api/events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: p.title, date: tarih, minutes: baslangicDk, endMinutes: bitisDk,
          calendarId: p.calendarId,
        }),
      });
      yeniId = yanit.event.id;
      if (p.location || p.description) {
        await istek(`/api/events/${yeniId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ location: p.location, description: p.description }),
        });
      }
      for (const dk of p.reminders) {
        await istek(`/api/events/${yeniId}/reminders`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ minutesBefore: dk }),
        });
      }
      // Yapıştırma TEK SEFERLİK: başarılı yazımdan sonra pano temizlenir,
      // bir sonraki tıklama normal "yeni etkinlik" akışına döner. Tekrar
      // yapıştırmak için yeniden kopyalamak (Ctrl+C) gerekir. İstek
      // başarısız olursa (yukarıda fırlar, eylem() yakalar) pano dolu
      // kalır -- kullanıcı kopyaladığını kaybetmesin.
      durum.pano = null;
    },
    t("yapistirildi", { baslik: p.title }),
    () => eylem(() => istek(`/api/events/${yeniId}`, { method: "DELETE" }), t("yapistirma_geri_alindi")),
  );
}

/* Hedef fareyle takip edilen boş saat (durum.imlecSaat) -- gün/hafta
 * görünümünde imleci ızgaranın üzerine getirip Ctrl+V basmak yeter, ayrıca
 * tıklamaya gerek yok. Ay görünümünde saat ızgarası olmadığı için kapsam
 * dışı; kullanıcıyı gün/hafta görünümüne yönlendiriyoruz. */
function yapistir() {
  if (!durum.pano) { bildir(t("yapistir_once_kopyala"), true); return; }
  if (!durum.imlecSaat) {
    bildir(t("yapistir_hedef_yok"), true);
    return;
  }
  panoyaYaz(durum.imlecSaat.date, durum.imlecSaat.minutes);
}

/* Çoğalt: kopyalamadan geçmeden TEK adımda "aynı saatte yarın bir tane daha"
 * -- Ctrl+V'nin "imleci hedefe götür" akışına göre daha hızlı bir kısayol.
 * panoyaYaz TEK SEFERLİK olduğu için yazımdan sonra pano yine boşalır;
 * başka bir yere de yapıştırmak istenirse yeniden kopyalamak gerekir. */
function cogalt() {
  if (!durum.secili) { bildir(t("cogalt_sec"), true); return; }
  const occ = durum.secili;
  if (!panoyaKopyala(occ)) return;
  const tarih = tarihKaydir(yerelTarihISO(occ.startUtc, occ.tzid), 1);
  const bas = dakikayaCevir(yerelSaatISO(occ.startUtc, occ.tzid));
  panoyaYaz(tarih, bas);
}

/* Ctrl+Z: o an görünen bildirimin "Geri al" düğmesi varsa onu tıklar.
 * Yeni bir geri-alma mekanizması DEĞİL -- var olan düğmeyi klavyeden de
 * erişilebilir yapıyor. Bildirim kapalıysa ya da düğmesi yoksa hiçbir şey
 * yapmaz. */
function geriAlKisayolu() {
  const kutu = el("bildirim");
  if (kutu.hidden) return;
  const dugme = kutu.querySelector(".bildirim-dugme");
  if (dugme) dugme.click();
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
      ? t("kapsam_sonsuz", { n: bilgi.ornek_sayisi })
      : t("kapsam_sayili", { n: bilgi.ornek_sayisi }))
    : t("kapsam_tek");
  const tamam = await onayla(
    t("seriyi_tamamen_sil"),
    t("seri_sil_metin", { baslik: bilgi.title, kapsam }),
    t("seri_sil_onay"),
    true,
  );
  if (!tamam) return;
  await eylem(
    () => istek(`/api/events/${occ.eventId}`, { method: "DELETE" }),
    t("seri_silindi", { baslik: bilgi.title }),
    () => eylem(
      () => istek("/api/events/restore_last", { method: "POST" }),
      t("seri_geri_alindi"),
    ),
  );
}

/* Yedekler kutusu (Takvim Arayuz.pdf §1h): tek bir <select> yerine satır
 * başına "Geri yükle" olan gerçek bir liste + "Şimdi yedekle / Klasörü aç /
 * Kapat". Döngü içinde: "Şimdi yedekle" ve "Klasörü aç" kutuyu KAPATMAZ,
 * liste tazelenip aynı kutu yeniden açılır -- kullanıcı arka arkaya birkaç
 * eylem yapabilsin diye (bkz. modalAc `ucuncu` ve `kur`e verilen `bitir`).
 * Geri yükleme kendi onay adımından geçer (tehlikeli, geri dönüşü var ama
 * CANLI dosyanın üstüne yazıyor), sonunda tam sayfa yenileme. */
async function yedekleriAc() {
  for (;;) {
    let veri;
    try {
      veri = await istek("/api/backups");
    } catch (hata) {
      bildir(hata.message, true);
      return;
    }

    const sonuc = await modalAc({
      baslik: t("yedekler_baslik"),
      metin: veri.backups.length ? "" : t("yedek_yok"),
      onay: t("simdi_yedekle"),
      iptalDegeri: { eylem: "kapat" },
      ucuncu: { etiket: t("klasor_ac"), anahtar: "_klasorAc" },
      genislik: 540,
      oku: () => ({ eylem: "yedekle_simdi" }),
      kur: (govde, kapat) => {
        if (!veri.backups.length) return null;
        const yol = document.createElement("p");
        yol.className = "yedek-yol";
        // Sabit metin: SAKLANAN (store/yedek.py) API'ye sızdırılmıyor, README
        // §5 de aynı sayıyı yazıyor -- ikisi birlikte güncellenir.
        yol.textContent = t("yedek_yol");
        govde.appendChild(yol);

        const liste = document.createElement("div");
        liste.className = "yedek-liste";
        veri.backups.forEach((b) => {
          const satir = document.createElement("div");
          satir.className = "yedek-satir";

          const bilgi = document.createElement("span");
          bilgi.className = "yedek-bilgi";
          const tarih = b.ad.replace(/^takvim-/, "").replace(/\.db$/, "");
          const sayi = b.etkinlikSayisi == null ? "?" : b.etkinlikSayisi;
          bilgi.textContent = t("yedek_satir", {
            tarih, sayi, kb: (b.boyut / 1024).toFixed(0),
          });

          const dugme = document.createElement("button");
          dugme.type = "button";
          dugme.className = "dugme";
          dugme.textContent = t("geri_yukle");
          dugme.onclick = () => kapat({ eylem: "geri_yukle", ad: b.ad });

          satir.append(bilgi, dugme);
          liste.appendChild(satir);
        });
        govde.appendChild(liste);
        return null;
      },
    });

    if (sonuc.eylem === "kapat") return;

    if (sonuc._klasorAc) {
      try {
        await istek("/api/backups/open", { method: "POST" });
      } catch (hata) {
        bildir(hata.message, true);
      }
      continue;
    }

    if (sonuc.eylem === "yedekle_simdi") {
      try {
        await istek("/api/backups", { method: "POST" });
        bildir(t("yedek_alindi"));
      } catch (hata) {
        bildir(hata.message, true);
      }
      continue;
    }

    // sonuc.eylem === "geri_yukle"
    const tamam = await onayla(
      t("yedekten_don_baslik"),
      t("yedekten_don_metin", { ad: sonuc.ad }),
      t("geri_yukle"),
      true,
    );
    if (!tamam) continue; // listeye dön
    try {
      await istek("/api/backups/restore", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ad: sonuc.ad }),
      });
      window.location.reload();
    } catch (hata) {
      bildir(hata.message, true);
    }
    return;
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
    if (kisayol) b.title = t("kisayol", { kisayol });
    b.onclick = islev;
    kap.appendChild(b);
  };

  ekle(t("duzenle"), false, () => etkinligiDuzenle(occ), "F2 · Enter");

  (occ.reminders || []).forEach((r) => {
    ekle(t("hatirlatici_kaldir", { metin: hatirlaticiMetni(r.minutesBefore) }), false, async () => {
      await eylem(
        () => istek(`/api/reminders/${r.id}`, { method: "DELETE" }),
        t("hatirlatici_kaldirildi"),
      );
    });
  });

  ekle(t("hatirlatici_ekle"), false, async () => {
    const ham = await sor(
      t("hatirlatici_ekle"),
      t("hatirlatici_sor_metin"),
      "15",
    );
    if (ham === null) return;
    const dakika = parseInt(ham, 10);
    if (Number.isNaN(dakika) || dakika < 0) {
      bildir(t("dakika_gir"), true);
      return;
    }
    await eylem(
      () => istek(`/api/events/${occ.eventId}/reminders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ minutesBefore: dakika }),
      }),
      t("hatirlatici_eklendi", { metin: hatirlaticiMetni(dakika) }),
    );
  });

  // Tekrarlı serilerde tek örnek / tüm seri ayrımı kritik: kullanıcı bir
  // dersi bu haftalık iptal etmekle dönem boyunca silmeyi karıştırmamalı.
  // Klavyede de aynı ayrım var: Del tek örnek, Shift+Del tüm seri.
  // TEKRARSIZ etkinlikte iki düğme göstermek anlamsız ve korkutucu: tek "Sil".
  if (occ.recurring) {
    ekle(t("bu_ornegi_sil"), true, () => ornegiSil(occ), "Del");
    ekle(t("seriyi_tamamen_sil"), true, () => seriyiSil(occ), "Shift+Del");
    ekle(t("bundan_sonrasini_degistir"), false, () => seriyiBol(occ));
  } else {
    ekle(t("sil"), true, () => ornegiSil(occ), "Del");
  }
}

/* Seriyi BÖLER: bu örnek ve sonrakiler yeni seri oluyor (THISANDFUTURE).
 * Anahtar `originalStartUtc` (taşınmış örnekte `startUtc` DEĞİL — AGENTS 21).
 * Saat değişmiyor; değişen başlık/konum/açıklama YALNIZCA yeni seriye yazılıyor.
 * İlk örnekte bölme sunucuda reddediliyor (eski seri boş kalırdı). */
async function seriyiBol(occ) {
  const s = await modalForm(t("bundan_sonrasini_degistir"),
    t("bol_metin", { baslik: occ.title }),
    [
      { ad: "baslik", etiket: t("bol_baslik_etiket"), tur: "metin", deger: occ.title },
      { ad: "konum", etiket: t("p_konum"), tur: "metin", deger: occ.location || "" },
      { ad: "aciklama", etiket: t("p_aciklama"), tur: "uzunmetin", deger: occ.description || "" },
    ],
    t("bol_onay"));
  if (s === null || !s.baslik.trim()) return;
  await eylem(
    () => istek(`/api/events/${occ.eventId}/split`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        originalStartUtc: occ.originalStartUtc,
        title: s.baslik.trim(),
        location: s.konum.trim(),
        description: s.aciklama.trim(),
      }),
    }),
    t("seri_bolundu"),
  );
}

function hatirlaticiMetni(dakika) {
  if (dakika === 0) return t("tam_baslarken");
  if (dakika % 1440 === 0) {
    const n = dakika / 1440;
    return n === 1 ? t("gun_once_tek") : t("gun_once", { n });
  }
  if (dakika % 60 === 0) {
    const n = dakika / 60;
    return n === 1 ? t("saat_once_tek") : t("saat_once", { n });
  }
  return dakika === 1 ? t("dakika_once_tek") : t("dakika_once", { n: dakika });
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
  await hizliEkleBaslat(metin, girdi);
};

/* Hızlı ekleme akışı, iki yola ayrılıyor:
 * - Çakışma yok (ya da tekrarlı bir seri): ESKİ tek istekli yol -- doğrudan
 *   kaydet, çakışırsa (tekrarlıda) sonradan bildir + geri al. Hız burada
 *   kaybetmesin diye kasıtlı: çoğu ekleme hiç çakışmıyor.
 * - Tekrarsız VE çakışıyor: Takvim Arayuz.pdf §1f -- kaydetmeden ÖNCE
 *   düzenlenebilir alanlarla 3 düğmeli bir onay kutusu açılır (`/api/events/
 *   parse` ile DB'ye dokunmadan önizleme alınıyor). */
async function hizliEkleBaslat(metin, girdi) {
  let onizleme;
  try {
    onizleme = await istek("/api/events/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: metin }),
    });
  } catch (hata) {
    bildir(hata.message, true);
    return;
  }

  let cakisma = [];
  if (onizleme.matched && !onizleme.allDay && !onizleme.recurring) {
    try {
      const c = await istek(
        `/api/conflicts?startUtc=${encodeURIComponent(onizleme.startUtc)}` +
        `&endUtc=${encodeURIComponent(onizleme.endUtc)}`,
      );
      cakisma = c.conflicts;
    } catch {
      // Çakışma sorgusu başarısızsa engellemeden devam.
    }
  }

  if (cakisma.length) {
    await cakismaOnayiVeKaydet(onizleme, cakisma, girdi);
    return;
  }

  try {
    await istek("/api/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: metin }),
    });
    girdi.value = "";
    if (!onizleme.matched) {
      bildir(
        t("eklendi_zaman_taninmadi", { baslik: onizleme.title }),
        true,
      );
    } else {
      bildir(t("eklendi", { baslik: onizleme.title, eslesme: onizleme.matched }));
    }
    await yukle();
  } catch (hata) {
    bildir(hata.message, true);
  }
}

/* Çakışma onay kutusu (Takvim Arayuz.pdf §1f): "Yine de kaydet / Saati
 * değiştir / Vazgeç". "Saati değiştir" formu KAPATMIYORMUŞ gibi davranır --
 * teknik olarak her düğme modalAc'ı kapatıyor (bkz. modalAc), burada aynı
 * (düzenlenmiş) değerlerle YENİDEN açarak aynı izlenimi veriyoruz. Kaydetme
 * DATE/MINUTES yoluyla (`_etkinlik_olustur_acik`): kullanıcı alanları
 * değiştirmiş olabilir, orijinal metni tekrar göndermek o düzenlemeleri
 * yok sayardı. */
async function cakismaOnayiVeKaydet(onizleme, cakisma, girdi) {
  const gorunurTakvim = durum.veri.calendars.find((c) => durum.takvimGorunur.get(c.id) !== false)
    || durum.veri.calendars[0] || {};
  const adlar = cakisma.map((x) =>
    `${x.title} · ${saatBicim(x.startUtc, x.tzid)}–${saatBicim(x.endUtc, x.tzid)}`
  ).join("\n");

  let deger = {
    baslik: onizleme.title,
    tarih: yerelTarihISO(onizleme.startUtc, onizleme.tzid),
    baslangic: yerelSaatISO(onizleme.startUtc, onizleme.tzid),
    bitis: yerelSaatISO(onizleme.endUtc, onizleme.tzid),
    takvim: String(gorunurTakvim.id || ""),
  };

  for (;;) {
    const s = await modalForm(
      t("cakisma_baslik"),
      t("cakisma_metin", { adlar }),
      [
        { ad: "baslik", etiket: t("baslik_etiket"), tur: "metin", deger: deger.baslik },
        { ad: "tarih", etiket: t("tarih_etiket"), tur: "tarih", deger: deger.tarih },
        { ad: "baslangic", etiket: t("baslangic"), tur: "saat", deger: deger.baslangic, dar: true },
        { ad: "bitis", etiket: t("bitis"), tur: "saat", deger: deger.bitis, dar: true },
        {
          ad: "takvim", etiket: t("p_takvim"), tur: "secim", deger: deger.takvim,
          secenekler: durum.veri.calendars.map((c) => ({ deger: String(c.id), etiket: c.name })),
        },
      ],
      t("yine_de_kaydet"),
      { etiket: t("saati_degistir"), anahtar: "_saatDegistir" },
      460,
    );

    if (s === null) { girdi.value = ""; return; } // Vazgeç / Esc / perdeye tık: hiçbir şey oluşturulmaz

    deger = { baslik: s.baslik, tarih: s.tarih, baslangic: s.baslangic, bitis: s.bitis, takvim: s.takvim };
    if (s._saatDegistir) continue; // aynı değerlerle yeniden aç, kullanıcı düzenlesin

    const ad = deger.baslik.trim();
    if (!ad) { bildir(t("istemci_baslik_bos"), true); continue; }
    const basDk = dakikayaCevir(deger.baslangic);
    const bitDk = dakikayaCevir(deger.bitis);
    if (bitDk <= basDk) { bildir(t("istemci_bitis_sira"), true); continue; }

    await eylem(
      () => istek("/api/events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: ad,
          date: deger.tarih,
          minutes: basDk,
          endMinutes: bitDk,
          calendarId: deger.takvim ? Number(deger.takvim) : undefined,
        }),
      }),
      t("eklendi_kisa", { baslik: ad }),
    );
    girdi.value = "";
    return;
  }
}

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
      liste.innerHTML = `<li class="arama-bos">${kacir(t("sonuc_yok"))}</li>`;
    }
    sonuc.results.forEach((ev) => {
      const takvim = durum.veri.calendars.find((c) => c.id === ev.calendarId);
      // <li> yalnızca liste öğesi çerçevesi; asıl tıklanabilir yüzey içindeki
      // <button> -- eskiden <li onclick>'ti, klavye/ekran okuyucu kullanan
      // biri arama sonucuna hiç gidemiyordu (bkz. ay-blok/gl-satir'daki aynı
      // düzeltme).
      const li = document.createElement("li");
      const dugme = document.createElement("button");
      dugme.type = "button";
      dugme.className = "arama-satir";
      dugme.style.borderLeftColor = takvim ? takvim.color : "#6b7280";
      dugme.innerHTML =
        `<div>${kacir(ev.title)}${ev.recurring ? " ↻" : ""}</div>` +
        `<div class="a-tarih">${tarihBicim(ev.startUtc, ev.tzid)}</div>`;
      // Sonuca tıklayınca o tarihe git
      dugme.onclick = () => {
        durum.anchor = new Intl.DateTimeFormat("en-CA", { timeZone: ev.tzid })
          .format(new Date(ev.startUtc));
        yukle();
      };
      li.appendChild(dugme);
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

/* Ctrl+Scroll (trackpad'de pinch de tarayıcıda ctrlKey:true'lu wheel olarak
 * gelir, o yüzden bu ikisini AYRI ele almaya gerek yok) ızgarayı büyütür/
 * küçültür. preventDefault ŞART: yoksa tarayıcı SAYFAYI yakınlaştırır,
 * ızgarayı değil. İmlecin altındaki saat SABİT kalır (Figma/Google Maps'teki
 * gibi): önce o anın toplam yükseklikteki payını hesaplıyoruz, yükseklik
 * değiştikten sonra aynı payı yine imlecin altına getirecek scrollTop'u
 * yazıyoruz -- yoksa her tekerlek hareketinde ekran farklı bir saate zıplar. */
function izgaraYakinlastir(e) {
  if (!e.ctrlKey) return;
  e.preventDefault();

  const kaydirma = el("izgara-kaydirma");
  const kutu = kaydirma.getBoundingClientRect();
  const imlecKonum = e.clientY - kutu.top + kaydirma.scrollTop;
  const oran = imlecKonum / (24 * durum.saatYukseklik);

  const adim = e.deltaY < 0 ? SAAT_YAKINLASTIR_ADIM : -SAAT_YAKINLASTIR_ADIM;
  const yeni = Math.max(
    SAAT_YUKSEKLIK_MIN,
    Math.min(SAAT_YUKSEKLIK_MAKS, durum.saatYukseklik + adim),
  );
  if (yeni === durum.saatYukseklik) return;
  durum.saatYukseklik = yeni;
  yogunlukUygula();
  ciz();

  kaydirma.scrollTop = oran * (24 * durum.saatYukseklik) - (e.clientY - kutu.top);
}
el("izgara-kaydirma").addEventListener("wheel", izgaraYakinlastir, { passive: false });

/* Zoom ucunda blok içeriği değişir (Takvim Arayuz.pdf "1i"): sıkışıkta
 * (≤32px/saat) saat satırı bile sığmayabilir, ferahta (≥100px/saat) konum
 * satırı için yer açılır. `#izgara` üstünde bir veri özniteliği -- CSS
 * seçicileri onu okuyor, JS her blok için tekrar hesaplamıyor. `ciz()`
 * `#gunler`in İÇİNİ boşaltıp yeniden dolduruyor ama `#izgara`nın kendisine
 * dokunmuyor, o yüzden öznitelik render'lar arasında hayatta kalıyor. */
function yogunlukUygula() {
  const y = durum.saatYukseklik;
  const izgara = el("izgara");
  if (y <= 32) izgara.dataset.yogunluk = "sikisik";
  else if (y >= 100) izgara.dataset.yogunluk = "ferah";
  else delete izgara.dataset.yogunluk;
}
yogunlukUygula();

el("onceki").onclick = () => kaydir(-1);
el("sonraki").onclick = () => kaydir(1);
el("bugun").onclick = () => { durum.anchor = bugunISO(); yukle(); };
el("takvim-ekle").onclick = takvimEkle;

/* Arama HER pencere boyutunda ikon + üstten inen şerit (Takvim Arayuz.pdf
 * §"Arama her boyutta 32×32 ikon düğmesi"). #arama'nın KENDİ oninput'u
 * (yukarıda) hiç değişmedi -- yalnızca görünürlüğünü/odağını yönetiyoruz. */
function aramaSeridiAc() {
  el("arama-serit").hidden = false;
  el("arama").focus();
}
function aramaSeridiKapat() {
  el("arama-serit").hidden = true;
  el("arama").value = "";
  aramaYap("");
}
el("arama-ac-dugme").onclick = () => {
  if (el("arama-serit").hidden) aramaSeridiAc();
  else aramaSeridiKapat();
};
el("arama-kapat").onclick = aramaSeridiKapat;
el("arama").addEventListener("keydown", (e) => {
  if (e.key === "Escape") { e.stopPropagation(); aramaSeridiKapat(); }
});

/* Dar pencerede (< 1040px) hızlı ekleme kutusu sığmıyor; "+ Ekle" düğmesi
 * tek satırlık bir soru kutusuyla AYNI gönderim yolunu (#hizli-form'un
 * submit'i) tetikliyor -- mantık İKİ YERDE yaşamasın diye. */
el("hizli-ac-dugme").onclick = async () => {
  const metin = await sor(t("yeni_etkinlik"), "", "");
  if (metin === null || !metin.trim()) return;
  el("hizli-girdi").value = metin.trim();
  const form = el("hizli-form");
  if (form.requestSubmit) form.requestSubmit();
  else form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
};
el("panel-kapat").onclick = panelKapat;
el("disa-aktar").onclick = () => { window.location.href = "/api/export"; };

// Boş durum ekranının üç düğmesi: gerçek eylemleri TEKRAR YAZMIYOR, zaten
// var olan yolları tetikliyor. "Etkinlik ekle" pencere genişliğine göre
// doğru girdiye gidiyor (geniş: kutuya odaklan, dar: aynı soru kutusu).
el("bd-etkinlik-ekle").onclick = () => {
  if (getComputedStyle(el("hizli-form")).display !== "none") el("hizli-girdi").focus();
  else el("hizli-ac-dugme").click();
};
el("bd-ice-aktar").onclick = () => el("ice-aktar").click();
el("bd-yedekler").onclick = () => el("yedekler").click();
el("yedekler").onclick = yedekleriAc;
el("ayarlar").onclick = ayarlariAc;
el("ice-aktar").onclick = () => el("ice-aktar-dosya").click();
el("ice-aktar-dosya").onchange = (e) => {
  const dosya = e.target.files[0];
  // Aynı dosya üst üste seçilebilsin diye sıfırla; yoksa change ateşlenmez.
  e.target.value = "";
  if (dosya) iceAktar(dosya);
};

/* Ayarlar: tepsiye küçült + otomatik başlatma + dil. İkisi de varsayılan kapalı;
 * açmak bilinçli karar (kapatınca tepsiye inmek, Başlangıç klasörüne yazmak).
 * Yeniden başlatma gerekmiyor: tepsi kararı her kapanışta dosyadan okunuyor.
 * Dil değişince sayfa YENİDEN YÜKLENİYOR: kısmi yeniden çizim değil, basit ve
 * güvenilir -- tüm metinler açılışta tek yerden kuruluyor. */
async function ayarlariAc() {
  let mevcut;
  try {
    mevcut = await istek("/api/ayarlar");
  } catch (hata) {
    bildir(hata.message, true);
    return;
  }
  const s = await modalForm(t("ayarlar_baslik"),
    t("ayarlar_metin"),
    [
      {
        ad: "tepsi",
        etiket: t("kapatilinca"),
        tur: "secim",
        deger: mevcut.tepsiye_kucult ? "kucult" : "kapat",
        secenekler: [
          { deger: "kapat", etiket: t("uygulamayi_kapat") },
          { deger: "kucult", etiket: t("tepsiye_kucult") },
        ],
      },
      {
        ad: "otomatik",
        etiket: t("acilista"),
        tur: "secim",
        deger: mevcut.otomatik_baslat ? "acik" : "kapali",
        secenekler: [
          { deger: "kapali", etiket: t("hatirlatici_baslatma") },
          { deger: "acik", etiket: t("hatirlatici_baslat") },
        ],
      },
      {
        ad: "dil",
        etiket: t("dil_etiket"),
        tur: "secim",
        deger: mevcut.dil === "en" ? "en" : "tr",
        secenekler: [
          { deger: "tr", etiket: "Türkçe" },
          { deger: "en", etiket: "English" },
        ],
      },
    ],
    t("kaydet"));
  if (!s) return;
  const dilDegisti = (s.dil === "en" ? "en" : "tr") !== durum.dil;
  await eylem(
    () => istek("/api/ayarlar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tepsiye_kucult: s.tepsi === "kucult",
        otomatik_baslat: s.otomatik === "acik",
        dil: s.dil === "en" ? "en" : "tr",
      }),
    }),
    t("ayarlar_kaydedildi"),
  );
  if (dilDegisti) window.location.reload();
}

/* `.ics` içe aktarma: önce ÖNİZLEME (`dry_run`), sonra gerçek yazma.
 * İki aşama ŞART: dosyanın kaç kayıt ekleyeceğini/güncelleyeceğini görmeden
 * yazmak, "bilgisayarımdaki her şey iki kere oldu" demek. */
async function iceAktar(dosya) {
  let metin;
  try {
    metin = await dosya.text();
  } catch {
    bildir(t("dosya_okunamadi"), true);
    return;
  }
  const baslik = { "Content-Type": "text/calendar; charset=utf-8" };
  let onizleme;
  try {
    onizleme = await istek("/api/import?dry_run=1", {
      method: "POST", headers: baslik, body: metin,
    });
  } catch (hata) {
    bildir(hata.message, true);
    return;
  }
  const parcalar = [
    t("parca_yeni", { n: onizleme.added }),
    t("parca_guncellenecek", { n: onizleme.updated }),
    t("parca_atlanacak", { n: onizleme.skipped }),
    t("parca_override", { n: onizleme.overrides }),
  ];
  if (onizleme.errors.length) {
    parcalar.push(t("parca_hatali", { n: onizleme.errors.length }));
  }
  if (onizleme.warnings.length) {
    parcalar.push(t("parca_uyari", { liste: onizleme.warnings.slice(0, 3).join("; ") }));
  }
  const tamam = await onayla(
    t("ice_aktar_baslik"),
    t("ice_aktar_metin", {
      dosya: dosya.name, takvim: onizleme.calendar, parcalar: parcalar.join(", "),
    }),
    t("ice_aktar_baslik"),
  );
  if (!tamam) return;
  try {
    const rapor = await istek("/api/import", {
      method: "POST", headers: baslik, body: metin,
    });
    bildir(t("ice_aktarildi", { yeni: rapor.added, guncellenen: rapor.updated }));
    await yukle();
  } catch (hata) {
    bildir(hata.message, true);
  }
}

document.querySelectorAll(".gorunum-dugme").forEach((b) => {
  b.onclick = () => { durum.gorunum = b.dataset.gorunum; yukle(); };
});

document.addEventListener("keydown", (e) => {
  // Soru kutusu açıkken arkadaki görünüm değişmesin: "Sil?" kutusundayken
  // "a" harfine basmak ay görünümüne atlıyordu.
  if (modalAcik()) return;

  // Alt'lı birleşimlere hiç karışmıyoruz (menü erişim tuşları vb.).
  if (e.altKey) return;

  const yaziKutusu = ["INPUT", "TEXTAREA"].includes(e.target.tagName);

  /* Pano kısayolları: Ctrl/Cmd + C/X/V/D/Z. Diğer TÜM Ctrl birleşimleri
   * (Ctrl+A tümünü seç, Ctrl+H, Ctrl+T...) bizim değil -- onları
   * yakalarsak kullanıcı metni seçemez ya da beklediği tarayıcı/işletim
   * sistemi davranışı yerine bizim bir şeyimiz çalışır. Yazı kutusundayken
   * de devre dışı: arama kutusunda ya da düzenleme formunda kullanıcının
   * kendi kopyala/yapıştırı çalışmalı, bizim etkinlik panomuz değil. */
  if (e.ctrlKey || e.metaKey) {
    if (yaziKutusu) return;
    const panoKisayollari = { c: kopyala, x: kes, v: yapistir, d: cogalt, z: geriAlKisayolu };
    const islev = panoKisayollari[e.key.toLowerCase()];
    if (!islev) return;
    e.preventDefault();
    islev();
    return;
  }

  // Yazarken kısayollar devreye girmesin. Del ve Backspace için bu ŞART:
  // hızlı ekleme kutusunda yazarken Del etkinlik silmemeli, harf silmeli.
  if (yaziKutusu) {
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
    // Panoda bir şey varken boş saate tıklamak YAPIŞTIRIR (izgaraTik); bu
    // yüzden "Yeni etkinlik" kutusuna geri dönmenin bir yolu şart -- Escape
    // panoyu temizliyor. Sessizce yapıyor: pano boşsa zaten yapacak bir şey
    // yok, panoluyken her Escape'te "temizlendi" bildirimi gürültü olurdu.
    Escape: () => { durum.pano = null; gunListesiKapat(); panelKapat(); },
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

/* ---------- açılış ---------- */

/* Sabit HTML metinlerini dile çevirir (`data-i18n*` öznitelikleri).
 *
 * HTML'i dil başına ikiye bölmüyoruz (bakım kâbusu): tek HTML, açılışta tek
 * doldurma. `data-i18n` → textContent, `data-i18n-html` → innerHTML (yalnızca
 * KENDİ sözlüğümüz, kullanıcı verisi değil), `data-i18n-ph` → placeholder,
 * `data-i18n-aria` → aria-label, `data-i18n-title` → title. */
function statikMetinleriUygula() {
  document.querySelectorAll("[data-i18n]").forEach((n) => {
    n.textContent = t(n.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-html]").forEach((n) => {
    n.innerHTML = t(n.dataset.i18nHtml);
  });
  document.querySelectorAll("[data-i18n-ph]").forEach((n) => {
    n.placeholder = t(n.dataset.i18nPh);
  });
  document.querySelectorAll("[data-i18n-aria]").forEach((n) => {
    n.setAttribute("aria-label", t(n.dataset.i18nAria));
  });
  document.querySelectorAll("[data-i18n-title]").forEach((n) => {
    n.title = t(n.dataset.i18nTitle);
  });
}

/* Dil ÖNCE okunuyor: ilk `yukle()` çizmeden `durum.dil` belli olmalı, yoksa
 * sayfa bir anlığına yanlış dilde çizilip sonra düzelir (göz kırpma). Ayar
 * okunamazsa varsayılan `tr` ile devam -- ayarsız açılış Türkçe demek. */
async function baslat() {
  try {
    const ayar = await istek("/api/ayarlar");
    if (ayar.dil === "en" || ayar.dil === "tr") durum.dil = ayar.dil;
  } catch {
    // Ayar alınamazsa varsayılan dilde devam; yukle() hatayı zaten bildirir.
  }
  document.documentElement.lang = durum.dil;
  statikMetinleriUygula();
  await yukle();
  canliBaslat();
}

baslat();
