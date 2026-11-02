# Nuova-Norma: agente di ricerca giuridica su fonti ufficiali svizzere

Un archivio versionato del diritto federale (da Fedlex) e un agente che fa ricerca solo in fonti ufficiali: Fedlex (RS, RU, FF), consultazioni federali, Parlamento (Curia Vista), Tribunale federale, Raccolta delle leggi del Canton Ticino. Ogni affermazione cita la fonte letta.

Nessuna dipendenza esterna obbligatoria: serve solo Python 3.10 o più recente (per i PDF ticinesi: `py -m pip install pypdf`). I dati restano sul tuo computer, nella cartella `data/`.

## Fonti ufficiali

L'elenco dei domini ammessi è chiuso e sta in `nn/sources.py`: una richiesta verso qualsiasi altro dominio viene rifiutata prima di partire.

| Fonte | Autorità | Cosa offre all'agente |
| --- | --- | --- |
| Fedlex (SPARQL + XML) | Cancelleria federale | ricerca leggi per titolo, import automatico, versioni future, pubblicazioni RU/FF, consultazioni |
| Curia Vista (OData) | Servizi del Parlamento | oggetti parlamentari, testi e risposte del Consiglio federale, votazioni in Consiglio |
| OpenCaseLaw (API pubblica) | progetto indipendente: copia delle sentenze pubblicate dai tribunali (CC0) | sentenze di tutti i tribunali federali e dei 26 cantoni dal 1875, grafo delle citazioni, commentari aperti (CC-BY, livello dottrina); le sentenze aperte entrano nell'archivio |
| bger.ch | Tribunale federale | ricerca a testo pieno in "Tutte le sentenze" e nelle DTF, testo delle decisioni |
| m3.ti.ch | Cancelleria dello Stato (TI) | Raccolta delle leggi: indice locale e testo degli atti (PDF) |

Per provare ogni fonte senza chiavi:

```
py -m nn verifica-fonti
py -m nn indicizza-ticino      # una volta: costruisce l'indice delle leggi ticinesi
```

### Fonti documentali (archivio comune con versioni)

Oltre alle leggi, Nuova-Norma archivia documenti che spiegano come le autorita applicano il diritto. Ogni fonte ha un **livello**, che l'agente dichiara sempre: una direttiva non viene mai presentata come legge.

