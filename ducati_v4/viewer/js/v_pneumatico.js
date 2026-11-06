/* Scheda Profilo pneumatico: raggio di rotolamento in piega, sezione ricostruita, punto di contatto al cursore,
   effetto della modifica sullo slittamento calcolato e verifica sul registrato (slittamento residuo in rilascio) */
(function () {
  const DV = window.DV;
  const S = DV.stato;
  const { el } = DV;
  const radice = document.getElementById("v-pneumatico");
  const NS = "http://www.w3.org/2000/svg";
  const RAD = Math.PI / 180;

  function inMm(p, z) {
    const R0 = p.R0_mm || 300;
    if (p.grandezza === "fattore") return z.map((v) => v * R0);
    if (p.grandezza === "delta_mm") return z.map((v) => R0 + v);
    return z.slice();
  }
  function daMm(p, R) {
    const R0 = p.R0_mm || 300;
    if (p.grandezza === "fattore") return R.map((v) => v / R0);
    if (p.grandezza === "delta_mm") return R.map((v) => v - R0);
    return R;
  }
  function profilo(p, buf) {
    const tab = S.struttura.tabelle.find((t) => t.id === p.tabella);
    const T = DV.calib.leggi(S.struttura, tab, buf);
    return { tab, phi: T.x.valori, R: inMm(p, T.z[0]) };
  }
  // sezione: dy/dphi = -(dR/dphi)/tan(phi)  -> punti (y, r)
  function sezione(phi, R) {
    const pts = [[0, R[0]]];
    let y = 0;
    for (let k = 0; k < phi.length - 1; k++) {
      const pm = Math.max(0.5, (phi[k] + phi[k + 1]) / 2) * RAD;
      y += -(R[k + 1] - R[k]) / Math.tan(pm);
      pts.push([y, R[k + 1]]);
    }
    return pts;
  }
  const interp = (xs, ys, x) => DV.calib.lookup1(xs, ys, x);

  // slittamento residuo in rilascio, per fascia di piega, dal registrato
  function residuo(pa, pp, quale) {
    const va = DV.canale("v_ant"), vp = DV.canale("v_post"), pg = DV.canale("piega"), gas = DV.canale("gas");
    if (!va || !vp || !pg) return null;
    const [a, b] = DV.intervallo();
    const passo = 2.5, nb = 28;
    const somme = Array.from({ length: nb }, () => []);
    for (let i = a + 5; i < b - 5; i++) {
      const v = va.dati[i];
      if (!(v > 40) || !(vp.dati[i] > 40)) continue;
      if (gas && !(gas.dati[i] < 8)) continue;
      const acc = ((va.dati[i + 5] - va.dati[i - 5]) / 3.6) / (10 * S.dt);
      if (Math.abs(acc) > 1.5) continue;
      const f = Math.abs(pg.dati[i]);
      const k = Math.floor(f / passo);
      if (k >= nb) continue;
      const Rf = interp(pa[quale].phi, pa[quale].R, f) / (pa.def.R0_mm || 300);
      const Rr = interp(pp[quale].phi, pp[quale].R, f) / (pp.def.R0_mm || 300);
      somme[k].push(((vp.dati[i] * Rr) / (v * Rf) - 1) * 100);
    }
    return somme.map((s, k) => {
      if (s.length < 20) return null;
      s.sort((x, y) => x - y);
      return { piega: (k + 0.5) * passo, mediana: s[Math.floor(s.length / 2)], n: s.length };
    }).filter(Boolean);
  }

  const vista = {
    alGiro: true,
    disegna() {
      DV.pulisciGrafici(radice);
      radice.innerHTML = "";
      const P = (S.struttura && S.struttura.profili_pneumatico) || [];
      if (!S.struttura || !S.binOrig || !P.length) {
        radice.append(el("div", { class: "pannello" }, el("h3", {}, "Profilo pneumatico"),
          el("p", { class: "nota" }, "Servono struttura e file .bin, e nella struttura la voce \"profili_pneumatico\" che indica quale tabella contiene il profilo (raggio di rotolamento in funzione della piega) per ogni ruota.")));
        return;
      }
      this.prof = P.map((p) => ({ def: p, orig: profilo(p, S.binOrig), mod: profilo(p, S.binMod) }));
      this.carte = [];
      for (const pr of this.prof) {
        const p = pr.def;
        const carta = el("div", { class: "pannello", style: { marginBottom: "12px" } });
        carta.append(el("h3", {}, `${p.ruota || p.id} · ${p.misura || ""} · tabella ${p.tabella}`),
          el("div", { class: "nota" }, `R0 = ${p.R0_mm} mm a moto dritta. Grigio = A (${DV.nomeA()}), blu = B (${DV.nomeB()}). Il punto è il contatto all'angolo di piega del cursore.`));
        const fila = el("div", { class: "fila", style: { alignItems: "stretch" } });
        const sez = el("div", { style: { flex: "1 1 380px" } });
        const gr = el("div", { style: { flex: "1 1 420px" } });
        fila.append(sez, gr);
        carta.append(fila);
        // generatore toroidale
        const r0 = el("input", { type: "number", value: p.R0_mm, step: "0.1" }), rc = el("input", { type: "number", value: "100", step: "1" });
        const b = el("button", { class: "bottone" }, `applica a B (${S.cfr})`);
        b.addEventListener("click", () => {
          const phi = pr.mod.phi;
          const R = phi.map((f) => +r0.value - +rc.value * (1 - Math.cos(f * RAD)));
          const z = [daMm(p, R).map((v) => DV.calib.quantizza(pr.mod.tab, v))];
          DV.calib.scrivi(S.struttura, pr.mod.tab, S.binMod, z);
          DV.ricalcola("mod");
          DV.emit("calibrazione");
          this.disegna();
        });
        carta.append(el("div", { class: "strumenti" }, "Profilo toroidale: R0", r0, "mm · raggio della corona", rc, "mm", b,
          el("span", { class: "nota" }, "R(φ) = R0 − rc·(1 − cos φ). Per modifiche punto per punto usa la scheda Mappe.")));
        radice.append(carta);
        this.carte.push({ pr, sez, gr });
        // grafico R(φ)
        const phiD = [];
        for (let f = pr.orig.phi[0]; f <= pr.orig.phi[pr.orig.phi.length - 1] + 1e-9; f += 0.5) phiD.push(f);
        const Ro = phiD.map((f) => interp(pr.orig.phi, pr.orig.R, f)), Rm = phiD.map((f) => interp(pr.mod.phi, pr.mod.R, f));
        const pg = DV.canale("piega");
        DV.grafico(gr, {
          titolo: "Raggio di rotolamento in funzione della piega", x: Float64Array.from(phiD), gruppo: "pneu-" + p.id, unita: "mm", etichettaX: "piega (°)",
          serie: [{ nome: DV.nomeA(), dati: Float64Array.from(Ro), colore: DV.colore("--tenue"), unita: "mm" }, { nome: DV.nomeB(), dati: Float64Array.from(Rm), colore: DV.colore("--s1"), unita: "mm" }],
          xDi: pg ? (i) => Math.abs(pg.dati[i]) : null, alClic: () => {}, altezza: 190,
        });
        const corr = el("div");
        gr.append(corr);
        DV.grafico(corr, {
          titolo: "Correzione della velocità ruota (R/R0 − 1)", x: Float64Array.from(phiD), gruppo: "pneu-" + p.id, unita: "%", etichettaX: "piega (°)",
          serie: [{ nome: DV.nomeA(), dati: Float64Array.from(Ro.map((v) => (v / p.R0_mm - 1) * 100)), colore: DV.colore("--tenue"), unita: "%" },
            { nome: DV.nomeB(), dati: Float64Array.from(Rm.map((v) => (v / p.R0_mm - 1) * 100)), colore: DV.colore("--s1"), unita: "%" }],
          xDi: pg ? (i) => Math.abs(pg.dati[i]) : null, alClic: () => {}, altezza: 150,
        });
      }
      // effetto combinato e verifica sul registrato
      const ant = this.prof.find((x) => /ant|front/i.test(x.def.ruota || x.def.id));
      const post = this.prof.find((x) => /post|rear/i.test(x.def.ruota || x.def.id));
      if (ant && post) {
        const box = el("div", { class: "pannello" });
        radice.append(box);
        const phiD = [];
        for (let f = 0; f <= 60; f += 0.5) phiD.push(f);
        const eff = phiD.map((f) => {
          const ro = interp(post.orig.phi, post.orig.R, f) / interp(ant.orig.phi, ant.orig.R, f);
          const rm = interp(post.mod.phi, post.mod.R, f) / interp(ant.mod.phi, ant.mod.R, f);
          return (rm / ro - 1) * 100;
        });
        const g1 = el("div");
        box.append(el("h3", {}, "Effetto di B rispetto ad A sullo slittamento calcolato"),
          el("div", { class: "nota" }, `Passando da A (${DV.nomeA()}) a B (${DV.nomeB()}), a parità di ruote, quanto cambia lo slittamento posteriore che la centralina calcola, in punti percentuali, in funzione della piega. Positivo = con B la centralina vede più slittamento (interviene prima).`), g1);
        const pg = DV.canale("piega");
        const emax = Math.max(1, ...eff.map(Math.abs)) * 1.2;
        DV.grafico(g1, { x: Float64Array.from(phiD), gruppo: "pneu-eff", unita: "punti %", etichettaX: "piega (°)", altezza: 170, y: [-emax, emax],
          serie: [{ nome: "variazione slittamento calcolato", dati: Float64Array.from(eff), colore: DV.colore("--s2"), unita: "%" }],
          xDi: pg ? (i) => Math.abs(pg.dati[i]) : null, alClic: () => {} });
        const ro = residuo(ant, post, "orig"), rm = residuo(ant, post, "mod");
        if (ro && ro.length > 3) {
          const g2 = el("div");
          box.append(el("h3", { style: { marginTop: "12px" } }, "Verifica sul registrato: slittamento residuo in rilascio"),
            el("div", { class: "nota" }, `In rilascio (gas < 8 %, velocità costante, oltre 40 km/h) la ruota posteriore non spinge: lo slittamento corretto con il profilo dovrebbe stare vicino a zero a ogni piega. Una curva che sale o scende con la piega dice che il profilo in tabella non è quello della gomma montata. Dati: ${S.giro ? "giro scelto" : "tutta la sessione"}.`), g2);
          const xs = ro.map((x) => x.piega);
          const mapM = new Map((rm || []).map((x) => [x.piega, x.mediana]));
          DV.grafico(g2, { x: Float64Array.from(xs), gruppo: "pneu-res", unita: "%", etichettaX: "piega (°)", altezza: 190,
            serie: [{ nome: `con profilo ${DV.nomeA()}`, dati: Float64Array.from(ro.map((x) => x.mediana)), colore: DV.colore("--tenue"), unita: "%" },
              { nome: `con profilo ${DV.nomeB()}`, dati: Float64Array.from(xs.map((x) => mapM.get(x) ?? NaN)), colore: DV.colore("--s1"), unita: "%" }],
            alClic: () => {} });
          box.append(el("table", { class: "dati", style: { maxWidth: "520px" } }, el("thead", {}, el("tr", {}, el("th", { class: "n" }, "piega °"), el("th", { class: "n" }, "campioni"), el("th", { class: "n" }, `${DV.nomeA()} %`), el("th", { class: "n" }, `${DV.nomeB()} %`))),
            el("tbody", {}, ro.map((x) => el("tr", {}, el("td", { class: "n" }, x.piega.toFixed(1)), el("td", { class: "n" }, String(x.n)), el("td", { class: "n" }, x.mediana.toFixed(2)), el("td", { class: "n" }, DV.fmt(mapM.get(x.piega))))))));
        } else box.append(el("p", { class: "nota" }, "Per la verifica sul registrato servono i canali v_ant, v_post, piega (e gas) nella sessione, con abbastanza tratti in rilascio."));
      }
      this.cursore();
    },
    cursore() {
      if (!this.carte) return;
      const pg = DV.canale("piega");
      const phiC = pg && S.sess ? Math.abs(pg.dati[S.i]) : null;
      for (const c of this.carte) this.sezione(c, phiC);
    },
    sezione(c, phiC) {
      const { pr, sez } = c;
      const p = pr.def;
      const So = sezione(pr.orig.phi, pr.orig.R), Sm = sezione(pr.mod.phi, pr.mod.R);
      const w = Math.max(320, sez.clientWidth || 380), h = 300;
      const tutti = [...So, ...Sm];
      const ymax = Math.max(...tutti.map((q) => Math.abs(q[0])), (p.larghezza_mm || 120) / 2) * 1.15;
      const rmin = Math.min(...tutti.map((q) => q[1])) - 15, rmax = Math.max(...tutti.map((q) => q[1])) + 12;
      const sc = Math.min((w - 20) / (2 * ymax), (h - 40) / (rmax - rmin));
      const X = (y) => w / 2 + y * sc, Y = (r) => h - 20 - (r - rmin) * sc;
      const path = (pts) => {
        const tutto = [...pts.slice().reverse().map(([y, r]) => [-y, r]), ...pts.slice(1)];
        return tutto.map(([y, r], k) => `${k ? "L" : "M"}${X(y).toFixed(1)},${Y(r).toFixed(1)}`).join("");
      };
      let svg = `<svg xmlns="${NS}" width="${w}" height="${h}" style="display:block">`;
      svg += `<line x1="${X(0)}" y1="10" x2="${X(0)}" y2="${h - 10}" stroke="${DV.colore("--griglia")}" stroke-dasharray="3 3"/>`;
      svg += `<path d="${path(So)}" fill="none" stroke="${DV.colore("--tenue")}" stroke-width="1.5" stroke-dasharray="5 3"/>`;
      svg += `<path d="${path(Sm)}" fill="none" stroke="${DV.colore("--s1")}" stroke-width="2"/>`;
      let testo = "";
      if (phiC !== null && Number.isFinite(phiC)) {
        const phiMax = pr.mod.phi[pr.mod.phi.length - 1];
        const f = Math.min(phiC, phiMax);
        const k = Math.min(pr.mod.phi.length - 2, Math.max(0, pr.mod.phi.findIndex((v, j) => j < pr.mod.phi.length - 1 && f <= pr.mod.phi[j + 1])));
        const t = (f - pr.mod.phi[k]) / ((pr.mod.phi[k + 1] - pr.mod.phi[k]) || 1);
        const yc = Sm[k][0] + (Sm[k + 1][0] - Sm[k][0]) * t, rcv = Sm[k][1] + (Sm[k + 1][1] - Sm[k][1]) * t;
        const Ro = interp(pr.orig.phi, pr.orig.R, f);
        const L = 80, dx = Math.cos(f * RAD), dy = -Math.sin(f * RAD);
        svg += `<line x1="${X(yc - L * dx)}" y1="${Y(rcv - L * dy)}" x2="${X(yc + L * dx)}" y2="${Y(rcv + L * dy)}" stroke="${DV.colore("--testo-2")}" stroke-width="1.5"/>`;
        svg += `<circle cx="${X(yc)}" cy="${Y(rcv)}" r="6" fill="${DV.colore("--s2")}" stroke="${DV.colore("--superficie")}" stroke-width="2"/>`;
        testo = `piega ${phiC.toFixed(1)}° · R ${rcv.toFixed(1)} mm (${DV.nomeA()} ${Ro.toFixed(1)}, ${(rcv - Ro >= 0 ? "+" : "") + (rcv - Ro).toFixed(1)}) · contatto a ${yc.toFixed(0)} mm dal centro`;
      }
      svg += `<text x="10" y="16" font-size="11" fill="${DV.colore("--testo-2")}">sezione ricostruita dal profilo (mm)</text></svg>`;
      sez.innerHTML = svg;
      sez.append(el("div", { class: "nota" }, testo || "Sposta il cursore su un tratto in piega per vedere il punto di contatto."));
    },
  };
  DV.registraVista("pneumatico", vista);
})();
