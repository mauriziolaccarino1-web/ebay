/* Scheda "Schema del software": schema a blocchi della centralina dei controlli (stile degli SVG del flusso),
   con corsie, tabelle ESPANSE dentro lo schema, il ramo attivo evidenziato e le celle su cui lavora la moto. */
(function () {
  const DV = window.DV;
  const S = DV.stato;
  const { el } = DV;
  const radice = document.getElementById("v-schema");
  const NS = "http://www.w3.org/2000/svg";

  // ---------------------------------------------------------------- stile (come modello_coppia_fuel_completo.svg)
  // corsie verticali da sinistra a destra, testata a pillola, blocchi bianchi con barra colorata,
  // connessioni curve, percorso importante come "bus" rosso spesso; tabelle su giallo chiaro (Simulink)
  const STILE = {
    font: "'Segoe UI', Arial, sans-serif", mono: "Consolas, ui-monospace, monospace",
    blocco: { w: 210, h: 66, r: 9, testa: 30 },
    cella: { w: 22, h: 14 },
    colW: 250, gapX: 74, margineX: 38, alto: 118, testaCorsia: 24, gapY: 18,
    corsie: [
      { id: "can", nome: "BUS CAN", col: "#64748b" },
      { id: "ingressi", nome: "INGRESSI", col: "#2563eb" },
      { id: "cond", nome: "CONDIZIONAMENTO", col: "#0891b2" },
      { id: "mappe", nome: "MAPPE E CURVE", col: "#b45309" },
      { id: "criteri", nome: "CRITERI", col: "#059669" },
      { id: "logica", nome: "RAMI E LOGICA", col: "#7c3aed" },
      { id: "uscite", nome: "USCITE → MOTORE", col: "#be123c" },
    ],
  };
  const corsiaDi = (n) => {
    if (n.def && n.def.corsia) return n.def.corsia;
    return { can: "can", ingresso: "ingressi", parametro: "ingressi", criterio: "criteri", ramo: "logica", logica: "logica", uscita: "uscite", osservato: "uscite" }[n.tipo]
      || (n.def && n.def.tipo === "tabella" ? "mappe" : "cond");
  };
  const SIMBOLO = { abs: "|u|", neg: "−u", min: "min", max: "max", somma: "Σ", prodotto: "Π", espressione: "f(u)", passabasso: "1/(τs+1)", derivata: "du/dt",
    rampa: "⟋", satura: "⊓", selettore: "⇄", confronto: ">", isteresi: "⊐", conferma: "⏱", ritardo: "z⁻ⁿ", costante: "k" };
  let scelto = null, zoom = 1, numeri = false;

  // ---------------------------------------------------------------- grafo
  function grafo(M) {
    const nodi = new Map();
    const add = (id, tipo, sotto, dip, extra = {}) => nodi.set(id, Object.assign({ id, tipo, sotto, dip: [...new Set(dip)].filter((d) => d !== id) }, extra));
    const sorg = (S.sess.meta && S.sess.meta.sorgenti) || {};
    for (const ing of M.ingressi || []) {
      const s = sorg[ing.id];
      if (s) add("can:" + ing.id, "can", `${s.id_hex || ""} ${s.segnale.split(".")[0]}`, [], { etichetta: s.segnale.split(".").pop() });
      add(ing.id, "ingresso", ing.unita || "", s ? ["can:" + ing.id] : [], { def: ing });
    }
    for (const k of Object.keys(M.parametri || {})) add(k, "parametro", "parametro", []);
    const ids = new Set([...nodi.keys(), ...(M.blocchi || []).map((b) => b.id)]);
    for (const b of M.blocchi || []) {
      const dip = [...DV.modello.dipendenze(b)].filter((d) => ids.has(d));
      let sotto = b.tipo;
      if (b.tipo === "tabella") { sotto = DV.modello.tabellaAl(DV.risVista(), b.id, S.i) || b.tabella; for (const p of b.tabella.match(/\{(\w+)\}/g) || []) dip.push(p.slice(1, -1)); }
      else if (b.tipo === "espressione") sotto = b.espressione;
      else if (b.tipo === "passabasso") sotto = b.alfa ? `α = ${b.alfa}` : `τ = ${b.tau_s} s`;
      add(b.id, "blocco", sotto, dip, { def: b });
    }
    for (const c of M.criteri || []) add(c.id, "criterio", `${c.valore} ${c.confronto || ">"} ${c.soglia}`,
      [...DV.espr.nomi(String(c.valore)), ...(typeof c.soglia === "string" ? DV.espr.nomi(c.soglia) : [])], { def: c, etichetta: `${c.id} ${c.nome}` });
    for (const r of M.rami || []) add(r.id, "ramo", r.condizione, DV.espr.nomi(r.condizione), { def: r, etichetta: `${r.id} ${r.nome || ""}` });
    if (M.logica) add("logica", "logica", M.logica, DV.espr.nomi(M.logica), { etichetta: "Logica" });
    for (const u of M.uscite || []) add("u:" + u.id, "uscita", `${u.blocco} se ${u.attiva_se || "sempre"}`, [u.blocco, ...(u.attiva_se ? DV.espr.nomi(u.attiva_se) : [])], { etichetta: u.id, chiave: u.id, def: u });
    for (const o of M.osservati || []) add("o:" + o.id, "osservato", "letto sul CAN", [o.confronta_con || "logica"], { etichetta: o.id, chiave: o.id, tratteggio: true });
    for (const n of nodi.values()) n.dip = n.dip.filter((d) => nodi.has(d));
    return nodi;
  }
  const monte = (nodi, id, out = new Set(), stop = null) => {
    if (out.has(id) || (stop && stop.has(id))) return out;
    out.add(id);
    const n = nodi.get(id);
    if (n) n.dip.forEach((d) => monte(nodi, d, out, stop));
    return out;
  };

  // ---------------------------------------------------------------- impaginazione: corsie verticali
  function impagina(nodi, buf) {
    const prof = new Map();
    const p = (id) => {
      if (prof.has(id)) return prof.get(id);
      prof.set(id, 0);
      const n = nodi.get(id);
      const v = n.dip.length ? 1 + Math.max(...n.dip.map(p)) : 0;
      prof.set(id, v);
      return v;
    };
    for (const id of nodi.keys()) p(id);
    for (const n of nodi.values()) {
      n.corsia = corsiaDi(n);
      n.w = STILE.blocco.w; n.h = STILE.blocco.h;
      if (n.tipo === "criterio") n.h = 90;
      if (n.def && n.def.tipo === "tabella") {
        const nome = DV.modello.tabellaAl(DV.risVista(), n.id, S.i) || (DV.risVista().usate[n.id] || {}).tabella;
        const tab = S.struttura && S.struttura.tabelle.find((t) => t.id === nome);
        if (tab && buf) {
          try {
            n.T = DV.calib.leggi(S.struttura, tab, buf);
            n.tab = tab;
            const C = n.T.z[0].length, R = n.T.z.length;
            n.w = Math.max(STILE.blocco.w, 40 + C * STILE.cella.w + 10);
            n.h = STILE.blocco.testa + 12 + (n.T.x ? 14 : 0) + R * STILE.cella.h + 24;
          } catch (e) { n.errore = e.message; }
        }
      }
    }
    const corsie = (S.modello.corsie || STILE.corsie).filter((c) => [...nodi.values()].some((n) => n.corsia === c.id)).map((c) => ({ ...c }));
    for (const n of nodi.values()) if (!corsie.find((c) => c.id === n.corsia)) corsie.push({ id: n.corsia, nome: n.corsia.toUpperCase(), col: "#0891b2" });
    let x = STILE.margineX;
    for (const c of corsie) {
      const larg = Math.max(STILE.colW, ...[...nodi.values()].filter((n) => n.corsia === c.id).map((n) => n.w + 30));
      c.x = x; c.w = larg;
      x += larg + STILE.gapX * 0.45;
    }
    // posizione verticale: in ordine di flusso, ogni blocco va all'altezza media di chi lo alimenta (senza sovrapporsi)
    const libero = new Map(corsie.map((c) => [c.id, STILE.alto + STILE.testaCorsia + 16]));
    const ordinati = [...nodi.values()].sort((a, b) => prof.get(a.id) - prof.get(b.id));
    for (const n of ordinati) {
      const c = corsie.find((q) => q.id === n.corsia);
      n.x = c.x + (c.w - n.w) / 2;
      const genitori = n.dip.map((d) => nodi.get(d)).filter((q) => q.y !== undefined);
      const voluto = genitori.length ? genitori.reduce((s2, q) => s2 + q.y + Math.min(q.h, 80) / 2, 0) / genitori.length - Math.min(n.h, 80) / 2 : 0;
      n.y = Math.max(libero.get(c.id), voluto);
      libero.set(c.id, n.y + n.h + STILE.gapY);
    }
    const alt = Math.max(...[...libero.values()]) + 20;
    for (const c of corsie) { c.y = STILE.alto; c.h = alt - STILE.alto - 10; }
    return { corsie, larg: x + STILE.margineX * 0.5, alt };
  }

  // ---------------------------------------------------------------- disegno
  const crea = (tag, attr = {}, padre) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attr)) if (v !== undefined && v !== null) e.setAttribute(k, v);
    if (padre) padre.append(e);
    return e;
  };
  const testo = (padre, x, y, s, cls, attr = {}) => { const t = crea("text", Object.assign({ x, y, class: cls }, attr), padre); t.textContent = s; return t; };
  const taglia = (s, n) => (s && s.length > n ? s.slice(0, n - 1) + "…" : s || "");

  // stile dentro l'SVG (così lo scaricato è autonomo); i colori seguono il tema della pagina con valori di riserva chiari
  const CSS_SCHEMA = `
  .sfondo { fill: var(--sch-bg, #f7f8fa); }
  .titolo-schema { font-size: 25px; font-weight: 800; fill: var(--sch-testo, #0f172a); }
  .sotto-schema { font-size: 13.5px; fill: var(--sch-sotto, #475569); font-variant-numeric: tabular-nums; }
  .legenda { font-size: 12.5px; fill: var(--sch-sotto, #475569); }
  .etichetta-corsia { font-size: 12px; font-weight: 700; fill: #fff; letter-spacing: .04em; }
  .centralina { fill: none; stroke: var(--sch-sotto, #475569); stroke-width: 1.2; stroke-dasharray: 6 4; }
  .arco { fill: none; stroke: #9aa3af; stroke-width: 1.5; opacity: .85; }
  .arco.taglio { stroke: #c0564b; stroke-dasharray: 5 3; }
  .arco.diag { stroke: #9a9a9a; stroke-width: 1.4; stroke-dasharray: 2 4; }
  .arco.on { stroke: #be123c; stroke-width: 3; opacity: .95; stroke-dasharray: none; }
  .arco.monte { stroke: #2563eb; stroke-width: 2.2; opacity: .9; }
  .nodo2 { cursor: pointer; }
  .nodo2 .corpo { fill: var(--sch-blocco, #ffffff); stroke-width: 1.5; }
  .nodo2 .corpo.lut { fill: var(--sch-lut, #fff6d5); }
  .nodo2 .t1 { font-size: 12.5px; font-weight: 700; fill: #fff; }
  .nodo2 .t2 { font-family: Consolas, ui-monospace, monospace; font-size: 9.3px; fill: #eef2ff; }
  .nodo2 .simbolo { font-family: Consolas, ui-monospace, monospace; font-size: 10px; font-weight: 700; fill: #fff; }
  .nodo2 .val { font-size: 11.5px; font-weight: 600; fill: var(--sch-testo, #1f2937); font-variant-numeric: tabular-nums; }
  .nodo2 .val2 { font-size: 10.5px; fill: var(--sch-sotto, #475569); font-variant-numeric: tabular-nums; }
  .nodo2 .asse { font-family: Consolas, ui-monospace, monospace; font-size: 8.5px; fill: var(--sch-sotto, #6b7280); }
  .nodo2 .num { font-family: Consolas, ui-monospace, monospace; font-size: 7.5px; fill: var(--sch-testo, #1f2937); pointer-events: none; }
  .nodo2 .num.chiaro { fill: #fff; }
  .nodo2 .num.nero { fill: #0b0b0b; }
  .nodo2 .barra-fondo { fill: var(--sch-barra, #e5e7eb); }
  .nodo2 .barra-soglia { fill: var(--sch-testo, #0f172a); }
  .cella-wp { fill: #ea580c; fill-opacity: calc(0.25 + var(--w, 0) * 0.7); stroke: var(--sch-testo, #0f172a); stroke-width: 1.6; pointer-events: none; }
  .mirino2 { stroke: var(--sch-testo, #0f172a); stroke-width: 1; stroke-dasharray: 3 2; opacity: .7; pointer-events: none; }
  .scia2 { stroke: #ea580c; stroke-width: 1.6; opacity: .8; pointer-events: none; }
  .nodo2.percorso .corpo { stroke: #be123c; stroke-width: 2.6; }
  .nodo2.vero .corpo { stroke: #be123c; stroke-width: 2.6; }
  .nodo2.sel .corpo { stroke: #2563eb; stroke-width: 3; }
  .nodo2.spento { opacity: .28; }
  `;
  const colCorsia = (L, n) => (L.corsie.find((c) => c.id === n.corsia) || { col: "#0891b2" }).col;

  const vista = {
    disegna() {
      radice.innerHTML = "";
      const r = DV.risVista();
      if (!S.sess || !S.modello || !r) { radice.append(el("div", { class: "pannello" }, el("p", { class: "nota" }, "Servono sessione e modello (e, per espandere le tabelle, struttura e .bin)."))); return; }
      const buf = DV.bufVista();
      const nodi = grafo(S.modello);
      const L = impagina(nodi, buf);
      this.nodi = nodi;
      const piu = el("button", { class: "bottone" }, "+"), meno = el("button", { class: "bottone" }, "−"), adatta = el("button", { class: "bottone" }, "adatta");
      const cbn = el("input", { type: "checkbox", checked: numeri || undefined });
      piu.addEventListener("click", () => { zoom *= 1.2; this.scala(); });
      meno.addEventListener("click", () => { zoom /= 1.2; this.scala(); });
      adatta.addEventListener("click", () => { zoom = Math.min(1.5, (this.cont.clientWidth - 10) / L.larg); this.scala(); });
      cbn.addEventListener("change", () => { numeri = cbn.checked; this.disegna(); });
      const scarica = el("button", { class: "bottone" }, "scarica SVG");
      scarica.addEventListener("click", () => DV.scarica(`schema_${DV.nomeVista()}_t${(S.i * S.dt).toFixed(2)}.svg`, new XMLSerializer().serializeToString(this.svg), "image/svg+xml"));
      radice.append(el("div", { class: "strumenti" }, DV.selettoreVista(() => this.disegna()), "zoom", meno, piu, adatta, el("label", { class: "fila" }, cbn, "numeri nelle celle"), scarica,
        el("span", { class: "nota" }, "clic su un blocco: traccia a monte · doppio clic su una tabella: Mappe · ▶ e frecce per ripercorrere il giro")));
      const svg = crea("svg", { width: L.larg, height: L.alt, viewBox: `0 0 ${L.larg} ${L.alt}`, class: "schema", "font-family": STILE.font });
      this.svg = svg; this.L = L;
      const stile = crea("style", {}, svg);
      stile.textContent = CSS_SCHEMA;
      const defs = crea("defs", {}, svg);
      const ombra = crea("filter", { id: "ombra", x: "-5%", y: "-5%", width: "110%", height: "120%" }, defs);
      crea("feDropShadow", { dx: 0, dy: 1, stdDeviation: 1.2, "flood-color": "#000", "flood-opacity": 0.12 }, ombra);
      const freccia = (id, col) => { const m = crea("marker", { id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 9, markerHeight: 9, orient: "auto-start-reverse", markerUnits: "userSpaceOnUse" }, defs); crea("path", { d: "M0,0 L10,5 L0,10 z", fill: col }, m); };
      freccia("m-fr", "#9aa3af"); freccia("m-on", "#be123c"); freccia("m-monte", "#2563eb"); freccia("m-taglio", "#c0564b"); freccia("m-diag", "#9a9a9a");
      crea("rect", { x: 0, y: 0, width: L.larg, height: L.alt, class: "sfondo" }, svg);
      // titolo, sottotitolo, legenda
      testo(svg, STILE.margineX, 40, (S.modello.centralina || "Centralina dei controlli") + " — catena del controllo in piega", "titolo-schema");
      this.sottotitolo = testo(svg, STILE.margineX, 64, "", "sotto-schema");
      const leg = crea("g", { transform: `translate(${STILE.margineX},86)` }, svg);
      let lx = 0;
      for (const [cls, nome] of [["on", "ramo che lavora e tutto ciò che lo alimenta"], ["fr", "flusso dei dati"], ["taglio", "verso l'uscita"], ["diag", "confronto con il CAN"]]) {
        crea("path", { d: `M${lx},0 H${lx + 26}`, class: "arco " + (cls === "fr" ? "" : cls), "marker-end": `url(#m-${cls === "on" ? "on" : cls})` }, leg);
        testo(leg, lx + 32, 4, nome, "legenda");
        lx += 46 + nome.length * 6.2;
      }
      crea("rect", { x: lx, y: -6, width: 12, height: 10, rx: 2, class: "cella-wp", style: "--w:0.8" }, leg);
      testo(leg, lx + 18, 4, "celle che la centralina sta leggendo (peso dell'interpolazione)", "legenda");
      // corsie verticali: banda tenue + pillola di testata
      for (const c of L.corsie) {
        crea("rect", { x: c.x, y: c.y, width: c.w, height: c.h, rx: 13, fill: c.col, "fill-opacity": 0.05, stroke: c.col, "stroke-opacity": 0.18 }, svg);
        crea("rect", { x: c.x + 8, y: c.y + 8, width: c.w - 16, height: STILE.testaCorsia, rx: 8, fill: c.col }, svg);
        testo(svg, c.x + c.w / 2, c.y + 8 + 16.5, c.nome, "etichetta-corsia", { "text-anchor": "middle" });
      }
      // contenitore della centralina: tutte le corsie tranne il bus CAN
      const dentro = L.corsie.filter((c) => c.id !== "can");
      if (dentro.length && dentro.length < L.corsie.length) {
        const x0 = dentro[0].x - 8, x1 = dentro[dentro.length - 1].x + dentro[dentro.length - 1].w + 8;
        crea("rect", { x: x0, y: L.corsie[0].y - 10, width: x1 - x0, height: L.corsie[0].h + 18, rx: 16, class: "centralina" }, svg);
      }
      // connessioni curve (Bezier)
      const gArchi = crea("g", {}, svg);
      this.archi = [];
      const conta = new Map();
      for (const n of nodi.values()) n.dip.forEach((d, k) => conta.set(n.id + "|" + d, [k, n.dip.length]));
      for (const n of nodi.values()) {
        for (const d of n.dip) {
          const a = nodi.get(d);
          const [k, tot] = conta.get(n.id + "|" + d);
          const avanti = a.x + a.w <= n.x;
          const x1 = avanti ? a.x + a.w : a.x + a.w / 2, y1 = avanti ? a.y + STILE.blocco.testa / 2 + 6 : a.y + a.h;
          const x2 = n.x, y2 = n.y + STILE.blocco.testa + 8 + (k * 12) % Math.max(12, Math.min(n.h - STILE.blocco.testa - 10, tot * 12));
          const dx = Math.max(40, Math.abs(x2 - x1) * 0.45);
          const dpath = avanti ? `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2 - 2},${y2}` : `M${x1},${y1} C${x1},${y1 + 60} ${x2 - 80},${y2} ${x2 - 2},${y2}`;
          const tipo = n.tipo === "osservato" ? "diag" : n.tipo === "uscita" ? "taglio" : "";
          const path = crea("path", { d: dpath, class: "arco " + tipo, "marker-end": `url(#m-${tipo || "fr"})` }, gArchi);
          // porta d'ingresso: triangolino nel colore della corsia
          crea("path", { d: `M${x2 - 1},${y2 - 4} L${x2 + 5},${y2} L${x2 - 1},${y2 + 4} z`, fill: colCorsia(L, n) }, gArchi);
          this.archi.push({ da: d, a: n.id, el: path, tipo });
        }
      }
      this.el = new Map();
      for (const n of nodi.values()) this.el.set(n.id, this.blocco(svg, n, colCorsia(L, n)));
      this.cont = el("div", { class: "flusso-svg" }, svg);
      this.dettaglio = el("div", { class: "pannello" });
      this.sequenza = el("div", { class: "pannello scorre", style: { maxHeight: "50vh" } });
      radice.append(el("div", { class: "flusso-wrap" }, this.cont, el("div", { class: "righe" }, this.dettaglio, this.sequenza)));
      if (zoom === 1 && this.cont.clientWidth && L.larg > this.cont.clientWidth) zoom = Math.max(0.45, (this.cont.clientWidth - 10) / L.larg);
      this.scala();
      this.cursore();
    },

    scala() {
      if (!this.svg) return;
      this.svg.setAttribute("width", this.L.larg * zoom);
      this.svg.setAttribute("height", this.L.alt * zoom);
    },

    blocco(svg, n, col) {
      const H = STILE.blocco.testa;
      const g = crea("g", { class: "nodo2 " + n.tipo + (n.def && n.def.tipo ? " b-" + n.def.tipo : ""), transform: `translate(${n.x},${n.y})` }, svg);
      const rc = crea("rect", { width: n.w, height: n.h, rx: STILE.blocco.r, class: "corpo" + (n.T ? " lut" : ""), stroke: col, filter: "url(#ombra)" }, g);
      if (n.tipo === "can" || n.tipo === "osservato") rc.setAttribute("stroke-dasharray", "4 3");
      // barra di testata colorata con titolo bianco e sottotitolo mono
      const clip = crea("clipPath", { id: "cl-" + n.id.replace(/[^\w-]/g, "_") }, g);
      crea("rect", { width: n.w, height: n.h, rx: STILE.blocco.r }, clip);
      crea("rect", { width: n.w, height: H, fill: col, "clip-path": `url(#cl-${n.id.replace(/[^\w-]/g, "_")})` }, g);
      testo(g, 9, 13.5, taglia(n.etichetta || n.id, Math.floor((n.w - 40) / 7.4)), "t1");
      testo(g, 9, 25, taglia(n.sotto || n.tipo, Math.floor((n.w - 16) / 5.4)), "t2");
      const simb = n.T ? null : n.def && n.def.tipo ? SIMBOLO[n.def.tipo] : n.tipo === "criterio" ? (n.def.confronto || ">") : n.tipo === "ramo" ? "AND" : n.tipo === "logica" ? "OR" : "";
      if (simb) testo(g, n.w - 8, 14, simb, "simbolo", { "text-anchor": "end" });
      if (n.T) { // glifo "mini griglia" delle lookup table
        const gx = n.w - 24, gy = 6;
        for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) crea("rect", { x: gx + b * 5.5, y: gy + a * 5.5, width: 4.5, height: 4.5, fill: "#fff", "fill-opacity": a === 1 && b === 1 ? 1 : 0.55 }, g);
      }
      const val = testo(g, 9, n.h - 12, "", "val");
      const out = { g, rc, val, col };
      if (n.tipo === "criterio") {
        crea("rect", { x: 9, y: H + 7, width: n.w - 18, height: 8, rx: 3, class: "barra-fondo" }, g);
        out.barra = crea("rect", { x: 9, y: H + 7, width: 0, height: 8, rx: 3, fill: col }, g);
        out.soglia = crea("rect", { x: 9, y: H + 3, width: 2, height: 16, class: "barra-soglia" }, g);
        out.sub = testo(g, 9, H + 31, "", "val2");
        val.setAttribute("y", n.h - 9);
      }
      if (n.T) {
        const T = n.T, R = T.z.length, C = T.z[0].length, cw = STILE.cella.w, ch = STILE.cella.h;
        const x0 = 36, y0 = H + 10 + (T.x ? 14 : 0);
        let mn = Infinity, mx = -Infinity;
        for (const rr of T.z) for (const v of rr) { mn = Math.min(mn, v); mx = Math.max(mx, v); }
        const dec = Math.max(0, Math.min(2, -Math.floor(Math.log10(Math.abs(n.tab.scala ?? 1) || 1))));
        out.celle = [];
        out.ax = []; out.ay = [];
        if (T.x) T.x.valori.forEach((v, j) => out.ax.push(C <= 14 || j % 2 === 0 || j === C - 1 ? testo(g, x0 + j * cw + cw / 2, y0 - 4, DV.fmt(v, Math.abs(v) >= 100 ? 0 : 1), "asse", { "text-anchor": "middle" }) : null));
        if (T.y) T.y.valori.forEach((v, i) => out.ay.push(testo(g, x0 - 4, y0 + i * ch + ch - 3.5, DV.fmt(v, Math.abs(v) >= 100 ? 0 : 1), "asse", { "text-anchor": "end" })));
        for (let i = 0; i < R; i++) {
          const riga = [];
          for (let j = 0; j < C; j++) {
            const q = mx > mn ? (T.z[i][j] - mn) / (mx - mn) : 0;
            const c = crea("rect", { x: x0 + j * cw, y: y0 + i * ch, width: cw - 1, height: ch - 1, rx: 1.5, fill: DV.seq(q), class: "cella" }, g);
            const ti = crea("title", {}, c); ti.textContent = `${T.y ? `${T.y.unita} ${DV.fmt(T.y.valori[i])} · ` : ""}${T.x ? `${T.x.unita} ${DV.fmt(T.x.valori[j])}` : ""} → ${T.z[i][j].toFixed(dec)} ${n.tab.unita || ""}`;
            if (numeri) testo(g, x0 + j * cw + cw / 2, y0 + i * ch + ch - 3.5, T.z[i][j].toFixed(dec), "num" + (q > 0.55 ? (DV.scuro() ? " nero" : " chiaro") : ""), { "text-anchor": "middle" });
            riga.push(c);
          }
          out.celle.push(riga);
        }
        out.scia = crea("path", { class: "scia2", fill: "none" }, g);
        out.peso = [0, 1, 2, 3].map(() => crea("rect", { width: cw - 1, height: ch - 1, rx: 1.5, class: "cella-wp", visibility: "hidden" }, g));
        out.mirV = crea("line", { class: "mirino2", visibility: "hidden" }, g);
        out.mirH = crea("line", { class: "mirino2", visibility: "hidden" }, g);
        out.geo = { x0, y0, cw, ch, R, C };
        val.setAttribute("y", y0 + R * ch + 15);
      }
      g.addEventListener("click", () => { scelto = scelto === n.id ? null : n.id; this.cursore(); });
      g.addEventListener("dblclick", () => { if (n.tab) { DV.emit("apriTabella", n.tab.id); document.querySelector('#schede button[data-vista="mappe"]').click(); } });
      return out;
    },

    cursore() {
      if (!this.nodi || !this.el) return;
      const r = DV.risVista();
      if (!r) return;
      const i = S.i, nodi = this.nodi;
      // il livello è cambiato: il blocco legge un'altra tabella, ridisegna lo schema
      for (const n of nodi.values()) if (n.tab) { const nm = DV.modello.tabellaAl(r, n.id, i); if (nm && nm !== n.tab.id) { this.disegna(); return; } }
      // ramo attivo: rami accesi + logica; tutto ciò che li alimenta
      // percorso attivo: i rami accesi e ciò che li alimenta; logica e uscite senza passare dai rami fermi
      const attivi = new Set();
      const fermi = new Set();
      for (const n of nodi.values()) {
        if (n.tipo !== "ramo" || !r.rami[n.id]) continue;
        if (r.rami[n.id][i] > 0.5) monte(nodi, n.id, attivi); else fermi.add(n.id);
      }
      const L = r.logica[i] > 0.5;
      if (L) {
        if (nodi.has("logica")) monte(nodi, "logica", attivi, fermi);
        for (const n of nodi.values()) if (n.tipo === "uscita" || n.tipo === "osservato") monte(nodi, n.id, attivi, fermi);
      }
      const traccia = scelto ? monte(nodi, scelto) : null;
      for (const [id, e] of this.el) {
        const n = nodi.get(id);
        let v = "", vero = null;
        if (n.tipo === "can") { const c = DV.canale(id.slice(4)); v = c ? DV.fmt(c.dati[i]) : ""; }
        else if (n.tipo === "criterio") {
          const C = r.criteri[id];
          vero = C.attivo[i] > 0.5;
          v = vero ? "✓ soddisfatto" : `manca ${DV.fmt(Math.abs(C.margine[i]))} ${n.def.unita || ""}`;
          e.sub.textContent = `${DV.fmt(C.valore[i])} ${n.def.confronto || ">"} ${DV.fmt(C.soglia[i])} ${n.def.unita || ""}`;
          const fondo = Math.max(Math.abs(C.soglia[i]) * 1.6, Math.abs(C.valore[i]) * 1.05, 1e-9), wmax = n.w - 18;
          e.barra.setAttribute("width", Math.max(0, Math.min(1, C.valore[i] / fondo)) * wmax);
          e.soglia.setAttribute("x", 9 + Math.max(0, Math.min(1, C.soglia[i] / fondo)) * wmax - 1);
        } else if (n.tipo === "ramo") { vero = r.rami[id][i] > 0.5; v = vero ? "LAVORA" : "fermo"; }
        else if (n.tipo === "logica") { vero = L; v = L ? "INTERVENTO" : "nessun intervento"; }
        else if (n.tipo === "uscita") { v = DV.fmt(r.uscite[n.chiave][i]) + " " + (n.def.unita || ""); vero = L; }
        else if (n.tipo === "osservato") { const c = DV.canale(n.chiave); v = c ? DV.fmt(c.dati[i]) : "–"; vero = c ? c.dati[i] > 0.5 : null; }
        else { const a = r.env[id]; v = a ? DV.fmt(a[i]) + (n.def && n.def.unita ? " " + n.def.unita : "") : ""; if (n.def && n.def.tipo === "confronto") vero = a[i] > 0.5; }
        e.val.textContent = v;
        e.g.classList.toggle("vero", vero === true);
        e.g.classList.toggle("percorso", attivi.has(id));
        e.g.classList.toggle("sel", id === scelto);
        e.g.classList.toggle("spento", !!traccia && !traccia.has(id));
        if (n.T) this.celleAttive(n, e, r, i);
      }
      for (const a of this.archi) {
        const on = attivi.has(a.a) && attivi.has(a.da);
        const mt = traccia && traccia.has(a.a) && traccia.has(a.da);
        a.el.setAttribute("class", "arco " + (on ? "on" : mt ? "monte" : a.tipo));
        a.el.setAttribute("marker-end", `url(#m-${on ? "on" : mt ? "monte" : a.tipo || "fr"})`);
      }
      const ramiOn = [...nodi.values()].filter((n) => n.tipo === "ramo" && r.rami[n.id][i] > 0.5).map((n) => n.etichetta);
      this.sottotitolo.textContent = `t ${(i * S.dt).toFixed(2)} s · calcolato con ${DV.nomeVista()} · ${DV.testoLivelli(i, r)} · ` + (ramiOn.length ? "ramo attivo: " + ramiOn.join(", ") : r.logica[i] > 0.5 ? "intervento" : "nessun ramo attivo");
      this.pannelli(r, i, attivi);
    },

    celleAttive(n, e, r, i) {
      const u = r.usate[n.id] || {};
      const { x0, y0, cw, ch, R, C } = e.geo;
      const T = n.T;
      e.peso.forEach((p) => p.setAttribute("visibility", "hidden"));
      e.mirV.setAttribute("visibility", "hidden"); e.mirH.setAttribute("visibility", "hidden");
      e.scia.setAttribute("d", "");
      if (!T.x) { e.peso[0].setAttribute("x", x0); e.peso[0].setAttribute("y", y0); e.peso[0].setAttribute("visibility", "visible"); e.peso[0].style.setProperty("--w", 1); return; }
      const xv = u.x ? u.x[i] : NaN, yv = u.y ? u.y[i] : NaN;
      if (!Number.isFinite(xv)) return;
      const fx = DV.calib.posizione(T.x.valori, xv), j0 = Math.floor(fx), wx = fx - j0, j1 = Math.min(j0 + 1, C - 1);
      let fy = 0, i0 = 0, wy = 0, i1 = 0;
      if (T.y && Number.isFinite(yv)) { fy = DV.calib.posizione(T.y.valori, yv); i0 = Math.floor(fy); wy = fy - i0; i1 = Math.min(i0 + 1, R - 1); }
      [[i0, j0, (1 - wx) * (1 - wy)], [i0, j1, wx * (1 - wy)], [i1, j0, (1 - wx) * wy], [i1, j1, wx * wy]].forEach(([a, b, w], k) => {
        if (w < 0.01) return;
        const p = e.peso[k];
        p.setAttribute("x", x0 + b * cw); p.setAttribute("y", y0 + a * ch);
        p.style.setProperty("--w", w.toFixed(3));
        p.setAttribute("visibility", "visible");
      });
      const X = x0 + (j0 + wx) * cw + cw / 2 - (j0 + wx >= C - 1 ? cw / 2 * 0 : 0), Y = y0 + (i0 + wy) * ch + ch / 2;
      e.mirV.setAttribute("x1", X); e.mirV.setAttribute("x2", X); e.mirV.setAttribute("y1", y0 - 2); e.mirV.setAttribute("y2", y0 + R * ch); e.mirV.setAttribute("visibility", "visible");
      if (T.y) { e.mirH.setAttribute("x1", x0 - 2); e.mirH.setAttribute("x2", x0 + C * cw); e.mirH.setAttribute("y1", Y); e.mirH.setAttribute("y2", Y); e.mirH.setAttribute("visibility", "visible"); }
      // scia degli ultimi 1.5 s
      const passi = Math.round(1.5 / S.dt);
      let d = "";
      for (let k = Math.max(0, i - passi); k <= i; k += 3) {
        if (!Number.isFinite(u.x[k])) continue;
        const px = x0 + DV.calib.posizione(T.x.valori, u.x[k]) * cw + cw / 2;
        const py = T.y && u.y ? y0 + DV.calib.posizione(T.y.valori, u.y[k]) * ch + ch / 2 : y0 + ch / 2;
        d += (d ? "L" : "M") + px.toFixed(1) + "," + py.toFixed(1);
      }
      e.scia.setAttribute("d", d);
      e.val.textContent = `x ${DV.fmt(xv)}${T.y ? ` · y ${DV.fmt(yv)}` : ""} → ${DV.fmt(r.env[n.id][i])} ${n.tab.unita || ""}`;
    },

    pannelli(r, i, attivi) {
      const nodi = this.nodi;
      this.dettaglio.innerHTML = "";
      const rami = [...nodi.values()].filter((n) => n.tipo === "ramo");
      const L = r.logica[i] > 0.5;
      this.dettaglio.append(el("h3", {}, `t ${(i * S.dt).toFixed(2)} s · ${DV.nomeVista()}`),
        el("div", { class: "stato " + (L ? "si" : "no") }, el("span", { class: "pallino" }), L ? "intervento" : "nessun intervento"),
        el("div", { class: "nota", style: { marginTop: "6px" } }, rami.map((n) => `${r.rami[n.id][i] > 0.5 ? "●" : "○"} ${n.etichetta}`).join(" · ")));
      if (scelto) {
        const n = nodi.get(scelto);
        this.dettaglio.append(el("h4", { style: { marginTop: "10px" } }, `${n.etichetta || n.id}`), el("div", { class: "nota" }, `${n.tipo} · ${n.sotto || ""}`),
          el("table", { class: "dati" }, el("tbody", {}, n.dip.map((d) => el("tr", {}, el("td", {}, d), el("td", { class: "n" }, this.el.get(d).val.textContent))))));
      }
      const ordine = [...nodi.values()].sort((a, b) => a.x - b.x || a.y - b.y);
      const m = scelto ? monte(nodi, scelto) : null;
      this.sequenza.innerHTML = "";
      this.sequenza.append(el("h3", {}, scelto ? `Sequenza a monte di ${scelto}` : "Sequenza dei passi"),
        el("table", { class: "dati" }, el("tbody", {}, ordine.filter((n) => !m || m.has(n.id)).map((n, k) => el("tr", { class: attivi.has(n.id) ? "sel" : "" },
          el("td", { class: "n" }, String(k + 1)), el("td", {}, n.etichetta || n.id), el("td", { class: "n" }, this.el.get(n.id).val.textContent))))));
    },
  };
  DV.registraVista("schema", vista);
})();
