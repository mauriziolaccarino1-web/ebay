/* Grafici nel tempo (uPlot) con cursore comune, zoom condiviso e bande di "criterio soddisfatto" */
(function () {
  const DV = (window.DV = window.DV || {});
  const S = DV.stato;
  const tutti = new Set();
  let sincronizza = true;
  DV.colSerie = (k) => DV.colore(`--s${(k % 8) + 1}`);

  function bandePlugin(bande) {
    return {
      hooks: {
        drawClear: (u) => {
          if (!bande || !bande.length) return;
          const ctx = u.ctx;
          const { top, height } = u.bbox;
          const x0 = u.scales.x.min, x1 = u.scales.x.max;
          for (const b of bande) {
            if (!b.dati) continue;
            ctx.fillStyle = b.colore || DV.colore("--attivo-banda");
            const d = b.dati;
            const i0 = Math.max(0, Math.floor(x0 / S.dt)), i1 = Math.min(d.length - 1, Math.ceil(x1 / S.dt));
            let ini = -1;
            for (let i = i0; i <= i1 + 1; i++) {
              const on = i <= i1 && d[i] > 0.5;
              if (on && ini < 0) ini = i;
              if (!on && ini >= 0) {
                const a = u.valToPos(ini * S.dt, "x", true), z = u.valToPos(i * S.dt, "x", true);
                ctx.fillRect(a, top, Math.max(1, z - a), height);
                ini = -1;
              }
            }
          }
        },
      },
    };
  }

  // sui grafici in funzione della distanza nel giro: fasce e numeri delle curve
  function curvePlugin() {
    return {
      hooks: {
        drawClear: (u) => {
          const C = DV.curve();
          if (!C.length) return;
          const ctx = u.ctx, { top, height } = u.bbox;
          const dpr = devicePixelRatio || 1;
          ctx.save();
          ctx.fillStyle = DV.colore("--evidenzia");
          for (const c of C) {
            const a = u.valToPos(c.inizio, "x", true), b = u.valToPos(c.fine, "x", true);
            if (b < u.bbox.left || a > u.bbox.left + u.bbox.width) continue;
            ctx.fillRect(a, top, Math.max(1, b - a), height);
          }
          ctx.fillStyle = DV.colore("--testo-2");
          ctx.font = `${11 * dpr}px system-ui`;
          for (const c of C) {
            const x = u.valToPos(c.apice, "x", true);
            if (x < u.bbox.left || x > u.bbox.left + u.bbox.width) continue;
            ctx.fillText(c.id, x - 6 * dpr, top + 12 * dpr);
          }
          ctx.restore();
        },
      },
    };
  }

  // sui grafici nel tempo: numero della curva all'istante dell'apice, giro per giro
  function curveTempoPlugin() {
    return {
      hooks: {
        drawClear: (u) => {
          const A = DV.apiciTempo();
          if (!A.length) return;
          const ctx = u.ctx, { top, height, left, width } = u.bbox;
          const dpr = devicePixelRatio || 1;
          const span = u.scales.x.max - u.scales.x.min;
          if (span > 400) return;  // troppo zoom indietro: le etichette si sovrapporrebbero
          ctx.save();
          ctx.strokeStyle = DV.colore("--asse");
          ctx.setLineDash([2 * dpr, 3 * dpr]);
          ctx.fillStyle = DV.colore("--testo-2");
          ctx.font = `${10 * dpr}px system-ui`;
          for (const { i, c } of A) {
            const x = u.valToPos(i * S.dt, "x", true);
            if (x < left || x > left + width) continue;
            ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + height); ctx.stroke();
            ctx.fillText(c.id, x + 2 * dpr, top + 10 * dpr);
          }
          ctx.restore();
        },
      },
    };
  }

  DV.grafico = function (el, o) {
    const larghezza = Math.max(300, el.clientWidth || el.parentElement.clientWidth || 800);
    const x = o.x || S.t;
    const dati = [x, ...o.serie.map((s) => s.dati)];
    const testo = DV.colore("--testo-2"), griglia = DV.colore("--griglia");
    const asse = { stroke: testo, grid: { stroke: griglia, width: 1 }, ticks: { stroke: griglia, width: 1 }, font: "11px system-ui" };
    const opt = {
      width: larghezza, height: o.altezza || 160,
      cursor: { sync: { key: o.gruppo || "t" }, drag: { x: true, y: false }, points: { size: 6 } },
      legend: { show: o.legenda !== false, live: true },
      scales: { x: { time: false }, y: o.y ? { range: o.y } : {} },
      axes: [Object.assign({}, asse, { values: o.valoriX }), Object.assign({}, asse, { size: 56, label: o.unita || "", labelSize: 14, labelFont: "11px system-ui" })],
      series: [{ label: o.etichettaX || "t (s)", value: (u, v) => (v == null ? "–" : v.toFixed(2)) }, ...o.serie.map((s, k) => ({
        label: s.nome, stroke: s.colore || DV.colSerie(k), width: s.larghezza || 1.5,
        dash: s.tratteggio, value: (u, v) => (v == null || Number.isNaN(v) ? "–" : DV.fmt(v, s.decimali ?? 2) + (s.unita ? " " + s.unita : "")),
        points: { show: false }, spanGaps: false,
      }))],
      plugins: [bandePlugin(o.bande), ...(o.curve ? [curvePlugin()] : []), ...(!o.x && o.curve !== false ? [curveTempoPlugin()] : [])],
      hooks: {
        setScale: [(u, key) => {
          if (key !== "x" || !sincronizza || o.gruppo === "distanza") return;
          sincronizza = false;
          for (const g of tutti) if (g.u !== u && g.gruppo === (o.gruppo || "t")) g.u.setScale("x", { min: u.scales.x.min, max: u.scales.x.max });
          sincronizza = true;
        }],
      },
    };
    el.innerHTML = "";
    if (o.titolo) el.append(DV.el("div", { class: "titolo-grafico" }, o.titolo));
    const box = DV.el("div", { class: "grafico" });
    el.append(box);
    const u = new uPlot(opt, dati, box);
    const linea = DV.el("div", { style: { position: "absolute", top: "0", bottom: "0", width: "0", borderLeft: `1.5px solid ${DV.colore("--testo")}`, pointerEvents: "none" } });
    u.over.append(linea);
    const g = { u, el, gruppo: o.gruppo || "t", linea, xDi: o.xDi };
    tutti.add(g);
    u.over.addEventListener("click", (e) => {
      if (u.select.width > 2) return;
      const v = u.posToVal(e.offsetX, "x");
      if (o.alClic) o.alClic(v); else DV.vaiA(v / S.dt);
    });
    g.posiziona = () => {
      const xv = g.xDi ? g.xDi(S.i) : S.i * S.dt;
      if (xv === null || xv === undefined || Number.isNaN(xv)) { linea.style.display = "none"; return; }
      const px = u.valToPos(xv, "x");
      linea.style.display = px < 0 || px > u.over.clientWidth ? "none" : "";
      linea.style.left = px + "px";
    };
    g.posiziona();
    if (S.zoom && g.gruppo === "t") u.setScale("x", S.zoom);
    g.distruggi = () => { tutti.delete(g); u.destroy(); };
    return g;
  };

  DV.on("cursore", () => { for (const g of tutti) if (g.el.isConnected) g.posiziona(); });
  DV.zoomTempo = (min, max) => {
    S.zoom = min === null ? null : { min, max };
    for (const g of tutti) {
      if (!g.el.isConnected || g.gruppo !== "t") continue;
      if (min === null) g.u.setScale("x", { min: 0, max: (S.n - 1) * S.dt });
      else g.u.setScale("x", { min, max });
    }
  };
  DV.pulisciGrafici = (radice) => { for (const g of [...tutti]) if (!g.el.isConnected || (radice && radice.contains(g.el))) g.distruggi(); };
  window.addEventListener("resize", () => {
    for (const g of tutti) if (g.el.isConnected && g.el.clientWidth) g.u.setSize({ width: g.el.clientWidth, height: g.u.height });
  });

  // colore della scala sequenziale (0..1) e divergente (-1..1)
  DV.seq = (f) => {
    const k = Math.max(0, Math.min(6, Math.round(f * 6)));
    return DV.colore(`--seq-${k}`);
  };
  DV.inkSu = (f) => (f > 0.55 ? "#ffffff" : "");
  function mescola(a, b, f) {
    const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
    const c = [16, 8, 0].map((s) => Math.round(((pa >> s) & 255) * (1 - f) + ((pb >> s) & 255) * f));
    return "#" + c.map((v) => v.toString(16).padStart(2, "0")).join("");
  }
  DV.div = (f) => {
    f = Math.max(-1, Math.min(1, f));
    const mid = DV.colore("--div-mid");
    return f < 0 ? mescola(mid, DV.colore("--div-neg"), -f) : mescola(mid, DV.colore("--div-pos"), f);
  };
  DV.mescola = mescola;
})();
