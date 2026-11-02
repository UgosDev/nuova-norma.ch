"""Ricerca preparata: prima che una squadra parta, l'archivio propone gli articoli candidati.

Unisce la ricerca testuale (FTS5) e, se disponibili, i vettori (nn.vettori) con la fusione per rango reciproco:
un articolo trovato da entrambe sale in cima. Costa millisecondi e nessuna chiamata al modello; la squadra riceve i
candidati nel primo messaggio e conserva tutti i suoi strumenti per cercare altro.
"""

from __future__ import annotations

import re
import sqlite3

from . import store, vettori

# parole frequenti nelle domande che non aiutano a trovare l'articolo
VUOTE = set("""
che chi cosa come quando dove perche quale quali quanto quanti sono essere stato stata posso puo possono devo deve
devono fare fatto fatta della delle dello degli dei del dal dalla dalle dagli con per tra fra una uno nel nella nelle
negli sul sulla sulle sugli anche ancora gia solo questo questa questi queste quello quella quelli quelle mio mia miei
mie suo sua suoi sue loro nostro nostra hanno avere aveva avevo dopo prima sempre mai molto poco tutto tutti tutte
caso modo cui non piu svizzera svizzero vale valgono diritto regola regole legge norma norme articolo articoli
può puo mentre posso voglio vorrei devo dovrei sapere come mai ancora cosa ecco mio mia miei mie ora oggi
""".split())

# parole di tutti i giorni -> termini dei testi di legge (aggiunte alla ricerca testuale; i vettori ci arrivano da soli)
GIURIDICHE = {
    "licenzi": "disdetta disdire", "licenziamento": "disdetta disdire", "dimett": "disdetta disdire",
    "affitt": "locazione pigione conduttore locatore", "inquilin": "conduttore locazione",
    "padrone di casa": "locatore", "proprietario di casa": "locatore", "capo": "datore",
    "stipendio": "salario", "paga": "salario", "malato": "malattia", "incidente": "infortunio",
    "cauzione": "garanzia deposito", "eredit": "successione eredi", "multa": "multa contravvenzione",
    "divorzi": "divorzio coniugi", "sposat": "coniugi matrimonio", "figli": "figli genitori",
    "ferie": "vacanze", "straordinari": "lavoro straordinario", "disoccupat": "disoccupazione indennita",
    "pensione": "rendita vecchiaia", "invalid": "invalidita rendita", "mutua": "assicurazione malattie",
    "cassa malati": "assicurazione malattie premi", "assegni familiari": "assegni familiari",
    # "cartello" e anche l'accordo vietato tra imprese (LCart): per strada e un segnale
    "cartell stradal": "segnale segnaletica stradale", "cartelli stradal": "segnali segnaletica stradale",
    "cartello autostradal": "segnale segnaletica autostrada", "cartelli autostradal": "segnali segnaletica autostrada",
    "rubare": "furto", "rubato": "furto", "rubat": "furto", "rotto": "danneggiamento", "rompere": "danneggiamento",
}

RRF_K = 60
# Peso del tipo di atto: a parita di somiglianza prima la legge generale (codici, leggi federali), poi le ordinanze.
# Le norme speciali sul personale della Confederazione (RS 172.220.*) e simili valgono per pochi: scendono,
# a meno che la domanda parli proprio di impiego pubblico.
PESO_TIPO = 0.005
FONDAMENTALI = {"101", "210", "220", "311.0", "312.0", "281.1", "272", "173.110", "831.10", "832.10", "837.0"}
SPECIALI = ("172.220.", "172.221.", "510.", "512.")
PUBBLICO = re.compile(r"confederazion|federal[ei]|impiegat\w* (?:pubblic|dello stato)|personale|funzionari|"
                      r"militar|esercito|soldat|cantonal[ei] (?:dipendent|impiegat)", re.IGNORECASE)


def tipo_atto(rs: str, titolo: str, domanda: str = "") -> int:
    rs, t = (rs or "").strip(), (titolo or "").lower()
    if rs.startswith(SPECIALI) and not PUBBLICO.search(domanda or ""):
        return -3
    if rs in FONDAMENTALI or t.startswith(("codice", "costituzione")):
        return 2
    if t.startswith(("legge federale", "legge sull", "legge sui", "legge sulla", "legge concernente")):
        return 1
    return 0


def parole_utili(testo: str) -> str:
    basso = (testo or "").lower()
    parole = [w for w in re.findall(r"\w+", basso) if len(w) >= 3 and w not in VUOTE]
    extra = [v for k, v in GIURIDICHE.items() if k in basso]
    return " ".join(dict.fromkeys(" ".join(extra).split() + parole))   # prima i termini di legge


PESO_AMBITO = 0.006   # articoli negli ambiti scelti per la domanda (prefissi RS): salgono, ma non escludono gli altri


def candidati(con: sqlite3.Connection, testo: str, lang: str = "it", k: int = 8, prefissi=()) -> list[dict]:
    """Gli articoli vigenti piu promettenti per la domanda, in ordine. Ogni voce dice da quale ricerca viene."""
    elenchi = {}
    try:
        elenchi["testo"] = store.search(con, parole_utili(testo), lang=lang, limit=k * 6)
    except sqlite3.Error:
        elenchi["testo"] = []
    try:
        elenchi["vettori"] = vettori.cerca(con, testo, lang=lang, k=k * 6)
    except Exception:   # vettori facoltativi: un problema qui non deve fermare la ricerca
        elenchi["vettori"] = []
    punti, voci = {}, {}
    for nome, righe in elenchi.items():
        for pos, r in enumerate(righe):
            chiave = (r["act_uri"], r["lang"], r["eid"])
            punti[chiave] = punti.get(chiave, 0.0) + 1.0 / (RRF_K + pos + 1)
            v = voci.setdefault(chiave, {"rs": r["sr"], "legge": r["title"], "articolo": store.art_key(r["num"] or "") or r["num"],
                                         "rubrica": r["heading"], "estratto": r.get("excerpt") or "", "da": []})
            v["da"].append(nome)
    for chiave, v in voci.items():
        punti[chiave] += PESO_TIPO * tipo_atto(v["rs"], v["legge"], testo)
        if prefissi and str(v["rs"]).startswith(tuple(prefissi)):
            punti[chiave] += PESO_AMBITO
    ordine = sorted(punti, key=lambda c: -punti[c])[:k]
    return [voci[c] for c in ordine]
