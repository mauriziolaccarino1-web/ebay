/* Avvio: schede, caricamento file, linea del tempo, riproduzione */
(function () {
  const DV = window.DV;
  const S = DV.stato;
  const { $, $$, el } = DV;

  // ---------------------------------------------------------------- schede
  S.vista = "acquisizione";
  const viste = DV.viste;
  function mostra(nome) {
    S.vista = nome;
    $$("#schede button").forEach((b) => b.classList.toggle("attiva", b.dataset.vista === nome));
    $$(".vista").forEach((v) => v.classList.toggle("attiva", v.id === "v-" + nome));
    const v = viste[nome];
    if (v && v.sporca !== false) { v.disegna(); v.sporca = false; }
    else if (v && v.cursore) v.cursore();
  }
  $("#schede").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) mostra(b.dataset.vista); });
  const sporca = () => { for (const v of Object.values(viste)) v.sporca = true; if (viste[S.vista]) { viste[S.vista].disegna(); viste[S.vista].sporca = false; } };
  DV.on("sessione", () => { $("#vuoto").hidden = !!S.sess; aggiornaGiri(); aggiornaCurve(); aggiornaParametri(); sporca(); disegnaTimeline(); aggiornaOra(); });
  DV.on("modello", () => { sporca(); disegnaTimeline(); aggiornaParametri(); });
  DV.on("modello", () => { aggiornaStatoCal(); aggiornaOra(); });
  DV.on("calibrazione", () => { aggiornaStatoCal(); for (const v of Object.values(viste)) v.sporca = true; if (["mappe", "pneumatico"].includes(S.vista)) { viste[S.vista].disegna(); viste[S.vista].sporca = false; } });
  DV.on("cursore", () => { aggiornaOra(); disegnaCursoreTimeline(); const v = viste[S.vista]; if (v && v.cursore) v.cursore(); });

  // ---------------------------------------------------------------- file
  $("#file").addEventListener("change", (e) => DV.caricaFile(e.target.files));
  document.addEventListener("dragover", (e) => { e.preventDefault(); document.body.classList.add("trascina"); });
  document.addEventListener("dragleave", (e) => { if (e.target === document.documentElement || e.clientY <= 0) document.body.classList.remove("trascina"); });
  document.addEventListener("drop", (e) => { e.preventDefault(); document.body.classList.remove("trascina"); DV.caricaFile(e.dataTransfer.files); });

  DV.on("progetto", (P) => {
    $("#nome-progetto").textContent = P.nome ? "· " + P.nome : "";
    const sel = $("#sessioni");
    if (P.sessioni && P.sessioni.length > 1) {
      sel.hidden = false;
      sel.innerHTML = "";
      P.sessioni.forEach((s) => sel.append(el("option", { value: s }, s)));
    }
  });
  $("#sessioni").addEventListener("change", (e) => DV.apriSessione(e.target.value));

  function aggiornaStatoCal() {
    const box = $("#stato-cal");
    box.innerHTML = "";
    if (!S.cal.length) { box.textContent = S.struttura ? `${S.struttura.tabelle.length} tabelle · nessun file .bin` : ""; return; }
    const sel = (val, on, titolo) => {
      const s = el("select", { title: titolo });
      S.cal.forEach((c) => s.append(el("option", { value: c.nome, selected: c.nome === val || undefined }, c.nome + (c.variante && c.variante !== c.nome ? ` (${c.variante})` : ""))));
      s.addEventListener("change", () => on(s.value));
      return s;
    };
    box.append(el("label", { class: "fila", style: { gap: "4px" } }, "A", sel(S.rif, (v) => DV.scegliCalibrazioni(v, null), "A = riferimento (per esempio la mappa montata in moto)")),
      el("label", { class: "fila", style: { gap: "4px" } }, "B", sel(S.cfr, (v) => DV.scegliCalibrazioni(null, v), "B = confronto: la mappa da confrontare con A e da modificare (copia di lavoro)")));
    if (S.struttura && S.binMod) {
      let testo;
      try {
        const v = DV.calib.verifica(S.struttura, S.binMod);
        testo = !v.length ? "nessun checksum definito" : v.every((x) => x.ok) ? "checksum B ok" : "checksum B da ricalcolare (lo fa l'esportazione)";
      } catch (e) { testo = e.message; }
      box.append(el("span", { class: "tenue" }, (DV.lavoroModificato() ? "B modificata · " : "") + testo));
    }
  }

  // ---------------------------------------------------------------- giri e parametri
  function aggiornaGiri() {
    const sel = $("#giro");
    sel.innerHTML = "";
    sel.append(el("option", { value: "" }, "tutta la sessione"));
    const lanc = DV.giri().filter((g) => g.tipo === "lanciato");
    const migliore = Math.min(...lanc.map((g) => g.tempo));
    DV.giri().forEach((g, k) => {
      const nome = g.tipo === "lanciato" ? `giro ${g.numero} · ${DV.tempo(g.tempo)}${g.tempo === migliore ? " ★" : ""}` : g.tipo === "uscita" ? "uscita box" : g.tipo === "rientro" ? "rientro" : `giro ${g.numero} (dubbio)`;
      sel.append(el("option", { value: k }, nome));
    });
  }
  $("#giro").addEventListener("change", (e) => {
    const k = e.target.value;
    if (k === "") { S.giro = null; DV.zoomTempo(null); }
    else {
      const g = DV.giri()[+k];
      S.giro = g;
      const a = DV.tRel(g.t_inizio), b = DV.tRel(g.t_fine);
      DV.zoomTempo(a, b);
      DV.vaiA(a / S.dt);
    }
    DV.emit("giro", S.giro);
    for (const v of Object.values(viste)) if (v.alGiro) v.sporca = true;
    if (viste[S.vista] && viste[S.vista].alGiro) { viste[S.vista].disegna(); viste[S.vista].sporca = false; }
    disegnaTimeline();
  });
  DV.intervallo = () => {
    if (!S.giro) return [0, S.n - 1];
    return [DV.indiceDaTempo(DV.tRel(S.giro.t_inizio)), DV.indiceDaTempo(DV.tRel(S.giro.t_fine))];
  };

  // menu delle curve: porta il cursore all'apice della curva nel giro scelto (o in quello del cursore)
  function aggiornaCurve() {
    const sc = $("#curva");
    sc.innerHTML = "";
    sc.append(el("option", { value: "" }, "vai alla curva…"));
    DV.curve().forEach((c) => sc.append(el("option", { value: c.id }, `${DV.nomeCurva(c)}${c.verso ? " (" + c.verso + ")" : ""}`)));
    sc.hidden = !DV.curve().length;
  }
  DV.on("curve", () => { aggiornaCurve(); sporca(); });
  DV.on("guida", () => { $("#link-guida").hidden = false; });
  $("#curva").addEventListener("change", (e) => {
    const c = DV.curve().find((x) => x.id === e.target.value);
    if (!c) return;
    const g = S.giro || DV.giroDi(S.i) || DV.giri().find((x) => x.tipo === "lanciato");
    if (!g) return;
    const ng = DV.canale("n_giro"), sg = DV.canale("s_giro");
    const a = DV.indiceDaTempo(DV.tRel(g.t_inizio)), b = DV.indiceDaTempo(DV.tRel(g.t_fine));
    let best = -1, d = Infinity;
    for (let i = a; i < b; i++) if (ng.dati[i] === g.numero && Math.abs(sg.dati[i] - c.apice) < d) { d = Math.abs(sg.dati[i] - c.apice); best = i; }
    if (best >= 0) DV.vaiA(best);
  });

  // un menu per livello: "dal CAN" (il valore registrato istante per istante) oppure un valore fisso
  function aggiornaParametri() {
    const box = $("#parametri");
    box.innerHTML = "";
    if (!S.modello || !S.modello.parametri) return;
    for (const [k, d] of Object.entries(DV.modello.infoParametri(S.modello))) {
      const sel = el("select", { title: `${d.nome}: "dal CAN" segue il livello registrato (anche se cambiato in pista); un numero lo fissa per tutta la sessione` });
      const canale = d.canale && DV.canale(d.canale);
      if (canale) {
        const visti = new Set();
        for (let i = 0; i < S.n; i += 50) if (Number.isFinite(canale.dati[i])) visti.add(Math.round(canale.dati[i]));
        sel.append(el("option", { value: "can" }, `dal CAN (${[...visti].sort((a, b) => a - b).join("→") || "–"})`));
      }
      const valori = d.valori || Array.from({ length: 9 }, (_, j) => j);
      for (const v of valori) sel.append(el("option", { value: String(v) }, String(v)));
      const scelta = S.parametri[k];
      sel.value = scelta === undefined || scelta === "can" ? (canale ? "can" : String(d.valore)) : String(scelta);
      sel.addEventListener("change", () => {
        S.parametri[k] = sel.value === "can" ? "can" : +sel.value;
        if (!S.binOrig) DV.avviso("per ricalcolare con un altro livello carica il file .bin e la struttura", "errore");
        DV.ricalcola();
      });
      box.append(el("label", { class: "fila", style: { gap: "4px" } }, d.breve || d.nome.split(" (")[0], sel));
    }
  }

  // ---------------------------------------------------------------- linea del tempo
  const tl = $("#timeline");
  let immagine = null;
  function disegnaTimeline() {
    const dpr = devicePixelRatio || 1;
    const w = tl.clientWidth, h = tl.clientHeight;
    tl.width = w * dpr; tl.height = h * dpr;
    const ctx = tl.getContext("2d", { willReadFrequently: true });
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!S.sess) return;
    const v = DV.canale("v_ant") || DV.canale("v_post") || [...S.canali.values()][0];
    const n = S.n;
    // giri
    DV.giri().forEach((g, k) => {
      const a = (DV.tRel(g.t_inizio) / S.dt / n) * w, b = (DV.tRel(g.t_fine) / S.dt / n) * w;
      ctx.fillStyle = k % 2 ? DV.colore("--superficie-2") : DV.colore("--superficie");
      ctx.fillRect(a, 0, b - a, h);
      ctx.fillStyle = DV.colore("--tenue");
      ctx.font = "10px system-ui";
      if (b - a > 30) ctx.fillText(g.tipo === "lanciato" ? `G${g.numero}` : g.tipo === "uscita" ? "uscita" : g.tipo === "rientro" ? "rientro" : "?", a + 3, 10);
    });
    // interventi previsti dal modello: A in basso (rosso), B sopra (arancio) se diversa
    const righe = [[S.ris.orig, "--critico", h - 6]];
    if (DV.confrontoAttivo()) righe.push([S.ris.mod, "--s2", h - 13]);
    for (const [r, col, y] of righe) {
      if (!r) continue;
      ctx.fillStyle = DV.colore(col);
      const L = r.logica;
      for (let px = 0; px < w; px++) {
        const i0 = Math.floor((px / w) * n), i1 = Math.floor(((px + 1) / w) * n);
        let on = false;
        for (let i = i0; i < i1 && !on; i++) on = L[i] > 0.5;
        if (on) ctx.fillRect(px, y, 1, 6);
      }
    }
    if (v) {
      let mx = 0;
      for (let i = 0; i < n; i += 7) if (v.dati[i] > mx) mx = v.dati[i];
      ctx.strokeStyle = DV.colore("--s1");
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      for (let px = 0; px < w; px++) {
        const i = Math.floor((px / w) * n);
        const y = h - 8 - (v.dati[i] / (mx || 1)) * (h - 18);
        px ? ctx.lineTo(px, y) : ctx.moveTo(px, y);
      }
      ctx.stroke();
    }
    if (S.giro) {
      const a = (DV.tRel(S.giro.t_inizio) / S.dt / n) * w, b = (DV.tRel(S.giro.t_fine) / S.dt / n) * w;
      ctx.strokeStyle = DV.colore("--s1");
      ctx.lineWidth = 2;
      ctx.strokeRect(a + 1, 1, b - a - 2, h - 2);
    }
    immagine = ctx.getImageData(0, 0, tl.width, tl.height);
    disegnaCursoreTimeline();
  }
  function disegnaCursoreTimeline() {
    if (!immagine || !S.sess) return;
    const ctx = tl.getContext("2d", { willReadFrequently: true });
    ctx.putImageData(immagine, 0, 0);
    const dpr = devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const x = (S.i / S.n) * tl.clientWidth;
    ctx.fillStyle = DV.colore("--testo");
    ctx.fillRect(x - 1, 0, 2, tl.clientHeight);
  }
  let trascinando = false;
  const daMouse = (e) => DV.vaiA((e.offsetX / tl.clientWidth) * S.n);
  tl.addEventListener("mousedown", (e) => { trascinando = true; daMouse(e); });
  tl.addEventListener("mousemove", (e) => trascinando && daMouse(e));
  window.addEventListener("mouseup", () => (trascinando = false));
  window.addEventListener("resize", () => disegnaTimeline());

  function aggiornaOra() {
    if (!S.sess) return;
    const t = S.i * S.dt;
    const g = DV.giroDi(S.i);
    const sg = DV.valore("s_giro");
    const cv = DV.testoCurva();
    $("#livelli").textContent = DV.testoLivelli();
    $("#ora").textContent = `t ${t.toFixed(2)} s` + (g ? ` · ${g.tipo === "lanciato" ? "giro " + g.numero : g.tipo === "uscita" ? "uscita box" : g.tipo}` : "") + (cv ? ` · ${cv}` : "") + (Number.isFinite(sg) ? ` · ${sg.toFixed(0)} m` : "");
    const q = DV.curvaDi();
    const sc = $("#curva");
    if (q && q.c && sc.value !== q.c.id) sc.value = q.c.id;
  }

  // ---------------------------------------------------------------- riproduzione e tastiera
  let gioca = false, ultimo = 0;
  function passo(ts) {
    if (!gioca) return;
    if (ultimo) {
      const dt = (ts - ultimo) / 1000 * +$("#velocita").value;
      const [, fine] = DV.intervallo();
      let i = S.i + dt / S.dt;
      if (i >= fine) { i = fine; gioca = false; $("#play").textContent = "▶"; }
      DV.vaiA(i);
    }
    ultimo = ts;
    requestAnimationFrame(passo);
  }
  $("#play").addEventListener("click", () => {
    gioca = !gioca;
    $("#play").textContent = gioca ? "❚❚" : "▶";
    ultimo = 0;
    if (gioca) requestAnimationFrame(passo);
  });
  $("#indietro").addEventListener("click", () => DV.vaiA(S.i - 1 / S.dt));
  $("#avanti").addEventListener("click", () => DV.vaiA(S.i + 1 / S.dt));
  document.addEventListener("keydown", (e) => {
    if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
    if (!S.sess) return;
    if (e.key === "ArrowLeft") { DV.vaiA(S.i - (e.shiftKey ? 1 / S.dt : 1)); e.preventDefault(); }
    if (e.key === "ArrowRight") { DV.vaiA(S.i + (e.shiftKey ? 1 / S.dt : 1)); e.preventDefault(); }
    if (e.key === " " && S.vista !== "mappe") { $("#play").click(); e.preventDefault(); }
  });

  // ---------------------------------------------------------------- tema
  // tema: automatico (segue il sistema), chiaro o scuro; la scelta resta in questo browser
  function applicaTema(t, ridisegna = true) {
    const r = document.documentElement;
    if (t) r.dataset.theme = t; else delete r.dataset.theme;
    $("#tema").value = t || "";
    try { if (t) localStorage.setItem("dv-tema", t); else localStorage.removeItem("dv-tema"); } catch (e) { /* senza memoria locale */ }
    if (ridisegna) { sporca(); disegnaTimeline(); }
  }
  $("#tema").addEventListener("change", (e) => applicaTema(e.target.value));
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (!document.documentElement.dataset.theme) { sporca(); disegnaTimeline(); } });
  try { applicaTema(localStorage.getItem("dv-tema") || "", false); } catch (e) { /* niente */ }

  // tooltip generico
  DV.tooltip = (e, html) => {
    const tt = $("#tooltip");
    if (!html) { tt.hidden = true; return; }
    tt.innerHTML = html;
    tt.hidden = false;
    const x = Math.min(e.clientX + 14, innerWidth - tt.offsetWidth - 8), y = Math.min(e.clientY + 14, innerHeight - tt.offsetHeight - 8);
    tt.style.left = x + "px"; tt.style.top = y + "px";
  };

  // avvio: se servito da "python -m dvtool visualizza" carica il progetto
  if (location.protocol.startsWith("http")) DV.caricaProgetto();
  aggiornaStatoCal();
})();
