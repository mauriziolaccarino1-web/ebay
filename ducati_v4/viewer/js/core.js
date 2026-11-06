/* Stato, caricamento dei file e utilità comuni del visualizzatore */
(function () {
  const DV = (window.DV = window.DV || {});
  const S = (DV.stato = {
    sess: null, struttura: null, modello: null, binOrig: null, binMod: null, nomeOrig: "", nomeMod: "",
    canali: new Map(), n: 0, dt: 0.01, i: 0, giro: null, parametri: {},
    ris: { orig: null, mod: null }, progetto: null, server: false,
  });
  DV.viste = {};
  DV.registraVista = (nome, oggetto) => (DV.viste[nome] = oggetto);
  const ascolti = {};
  DV.on = (ev, f) => (ascolti[ev] = ascolti[ev] || []).push(f);
  DV.emit = (ev, x) => (ascolti[ev] || []).forEach((f) => { try { f(x); } catch (e) { console.error(e); DV.avviso(String(e.message || e), "errore"); } });

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
      S.parametri = Object.assign({}, sess.modello.parametri || sess.modello.def.parametri || {});
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
    const esegui = (buf) => DV.modello.esegui(S.modello, canali, S.n, S.dt, S.struttura, buf, S.parametri);
    try {
      if ((quale === "entrambi" || quale === "orig") && S.binOrig) S.ris.orig = esegui(S.binOrig);
      if ((quale === "entrambi" || quale === "mod") && S.binMod) S.ris.mod = esegui(S.binMod);
      if (!S.binOrig && S.sess.modello) S.ris.orig = dalFile(S.sess.modello);
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
    for (const u of m.tabelle_usate) usate[u.blocco] = { tabella: u.tabella, x: u.x && daB64(u.x), y: u.y && daB64(u.y) };
    return { env, criteri, rami, logica: daB64(m.logica), uscite, usate, ordine: m.blocchi.map((b) => b.id), parametri: m.parametri, dalFile: true };
  }

  // ---------------------------------------------------------------- riconoscimento dei file caricati
  async function caricaFile(file) {
    const nome = file.name;
    if (/\.(bin|ori|hex|mod|cal)$/i.test(nome) && !nome.endsWith(".json")) {
      const buf = new Uint8Array(await file.arrayBuffer());
      if (!S.binOrig || /orig/i.test(nome)) { S.binOrig = buf; S.nomeOrig = nome; if (!S.binMod) { S.binMod = buf.slice(); S.nomeMod = nome + " (copia di lavoro)"; } }
      else { S.binMod = buf; S.nomeMod = nome; }
      DV.avviso(`file centralina: ${nome} (${(buf.length / 1024).toFixed(0)} kB)`);
      DV.emit("calibrazione");
      return;
    }
    const testo = await testoDa(file);
    let j;
    try { j = JSON.parse(testo); } catch (e) { throw new Error(`${nome}: non è JSON valido`); }
    classificaJSON(j, nome);
  }
  function classificaJSON(j, nome) {
    if (j.tipo === "sessione_dvtool") { caricaSessione(j); DV.avviso(`sessione: ${nome}`); }
    else if (j.tabelle) { S.struttura = j; DV.avviso(`struttura: ${j.nome || nome} (${j.tabelle.length} tabelle)`); DV.emit("calibrazione"); DV.ricalcola(); }
    else if (j.blocchi || j.criteri) { S.modello = j; DV.avviso(`modello: ${j.nome || nome}`); DV.emit("sessione"); DV.ricalcola(); }
    else if (j.modifiche) { applicaPatch(j); }
    else throw new Error(`${nome}: tipo di file non riconosciuto`);
  }
  function applicaPatch(p) {
    if (!S.struttura || !S.binMod) throw new Error("per applicare una patch servono struttura e file .bin");
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
      if (P.struttura) S.struttura = await prendi(P.struttura);
      if (P.modello) S.modello = await prendi(P.modello);
      if (P.originale) { S.binOrig = await prendi(P.originale, "bin"); S.nomeOrig = P.originale; }
      if (P.modificato) { S.binMod = await prendi(P.modificato, "bin"); S.nomeMod = P.modificato; }
      else if (S.binOrig) { S.binMod = S.binOrig.slice(); S.nomeMod = "copia di lavoro"; }
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
