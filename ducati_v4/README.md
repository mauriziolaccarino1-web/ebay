# ducati_v4 — analisi del controllo in piega (Panigale V4 R 2025, protocollo V4S)

Moto: Ducati Panigale V4 R 2025. Il software analizzato è quello della **centralina dei controlli** (file Divac Pro,
pensato per le slick), che chiede alla centralina motore la riduzione di coppia sul CAN (0x019 TrqSlow/TrqFast).
Prima prova: Vallelunga (4085 m) con il cronometro R9 usato come registratore.

Strumenti per:

| bisogno | strumento |
|---|---|
| portare dati e decodifica dal PC di casa a quello di lavoro | `dvtool pacchetto` (zip con impronte sha256) + questo repository |
| usare la scatola del cronometro della R9 **solo come registratore** CAN sulla Ducati | `dvtool cronometro` + `dvtool/registratore_can.py` |
| tempi sul giro **senza antenna GPS**, dalla distanza percorsa | `dvtool giri` (anche dentro `sessione`) |
| verificare che la moto usi il protocollo della Streetfighter V4S | `dvtool can verifica` + scheda *Protocollo CAN* |
| vedere quale ramo dei controlli lavora, dove è il punto attuale, quanto manca a ogni soglia (4 criteri) | visualizzatore, schede *Criteri e rami* e *Schema software* |
| vedere lo schema del software della centralina dei controlli con le tabelle espanse, il ramo attivo e le celle su cui lavora; tracciare tutta la sequenza dei dati (CAN → ingressi → blocchi → criteri → rami → logica → uscita) | scheda *Schema software* |
| per ogni ramo, quanto si è lontani dal trigger della derivata (di potenza) e dove nel giro ci si avvicina | scheda *Trigger per ramo* |
| ripercorrere il giro vedendo, come in INCA, le lookup table lette dal programma con le celle su cui sta la moto e il ramo attivo | scheda *Tabelle dal vivo* |
| scegliere la mappa di riferimento (NOSLICK, SLICK, …) e confrontarla con un'altra | selettori **A** / **B** in alto, `dvtool progetto --cal` |
| vedere e modificare tabelle e curve, capire quale si sta usando e dove | scheda *Mappe* + `dvtool calib` |
| vedere il profilo pneumatico, com'è e come lo si sta modificando | scheda *Profilo pneumatico* |

