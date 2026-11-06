/* Stato, caricamento dei file e utilità comuni del visualizzatore */
(function () {
  const DV = (window.DV = window.DV || {});
  const S = (DV.stato = {
    sess: null, struttura: null, modello: null,
    // calibrazioni caricate: {nome, file (com'è su disco), lavoro (copia modificabile), variante}
    cal: [], rif: null, cfr: null,
    canali: new Map(), n: 0, dt: 0.01, i: 0, giro: null, parametri: {},
    ris: { orig: null, mod: null }, progetto: null, server: false,
  });
  // A = riferimento, B = confronto (copia di lavoro modificabile)
  const calDi = (n) => S.cal.find((c) => c.nome === n) || null;
  Object.defineProperty(S, "binOrig", { get: () => (calDi(S.rif) ? calDi(S.rif).file : null) });
  Object.defineProperty(S, "binMod", { get: () => (calDi(S.cfr) ? calDi(S.cfr).lavoro : null) });
  Object.defineProperty(S, "binCfrFile", { get: () => (calDi(S.cfr) ? calDi(S.cfr).file : null) });
  Object.defineProperty(S, "nomeOrig", { get: () => S.rif || "" });
  Object.defineProperty(S, "nomeMod", { get: () => S.cfr || "" });
  DV.calDi = calDi;
  // quale calibrazione mostrano Flusso e Tabelle dal vivo: "B" (default) o "A"
  S.vistaCal = "B";
  DV.risVista = () => (S.vistaCal === "A" ? S.ris.orig || S.ris.mod : S.ris.mod || S.ris.orig);
  DV.bufVista = () => (S.vistaCal === "A" ? S.binOrig || S.binMod : S.binMod || S.binOrig);
  DV.nomeVista = () => (S.vistaCal === "A" ? DV.nomeA() : DV.nomeB());
  DV.selettoreVista = (dopo) => {
    const s = DV.el("select", { title: "calibrazione con cui sono calcolati i valori mostrati" });
    for (const [k, n] of [["A", `A · ${DV.nomeA()}`], ["B", `B · ${DV.nomeB()}`]]) s.append(DV.el("option", { value: k, selected: S.vistaCal === k || undefined }, n));
    s.addEventListener("change", () => { S.vistaCal = s.value; dopo(); });
    return DV.el("label", { class: "fila", style: { gap: "6px" } }, "calcolato con", s);
  };
  DV.confrontoAttivo = () => !!(S.ris.mod && S.ris.orig && (S.rif !== S.cfr || DV.lavoroModificato()));
  // concordanza tra intervento previsto e osservato sul CAN (interventi in comune / unione)
  DV.concordanza = (r, o) => {
    const c = DV.canale(o.id);
    if (!r || !c) return null;
    const v = (o.confronta_con && r.env[o.confronta_con]) || r.logica;
    let tp = 0, un = 0;
    for (let i = 0; i < S.n; i++) {
      const a = c.dati[i] > (o.soglia ?? 0.5), b = v[i] > 0.5;
      if (a && b) tp++;
      if (a || b) un++;
    }
    return un ? tp / un : 1;
  };
  DV.nomeA = () => S.rif || "A";
  DV.nomeB = () => (S.cfr ? S.cfr + (DV.lavoroModificato() ? " ✎" : "") : "B");
  DV.lavoroModificato = () => {
    const c = calDi(S.cfr);
    if (!c) return false;
    for (let i = 0; i < c.file.length; i++) if (c.file[i] !== c.lavoro[i]) return true;
    return false;
  };
  function assegnaVariante(c) {
    const V = (S.struttura && S.struttura.varianti) || [];
    if (!V.length) { c.variante = null; return; }
    const perSha = c.sha && V.find((v) => v.sha256 && v.sha256.toLowerCase() === c.sha);
    const v = perSha ? perSha.nome : c.varianteIndicata || DV.calib.varianteDaNome(S.struttura, c.nome) || DV.calib.varianteDaNome(S.struttura, c.fileNome);
    c.variante = v || null;
    c.file.variante = c.lavoro.variante = c.variante;
    c.file.nome = c.lavoro.nome = c.nome;
    if (!v) DV.avviso(`${c.nome}: variante non riconosciuta (varianti: ${V.map((x) => x.nome).join(", ")})`, "errore");
  }
  DV.aggiungiCalibrazione = async (nome, buf, opz = {}) => {
    let sha = null;
    try { const h = await crypto.subtle.digest("SHA-256", buf); sha = [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join(""); } catch (e) { /* senza crypto.subtle */ }
    let nn = nome, k = 2;
    while (calDi(nn)) nn = `${nome} (${k++})`;
    const c = { nome: nn, file: buf, lavoro: buf.slice(), sha, fileNome: opz.file || nome, varianteIndicata: opz.variante };
    assegnaVariante(c);
    S.cal.push(c);
    if (!S.rif) S.rif = nn;
    if (!S.cfr || S.cfr === S.rif) S.cfr = nn;
    return c;
  };
  DV.scegliCalibrazioni = (rif, cfr) => {
    if (rif) S.rif = rif;
    if (cfr) S.cfr = cfr;
    DV.emit("calibrazione");
    DV.ricalcola();
  };
  DV.viste = {};
  DV.registraVista = (nome, oggetto) => (DV.viste[nome] = oggetto);
  const ascolti = {};
  DV.on = (ev, f) => (ascolti[ev] = ascolti[ev] || []).push(f);
  DV.emit = (ev, x) => (ascolti[ev] || []).forEach((f) => { try { f(x); } catch (e) { console.error(e); DV.avviso(String(e.message || e), "errore"); } });
  DV.on("struttura", () => S.cal.forEach(assegnaVariante));

  DV.$ = (s, r = document) => r.querySelector(s);
  DV.$$ = (s, r = document) => [...r.querySelectorAll(s)];
  DV.el = (tag, attr = {}, ...figli) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attr || {})) {
      if (k === "class") e.className = v;
      else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? "" : v);
    }
    for (const f of figli.flat()) if (f !== null && f !== undefined && f !== false) e.append(f instanceof Node ? f : document.createTextNode(String(f)));
    return e;
  };
  DV.fmt = (v, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? "–" : Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(d));
  DV.tempo = (s) => {
    if (s === null || s === undefined || !isFinite(s)) return "–";
    const m = Math.floor(s / 60);
    return `${m}:${(s - m * 60).toFixed(3).padStart(6, "0")}`;
  };
  DV.avviso = (msg, tipo = "info") => {
    const box = DV.$("#avvisi");
    const e = DV.el("div", { class: "avviso " + tipo }, msg);
    box.append(e);
    setTimeout(() => e.remove(), tipo === "errore" ? 12000 : 5000);
  };

  // ---------------------------------------------------------------- decodifica canali
  function daB64(b64) {
    const bin = atob(b64);
    const u = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
    return new Float32Array(u.buffer);
  }
  DV.daB64 = daB64;

  async function testoDa(file) {
    if (file.name.endsWith(".gz")) {
      if (!window.DecompressionStream) throw new Error("questo browser non apre i .gz: usa Chrome/Edge recenti o salva la sessione senza .gz");
      const ds = file.stream().pipeThrough(new DecompressionStream("gzip"));
      return await new Response(ds).text();
    }
    return await file.text();
  }

  function caricaSessione(sess) {
    S.sess = sess;
    S.n = sess.tempo.n;
    S.dt = sess.tempo.dt;
    S.canali = new Map();
    for (const c of sess.canali) S.canali.set(c.id, { id: c.id, nome: c.nome, unita: c.unita, gruppo: c.gruppo, dati: daB64(c.b64) });
    if (sess.modello) {
      for (const b of sess.modello.blocchi) S.canali.set("m:" + b.id, { id: "m:" + b.id, nome: b.id, unita: unitaBlocco(sess.modello.def, b.id), gruppo: "modello", dati: daB64(b.b64) });
      S.parametri = Object.assign({}, sess.modello.scelte_parametri || {});
      if (!S.modello) S.modello = sess.modello.def;
    }
    S.t = new Float64Array(S.n);
    for (let i = 0; i < S.n; i++) S.t[i] = i * S.dt;
    S.i = 0;
    S.giro = null;
    S.ris = { orig: null, mod: null };
    DV.emit("sessione");
    DV.ricalcola();
  }
  function unitaBlocco(M, id) {
    const b = (M.blocchi || []).find((x) => x.id === id);
    return (b && b.unita) || "";
  }

  DV.canale = (id) => S.canali.get(id) || S.canali.get("m:" + id) || null;
  DV.valore = (id, i = S.i) => { const c = DV.canale(id); return c ? c.dati[i] : NaN; };

  // ---------------------------------------------------------------- ricalcolo del modello (originale e modificata)
  DV.ricalcola = function (quale = "entrambi") {
    if (!S.modello || !S.sess) { DV.emit("modello"); return; }
    const canali = {};
    for (const ing of S.modello.ingressi || []) { const c = DV.canale(ing.id); if (c) canali[ing.id] = c.dati; }
    for (const d of Object.values(DV.modello.infoParametri(S.modello))) { const c = d.canale && DV.canale(d.canale); if (c) canali[d.canale] = c.dati; }
    const esegui = (buf) => DV.modello.esegui(S.modello, canali, S.n, S.dt, S.struttura, buf, S.parametri);
    try {
      if ((quale === "entrambi" || quale === "orig") && S.binOrig) S.ris.orig = esegui(S.binOrig);
      if ((quale === "entrambi" || quale === "mod") && S.binMod) S.ris.mod = esegui(S.binMod);
      if (!S.binOrig && S.sess.modello) S.ris.orig = dalFile(S.sess.modello);
      if (!S.binMod) S.ris.mod = null;
    } catch (e) {
      DV.avviso("ricalcolo del modello: " + e.message, "errore");
      if (S.sess.modello) S.ris.orig = dalFile(S.sess.modello);
    }
    DV.emit("modello");
  };
  // risultati salvati nel file di sessione (senza .bin caricato)
  function dalFile(m) {
    const env = {};
    for (const [id, c] of S.canali) env[id.startsWith("m:") ? id.slice(2) : id] = c.dati;
    const criteri = {};
    for (const c of m.criteri) {
      const v = c.valore_id ? env[c.valore_id] : daB64(c.valore);
      const s = c.soglia_id ? env[c.soglia_id] : daB64(c.soglia);
      const sopra = c.confronto === ">" || c.confronto === ">=";
      const mg = new Float64Array(S.n);
      for (let i = 0; i < S.n; i++) mg[i] = sopra ? s[i] - v[i] : v[i] - s[i];
      criteri[c.id] = { valore: v, soglia: s, margine: mg, attivo: daB64(c.attivo) };
      env[c.id] = criteri[c.id].attivo;
    }
    const rami = {};
    for (const r of m.rami) rami[r.id] = daB64(r.b64);
    const uscite = {};
    for (const u of m.uscite) uscite[u.id] = daB64(u.b64);
    const usate = {};
    for (const u of m.tabelle_usate) usate[u.blocco] = { tabella: u.tabella, nomi: u.nomi || null, idx: u.idx ? daB64(u.idx) : null, x: u.x && daB64(u.x), y: u.y && daB64(u.y) };
    const parV = {};
    for (const [k, d] of Object.entries(DV.modello.infoParametri(m.def))) { const c = d.canale && DV.canale(d.canale); parV[k] = c ? c.dati : new Float64Array(S.n).fill(+d.valore); }
    return { env, criteri, rami, logica: daB64(m.logica), uscite, usate, ordine: m.blocchi.map((b) => b.id), parametri: m.scelte_parametri || {}, parV, dalFile: true };
  }

  // ---------------------------------------------------------------- riconoscimento dei file caricati
  async function caricaFile(file) {
    const nome = file.name;
    if (/\.(bin|ori|hex|mod|cal)$/i.test(nome) && !nome.endsWith(".json")) {
      const buf = new Uint8Array(await file.arrayBuffer());
      const c = await DV.aggiungiCalibrazione(nome.replace(/\.[^.]+$/, ""), buf, { file: nome });
      DV.avviso(`file centralina: ${c.nome} (${(buf.length / 1024).toFixed(0)} kB${c.variante ? ", variante " + c.variante : ""})`);
      DV.emit("calibrazione");
      DV.ricalcola();
      return;
    }
    const testo = await testoDa(file);
    let j;
    try { j = JSON.parse(testo); } catch (e) { throw new Error(`${nome}: non è JSON valido`); }
    classificaJSON(j, nome);
  }
  function classificaJSON(j, nome) {
    if (j.tipo === "sessione_dvtool") { caricaSessione(j); DV.avviso(`sessione: ${nome}`); }
    else if (j.tabelle) { S.struttura = j; DV.emit("struttura"); DV.avviso(`struttura: ${j.nome || nome} (${j.tabelle.length} tabelle)`); DV.emit("calibrazione"); DV.ricalcola(); }
    else if (j.blocchi || j.criteri) { S.modello = j; DV.avviso(`modello: ${j.nome || nome}`); DV.emit("sessione"); DV.ricalcola(); }
    else if (j.modifiche) { applicaPatch(j); }
    else throw new Error(`${nome}: tipo di file non riconosciuto`);
  }
  function applicaPatch(p) {
    if (!S.struttura || !S.binMod) throw new Error("per applicare una patch servono struttura e file .bin");
    if (p.variante && S.binMod.variante && p.variante !== S.binMod.variante) throw new Error(`la patch è per la variante ${p.variante}, B è ${S.binMod.variante}`);
    const per = new Map(S.struttura.tabelle.map((t) => [t.id, t]));
    let n = 0;
    for (const m of p.modifiche) if (m.tabella && per.has(m.tabella)) { DV.calib.scrivi(S.struttura, per.get(m.tabella), S.binMod, m.valori); n++; }
    DV.avviso(`patch applicata: ${n} tabelle`);
    DV.emit("calibrazione");
    DV.ricalcola("mod");
  }
  DV.caricaFile = async (files) => {
    // prima struttura/modello, poi bin, poi sessioni
    const arr = [...files];
    const peso = (f) => (/struttura|modello/i.test(f.name) ? 0 : /\.(bin|ori)$/i.test(f.name) ? 1 : 2);
    arr.sort((a, b) => peso(a) - peso(b));
    for (const f of arr) {
      try { await caricaFile(f); } catch (e) { DV.avviso(e.message, "errore"); }
    }
  };

  // modalità server (python -m dvtool visualizza): progetto.json nella cartella servita
  DV.caricaProgetto = async () => {
    try {
      const r = await fetch("progetto/progetto.json", { cache: "no-store" });
      if (!r.ok) return false;
      const P = await r.json();
      S.progetto = P;
      S.server = true;
      const prendi = async (p, tipo) => {
        const q = await fetch("progetto/" + p, { cache: "no-store" });
        if (!q.ok) throw new Error(`${p}: ${q.status}`);
        if (tipo === "bin") return new Uint8Array(await q.arrayBuffer());
        const blob = await q.blob();
        return JSON.parse(await testoDa(new File([blob], p)));
      };
      if (P.struttura) { S.struttura = await prendi(P.struttura); DV.emit("struttura"); }
      if (P.modello) S.modello = await prendi(P.modello);
      const elenco = P.calibrazioni || [P.originale && { nome: "originale", file: P.originale }, P.modificato && { nome: "modificato", file: P.modificato }].filter(Boolean);
      for (const c of elenco) await DV.aggiungiCalibrazione(c.nome, await prendi(c.file, "bin"), { file: c.file, variante: c.variante });
      if (P.riferimento && calDi(P.riferimento)) S.rif = P.riferimento;
      if (P.confronto && calDi(P.confronto)) S.cfr = P.confronto;
      DV.emit("calibrazione");
      DV.emit("progetto", P);
      if (P.sessioni && P.sessioni.length) await DV.apriSessione(P.sessioni[0]);
      return true;
    } catch (e) {
      DV.avviso("progetto: " + e.message, "errore");
      return false;
    }
  };
  DV.apriSessione = async (p) => {
    const q = await fetch("progetto/" + p, { cache: "no-store" });
    const blob = await q.blob();
    caricaSessione(JSON.parse(await testoDa(new File([blob], p))));
  };

  DV.vaiA = (i) => {
    S.i = Math.max(0, Math.min(S.n - 1, Math.round(i)));
    DV.emit("cursore", S.i);
  };
  DV.indiceDaTempo = (t) => Math.max(0, Math.min(S.n - 1, Math.round(t / S.dt)));

  DV.giri = () => (S.sess && S.sess.giri ? S.sess.giri.giri : []);
  DV.giroDi = (i) => {
    const t = i * S.dt + (S.sess.meta.t0_assoluto || 0);
    return DV.giri().find((g) => t >= g.t_inizio && t < g.t_fine) || null;
  };
  DV.tRel = (tAss) => tAss - (S.sess.meta.t0_assoluto || 0);

  // ---------------------------------------------------------------- curve (dal giro modello, distanze dal traguardo)
  const chiaveNomi = () => "dv-curve-" + Math.round((S.sess && S.sess.giri && S.sess.giri.lunghezza_giro) || 0);
  DV.nomiCurve = () => { try { return JSON.parse(localStorage.getItem(chiaveNomi()) || "{}"); } catch (e) { return {}; } };
  DV.salvaNomeCurva = (id, nome) => {
    const n = DV.nomiCurve();
    if (nome) n[id] = nome; else delete n[id];
    try { localStorage.setItem(chiaveNomi(), JSON.stringify(n)); } catch (e) { /* senza memoria locale */ }
    DV.emit("curve");
  };
  DV.curve = () => ((S.sess && S.sess.giri && S.sess.giri.curve) || []);
  DV.nomeCurva = (c) => { const n = DV.nomiCurve()[c.id] || c.nome; return n ? `${c.id} ${n}` : c.id; };
  // dove sono: curva (con fase) o rettilineo verso la prossima
  DV.curvaDi = (i = S.i) => {
    const s = DV.valore("s_giro", i);
    const C = DV.curve();
    if (!Number.isFinite(s) || !C.length) return null;
    const L = S.sess.giri.lunghezza_giro;
    for (const c of C) if (s >= c.inizio && s <= c.fine) return { c, s, fase: s < c.apice ? "ingresso" : "uscita", alApice: c.apice - s };
    const dopo = C.find((c) => c.inizio > s) || C[0];
    const fra = dopo.inizio > s ? dopo.inizio - s : dopo.inizio + L - s;
    return { c: null, s, prossima: dopo, fra };
  };
  // istanti di passaggio all'apice di ogni curva, giro per giro (per le etichette sui grafici nel tempo)
  let apiciCache = null;
  DV.on("sessione", () => (apiciCache = null));
  DV.apiciTempo = () => {
    if (apiciCache) return apiciCache;
    const out = [], sg = DV.canale("s_giro"), ng = DV.canale("n_giro"), C = DV.curve();
    if (!sg || !ng || !C.length) return (apiciCache = out);
    for (let i = 1; i < S.n; i++) {
      if (ng.dati[i] < 0 || ng.dati[i] !== ng.dati[i - 1]) continue;
      for (const c of C) if (sg.dati[i - 1] < c.apice && sg.dati[i] >= c.apice) out.push({ i, c });
    }
    return (apiciCache = out);
  };
  // livelli (potenza, TC, SCS, AW, freno motore…) all'istante i, come li usa la catena ricalcolata
  DV.testoLivelli = (i = S.i, r = null) => {
    r = r || S.ris.orig || S.ris.mod;
    if (!r || !r.parV || !S.modello) return "";
    const info = DV.modello.infoParametri(S.modello);
    return Object.entries(r.parV).map(([k, v]) => `${(info[k] && info[k].breve) || k} ${Number.isFinite(v[i]) ? v[i] : "–"}`).join(" · ");
  };
  DV.testoCurva = (i = S.i) => {
    const q = DV.curvaDi(i);
    if (!q) return "";
    if (q.c) return `${DV.nomeCurva(q.c)}${q.c.verso ? " " + q.c.verso : ""} · ${q.fase}${q.fase === "ingresso" ? `, apice fra ${q.alApice.toFixed(0)} m` : ""}`;
    return `rettilineo → ${DV.nomeCurva(q.prossima)} fra ${q.fra.toFixed(0)} m`;
  };

  DV.scarica = (nome, dati, tipo = "application/octet-stream") => {
    const url = URL.createObjectURL(new Blob([dati], { type: tipo }));
    const a = DV.el("a", { href: url, download: nome });
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
  };

  // colori dai token CSS
  DV.colore = (nome) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
})();