| Fonte (`id`) | Autorita | Livello | Cosa contiene |
| --- | --- | --- | --- |
| `ticino` | Cancelleria dello Stato | legge | testo di ogni atto della Raccolta ticinese, con versioni |
| `ufas` | Ufficio federale delle assicurazioni sociali | prassi | direttive e circolari su AVS, AI, IPG, PC, previdenza professionale, assegni familiari, prestazioni transitorie (se manca l'italiano: francese o tedesco, dichiarato) |
| `promemoria` | Centro d'informazione AVS/AI | informativo | promemoria aggiornati ogni anno, con gli importi |
| `cavpp` | Commissione di alta vigilanza della previdenza professionale | prassi | direttive e comunicazioni (molti PDF solo in francese, dichiarato) |
| `ufsp` | Ufficio federale della sanita pubblica | prassi | circolari agli assicuratori malattia e infortuni |
| `seco_ladi` | SECO | prassi | Prassi LADI e direttive sulla disoccupazione |
| `seco_ll` | SECO | prassi | indicazioni sulla legge sul lavoro e sulle ordinanze 1-5, anche per articolo |
| `afc` | Amministrazione federale delle contribuzioni | prassi | circolari su imposta federale diretta, imposta preventiva, tasse di bollo; progetti di prassi IVA |
| `sem` | Segreteria di Stato della migrazione | prassi | istruzioni e circolari su stranieri, libera circolazione, asilo |
| `seco_oip` | SECO | prassi | guide sull'indicazione dei prezzi (OIP), per settore |
| `ufcom` | Ufficio federale delle comunicazioni | prassi | prescrizioni tecniche e amministrative (RS 784.101.113/x) |
| `comcom` | Commissione federale delle comunicazioni | decisione | decisioni dal 1998 |
| `comco` | Commissione della concorrenza | decisione | raccolta DPC dal 1997 e decisioni recenti |
| `elcom` | Commissione federale dell'energia elettrica | prassi / decisione | istruzioni, comunicazioni, decisioni |
| `ufam` | Ufficio federale dell'ambiente | prassi | aiuti all'esecuzione (elenco cronologico completo) |
| `swissmedic` | Swissmedic | prassi | guide e promemoria su medicamenti e dispositivi medici |
| `eurlex` | Ufficio delle pubblicazioni dell'UE (CELLAR) | diritto_ue | GDPR, AI Act, DSA, DMA, Data Act, ePrivacy, NIS 2, eIDAS, consumatori, accessibilita, Roma I, Bruxelles I bis, IDD, Solvibilita II, MiFID II, PSD2, reg. 883/2004 e 987/2009 (versione consolidata piu recente in italiano) |
| `ombudsman` | Ombudsman dell'assicurazione privata (fondazione privata) | privato | casi esemplari e rapporti annuali |
| `ifpdt` | Incaricato federale della protezione dei dati | prassi | pagine del sito (FAQ, temi), guide, decisioni, raccomandazioni |
| `finma` | FINMA | prassi | circolari: archivio per anno; quelle in vigore se leggibili senza JavaScript |
| `votazioni` | Ufficio federale di statistica | dati | ogni votazione federale dal 1848, risultato nazionale e per cantone |

```
py -m pip install pypdf          # una volta: serve per i PDF
py -m nn verifica-raccolte       # prova ogni lettore senza toccare l'archivio, e controlla i robots.txt
py -m nn aggiorna-raccolte       # scarica tutto cio che manca o e cambiato (tutte le fonti)
py -m nn aggiorna-raccolte ufas promemoria --limite 20   # solo alcune fonti, al massimo 20 documenti ciascuna
py -m nn stato-raccolte          # documenti, versioni e ultimo controllo per fonte
```

Regole dell'archivio: ogni file si conserva in `data/raw/` con il nome della sua impronta SHA-256 e non si sovrascrive; un'impronta nuova e una versione nuova, con la data dichiarata dalla fonte ("Stato al", "valida dal"); un documento che la fonte non elenca piu resta in archivio, marcato "non piu pubblicato". Si rispetta il `robots.txt` di ogni sito, e un reindirizzamento verso un dominio fuori elenco viene rifiutato.

Fonti studiate ma non ancora collegate (la verifica ne controlla il robots.txt): sentenze ticinesi (sentenze.ti.ch), Istituto delle assicurazioni sociali e Divisione delle contribuzioni (www4.ti.ch), Tribunale penale e Tribunale amministrativo federale (API Weblaw non documentate), FUSC e Foglio ufficiale ticinese (amtsblattportal.ch), pubblicazioni IVA in vigore, dati sui premi LAMal, simap, Zefix (credenziali gratuite su richiesta a zefix@bj.admin.ch), LexFind (nessuna condizione d'uso pubblica).

Livelli: `legge`, `giurisprudenza`, `parlamento`, `prassi` (vincola l'amministrazione, non i tribunali), `decisione` (caso singolo di un'autorita), `informativo`, `dati`, `diritto_ue` (in Svizzera vale solo se richiamato da un accordo o dal diritto svizzero, o per chi opera nell'UE), `privato`.

Non collegate anche: Sorveglianza dei prezzi (elenchi paginati con JavaScript), banca dati delle decisioni UFCOM (applicazione JavaScript), giurisprudenza amministrativa federale GAAC (ferma al 2017, all'Archivio federale).

Escluse per scelta: i PDF della Suva (esclusi dal suo robots.txt) e le raccomandazioni della commissione ad hoc LAINF su koordination.ch (il sito vieta espressamente l'estrazione di testi e l'uso da parte di AI).

### Leggi federali in blocco

```
py -m nn importa-pacchetto                 # elenco dei pacchetti
py -m nn importa-pacchetto sociali         # AVS, AI, IPG, PC, LPP, LAMal, LAINF, LADI, assegni familiari
py -m nn importa-pacchetto anorma          # LPD, OPDa, CO, LCSl, OIP, LTC... (privacy policy, CG, e-commerce)
py -m nn importa-catalogo --solo-elenco    # tutta la Raccolta sistematica in vigore: cosa importerebbe
py -m nn importa-catalogo --prefisso 8 --limite 50   # un settore (RS 8: sanita, lavoro, sicurezza sociale), 50 atti per volta
```

`importa-catalogo` riprende da dove si era fermato: gli atti gia in archivio si saltano (con `--aggiorna` si ricontrollano le versioni nuove).

Per provare su una copia dell'archivio: `set NN_DB=C:\percorso\copia.sqlite` (e `NN_RAW` per i file originali).

Nota sul Tribunale federale: il sito non ha un'API e il suo `robots.txt` scoraggia l'accesso automatico. Nuova-Norma lo interroga solo su richiesta esplicita, con pause tra le richieste. Il lettore delle pagine è tollerante ma va confermato alla prima esecuzione reale.

## Rapporti di ricerca

```
py -m nn rapporto "Cosa deve rispettare un e-commerce in Ticino?"
```

Salva risposta, fonti e ricerche eseguite in `data/rapporti/<data>-<titolo>.md`.

## Installazione su Windows

1. Installa Python da [python.org](https://www.python.org/downloads/), oppure da PowerShell:
   ```
   winget install Python.Python.3.12
   ```
2. Apri PowerShell nella cartella `nuova-norma`.

## Interfaccia

```
py -m nn sito
```

Si apre il browser su `http://127.0.0.1:8765`. Da lì si importano gli atti, si sfogliano le versioni, si leggono gli articoli con la loro storia e si vedono le differenze evidenziate. L'interfaccia è raggiungibile solo dal tuo computer. Per chiuderla: `Ctrl+C` in PowerShell.

## Agente AI ("Chiedi")

Risponde a domande consultando le fonti ufficiali: prima l'archivio locale, poi Fedlex (importando da solo le leggi che mancano), Parlamento, consultazioni, Tribunale federale e diritto cantonale. Cita la fonte per ogni affermazione. Le citazioni sono link alla pagina dell'articolo; una citazione che non corrisponde a nessun articolo in archivio viene segnalata come "non verificato".

Due fornitori, scelti con `NN_PROVIDER` nel file `.env`:

- `infomaniak` (predefinito): server in Svizzera, solo modelli sviluppati in Europa (Mistral AI, Swiss AI Initiative). Il blocco è nel codice: un modello di altra origine viene rifiutato prima di inviare qualsiasi dato.
- `openai`: soluzione temporanea, server negli Stati Uniti. La pagina "Chiedi" lo segnala in alto.

Per controllare la configurazione senza mostrare la chiave:

```
py -m nn verifica-ai
```

Configurazione:

1. Copia `env-esempio.txt` in un nuovo file chiamato `.env` (stessa cartella).
2. Scegli il fornitore (`NN_PROVIDER`) e inserisci la sua chiave: `INFOMANIAK_API_TOKEN` e `INFOMANIAK_PRODUCT_ID`, oppure `OPENAI_API_KEY`.
3. Apri il sito e vai su "Chiedi", oppure:
   ```
   py -m nn chiedi "Per quanto tempo devo conservare le fatture?"
   ```

Il file `.env` contiene il token: resta solo sul tuo computer ed è escluso da git.

## Riga di comando

```
py -m nn importa 235.1                 # nLPD in italiano, tutte le versioni XML
py -m nn importa 235.1 --lingua de     # stessa legge in tedesco
py -m nn versioni 235.1
py -m nn differenze 235.1              # ultime due versioni
py -m nn differenze 235.1 --da 2023-09-01 --a 2024-01-01
py -m nn articolo 235.1 "Art. 6"
```

Nell'output delle differenze, le parole tolte sono tra `[- -]` e quelle aggiunte tra `{+ +}`.

Si può importare qualsiasi atto della RS indicandone il numero (es. `220` per il Codice delle obbligazioni) oppure l'URI Fedlex completo.

## Test

```
py -m unittest -v tests.test_nn tests.test_agent tests.test_fonti tests.test_formati tests.test_raccolte
```

I test non usano la rete: simulano Fedlex con XML di esempio.

## Come funziona

| File | Ruolo |
| --- | --- |
| `nn/fedlex.py` | Query SPARQL a `fedlex.data.admin.ch` e download dei file, con pause tra le richieste |
| `nn/akn.py` | Lettura dell'XML Akoma Ntoso: atto, capitoli, articoli, note |
| `nn/store.py` | Archivio SQLite: atti, versioni, articoli |
| `nn/web.py` | Interfaccia web locale |
| `nn/agent.py` | Agente: 22 strumenti sulle fonti, ciclo di ricerca, citazioni |
| `nn/sources.py` | Registro delle fonti ufficiali, allowlist dei domini, accesso HTTP con pause |
| `nn/parlamento.py` | Curia Vista (OData) |
| `nn/giurisprudenza.py` | Tribunale federale (lettura delle pagine di ricerca) |
| `nn/cantoni.py` | Canton Ticino: esplorazione, indice locale, testo degli atti |
| `nn/ai.py` | Client Infomaniak (con blocco dei modelli non europei) e OpenAI, diagnosi |
| `nn/documenti.py` | Archivio comune delle fonti documentali: versioni con impronta, date dichiarate, ricerca |
| `nn/raccolte.py` | Lettori delle fonti documentali (21 fonti) e lettore comune per i siti della Confederazione |
| `nn/eurlex.py` | Diritto UE dall'archivio CELLAR: atti selezionati, versioni consolidate |
| `nn/pacchetti.py` | Gruppi di leggi federali da importare in blocco |
| `nn/diff.py` | Confronto tra versioni: articoli aggiunti, abrogati, modificati, parola per parola |
| `data/raw/` | File originali, nominati con la loro impronta SHA-256: non vengono mai sovrascritti |

Le note a piè di pagina di Fedlex (riferimenti RU) restano fuori dal testo dell'articolo e sono salvate a parte. Così un articolo non risulta modificato solo perché è cambiata una nota.

## Limiti noti

- Fedlex pubblica l'XML solo per le versioni dal 2022 in poi. Le versioni più vecchie esistono solo in PDF/HTML e saranno un passo successivo.
- Il primo import su dati reali serve anche a verificare il parser: se qualcosa non torna, l'output va condiviso per correggerlo.