Nessuna installazione oltre a Python 3.10+ e `numpy`. Il visualizzatore è una pagina HTML con
[uPlot](https://github.com/leeoniya/uPlot) incluso (licenza MIT, `viewer/lib/`): funziona anche senza internet.

> **Il repository è pubblico.** DBC, file della centralina, struttura e modello compilati, acquisizioni e token
> vanno in `privato/`, che git ignora. Qui ci sono solo il codice, i modelli vuoti e un esempio sintetico.

## 0. Il modo più semplice: la Guida

Doppio clic su **`guida.bat`**: si apre nel browser una procedura passo per passo, con un pulsante per ogni fase:

1. **Prima di partire**: controlla cosa c'è sul PC (client SSH, chiave, DBC, struttura, modello, file della centralina) e spiega cosa fare per le voci in rosso; qui si imposta l'indirizzo della scatola e la pista.
2. **Collega il cronometro**: prova il collegamento in sola lettura e mostra lo stato della scatola.
3. **Registra**: chiede la password di sudo della scatola, che non viene salvata, mette `can1` in ascolto e avvia la registrazione; *Controlla che stia registrando* verifica che il file cresca. Poi si stacca il PC e si esce in pista.
4. **Ferma e scarica**: ferma, scarica con verifica delle impronte e **rimette la scatola come per la R9**.
5. **Riguarda**: scegli l'acquisizione, la mappa A (montata) e la mappa B (da confrontare). La Guida stima giri e curve, verifica il protocollo, ricalcola la catena e apre il visualizzatore.
6. **Prepara il file per la centralina**: dopo la modifica in *Mappe*, il pulsante *Prepara il file per la centralina* crea un file nuovo in `privato\calibrazioni\modificati`. Il file ha checksum corretto e verificato e il confronto con l'originale; se la regola del checksum non torna sull'originale, la Guida rifiuta di prepararlo. Gli originali non vengono mai modificati.

La Guida gira solo su questo PC (127.0.0.1) e accetta comandi solo dalle sue pagine.

## 1. Prova subito con i dati DEMO

```
py -m pip install numpy
py -m dvtool demo --apri          (Linux: python3 -m dvtool demo --apri)
```

Crea in `esempi/demo/` una pista, un log CAN, un modello e due mappe della centralina **inventati** (protocollo
DEMO, non Ducati): `NOSLICK`, montata nel registrato, e `SLICK`, più libera, con i profili pneumatico in altri
indirizzi. Poi apre il visualizzatore su `http://127.0.0.1:8765`. Serve a vedere come funziona tutto prima di avere
i file veri.

## 2. Dal PC di casa al PC di lavoro

Sul PC di **lavoro**:

```
git clone https://github.com/mauriziolaccarino1-web/ebay.git
cd ebay && git checkout claude/ducati-420-25-divac-analysis-v5qwmk && cd ducati_v4
```

(oppure scarica lo zip del ramo da GitHub). Sul PC di **casa**, dalla cartella `ducati_v4`:

```
py -m dvtool pacchetto crea --raccolta esempi\raccolta_casa.json --out ducati_v4_trasferimento.zip
```

`esempi/raccolta_casa.json` elenca i percorsi trovati nelle sessioni precedenti: DBC e protocollo della SFV4
(`filippo\SFV4_23\can\`), materiale BBSV4 (`filippo\ducati\`), note e cattura del 31/10 (`D:\h3d_note\sfv4_2023\`).
Controlla i percorsi: quelli che non esistono vengono elencati e saltati. Porta lo zip sul PC di lavoro (chiavetta,
OneDrive…) e:

```
py -m dvtool pacchetto apri ducati_v4_trasferimento.zip --in privato
```

L'apertura verifica l'impronta di ogni file e non sovrascrive file diversi già presenti (`--sovrascrivi` per farlo).
Il pacchetto funziona anche al contrario (lavoro → casa).

**Chiave SSH per il cronometro dal PC di lavoro.** La scatola accetta solo chiavi e oggi conosce solo quella del
PC di casa, che però non la raggiunge: la scatola è con te. Si usa quindi per pochi minuti una copia della chiave
di casa sul PC di lavoro, solo per autorizzare la chiave nuova.

1. **Casa:** trova la chiave con cui entri nella scatola. È in `%USERPROFILE%\.ssh\`: se c'è il file `config`,
   la riga `IdentityFile` sotto l'`Host` della scatola (169.254.55.1, `r9-yccu` o l'indirizzo .206); altrimenti
   è `id_ed25519` (o `id_rsa`), il file **senza** `.pub`.
2. Copiala sul PC di lavoro con il trasferimento file di AnyDesk, in `%USERPROFILE%\.ssh\chiave_casa`.
   Mai per email, chat o cartelle in cloud.
3. **Lavoro:** `ssh-keygen -t ed25519`, con invio a tutte le domande. La passphrase va lasciata vuota, altrimenti
   la Guida non può usare la chiave.
4. **Lavoro, con la scatola accesa** e raggiungibile via USB o sullo stesso hotspot del telefono (va bene anche
   montata sulla R9: non si tocca il CAN):
   ```
   dvtool.bat cronometro autorizza --scatola r9 --host <indirizzo> --file %USERPROFILE%\.ssh\id_ed25519.pub --chiave %USERPROFILE%\.ssh\chiave_casa
   ```
   - Se la chiave di casa ha una passphrase, te la chiede.
   - Alla fine verifica che la chiave nuova entri da sola.
   - Se ssh dice `UNPROTECTED PRIVATE KEY FILE`:
     `icacls %USERPROFILE%\.ssh\chiave_casa /inheritance:r /grant:r "%USERNAME%":F`
5. **Lavoro:** `del %USERPROFILE%\.ssh\chiave_casa`.

Sulla scatola si aggiunge solo una riga a `~/.ssh/authorized_keys`.

**USB o wifi.** Via USB l'indirizzo della R9 è 169.254.55.1. Via wifi PC e scatola stanno sull'hotspot del
telefono: l'ultimo numero è .206, il resto cambia ogni volta che riaccendi l'hotspot, e lo leggi sul telefono
fra i dispositivi connessi. Mettilo nella Guida al passo 1 («Indirizzo») o usa `--host`. L'impronta della
scatola è salvata sotto l'indirizzo USB, per cui va bene in tutti e due i modi.

## 3. In pista: il cronometro come registratore

Sulla Ducati va la **scatola della R9**. La CM4 è quella usata il 31/10 sulla Streetfighter: da quella prova
vengono le indicazioni, ma la scatola è un'altra. Fatti dalle sessioni precedenti, da ricontrollare:

| | R9 (`r9-yccu`): va sulla Ducati | CM4 (`h3d-cm4`): prova SFV4 del 31/10 |
|---|---|---|
| hardware | Pi Zero 2 W + Waveshare 2-CH CAN HAT+ (MCP2515) | CM4 + CAN HAT (MCP2515, 8 MHz) |
| indirizzo via USB | 169.254.55.1 | 169.254.59.1 |
| utente SSH | yccu | yccu |
| bus moto | can1 sul morsetto CAN_0 (`spi1.1`); can0 (`spi1.2`) è la lambda | can1 (`spi1.1`) |
| registrazione | `registratore_can.py` di questi strumenti (candump non c'è) | `candump -L` |
| sudo | chiede la password | senza password |
| provata sulla Ducati | **no**: la prima volta sarà in garage | sì, Streetfighter V4 2023 |

Bus Ducati: 500 kbit/s, ID a 11 bit. Il cronometro **deve stare in listen-only**: non dà l'ACK e non può
trasmettere nulla sul bus della moto.

```
py -m dvtool cronometro stato    --scatola r9          # risponde? can1 com'è? è il morsetto della moto? servizi attivi?
py -m dvtool cronometro prova    --scatola r9          # 20 s di registratore senza cambiare niente (anche sulla R9)
py -m dvtool cronometro prepara  --scatola r9          # ferma per ora i registratori r9, can1 a 500k in LISTEN-ONLY
py -m dvtool cronometro registra --scatola r9          # avvia la registrazione in ~/catture_ducati/
   ... turno in pista ...
py -m dvtool cronometro ferma    --scatola r9
py -m dvtool cronometro scarica  --scatola r9 --dest privato\acquisizioni
py -m dvtool cronometro ripristina --scatola r9        # listen-only off, riavvia solo i servizi che erano attivi
```

**La scatola della R9 non viene modificata.**
- Niente viene installato: il registratore (`dvtool/registratore_can.py`, solo libreria standard) viene mandato via SSH in una copia temporanea `/tmp/dvtool_registratore.py`, che sparisce allo spegnimento.
- I servizi R9 che usano `can1` vengono solo **fermati**, non disattivati. `ripristina` riavvia esattamente quelli che erano attivi prima, letti da `~/catture_ducati/.servizi_attivi_prima`.
- Il listen-only di `can1` è un'impostazione del momento.
- Spegnendo e riaccendendo, la scatola torna esattamente come per la R9.
- Resta solo la cartella dati `~/catture_ducati`.
- Sul PC di lavoro serve una riga in più fra le chiavi SSH autorizzate della scatola (`cronometro autorizza`).

Ogni comando che cambia qualcosa sulla scatola mostra cosa eseguirà e chiede conferma. Sulla scatola non viene
cancellato nulla; `scarica` confronta le impronte sha256. Con `--host` usi un altro indirizzo (es. hotspot del
telefono: sulla R9 l'ultimo ottetto è sempre .206). Le impostazioni si possono fissare in `privato/cronometro.json`.


**Collegamento alla presa della Ducati.** Sono le indicazioni della prova con la CM4 sulla Streetfighter, il 31/10.
- **Pinout:** quello della presa Ducati non è mai stato annotato. Il pinout YDT a 6 poli (bianco CAN-H, verde acqua CAN-L, rosso +12 V, nero massa) è della Yamaha, non vale per la Ducati.
- **Misure prima di collegare:**
  - a quadro spento, fra CAN-H e CAN-L circa **60 Ω**: le due terminazioni della moto;
  - a quadro acceso, CAN-H 2,5-3,5 V e CAN-L 1,5-2,5 V verso massa;
  - +12 V e massa si trovano con il tester.
- **Terminazione da 120 Ω:** sulla CM4 il ponticello era stato **tolto**, perché la moto ha già le sue. Se la scheda CAN della scatola R9 ha la terminazione inserita, toglila per la Ducati e **rimettila prima di rimontare la scatola sulla R9**. Con la scatola collegata, la misura deve restare intorno a 60 Ω: 40 Ω vuol dire una terminazione in più.
- **Bus muto a quadro spento:** la prima volta, il 31/10, sono arrivati 0 frame proprio per questo. Ci vuole il quadro acceso.
- **Overflow dell'MCP2515:** il controller della scatola perde qualche frame (12 overflow in 48 s, circa 1650 frame/s). I frame di errore (`20000004#...`) vengono registrati e contati a parte nella verifica del protocollo, che dice anche quanti frame mancano per ID.

**Dalla CM4 della Streetfighter alla scatola della R9.** Quello che il 31/10 ha provato vale anche qui: stesso
controller MCP2515 sullo stesso morsetto `spi1.1`, listen-only a 500 kbit/s, stessi overflow (sulla R9 visti
anche il 30/10). Quello che sulla R9 **non è ancora provato**, e come lo coprono gli strumenti:
- **Registratore.** Sulla R9 candump non c'è e non si installa: gira `registratore_can.py`, mandato via SSH in `/tmp`.
  Scrive lo stesso formato `candump -L`, compresi i frame di errore, e in più conta i frame che il Pi
  stesso non fa in tempo a leggere (`SO_RXQ_OVFL`), separati dagli overflow del controller.
  - **Prova prima della Ducati:** *Prova il registratore* nella Guida (passo 2) o `cronometro prova`. Lo fa girare
    20 s leggendo can1 così com'è: niente sudo, servizi della R9 accesi, porta non toccata, cartella temporanea
    cancellata. Si può fare con la scatola sulla R9 accesa, perché un lettore in più non trasmette nulla.
    Riporta frame al secondo, frame persi, overflow e CPU.
- **Pi Zero 2 W.** È molto meno potente della CM4. La prova e *Controlla che stia registrando* dicono se tiene il passo.
- **Nomi delle porte.** `can0`/`can1` dipendono dall'ordine di avvio. Prima di toccare il bus, *prepara*,
  *registra* e *prova* controllano che `can1` sia davvero sul morsetto della moto (`spi1.1`). Se non lo è si
  fermano senza cambiare niente; di solito basta spegnere e riaccendere la scatola.
- **Alimentazione.** Il 31/10 la CM4 non era alimentata dalla moto. Se la scatola della R9 prende i 12 V dalla
  presa Ducati, a quadro spento si spegne e alla riaccensione torna come per la R9: servizi accesi e can1 normale,
  cioè dà l'ACK sul bus della Ducati. Prima di uscire premi *Controlla che stia registrando*, che lo riconosce, e
  se serve rifai il passo 3. Se il cablaggio lo permette, è meglio un power bank. Il registratore scrive su SD
  ogni 2 s, così uno spegnimento brusco perde al massimo gli ultimi 2 s.
- **Orologio.** Il Pi Zero non ha l'orologio a batteria e via USB non riceve l'ora: *stato* mostra lo scarto
  rispetto al PC. Catture e segni usano lo stesso orologio della scatola, quindi restano allineati fra loro.

La CM4 resta configurata negli strumenti (`--scatola cm4` o «CM4» al passo 1): se la usi, registra con candump come il 31/10.

**Marcatori.** Il 31/10 ogni azione in garage era segnata con l'ora: quadro acceso, gas tre volte, leve dei freni, marce, livelli dal menu, motore. Così si è visto subito quale campo si muoveva, e 28 campi sono stati confermati. Nella Guida, al passo 3, *Segna un momento* fa lo stesso: i segni finiscono in `marcatori.txt` con l'orologio della scatola, vengono scaricati con le catture e compaiono sulla linea del tempo e in *Acquisizione*.

Note:

- Se la scatola si spegne con la moto, alla riaccensione è tornata come per la R9: rifai *prepara* e *registra* (passo 3 della Guida).
- Sulla R9 il registratore Python lascia `.registratore.stato` (frame/s, persi, overflow, CPU) aggiornato ogni 5 s, e a fine registrazione la riga `FINE` in `marcatori.txt` con i totali.
- Il formato registrato è quello di `candump -L` (come la cattura SFV4 del 31/10), letto direttamente da tutti i comandi.
- Si registra tutto il bus grezzo, senza filtri: anche gli ID non descritti nel DBC. Le catture non si modificano
  e non si cancellano; ogni analisi si rifà da lì, anche dopo aver aggiornato DBC o profilo.
- Senza GPS l'orologio della scatola può essere sbagliato: per l'analisi contano solo i tempi relativi.
- L'MCP2515 a questo carico perde qualche frame (12 overflow in 48 s sulla SFV4): la verifica del protocollo li conta per ID.
- Si leggono anche i segmenti `r9-can` (`.jsonl.gz`) e le cartelle `app_data/can_cablato/`.

## 4. Analisi

```
py -m dvtool can inventario privato\acquisizioni\cattura_XXXX.log
py -m dvtool can verifica   privato\acquisizioni\cattura_XXXX.log --dbc privato\can\SFV4_bus_practical.dbc --profilo esempi\profilo_ducati_v4.json --out verifica.md
py -m dvtool giri           privato\acquisizioni\cattura_XXXX.log --profilo esempi\profilo_ducati_v4.json   (pista: vallelunga nel profilo)
py -m dvtool sessione       privato\acquisizioni\cattura_XXXX.log --profilo esempi\profilo_ducati_v4.json ^
                            --modello privato\modello.json --struttura privato\struttura.json ^
                            --bin NOSLICK=privato\calibrazioni\noslick.bin --out privato\sessione_1.json.gz
py -m dvtool progetto       --cartella privato\progetto --struttura privato\struttura.json --modello privato\modello.json ^
                            --cal NOSLICK=privato\calibrazioni\noslick.bin --cal SLICK=privato\calibrazioni\slick.bin ^
                            --sessione privato\sessione_1.json.gz --riferimento NOSLICK --confronto SLICK
visualizza.bat privato\progetto
```

**È il protocollo della V4S?** Sulla Streetfighter V4 2023 ogni frame della centralina (tranne 0x360) porta un
contatore in B6[3:0] e un CRC-8 SAE J1850 in B7 (poli 0x1D, init 0xFF, xor 0xFF), corretti al 100%. La verifica
li cerca su ogni ID: se li ritrovi sugli stessi ID, con gli stessi periodi e con segnali plausibili (giri/velocità a
gradini per marcia, ruote coerenti, piega entro ±70°), il protocollo è lo stesso. Il profilo
`esempi/profilo_ducati_v4.json` dice per ogni canale se era già stato visto funzionare: ruote, piega e
TrqSlow/TrqFast **non erano ancora stati provati** in moto.

**Giri senza GPS.** La distanza è l'integrale della velocità ruota anteriore, corretta per il raggio in piega. La
firma della pista (velocità e curvatura g·tan(piega)/v² lungo la distanza) dà per autocorrelazione la lunghezza
reale del giro. Questa assorbe l'errore di circonferenza e la traiettoria. Ogni passaggio sul traguardo è il picco di
correlazione con un giro modello. Sui dati sintetici l'errore sul tempo sul giro resta sotto i 2 centesimi. Opzioni:
`--pista` (nome o metri, restringe la ricerca), `--linea vmax|frenata`, `--offset` (metri) e `--t-traguardo` (un
istante noto di passaggio, per esempio dal video). Dalla stessa firma si ricostruisce la forma della pista, senza GPS.

## 5. Il visualizzatore

`py -m dvtool visualizza <cartella>` serve la cartella (con `progetto.json`) solo su 127.0.0.1. In alternativa
puoi aprire `viewer/index.html` direttamente e trascinare i file: sessione `.json.gz`, struttura, modello e `.bin`.
In alto a destra si sceglie il tema: **automatico** (segue il sistema), **chiaro** o **scuro**. La scelta resta salvata in
quel browser e vale per tutte le schede, compreso lo schema del software; l'SVG scaricato è sempre chiaro.

La linea del tempo in basso, le frecce (Maiusc = 1 s) e la barra spaziatrice muovono il cursore, che è comune a
tutte le schede. In alto scegli il giro, i parametri del modello (per esempio il livello) e le due mappe:

- **A = riferimento**, per esempio la NOSLICK montata in moto;
- **B = confronto**, per esempio la SLICK. Le modifiche si fanno su una copia di lavoro di B; il file B su disco non cambia.

Ogni mappa caricata è riconosciuta dalla sua impronta sha256 (o dal nome) fra le `varianti` della struttura. La
catena viene ricalcolata con A e con B sulla stessa acquisizione; nella linea del tempo gli interventi di A sono in
rosso e quelli di B in arancio. In *Criteri e rami* la **concordanza** con il canale CAN della centralina dice quale
delle due era davvero montata (demo: NOSLICK 95%, SLICK 36%).

- **Acquisizione**: canali nel tempo (stessa unità = stesso grafico), pista ricostruita con il punto attuale, interventi evidenziati.
- **Criteri e rami**: per ognuno dei criteri valore, soglia, misuratore con isteresi e distanza dalla soglia (in unità e in % della soglia). Mostra i rami con i termini veri/falsi, cosa manca perché un ramo lavori, la logica e l'uscita. Confronta la previsione con ciò che la centralina ha fatto davvero (canale CAN osservato). Grafici della distanza normalizzata e statistiche per giro, originale → modificata.
- **Trigger per ramo**: per ogni ramo una scheda con lo stato, la distanza del ramo intero dal suo trigger (il termine più lontano) e, per il criterio a derivata, valore, soglia, quanto manca e a che velocità ci si avvicina, con la stima del tempo al trigger. Sotto ci sono, per ramo, la distanza nel tempo, il minimo ogni 10 m lungo il giro (dove ci si avvicina, giro per giro) e una tabella per giro con scatti, durata e punto più vicino (clic = vai all'istante). Il criterio a derivata è quello con `"derivata": true` nel modello, oppure con un blocco «derivata» a monte del valore.
- **Tabelle dal vivo** (vista compatta, alternativa allo schema): una finestra per ogni lookup table letta dal programma dei controlli, con i parametri attuali (per esempio la soglia del livello 2). Mentre ripercorri il giro (▶, frecce, trascinando la linea del tempo) mostra:
  - le 4 celle che la centralina sta interpolando, colorate in proporzione al peso;
  - i valori d'asse evidenziati e il mirino sul punto esatto;
  - la scia degli ultimi secondi e il valore in uscita;
  - l'avviso «saturato» quando l'ingresso esce dall'asse.

  Le finestre del ramo che sta lavorando sono bordate di rosso, quelle dei rami fermi si attenuano. Si può chiedere di vedere solo le tabelle del ramo attivo. A sinistra ci sono lo stato di logica, rami e criteri (quanto manca alla soglia) e la finestra *Misure* con tutte le grandezze della catena. Lo sfondo delle celle può essere il valore, *dove lavora nel giro* oppure la differenza B − A. Calcolo con A o con B a scelta.
- **Schema software**: lo schema a blocchi della centralina dei controlli nello stile degli SVG del flusso del software, cioè corsie verticali (Bus CAN, Ingressi, Condizionamento, Mappe e curve, Criteri, Rami e logica, Uscite verso il motore), blocchi con la barra colorata della corsia e connessioni curve. Le lookup table sono **espanse dentro lo schema**, su fondo giallo come nello schema Simulink, con le celle colorate per valore. All'istante del cursore:
  - il **ramo che lavora** e tutto ciò che lo alimenta è disegnato come bus rosso spesso, i rami fermi restano grigi;
  - in ogni tabella le **celle che la centralina sta leggendo** sono in arancio, in proporzione al peso, con mirino e scia;
  - i criteri mostrano valore, soglia e una barra con la soglia.

  Un clic su un blocco traccia a monte fino al segnale CAN, con la sequenza dei passi. Un doppio clic su una tabella la apre in *Mappe*. *Scarica SVG* salva lo schema di quell'istante. Le corsie si possono assegnare a mano con `"corsia"` nei blocchi e `"corsie"` nel modello.
- **Mappe**: elenco con le tabelle *in uso* con i parametri attuali, *≠ A* e *✎ modificata*. Viste valori, differenza B − A, *dove lavora* (percentuale di tempo per cella nel giro scelto) e superficie 3D. Il punto di lavoro al cursore ha una scia di 3 s. Puoi modificare (imposta, somma, %, interpola, liscia, riporta all'originale, annulla, punti trascinabili sulle curve) e i criteri si ricalcolano subito sulla stessa acquisizione. Esporti il `.bin` con il checksum corretto oppure una patch `.json`.
- **Profilo pneumatico**: raggio di rotolamento in funzione della piega (originale/modificato), sezione della gomma ricostruita dal profilo con il punto di contatto alla piega del cursore, correzione della velocità ruota, effetto della modifica sullo slittamento calcolato e generatore toroidale. C'è anche la **verifica sul registrato**: in rilascio lo slittamento corretto dovrebbe stare a zero a ogni piega. Se cresce con la piega, il profilo in tabella non è quello della gomma montata.
- **Giri**: tempi, distacchi, sovrapposizione per distanza e distacco lungo il giro, con le fasce delle curve.

**Livelli della moto (potenza, TC, SCS, AW, freno motore).** Ogni livello è un parametro del modello, legato al suo
canale CAN: sulla Ducati TC = DTC, SCS = DSC e AW = DWC (0x018, con il bit di spento), freno motore = EBC (0x190) e
potenza = Power Mode (0x080). In alto c'è un menu per livello:
- **dal CAN** (predefinito): la catena usa il livello registrato istante per istante, quindi se in pista cambi il TC da 2 a 3 il ricalcolo lo segue. Il menu mostra i valori trovati, per esempio «dal CAN (2→3)»;
- **un numero**: fissa quel livello per tutta la sessione, per vedere sullo stesso giro cosa avrebbe fatto la centralina con un altro livello.

I livelli in uso all'istante del cursore sono nella barra in basso. Se le tabelle cambiano con il livello, nel modello
il nome ha il segnaposto, per esempio `CRIT1_SOGLIA_TC{tc}`. In *Mappe*, *Schema software* e *Tabelle dal vivo* compare
la tabella del livello di quell'istante: *in uso ora* è quella letta adesso, *in uso* una letta in un altro momento del
giro. Un livello senza tabella, per esempio 0 = spento, non fa intervenire quel ramo.

**In che giro e in che curva sono.** La barra in basso dice sempre giro, curva, fase e metri dal traguardo, per esempio
`giro 3 · T4 sinistra · ingresso, apice fra 30 m · 1084 m`, oppure `rettilineo → T5 fra 210 m`. Le curve sono
riconosciute dal giro modello: tratti con piega oltre 12°, con la velocità minima se manca la piega. Sono numerate dal
traguardo T1, T2… con verso, apice, piega massima e velocità minima.
- In alto, *vai alla curva…* porta il cursore all'apice di quella curva nel giro scelto.
- Sulla mappa della pista, la curva in cui sei è evidenziata. Un clic sull'etichetta le dà un nome (es. Curva Grande); un clic sulla pista porta lì il cursore.
- *copia i nomi per il profilo* produce la voce `"curve": {"nomi": [...]}` da incollare nel profilo, così i nomi valgono su tutti i PC.
- I numeri delle curve compaiono anche sopra i grafici nel tempo, all'istante dell'apice, giro per giro. Sui grafici per distanza compaiono come fasce.
- In *Trigger per ramo* c'è la tabella *Per curva*: quante volte scatta ogni ramo in ogni curva e quanto ci si avvicina al trigger della derivata.

In `profilo_ducati_v4.json`, `curve.piega_positiva` dice se la piega positiva sul CAN è a destra o a sinistra. È da
verificare al primo turno: Vallelunga si gira in senso orario, quindi la maggior parte delle curve è a destra.
- **Protocollo CAN**: esito, origine di ogni canale, integrità contatore/CRC, messaggi attesi, ID sconosciuti, controlli fisici.

## 6. Struttura e modello della centralina (da compilare con la decodifica)

Gli strumenti non contengono la decodifica della centralina: la leggono da due file JSON in `privato/`.

- `esempi/struttura_da_compilare.json` → `privato/struttura.json`: per ogni tabella indirizzo, tipo di dato, endianità, scala, dimensioni e assi; poi le regole di checksum e quali tabelle sono profili pneumatico. In `varianti` vanno le mappe (NOSLICK, SLICK) con lo sha256 del file. Se in una mappa una tabella sta altrove, l'indirizzo si scrive per variante: `"indirizzo": {"NOSLICK": "0x…", "SLICK": "0x…"}`. I comandi `calib` riconoscono la variante dall'impronta del file oppure con `--variante`.
- `esempi/modello_da_compilare.json` → `privato/modello.json`: la catena a blocchi (filtri, lookup, espressioni), i 4 criteri (valore, confronto, soglia, isteresi), i rami, la logica e i canali CAN da confrontare.

Gli indirizzi nei modelli sono segnaposto. I file vanno compilati sul PC di casa con il materiale della
decodifica. Controlli dopo la compilazione:

```
py -m dvtool calib elenco   --struttura privato\struttura.json --bin privato\calibrazioni\noslick.bin
py -m dvtool calib confronta --struttura privato\struttura.json --bin noslick.bin --altro slick.bin   (tabelle diverse fra le due mappe)
py -m dvtool calib checksum --struttura privato\struttura.json --bin privato\calibrazioni\originale.bin   (sull'originale deve dare OK)
py -m dvtool calib cerca-checksum --struttura privato\struttura.json --bin originale.bin --da 0x... --a 0x...   (se la regola non è nota)
```

L'esempio completo e funzionante di entrambi i formati è in `esempi/demo/` dopo `dvtool demo`
(`struttura_demo.json`, `modello_demo.json`).

### Modifiche alla centralina

- Lavora sempre su una copia; l'originale resta com'è (il visualizzatore modifica solo la *copia di lavoro*).
- `py -m dvtool calib applica --struttura ... --bin originale.bin --patch patch.json --out modificato.bin` riscrive le tabelle, corregge e verifica il checksum, avvisa se il file di partenza non è quello della patch e dice quali celle sono state saturate.
- `calib confronta` elenca tabella per tabella cosa è cambiato e le **regioni cambiate fuori dalla struttura** (devono essere zero).
- Senza una regola di checksum verificata sull'originale il file non è pronto da scrivere in centralina, e gli strumenti lo dicono.
- Il controllo in piega agisce sulla trazione in curva: prova le modifiche per gradi, in pista, rifacendo l'acquisizione e confrontando originale → modificata nella scheda *Criteri e rami*.

## 7. Prove automatiche

```
python -m unittest discover -s tests      (14 prove: DBC Intel/Motorola, frame reali SFV4 e CRC-8, formati log,
                                          giri senza GPS, checksum, patch, varianti NOSLICK/SLICK, modello,
                                          demo fine-a-fine, parità del motore JavaScript con quello Python via node)
```

## Struttura

```
dvtool/            pacchetto Python (cli, canlog, dbc, laps, model, calib, checksum, protocollo, sessione,
                   cronometro, registratore_can, pacchetto, server, synth)
viewer/            visualizzatore (index.html, js/, style.css, lib/uPlot)
esempi/            profilo Ducati V4, modelli da compilare, raccolta per il trasferimento
privato/           (ignorata da git) dati veri
tests/             prove
guida.bat                    la Guida (doppio clic)
dvtool.bat, visualizza.bat   avvio rapido su Windows
```
