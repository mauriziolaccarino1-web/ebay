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
  DV.on("sessione", () => { $("#vuoto").hidden = !!S.sess; aggiornaGiri(); aggiornaParametri(); sporca(); disegnaTimeline(); aggiornaOra(); });
  DV.on("modello", () => { sporca(); disegnaTimeline(); aggiornaParametri(); });
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
    const parti = [];
    if (S.struttura) parti.push(`${S.struttura.tabelle.length} tabelle`);
    if (S.binOrig) {
      const v = S.struttura ? DV.calib.verifica(S.struttura, S.binMod || S.binOrig) : [];
      const ok = v.every((x) => x.ok);
      parti.push(`${S.nomeMod || S.nomeOrig}${v.length ? (ok ? " · checksum ok" : " · checksum da ricalcolare (lo fa l'esportazione)") : " · nessun checksum definito"}`);
    }
    $("#stato-cal").textContent = parti.join(" · ");
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

  function aggiornaParametri() {
    const box = $("#parametri");
    box.innerHTML = "";
    if (!S.modello || !S.modello.parametri) return;
    for (const [k, v] of Object.entries(S.modello.parametri)) {
      const inp = el("input", { type: "number", value: S.parametri[k] ?? v, step: "1", title: `parametro del modello: ${k}` });
      inp.addEventListener("change", () => {
        S.parametri[k] = +inp.value;
        if (!S.binOrig) DV.avviso("per ricalcolare con un altro parametro carica il file .bin e la struttura", "errore");
        DV.ricalcola();
      });
      box.append(el("label", { class: "fila", style: { gap: "4px" } }, k, inp));
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
    // interventi previsti dal modello
    const r = S.ris.mod || S.ris.orig;
    if (r) {
      ctx.fillStyle = DV.colore("--critico");
      const L = r.logica;
      for (let px = 0; px < w; px++) {
        const i0 = Math.floor((px / w) * n), i1 = Math.floor(((px + 1) / w) * n);
        let on = false;
        for (let i = i0; i < i1 && !on; i++) on = L[i] > 0.5;
        if (on) ctx.fillRect(px, h - 6, 1, 6);
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
    $("#ora").textContent = `t ${t.toFixed(2)} s` + (g ? ` · ${g.tipo === "lanciato" ? "giro " + g.numero : g.tipo}` : "") + (Number.isFinite(sg) ? ` · ${sg.toFixed(0)} m` : "");
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
  $("#tema").addEventListener("click", () => {
    const r = document.documentElement;
    const scuro = r.dataset.theme ? r.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    r.dataset.theme = scuro ? "light" : "dark";
    try { localStorage.setItem("dv-tema", r.dataset.theme); } catch (e) { /* niente */ }
    sporca();
    disegnaTimeline();
  });
  try { const t = localStorage.getItem("dv-tema"); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* niente */ }

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
