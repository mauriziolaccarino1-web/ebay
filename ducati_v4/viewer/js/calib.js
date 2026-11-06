/* Lettura/scrittura delle tabelle nel file della centralina e checksum (stessa logica di dvtool/calib.py) */
(function () {
  const DV = (window.DV = window.DV || {});
  const TIPI = {
    u8: [1, "getUint8", "setUint8", 0, 255], s8: [1, "getInt8", "setInt8", -128, 127],
    u16: [2, "getUint16", "setUint16", 0, 65535], s16: [2, "getInt16", "setInt16", -32768, 32767],
    u32: [4, "getUint32", "setUint32", 0, 4294967295], s32: [4, "getInt32", "setInt32", -2147483648, 2147483647],
    f32: [4, "getFloat32", "setFloat32", null, null],
  };
  const int = (x) => (typeof x === "string" ? parseInt(x, x.startsWith("0x") || x.startsWith("0X") ? 16 : 10) : x | 0);
  const le = (e) => e === undefined || e === "le" || e === "little";

  function base(S) { return int((S.file && S.file.base) || 0); }

  function dim(tab) {
    const t = tab.tipo || "mappa";
    if (t === "valore") return [1, 1];
    if (t === "curva") return [1, tab.colonne || tab.n || 1];
    return [tab.righe, tab.colonne];
  }

  function asse(S, spec, buf, nAtteso) {
    if (spec === undefined || spec === null) return { valori: Array.from({ length: nAtteso }, (_, i) => i), unita: "", nome: "indice" };
    let nome = "";
    if (typeof spec === "string") {
      nome = spec;
      spec = (S.assi || {})[spec];
      if (!spec) throw new Error("asse non definito: " + nome);
    }
    if (spec.valori) return { valori: spec.valori.slice(), unita: spec.unita || "", nome: spec.nome || nome, segnale: spec.segnale, spec };
    const [w, get] = TIPI[spec.dtype || "u16"];
    const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
    const off = int(spec.indirizzo) - base(S);
    const n = spec.n || nAtteso;
    const v = [];
    for (let i = 0; i < n; i++) v.push(dv[get](off + i * w, le(spec.endian)) * (spec.scala ?? 1) + (spec.offset ?? 0));
    return { valori: v, unita: spec.unita || "", nome: spec.nome || nome, segnale: spec.segnale, indirizzo: int(spec.indirizzo), spec };
  }

  function leggi(S, tab, buf) {
    const [r, c] = dim(tab);
    const [w, get] = TIPI[tab.dtype || "u16"];
    const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
    const off = int(tab.indirizzo) - base(S);
    const z = [];
    for (let i = 0; i < r; i++) z.push(new Array(c));
    for (let k = 0; k < r * c; k++) {
      const raw = dv[get](off + k * w, le(tab.endian));
      const [i, j] = tab.ordine === "colonne" ? [k % r, Math.floor(k / r)] : [Math.floor(k / c), k % c];
      z[i][j] = raw * (tab.scala ?? 1) + (tab.offset ?? 0);
    }
    const x = tab.tipo !== "valore" ? asse(S, tab.asse_x, buf, c) : null;
    const y = (tab.tipo || "mappa") === "mappa" ? asse(S, tab.asse_y, buf, r) : null;
    return { z, x, y, r, c };
  }

  // scrive valori fisici; ritorna gli avvisi
  function scrivi(S, tab, buf, z) {
    const [r, c] = dim(tab);
    const [w, , set, lo, hi] = TIPI[tab.dtype || "u16"];
    const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
    const off = int(tab.indirizzo) - base(S);
    let sat = 0;
    for (let k = 0; k < r * c; k++) {
      const [i, j] = tab.ordine === "colonne" ? [k % r, Math.floor(k / r)] : [Math.floor(k / c), k % c];
      let raw = (z[i][j] - (tab.offset ?? 0)) / (tab.scala ?? 1);
      if (lo !== null) {
        raw = Math.round(raw);
        if (raw < lo || raw > hi) { sat++; raw = Math.min(Math.max(raw, lo), hi); }
      }
      dv[set](off + k * w, raw, le(tab.endian));
    }
    return sat ? [`${tab.id}: ${sat} celle saturate al campo del tipo ${tab.dtype}`] : [];
  }

  // valore realmente memorizzabile (arrotondato al passo della scala)
  function quantizza(tab, v) {
    const [, , , lo, hi] = TIPI[tab.dtype || "u16"];
    if (lo === null) return Math.fround(v);
    let raw = Math.round((v - (tab.offset ?? 0)) / (tab.scala ?? 1));
    raw = Math.min(Math.max(raw, lo), hi);
    return raw * (tab.scala ?? 1) + (tab.offset ?? 0);
  }

  // ---------------------------------------------------------------- checksum
  function crc16(data, poly, init, rifl) {
    let crc = init;
    if (rifl) {
      let rp = 0;
      for (let i = 0; i < 16; i++) if (poly & (1 << i)) rp |= 1 << (15 - i);
      for (const b of data) { crc ^= b; for (let k = 0; k < 8; k++) crc = crc & 1 ? (crc >>> 1) ^ rp : crc >>> 1; }
    } else {
      for (const b of data) { crc ^= b << 8; for (let k = 0; k < 8; k++) crc = crc & 0x8000 ? ((crc << 1) ^ poly) & 0xffff : (crc << 1) & 0xffff; }
    }
    return crc & 0xffff;
  }
  let T32 = null;
  function crc32(data) {
    if (!T32) {
      T32 = new Uint32Array(256);
      for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; T32[n] = c >>> 0; }
    }
    let c = 0xffffffff;
    for (const b of data) c = T32[(c ^ b) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }
  function crc32mpeg2(data) {
    let c = 0xffffffff;
    for (const b of data) { c ^= b << 24; for (let k = 0; k < 8; k++) c = c & 0x80000000 ? ((c << 1) ^ 0x04c11db7) >>> 0 : (c << 1) >>> 0; }
    return c >>> 0;
  }
  function calcola(alg, d) {
    const dv = new DataView(d.buffer, d.byteOffset, d.byteLength);
    let s = 0;
    switch (alg) {
      case "sum8": for (const b of d) s = (s + b) & 0xff; return [s, 8];
      case "sum8_32": for (const b of d) s = (s + b) >>> 0; return [s, 32];
      case "sum16_le": case "sum16_be": {
        const L = alg.endsWith("le");
        for (let i = 0; i + 1 < d.length; i += 2) s = (s + dv.getUint16(i, L)) & 0xffff;
        if (d.length % 2) s = (s + (L ? d[d.length - 1] : d[d.length - 1] << 8)) & 0xffff;
        return [s, 16];
      }
      case "sum32_le": case "sum32_be": {
        const L = alg.endsWith("le");
        let i = 0;
        for (; i + 3 < d.length; i += 4) s = (s + dv.getUint32(i, L)) >>> 0;
        if (i < d.length) {
          const t = new Uint8Array(4); t.set(d.subarray(i));
          s = (s + new DataView(t.buffer).getUint32(0, L)) >>> 0;
        }
        return [s, 32];
      }
      case "crc16_ccitt": return [crc16(d, 0x1021, 0xffff, false), 16];
      case "crc16_xmodem": return [crc16(d, 0x1021, 0x0000, false), 16];
      case "crc16_modbus": return [crc16(d, 0x8005, 0xffff, true), 16];
      case "crc32": return [crc32(d), 32];
      case "crc32_mpeg2": return [crc32mpeg2(d), 32];
    }
    throw new Error("checksum sconosciuto: " + alg);
  }
  const FMT = { u8: [1, "getUint8", "setUint8", true], u16le: [2, "getUint16", "setUint16", true], u16be: [2, "getUint16", "setUint16", false], u32le: [4, "getUint32", "setUint32", true], u32be: [4, "getUint32", "setUint32", false] };
  function complementa(v, bit, tipo) {
    const m = bit === 32 ? 0xffffffff : (1 << bit) - 1;
    if (tipo === "uno") return (~v & m) >>> 0;
    if (tipo === "due") return (-v & m) >>> 0;
    return v >>> 0;
  }
  function dati(buf, spec, b) {
    const pos = int(spec.posizione) - b;
    const larg = FMT[spec.formato || "u32le"][0];
    const escl = (spec.escludi || []).map(([a, c]) => [int(a) - b, int(c) - b]);
    escl.push([pos, pos + larg]);
    escl.sort((p, q) => p[0] - q[0]);
    const pezzi = [];
    for (const [a0, b0] of spec.regioni) {
      const a = int(a0) - b, e = int(b0) - b;
      let cur = a;
      for (const [ea, eb] of escl) {
        if (eb <= cur || ea >= e) continue;
        pezzi.push(buf.subarray(cur, Math.max(cur, ea)));
        cur = Math.max(cur, eb);
      }
      pezzi.push(buf.subarray(cur, e));
    }
    const tot = pezzi.reduce((s, p) => s + p.length, 0);
    const out = new Uint8Array(tot);
    let o = 0;
    for (const p of pezzi) { out.set(p, o); o += p.length; }
    return out;
  }
  function verifica(S, buf) {
    const b = base(S);
    return (S.checksum || []).map((spec) => {
      const [v, bit] = calcola(spec.algoritmo, dati(buf, spec, b));
      const [larg, get] = FMT[spec.formato || "u32le"];
      const atteso = complementa(v, bit, spec.complemento || "nessuno") & (larg === 4 ? 0xffffffff : (1 << (8 * larg)) - 1);
      const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
      const salvato = dv[get](int(spec.posizione) - b, FMT[spec.formato || "u32le"][3]);
      return { id: spec.id, salvato: salvato >>> 0, calcolato: atteso >>> 0, ok: salvato >>> 0 === atteso >>> 0 };
    });
  }
  function correggi(S, buf) {
    const b = base(S);
    const ris = verifica(S, buf);
    (S.checksum || []).forEach((spec, i) => {
      const [, , set, L] = FMT[spec.formato || "u32le"];
      new DataView(buf.buffer, buf.byteOffset, buf.byteLength)[set](int(spec.posizione) - b, ris[i].calcolato, L);
    });
    return verifica(S, buf);
  }

  // ---------------------------------------------------------------- interpolazione come in centralina (saturata)
  function cerca(ax, x) {
    const n = ax.length;
    if (n < 2) return [0, 0];
    if (x <= ax[0]) return [0, 0];
    if (x >= ax[n - 1]) return [n - 2, 1];
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (ax[m] <= x) lo = m; else hi = m; }
    const d = ax[lo + 1] - ax[lo];
    return [lo, d ? (x - ax[lo]) / d : 0];
  }
  function lookup1(ax, z, x) {
    if (ax.length < 2) return z[0];
    const [i, f] = cerca(ax, x);
    return z[i] * (1 - f) + z[i + 1] * f;
  }
  function lookup2(ax, ay, z, x, y) {
    const [i, fx] = cerca(ax, x);
    const [j, fy] = cerca(ay, y);
    const i1 = Math.min(i + 1, ax.length - 1), j1 = Math.min(j + 1, ay.length - 1);
    return z[j][i] * (1 - fx) * (1 - fy) + z[j][i1] * fx * (1 - fy) + z[j1][i] * (1 - fx) * fy + z[j1][i1] * fx * fy;
  }
  // posizione frazionaria nella griglia (per disegnare il punto di lavoro)
  function posizione(ax, x) {
    const [i, f] = cerca(ax, x);
    return ax.length < 2 ? 0 : i + f;
  }

  DV.calib = { leggi, scrivi, dim, quantizza, verifica, correggi, calcola, lookup1, lookup2, posizione, base, int, TIPI };
})();
