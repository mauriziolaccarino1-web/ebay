# Passaggio a Claude Code: verifiche iniziali

Documento per la sessione di Claude Code che fa le prime verifiche, sul PC di casa (raggiungibile solo con AnyDesk
o con Claude Code in Remote Control) e poi sul PC di lavoro. Il contesto completo è nel README.

## Situazione

- Moto: Ducati Panigale V4 R 2025. La logica dei controlli sta nella **centralina dei controlli** (software
  Divac Pro, pensato per le slick). Verso la centralina motore manda le richieste di coppia su 0x019.
- Mappe da confrontare: **NOSLICK** e **Divac Pro**. Livelli selezionabili sulla moto: potenza, TC (DTC),
  SCS (DSC), AW (DWC) e freno motore (EBC).
- Registratore: la scatola H3D Chrono della **R9** (`r9-yccu`, Pi Zero 2 W, utente `yccu`, USB 169.254.55.1,
  bus `can1` sul morsetto `spi1.1`). La CM4 è servita solo per la prova sulla Streetfighter del 31/10. Sulla R9
  candump non c'è: registra `registratore_can.py`, che su una scatola vera non ha ancora mai girato.
- Prima prova in pista: Vallelunga.
- Si presume che il protocollo sia quello della Streetfighter V4S 2023: 500 kbit/s, ID a 11 bit, contatore in
  B6[3:0] e CRC-8 SAE J1850 in B7. Ruote, piega e TrqSlow/TrqFast **non sono mai stati verificati in moto**.
