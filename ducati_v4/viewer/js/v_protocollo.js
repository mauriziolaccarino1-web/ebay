/* Scheda Protocollo CAN: è davvero il protocollo della V4S? messaggi, integrità (contatore + CRC-8), controlli fisici */
(function () {
  const DV = window.DV;
  const S = DV.stato;
  const { el } = DV;
  const radice = document.getElementById("v-protocollo");
  const tabella = (cols, righe) => el("div", { class: "scorre" }, el("table", { class: "dati" },
    el("thead", {}, el("tr", {}, cols.map(([k, n, num]) => el("th", { class: num ? "n" : "" }, n)))),
    el("tbody", {}, righe.map((r) => el("tr", {}, cols.map(([k, , num, f]) => el("td", { class: num ? "n" : "" }, f ? f(r[k], r) : r[k] === undefined || r[k] === null ? "" : String(r[k]))))))));

  const vista = {
    disegna() {
      radice.innerHTML = "";
      const P = S.sess && S.sess.protocollo;
      if (!P) { radice.append(el("div", { class: "pannello" }, el("p", { class: "nota" }, "Nessuna verifica del protocollo nella sessione."))); return; }
      const sorg = (S.sess.meta && S.sess.meta.sorgenti) || {};
      radice.append(el("div", { class: "pannello" }, el("h3", {}, "Esito"), el("p", {}, P.giudizio),
        el("div", { class: "nota" }, `DBC: ${S.sess.meta.dbc || "–"} · moto: ${S.sess.meta.moto || "–"} · log: ${S.sess.meta.origine}`),
        el("ul", { class: "nota" }, (S.sess.meta.note || []).map((n) => el("li", {}, n)))));
      const box = el("div", { class: "righe", style: { marginTop: "12px" } });
      radice.append(box);
      if (Object.keys(sorg).length) box.append(el("div", { class: "pannello" }, el("h3", {}, "Da dove arriva ogni canale"),
        tabella([["nome", "canale"], ["id_hex", "ID"], ["segnale", "segnale DBC"], ["stato", "verificato in pista"]],
          Object.entries(sorg).map(([k, v]) => Object.assign({ nome: k }, v)))));
      if (P.integrita && P.integrita.length) box.append(el("div", { class: "pannello" }, el("h3", {}, "Integrità dei frame (contatore B6[3:0] + CRC-8 SAE J1850 in B7)"),
        el("div", { class: "nota" }, "Sulla Streetfighter V4 2023 ogni frame della centralina (tranne 0x360) porta contatore e CRC-8 J1850 corretti al 100%. Trovare lo stesso schema qui è la prova più forte che il protocollo è lo stesso. Frame persi = salti del contatore (il registratore non ha tenuto il ritmo)."),
        tabella([["id_hex", "ID"], ["frame", "frame", 1], ["crc_j1850_%", "CRC ok %", 1], ["contatore_ok_%", "contatore ok %", 1], ["frame_persi_stimati", "persi", 1], ["buchi", "buchi", 1], ["protetto", "schema V4S", 0, (v) => (v ? "sì" : "")]], P.integrita)));
      box.append(el("div", { class: "pannello" }, el("h3", {}, "Messaggi attesi dal DBC"),
        tabella([["id_hex", "ID"], ["nome", "nome"], ["presente", "presente", 0, (v) => (v ? "sì" : "NO")], ["hz", "Hz", 1], ["periodo_ms", "periodo ms", 1, (v) => (v ? v.toFixed(1) : "")], ["periodo_atteso_ms", "atteso", 1], ["dlc_visti", "DLC", 0, (v) => (v ? v.join(",") : "")]], P.messaggi)));
      if (P.id_sconosciuti.length) box.append(el("div", { class: "pannello" }, el("h3", {}, "ID presenti ma non descritti nel DBC"),
        tabella([["id_hex", "ID"], ["hz", "Hz", 1, (v) => v.toFixed(1)], ["dlc", "DLC"], ["byte_variabili", "byte che cambiano", 0, (v) => v.join(",")], ["esempio", "esempio"]], P.id_sconosciuti)));
      if (P.plausibilita.length) box.append(el("div", { class: "pannello" }, el("h3", {}, "Controlli fisici"),
        tabella([["esito", "esito", 0, (v) => (v === "ok" ? "✓ ok" : "⚠ da verificare")], ["controllo", "controllo"], ["valore", "valore", 0, (v) => (typeof v === "object" ? JSON.stringify(v) : String(v))], ["nota", "nota"]], P.plausibilita)));
      if (P.segnali.length) box.append(el("div", { class: "pannello" }, el("h3", {}, "Segnali"),
        tabella([["segnale", "segnale"], ["unita", "unità"], ["min", "min", 1, (v) => DV.fmt(v)], ["max", "max", 1, (v) => DV.fmt(v)], ["fermo", "fermo", 0, (v) => (v ? "sì" : "")], ["fuori_campo_%", "fuori campo %", 1]], P.segnali)));
    },
  };
  DV.registraVista("protocollo", vista);
})();
