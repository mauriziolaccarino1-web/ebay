/* Scheda Acquisizione: canali nel tempo (stessa unità = stesso grafico), mappa della pista, valori al cursore */
(function () {
  const DV = window.DV;
  const S = DV.stato;
  const { el } = DV;
  const radice = document.getElementById("v-acquisizione");
  let scelti = null;
  const PREDEFINITI = ["v_ant", "v_post", "piega", "giri", "gas", "farfalla", "marcia", "tc_attivo", "taglio_can"];

  const vista = {
    alGiro: true,
    disegna() {
      DV.pulisciGrafici(radice);
      radice.innerHTML = "";
      if (!S.sess) return;
      if (!scelti) scelti = new Set(PREDEFINITI.filter((x) => S.canali.has(x)));
      const elenco = el("div", { class: "pannello elenco" });
      const cerca = el("input", { type: "text", placeholder: "cerca canale…", style: { width: "100%", marginBottom: "6px" } });
      elenco.append(el("h3", {}, "Canali"), cerca);
      const gruppi = new Map();
      for (const c of S.canali.values()) {
        const g = c.gruppo || "altri";
        if (!gruppi.has(g)) gruppi.set(g, []);
        gruppi.get(g).push(c);
      }
      const corpo = el("div");
      for (const [g, cs] of gruppi) {
        const d = el("details", { open: g === "principali" || g === "giri" ? true : undefined }, el("summary", {}, `${g} (${cs.length})`));
        for (const c of cs) {
          const cb = el("input", { type: "checkbox", checked: scelti.has(c.id) || undefined });
          cb.addEventListener("change", () => { cb.checked ? scelti.add(c.id) : scelti.delete(c.id); disegnaGrafici(); });
          d.append(el("label", { "data-nome": (c.nome + " " + c.id).toLowerCase() }, cb, c.nome, el("span", { class: "u" }, c.unita)));
        }
        corpo.append(d);
      }
      cerca.addEventListener("input", () => {
        const q = cerca.value.toLowerCase();
        corpo.querySelectorAll("label").forEach((l) => (l.style.display = !q || l.dataset.nome.includes(q) ? "" : "none"));
        if (q) corpo.querySelectorAll("details").forEach((d) => (d.open = true));
      });
      elenco.append(corpo);
      const destra = el("div", { class: "righe" });
      const grafici = el("div", { class: "pannello" });
      const sotto = el("div", { class: "fila", style: { alignItems: "stretch" } });
      this.mappa = el("canvas", { class: "tela", style: { height: "320px", flex: "1 1 340px" } });
      this.valori = el("div", { class: "pannello", style: { flex: "1 1 300px" } });
      sotto.append(el("div", { class: "pannello", style: { flex: "1 1 360px" } }, el("h3", {}, "Pista ricostruita (senza GPS)"),
        el("div", { class: "nota" }, "Forma ottenuta integrando la direzione: g·tan(piega)/v. Il punto è la posizione al cursore; il colore della traccia segue gli interventi previsti."),
        this.mappa), this.valori);
      destra.append(grafici, sotto);
      radice.append(el("div", { class: "griglia2" }, elenco, destra));
      const disegnaGrafici = () => {
        DV.pulisciGrafici(grafici);
        grafici.innerHTML = "";
        const perUnita = new Map();
        for (const id of scelti) {
          const c = S.canali.get(id);
          if (!c) continue;
          const u = c.unita || "–";
          if (!perUnita.has(u)) perUnita.set(u, []);
          perUnita.get(u).push(c);
        }
        if (!perUnita.size) grafici.append(el("p", { class: "nota" }, "Scegli i canali a sinistra."));
        const banda = (S.ris.mod || S.ris.orig) ? [{ dati: (S.ris.mod || S.ris.orig).logica }] : [];
        for (const [u, cs] of perUnita) {
          const box = el("div");
          grafici.append(box);
          DV.grafico(box, { unita: u, altezza: cs.length > 2 ? 190 : 150, bande: banda,
            serie: cs.map((c, k) => ({ nome: c.nome, dati: c.dati, unita: c.unita, colore: DV.colSerie(k) })) });
        }
        grafici.append(el("div", { class: "nota" }, "Trascina per ingrandire, doppio clic per tornare indietro, clic per spostare il cursore. Le bande rosse sono gli istanti in cui la catena ricalcolata interviene."));
      };
      disegnaGrafici();
      this.disegnaMappa();
      this.cursore();
    },
    disegnaMappa() {
      const cv = this.mappa;
      if (!cv) return;
      const G = S.sess.giri;
      const dpr = devicePixelRatio || 1;
      const w = cv.clientWidth, h = cv.clientHeight;
      cv.width = w * dpr; cv.height = h * dpr;
      const ctx = cv.getContext("2d", { willReadFrequently: true });
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      if (!G || !G.mappa_xy) { ctx.fillStyle = DV.colore("--tenue"); ctx.fillText("mappa non disponibile (serve la piega o l'imbardata)", 12, 20); this.sfondo = null; return; }
      const P = G.mappa_xy;
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      for (const [x, y] of P) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
      const sc = Math.min((w - 30) / (x1 - x0 || 1), (h - 30) / (y1 - y0 || 1));
      this.trasf = (x, y) => [15 + (x - x0) * sc + ((w - 30) - (x1 - x0) * sc) / 2, h - 15 - (y - y0) * sc - ((h - 30) - (y1 - y0) * sc) / 2];
      // quanto spesso interviene ogni tratto della pista (sui giri lanciati)
      const r = S.ris.mod || S.ris.orig;
      const sg = DV.canale("s_giro");
      const peso = new Float64Array(P.length), cont = new Float64Array(P.length);
      if (r && sg) {
        for (let i = 0; i < S.n; i++) {
          const s = sg.dati[i];
          if (!Number.isFinite(s)) continue;
          const k = Math.min(P.length - 1, Math.max(0, Math.round(s / G.mappa_ds)));
          cont[k]++;
          if (r.logica[i] > 0.5) peso[k]++;
        }
      }
      ctx.lineWidth = 6;
      ctx.lineCap = "round";
      for (let k = 1; k < P.length; k++) {
        const f = cont[k] ? peso[k] / cont[k] : 0;
        ctx.strokeStyle = f > 0.02 ? DV.mescola(DV.colore("--asse").length === 7 ? DV.colore("--asse") : "#c3c2b7", DV.colore("--critico"), Math.min(1, f * 4)) : DV.colore("--asse");
        ctx.beginPath();
        ctx.moveTo(...this.trasf(...P[k - 1]));
        ctx.lineTo(...this.trasf(...P[k]));
        ctx.stroke();
      }
      const [lx, ly] = this.trasf(...P[0]);
      ctx.fillStyle = DV.colore("--testo");
      ctx.fillRect(lx - 1, ly - 9, 3, 18);
      ctx.font = "11px system-ui";
      ctx.fillText("traguardo stimato", lx + 6, ly - 6);
      this.sfondo = ctx.getImageData(0, 0, cv.width, cv.height);
    },
    cursore() {
      if (!S.sess || !this.valori) return;
      // punto sulla pista
      const cv = this.mappa;
      if (this.sfondo && cv) {
        const ctx = cv.getContext("2d", { willReadFrequently: true });
        ctx.putImageData(this.sfondo, 0, 0);
        const sg = DV.valore("s_giro");
        const G = S.sess.giri;
        if (Number.isFinite(sg) && G.mappa_xy) {
          const k = Math.min(G.mappa_xy.length - 1, Math.max(0, Math.round(sg / G.mappa_ds)));
          const [x, y] = this.trasf(...G.mappa_xy[k]);
          const dpr = devicePixelRatio || 1;
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
          ctx.beginPath();
          ctx.arc(x, y, 7, 0, Math.PI * 2);
          ctx.fillStyle = DV.colore("--s1");
          ctx.fill();
          ctx.lineWidth = 2;
          ctx.strokeStyle = DV.colore("--superficie");
          ctx.stroke();
        }
      }
      // valori al cursore
      const righe = [];
      for (const id of scelti || []) {
        const c = S.canali.get(id);
        if (c) righe.push(el("tr", {}, el("td", {}, c.nome), el("td", { class: "n" }, DV.fmt(c.dati[S.i])), el("td", {}, c.unita)));
      }
      const r = S.ris.mod || S.ris.orig;
      this.valori.innerHTML = "";
      this.valori.append(el("h3", {}, `Valori a t = ${(S.i * S.dt).toFixed(2)} s`));
      if (r) {
        const on = r.logica[S.i] > 0.5;
        this.valori.append(el("div", { class: "stato " + (on ? "si" : "no") }, el("span", { class: "pallino" }), on ? "✕ la catena interviene" : "✓ nessun intervento"));
      }
      this.valori.append(el("table", { class: "dati" }, el("tbody", {}, righe)));
    },
  };
  DV.registraVista("acquisizione", vista);
})();
