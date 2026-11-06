# privato/

Qui vanno i file che **non** devono finire nel repository (che è pubblico):
DBC della moto, file della centralina (.ORI/.bin), struttura e modello compilati, acquisizioni, token.

Struttura consigliata (la crea `pacchetto apri`):

    privato/can/            DBC (SFV4_bus_practical.dbc, SFV4_ECU_reconstructed.dbc, ...)
    privato/calibrazioni/   originale e modificati
    privato/decodifica/     materiale della decodifica dal PC di casa
    privato/acquisizioni/   catture scaricate dal cronometro
    privato/progetto/       progetto.json + sessioni + struttura + modello per il visualizzatore
    privato/cronometro.json configurazione delle scatole (facoltativa)
