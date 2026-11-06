/* Scheda Flusso dati: grafo della catena (CAN -> ingressi -> blocchi -> criteri -> rami -> logica -> uscita)
   con i valori al cursore, la traccia a monte del nodo scelto e la sequenza dei passi */
(function () {
  const DV = window.DV;
  const S = DV.stato;
  const { el } = DV;
  const radice = document.getElementById("v-flusso");
  const NS = "http://www.w3.org/2000/svg";
  const W = 168, H = 50, GX = 60, GY = 14;
  let scelto = null;

  function costruisciGrafo(M) {
    const nodi = new Map();
    const add = (id, tipo, sotto, dip, extra = {}) => nodi.set(id, Object.assign({ id, tipo, sotto, dip: [...new Set(dip)].filter((d) => d !== id) }, extra));
    const sorg = (S.sess.meta && S.sess.meta.sorgenti) || {};
    for (const ing of M.ingressi || []) {
      const s = sorg[ing.id];
      if (s) add("can:" + ing.id, "can", `${s.id_hex || ""} ${s.segnale}`, [], { etichetta: s.segnale.split(".").pop() });
      add(ing.id, "ingresso", ing.descrizione || ing.segnale || "", s ? ["can:" + ing.id] : []);
    }
    for (const k of Object.keys(M.parametri || {})) add(k, "parametro", "parametro", []);
    const noti = new Set(nodi.keys());
    for (const b of M.blocchi || []) {
      const dip = [...DV.modello.dipendenze(b)].filter((d) => noti.has(d) || (M.blocchi || []).some((x) => x.id === d));
      let sotto = b.tipo;
      if (b.tipo === "tabella") { sotto = "tabella " + DV.modello.nomeTabella(b.tabella, S.parametri); for (const p of (b.tabella.match(/\{(\w+)\}/g) || [])) dip.push(p.slice(1, -1)); }
      else if (b.tipo === "espressione") sotto = b.espressione;
      else if (b.tipo === "passabasso") sotto = b.alfa ? `filtro α=${b.alfa}` : `filtro τ=${b.tau_s}s`;
      add(b.id, "blocco", sotto, dip, { def: b });
    }
    for (const c of M.criteri || []) {
      const dip = [...DV.espr.nomi(String(c.valore)), ...(typeof c.soglia === "string" ? DV.espr.nomi(c.soglia) : [])];
      add(c.id, "criterio", `${c.valore} ${c.confronto || ">"} ${c.soglia}`, dip, { def: c, etichetta: `${c.id} ${c.nome}` });
    }
    for (const r of M.rami || []) add(r.id, "ramo", r.condizione, DV.espr.nomi(r.condizione), { etichetta: `${r.id} ${r.nome || ""}` });
    if (M.logica) add("logica", "logica", M.logica, DV.espr.nomi(M.logica));
    for (const u of M.uscite || []) add("u:" + u.id, "uscita", `${u.blocco} se ${u.attiva_se || "sempre"}`, [u.blocco, ...(u.attiva_se ? DV.espr.nomi(u.attiva_se) : [])], { etichetta: u.id, chiave: u.id });
    for (const o of M.osservati || []) add("o:" + o.id, "osservato", `dal CAN, confronto con ${o.confronta_con || "logica"}`, [o.confronta_con || "logica"], { etichetta: o.id, chiave: o.id, tratteggio: true });
    for (const n of nodi.values()) n.dip = n.dip.filter((d) => nodi.has(d));
    // profondità
    const prof = new Map();
    const p = (id) => {
      if (prof.has(id)) return prof.get(id);
      prof.set(id, 0);
      const n = nodi.get(id);
      const v = n.dip.length ? 1 + Math.max(...n.dip.map(p)) : n.tipo === "ingresso" || n.tipo === "parametro" ? 1 : 0;
      prof.set(id, v);
      return v;
    };
    for (const id of nodi.keys()) p(id);
    const colonne = [];
    for (const [id, d] of prof) (colonne[d] = colonne[d] || []).push(id);
    // ordine nelle colonne: baricentro dei genitori (due passate)
    const y = new Map();
    colonne.forEach((col) => col && col.forEach((id, k) => y.set(id, k)));
    for (let pass = 0; pass < 2; pass++) {
      colonne.forEach((col) => {
        if (!col) return;
        col.sort((a, b) => {
          const ba = nodi.get(a).dip.length ? nodi.get(a).dip.reduce((s, d) => s + y.get(d), 0) / nodi.get(a).dip.length : y.get(a);
          const bb = nodi.get(b).dip.length ? nodi.get(b).dip.reduce((s, d) => s + y.get(d), 0) / nodi.get(b).dip.length : y.get(b);
          return ba - bb;
        });
        col.forEach((id, k) => y.set(id, k));
      });
    }
    colonne.forEach((col, c) => col && col.forEach((id, k) => { const n = nodi.get(id); n.x = 10 + c * (W + GX); n.y = 10 + k * (H + GY); }));
    const larg = 20 + colonne.length * (W + GX), alt = 20 + Math.max(...colonne.filter(Boolean).map((c) => c.length)) * (H + GY);
    return { nodi, larg, alt };
  }

  function monte(nodi, id, out = new Set()) {
    if (out.has(id)) return out;
    out.add(id);
    const n = nodi.get(id);
    if (n) n.dip.forEach((d) => monte(nodi, d, out));
    return out;
  }

  function valoreNodo(n, r, i) {
    if (!r) return { testo: "", bool: null };
    if (n.tipo === "can") {
      const c = DV.canale(n.id.slice(4));
      return { testo: c ? DV.fmt(c.dati[i]) : "", bool: null };
    }
    if (n.tipo === "criterio") { const c = r.criteri[n.id]; return { testo: c.attivo[i] > 0.5 ? "soddisfatto" : `distanza ${DV.fmt(c.margine[i])}`, bool: c.attivo[i] > 0.5 }; }
    if (n.tipo === "ramo") return { testo: r.rami[n.id][i] > 0.5 ? "LAVORA" : "fermo", bool: r.rami[n.id][i] > 0.5 };
    if (n.tipo === "logica") return { testo: r.logica[i] > 0.5 ? "INTERVENTO" : "nessuno", bool: r.logica[i] > 0.5 };
    if (n.tipo === "uscita") return { testo: DV.fmt(r.uscite[n.chiave][i]), bool: r.logica[i] > 0.5 };
    if (n.tipo === "osservato") { const c = DV.canale(n.chiave); const v = c ? c.dati[i] : NaN; return { testo: c ? DV.fmt(v) : "–", bool: v > 0.5 }; }
    const v = r.env[n.id];
    if (!v) return { testo: "", bool: null };
    const b = n.def && n.def.tipo === "confronto" ? v[i] > 0.5 : null;
    const u = n.def && n.def.unita ? " " + n.def.unita : "";
    return { testo: DV.fmt(v[i]) + u, bool: b };
  }

  const taglia = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

  const vista = {
    disegna() {
      radice.innerHTML = "";
      const r = S.ris.mod || S.ris.orig;
      if (!S.sess || !S.modello) { radice.append(el("div", { class: "pannello" }, el("p", { class: "nota" }, "Carica una sessione e il modello."))); return; }
      const G = costruisciGrafo(S.modello);
      this.G = G;
      const svg = document.createElementNS(NS, "svg");
      svg.setAttribute("width", G.larg);
      svg.setAttribute("height", G.alt);
      const archi = document.createElementNS(NS, "g");
      svg.append(archi);
      this.archi = [];
      for (const n of G.nodi.values()) {
        for (const d of n.dip) {
          const a = G.nodi.get(d);
          const pth = document.createElementNS(NS, "path");
          const x1 = a.x + W, y1 = a.y + H / 2, x2 = n.x, y2 = n.y + H / 2;
          pth.setAttribute("d", `M${x1},${y1} C${x1 + GX / 2},${y1} ${x2 - GX / 2},${y2} ${x2},${y2}`);
          pth.setAttribute("class", "arco");
          if (n.tratteggio) pth.setAttribute("stroke-dasharray", "4 3");
          archi.append(pth);
          this.archi.push({ da: d, a: n.id, el: pth });
        }
      }
      this.elNodi = new Map();
      for (const n of G.nodi.values()) {
        const g = document.createElementNS(NS, "g");
        g.setAttribute("class", "nodo");
        g.setAttribute("transform", `translate(${n.x},${n.y})`);
        const rc = document.createElementNS(NS, "rect");
        rc.setAttribute("width", W); rc.setAttribute("height", H);
        if (n.tipo === "can" || n.tipo === "osservato") rc.setAttribute("stroke-dasharray", "4 3");
        const t1 = document.createElementNS(NS, "text"); t1.setAttribute("x", 8); t1.setAttribute("y", 15); t1.textContent = taglia(n.etichetta || n.id, 24);
        const t2 = document.createElementNS(NS, "text"); t2.setAttribute("x", 8); t2.setAttribute("y", 29); t2.setAttribute("class", "sub"); t2.textContent = taglia(n.sotto || n.tipo, 30);
        const t3 = document.createElementNS(NS, "text"); t3.setAttribute("x", 8); t3.setAttribute("y", 43); t3.setAttribute("class", "val");
        const ti = document.createElementNS(NS, "title"); ti.textContent = `${n.id} (${n.tipo})\n${n.sotto || ""}`;
        g.append(rc, t1, t2, t3, ti);
        g.addEventListener("click", () => { scelto = scelto === n.id ? null : n.id; this.evidenzia(); this.cursore(); });
        g.addEventListener("dblclick", () => {
          if (n.def && n.def.tipo === "tabella") { DV.emit("apriTabella", DV.modello.nomeTabella(n.def.tabella, S.parametri)); document.querySelector('#schede button[data-vista="mappe"]').click(); }
        });
        svg.append(g);
        this.elNodi.set(n.id, { g, val: t3 });
      }
      this.dettaglio = el("div", { class: "pannello" });
      this.sequenza = el("div", { class: "pannello scorre", style: { maxHeight: "48vh" } });
      radice.append(el("div", { class: "nota", style: { marginBottom: "8px" } },
        "Ogni riquadro è un passo della catena con il suo valore all'istante del cursore. Clic su un riquadro: evidenzia tutto ciò che lo alimenta (traccia a monte fino al segnale CAN). Doppio clic su una tabella: la apre nella scheda Mappe. In rosso ciò che è attivo."),
        el("div", { class: "flusso-wrap" }, el("div", { class: "flusso-svg" }, svg), el("div", { class: "righe" }, this.dettaglio, this.sequenza)));
      this.evidenzia();
      this.cursore();
      if (!r) this.dettaglio.append(el("p", { class: "nota" }, "Risultati del modello non disponibili."));
    },
    evidenzia() {
      const G = this.G;
      const m = scelto ? monte(G.nodi, scelto) : null;
      for (const [id, x] of this.elNodi) {
        x.g.classList.toggle("sel", id === scelto);
        x.g.classList.toggle("monte", !!m && m.has(id) && id !== scelto);
        x.g.classList.toggle("spento", !!m && !m.has(id));
      }
      for (const a of this.archi) a.el.classList.toggle("monte", !!m && m.has(a.a) && m.has(a.da));
    },
    cursore() {
      if (!this.G) return;
      const r = S.ris.mod || S.ris.orig;
      const i = S.i;
      const stati = new Map();
      for (const [id, x] of this.elNodi) {
        const n = this.G.nodi.get(id);
        const v = valoreNodo(n, r, i);
        x.val.textContent = v.testo;
        x.g.classList.toggle("vero", v.bool === true);
        stati.set(id, v);
      }
      for (const a of this.archi) a.el.classList.toggle("vero", stati.get(a.da) && stati.get(a.da).bool === true && stati.get(a.a) && stati.get(a.a).bool === true);
      // dettaglio e sequenza
      this.dettaglio.innerHTML = "";
      if (scelto) {
        const n = this.G.nodi.get(scelto);
        const v = stati.get(scelto);
        const ingressi = n.dip.map((d) => el("tr", {}, el("td", {}, d), el("td", { class: "n" }, stati.get(d) ? stati.get(d).testo : "")));
        this.dettaglio.append(el("h3", {}, `${n.etichetta || n.id}`), el("div", { class: "nota" }, `${n.tipo} · ${n.sotto || ""}`),
          el("div", { class: "grande", style: { margin: "6px 0" } }, v ? v.testo : ""),
          el("table", { class: "dati" }, el("thead", {}, el("tr", {}, el("th", {}, "ingresso"), el("th", { class: "n" }, "valore"))), el("tbody", {}, ingressi)));
      } else this.dettaglio.append(el("p", { class: "nota" }, "Nessun riquadro scelto: la sequenza sotto mostra tutti i passi in ordine di calcolo."));
      const ordine = [...this.G.nodi.values()].sort((a, b) => a.x - b.x || a.y - b.y);
      const m = scelto ? monte(this.G.nodi, scelto) : null;
      const righe = ordine.filter((n) => !m || m.has(n.id)).map((n, k) => el("tr", { class: n.id === scelto ? "sel" : "" },
        el("td", { class: "n" }, String(k + 1)), el("td", {}, n.etichetta || n.id), el("td", { class: "tenue" }, taglia(n.sotto || n.tipo, 38)),
        el("td", { class: "n" }, stati.get(n.id) ? stati.get(n.id).testo : "")));
      this.sequenza.innerHTML = "";
      this.sequenza.append(el("h3", {}, scelto ? `Sequenza a monte di ${scelto}` : "Sequenza completa"),
        el("table", { class: "dati" }, el("thead", {}, el("tr", {}, el("th", { class: "n" }, "#"), el("th", {}, "passo"), el("th", {}, "operazione"), el("th", { class: "n" }, "valore"))), el("tbody", {}, righe)));
    },
  };
  DV.registraVista("flusso", vista);
})();
