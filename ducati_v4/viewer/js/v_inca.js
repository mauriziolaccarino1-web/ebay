/* Scheda "Tabelle dal vivo" (stile INCA): tutte le lookup table lette dal programma dei controlli,
   ognuna con le celle su cui sta lavorando la moto all'istante del cursore (pesi dell'interpolazione),
   gli assi evidenziati, il mirino, la scia, e il ramo attivo. Ripercorrendo il giro si vede la mappatura lavorare. */
(function () {
  const DV = window.DV;
  const S = DV.stato;
  const { el } = DV;
  const radice = document.getElementById("v-inca");
  const opz = { sfondo: "valori", scia: 1.5, soloAttive: false };

  // ---------------------------------------------------------------- grafo a valle (chi usa cosa)
  function aValle(M) {
    const usa = new Map();
    const lega = (da, a) => { if (!usa.has(da)) usa.set(da, new Set()); usa.get(da).add(a); };
    for (const b of M.blocchi || []) {
      for (const d of DV.modello.dipendenze(b)) lega(d, b.id);
      if (b.tipo === "tabella") for (const p of b.tabella.match(/\{(\w+)\}/g) || []) lega(p.slice(1, -1), b.id);
    }
    for (const c of M.criteri || []) for (const d of [...DV.espr.nomi(String(c.valore)), ...(typeof c.soglia === "string" ? DV.espr.nomi(c.soglia) : [])]) lega(d, c.id);
    for (const r of M.rami || []) for (const d of DV.espr.nomi(r.condizione)) lega(d, r.id);
    if (M.logica) for (const d of DV.espr.nomi(M.logica)) lega(d, "logica");
    for (const u of M.uscite || []) { lega(u.blocco, "u:" + u.id); if (u.attiva_se) for (const d of DV.espr.nomi(u.attiva_se)) lega(d, "u:" + u.id); }
    return (id) => {
      const visti = new Set(), coda = [id];
      while (coda.length) { const x = coda.pop(); for (const y of usa.get(x) || []) if (!visti.has(y)) { visti.add(y); coda.push(y); } }
      return visti;
    };
  }

  function densita(u, T) {
    const [a, b] = DV.intervallo();
    const D = T.z.map((r) => r.map(() => 0));
    let tot = 0;
    const ax = T.x ? T.x.valori : [0], ay = T.y ? T.y.valori : null;
    for (let i = a; i <= b; i++) {
      if (!u.x || !Number.isFinite(u.x[i])) continue;
      const fx = DV.calib.posizione(ax, u.x[i]), ix = Math.floor(fx), wx = fx - ix, ix1 = Math.min(ix + 1, ax.length - 1);
      let iy = 0, wy = 0, iy1 = 0;
      if (ay && u.y) { const fy = DV.calib.posizione(ay, u.y[i]); iy = Math.floor(fy); wy = fy - iy; iy1 = Math.min(iy + 1, ay.length - 1); }
      D[iy][ix] += (1 - wx) * (1 - wy); D[iy][ix1] += wx * (1 - wy);
      if (ay) { D[iy1][ix] += (1 - wx) * wy; D[iy1][ix1] += wx * wy; }
      tot++;
    }
    return { D, tot };
  }

  const vista = {
    alGiro: true,
    disegna() {
      radice.innerHTML = "";
      this.finestre = [];
      const r = DV.risVista();
      if (!S.sess || !S.modello || !S.struttura || !DV.bufVista() || !r || r.dalFile) {
        radice.append(el("div", { class: "pannello" }, el("h3", {}, "Tabelle dal vivo"),
          el("p", { class: "nota" }, "Servono sessione, modello, struttura e almeno un file .bin: le celle si accendono ricalcolando la catena con la calibrazione scelta.")));
        return;
      }
      const M = S.modello;
      const valle = aValle(M);
      const crit = (M.criteri || []).map((c) => c.id), rami = (M.rami || []).map((x) => x.id);
      const buf = DV.bufVista(), altro = S.vistaCal === "A" ? S.binMod : S.binOrig;
      const perId = new Map(S.struttura.tabelle.map((t) => [t.id, t]));
      // barra strumenti
      const sf = el("select", {});
      for (const [k, n] of [["valori", "sfondo: valori"], ["uso", "sfondo: dove lavora nel giro"], ["differenza", "sfondo: B − A"]]) sf.append(el("option", { value: k, selected: opz.sfondo === k || undefined }, n));
      sf.addEventListener("change", () => { opz.sfondo = sf.value; this.disegna(); });
      const sc = el("select", {});
      for (const v of [0, 0.5, 1.5, 3]) sc.append(el("option", { value: v, selected: opz.scia === v || undefined }, v ? `scia ${v} s` : "senza scia"));
      sc.addEventListener("change", () => { opz.scia = +sc.value; this.cursore(); });
      const so = el("input", { type: "checkbox", checked: opz.soloAttive || undefined });
      so.addEventListener("change", () => { opz.soloAttive = so.checked; this.cursore(); });
      radice.append(el("div", { class: "strumenti" }, DV.selettoreVista(() => this.disegna()), sf, sc, el("label", { class: "fila" }, so, "solo le tabelle del ramo che lavora"),
        el("span", { class: "nota" }, "▶ / frecce per ripercorrere il giro · clic su una cella: valori A/B · doppio clic: apre la tabella in Mappe")));
      // colonna sinistra: stato e misure
      this.stato = el("div", { class: "pannello" });
      this.misure = el("div", { class: "pannello scorre", style: { maxHeight: "58vh" } });
      const griglia = el("div", { class: "inca-griglia" });
      radice.append(el("div", { class: "inca-wrap" }, el("div", { class: "righe inca-lato" }, this.stato, this.misure), griglia));
      // finestre: una per ogni blocco tabella, ordinate per criterio servito
      const blocchi = (M.blocchi || []).filter((b) => b.tipo === "tabella");
      const info = blocchi.map((b) => {
        const nome = DV.modello.tabellaAl(r, b.id, S.i) || (r.usate[b.id] && r.usate[b.id].tabella) || DV.modello.nomeTabella(b.tabella, {});
        const v = valle(b.id);
        const cs = crit.filter((c) => v.has(c)), rs = rami.filter((x) => v.has(x));
        const ordine = cs.length ? Math.min(...cs.map((c) => crit.indexOf(c))) : 99;
        return { b, nome, def: perId.get(nome), cs, rs, uscita: [...v].some((x) => x.startsWith("u:")), ordine };
      }).sort((p, q) => p.ordine - q.ordine);
      for (const f of info) {
        if (!f.def) { griglia.append(el("div", { class: "finestra" }, el("div", { class: "testa" }, el("b", {}, f.b.id), ` tabella ${f.nome} non trovata nella struttura`))); continue; }
        let T, Ta = null;
        try { T = DV.calib.leggi(S.struttura, f.def, buf); } catch (e) { griglia.append(el("div", { class: "finestra" }, el("div", { class: "testa" }, el("b", {}, f.b.id), " " + e.message))); continue; }
        try { if (altro) Ta = DV.calib.leggi(S.struttura, f.def, altro); } catch (e) { Ta = null; }
        this.finestre.push(this.finestra(griglia, f, T, Ta, r));
      }
      this.costruisciMisure(r);
      this.cursore();
    },

    finestra(dove, f, T, Ta, r) {
      const u = r.usate[f.b.id] || {};
      const R = T.z.length, C = T.z[0].length;
      const dec = Math.max(0, Math.min(3, -Math.floor(Math.log10(Math.abs(f.def.scala ?? 1) || 1))));
      let mn = Infinity, mx = -Infinity, dmax = 0;
      for (let i = 0; i < R; i++) for (let j = 0; j < C; j++) {
        mn = Math.min(mn, T.z[i][j]); mx = Math.max(mx, T.z[i][j]);
        if (Ta && Ta.z.length === R && Ta.z[0].length === C) dmax = Math.max(dmax, Math.abs(T.z[i][j] - Ta.z[i][j]));
      }
      const D = opz.sfondo === "uso" ? densita(u, T) : null;
      let umax = 0;
      if (D) for (const rr of D.D) for (const v of rr) umax = Math.max(umax, v);
      const badge = [...f.cs.map((c) => el("span", { class: "badge", "data-c": c }, c)), ...f.rs.map((x) => el("span", { class: "badge", "data-r": x }, x)),
        f.uscita ? el("span", { class: "badge" }, "uscita") : null];
      const usc = el("span", { class: "uscita-val" });
      const assi = el("div", { class: "nota inca-assi" });
      const tbl = el("table", { class: "inca" });
      const thx = [], thy = [], celle = [];
      if (T.x) {
        const tr = el("tr", {}, el("th", { class: "angolo" }, T.y ? `${T.y.unita || "y"}\\${T.x.unita || "x"}` : T.x.unita || "x"));
        T.x.valori.forEach((v) => { const th = el("th", { class: "asse" }, DV.fmt(v, Math.abs(v) >= 100 ? 0 : 1)); thx.push(th); tr.append(th); });
        tbl.append(tr);
      }
      for (let i = 0; i < R; i++) {
        const tr = el("tr");
        if (T.y) { const th = el("th", { class: "asse" }, DV.fmt(T.y.valori[i], Math.abs(T.y.valori[i]) >= 100 ? 0 : 1)); thy.push(th); tr.append(th); }
        else if (T.x) tr.append(el("th", { class: "angolo" }, f.def.unita || ""));
        const riga = [];
        for (let j = 0; j < C; j++) {
          const v = T.z[i][j];
          let fondo = "", ink = "";
          if (opz.sfondo === "valori") { const q = mx > mn ? (v - mn) / (mx - mn) : 0; fondo = DV.seq(q); ink = DV.inkSu(q); }
          else if (opz.sfondo === "uso" && D) { const q = umax ? D.D[i][j] / umax : 0; fondo = q ? DV.seq(0.15 + 0.85 * q) : ""; ink = DV.inkSu(0.15 + 0.85 * q); }
          else if (opz.sfondo === "differenza" && Ta) { const d = S.vistaCal === "A" ? Ta.z[i][j] - v : v - Ta.z[i][j]; fondo = dmax ? DV.div(d / dmax) : ""; }
          const diverso = Ta && Ta.z[i] && Ta.z[i][j] !== undefined && Ta.z[i][j] !== v;
          const td = el("td", { style: { background: fondo, color: ink }, class: diverso ? "diversa" : "" }, v.toFixed(dec));
          td.addEventListener("click", (e) => DV.tooltip(e, `<b>${f.nome}</b> [${i},${j}]<br>${T.y ? `${T.y.unita} ${DV.fmt(T.y.valori[i])} · ` : ""}${T.x ? `${T.x.unita} ${DV.fmt(T.x.valori[j])}` : ""}<br>${DV.nomeVista()}: ${v.toFixed(dec)}${Ta && Ta.z[i] ? `<br>${S.vistaCal === "A" ? DV.nomeB() : DV.nomeA()}: ${Ta.z[i][j].toFixed(dec)}` : ""}${D ? `<br>uso ${((D.D[i][j] / Math.max(1, D.tot)) * 100).toFixed(2)}%` : ""}`));
          td.addEventListener("mouseleave", (e) => DV.tooltip(e, null));
          td.addEventListener("dblclick", () => { DV.emit("apriTabella", f.nome); document.querySelector('#schede button[data-vista="mappe"]').click(); });
          riga.push(td);
          tr.append(td);
        }
        celle.push(riga);
        tbl.append(tr);
      }
      const mv = el("div", { class: "mirino v" }), mh = el("div", { class: "mirino h" });
      const wrap = el("div", { class: "inca-tab" }, tbl, mv, mh);
      const box = el("div", { class: "finestra" },
        el("div", { class: "testa" }, el("b", {}, f.b.id), el("span", { class: "tenue" }, ` ← ${f.nome}`), ...badge, usc),
        el("div", { class: "nota" }, `${f.def.nome || ""}${f.def.unita ? " · " + f.def.unita : ""} · ${T.y ? "mappa" : T.x ? "curva" : "valore"} ${R}×${C} @0x${DV.calib.ind(f.def.indirizzo, DV.bufVista()).toString(16).toUpperCase()}${typeof f.def.indirizzo === "object" ? " (" + DV.bufVista().variante + ")" : ""}`),
        assi, wrap);
      dove.append(box);
      return { f, T, u, celle, thx, thy, mv, mh, wrap, box, usc, assi, accese: [], scia: [], dec, R, C };
    },

    costruisciMisure(r) {
      const M = S.modello;
      const righe = [];
      const add = (id, nome, unita, tipo) => {
        const v = el("td", { class: "n" });
        righe.push({ id, tipo, v, tr: el("tr", {}, el("td", {}, nome), v, el("td", { class: "tenue" }, unita || "")) });
      };
      for (const i of M.ingressi || []) add(i.id, i.id, i.unita, "ingresso");
      for (const b of M.blocchi || []) if (b.tipo !== "tabella") add(b.id, b.id, b.unita, b.tipo === "confronto" ? "bool" : "blocco");
      for (const b of M.blocchi || []) if (b.tipo === "tabella") add(b.id, b.id + " (tab)", b.unita, "blocco");
      for (const u of M.uscite || []) add("u:" + u.id, u.id + " (uscita)", u.unita, "uscita");
      this.righeMisure = righe;
      this.misure.innerHTML = "";
      this.misure.append(el("h3", {}, "Misure"), el("table", { class: "dati" }, el("tbody", {}, righe.map((x) => x.tr))));
    },

    cursore() {
      if (!this.finestre || !this.stato) return;
      const r = DV.risVista();
      if (!r) return;
      const i = S.i;
      const M = S.modello;
      // --- stato: logica, rami, criteri
      const L = r.logica[i] > 0.5;
      const ramiOn = new Set((M.rami || []).filter((x) => r.rami[x.id] && r.rami[x.id][i] > 0.5).map((x) => x.id));
      const critOn = new Set((M.criteri || []).filter((c) => r.criteri[c.id].attivo[i] > 0.5).map((c) => c.id));
      this.stato.innerHTML = "";
      this.stato.append(el("h3", {}, `t ${(i * S.dt).toFixed(2)} s · ${DV.nomeVista()}`), el("div", { class: "nota" }, DV.testoLivelli(i, r)),
        el("div", { class: "stato " + (L ? "si" : "no"), style: { marginBottom: "8px" } }, el("span", { class: "pallino" }), L ? "INTERVENTO" : "nessun intervento"),
        el("table", { class: "dati" }, el("tbody", {},
          (M.rami || []).map((x) => el("tr", { class: ramiOn.has(x.id) ? "sel" : "" }, el("td", {}, (ramiOn.has(x.id) ? "● " : "○ ") + x.id), el("td", {}, x.nome || ""), el("td", { class: "tenue" }, x.condizione))),
          (M.criteri || []).map((c) => {
            const R = r.criteri[c.id];
            return el("tr", {}, el("td", {}, (critOn.has(c.id) ? "● " : "○ ") + c.id),
              el("td", { class: "n" }, `${DV.fmt(R.valore[i])} ${c.confronto} ${DV.fmt(R.soglia[i])}`),
              el("td", { class: "n tenue" }, critOn.has(c.id) ? "soddisfatto" : `manca ${DV.fmt(Math.abs(R.margine[i]))} ${c.unita || ""}`));
          }))));
      // --- misure
      for (const x of this.righeMisure || []) {
        const v = x.id.startsWith("u:") ? r.uscite[x.id.slice(2)] : r.env[x.id];
        const val = v ? v[i] : NaN;
        x.v.textContent = x.tipo === "bool" ? (val > 0.5 ? "● vero" : "○ falso") : DV.fmt(val);
        x.tr.classList.toggle("sel", x.tipo === "bool" && val > 0.5);
      }
      // il livello è cambiato e il blocco legge un'altra tabella: ridisegna le finestre
      if (this.finestre.some((w) => { const nm = DV.modello.tabellaAl(r, w.f.b.id, i); return nm && nm !== w.f.nome; })) { this.disegna(); return; }
      // --- finestre
      const passi = Math.round(opz.scia / S.dt);
      for (const w of this.finestre) {
        const { f, T, u } = w;
        // ramo attivo?
        const attiva = (f.rs.length && f.rs.some((x) => ramiOn.has(x))) || (!f.rs.length && (f.uscita || f.cs.length) && L);
        const spenta = !attiva && (f.rs.length > 0 || f.cs.length > 0) && !L;
        w.box.classList.toggle("attiva", !!attiva);
        w.box.classList.toggle("spenta", !!spenta && !attiva);
        w.box.style.display = opz.soloAttive && !attiva ? "none" : "";
        w.box.querySelectorAll("[data-c]").forEach((b) => b.classList.toggle("acceso", critOn.has(b.dataset.c)));
        w.box.querySelectorAll("[data-r]").forEach((b) => b.classList.toggle("acceso", ramiOn.has(b.dataset.r)));
        // spegni le celle accese prima
        for (const c of w.accese) { c.classList.remove("wp"); c.style.removeProperty("--w"); }
        for (const c of w.scia) c.classList.remove("scia");
        w.thx.concat(w.thy).forEach((th) => th.classList.remove("wp"));
        w.accese = []; w.scia = [];
        const xv = u.x ? u.x[i] : NaN, yv = u.y ? u.y[i] : NaN;
        const usc = r.env[f.b.id] ? r.env[f.b.id][i] : NaN;
        w.usc.textContent = ` = ${DV.fmt(usc)} ${f.def.unita || ""}`;
        if (!T.x) { w.celle[0][0].classList.add("wp"); w.celle[0][0].style.setProperty("--w", 1); w.accese.push(w.celle[0][0]); w.assi.textContent = "valore fisso"; w.mv.style.display = w.mh.style.display = "none"; continue; }
        if (!Number.isFinite(xv) || (T.y && !Number.isFinite(yv))) { w.assi.textContent = "ingresso non disponibile"; w.mv.style.display = w.mh.style.display = "none"; continue; }
        const ax = T.x.valori, ay = T.y ? T.y.valori : null;
        const fx = DV.calib.posizione(ax, xv), j0 = Math.floor(fx), wx = fx - j0, j1 = Math.min(j0 + 1, w.C - 1);
        let fy = 0, i0 = 0, wy = 0, i1 = 0;
        if (ay) { fy = DV.calib.posizione(ay, yv); i0 = Math.floor(fy); wy = fy - i0; i1 = Math.min(i0 + 1, w.R - 1); }
        const satx = xv < ax[0] ? "◀" : xv > ax[ax.length - 1] ? "▶" : "";
        const saty = ay ? (yv < ay[0] ? "▲" : yv > ay[ay.length - 1] ? "▼" : "") : "";
        const pesi = [[i0, j0, (1 - wx) * (1 - wy)], [i0, j1, wx * (1 - wy)], [i1, j0, (1 - wx) * wy], [i1, j1, wx * wy]];
        for (const [a, b, p] of pesi) {
          if (p < 0.005) continue;
          const c = w.celle[a][b];
          const prima = +(c.style.getPropertyValue("--w") || 0);
          c.style.setProperty("--w", Math.min(1, prima + p).toFixed(3));
          if (!c.classList.contains("wp")) { c.classList.add("wp"); w.accese.push(c); }
        }
        [w.thx[j0], wx > 0.005 ? w.thx[j1] : null, ay ? w.thy[i0] : null, ay && wy > 0.005 ? w.thy[i1] : null].forEach((th) => th && th.classList.add("wp"));
        w.assi.textContent = `x ${f.b.x} = ${DV.fmt(xv)} ${T.x.unita || ""} ${satx ? satx + " oltre l'asse (saturato)" : ""}` + (ay ? ` · y ${f.b.y} = ${DV.fmt(yv)} ${T.y.unita || ""} ${saty ? saty + " oltre l'asse (saturato)" : ""}` : "");
        // scia: celle più vicine negli ultimi secondi
        if (passi > 0) {
          for (let k = Math.max(0, i - passi); k < i; k += 2) {
            const x2 = u.x[k];
            if (!Number.isFinite(x2)) continue;
            const cj = Math.round(DV.calib.posizione(ax, x2));
            const ci = ay && u.y ? Math.round(DV.calib.posizione(ay, u.y[k])) : 0;
            const c = w.celle[ci] && w.celle[ci][cj];
            if (c && !c.classList.contains("scia")) { c.classList.add("scia"); w.scia.push(c); }
          }
        }
        // mirino alla posizione esatta (interpolata fra i centri delle celle)
        const c00 = w.celle[i0][j0], c01 = w.celle[i0][j1], c10 = w.celle[i1][j0];
        if (c00.offsetWidth) {
          const cx = (c) => c.offsetLeft + c.offsetWidth / 2, cy = (c) => c.offsetTop + c.offsetHeight / 2;
          const X = cx(c00) + (cx(c01) - cx(c00)) * wx, Y = cy(c00) + (cy(c10) - cy(c00)) * wy;
          const tb = w.celle[0][0].closest("table");
          w.mv.style.display = ""; w.mv.style.left = X + "px"; w.mv.style.top = tb.offsetTop + "px"; w.mv.style.height = tb.offsetHeight + "px";
          if (ay) { w.mh.style.display = ""; w.mh.style.top = Y + "px"; w.mh.style.left = tb.offsetLeft + "px"; w.mh.style.width = tb.offsetWidth + "px"; }
          else w.mh.style.display = "none";
        }
      }
    },
  };
  DV.registraVista("inca", vista);
})();
