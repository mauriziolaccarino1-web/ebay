/* Espressioni del modello (stesso sottoinsieme di Python usato da dvtool/model.py), valutate
   elemento per elemento su Float64Array. Esempio: "(v_post_c - v_rif) / max(v_rif, 15) * 100" */
(function () {
  const DV = (window.DV = window.DV || {});

  function tokenizza(s) {
    const re = /\s*(?:(\d+\.\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?|\d+(?:[eE][-+]?\d+)?)|([A-Za-z_]\w*)|(\*\*|<=|>=|==|!=|[-+*/%(),<>]))/y;
    const out = [];
    let i = 0;
    s = s.trim();
    while (i < s.length) {
      re.lastIndex = i;
      const m = re.exec(s);
      if (!m) throw new Error("espressione non valida vicino a: " + s.slice(i, i + 12));
      if (m[1] !== undefined) out.push({ t: "num", v: parseFloat(m[1]) });
      else if (m[2] !== undefined) out.push({ t: ["and", "or", "not", "if", "else", "True", "False"].includes(m[2]) ? m[2] : "id", v: m[2] });
      else out.push({ t: m[3] });
      i = re.lastIndex;
      while (i < s.length && s[i] === " ") i++;
    }
    return out;
  }

  // grammatica: ternario > or > and > not > confronto > somma > prodotto > unario > potenza > atomo
  function analizza(testo) {
    const tk = tokenizza(testo);
    let p = 0;
    const peek = () => tk[p] || { t: "fine" };
    const prendi = (t) => {
      if (peek().t !== t) throw new Error(`atteso '${t}' in '${testo}'`);
      return tk[p++];
    };
    function ternario() {
      const a = or_();
      if (peek().t === "if") {
        p++;
        const c = or_();
        prendi("else");
        const b = ternario();
        return { op: "if", c, a, b };
      }
      return a;
    }
    function or_() {
      let a = and_();
      while (peek().t === "or") { p++; a = { op: "or", a, b: and_() }; }
      return a;
    }
    function and_() {
      let a = not_();
      while (peek().t === "and") { p++; a = { op: "and", a, b: not_() }; }
      return a;
    }
    function not_() {
      if (peek().t === "not") { p++; return { op: "not", a: not_() }; }
      return confronto();
    }
    function confronto() {
      let a = somma();
      const ops = ["<", ">", "<=", ">=", "==", "!="];
      let catena = null;
      while (ops.includes(peek().t)) {
        const op = tk[p++].t;
        const b = somma();
        const c = { op, a, b };
        catena = catena ? { op: "and", a: catena, b: c } : c;
        a = b;
      }
      return catena || a;
    }
    function somma() {
      let a = prodotto();
      while (peek().t === "+" || peek().t === "-") { const op = tk[p++].t; a = { op, a, b: prodotto() }; }
      return a;
    }
    function prodotto() {
      let a = unario();
      while (["*", "/", "%"].includes(peek().t)) { const op = tk[p++].t; a = { op, a, b: unario() }; }
      return a;
    }
    function unario() {
      if (peek().t === "-") { p++; return { op: "neg", a: unario() }; }
      if (peek().t === "+") { p++; return unario(); }
      return potenza();
    }
    function potenza() {
      const a = atomo();
      if (peek().t === "**") { p++; return { op: "**", a, b: unario() }; }
      return a;
    }
    function atomo() {
      const x = peek();
      if (x.t === "num") { p++; return { op: "num", v: x.v }; }
      if (x.t === "True" || x.t === "False") { p++; return { op: "num", v: x.t === "True" ? 1 : 0 }; }
      if (x.t === "id") {
        p++;
        if (peek().t === "(") {
          p++;
          const args = [];
          if (peek().t !== ")") {
            args.push(ternario());
            while (peek().t === ",") { p++; args.push(ternario()); }
          }
          prendi(")");
          return { op: "call", f: x.v, args };
        }
        return { op: "id", v: x.v };
      }
      if (x.t === "(") { p++; const e = ternario(); prendi(")"); return e; }
      throw new Error(`simbolo inatteso '${x.t}' in '${testo}'`);
    }
    const albero = ternario();
    if (p < tk.length) throw new Error(`testo in più in '${testo}'`);
    return albero;
  }

  const FUNZ = new Set(["abs", "min", "max", "sqrt", "tan", "sin", "cos", "atan", "atan2", "radians", "degrees",
    "clip", "where", "sign", "exp", "log", "floor", "round"]);

  function nomi(albero, out = new Set()) {
    if (!albero) return out;
    if (albero.op === "id") out.add(albero.v);
    for (const k of ["a", "b", "c"]) if (albero[k]) nomi(albero[k], out);
    if (albero.args) albero.args.forEach((x) => nomi(x, out));
    return out;
  }

  // operazione elemento per elemento tra numeri e/o array
  function mappa(n, f, ...xs) {
    if (xs.every((x) => typeof x === "number")) return f(...xs);
    const out = new Float64Array(n);
    const acc = xs.map((x) => (typeof x === "number" ? () => x : (i) => x[i]));
    for (let i = 0; i < n; i++) {
      const v = [];
      for (let k = 0; k < acc.length; k++) v.push(acc[k](i));
      out[i] = f(...v);
    }
    return out;
  }
  // versioni veloci per due argomenti
  function bin(n, a, b, f) {
    if (typeof a === "number" && typeof b === "number") return f(a, b);
    const out = new Float64Array(n);
    if (typeof a === "number") for (let i = 0; i < n; i++) out[i] = f(a, b[i]);
    else if (typeof b === "number") for (let i = 0; i < n; i++) out[i] = f(a[i], b);
    else for (let i = 0; i < n; i++) out[i] = f(a[i], b[i]);
    return out;
  }

  function valutaAlbero(al, env, n) {
    const ev = (x) => valutaAlbero(x, env, n);
    switch (al.op) {
      case "num": return al.v;
      case "id":
        if (!(al.v in env)) throw new Error(`nome sconosciuto '${al.v}'`);
        return env[al.v];
      case "+": return bin(n, ev(al.a), ev(al.b), (a, b) => a + b);
      case "-": return bin(n, ev(al.a), ev(al.b), (a, b) => a - b);
      case "*": return bin(n, ev(al.a), ev(al.b), (a, b) => a * b);
      case "/": return bin(n, ev(al.a), ev(al.b), (a, b) => a / b);
      case "%": return bin(n, ev(al.a), ev(al.b), (a, b) => ((a % b) + b) % b);
      case "**": return bin(n, ev(al.a), ev(al.b), (a, b) => Math.pow(a, b));
      case "neg": return mappa(n, (a) => -a, ev(al.a));
      case "<": return bin(n, ev(al.a), ev(al.b), (a, b) => (a < b ? 1 : 0));
      case ">": return bin(n, ev(al.a), ev(al.b), (a, b) => (a > b ? 1 : 0));
      case "<=": return bin(n, ev(al.a), ev(al.b), (a, b) => (a <= b ? 1 : 0));
      case ">=": return bin(n, ev(al.a), ev(al.b), (a, b) => (a >= b ? 1 : 0));
      case "==": return bin(n, ev(al.a), ev(al.b), (a, b) => (a === b ? 1 : 0));
      case "!=": return bin(n, ev(al.a), ev(al.b), (a, b) => (a !== b ? 1 : 0));
      case "and": return bin(n, ev(al.a), ev(al.b), (a, b) => (a && b ? 1 : 0));
      case "or": return bin(n, ev(al.a), ev(al.b), (a, b) => (a || b ? 1 : 0));
      case "not": return mappa(n, (a) => (a ? 0 : 1), ev(al.a));
      case "if": return mappa(n, (c, a, b) => (c ? a : b), ev(al.c), ev(al.a), ev(al.b));
      case "call": {
        const f = al.f;
        if (!FUNZ.has(f)) throw new Error(`funzione non ammessa: ${f}`);
        const a = al.args.map(ev);
        const M = Math;
        const tab = {
          abs: M.abs, sqrt: M.sqrt, tan: M.tan, sin: M.sin, cos: M.cos, atan: M.atan, exp: M.exp, log: M.log,
          floor: M.floor, round: M.round, sign: M.sign, atan2: M.atan2,
          radians: (x) => (x * M.PI) / 180, degrees: (x) => (x * 180) / M.PI,
          min: (...v) => M.min(...v), max: (...v) => M.max(...v),
          clip: (x, lo, hi) => M.min(M.max(x, lo), hi), where: (c, x, y) => (c ? x : y),
        };
        if (a.length === 2) return bin(n, a[0], a[1], tab[f]);
        return mappa(n, tab[f], ...a);
      }
    }
    throw new Error("nodo sconosciuto " + al.op);
  }

  const cache = new Map();
  DV.espr = {
    analizza: (s) => {
      if (!cache.has(s)) cache.set(s, analizza(String(s)));
      return cache.get(s);
    },
    nomi: (s) => [...nomi(DV.espr.analizza(s))].filter((x) => !FUNZ.has(x)),
    valuta: (s, env, n) => valutaAlbero(DV.espr.analizza(s), env, n),
    // condizione "C1 and C2 and not C3" -> termini al primo livello di AND
    termini: (s) => {
      const out = [];
      const giu = (al) => {
        if (al.op === "and") { giu(al.a); giu(al.b); } else out.push(al);
      };
      giu(DV.espr.analizza(s));
      return out.map((al) => ({ albero: al, testo: testoDi(al), id: al.op === "id" ? al.v : al.op === "not" && al.a.op === "id" ? al.a.v : null, negato: al.op === "not" }));
    },
    termini_or: (s) => {
      const out = [];
      const giu = (al) => { if (al.op === "or") { giu(al.a); giu(al.b); } else out.push(al); };
      giu(DV.espr.analizza(s));
      return out.map(testoDi);
    },
    valutaAlbero,
  };
  function testoDi(al) {
    switch (al.op) {
      case "num": return String(al.v);
      case "id": return al.v;
      case "not": return "not " + testoDi(al.a);
      case "neg": return "-" + testoDi(al.a);
      case "call": return `${al.f}(${al.args.map(testoDi).join(", ")})`;
      case "if": return `${testoDi(al.a)} if ${testoDi(al.c)} else ${testoDi(al.b)}`;
      default: return `(${testoDi(al.a)} ${al.op} ${testoDi(al.b)})`;
    }
  }
})();
