/* Scheda "Trigger per ramo": per ogni ramo della logica, quanto manca al trigger della derivata (di potenza,
   di slittamento… il criterio a derivata del ramo) e quanto manca al ramo intero; dove nel giro ci si avvicina. */
(function () {
  const DV = window.DV;
  const S = DV.stato;
  const { el } = DV;
  const radice = document.getElementById("v-trigger");

  // il criterio è "a derivata"? esplicito (derivata: true) o perché a monte del valore c'è un blocco derivata
  function aMonte(M, nome, visti = new Set()) {
    if (visti.has(nome)) return visti;
    visti.add(nome);
    const b = (M.blocchi || []).find((x) => x.id === nome);
    if (b) for (const d of DV.modello.dipendenze(b)) aMonte(M, d, visti);
    return visti;
  }
  function eDerivata(M, c) {
    if (c.derivata !== undefined) return !!c.derivata;
    const nomi = DV.espr.nomi(String(c.valore));
    const monte = new Set();
    nomi.forEach((n) => aMonte(M, n, monte));
    return [...monte].some((n) => { const b = (M.blocchi || []).find((x) => x.id === n); return b && b.tipo === "derivata"; });
  }
  function scala(c, R) {
    if (c.scala) return c.scala;
    const v = [];
    for (let i = 0; i < R.soglia.length; i += 13) if (Number.isFinite(R.soglia[i])) v.push(Math.abs(R.soglia[i]));
    v.sort((a, b) => a - b);
    return v[Math.floor(v.length * 0.9)] || 1;
  }
  // termini del ramo legati ai criteri: stato richiesto e distanza normalizzata per arrivarci
  function terminiRamo(M, ra) {
    return DV.espr.termini(ra.condizione).map((t) => ({ ...t, crit: (M.criteri || []).find((c) => c.id === t.id) || null }));
  }

  function analisi(r) {
    const M = S.modello;
    const n = S.n;
    const rami = (M.rami && M.rami.length) ? M.rami : DV.espr.termini_or(M.logica || "").map((t, k) => ({ id: "R" + (k + 1), nome: "", condizione: t }));
    return rami.map((ra) => {
      const term = terminiRamo(M, ra);
      const sc = new Map(term.filter((t) => t.crit).map((t) => [t.id, scala(t.crit, r.criteri[t.id])]));
      // distanza del ramo = il termine più lontano dallo stato richiesto
      const dist = new Float32Array(n);
      for (let i = 0; i < n; i++) {
        let d = 0;
        for (const t of term) {
          if (!t.crit) continue;
          const m = r.criteri[t.id].margine[i] / sc.get(t.id);
          d = Math.max(d, t.negato ? Math.max(-m, 0) : Math.max(m, 0));
        }
        dist[i] = d;
      }
      const der = term.filter((t) => t.crit && eDerivata(M, t.crit)).map((t) => {
        const R = r.criteri[t.id];
        const norm = new Float32Array(n);
        for (let i = 0; i < n; i++) norm[i] = R.margine[i] / sc.get(t.id);
        // velocità di avvicinamento (unità/s), media su ~50 ms
        const k = Math.max(1, Math.round(0.025 / S.dt));
        const vel = new Float32Array(n);
        for (let i = k; i < n - k; i++) vel[i] = -(R.margine[i + k] - R.margine[i - k]) / (2 * k * S.dt);
        return { t, c: t.crit, R, norm, vel, sc: sc.get(t.id) };
      });
      return { ra, term, dist, der, attivo: r.rami[ra.id] || r.logica };
    });
  }

  const vista = {
    alGiro: true,
    disegna() {
      DV.pulisciGrafici(radice);
      radice.innerHTML = "";
      const r = DV.risVista();
      if (!S.sess || !S.modello || !r) { radice.append(el("div", { class: "pannello" }, el("p", { class: "nota" }, "Servono sessione e modello."))); return; }
      this.A = analisi(r);
      const nDer = this.A.reduce((s, x) => s + x.der.length, 0);
      radice.append(el("div", { class: "strumenti" }, DV.selettoreVista(() => this.disegna()),
        el("span", { class: "nota" }, nDer ? "Il criterio a derivata è quello che nel modello ha \"derivata\": true, oppure un blocco «derivata» a monte del valore. Distanze in frazione della soglia: 0 = trigger, sotto zero = superato."
          : "Nessun criterio a derivata nel modello: segna il criterio con \"derivata\": true. Sotto c'è comunque la distanza di ogni ramo dal suo trigger.")));
      this.carte = el("div", { class: "carte" });
      radice.append(this.carte);
      const gr = el("div", { class: "pannello", style: { marginTop: "12px" } });
      radice.append(gr);
      for (const a of this.A) {
        const box = el("div");
        gr.append(box);
        const serie = a.der.map((d, k) => ({ nome: `${d.c.id} derivata (× soglia)`, dati: d.norm, colore: DV.colSerie(k + 3) }));
        serie.push({ nome: "distanza del ramo (termine più lontano)", dati: a.dist, colore: DV.colore("--testo-2"), tratteggio: [5, 4] });
        DV.grafico(box, { titolo: `${a.ra.id}${a.ra.nome ? " · " + a.ra.nome : ""} — ${a.ra.condizione}`, unita: "× soglia", y: [-1, 2], altezza: 150, serie, bande: [{ dati: a.attivo }] });
      }
      gr.append(el("div", { class: "nota" }, "Banda rossa = ramo che lavora. La linea tratteggiata è la distanza del ramo intero dal suo trigger: diventa 0 quando tutte le condizioni del ramo sono vere."));
      this.perDistanza(radice);
      this.perCurva(radice);
      this.tabella(radice);
      this.cursore();
    },

    perDistanza(dove) {
      const G = S.sess.giri, sg = DV.canale("s_giro"), ng = DV.canale("n_giro");
      if (!G || !sg || !this.A.some((a) => a.der.length)) return;
      const lanc = G.giri.filter((g) => g.tipo === "lanciato").slice(0, 6);
      const ds = 10, nb = Math.ceil(G.lunghezza_giro / ds);
      const xs = new Float64Array(nb).map((_, k) => k * ds);
      const box = el("div", { class: "pannello", style: { marginTop: "12px" } }, el("h3", {}, "Dove nel giro ci si avvicina al trigger della derivata"),
        el("div", { class: "nota" }, "Minimo della distanza dal trigger ogni 10 m, giro per giro (giri lanciati). Le punte verso lo zero sono i punti della pista in cui la derivata sta per far scattare il ramo."));
      dove.append(box);
      for (const a of this.A) for (const d of a.der) {
        const serie = lanc.map((g, k) => {
          const v = new Float32Array(nb).fill(NaN);
          const i0 = DV.indiceDaTempo(DV.tRel(g.t_inizio)), i1 = DV.indiceDaTempo(DV.tRel(g.t_fine));
          for (let i = i0; i < i1; i++) {
            if (ng.dati[i] !== g.numero) continue;
            const b = Math.floor(sg.dati[i] / ds);
            if (b < 0 || b >= nb) continue;
            if (!(d.norm[i] >= v[b])) v[b] = d.norm[i];
          }
          return { nome: `giro ${g.numero}`, dati: v, colore: DV.colSerie(k) };
        });
        const g = el("div");
        box.append(g);
        DV.grafico(g, { titolo: `${a.ra.id} · ${d.c.id} ${d.c.nome}`, x: xs, gruppo: "distanza", unita: "× soglia", etichettaX: "distanza nel giro (m)", y: [-1, 2], altezza: 170, curve: true,
          serie, xDi: (i) => DV.valore("s_giro", i), alClic: () => {} });
      }
    },

    // per ogni curva: quante volte scatta ogni ramo e quanto ci si avvicina al trigger della derivata (giri lanciati)
    perCurva(dove) {
      const C = DV.curve(), sg = DV.canale("s_giro"), ng = DV.canale("n_giro");
      if (!C.length || !sg) return;
      const lanc = new Set(DV.giri().filter((g) => g.tipo === "lanciato").map((g) => g.numero));
      const col = [];
      for (const a of this.A) { col.push({ a, d: null }); for (const d of a.der) col.push({ a, d }); }
      const righe = C.map((c) => {
        const celle = col.map((k) => {
          let n = 0, prima = false, mn = Infinity, dove = -1;
          for (let i = 0; i < S.n; i++) {
            const s = sg.dati[i];
            const dentro = lanc.has(ng.dati[i]) && s >= c.inizio && s <= c.fine;
            if (!dentro) { prima = false; continue; }
            if (!k.d) { const on = k.a.attivo[i] > 0.5; if (on && !prima) n++; prima = on; }
            else if (k.d.norm[i] < mn) { mn = k.d.norm[i]; dove = i; }
          }
          if (!k.d) return el("td", { class: "n" }, String(n));
          const g = dove >= 0 ? ng.dati[dove] : null;
          return el("td", { class: "n", "data-i": dove }, mn === Infinity ? "–" : `${mn.toFixed(2)} · giro ${g}`);
        });
        return el("tr", {}, el("td", {}, DV.nomeCurva(c)), el("td", {}, c.verso || ""), ...celle);
      });
      const testa = el("tr", {}, el("th", {}, "curva"), el("th", {}, "verso"),
        ...col.map((k) => el("th", { class: "n" }, k.d ? `${k.a.ra.id} ${k.d.c.id}: min · giro` : `${k.a.ra.id}: scatti`)));
      const tab = el("table", { class: "dati" }, el("thead", {}, testa), el("tbody", {}, righe));
      tab.addEventListener("click", (e) => { const td = e.target.closest("td[data-i]"); if (td && +td.dataset.i >= 0) DV.vaiA(+td.dataset.i); });
      dove.append(el("div", { class: "pannello", style: { marginTop: "12px" } }, el("h3", {}, "Per curva (giri lanciati)"),
        el("div", { class: "nota" }, "scatti = quante volte il ramo si accende dentro la curva, sommando i giri lanciati; min = distanza minima dal trigger della derivata e in quale giro. Clic su un valore: il cursore va lì."),
        el("div", { class: "scorre" }, tab)));
    },

    tabella(dove) {
      const giri = DV.giri();
      if (!giri.length) return;
      const sg = DV.canale("s_giro");
      const col = [];
      for (const a of this.A) {
        col.push({ a, d: null });
        for (const d of a.der) col.push({ a, d });
      }
      const testa = el("tr", {}, el("th", {}, "giro"), el("th", { class: "n" }, "tempo"),
        ...col.map((c) => el("th", { class: "n" }, c.d ? `${c.a.ra.id} ${c.d.c.id}: min · dove` : `${c.a.ra.id}: scatti · s`)));
      const righe = giri.map((g) => {
        const i0 = DV.indiceDaTempo(DV.tRel(g.t_inizio)), i1 = DV.indiceDaTempo(DV.tRel(g.t_fine));
        const celle = col.map((c) => {
          if (!c.d) {
            let n = 0, t = 0, prima = false;
            for (let i = i0; i < i1; i++) { const on = c.a.attivo[i] > 0.5; if (on) { t++; if (!prima) n++; } prima = on; }
            return el("td", { class: "n" }, `${n} · ${(t * S.dt).toFixed(2)}`);
          }
          let mn = Infinity, dove = -1;
          for (let i = i0; i < i1; i++) if (c.d.norm[i] < mn) { mn = c.d.norm[i]; dove = i; }
          const s = sg && dove >= 0 ? sg.dati[dove] : NaN;
          const q = dove >= 0 ? DV.curvaDi(dove) : null;
          const dc = q ? (q.c ? ` ${q.c.id}` : " rettilineo") : "";
          return el("td", { class: "n", "data-i": dove, title: "clic: vai all'istante" }, `${mn === Infinity ? "–" : mn.toFixed(2)} · ${Number.isFinite(s) ? s.toFixed(0) + " m" + dc : "–"}`);
        });
        return el("tr", { "data-i": i0 }, el("td", {}, g.tipo === "lanciato" ? `giro ${g.numero}` : g.tipo), el("td", { class: "n" }, DV.tempo(g.tempo)), ...celle);
      });
      const tab = el("table", { class: "dati" }, el("thead", {}, testa), el("tbody", {}, righe));
      tab.addEventListener("click", (e) => { const td = e.target.closest("td[data-i]"); const tr = e.target.closest("tr[data-i]"); const k = td ? +td.dataset.i : tr ? +tr.dataset.i : -1; if (k >= 0) DV.vaiA(k); });
      dove.append(el("div", { class: "pannello", style: { marginTop: "12px" } }, el("h3", {}, "Per giro"),
        el("div", { class: "nota" }, "scatti = quante volte il ramo si è acceso e per quanti secondi; min = distanza minima dal trigger della derivata (× soglia) e a che metro del giro. Clic su una cella: il cursore va in quell'istante."),
        el("div", { class: "scorre" }, tab)));
    },

    cursore() {
      if (!this.A || !this.carte) return;
      const i = S.i;
      this.carte.innerHTML = "";
      for (const a of this.A) {
        const on = a.attivo[i] > 0.5;
        const termini = a.term.map((t) => {
          if (!t.crit) return el("div", { class: "nota" }, `${t.testo}: condizione senza soglia`);
          const R = DV.risVista().criteri[t.id];
          const m = R.margine[i] / scala(t.crit, R);
          const d = t.negato ? Math.max(-m, 0) : Math.max(m, 0);
          const ok = d === 0;
          return el("div", { class: "fila", style: { gap: "6px", justifyContent: "space-between" } },
            el("span", {}, (ok ? "● " : "○ ") + t.testo), el("span", { class: "tenue" }, ok ? "ok" : `mancano ${(d * 100).toFixed(0)}% della soglia`));
        });
        const der = a.der.map((d) => {
          const v = d.R.valore[i], s = d.R.soglia[i], m = d.R.margine[i], vel = d.vel[i];
          const sopra = (d.c.confronto || ">").startsWith(">");
          const fondo = Math.max(Math.abs(s) * 1.6, Math.abs(v) * 1.05, 1e-9);
          const pv = Math.max(0, Math.min(100, (v / fondo) * 100)), ps = Math.max(0, Math.min(100, (s / fondo) * 100));
          const att = d.R.attivo[i] > 0.5;
          const tempo = !att && m > 0 && vel > 0 ? m / vel : null;
          return el("div", { style: { marginTop: "8px" } },
            el("div", { class: "fila", style: { justifyContent: "space-between" } }, el("b", {}, `${d.c.id} derivata`),
              el("span", { class: "stato " + (att ? "si" : "no") }, el("span", { class: "pallino" }), att ? "trigger" : "sotto")),
            el("div", { class: "grande" }, `${DV.fmt(v)} `, el("span", { class: "tenue", style: { fontSize: "13px" } }, `${d.c.unita || ""} ${d.c.confronto} ${DV.fmt(s)}`)),
            el("div", { class: "misuratore", style: { "--colore": DV.colSerie(3) } }, el("div", { class: "barra-v", style: { width: pv + "%" } }), el("div", { class: "soglia", style: { left: ps + "%" } })),
            el("div", {}, att ? `oltre il trigger di ${DV.fmt(Math.abs(m))} ${d.c.unita || ""}` : `mancano ${DV.fmt(Math.abs(m))} ${d.c.unita || ""} (${((Math.abs(m) / d.sc) * 100).toFixed(0)}% della soglia)`),
            el("div", { class: "nota" }, vel > 0 && !att ? `si avvicina a ${DV.fmt(vel)} ${d.c.unita || ""}/s` + (tempo !== null && tempo < 3 ? ` → trigger fra ~${(tempo * 1000).toFixed(0)} ms a questo ritmo` : "") : vel < 0 && !att ? "si sta allontanando" : ""),
            sopra ? null : el("div", { class: "nota" }, "criterio «sotto soglia»"));
        });
        this.carte.append(el("div", { class: "carta", style: { "--colore": on ? DV.colore("--critico") : DV.colore("--asse") } },
          el("div", { class: "fila", style: { justifyContent: "space-between" } }, el("span", { class: "nome" }, `${a.ra.id}${a.ra.nome ? " · " + a.ra.nome : ""}`),
            el("span", { class: "stato " + (on ? "si" : "no") }, el("span", { class: "pallino" }), on ? "lavora" : "fermo")),
          el("div", { class: "nota" }, a.ra.condizione),
          el("div", { style: { margin: "6px 0" } }, on ? "il ramo è scattato" : `distanza del ramo dal trigger: ${(a.dist[i] * 100).toFixed(0)}% della soglia del termine più lontano`),
          ...termini, ...der));
      }
    },
  };
  DV.registraVista("trigger", vista);
})();
