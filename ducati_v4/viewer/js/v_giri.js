/* Scheda Giri: tempi stimati senza GPS, sovrapposizione per distanza, distacco dal giro di riferimento */
(function () {
  const DV = window.DV;
  const S = DV.stato;
  const { el } = DV;
  const radice = document.getElementById("v-giri");
  let scelti = null, canale = "v_ant";

  function perDistanza(g, id, L, ds = 2) {
    const sg = DV.canale("s_giro"), ng = DV.canale("n_giro"), c = DV.canale(id);
    const a = DV.indiceDaTempo(DV.tRel(g.t_inizio)), b = DV.indiceDaTempo(DV.tRel(g.t_fine));
    const n = Math.floor(L / ds);
    const out = new Float32Array(n).fill(NaN), tempi = new Float32Array(n).fill(NaN);
    let k = 0;
    for (let i = a; i < b; i++) {
      const s = sg.dati[i];
      if (!Number.isFinite(s) || (ng && ng.dati[i] !== g.numero)) continue;
      const j = Math.floor(s / ds);
      while (k <= j && k < n) { out[k] = c ? c.dati[i] : NaN; tempi[k] = (i - a) * S.dt; k++; }
    }
    return { out, tempi };
  }

  const vista = {
    disegna() {
      DV.pulisciGrafici(radice);
      radice.innerHTML = "";
      const G = S.sess && S.sess.giri;
      if (!G || !G.giri.length) { radice.append(el("div", { class: "pannello" }, el("p", { class: "nota" }, "Nessun giro stimato in questa sessione."))); return; }
      const lanc = G.giri.filter((g) => g.tipo === "lanciato");
      const migliore = lanc.reduce((m, g) => (!m || g.tempo < m.tempo ? g : m), null);
      if (!scelti) scelti = new Set(lanc.slice(0, 4).map((g) => g.numero));
      const righe = G.giri.map((g) => {
        const cb = el("input", { type: "checkbox", checked: scelti.has(g.numero) || undefined, disabled: g.tipo !== "lanciato" && g.tipo !== "dubbio" ? true : undefined });
        cb.addEventListener("change", () => { cb.checked ? scelti.add(g.numero) : scelti.delete(g.numero); this.disegna(); });
        const tr = el("tr", { "data-i": DV.indiceDaTempo(DV.tRel(g.t_inizio)) },
          el("td", {}, cb), el("td", {}, g.tipo === "lanciato" ? `giro ${g.numero}` : g.tipo === "uscita" ? "uscita box" : g.tipo === "rientro" ? "rientro" : `giro ${g.numero} (dubbio)`),
          el("td", { class: "n" }, DV.tempo(g.tempo) + (g === migliore ? " ★" : "")),
          el("td", { class: "n" }, migliore && g.tipo === "lanciato" ? (g.tempo - migliore.tempo >= 0 ? "+" : "") + (g.tempo - migliore.tempo).toFixed(3) : ""),
          el("td", { class: "n" }, g.distanza.toFixed(1)), el("td", { class: "n" }, g.qualita.toFixed(2)));
        return tr;
      });
      const tab = el("table", { class: "dati" }, el("thead", {}, el("tr", {}, el("th", {}, ""), el("th", {}, "giro"), el("th", { class: "n" }, "tempo"), el("th", { class: "n" }, "distacco"), el("th", { class: "n" }, "distanza m"), el("th", { class: "n", title: "correlazione con il giro modello al passaggio sul traguardo" }, "qualità"))), el("tbody", {}, righe));
      tab.addEventListener("click", (e) => { const tr = e.target.closest("tr[data-i]"); if (tr && e.target.tagName !== "INPUT") DV.vaiA(+tr.dataset.i); });
      const sinistra = el("div", { class: "pannello" }, el("h3", {}, "Giri stimati dalla distanza"),
        el("div", { class: "nota" }, (G.note || []).join(" · ")), el("div", { class: "scorre" }, tab),
        el("div", { class: "avvertenza" }, "Tempi senza GPS: il traguardo è un punto riconosciuto dalla forma del giro (velocità e curvatura). Lo scarto tra giri è affidabile; la posizione assoluta della linea può differire di qualche metro da quella reale."));
      const sel = el("select", {});
      for (const c of S.canali.values()) if (c.gruppo !== "giri") sel.append(el("option", { value: c.id, selected: c.id === canale || undefined }, c.nome));
      sel.addEventListener("change", () => { canale = sel.value; this.disegna(); });
      const destra = el("div", { class: "pannello" }, el("div", { class: "strumenti" }, "canale", sel));
      radice.append(el("div", { class: "griglia2", style: { gridTemplateColumns: "minmax(320px, 420px) 1fr" } }, sinistra, destra));
      const L = G.lunghezza_giro, ds = 2;
      const xs = new Float64Array(Math.floor(L / ds)).map((_, k) => k * ds);
      const gi = G.giri.filter((g) => scelti.has(g.numero) && (g.tipo === "lanciato" || g.tipo === "dubbio"));
      const dati = gi.map((g) => ({ g, ...perDistanza(g, canale, L, ds) }));
      const c = DV.canale(canale);
      const box1 = el("div"), box2 = el("div");
      destra.append(box1, box2);
      if (!dati.length) { destra.append(el("p", { class: "nota" }, "Scegli i giri da confrontare.")); return; }
      DV.grafico(box1, { titolo: `${c ? c.nome : canale} lungo il giro`, x: xs, gruppo: "distanza", unita: c ? c.unita : "", etichettaX: "distanza (m)", altezza: 230, curve: true,
        serie: dati.map((d, k) => ({ nome: `giro ${d.g.numero}`, dati: d.out, colore: DV.colSerie(k), unita: c ? c.unita : "" })),
        xDi: (i) => DV.valore("s_giro", i), alClic: () => {} });
      const rif = dati.reduce((m, d) => (!m || d.g.tempo < m.g.tempo ? d : m), null);
      DV.grafico(box2, { titolo: `Distacco dal giro ${rif.g.numero} (positivo = più lento)`, x: xs, gruppo: "distanza", unita: "s", etichettaX: "distanza (m)", altezza: 180, curve: true,
        serie: dati.map((d, k) => ({ nome: `giro ${d.g.numero}`, dati: d.tempi.map((t, j) => t - rif.tempi[j]), colore: DV.colSerie(k), unita: "s", decimali: 3 })),
        xDi: (i) => DV.valore("s_giro", i), alClic: () => {} });
    },
  };
  DV.registraVista("giri", vista);
})();
