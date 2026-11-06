// Confronta il motore JS (viewer/js) con i risultati Python salvati nella sessione demo.
const fs = require("fs"), zlib = require("zlib"), path = require("path"), vm = require("vm");
const dir = process.argv[2];
const ctx = { window: {}, Math, Float64Array, Float32Array, Uint8Array, DataView, Uint32Array, Map, Set, Array, Object, Number, String, JSON, console, parseInt, parseFloat, isFinite, Infinity, NaN };
ctx.window = ctx; vm.createContext(ctx);
for (const f of ["espr.js", "calib.js", "modello.js"]) vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "viewer", "js", f), "utf8"), ctx);
const DV = ctx.DV;
const sess = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(dir, "sessione_demo.json.gz"))).toString());
const S = JSON.parse(fs.readFileSync(path.join(dir, "struttura_demo.json")));
const M = JSON.parse(fs.readFileSync(path.join(dir, "modello_demo.json")));
const buf = new Uint8Array(fs.readFileSync(path.join(dir, "demo_originale.bin")));
const b64 = (s) => new Float32Array(new Uint8Array(Buffer.from(s, "base64")).buffer);
const canali = {}; for (const c of sess.canali) canali[c.id] = b64(c.b64);
const r = DV.modello.esegui(M, canali, sess.tempo.n, sess.tempo.dt, S, buf, {});
let peggio = 0, cattivi = 0;
for (const b of sess.modello.blocchi) {
  const py = b64(b.b64), js = r.env[b.id];
  let mx = 0, sc = 1e-6;
  for (let i = 0; i < py.length; i++) { mx = Math.max(mx, Math.abs(py[i] - js[i])); sc = Math.max(sc, Math.abs(py[i])); }
  const rel = mx / sc; peggio = Math.max(peggio, rel);
  if (rel > 1e-4) { cattivi++; console.log("DIFFERENZA", b.id, mx, rel); }
}
let diffL = 0; const pl = b64(sess.modello.logica);
for (let i = 0; i < pl.length; i++) if ((pl[i] > 0.5) !== (r.logica[i] > 0.5)) diffL++;
const cs = DV.calib.verifica(S, buf);
console.log(JSON.stringify({ blocchi: sess.modello.blocchi.length, peggior_scarto_relativo: peggio, blocchi_diversi: cattivi, campioni_logica_diversi: diffL, checksum_js: cs }));
process.exit(cattivi || diffL > 5 || !cs.every((x) => x.ok) ? 1 : 0);
