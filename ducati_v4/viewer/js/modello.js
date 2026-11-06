/* Motore della catena di controllo nel browser (stessa semantica di dvtool/model.py).
   Serve a ricalcolare i criteri subito dopo una modifica alle tabelle. */
(function () {
  const DV = (window.DV = window.DV || {});
  const E = () => DV.espr;

  function dipendenze(b) {
    const d = new Set(b.ingressi || []);
    for (const k of ["x", "y", "a", "b", "ingresso", "se_vero", "se_falso"]) {
      const v = b[k];
      if (typeof v === "string") E().nomi(v).forEach((x) => d.add(x));
    }
    for (const k of ["espressione", "condizione"]) if (b[k]) E().nomi(b[k]).forEach((x) => d.add(x));
    d.delete("t"); d.delete("dt");
    return d;
  }

  function ordina(M) {
    const noti = new Set([...(M.ingressi || []).map((i) => i.id), ...Object.keys(M.parametri || {})]);
    const rimasti = new Map((M.blocchi || []).map((b) => [b.id, b]));
    const ordine = [];
    while (rimasti.size) {
      let prog = false;
      for (const [id, b] of [...rimasti]) {
        if ([...dipendenze(b)].every((x) => noti.has(x))) { ordine.push(b); noti.add(id); rimasti.delete(id); prog = true; }
      }
      if (!prog) throw new Error("dipendenze irrisolte: " + [...rimasti.keys()].join(", "));
    }
    return ordine;
  }

  const pieno = (n, v) => new Float64Array(n).fill(v);
  const comeArray = (n, v) => (typeof v === "number" ? pieno(n, v) : v);

  function isteresi(x, on, off) {
    const y = new Float64Array(x.length);
    let st = false;
    for (let i = 0; i < x.length; i++) {
      if (!st && x[i] >= on) st = true;
      else if (st && x[i] <= off) st = false;
      y[i] = st ? 1 : 0;
    }
    return y;
  }

  function nomeTabella(nome, par) {
    return nome.replace(/\{(\w+)\}/g, (_, k) => {
      const v = par[k];
      return Number.isInteger(v) ? String(v) : String(v);
    });
  }

  /* canali: {id: Float32Array|Float64Array}; S struttura; buf Uint8Array; par parametri extra */
  function esegui(M, canali, n, dt, S, buf, parExtra) {
    const par = Object.assign({}, M.parametri || {}, parExtra || {});
    const env = { dt };
    const t = new Float64Array(n);
    for (let i = 0; i < n; i++) t[i] = i * dt;
    env.t = t;
    for (const [k, v] of Object.entries(par)) env[k] = pieno(n, +v);
    for (const ing of M.ingressi || []) {
      const c = canali[ing.id];
      if (!c) throw new Error(`ingresso '${ing.id}' assente nella sessione`);
      env[ing.id] = Float64Array.from(c);
    }
    const tab = new Map(((S && S.tabelle) || []).map((x) => [x.id, x]));
    const usate = {};
    const cacheTab = new Map();
    const leggiTab = (nome) => {
      if (!cacheTab.has(nome)) {
        if (!tab.has(nome) || !buf) throw new Error(`tabella '${nome}' non disponibile (serve struttura + .bin)`);
        cacheTab.set(nome, DV.calib.leggi(S, tab.get(nome), buf));
      }
      return cacheTab.get(nome);
    };
    const ordine = ordina(M);
    for (const b of ordine) {
      const ins = (b.ingressi || []).map((i) => env[i]);
      const arg = (k) => {
        const v = b[k];
        if (typeof v === "number") return pieno(n, v);
        if (v in env) return env[v];
        return comeArray(n, E().valuta(v, env, n));
      };
      let out;
      switch (b.tipo) {
        case "costante": out = pieno(n, +b.valore); break;
        case "abs": out = ins[0].map(Math.abs); break;
        case "neg": out = ins[0].map((v) => -v); break;
        case "min": out = ins[0].map((v, i) => Math.min(...ins.map((a) => a[i]))); break;
        case "max": out = ins[0].map((v, i) => Math.max(...ins.map((a) => a[i]))); break;
        case "somma": out = ins[0].map((v, i) => ins.reduce((s, a) => s + a[i], 0)); break;
        case "prodotto": out = ins[0].map((v, i) => ins.reduce((s, a) => s * a[i], 1)); break;
        case "espressione": out = comeArray(n, E().valuta(b.espressione, env, n)); break;
        case "passabasso": {
          const alfa = b.alfa ?? dt / (+b.tau_s + dt);
          const x = ins[0];
          out = new Float64Array(n);
          let acc = x[0];
          for (let i = 0; i < n; i++) { acc += alfa * (x[i] - acc); out[i] = acc; }
          break;
        }
        case "derivata": {
          const x = ins[0];
          out = new Float64Array(n);
          for (let i = 0; i < n; i++) {
            if (i === 0) out[i] = (x[1] - x[0]) / dt;
            else if (i === n - 1) out[i] = (x[n - 1] - x[n - 2]) / dt;
            else out[i] = (x[i + 1] - x[i - 1]) / (2 * dt);
          }
          break;
        }
        case "rampa": {
          const x = ins[0], su = b.su_per_s * dt, giu = b.giu_per_s * dt;
          out = new Float64Array(n);
          let acc = x[0];
          for (let i = 0; i < n; i++) { const d = x[i] - acc; acc += d > 0 ? Math.min(d, su) : Math.max(d, -giu); out[i] = acc; }
          break;
        }
        case "satura": out = ins[0].map((v) => Math.min(Math.max(v, b.min ?? -Infinity), b.max ?? Infinity)); break;
        case "tabella": {
          const nome = nomeTabella(b.tabella, par);
          const T = leggiTab(nome);
          const def = tab.get(nome);
          const xv = arg("x");
          out = new Float64Array(n);
          if (def.tipo === "curva") {
            const ax = T.x.valori, z = T.z[0];
            for (let i = 0; i < n; i++) out[i] = DV.calib.lookup1(ax, z, xv[i]);
            usate[b.id] = { tabella: nome, x: xv };
          } else if (def.tipo === "valore") {
            out.fill(T.z[0][0]);
            usate[b.id] = { tabella: nome };
          } else {
            const yv = arg("y");
            const ax = T.x.valori, ay = T.y.valori, z = T.z;
            for (let i = 0; i < n; i++) out[i] = DV.calib.lookup2(ax, ay, z, xv[i], yv[i]);
            usate[b.id] = { tabella: nome, x: xv, y: yv };
          }
          break;
        }
        case "selettore": {
          const c = comeArray(n, E().valuta(b.condizione, env, n)), a = arg("se_vero"), f = arg("se_falso");
          out = new Float64Array(n);
          for (let i = 0; i < n; i++) out[i] = c[i] > 0 ? a[i] : f[i];
          break;
        }
        case "confronto": {
          const a = arg("a"), c = arg("b");
          const op = { ">": (p, q) => p > q, ">=": (p, q) => p >= q, "<": (p, q) => p < q, "<=": (p, q) => p <= q }[b.op];
          out = new Float64Array(n);
          for (let i = 0; i < n; i++) out[i] = op(a[i], c[i]) ? 1 : 0;
          break;
        }
        case "isteresi": out = isteresi(arg("ingresso"), +b.on, +b.off); break;
        case "conferma": {
          const x = arg("ingresso");
          const non = Math.max(1, Math.round((b.t_on_s || 0) / dt)), noff = Math.max(1, Math.round((b.t_off_s || 0) / dt));
          out = new Float64Array(n);
          let st = false, cnt = 0;
          for (let i = 0; i < n; i++) {
            const v = x[i] > 0.5;
            if (v !== st) { cnt++; if ((v && cnt >= non) || (!v && cnt >= noff)) { st = v; cnt = 0; } } else cnt = 0;
            out[i] = st ? 1 : 0;
          }
          break;
        }
        case "ritardo": {
          const k = Math.round(b.t_s / dt), x = arg("ingresso");
          out = new Float64Array(n);
          for (let i = 0; i < n; i++) out[i] = x[Math.max(0, i - k)];
          break;
        }
        default: throw new Error("tipo di blocco sconosciuto: " + b.tipo);
      }
      env[b.id] = out instanceof Float64Array ? out : Float64Array.from(out);
    }
    const criteri = {};
    for (const c of M.criteri || []) {
      const v = c.valore in env ? env[c.valore] : comeArray(n, E().valuta(c.valore, env, n));
      const s = typeof c.soglia === "number" ? pieno(n, c.soglia) : c.soglia in env ? env[c.soglia] : comeArray(n, E().valuta(c.soglia, env, n));
      const op = c.confronto || ">";
      const sopra = op === ">" || op === ">=";
      const m = new Float64Array(n);
      for (let i = 0; i < n; i++) m[i] = sopra ? s[i] - v[i] : v[i] - s[i];
      let att;
      if (c.isteresi) {
        const nm = m.map((x) => -x);
        att = isteresi(nm, op === ">" || op === "<" ? 0 : -1e-12, -c.isteresi);
      } else {
        att = new Float64Array(n);
        for (let i = 0; i < n; i++) att[i] = (op === ">" ? v[i] > s[i] : op === ">=" ? v[i] >= s[i] : op === "<" ? v[i] < s[i] : v[i] <= s[i]) ? 1 : 0;
      }
      criteri[c.id] = { valore: v, soglia: s, margine: m, attivo: att };
      env[c.id] = att;
    }
    const rami = {};
    for (const r of M.rami || []) { rami[r.id] = comeArray(n, E().valuta(r.condizione, env, n)); env[r.id] = rami[r.id]; }
    const logica = M.logica ? comeArray(n, E().valuta(M.logica, env, n)) : pieno(n, 0);
    env.logica = logica;
    const uscite = {};
    for (const u of M.uscite || []) {
      const v = env[u.blocco];
      let o = v;
      if (u.attiva_se) {
        const c = comeArray(n, E().valuta(u.attiva_se, env, n));
        o = new Float64Array(n);
        for (let i = 0; i < n; i++) o[i] = c[i] > 0 ? v[i] : u.valore_riposo || 0;
      }
      uscite[u.id] = o;
      env[u.id] = o;
    }
    return { env, criteri, rami, logica, uscite, usate, ordine: ordine.map((b) => b.id), parametri: par };
  }

  DV.modello = { esegui, ordina, dipendenze, nomeTabella };
})();