- Sul PC di casa ci sono la decodifica della centralina (BBSV4, materiale in `%USERPROFILE%\Desktop\claude\filippo\ducati\`),
  il protocollo SFV4 (`...\filippo\SFV4_23\can\`) e la cattura SFV4 del 31/10
  (`D:\h3d_note\sfv4_2023\catture\cattura_20261031_172807.log`, 94 MB).

## Regole per la sessione

1. **Il repository è pubblico.** Non fare mai commit di niente che stia in `privato\`: DBC, file `.bin`/`.ORI`, struttura e modello compilati, catture, chiavi, password.
2. **La scatola della R9 non va modificata.**
   - Niente installazioni, niente modifiche a `/home/yccu/projects/yccu-peer`, nessun servizio disattivato.
   - Si usano solo le operazioni di `dvtool cronometro` o della Guida.
   - SSH verso la scatola solo quando Maurizio lo chiede.
3. **Registra (listen-only) solo con la scatola sulla Ducati, mai sulla R9.** La centralina R9 vuole l'ACK della scatola.
4. **Nessuna trasmissione sul CAN** e nessuna scrittura in centralina. I file per la centralina si preparano solo
   con la Guida o con `calib applica`, solo se il checksum risulta OK sul file originale. Gli originali non si modificano mai.

## A. PC di casa (via AnyDesk o Claude Code sul PC di casa)

1. **Strumenti:**
   `git clone https://github.com/mauriziolaccarino1-web/ebay.git`, poi
   `git checkout claude/ducati-420-25-divac-analysis-v5qwmk`, poi `cd ducati_v4`.
   In alternativa scarica lo zip del ramo. Poi `py -m pip install numpy` e `py -m unittest discover -s tests`, che deve dare OK.
2. **DBC ricostruiti:** estrai `ducati_v4_privato_dal_cloud.zip` dentro `privato\`. Lo zip è nella conversazione con Claude da cui viene questo documento.
3. **Verifica offline sulla cattura SFV4**, sicura perché non tocca niente:
   ```
   dvtool.bat can verifica D:\h3d_note\sfv4_2023\catture\cattura_20261031_172807.log --dbc privato\can\SFV4_bus_practical.dbc --profilo esempi\profilo_ducati_v4.json --out verifica_sfv4.md
   ```
   Atteso: contatore e CRC-8 corretti su tutti gli ID della centralina tranne 0x360, come il 31/10. Qualche frame
   perso, perché l'MCP2515 va in overflow a questo carico. È la prova che lettore e DBC sono giusti prima di passare alla Panigale.
4. **Struttura e modello:** dal materiale della decodifica compila `esempi\struttura_da_compilare.json` in
   `privato\struttura.json` e `esempi\modello_da_compilare.json` in `privato\modello.json`.
   - **Struttura:** le varianti NOSLICK e DIVAC con lo sha256 dei due file, le tabelle dei 4 criteri con assi e
     scala, i profili pneumatico e la regola di checksum.
   - **Modello:** la catena dei 4 criteri, i rami e i 5 livelli legati ai canali CAN del profilo. Il criterio sulla
     derivata di potenza va marcato con `"derivata": true`.
   - **Verifiche:**
     ```
     dvtool.bat calib elenco   --struttura privato\struttura.json --bin <file>
     dvtool.bat calib checksum --struttura privato\struttura.json --bin <NOSLICK originale>     (deve dare OK)
     dvtool.bat calib checksum --struttura privato\struttura.json --bin <Divac Pro originale>   (deve dare OK)
     dvtool.bat calib confronta --struttura privato\struttura.json --bin <NOSLICK> --altro <Divac Pro>
     ```
     Se il checksum non torna, la regola è sbagliata: `calib cerca-checksum --da --a` sulla regione protetta aiuta a trovarla.
5. **Pacchetto per il PC di lavoro:**
   ```
   dvtool.bat pacchetto crea --raccolta esempi\raccolta_casa.json --out ducati_v4_trasferimento.zip
   ```
   Controlla l'elenco «non trovato» e correggi la raccolta. Aggiungi `privato\struttura.json`, `privato\modello.json`
   e i due file della centralina con i nomi `NOSLICK.bin` e `DIVAC_PRO.bin`, in una sottocartella `calibrazioni`.
6. **Chiave SSH:** trova in `%USERPROFILE%\.ssh\` la chiave con cui questo PC entra nella scatola R9: è la riga
   `IdentityFile` del file `config` sotto l'Host della scatola, altrimenti `id_ed25519` (o `id_rsa`), senza `.pub`.
   Copiala con AnyDesk sul PC di lavoro come `%USERPROFILE%\.ssh\chiave_casa`. Serve solo al punto B3.
7. **Porta sul PC di lavoro** `ducati_v4_trasferimento.zip` (e, se serve per B3, la chiave) con il trasferimento
   file di AnyDesk o con OneDrive.

**Riferimento:** la prova CM4 + Streetfighter V4 2023 del 31/10, con le note in `D:\h3d_note\sfv4_2023\`
(`STATO.md`, `prova_sfv4.sh`, `analisi\cattura_20261031_172807_analisi.md`). Contiene la procedura passiva usata e
riprodotta qui, i 28 campi confermati e i problemi trovati: sentinelle all'accensione, bit DWC off = b5.6, scale AiM
del power mode sfalsate di uno, assi IMU 0x178/0x17C ruotati di circa 56°.

## B. PC di lavoro (Claude Code)

1. **Strumenti come in A1.** Poi, per vedere il visualizzatore, `dvtool.bat demo --apri`.
2. **Dati:** `dvtool.bat pacchetto apri ducati_v4_trasferimento.zip --in privato`, poi estrai lì anche lo zip dei DBC.
   La struttura dei file deve essere `privato\struttura.json`, `privato\modello.json`, `privato\calibrazioni\*.bin` e `privato\can\*.dbc`.
3. **Accesso alla scatola.** La scatola accetta solo chiavi e il PC di casa non la raggiunge, perché la scatola è con te.
   - **Soluzione consigliata:** crea una chiave nuova (`ssh-keygen -t ed25519`, passphrase vuota), poi autorizzala
     con la copia temporanea della chiave di casa (A6), con la scatola via USB o sullo stesso hotspot:
     `dvtool.bat cronometro autorizza --scatola r9 --host <indirizzo> --file %USERPROFILE%\.ssh\id_ed25519.pub --chiave %USERPROFILE%\.ssh\chiave_casa`.
     Poi cancella la copia: `del %USERPROFILE%\.ssh\chiave_casa`.
   - Via wifi l'indirizzo della R9 finisce con .206 e il resto cambia a ogni accensione dell'hotspot: leggilo sul telefono.
   - Su Windows le chiavi private devono avere permessi ristretti (`icacls`), altrimenti OpenSSH le rifiuta.
   - Sulla scatola si aggiunge solo una riga alle chiavi autorizzate.
4. **Guida:** doppio clic su `guida.bat`.
   - **Passo 1:** le voci devono essere tutte verdi, tranne le acquisizioni.
   - **Passo 2, con la scatola collegata via USB**, anche se è ancora montata sulla R9: lettura sola. Atteso:
     hostname `r9-yccu`, `can1` normale e **sul morsetto della moto (`spi1.1`)**, stato dei servizi
     `r9-can-correlation`/`r9-can`, spazio libero, scarto dell'orologio.
   - **Sempre al passo 2, *Prova il registratore*, con la R9 accesa.** Non cambia niente sulla scatola: 20 s di
     lettura di can1 così com'è, senza sudo, con i servizi della R9 accesi. È la prima volta che il registratore
     Python gira su una scatola vera. Annota frame al secondo, frame persi dal registratore, overflow del
     controller e CPU. Se i frame persi non sono zero, il Pi Zero non tiene il passo: dillo prima della Ducati.
5. **Prima prova sulla Ducati, in garage**, con la scatola collegata alla presa CAN della moto. Prima di collegare,
   leggi *Collegamento alla presa della Ducati* nel README: pinout non annotato, 60 Ω, tensioni, ponticello da 120 Ω,
   quadro acceso. Decidi anche come alimentare la scatola: se prende i 12 V dalla moto, a ogni quadro spento si
   riaccende come per la R9 (can1 normale, dà l'ACK); un power bank lo evita. Rifai la stessa sequenza della prova
   CM4 sulla Streetfighter del 31/10, segnando ogni azione con *Segna un momento* (passo 3 della Guida).
   - **Passo 3 della Guida:** password di sudo, poi registra.
   - **Sequenza da segnare:**
     1. quadro acceso, fermo per 40 s;
     2. gas 0 → 100 tre volte;
     3. leva del freno anteriore e pedale del posteriore;
     4. folle → prima;
     5. livelli dal menu: TC, AW, SCS, freno motore, potenza;
     6. motore acceso al minimo;
     7. moto piegata a destra e a sinistra sul cavalletto;
     8. ruota anteriore girata a mano. Il 31/10 gli ultimi due non erano stati fatti: ruote e piega sono ancora da verificare.
   - **Passo 4:** ferma, scarica, rimetti la scatola come per la R9.
   - **Verifica:**
     ```
     dvtool.bat can verifica privato\acquisizioni\<cattura>.log --dbc privato\can\SFV4_bus_practical.dbc --profilo esempi\profilo_ducati_v4.json --out verifica_ducati.md
     ```
   - **Atteso:**
     - stessi ID della SFV4 con contatore e CRC-8 corretti;
     - giri e marcia plausibili;
     - `dtc_livello` e `dwc_livello` che cambiano quando li cambi tu;
     - piega con il segno giusto: annota se a destra è positiva, serve per `curve.piega_positiva` nel profilo;
     - `v_ant` diversa da zero quando giri la ruota.
     Annota nel profilo (campo `verificato`) cosa risulta confermato e correggi quello che non torna.
6. **Poi in pista:** passi 3 e 4 a ogni turno, passo 5 per riguardare. Il passo 6 serve solo dopo una modifica,
   con struttura e checksum verificati.

## Cosa riportare alla fine delle verifiche

`verifica_sfv4.md`, `verifica_ducati.md` e l'elenco dei canali confermati o da correggere nel profilo. Poi:
- l'esito di *Prova il registratore* sulla R9 (frame/s, persi, overflow, CPU) e lo stesso dato letto da
  *Controlla che stia registrando* sulla Ducati;
- il segno della piega;
- i valori dei livelli letti, confrontati con quelli impostati sul cruscotto;
- l'esito di `calib checksum` sui due originali.
