# Contesto del lavoro (per una sessione nuova, sul PC di lavoro o di casa)

Riassunto della discussione con Maurizio da cui sono nati questi strumenti: cosa vuole, cosa è stato deciso, cosa
è provato e cosa no. Va letto prima di `PASSAGGIO_CLAUDE_CODE.md` (i passi) e del `README.md` (i comandi).
Maurizio scrive spesso dal telefono, in italiano: risposte brevi, passo per passo, comandi da incollare.

## Obiettivo

- **Moto:** Ducati Panigale V4 R 2025.
- **Centralina dei controlli:** il software **Divac Pro**, pensato per le slick, già decodificato sul PC di casa.
  Verso la centralina motore manda le richieste di coppia su 0x019 (TrqSlow/TrqFast).
- **Le domande di Maurizio:**
  - quale ramo dei controlli lavora istante per istante;
  - dov'è il punto attuale e quanto manca alla soglia, per ognuno dei **4 criteri**;
  - quanto manca al trigger della **derivata di potenza**, ramo per ramo;
  - quali tabelle e quali celle sta usando;
  - come modificare il file per la centralina, compreso il **profilo pneumatico**: com'è e come lo sta cambiando.
- **Mappe:** **NOSLICK** e **Divac Pro**, da confrontare (A = montata, B = confronto, si sceglie).
  Sul PC di casa sono i due file `.ORI.bin` nella cartella della decodifica (`filippo\ducati\`); i nomi sono
  nelle note in `privato\ricerche\`. Quale dei due sia il Divac Pro va confermato con Maurizio.
- **Livelli selezionabili sulla moto:** potenza, TC (DTC), SCS (DSC), AW (DWC), freno motore (EBC).
- **Pista:** Vallelunga, **senza antenna GPS**. Giri e curve si stimano dalla distanza.
- **Registratore:** la **scatola H3D Chrono della R9** (`r9-yccu`), usata solo per registrare il CAN.
  Maurizio non vuole che venga modificata («non voglio piallarla»).
- **Due PC:** sul PC di casa c'è tutta la decodifica, e si raggiunge solo con AnyDesk. Il PC di lavoro è quello
  che va in pista. Sul PC voleva una GUI che lo guidi: è `guida.bat`.

## Cosa è stato deciso, nell'ordine in cui è stato chiesto

1. **Visualizzatore** (`visualizza.bat`):
   - **Schema software:** schema a corsie nello stile degli SVG del flusso fatti per la decodifica, con le tabelle
     espanse, il ramo attivo evidenziato e le celle in uso.
   - **Tabelle dal vivo:** la vista tipo INCA, **tenuta anche lei**: «teniamo la doppia visualizzazione, poi
     usandolo decidiamo».
   - **Trigger per ramo:** la distanza dal trigger della derivata di potenza.
   - **Giri e curve:** lap e curva corrente sempre visibili (barra in basso, mappa della pista ricostruita,
     selettore «vai alla curva»).
   - **Tema:** chiaro, scuro o automatico.
   - **Livelli:** i 5 livelli si leggono dal CAN o si fissano a mano; la catena viene ricalcolata con quelli.
2. **Protocollo:** si presume quello della Streetfighter V4S 2023, con un controllo automatico
   (`can verifica`: contatore, CRC-8, periodi, valori fisici, overflow).
3. **Guida** (`guida.bat`), in 6 passi:
   1. impostazioni;
   2. collega la scatola, e *Prova il registratore*;
   3. registra, e *Segna un momento*;
   4. ferma, scarica, rimetti la scatola com'era;
   5. riguarda;
   6. prepara il file per la centralina.
4. **Dalla CM4 alla R9.** La prova sulla Streetfighter del 31/10 è stata fatta con la **CM4** e candump. Sulla
   Ducati va invece la **scatola della R9**, che è un Pi Zero 2 W senza candump: registra `registratore_can.py`,
   che su una scatola vera non ha ancora girato.

## Regole, da rispettare sempre

- **Il repository è pubblico.** Niente di `privato\` va pubblicato: DBC, `.bin`/`.ORI`, struttura e modello
  compilati, catture, chiavi, password. Niente percorsi personali nei file pubblici: si usa `%USERPROFILE%`.
- **La scatola della R9 non si modifica.**
  - Niente installazioni, niente modifiche al progetto `yccu-peer`, nessun servizio disattivato.
  - I servizi si fermano solo per la registrazione e poi si rimettono come erano.
  - SSH verso la scatola solo quando lo chiede Maurizio.
- **Listen-only (*prepara* / *registra*) solo con la scatola sulla Ducati, mai sulla R9.** La centralina della
  R9 vuole l'ACK della scatola. Sulla R9 si usano solo *Prova il collegamento* e *Prova il registratore*.
- **Nessuna trasmissione sul CAN, nessuna scrittura in centralina.** I file per la centralina si preparano solo
  se il checksum dell'originale torna. Gli originali non si toccano mai.
- **La password di sudo** la scrive Maurizio e non si salva da nessuna parte.
- **Struttura e modello** (`privato\struttura.json`, `privato\modello.json`) li compila Maurizio dal
  materiale della decodifica. Gli strumenti sono guidati dai dati e non contengono la catena della centralina.

## Protocollo: cosa si sa

- **Formato del bus:** 500 kbit/s, ID a 11 bit. I frame della centralina sono Motorola, quelli dell'IMU Intel.
  Contatore in B6[3:0], CRC-8 SAE J1850 in B7.
- **ID principali:**

  | ID | contenuto |
  |---|---|
  | 0x018 | ruote, livelli DTC/DWC/DSC, bit di off (DWC off = b5.6) |
  | 0x019 | TrqSlow/TrqFast |
  | 0x024 | giri, marcia, gas |
  | 0x080 | modo motore |
  | 0x188 | piega |
  | 0x190 | EBC |
  | 0x020 | livelli del cruscotto |

  I DBC sono in `privato\can\` (`SFV4_bus_practical.dbc`), il profilo in `esempi\profilo_ducati_v4.json`.
- **Sentinelle all'accensione** (0xFF, 0xFFF, piega −409,6°, marcia 7): vengono scartate con gli intervalli
  del profilo.
- **Scale e assi da tenere presenti:**
  - il power mode delle scale AiM è sfalsato di uno;
  - DTC_Lv su AiM ha scala 0,5 e offset +1, ancora da confermare;
  - gli assi dell'IMU su 0x178/0x17C sono ruotati di circa 56°.
- **Prova del 31/10** (CM4, Streetfighter, listen-only): 28 campi confermati, con i marcatori di ogni azione.
  - **Ricevitore:** l'MCP2515 va in overflow, 12 volte in 48 s a circa 1650 frame/s. I frame di errore
    `20000004` vengono contati a parte e non diventano l'ID 0x004.
  - **Mai verificati in movimento:** ruote, piega e TrqSlow/TrqFast.

## Scatola della R9: cosa c'è da sapere

- **Hardware e accesso:** Pi Zero 2 W con Waveshare 2-CH CAN HAT+ (MCP2515), utente `yccu`.
  - Via USB: 169.254.55.1.
  - Via hotspot del telefono: ultimo numero .206, il resto cambia.
- **Porte:** bus della moto = `can1` sul morsetto CAN_0 (`spi1.1`); `can0` (`spi1.2`) è la lambda. Dopo un
  riavvio i nomi possono scambiarsi: *prepara*, *registra* e *prova* controllano il morsetto e, se non torna,
  si fermano senza toccare niente.
- **Servizi che usano `can1`:** `r9-can-correlation` e `r9-can`. Si fermano per registrare (non si
  disattivano) e *ripristina* riavvia solo quelli che erano attivi.
- **Il registratore** gira da una copia in `/tmp` e scrive nel formato di `candump -L`.
  - Conta i frame che il Pi perde, le scritture su SD sono ogni 2 s, `.registratore.stato` si aggiorna ogni 5 s.
  - I segni di *Segna un momento* finiscono in `~/catture_ducati/marcatori.txt`.
- **Alimentazione:** se la scatola prende corrente dalla moto, a quadro spento si spegne e alla riaccensione
  torna come per la R9, cioè dà l'ACK sul bus. Prima di uscire va fatto *Controlla che stia registrando*.
- **Chiave SSH:** la scatola accetta solo chiavi e oggi conosce solo quella del PC di casa. Il PC di lavoro si
  autorizza con `cronometro autorizza --chiave <copia temporanea della chiave di casa>` (README, «Chiave SSH»).

## Cosa si può fare con una cattura

**Subito, senza struttura e modello:** giri, curve, mappa della pista, canali, livelli, segni, protocollo.
```
dvtool.bat can verifica <cattura.log> --dbc privato\can\SFV4_bus_practical.dbc --profilo esempi\profilo_ducati_v4.json --out verifica.md
dvtool.bat giri <cattura.log> --profilo esempi\profilo_ducati_v4.json --pista vallelunga
```
Oppure Guida → passo 5 (*Riguarda*), che crea la sessione e apre il visualizzatore.

**Con `privato\struttura.json`, `privato\modello.json` e le due mappe:** criteri, rami, trigger, tabelle e celle
in uso, confronto A/B, modifica e checksum.
```
dvtool.bat sessione <cattura.log> --profilo esempi\profilo_ducati_v4.json --modello privato\modello.json --struttura privato\struttura.json --bin NOSLICK=privato\calibrazioni\NOSLICK.bin --bin DIVAC_PRO=privato\calibrazioni\DIVAC_PRO.bin --pista vallelunga --out privato\progetto\sessione.json.gz
dvtool.bat calib checksum --struttura privato\struttura.json --bin privato\calibrazioni\NOSLICK.bin
```

## Stato

- **Provato solo su dati sintetici e su una scatola finta** (`tests\scatola_finta`):
  - visualizzatore e catena;
  - giri, con un errore sul tempo sotto i 20 ms;
  - Guida;
  - registra, segna, ferma, scarica e ripristina;
  - prova del registratore;
  - porte scambiate.
- **Mai provato su una scatola vera né sulla moto.** La prima volta sarà *Prova il registratore* con la
  scatola sulla R9, poi la sequenza in garage sulla Ducati (PASSAGGIO, B5).
- **Punti aperti:**
  - `struttura.json` e `modello.json` da compilare (PASSAGGIO, A4);
  - pinout della presa Ducati, mai annotato (quello YDT è Yamaha);
  - segno della piega (`curve.piega_positiva` nel profilo);
  - scala di DTC_Lv;
  - numerazione del power mode sulla V4 R;
  - quale fra L1 e L2 sia DTC e quale DWC (l'analisi della centralina e l'osservazione in moto non concordano);
  - cosa riporta *Prova il registratore* sul Pi Zero: frame persi e CPU.
