/* Scheda Mappe: elenco tabelle, valori/differenza/uso, punto di lavoro dal registrato, modifica ed export */
(function () {
  const DV = window.DV;
  const S = DV.stato;
  const { el } = DV;
  const radice = document.getElementById("v-mappe");
  let corrente = null, modo = "valori", sel = null, annulla = [], vista3d = { az: -0.7, el: 0.6 };

  DV.on("apriTabella", (id) => { corrente = id; sel = null; });

  // tabelle lette dalla catena nel tratto scelto (giro o sessione): nome -> {blocco, ora = letta all'istante del cursore}
  function tabelleInUso() {
    const m = new Map();
    const r = S.ris.mod || S.ris.orig;
    if (!r) return m;
    const [a, b] = DV.intervallo();
    for (const bl of (S.modello && S.modello.blocchi) || []) {
      if (bl.tipo !== "tabella") continue;
      const ora = DV.modello.tabellaAl(r, bl.id, S.i);
      for (const nm of DV.modello.tabelleFra(r, bl.id, a, b)) m.set(nm, { blocco: bl.id, ora: nm === ora });
    }
    return m;
  }
  const bloccoDi = (u) => (u ? u.blocco : undefined);
  // B (copia di lavoro) diversa da A?
  function diversa(tab) {
    if (!S.binOrig || !S.binMod) return false;
    return !DV.calib.uguali(S.struttura, tab, S.binOrig, S.binMod);
  }
  // copia di lavoro di B modificata rispetto al file B?
  function editata(tab) {
    if (!S.binCfrFile || !S.binMod) return false;
    return !DV.calib.uguali(S.struttura, tab, S.binCfrFile, S.binMod);
  }

  // densità d'uso: pesi bilineari accumulati sulle celle nel tratto scelto
  function uso(tab, T) {
    const r = S.ris.mod || S.ris.orig;
    if (!r) return null;
    const blocco = bloccoDi(tabelleInUso().get(tab.id));
    const u = blocco && r.usate[blocco];
    if (!u || !u.x) return null;
    const [a, b] = DV.intervallo();
    const D = T.z.map((riga) => riga.map(() => 0));
    let tot = 0;
    const ax = T.x.valori, ay = T.y ? T.y.valori : null;
    for (let i = a; i <= b; i++) {
      const vx = u.x[i];
      if (!Number.isFinite(vx)) continue;
      if (u.idx && u.nomi[u.idx[i]] !== tab.id) continue;  // in quell'istante il livello usava un'altra tabella
      const fx = DV.calib.posizione(ax, vx);
      const ix = Math.floor(fx), wx = fx - ix;
      let iy = 0, wy = 0;
      if (ay && u.y) { const fy = DV.calib.posizione(ay, u.y[i]); iy = Math.floor(fy); wy = fy - iy; }
      const ix1 = Math.min(ix + 1, ax.length - 1), iy1 = ay ? Math.min(iy + 1, ay.length - 1) : 0;
      D[iy][ix] += (1 - wx) * (1 - wy); D[iy][ix1] += wx * (1 - wy);
      if (ay) { D[iy1][ix] += (1 - wx) * wy; D[iy1][ix1] += wx * wy; }
      tot++;
    }
    return { D, tot, u };
  }

  const vista = {
    alGiro: true,
    disegna() {
      radice.innerHTML = "";
      if (!S.struttura) {
        radice.append(el("div", { class: "pannello" }, el("h3", {}, "Serve la struttura delle tabelle"),
          el("p", { class: "nota" }, "Carica il file struttura (.json) e il file della centralina (.bin). La struttura dice dove sta ogni tabella, che tipo di dato è, la scala e gli assi.")));
        return;
      }
      if (!S.binOrig) { radice.append(el("div", { class: "avvertenza" }, "Carica anche il file .bin della centralina per vedere i valori.")); }
      const inUso = tabelleInUso();
      const lista = el("div", { class: "pannello lista-tab" });
      const cerca = el("input", { type: "text", placeholder: "cerca tabella…", style: { width: "100%" } });
      const soloUso = el("input", { type: "checkbox" });
      lista.append(el("h3", {}, `Tabelle (${S.struttura.tabelle.length})`), cerca, el("label", { class: "fila nota" }, soloUso, "solo quelle lette dal modello"));
      const corpo = el("div");
      lista.append(corpo);
      const gruppi = new Map();
      for (const t of S.struttura.tabelle) { const g = t.gruppo || "altre"; if (!gruppi.has(g)) gruppi.set(g, []); gruppi.get(g).push(t); }
      const riempi = () => {
        corpo.innerHTML = "";
        const q = cerca.value.toLowerCase();
        for (const [g, ts] of gruppi) {
          const vis = ts.filter((t) => (!q || (t.id + " " + (t.nome || "")).toLowerCase().includes(q)) && (!soloUso.checked || inUso.has(t.id)));
          if (!vis.length) continue;
          corpo.append(el("h4", { style: { marginTop: "8px" } }, g));
          for (const t of vis) {
            const [rr, cc] = DV.calib.dim(t);
            const v = el("div", { class: "voce" + (t.id === corrente ? " sel" : "") },
              el("span", { class: "id" }, t.id),
              el("span", { class: "fila", style: { gap: "4px" } }, el("span", { class: "nota" }, `${t.nome || ""} · ${rr}×${cc}`),
                inUso.has(t.id) ? el("span", { class: "badge uso", title: "letta dal blocco " + inUso.get(t.id).blocco + (S.giro ? " nel giro scelto" : " nella sessione") }, inUso.get(t.id).ora ? "in uso ora" : "in uso") : null,
                S.binOrig && S.rif !== S.cfr && diversa(t) ? el("span", { class: "badge", title: `${DV.nomeB()} diversa da ${DV.nomeA()}` }, "≠ A") : null,
                editata(t) ? el("span", { class: "badge mod", title: "modificata nella copia di lavoro" }, "✎ modificata") : null,
                t.verificato === false ? el("span", { class: "badge" }, "da verificare") : null));
            v.addEventListener("click", () => { corrente = t.id; sel = null; this.disegna(); });
            corpo.append(v);
          }
        }
      };
      cerca.addEventListener("input", riempi);
      soloUso.addEventListener("change", riempi);
      riempi();
      if (!corrente) corrente = [...inUso.keys()][0] || S.struttura.tabelle[0].id;
      this.inUsoOra = [...inUso].filter(([, v]) => v.ora).map(([k]) => k).join(",");
      this.centro = el("div", { class: "righe" });
      radice.append(el("div", { class: "griglia2" }, lista, this.centro));
      this.disegnaTabella();
    },

    disegnaTabella() {
      const C = this.centro;
      C.innerHTML = "";
      const tab = S.struttura.tabelle.find((t) => t.id === corrente);
      if (!tab || !S.binOrig) return;
      const To = DV.calib.leggi(S.struttura, tab, S.binOrig);
      const Tm = DV.calib.leggi(S.struttura, tab, S.binMod);
      this.tab = tab; this.To = To; this.Tm = Tm;
      const inUso = tabelleInUso();
      const altriLivelli = [...inUso.keys()].filter((k) => k !== tab.id && k.replace(/\d+$/, "") === tab.id.replace(/\d+$/, ""));
      const famiglia = S.modello && (S.modello.blocchi || []).find((b) => b.tipo === "tabella" && b.tabella.includes("{") && new RegExp("^" + b.tabella.replace(/\{\w+\}/g, ".+") + "$").test(tab.id));
      const testa = el("div", { class: "pannello" },
        el("div", { class: "fila", style: { justifyContent: "space-between" } },
          el("h3", {}, `${tab.id} · ${tab.nome || ""}`),
          el("span", { class: "fila" }, inUso.has(tab.id) ? el("span", { class: "badge uso" }, inUso.get(tab.id).ora ? `in uso ora (blocco ${inUso.get(tab.id).blocco} · ${DV.testoLivelli()})` : `letta ${S.giro ? "nel giro" : "nella sessione"}, non in questo istante (${DV.testoLivelli()})`) :
            famiglia ? el("span", { class: "badge" }, `non letta con i livelli di questa sessione`) : el("span", { class: "badge" }, "non letta dal modello"))),
        el("div", { class: "nota" }, `${tab.descrizione || ""} · indirizzo ${typeof tab.indirizzo === "object" ? Object.entries(tab.indirizzo).map(([k, v]) => k + " " + v).join(", ") : tab.indirizzo} · ${tab.dtype || "u16"} ${tab.endian || "le"} · scala ${tab.scala ?? 1} · offset ${tab.offset ?? 0} · unità ${tab.unita || "–"}` +
          (To.x ? ` · asse x: ${To.x.nome || ""} ${To.x.unita || ""}${To.x.segnale ? " ← " + To.x.segnale : ""}` : "") + (To.y ? ` · asse y: ${To.y.nome || ""} ${To.y.unita || ""}${To.y.segnale ? " ← " + To.y.segnale : ""}` : "") +
          (tab.fonte ? ` · fonte: ${tab.fonte}` : "")),
        altriLivelli.length ? el("div", { class: "nota" }, "Stessa famiglia in uso: " + altriLivelli.join(", ")) : null);
      C.append(testa);
      // modi
      const modi = el("div", { class: "strumenti" });
      for (const [k, n] of [["valori", `Valori (${DV.nomeB()})`], ["differenza", `B − A (${DV.nomeB()} − ${DV.nomeA()})`], ["uso", "Dove lavora (registrato)"], ["3d", "Superficie 3D"]]) {
        if (k === "3d" && tab.tipo !== "mappa") continue;
        const b = el("button", { class: "bottone" + (modo === k ? " attivo" : "") }, n);
        b.addEventListener("click", () => { modo = k; this.disegnaTabella(); });
        modi.append(b);
      }
      C.append(modi);
      const corpo = el("div", { class: "pannello" });
      C.append(corpo);
      if (tab.tipo === "curva" || tab.tipo === "valore") this.curva(corpo, tab, To, Tm);
      if (modo === "3d" && tab.tipo === "mappa") this.superficie(corpo, To, Tm);
      else this.griglia(corpo, tab, To, Tm);
      C.append(this.strumentiModifica(tab));
      C.append(this.esportazione());
      this.cursore();
    },

    griglia(dove, tab, To, Tm) {
      const R = To.z.length, Cn = To.z[0].length;
      const U = modo === "uso" ? uso(tab, To) : null;
      let mn = Infinity, mx = -Infinity, dmax = 0, umax = 0;
      for (let i = 0; i < R; i++) for (let j = 0; j < Cn; j++) {
        mn = Math.min(mn, Tm.z[i][j]); mx = Math.max(mx, Tm.z[i][j]);
        dmax = Math.max(dmax, Math.abs(Tm.z[i][j] - To.z[i][j]));
        if (U) umax = Math.max(umax, U.D[i][j]);
      }
      const dec = Math.max(0, Math.min(4, -Math.floor(Math.log10(Math.abs(tab.scala ?? 1) || 1))));
      const tbl = el("table", { class: "mappa-griglia" });
      const hdr = el("tr", {}, el("th", {}, To.y ? `${To.y.unita || "y"} \\ ${To.x ? To.x.unita || "x" : ""}` : To.x ? To.x.unita || "x" : ""));
      if (To.x) To.x.valori.forEach((v) => hdr.append(el("th", {}, DV.fmt(v, 1))));
      tbl.append(hdr);
      this.celle = [];
      for (let i = 0; i < R; i++) {
        const tr = el("tr", {}, el("th", {}, To.y ? DV.fmt(To.y.valori[i], 1) : ""));
        const riga = [];
        for (let j = 0; j < Cn; j++) {
          const vo = To.z[i][j], vm = Tm.z[i][j], d = vm - vo;
          let fondo, testo;
          if (modo === "differenza") { fondo = DV.div(dmax ? d / dmax : 0); testo = d ? (d > 0 ? "+" : "") + d.toFixed(dec) : "·"; }
          else if (modo === "uso" && U) { const f = umax ? U.D[i][j] / umax : 0; fondo = f ? DV.seq(0.15 + 0.85 * f) : ""; testo = U.tot ? ((U.D[i][j] / U.tot) * 100).toFixed(1) : ""; }
          else { const f = mx > mn ? (vm - mn) / (mx - mn) : 0; fondo = DV.seq(f); testo = vm.toFixed(dec); }
          const f2 = modo === "valori" ? (mx > mn ? (vm - mn) / (mx - mn) : 0) : modo === "uso" && U && umax ? 0.15 + 0.85 * (U.D[i][j] / umax) : 0;
          const td = el("td", { style: { background: fondo, color: DV.inkSu(f2) || "" }, class: d ? "cambiata" : "", "data-i": i, "data-j": j }, testo);
          td.addEventListener("mouseenter", (e) => DV.tooltip(e, `<b>${To.y ? `${To.y.unita} ${DV.fmt(To.y.valori[i], 2)} · ` : ""}${To.x ? `${To.x.unita} ${DV.fmt(To.x.valori[j], 2)}` : ""}</b><br>A ${DV.nomeA()} ${vo.toFixed(dec)} · B ${DV.nomeB()} ${vm.toFixed(dec)}${d ? ` (${d > 0 ? "+" : ""}${d.toFixed(dec)}${vo ? `, ${((d / Math.abs(vo)) * 100).toFixed(1)}%` : ""})` : ""}${U ? `<br>uso ${((U.D[i][j] / Math.max(1, U.tot)) * 100).toFixed(2)}% del tempo` : ""}`));
          td.addEventListener("mouseleave", (e) => DV.tooltip(e, null));
          riga.push(td);
          tr.append(td);
        }
        this.celle.push(riga);
        tbl.append(tr);
      }
      // selezione a rettangolo
      let ini = null;
      tbl.addEventListener("mousedown", (e) => { const td = e.target.closest("td[data-i]"); if (!td) return; ini = [+td.dataset.i, +td.dataset.j]; sel = [ini[0], ini[1], ini[0], ini[1]]; this.aggiornaSel(); e.preventDefault(); });
      tbl.addEventListener("mouseover", (e) => { if (!ini || e.buttons !== 1) return; const td = e.target.closest("td[data-i]"); if (!td) return; sel = [Math.min(ini[0], +td.dataset.i), Math.min(ini[1], +td.dataset.j), Math.max(ini[0], +td.dataset.i), Math.max(ini[1], +td.dataset.j)]; this.aggiornaSel(); });
      window.addEventListener("mouseup", () => (ini = null), { once: true });
      const cont = el("div", { class: "contenitore-mappa" }, tbl);
      this.svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      this.svg.setAttribute("class", "sovrapposto");
      cont.append(this.svg);
      dove.append(cont, el("div", { class: "nota", style: { marginTop: "6px" } },
        modo === "uso" ? (U ? `Percentuale del tempo (${S.giro ? "giro scelto" : "sessione"}) in cui la centralina legge ogni cella, pesata come l'interpolazione. Il punto è l'istante del cursore, la scia gli ultimi 3 s.` : "Questa tabella non è letta dal modello con i parametri attuali, oppure manca la sessione.")
          : "Colore = valore di B (scala blu). Riga arancio sotto la cella = diversa da A. Trascina per selezionare; il punto blu è dove legge la centralina all'istante del cursore, la scia gli ultimi 3 s."));
      this.aggiornaSel();
    },

    aggiornaSel() {
      if (!this.celle) return;
      this.celle.forEach((riga, i) => riga.forEach((td, j) => td.classList.toggle("sel", !!sel && i >= sel[0] && i <= sel[2] && j >= sel[1] && j <= sel[3])));
      if (this.infoSel) this.infoSel.textContent = sel ? `selezione ${sel[2] - sel[0] + 1}×${sel[3] - sel[1] + 1} celle` : "nessuna selezione (clic o trascina sulle celle)";
    },

    curva(dove, tab, To, Tm) {
      const cv = el("canvas", { class: "tela", style: { height: "260px" } });
      dove.append(cv);
      this.cvCurva = cv;
      let trascina = null;
      const pos = (e) => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
      cv.addEventListener("mousedown", (e) => {
        if (!this.geoCurva) return;
        const [x, y] = pos(e);
        const k = this.geoCurva.vicino(x, y);
        if (k !== null) { trascina = k; annulla.push({ id: tab.id, z: Tm.z.map((r) => r.slice()) }); }
      });
      cv.addEventListener("mousemove", (e) => {
        if (trascina === null || !this.geoCurva) return;
        const [, y] = pos(e);
        const z = this.Tm.z.map((r) => r.slice());
        z[0][trascina] = DV.calib.quantizza(tab, this.geoCurva.yVal(y));
        DV.calib.scrivi(S.struttura, tab, S.binMod, z);
        this.Tm = DV.calib.leggi(S.struttura, tab, S.binMod);
        this.disegnaCurva();
      });
      window.addEventListener("mouseup", () => { if (trascina !== null) { trascina = null; this.dopoModifica(); } });
      requestAnimationFrame(() => this.disegnaCurva());
      dove.append(el("div", { class: "nota" }, `Curva grigia = A (${DV.nomeA()}), blu = B (${DV.nomeB()}). Trascina i punti in verticale per modificare; la linea verticale è il valore letto all'istante del cursore.`));
    },
    disegnaCurva() {
      const cv = this.cvCurva, To = this.To, Tm = this.Tm;
      if (!cv || !cv.isConnected) return;
      const dpr = devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
      cv.width = w * dpr; cv.height = h * dpr;
      const ctx = cv.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const xs = To.x ? To.x.valori : [0];
      const ys = [...To.z[0], ...Tm.z[0]];
      let y0 = Math.min(...ys), y1 = Math.max(...ys);
      if (y1 === y0) { y0 -= 1; y1 += 1; }
      const pad = (y1 - y0) * 0.12; y0 -= pad; y1 += pad;
      const x0 = xs[0], x1 = xs[xs.length - 1] === xs[0] ? xs[0] + 1 : xs[xs.length - 1];
      const L = 56, Rr = 12, T = 12, B = 30;
      const X = (v) => L + ((v - x0) / (x1 - x0)) * (w - L - Rr), Y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (h - T - B);
      ctx.strokeStyle = DV.colore("--griglia"); ctx.fillStyle = DV.colore("--testo-2"); ctx.font = "11px system-ui"; ctx.lineWidth = 1;
      for (let k = 0; k <= 4; k++) { const v = y0 + ((y1 - y0) * k) / 4; ctx.beginPath(); ctx.moveTo(L, Y(v)); ctx.lineTo(w - Rr, Y(v)); ctx.stroke(); ctx.fillText(DV.fmt(v, 1), 4, Y(v) + 4); }
      xs.forEach((v) => ctx.fillText(DV.fmt(v, 0), X(v) - 8, h - 10));
      const linea = (z, col, larg, punti) => {
        ctx.strokeStyle = col; ctx.lineWidth = larg; ctx.beginPath();
        xs.forEach((v, k) => (k ? ctx.lineTo(X(v), Y(z[k])) : ctx.moveTo(X(v), Y(z[k]))));
        ctx.stroke();
        if (punti) xs.forEach((v, k) => { ctx.beginPath(); ctx.arc(X(v), Y(z[k]), 4.5, 0, 7); ctx.fillStyle = col; ctx.fill(); ctx.strokeStyle = DV.colore("--superficie"); ctx.lineWidth = 2; ctx.stroke(); });
      };
      linea(To.z[0], DV.colore("--tenue"), 1.5, false);
      linea(Tm.z[0], DV.colore("--s1"), 2, true);
      this.geoCurva = {
        vicino: (x, y) => { let best = null, d = 14; xs.forEach((v, k) => { const dd = Math.hypot(X(v) - x, Y(Tm.z[0][k]) - y); if (dd < d) { d = dd; best = k; } }); return best; },
        yVal: (py) => y0 + (1 - (py - T) / (h - T - B)) * (y1 - y0), X, Y,
      };
      // punto di lavoro
      const r = S.ris.mod || S.ris.orig;
      const b = bloccoDi(tabelleInUso().get(this.tab.id));
      const u = r && b && DV.modello.tabellaAl(r, b, S.i) === this.tab.id && r.usate[b];
      if (u && u.x && S.sess) {
        const xv = u.x[S.i];
        if (Number.isFinite(xv)) {
          const xc = Math.min(Math.max(xv, x0), x1);
          ctx.strokeStyle = DV.colore("--testo"); ctx.setLineDash([4, 3]); ctx.beginPath(); ctx.moveTo(X(xc), T); ctx.lineTo(X(xc), h - B); ctx.stroke(); ctx.setLineDash([]);
          const yv = DV.calib.lookup1(xs, Tm.z[0], xv);
          ctx.beginPath(); ctx.arc(X(xc), Y(yv), 6, 0, 7); ctx.fillStyle = DV.colore("--s2"); ctx.fill();
          ctx.fillStyle = DV.colore("--testo"); ctx.fillText(`${DV.fmt(xv)} ${this.To.x.unita || ""} → ${DV.fmt(yv)} ${this.tab.unita || ""}`, Math.min(X(xc) + 8, w - 150), T + 12);
        }
      }
    },

    superficie(dove, To, Tm) {
      const cv = el("canvas", { class: "tela", style: { height: "380px", cursor: "grab" } });
      dove.append(cv, el("div", { class: "nota" }, `Trascina per ruotare. Grigio = A (${DV.nomeA()}), blu = B (${DV.nomeB()}).`));
      let ini = null;
      cv.addEventListener("mousedown", (e) => (ini = [e.clientX, e.clientY, vista3d.az, vista3d.el]));
      window.addEventListener("mousemove", (e) => { if (!ini) return; vista3d.az = ini[2] + (e.clientX - ini[0]) / 150; vista3d.el = Math.max(0.05, Math.min(1.5, ini[3] + (e.clientY - ini[1]) / 150)); disegna(); });
      window.addEventListener("mouseup", () => (ini = null));
      const disegna = () => {
        const dpr = devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
        cv.width = w * dpr; cv.height = h * dpr;
        const ctx = cv.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        const R = To.z.length, C = To.z[0].length;
        let mn = Infinity, mx = -Infinity;
        for (const Z of [To.z, Tm.z]) for (const r of Z) for (const v of r) { mn = Math.min(mn, v); mx = Math.max(mx, v); }
        const ca = Math.cos(vista3d.az), sa = Math.sin(vista3d.az), ce = Math.cos(vista3d.el), se = Math.sin(vista3d.el);
        const sc = Math.min(w, h) * 0.38;
        const P = (i, j, v) => {
          const x = j / (C - 1 || 1) - 0.5, y = i / (R - 1 || 1) - 0.5, z = mx > mn ? (v - mn) / (mx - mn) - 0.5 : 0;
          const xr = x * ca - y * sa, yr = x * sa + y * ca;
          return [w / 2 + xr * sc * 1.4, h / 2 + (yr * se - z * ce) * sc * 1.2];
        };
        const rete = (Z, col, lw) => {
          ctx.strokeStyle = col; ctx.lineWidth = lw;
          for (let i = 0; i < R; i++) { ctx.beginPath(); for (let j = 0; j < C; j++) { const [x, y] = P(i, j, Z[i][j]); j ? ctx.lineTo(x, y) : ctx.moveTo(x, y); } ctx.stroke(); }
          for (let j = 0; j < C; j++) { ctx.beginPath(); for (let i = 0; i < R; i++) { const [x, y] = P(i, j, Z[i][j]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); } ctx.stroke(); }
        };
        rete(To.z, DV.colore("--asse"), 1);
        rete(Tm.z, DV.colore("--s1"), 1.5);
        ctx.fillStyle = DV.colore("--testo-2"); ctx.font = "11px system-ui";
        ctx.fillText(`x: ${To.x.unita || ""}  y: ${To.y.unita || ""}  z: ${this.tab.unita || ""} [${DV.fmt(mn)} .. ${DV.fmt(mx)}]`, 10, 16);
      };
      requestAnimationFrame(disegna);
    },

    strumentiModifica(tab) {
      const box = el("div", { class: "pannello" });
      const val = el("input", { type: "number", step: "any", value: "1" });
      this.infoSel = el("span", { class: "nota" });
      const applica = (f) => {
        if (!S.binMod) return;
        const Z = this.Tm.z.map((r) => r.slice());
        const s = sel || [0, 0, Z.length - 1, Z[0].length - 1];
        annulla.push({ id: tab.id, z: this.Tm.z.map((r) => r.slice()) });
        f(Z, s, +val.value);
        for (let i = 0; i < Z.length; i++) for (let j = 0; j < Z[0].length; j++) Z[i][j] = DV.calib.quantizza(tab, Z[i][j]);
        const avv = DV.calib.scrivi(S.struttura, tab, S.binMod, Z);
        avv.forEach((a) => DV.avviso(a, "errore"));
        this.dopoModifica();
      };
      const per = (Z, s, f) => { for (let i = s[0]; i <= s[2]; i++) for (let j = s[1]; j <= s[3]; j++) f(i, j); };
      const B = (testo, titolo, f) => { const b = el("button", { class: "bottone", title: titolo }, testo); b.addEventListener("click", () => applica(f)); return b; };
      box.append(el("h3", {}, "Modifica (sulla copia di lavoro)"),
        el("div", { class: "strumenti" }, "valore", val,
          B("= imposta", "imposta il valore nelle celle selezionate", (Z, s, v) => per(Z, s, (i, j) => (Z[i][j] = v))),
          B("+ somma", "aggiunge il valore", (Z, s, v) => per(Z, s, (i, j) => (Z[i][j] += v))),
          B("× %", "aumenta/diminuisce in percentuale (es. 10 = +10%, -5 = -5%)", (Z, s, v) => per(Z, s, (i, j) => (Z[i][j] *= 1 + v / 100))),
          B("interpola", "riga per riga: dal primo all'ultimo valore della selezione", (Z, s) => { for (let i = s[0]; i <= s[2]; i++) { const a = Z[i][s[1]], b = Z[i][s[3]], n = s[3] - s[1]; for (let j = s[1]; j <= s[3]; j++) Z[i][j] = n ? a + ((b - a) * (j - s[1])) / n : a; } }),
          B("liscia", "media con le celle vicine", (Z, s) => { const C = Z.map((r) => r.slice()); per(Z, s, (i, j) => { let t = 0, n = 0; for (let di = -1; di <= 1; di++) for (let dj = -1; dj <= 1; dj++) { const r = C[i + di]; if (r && r[j + dj] !== undefined) { t += r[j + dj]; n++; } } Z[i][j] = t / n; }); }),
          B("↺ da A", "copia nella selezione i valori di A", (Z, s) => per(Z, s, (i, j) => (Z[i][j] = this.To.z[i][j]))),
          B("↺ file B", "riporta la selezione ai valori del file B (annulla le modifiche)", (Z, s) => { const F = DV.calib.leggi(S.struttura, tab, S.binCfrFile).z; per(Z, s, (i, j) => (Z[i][j] = F[i][j])); })),
        el("div", { class: "strumenti" }, this.infoSel,
          (() => { const b = el("button", { class: "bottone" }, "annulla"); b.addEventListener("click", () => { const u = annulla.pop(); if (!u) return; const t = S.struttura.tabelle.find((x) => x.id === u.id); DV.calib.scrivi(S.struttura, t, S.binMod, u.z); this.dopoModifica(); }); return b; })(),
          (() => { const b = el("button", { class: "bottone" }, "deseleziona"); b.addEventListener("click", () => { sel = null; this.aggiornaSel(); }); return b; })()),
        el("div", { class: "nota" }, "Ogni modifica viene arrotondata al passo reale del dato in centralina e ricalcola subito i criteri sulla sessione aperta (scheda Criteri: A → B)."));
      this.aggiornaSel();
      return box;
    },

    dopoModifica() {
      this.Tm = DV.calib.leggi(S.struttura, this.tab, S.binMod);
      DV.ricalcola("mod");
      DV.emit("calibrazione");
      this.disegnaTabella();
    },

    esportazione() {
      const box = el("div", { class: "pannello" });
      if (!S.binMod) return box;
      const v = DV.calib.verifica(S.struttura, S.binMod);
      const cambi = S.struttura.tabelle.filter((t) => editata(t));
      box.append(el("h3", {}, `Copia di lavoro di ${S.cfr}${S.binMod.variante ? " (variante " + S.binMod.variante + ")" : ""}`),
        el("div", { class: "nota" }, `${cambi.length} tabelle modificate rispetto al file ${S.cfr}${cambi.length ? ": " + cambi.map((t) => t.id).join(", ") : ""}.`),
        el("div", { class: "nota" }, v.length ? "Checksum: " + v.map((x) => `${x.id} ${x.ok ? "ok" : "da correggere (verrà corretto all'esportazione)"}`).join(", ") : "ATTENZIONE: nessun checksum nella struttura: il file esportato NON è pronto per la centralina."));
      const bBin = el("button", { class: "bottone primario" }, "Scarica .bin modificato");
      bBin.addEventListener("click", () => {
        const copia = DV.calib.copia(S.binMod);
        const r = DV.calib.correggi(S.struttura, copia);
        if (r.some((x) => !x.ok)) { DV.avviso("checksum non corretto: file non esportato", "errore"); return; }
        DV.scarica((S.cfr || "centralina") + "_mod.bin", copia);
      });
      const bPatch = el("button", { class: "bottone" }, "Scarica patch .json");
      bPatch.addEventListener("click", async () => {
        const mod = cambi.map((t) => ({ tabella: t.id, valori: DV.calib.leggi(S.struttura, t, S.binMod).z }));
        const c = DV.calDi(S.cfr);
        DV.scarica(`patch_${S.cfr}.json`, JSON.stringify({ base: S.cfr, base_sha256: c.sha, variante: c.variante, creato: new Date().toISOString(), modifiche: mod }, null, 1), "application/json");
      });
      box.append(el("div", { class: "strumenti" }, bBin, bPatch),
        el("div", { class: "nota" }, "Consigliato: applica la patch con «python -m dvtool calib applica» che riscrive le tabelle, corregge e verifica il checksum e controlla che il file di partenza sia quello giusto."));
      return box;
    },

    cursore() {
      // se il livello cambia (tabella in uso diversa) aggiorna l'elenco e i segni
      const ora = [...tabelleInUso()].filter(([, v]) => v.ora).map(([k]) => k).join(",");
      if (this.inUsoOra !== undefined && ora !== this.inUsoOra && S.struttura) { this.inUsoOra = ora; this.disegna(); return; }
      if (this.tab && (this.tab.tipo === "curva" || this.tab.tipo === "valore")) this.disegnaCurva();
      if (!this.svg || !this.celle || !this.celle.length || !S.sess) return;
      const r = S.ris.mod || S.ris.orig;
      const b = bloccoDi(tabelleInUso().get(this.tab.id));
      const u = r && b && DV.modello.tabellaAl(r, b, S.i) === this.tab.id && r.usate[b];
      this.svg.innerHTML = "";
      if (!u || !u.x || this.tab.tipo !== "mappa") return;
      const cont = this.svg.parentElement;
      this.svg.setAttribute("width", cont.scrollWidth); this.svg.setAttribute("height", cont.scrollHeight);
      const base = cont.getBoundingClientRect();
      const centro = (i, j) => { const rc = this.celle[i][j].getBoundingClientRect(); return [rc.left - base.left + rc.width / 2 + cont.scrollLeft, rc.top - base.top + rc.height / 2 + cont.scrollTop]; };
      const P = (k) => {
        const fx = DV.calib.posizione(this.To.x.valori, u.x[k]), fy = DV.calib.posizione(this.To.y.valori, u.y[k]);
        const j0 = Math.floor(fx), i0 = Math.floor(fy);
        const j1 = Math.min(j0 + 1, this.celle[0].length - 1), i1 = Math.min(i0 + 1, this.celle.length - 1);
        const [ax, ay] = centro(i0, j0), [bx] = centro(i0, j1), [, by] = centro(i1, j0);
        return [ax + (bx - ax) * (fx - j0), ay + (by - ay) * (fy - i0)];
      };
      const NS = "http://www.w3.org/2000/svg";
      const passi = Math.round(3 / S.dt);
      let d = "";
      for (let k = Math.max(0, S.i - passi); k <= S.i; k += 2) { if (!Number.isFinite(u.x[k]) || !Number.isFinite(u.y[k])) continue; const [x, y] = P(k); d += (d ? "L" : "M") + x.toFixed(1) + "," + y.toFixed(1); }
      const scia = document.createElementNS(NS, "path");
      scia.setAttribute("d", d); scia.setAttribute("fill", "none"); scia.setAttribute("stroke", DV.colore("--s2")); scia.setAttribute("stroke-width", "2"); scia.setAttribute("opacity", "0.85");
      this.svg.append(scia);
      if (Number.isFinite(u.x[S.i]) && Number.isFinite(u.y[S.i])) {
        const [x, y] = P(S.i);
        const c = document.createElementNS(NS, "circle");
        c.setAttribute("cx", x); c.setAttribute("cy", y); c.setAttribute("r", 7); c.setAttribute("fill", DV.colore("--s1")); c.setAttribute("stroke", DV.colore("--superficie")); c.setAttribute("stroke-width", "2");
        this.svg.append(c);
        const t = document.createElementNS(NS, "text");
        t.setAttribute("x", x + 10); t.setAttribute("y", y - 8); t.setAttribute("font-size", "11"); t.setAttribute("fill", DV.colore("--testo"));
        t.textContent = `${DV.fmt(u.x[S.i])} ${this.To.x.unita || ""} · ${DV.fmt(u.y[S.i])} ${this.To.y.unita || ""} → ${DV.fmt(DV.calib.lookup2(this.To.x.valori, this.To.y.valori, this.Tm.z, u.x[S.i], u.y[S.i]))} ${this.tab.unita || ""}`;
        this.svg.append(t);
        const bb = t.getBBox();
        const fondo = document.createElementNS(NS, "rect");
        fondo.setAttribute("x", bb.x - 4); fondo.setAttribute("y", bb.y - 2); fondo.setAttribute("width", bb.width + 8); fondo.setAttribute("height", bb.height + 4);
        fondo.setAttribute("rx", 4); fondo.setAttribute("fill", DV.colore("--superficie")); fondo.setAttribute("stroke", DV.colore("--bordo"));
        this.svg.insertBefore(fondo, t);
      }
    },
  };
  DV.registraVista("mappe", vista);
})();
