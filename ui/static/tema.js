/* Tema: <html data-tema="koyu|acik">. Seçim "koyu" | "acik" | "sistem"; "sistem"
   işletim sisteminin renk tercihine bakar ve değişince canlı izler.
   Seçim ayarlar.json'da; burada yalnızca açılışta göz kırpmasın diye
   localStorage önbelleği okunuyor (app.js ayarı okuyunca günceller). Ağ yok. */
(function () {
  var AD = "takvim-tema";
  var mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;
  var secim = "koyu";
  function coz(s) { return s === "sistem" ? (mq && mq.matches ? "acik" : "koyu") : (s === "acik" ? "acik" : "koyu"); }
  function uygula() { document.documentElement.setAttribute("data-tema", coz(secim)); }
  window.temaUygula = function (s) {
    secim = (s === "acik" || s === "sistem") ? s : "koyu";
    try { localStorage.setItem(AD, secim); } catch (e) { /* önbellek yoksa sorun değil */ }
    uygula();
  };
  try { var k = localStorage.getItem(AD); if (k) secim = k; } catch (e) { /* varsayılan koyu */ }
  if (mq && mq.addEventListener) mq.addEventListener("change", uygula);
  uygula();
})();
