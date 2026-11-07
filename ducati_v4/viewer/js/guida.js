/* Guida passo per passo: parla con il servizio locale (python -m dvtool guida) */
(function () {
  const $ = (s) => document.querySelector(s);
  const el = (tag, attr = {}, ...figli) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attr || {})) {
      if (k === "class") e.className = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? "" : v);
    }
    for (const f of figli.flat()) if (f !== null && f !== undefined && f !== false) e.append(f instanceof Node ? f : document.createTextNode(String(f)));
    return e;
  };
  const avviso = (msg, tipo = "info") => { const e = el("div", { class: "avviso " + tipo }, msg); $("#avvisi").append(e); setTimeout(() => e.remove(), 6000); };
  const tempo = (s) => { if (s == null) return "–"; const m = Math.floor(s / 60); return `${m}:${(s - m * 60).toFixed(3).padStart(6, "0")}`; };
  const mb = (b) => (b / 1e6).toFixed(1) + " MB";

  // ---------------------------------------------------------------- servizio locale
  let codice = null;
  async function api(metodo, percorso, corpo) {
    if (!codice) {
      const r = await fetch("/api/codice");
      const j = await r.json();
      if (!j.guida) throw new Error("questa pagina va aperta con guida.bat (python -m dvtool guida)");
      codice = j.codice;
    }
    const r = await fetch(percorso, { method: metodo, headers: { "Content-Type": "application/json", "X-Dvtool-Codice": codice }, body: corpo ? JSON.stringify(corpo) : undefined });
    return r.json();
  }
  // esegue un'azione mostrando l'attesa nel riquadro esito
  async function esegui(box, testo, fn) {
    box.className = "esito attesa";
    box.innerHTML = "";
    box.append(el("span", { class: "rotella" }), testo);
    try { return await fn(); } catch (e) { mostra(box, false, String(e.message || e)); return null; }
  }
  function mostra(box, ok, titolo, ...dettagli) {
    box.className = "esito " + (ok ? "si" : "no");
    box.innerHTML = "";
    box.append(el("b", {}, (ok ? "✓ " : "✕ ") + titolo), ...dettagli);
  }

  // ---------------------------------------------------------------- passi
  const fatti = new Set();
  let stato = null, corrente = 0;
  const PASSI = [
    { titolo: "Prima di partire", sotto: "controlli e impostazioni", f: passoControlli },
    { titolo: "Collega il cronometro", sotto: "cavo USB, prova", f: passoCollega },
    { titolo: "Registra", sotto: "ai box, prima di uscire", f: passoRegistra },
    { titolo: "Ferma e scarica", sotto: "al rientro", f: passoScarica },
    { titolo: "Riguarda", sotto: "giri, curve, controlli", f: passoRiguarda },
    { titolo: "Prepara il file per la centralina", sotto: "dopo la modifica delle mappe", f: passoFile },
  ];
  function disegnaPassi() {
    const nav = $("#passi");
    nav.innerHTML = "";
    PASSI.forEach((p, k) => nav.append(el("button", { class: (k === corrente ? "attivo " : "") + (fatti.has(k) ? "fatto" : ""), onclick: () => vai(k) },
      el("span", { class: "num" }, fatti.has(k) ? "✓" : String(k + 1)), el("span", {}, p.titolo, el("span", { class: "sotto" }, p.sotto)))));
  }
  async function vai(k) {
    corrente = k;
    disegnaPassi();
    const main = $("#passo");
    main.innerHTML = "";
    try { stato = await api("GET", "/api/guida/stato"); } catch (e) { main.append(el("div", { class: "scheda" }, el("h3", {}, "Servizio locale non raggiungibile"), el("p", {}, String(e.message || e)))); return; }
    PASSI[k].f(main);
  }
  const avanti = (k) => el("button", { class: "bottone", onclick: () => vai(k) }, `Avanti: ${PASSI[k].titolo} →`);

  // ---- 1
  function passoControlli(main) {
    const imp = stato.impostazioni;
    main.append(el("h2", {}, "1 · Prima di partire"), el("p", { class: "intro" }, "Controllo di cosa c'è su questo PC. Le voci in rosso spiegano cosa fare."));
    const lista = el("div", { class: "scheda" }, el("h3", {}, "Controlli"));
    for (const c of stato.controlli) {
      lista.append(el("div", { class: "controllo" }, el("span", { class: "icona " + (c.ok ? "si" : "no") }, c.ok ? "✓" : "✕"), el("span", {}, el("b", {}, c.voce)),
        el("span", { class: "det" }, c.dettaglio), !c.ok && c.aiuto ? el("div", { class: "aiuto" }, c.aiuto) : null));
    }
    const sc = el("select", {}, el("option", { value: "r9" }, "R9 (r9-yccu)"), el("option", { value: "cm4" }, "CM4 (h3d-cm4)"));
    sc.value = imp.scatola;
    const host = el("input", { type: "text", value: imp.host });
    const usb = el("button", { class: "bottone", onclick: () => (host.value = sc.value === "cm4" ? "169.254.59.1" : "169.254.55.1") }, "indirizzo USB");
    const pista = el("input", { type: "text", value: imp.pista });
    const box = el("div");
    const salva = el("button", { class: "bottone primario", onclick: async () => {
      await api("POST", "/api/guida/impostazioni", { scatola: sc.value, host: host.value.trim(), pista: pista.value.trim() });
      avviso("impostazioni salvate");
      fatti.add(0); vai(1);
    } }, "Salva e vai avanti");
    main.append(lista, el("div", { class: "scheda" }, el("h3", {}, "Impostazioni"),
      el("div", { class: "campi" }, el("label", {}, "Cronometro"), sc, el("label", {}, "Indirizzo"), el("span", { class: "azioni" }, host, usb),
        el("label", {}, "Pista"), pista),
      el("p", { class: "nota" }, "Con il cavo USB l'indirizzo della R9 è 169.254.55.1. Con l'hotspot del telefono l'ultimo numero è .206 e il resto cambia: leggilo dall'app o dal telefono."),
      el("div", { class: "azioni" }, salva), box));
  }

  // ---- 2
  function testoPrese(r) {
    const elenco = Object.entries(r.prese || {}).map(([k, v]) => `${k} → ${v || "?"}`).join(", ");
    if (r.presa_ok === false) return `⚠ ${r.bus} NON è il morsetto della moto (${r.presa}): i nomi si sono scambiati all'avvio. Spegni e riaccendi la scatola. (${elenco})`;
    if (r.presa_ok === true) return `✓ ${r.bus} è il morsetto della moto (${r.presa}) · ${elenco}`;
    return elenco || "non lette";
  }
  function testoRegistratore(r) {
    if (!r.registratore.length) return "fermo";
    const s = r.registratore_stato;
    if (!s) return "● " + r.registratore.join(", ");
    const persi = s.persi_socket == null ? "persi ?" : `persi ${s.persi_socket} dall'avvio`;
    return `● ${r.registratore.join(", ")} · ${Math.round(s.frame_al_s)} frame/s · ${persi} · overflow ${s.overflow} · CPU ${s.cpu_pct}%`;
  }
  function schedaStato(r) {
    if (!r.ok) return el("div", {}, el("p", {}, r.errore));
    const scarto = r.orologio_scarto_s;
    return el("div", { class: "campi" },
      el("span", {}, "Scatola"), el("span", {}, `${r.hostname} (${r.dest}) · accesa ${r.acceso_da}`),
      el("span", {}, "Porte CAN"), el("span", {}, testoPrese(r)),
      el("span", {}, "Porta CAN"), el("span", {}, r.listen_only ? "✓ in ascolto (LISTEN-ONLY): non disturba il bus" : "normale (come per la R9)"),
      el("span", {}, "Orologio"), el("span", {}, scarto == null ? "?" : `${scarto > 0 ? "+" : ""}${scarto.toFixed(1)} s rispetto al PC${Math.abs(scarto) > 120 ? " (senza GPS e senza rete conta solo il tempo relativo)" : ""}`),
      el("span", {}, "Registratore"), el("span", {}, testoRegistratore(r)),
      el("span", {}, "Catture"), el("span", {}, r.catture.length ? r.catture.map((f) => `${f.nome} ${mb(f.byte)}`).join(" · ") : "nessuna"),
      el("span", {}, "Disco"), el("span", {}, r.disco));
  }
  function passoCollega(main) {
    const imp = stato.impostazioni;
    main.append(el("h2", {}, "2 · Collega il cronometro"),
      el("p", { class: "intro" }, `Collega la scatola ${imp.scatola.toUpperCase()} a questo PC con il cavo USB (o mettili sullo stesso hotspot), poi prova il collegamento. Questa prova legge soltanto, non cambia nulla.`));
    const box = el("div");
    main.append(el("div", { class: "scheda" }, el("div", { class: "azioni" }, el("button", { class: "bottone primario grande", onclick: async () => {
      const r = await esegui(box, "provo il collegamento…", () => api("POST", "/api/cronometro/stato", {}));
      if (!r) return;
      mostra(box, r.ok, r.ok ? "Collegamento riuscito" : "Collegamento non riuscito", schedaStato(r));
      if (r.ok) { fatti.add(1); box.append(el("div", { class: "azioni" }, avanti(2))); disegnaPassi(); }
    } }, "Prova il collegamento")), box));
    // la R9 non ha candump: il registratore Python va provato su questa scatola prima della Ducati
    const box2 = el("div");
    main.append(el("div", { class: "scheda" }, el("h3", {}, "Prova il registratore (20 s, non cambia niente)"),
      el("p", { class: "nota" }, "Sulla Streetfighter la CM4 registrava con candump; la scatola della R9 non ce l'ha e usa il registratore di questi strumenti. " +
        "Questa prova lo fa girare per 20 s leggendo can1 così com'è: niente sudo, servizi della R9 accesi, porta non toccata, nessun file lasciato. " +
        "Va bene anche con la scatola sulla R9 accesa: dice quanti frame al secondo arrivano e se se ne perdono."),
      el("div", { class: "azioni" }, el("button", { class: "bottone", onclick: async () => {
        const r = await esegui(box2, "registro per 20 s…", () => api("POST", "/api/cronometro/prova_registratore", { secondi: 20 }));
        if (!r) return;
        mostra(box2, r.ok, r.ok ? "Il registratore gira su questa scatola" : "Prova non riuscita",
          r.ok ? el("ul", {}, ...r.giudizio.map((g) => el("li", {}, g)), el("li", {}, `Porta CAN: ${r.listen_only ? "in ascolto" : "normale"}, lasciata com'era.`)) : el("pre", {}, r.errore || ""));
      } }, "Prova il registratore")), box2));
  }

  // ---- 3
  function passoRegistra(main) {
    main.append(el("h2", {}, "3 · Registra"), el("p", { class: "intro" }, "Ai box, con la scatola collegata alla presa CAN della Ducati e accesa. Dopo l'avvio puoi staccare il PC: la registrazione continua da sola."),
      el("div", { class: "avvertenza" }, el("b", {}, "Solo sulla Ducati, mai con la scatola montata sulla R9: "), "sul bus della R9 la centralina ha bisogno dell'ACK della scatola e con can1 in ascolto passivo continuerebbe a ritrasmettere. Sulla R9 usa solo «Prova il collegamento»."),
      el("div", { class: "cosa-cambia" }, el("b", {}, "Cosa cambia sulla scatola della R9, e solo finché non la ripristini o la spegni:"),
        el("ul", {}, el("li", {}, "i due registratori della R9 che usano can1 vengono fermati (non disattivati);"),
          el("li", {}, "can1 va in ascolto passivo a 500 kbit/s: non dà l'ACK e non può trasmettere nulla sulla Ducati;"),
          el("li", {}, "il registratore gira da una copia temporanea in /tmp, che sparisce allo spegnimento;"),
          el("li", {}, "le catture vanno nella cartella ~/catture_ducati.")),
        el("div", {}, "Il software della R9 non viene toccato, niente viene installato.")));
    const pw = el("input", { type: "password", autocomplete: "off", placeholder: "password di sudo sulla scatola" });
    const box = el("div"), box2 = el("div");
    main.append(el("div", { class: "scheda" }, el("div", { class: "campi" }, el("label", {}, "Password sudo"), pw),
      el("p", { class: "nota" }, "Serve per mettere can1 in ascolto. Va direttamente alla scatola e non viene salvata."),
      el("div", { class: "azioni" }, el("button", { class: "bottone primario grande", onclick: async () => {
        const r = await esegui(box, "metto can1 in ascolto e avvio la registrazione…", () => api("POST", "/api/cronometro/prepara_registra", { password: pw.value }));
        pw.value = "";
        if (!r) return;
        mostra(box, r.ok, r.ok ? "In ascolto e in registrazione: puoi staccare il PC e uscire" : `Non riuscito (${r.passo || ""})`, el("p", {}, r.errore || ""), el("pre", {}, r.testo || ""));
        if (r.ok) { fatti.add(2); disegnaPassi(); }
      } }, "Metti in ascolto e avvia la registrazione"),
      el("button", { class: "bottone", onclick: async () => {
        const a = await esegui(box2, "controllo…", () => api("POST", "/api/cronometro/stato", {}));
        if (!a) return;
        await new Promise((ok) => setTimeout(ok, 3000));
        const b = await api("POST", "/api/cronometro/stato", {});
        const tot = (r) => (r.catture || []).reduce((s, f) => s + f.byte, 0);
        const cresce = tot(b) > tot(a);
        const riavviata = b.ok && !b.registratore.length && !b.listen_only;
        mostra(box2, b.ok && b.registratore.length && cresce, !b.ok ? "Scatola non raggiungibile"
          : riavviata ? "La scatola è tornata come per la R9 (si è spenta e riaccesa?): rifai «Metti in ascolto e avvia la registrazione»"
            : cresce ? `Sta registrando: +${((tot(b) - tot(a)) / 1e3).toFixed(0)} kB in 3 s` : "Il file non cresce: la moto è accesa? il CAN è collegato?", schedaStato(b));
      } }, "Controlla che stia registrando")), box, box2),
      schedaMarcatori(),
      el("p", { class: "nota" }, "Se la scatola prende corrente dalla moto, a quadro spento si spegne e alla riaccensione torna come per la R9: servizi della R9 accesi e can1 normale, " +
        "cioè dà l'ACK sul bus della Ducati. Prima di uscire premi «Controlla che stia registrando» e, se serve, ripeti questo passo. " +
        "Meglio ancora, se il cablaggio della scatola lo permette, alimentala da un power bank: resta accesa e in ascolto tutto il giorno."),
      avanti(3));
  }

  // marcatori: come nella prova SFV4 del 31/10, ogni azione in garage segnata con l'orologio della scatola
  const AZIONI = ["quadro acceso", "motore acceso", "gas 0→100 tre volte", "leva freno anteriore", "pedale freno posteriore",
    "folle → prima", "TC cambiato", "AW cambiato", "SCS cambiato", "freno motore cambiato", "potenza cambiata",
    "piega a destra", "piega a sinistra", "ruota anteriore girata a mano"];
  function schedaMarcatori() {
    const box = el("div", { class: "nota" });
    const libero = el("input", { type: "text", placeholder: "oppure scrivi tu, es. «DTC da 3 a 5»" });
    const segna = async (testo) => {
      const r = await api("POST", "/api/cronometro/marca", { testo });
      box.prepend(el("div", {}, r.ok ? `✓ ${new Date().toLocaleTimeString()} · ${r.testo}` : `✕ ${r.errore}`));
    };
    return el("div", { class: "scheda" }, el("h3", {}, "Segna un momento (verifica in garage)"),
      el("p", { class: "nota" }, "Premi il pulsante mentre fai l'azione: il segno finisce nelle catture e nel visualizzatore compare sulla linea del tempo, così si vede subito quale canale si muove. È il metodo usato con la CM4 sulla Streetfighter."),
      el("div", { class: "azioni" }, ...AZIONI.map((a) => el("button", { class: "bottone", onclick: () => segna(a) }, a))),
      el("div", { class: "azioni" }, libero, el("button", { class: "bottone", onclick: () => { if (libero.value.trim()) { segna(libero.value.trim()); libero.value = ""; } } }, "Segna")),
      box);
  }

  // ---- 4
  function passoScarica(main) {
    main.append(el("h2", {}, "4 · Ferma e scarica"), el("p", { class: "intro" }, "Al rientro: ricollega il PC, ferma la registrazione e scarica le catture. Sulla scatola non si cancella nulla."));
    const box = el("div"), box2 = el("div"), box3 = el("div");
    const pw = el("input", { type: "password", autocomplete: "off", placeholder: "password di sudo" });
    main.append(el("div", { class: "scheda" }, el("div", { class: "azioni" },
      el("button", { class: "bottone primario grande", onclick: async () => {
        const r = await esegui(box, "fermo la registrazione…", () => api("POST", "/api/cronometro/ferma", {}));
        if (r) mostra(box, r.ok, r.ok ? "Registrazione ferma" : "Non riuscito", el("p", {}, r.errore || ""));
      } }, "1. Ferma la registrazione"),
      el("button", { class: "bottone primario grande", onclick: async () => {
        const r = await esegui(box2, "scarico e verifico le impronte…", () => api("POST", "/api/cronometro/scarica", {}));
        if (!r) return;
        mostra(box2, r.ok, r.ok ? `Catture scaricate in ${r.dest || ""}` : "Qualcosa non è andato", el("p", {}, r.errore || r.nota || ""),
          el("table", { class: "dati" }, el("tbody", {}, (r.file || []).map((f) => el("tr", {}, el("td", {}, f.ok ? "✓" : "✕"), el("td", {}, f.nome), el("td", { class: "n" }, f.byte ? mb(f.byte) : ""), el("td", {}, f.esito))))),
          r.registrazione_attiva ? el("p", {}, "Attenzione: la registrazione è ancora attiva, il file in corso può crescere ancora.") : null);
        if (r.ok) { fatti.add(3); disegnaPassi(); }
      } }, "2. Scarica le catture")), box, box2),
      el("div", { class: "scheda" }, el("h3", {}, "Prima di rimontare la scatola sulla R9"),
        el("p", {}, "Rimetti la scatola com'era: can1 normale e i servizi della R9 che erano attivi di nuovo in funzione. In alternativa basta spegnerla e riaccenderla."),
        el("div", { class: "campi" }, el("label", {}, "Password sudo"), pw),
        el("div", { class: "azioni" }, el("button", { class: "bottone", onclick: async () => {
          const r = await esegui(box3, "ripristino…", () => api("POST", "/api/cronometro/ripristina", { password: pw.value }));
          pw.value = "";
          if (r) mostra(box3, r.ok, r.ok ? "Scatola di nuovo come per la R9" : "Non riuscito", el("p", {}, r.errore || ""), el("pre", {}, r.testo || ""));
        } }, "Rimetti la scatola come per la R9")), box3),
      avanti(4));
  }

  // ---- 5
  function passoRiguarda(main) {
    main.append(el("h2", {}, "5 · Riguarda"), el("p", { class: "intro" }, "Scegli l'acquisizione e le due mappe: A è quella montata in moto durante l'acquisizione, B quella da confrontare o modificare. La Guida prepara tutto e apre il visualizzatore."));
    const acq = el("select", {});
    stato.acquisizioni.forEach((a) => acq.append(el("option", { value: a.file }, `${a.file} · ${mb(a.byte)} · ${a.data}`)));
    const selCal = (val) => { const s = el("select", {}); stato.calibrazioni.forEach((c) => s.append(el("option", { value: c.nome, selected: c.nome === val || undefined }, c.nome))); return s; };
    const A = selCal(stato.impostazioni.rif), B = selCal(stato.impostazioni.cfr || (stato.calibrazioni[1] || {}).nome);
    const pista = el("input", { type: "text", value: stato.impostazioni.pista });
    const box = el("div");
    if (!stato.acquisizioni.length) main.append(el("div", { class: "scheda" }, el("p", {}, `Nessuna acquisizione in ${stato.impostazioni.acquisizioni}: scaricale al passo 4.`)));
    main.append(el("div", { class: "scheda" }, el("div", { class: "campi" },
      el("label", {}, "Acquisizione"), acq, el("label", {}, "A · mappa montata"), stato.calibrazioni.length ? A : el("span", { class: "nota" }, "nessun file della centralina"),
      el("label", {}, "B · mappa da confrontare"), stato.calibrazioni.length ? B : el("span"), el("label", {}, "Pista"), pista),
      el("div", { class: "azioni" }, el("button", { class: "bottone primario grande", disabled: !stato.acquisizioni.length || undefined, onclick: async () => {
        const r = await esegui(box, "leggo il CAN, stimo i giri e ricalcolo la catena… (qualche decina di secondi per un turno)",
          () => api("POST", "/api/guida/analizza", { acquisizione: acq.value, rif: A.value, cfr: B.value, pista: pista.value.trim() }));
        if (!r) return;
        if (!r.ok) { mostra(box, false, "Analisi non riuscita", el("p", {}, r.errore)); return; }
        mostra(box, true, "Analisi pronta",
          el("div", { class: "campi", style: "margin-top:8px" },
            el("span", {}, "Giri lanciati"), el("span", {}, String(r.giri)), el("span", {}, "Migliore"), el("span", { class: "giro-tempo" }, tempo(r.migliore)),
            el("span", {}, "Curve riconosciute"), el("span", {}, String(r.curve)),
            el("span", {}, "Protocollo"), el("span", {}, r.protocollo),
            el("span", {}, "Catena di controllo"), el("span", {}, r.catena ? "ricalcolata (criteri, rami, schema, mappe)" : "non disponibile: servono struttura e modello compilati")),
          el("ul", { class: "nota" }, (r.plausibilita || []).map((p) => el("li", {}, `${p.esito === "ok" ? "✓" : "⚠"} ${p.controllo}: ${typeof p.valore === "object" ? JSON.stringify(p.valore) : p.valore}`))),
          el("details", {}, el("summary", { class: "nota" }, "note"), el("ul", { class: "nota" }, r.note.map((n) => el("li", {}, n)))),
          el("div", { class: "azioni" }, el("a", { class: "bottone primario grande", href: "/", target: "_blank", rel: "noopener" }, "Apri il visualizzatore ↗"), avanti(5)));
        fatti.add(4); disegnaPassi();
      } }, "Prepara l'analisi")), box));
  }

  // ---- 6
  function passoFile(main) {
    main.append(el("h2", {}, "6 · Prepara il file per la centralina"),
      el("div", { class: "scheda" }, el("h3", {}, "Come si modifica"),
        el("ol", {}, el("li", {}, "Nel visualizzatore metti in alto A = mappa montata e B = mappa da modificare."),
          el("li", {}, "Scheda Mappe (o Profilo pneumatico): scegli la tabella «in uso ora» e modificala. Si lavora su una copia di B."),
          el("li", {}, "Guarda l'effetto sullo stesso giro: Criteri e rami (A → B), Trigger per ramo, Schema software."),
          el("li", {}, "In fondo alla scheda Mappe premi «Prepara il file per la centralina». In alternativa carica qui sotto una patch .json scaricata prima.")),
        el("p", { class: "nota" }, "I file originali in privato\\calibrazioni non vengono mai modificati: il file nuovo va in privato\\calibrazioni\\modificati con data e ora nel nome.")));
    const file = el("input", { type: "file", accept: ".json" });
    const base = el("select", {});
    stato.calibrazioni.forEach((c) => base.append(el("option", { value: c.file, selected: c.nome === stato.impostazioni.cfr || undefined }, c.nome)));
    const box = el("div");
    main.append(el("div", { class: "scheda" }, el("h3", {}, "Da una patch"), el("div", { class: "campi" }, el("label", {}, "Patch .json"), file, el("label", {}, "File di partenza"), base),
      el("div", { class: "azioni" }, el("button", { class: "bottone primario grande", onclick: async () => {
        if (!file.files[0]) { avviso("scegli la patch", "errore"); return; }
        const patch = JSON.parse(await file.files[0].text());
        const r = await esegui(box, "applico la patch, correggo e verifico il checksum…", () => api("POST", "/api/guida/applica", { file: base.value, patch }));
        if (r) mostraFile(box, r);
      } }, "Prepara il file")), box));
  }
  function mostraFile(box, r) {
    if (!r.ok && !r.file) { mostra(box, false, "File non preparato", el("p", {}, r.errore || "")); return; }
    mostra(box, r.ok, r.ok ? "File pronto da scrivere in centralina" : "File creato ma NON pronto: controlla sotto",
      el("div", { class: "campi", style: "margin-top:8px" },
        el("span", {}, "File"), el("code", {}, r.file), el("span", {}, "Partito da"), el("span", {}, r.base + (r.variante ? ` (variante ${r.variante})` : "")),
        el("span", {}, "Impronta"), el("code", {}, r.sha256.slice(0, 16) + "…"),
        el("span", {}, "Checksum"), el("span", {}, r.checksum.map((c) => `${c.ok ? "✓" : "✕"} ${c.id}`).join(" · ") || "nessuno"),
        el("span", {}, "Tabelle cambiate"), el("span", {}, r.tabelle_cambiate.map((t) => `${t.id} (${t.celle_cambiate} celle)`).join(", ") || "nessuna"),
        el("span", {}, "Fuori dalla struttura"), el("span", {}, r.fuori_struttura.length ? `✕ ${r.fuori_struttura.length} zone cambiate: NON scrivere questo file` : "✓ nessuna zona cambiata")),
      r.avvisi && r.avvisi.length ? el("ul", {}, r.avvisi.map((a) => el("li", {}, a))) : null,
      el("p", {}, "Scrivi questo file con lo strumento con cui hai letto la centralina e tieni l'originale. Procedi a piccoli passi: nuova acquisizione e confronto prima/dopo."));
  }
  window.guidaMostraFile = mostraFile;

  // ---------------------------------------------------------------- tema
  const tema = $("#tema");
  const applica = (t) => { if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; tema.value = t || ""; try { t ? localStorage.setItem("dv-tema", t) : localStorage.removeItem("dv-tema"); } catch (e) { /* niente */ } };
  tema.addEventListener("change", () => applica(tema.value));
  try { applica(localStorage.getItem("dv-tema") || ""); } catch (e) { /* niente */ }

  vai(0);
})();
