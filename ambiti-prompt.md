Sei un giurista svizzero esperto della Raccolta sistematica del diritto federale (RS, Fedlex). Ti chiedo di preparare
l'elenco degli **ambiti del diritto** che un assistente legale (Ugo, del servizio Anorma) usa per capire quali materie
tocca la domanda di un utente comune, prima di cercare nelle leggi.

Un modello AI molto veloce leggerà questo elenco e darà a ogni ambito un punteggio da 0 a 1 per ogni domanda: per
questo nome, descrizione, "non_confondere" ed esempi devono essere chiari a chi non è giurista. I campi successivi li
usa il programma per decidere dove cercare.

## Materiale allegato
Il file `ambiti-materiale.txt` elenca le leggi federali in vigore che l'archivio contiene davvero, raggruppate per
prefisso RS di 3 cifre, con i titoli degli atti principali. **Usa solo numeri RS che compaiono lì.** Non inventare
numeri: se un atto che ti serve non c'è, scrivilo nel campo "note" invece di inventarne il numero.

## Cosa produrre
Un unico array JSON valido (niente testo prima o dopo, niente commenti), con **almeno 70 ambiti** in italiano:
- tutti i rami della RS interna (1 Stato, 2 Diritto privato, 3 Diritto penale, 4 Scuola e cultura, 5 Difesa,
  6 Finanze, 7 Lavori pubblici, energia e trasporti, 8 Sanità, lavoro, sicurezza sociale, 9 Economia), suddivisi al
  livello utile per un utente comune (di solito 2 o 3 cifre: es. 741 Circolazione stradale, non tutto il ramo 7);
- per i rami molto usati dalla gente, suddivisioni più fini: ad esempio nel diritto privato separa locazione,
  contratto di lavoro, compravendita, famiglia e divorzio, successioni, proprietà e vicinato, responsabilità civile
  e risarcimento, esecuzione e fallimento; nella sicurezza sociale separa AVS, AI, prestazioni complementari,
  previdenza professionale, assicurazione malattie, infortuni, disoccupazione, assegni familiari;
- almeno questi ambiti trasversali, che nella RS non stanno in un solo posto: "diritto cantonale ticinese",
  "responsabilità civile e risarcimento", "procedura e termini per difendersi (ricorsi, opposizioni, prescrizione)",
  "protezione dei dati", "diritto dei consumatori", "diritto UE che vale in Svizzera".

## Campi di ogni ambito
| campo | obbligatorio | contenuto |
|---|---|---|
| id | sì | breve, minuscolo, con trattini, unico (es. "circolazione-stradale") |
| nome | sì | nome dell'ambito in italiano |
| descrizione | sì | 10-25 parole di tutti i giorni: cose, situazioni e persone tipiche (non termini tecnici) |
| non_confondere | sì | elenco, anche vuoto, di parole ambigue con l'ambito giusto (es. "cartelli tra imprese: concorrenza") |
| esempi | sì | 2 o 3 domande brevi come le scriverebbe un utente comune |
| rs | sì | prefissi RS dove cercare (es. ["741"]); solo prefissi presenti nel materiale |
| atti | sì | 1-5 numeri RS degli atti principali, presi dal materiale |
| livelli | sì | tra "federale", "cantonale", "comunale" |
| prassi | no | autorità che pubblicano direttive o circolari (es. "USTRA", "UFAS", "SECO", "AFC", "FINMA") |
| squadre | sì | tra "federale", "cantone", "giurisprudenza", "parlamento", "prassi", "ue" |
| collegati | sì | id di 2-5 altri ambiti che escono spesso insieme a questo (devono esistere nell'elenco) |
| padre | sì | id del ramo superiore, oppure null per i 9 rami principali |
| soglia | no | punteggio minimo per entrare, predefinito 0.4 |
| note | no | dubbi o atti mancanti dal materiale |

Includi anche i 9 rami principali come ambiti (con padre null), così il punteggio si può dare prima ai rami e poi alle
foglie.

## Esempio di un ambito (formato esatto)
```json
{"id": "circolazione-stradale", "nome": "Circolazione stradale",
 "descrizione": "auto, moto, bici, monopattini, patente, multe, incidenti, segnali e cartelli stradali, parcheggi, controlli della polizia",
 "non_confondere": ["cartelli tra imprese: concorrenza"],
 "esempi": ["Cosa rischio se guido dopo aver bevuto?", "Posso portare a casa un cartello stradale trovato a terra?",
            "Mi hanno ritirato la patente: posso ricorrere?"],
 "rs": ["741"], "atti": ["741.01", "741.11", "741.21"], "livelli": ["federale", "cantonale"],
 "prassi": ["USTRA"], "squadre": ["federale", "cantone", "giurisprudenza"],
 "collegati": ["responsabilita-civile", "assicurazioni-private", "diritto-penale", "strade-nazionali"],
 "padre": "trasporti", "soglia": 0.4}
```

## Controlli prima di consegnare
- almeno 70 ambiti, id tutti diversi;
- ogni numero in "rs" e "atti" compare nel materiale allegato;
- ogni id in "collegati" e "padre" esiste nell'elenco;
- descrizioni in parole semplici, senza sigle non spiegate;
- JSON valido: un solo array, virgolette doppie, nessuna virgola finale.
