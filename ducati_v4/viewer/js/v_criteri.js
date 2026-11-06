/* Scheda Criteri e rami: dove sta il punto attuale rispetto a ogni soglia, quale ramo lavora, cosa manca */
(function () {
  const DV = window.DV;
  const S = DV.stato;
  const { el } = DV;
  const radice = document.getElementById("v-criteri");

  const defCrit = () => (S.modello && S.modello.criteri) || [];
  const cacheScala = new WeakMap();
  const scala = (c, r) => {
    const sv = r.criteri[c.id].soglia;
    if (c.scala) return c.scala;
    if (cacheScala.has(sv)) return cacheScala.get(sv);
    const val = scalaDa(sv);
    cacheScala.set(sv, val);
    return val;
  };
  const scalaDa = (sv) => {
    const v = [];
    for (let i = 0; i < sv.length; i += 13) if (Number.isFinite(sv[i])) v.push(Math.abs(sv[i]));
    v.sort((a, b) => a - b);
    return v[Math.floor(v.length * 0.9)] || 1;
  };
  const diversi = (a, b) => { if (!a || !b) return false; for (let i = 0; i < a.length; i += 3) if (Math.abs(a[i] - b[i]) > 1e-9) return true; return false; };

  function envScalare(r, i) {
    const e = {};
    for (const [k, v] of Object.entries(r.env)) if (v && v.length) e[k] = v[i];
    for (const [k, v] of Object.entries(r.criteri)) e[k] = v.attivo[i];
    for (const [k, v] of Object.entries(r.rami)) e[k] = v[i];
    e.logica = r.logica[i];
    return e;
  }

  const vista = {
    alGiro: true,
    disegna() {
      DV.pulisciGrafici(radice);
      radice.innerHTML = "";
      const r = S.ris.orig || S.ris.mod;
      if (!S.sess || !S.modello || !r) {
        radice.append(el("div", { class: "pannello" }, el("h3", {}, "Serve il modello della catena di controllo"),
          el("p", { class: "nota" }, "Carica il file modello (.json) e, per ricalcolare con le tabelle, la struttura e il file .bin. Senza .bin vengono mostrati i risultati salvati nella sessione.")));
        return;
      }
      radice.append(el("div", { class: "nota", style: { marginBottom: "8px" } },
        `${S.modello.nome || "modello"} · parametri ${JSON.stringify(r.parametri || {})}` +
        (DV.confrontoAttivo() ? ` · A = ${DV.nomeA()}, B = ${DV.nomeB()} ricalcolate sullo stesso giro registrato` : ` · calibrazione ${DV.nomeA()}`)));
      this.carte = el("div", { class: "carte" });
      this.rami = el("div", { class: "pannello" });
      radice.append(this.carte, el("div", { style: { height: "12px" } }), this.rami);
      // grafici
      const gr = el("div", { class: "pannello", style: { marginTop: "12px" } });
      radice.append(gr);
      const crit = defCrit();
      const normBox = el("div");
      gr.append(normBox);
      DV.grafico(normBox, {
        titolo: "Distanza dalla soglia, in frazione della soglia (sotto lo zero = criterio soddisfatto)",
        unita: "× soglia", altezza: 200, y: [-1, 2],
        serie: crit.map((c, k) => {
          const sc = scala(c, r);
          const m = r.criteri[c.id].margine;
          const d = new Float32Array(m.length);
          for (let i = 0; i < m.length; i++) d[i] = m[i] / sc;
          return { nome: `${c.id} ${c.nome}`, dati: d, colore: DV.colSerie(k) };
        }),
        bande: [{ dati: r.logica }],
      });
      crit.forEach((c, k) => {
        const box = el("div");
        gr.append(box);
        const o = S.ris.orig && S.ris.orig.criteri[c.id], m = S.ris.mod && S.ris.mod.criteri[c.id];
        const base = o || m;
        const serie = [{ nome: "valore", dati: base.valore, colore: DV.colSerie(k), unita: c.unita },
          { nome: "soglia", dati: base.soglia, colore: DV.colore("--testo-2"), tratteggio: [6, 4], unita: c.unita }];
        if (o && m && diversi(o.valore, m.valore)) serie.push({ nome: `valore (${DV.nomeB()})`, dati: m.valore, colore: DV.colSerie(k), tratteggio: [2, 3], unita: c.unita });
        if (o && m && diversi(o.soglia, m.soglia)) serie.push({ nome: `soglia (${DV.nomeB()})`, dati: m.soglia, colore: DV.colore("--s8"), tratteggio: [6, 4], unita: c.unita });
        DV.grafico(box, { titolo: `${c.id} · ${c.nome} (${c.valore} ${c.confronto} ${c.soglia})`, unita: c.unita, altezza: 150, serie, bande: [{ dati: base.attivo }] });
      });
      gr.append(el("div", { class: "nota" }, `Le bande rosse indicano quando il criterio è soddisfatto con ${DV.nomeA()} (A). Le linee tratteggiate sono ${DV.nomeB()} (B).`));
      this.statistiche(radice);
      this.cursore();
    },
    cursore() {
      if (!this.carte || !S.sess) return;
      const r = S.ris.orig || S.ris.mod;
      if (!r) return;
      const rm = DV.confrontoAttivo() ? S.ris.mod : null;
      const i = S.i;
      this.carte.innerHTML = "";
      defCrit().forEach((c, k) => {
        const R = r.criteri[c.id];
        const v = R.valore[i], s = R.soglia[i], m = R.margine[i], on = R.attivo[i] > 0.5;
        const sc = scala(c, r);
        const sopra = (c.confronto || ">").startsWith(">");
        const fondo = Math.max(Math.abs(s) * 1.6, sc * 1.6, Math.abs(v) * 1.05, 1e-9);
        const pv = Math.max(0, Math.min(100, (v / fondo) * 100)), ps = Math.max(0, Math.min(100, (s / fondo) * 100));
        const ist = c.isteresi ? Math.abs(c.isteresi) / fondo * 100 : 0;
        const testoDist = on
          ? `oltre la soglia di ${DV.fmt(Math.abs(m))} ${c.unita}`
          : `mancano ${DV.fmt(Math.abs(m))} ${c.unita} (${DV.fmt((Math.abs(m) / sc) * 100, 0)}% della soglia)`;
        const carta = el("div", { class: "carta", style: { "--colore": DV.colSerie(k) } },
          el("div", { class: "fila", style: { justifyContent: "space-between" } }, el("span", { class: "nome" }, `${c.id} · ${c.nome}`),
            el("span", { class: "stato " + (on ? "si" : "no") }, el("span", { class: "pallino" }), on ? "soddisfatto" : "non soddisfatto")),
          el("div", { class: "grande" }, `${DV.fmt(v)} `, el("span", { class: "tenue", style: { fontSize: "13px" } }, `${c.unita} ${c.confronto} ${DV.fmt(s)}`)),
          el("div", { class: "misuratore", style: { "--colore": DV.colSerie(k) } },
            ist ? el("div", { class: "isteresi", style: { left: (sopra ? ps - ist : ps) + "%", width: ist + "%" } }) : null,
            el("div", { class: "barra-v", style: { width: pv + "%" } }), el("div", { class: "soglia", style: { left: ps + "%" } })),
          el("div", { class: "misuratore-legenda" }, el("span", {}, "0"), el("span", {}, `soglia ${DV.fmt(s)}`), el("span", {}, DV.fmt(fondo))),
          el("div", {}, testoDist),
          el("div", { class: "valori" },
            el("span", {}, "valore"), el("span", {}, c.valore), el("span", {}, "soglia da"), el("span", {}, String(c.soglia)),
            c.isteresi ? el("span", {}, "isteresi") : null, c.isteresi ? el("span", {}, `${c.isteresi} ${c.unita}`) : null,
            rm ? el("span", {}, DV.nomeB()) : null,
            rm ? el("span", {}, `${DV.fmt(rm.criteri[c.id].valore[i])} ${c.confronto} ${DV.fmt(rm.criteri[c.id].soglia[i])} → ${rm.criteri[c.id].attivo[i] > 0.5 ? "soddisfatto" : "no"}`) : null));
        this.carte.append(carta);
      });
      // rami
      const env = envScalare(r, i);
      this.rami.innerHTML = "";
      this.rami.append(el("h3", {}, "Rami della logica"));
      const rami = (S.modello.rami && S.modello.rami.length) ? S.modello.rami : DV.espr.termini_or(S.modello.logica || "").map((t, k) => ({ id: "R" + (k + 1), nome: "", condizione: t }));
      const box = el("div", { class: "rami" });
      for (const ra of rami) {
        const vero = DV.espr.valuta(ra.condizione, env, 1) > 0.5;
        const termini = DV.espr.termini(ra.condizione);
        const mancano = [];
        const pezzi = termini.map((t) => {
          const val = DV.espr.valutaAlbero(t.albero, env, 1) > 0.5;
          if (!val && t.id && r.criteri[t.id]) {
            const cdef = defCrit().find((x) => x.id === t.id);
            const mm = r.criteri[t.id].margine[i];
            mancano.push(t.negato ? `${t.id} deve tornare sotto soglia (${DV.fmt(Math.abs(mm))} ${cdef.unita})` : `${t.id} a ${DV.fmt(Math.abs(mm))} ${cdef.unita} dalla soglia`);
          } else if (!val) mancano.push(t.testo);
          return el("span", { class: "termine" + (val ? " vero" : "") }, (val ? "● " : "○ ") + t.testo);
        });
        box.append(el("div", { class: "ramo" + (vero ? " attivo" : "") },
          el("b", {}, `${ra.id}${ra.nome ? " · " + ra.nome : ""}`), ...pezzi,
          el("span", { class: "manca" }, vero ? "→ questo ramo sta lavorando" : "manca: " + mancano.join("; "))));
      }
      const L = r.logica[i] > 0.5;
      const usc = Object.entries(r.uscite).map(([k, v]) => `${k} = ${DV.fmt(v[i])}`).join(", ");
      box.append(el("div", { class: "ramo" + (L ? " attivo" : "") }, el("b", {}, "Logica"), el("code", {}, S.modello.logica || ""),
        el("span", { class: "stato " + (L ? "si" : "no") }, el("span", { class: "pallino" }), L ? "intervento" : "nessun intervento"),
        usc ? el("span", { class: "manca" }, usc) : null,
        rm ? el("span", { class: "manca" }, `· ${DV.nomeB()}: ${rm.logica[i] > 0.5 ? "intervento" : "nessun intervento"}`) : null));
      // osservato sul CAN
      for (const o of S.modello.osservati || []) {
        const c = DV.canale(o.id);
        if (!c) continue;
        const vo = c.dati[i] > (o.soglia ?? 0.5);
        const ca = DV.concordanza(S.ris.orig, o), cb = DV.confrontoAttivo() ? DV.concordanza(S.ris.mod, o) : null;
        box.append(el("div", { class: "ramo" }, el("b", {}, `Centralina (CAN): ${o.id}`),
          el("span", { class: "stato " + (vo ? "si" : "no") }, el("span", { class: "pallino" }), vo ? "interviene" : "non interviene"),
          el("span", { class: "manca" }, vo === L ? "il modello concorda" : "il modello NON concorda in questo istante"),
          ca !== null ? el("span", { class: "manca", title: "quota di campioni in cui modello e centralina sono d'accordo, sull'intervento (interventi in comune / tutti gli interventi): dice quale calibrazione era montata" },
            `· concordanza nella sessione: ${DV.nomeA()} ${(ca * 100).toFixed(0)}%` + (cb !== null ? ` · ${DV.nomeB()} ${(cb * 100).toFixed(0)}%` : "")) : null));
      }
      this.rami.append(box);
    },
    statistiche(dove) {
      const crit = defCrit();
      const giri = DV.giri();
      if (!giri.length) return;
      const ro = S.ris.orig, rm = DV.confrontoAttivo() ? S.ris.mod : null;
      const stat = (r, a, b) => {
        const scale = crit.map((c) => scala(c, r));
        let ni = 0, ti = 0, prima = false;
        const perc = crit.map(() => 0), minm = crit.map(() => Infinity);
        for (let i = a; i < b; i++) {
          const L = r.logica[i] > 0.5;
          if (L) { ti++; if (!prima) ni++; }
          prima = L;
          crit.forEach((c, k) => {
            const R = r.criteri[c.id];
            if (R.attivo[i] > 0.5) perc[k]++;
            const mm = R.margine[i] / scale[k];
            if (mm < minm[k]) minm[k] = mm;
          });
        }
        return { ni, ti: ti * S.dt, perc: perc.map((p) => (p / Math.max(1, b - a)) * 100), minm };
      };
      const testa = el("tr", {}, el("th", {}, "giro"), el("th", { class: "n" }, "tempo"), el("th", { class: "n" }, "interventi"), el("th", { class: "n" }, "durata s"),
        ...crit.map((c) => el("th", { class: "n", title: "tempo soddisfatto / distanza minima dalla soglia" }, `${c.id} % · min`)));
      const righe = giri.map((g, k) => {
        const a = DV.indiceDaTempo(DV.tRel(g.t_inizio)), b = DV.indiceDaTempo(DV.tRel(g.t_fine));
        const so = stat(ro || rm, a, b);
        const sm = rm ? stat(rm, a, b) : null;
        const fr = (x, y, f) => (y === null ? f(x) : `${f(x)} → ${f(y)}`);
        return el("tr", { "data-i": a },
          el("td", {}, g.tipo === "lanciato" ? `giro ${g.numero}` : g.tipo), el("td", { class: "n" }, DV.tempo(g.tempo)),
          el("td", { class: "n" }, fr(so.ni, sm ? sm.ni : null, String)), el("td", { class: "n" }, fr(so.ti, sm ? sm.ti : null, (x) => x.toFixed(2))),
          ...crit.map((c, j) => el("td", { class: "n" }, fr(so.perc[j], sm ? sm.perc[j] : null, (x) => x.toFixed(1)) + " · " + fr(so.minm[j], sm ? sm.minm[j] : null, (x) => (x === Infinity ? "–" : x.toFixed(2))))));
      });
      const tab = el("table", { class: "dati" }, el("thead", {}, testa), el("tbody", {}, righe));
      tab.addEventListener("click", (e) => { const tr = e.target.closest("tr[data-i]"); if (tr) DV.vaiA(+tr.dataset.i); });
      dove.append(el("div", { class: "pannello", style: { marginTop: "12px" } }, el("h3", {}, "Per giro"),
        el("div", { class: "nota" }, "Interventi = quante volte la logica si accende; % = tempo con il criterio soddisfatto; min = distanza minima dalla soglia in frazione della soglia (negativa = superata)." + (rm ? ` Formato: ${DV.nomeA()} → ${DV.nomeB()}.` : "")),
        el("div", { class: "scorre" }, tab)));
    },
  };
  DV.registraVista("criteri", vista);
})();
