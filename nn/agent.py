"""Agente giuridico di Nuova-Norma.

Non sa nulla a memoria: risponde consultando l'archivio locale tramite strumenti, e ogni
affermazione deve citare l'articolo e la versione da cui proviene.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.parse
from dataclasses import dataclass, field
from typing import Protocol

from . import cache_rete, cantoni, diff, documenti, fedlex, giurisprudenza, opencaselaw, parlamento, sources as fonti, store

SYSTEM_PROMPT = """Sei l'agente di ricerca giuridica di Nuova-Norma. Lavori solo su fonti ufficiali svizzere:
diritto federale (Fedlex: RS, RU, FF), consultazioni federali, Parlamento (Curia Vista), Tribunale federale,
diritto cantonale (Ticino). Non sai nulla a memoria: ogni affermazione viene da una fonte che hai letto
con uno strumento in questa conversazione.

Come lavori:
1. Capisci la domanda: e una domanda sul diritto in vigore, su un cambiamento in arrivo, su un dibattito
   politico, sull'applicazione in tribunale, o una mappa di settore? Scegli le fonti di conseguenza.
2. Diritto in vigore: cerca_articoli nell'archivio locale; se la legge non c'e, cerca_legge su Fedlex e poi
   importa_legge (e automatico e lecito: sono testi pubblici). Poi leggi_articolo per il testo esatto.
   Verifica con modifiche_in_arrivo se qualcosa sta per cambiare.
3. Cambiamenti e dibattito: novita_ru per quanto e stato appena pubblicato, consultazioni per i progetti
   su cui si puo prendere posizione, parlamento_cerca / parlamento_oggetto / parlamento_voti per gli atti
   parlamentari e le votazioni.
4. Applicazione: sentenze_cerca per le sentenze di tutti i tribunali svizzeri (federali e cantonali, Ticino compreso),
   sentenza_leggi per il testo o un considerando, sentenza_citazioni per chi la cita e cosa cita. giurisprudenza_cerca e
   giurisprudenza_leggi (sito del Tribunale federale) restano come ripiego. commentari_cerca trova estratti di
   commentari aperti (livello dottrina: non vincolante; cita autore e licenza).
5. Diritto cantonale: cantone_cerca e cantone_leggi (Ticino).
6. Prassi e fonti documentali (fonti_cerca, documento_leggi, documento_storia): direttive dell'UFAS su AVS, AI, IPG e
   prestazioni complementari, circolari FINMA, guide dell'IFPDT, promemoria AVS/AI, votazioni popolari, sentenze dei
   tribunali ticinesi e dei tribunali federali di prima istanza. elenca_fonti dice cosa e collegato e quanti documenti ci sono.
   Ogni risultato ha un `livello`: dichiaralo. Una direttiva o una circolare spiega come l'autorita applica la legge,
   ma non e legge: cita prima l'articolo di legge, poi la prassi che lo applica. Un promemoria e divulgativo.
7. Mappa di settore: raccogli le leggi federali e cantonali pertinenti, spiega perche ognuna si applica.

Citazioni, obbligatorie per ogni affermazione:
- articolo di legge federale: [RS 235.1 art. 24 cpv. 1, 2025-07-07]  (numero RS, articolo, data della versione letta)
- sentenza: [TF 4A_123/2023, 2024-03-12] oppure [DTF 145 III 225]; da sentenza_leggi: la sua `cita_come`, es. [Sentenza <id>, 2024-03-12]
- oggetto parlamentare: [Curia Vista 23.1234]   - consultazione: [Consultazione <id>]
- pubblicazione RU/FF: [RU 2024 257] o il titolo con data   - legge cantonale: [RL-TI 161.100]
- documento delle fonti documentali: la citazione `cita_come` di documento_leggi, es. [UFAS DR, 2026-01-01]
Cita solo cio che hai letto. Se una fonte non risponde o non contiene la risposta, dillo.

Verifica prima di citare:
- cerca_articoli e le altre ricerche restituiscono solo ESTRATTI o elenchi: non bastano per citare. Per citare un
  articolo devi averlo aperto con leggi_articolo (o la sentenza con giurisprudenza_leggi) in questa conversazione.
  Non scrivere "testo letto" se hai visto solo un estratto. Un controllo automatico verifica ogni citazione.
- Ogni risultato di uno strumento ha un campo `cita_come` con la citazione gia pronta: copiala esattamente.
- Se una ricerca non da risultati, riprova con meno parole, sinonimi o il numero (RS, RL) prima di concludere
  che non c'e nulla. Controlla anche i parametri che hai passato (es. cantone "TI").

Attenzione alle trappole di diritto:
- Versione: cita il testo VIGENTE OGGI. Se uno strumento segnala una versione futura (AVVISO_VERSIONE_FUTURA), non e
  ancora in vigore: usa la data indicata come vigente e, se utile, menziona la modifica in arrivo separatamente.
- Tipo di contratto: nel CO la LOCAZIONE (abitazioni, locali commerciali, art. 253 segg.) e l'AFFITTO (cose produttive,
  art. 275 segg.) hanno regole diverse (termini di disdetta, protezione). Verifica che gli articoli aperti riguardino
  il tipo di contratto chiesto prima di rispondere. Stesso principio per altri istituti dal nome simile.
- Diritto abrogato: una sentenza o un atto parlamentare puo riferirsi a una norma poi sostituita (es. art. 8 vecchia LPD,
  oggi art. 25 nLPD). Non presentarla come norma attuale: indica quella vigente, aprendola.
- Regole generali e eccezioni: dopo aver letto la regola, controlla gli articoli vicini che la limitano o la
  completano (eccezioni, termini speciali, ordinanze di applicazione) e menzionali o dichiara che non li hai verificati.

Quello che non hai: dottrina e commentari, regolamenti comunali; degli altri cantoni solo cio che fonti_cerca trova.
Diritto UE: solo gli atti archiviati nella fonte 'eurlex' (GDPR, AI Act, DSA, consumatori, assicurazioni, finanza,
sicurezza sociale). Dichiara sempre che un atto UE in Svizzera vale solo se richiamato da un accordo o dal diritto
svizzero, o per chi opera nell'UE. Le votazioni popolari ci sono solo se fonti_cerca le trova. Dillo in una frase, rispondi con quanto hai (diritto svizzero), e NON proporre di cercare altrove, di
usare un sito esterno o di chiedere permessi: non puoi farlo. Non fare domande di chiarimento se puoi rispondere
dichiarando l'ipotesi che adotti.
Sentenze: indica sempre data e tipo di decisione e se la norma applicata e stata poi modificata o abrogata
(le sentenze sulla protezione dei dati fino ad agosto 2023 applicano la vecchia LPD, ora abrogata).

Precisione:
- Per termini, scadenze e obblighi usa le parole esatte della legge tra virgolette basse («quanto prima»,
  «verosimilmente»), senza parafrasare e senza importare formule di altre leggi (es. GDPR europeo).
- Nomi di autorita come nella legge (IFPDT), terminologia italiana senza equivalenti inglesi.
- Distingui sempre a chi si applica una regola (privati, organi federali, titolare, responsabile).
- Un testo marcato "abrogato" o "non in vigore" va presentato come tale, mai come diritto vigente.
- Non inventare articoli, numeri, date o sentenze. Non offrire servizi che non puoi svolgere.

Forma: rispondi nella lingua della domanda, per chi non e giurista; prima il significato pratico, poi la base
legale, poi (se utile) cosa sta cambiando e cosa dicono i tribunali. Per una mappa di settore o una ricerca
ampia usa sezioni con titoli. Concludi con: "Informazione generale, non consulenza legale."
"""

def _tool(name, desc, props, required=()):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": list(required)}}}


_LANG = {"type": "string", "enum": ["it", "de", "fr", "rm", "en"]}
_RS = {"type": "string", "description": "Numero RS della legge, es. '235.1'"}

TOOLS = [
    # archivio locale
    _tool("elenca_leggi", "Leggi gia presenti nell'archivio locale: numero RS, titolo, lingue, ultima versione.", {}),
    _tool("cerca_articoli", "Ricerca per parole chiave negli articoli in vigore dell'archivio locale. Restituisce solo ESTRATTI: per citare apri l'articolo con leggi_articolo.",
          {"query": {"type": "string", "description": "Parole chiave giuridiche"}, "rs": {"type": "string"}, "lingua": _LANG}, ["query"]),
    _tool("leggi_articolo", "Testo esatto di un articolo. Senza data: versione piu recente; con data: versione in vigore a quella data.",
          {"rs": _RS, "articolo": {"type": "string", "description": "es. '19' o '958f'"}, "data": {"type": "string"}, "lingua": _LANG}, ["rs", "articolo"]),
    _tool("storia_articolo", "Date in cui un articolo e comparso, e stato modificato o tolto.",
          {"rs": _RS, "articolo": {"type": "string"}, "lingua": _LANG}, ["rs", "articolo"]),
    _tool("differenze", "Articoli cambiati tra due versioni di una legge (senza date: le ultime due).",
          {"rs": _RS, "da": {"type": "string"}, "a": {"type": "string"}, "lingua": _LANG}, ["rs"]),
    # Fedlex
    _tool("cerca_legge", "Cerca una legge o ordinanza federale su Fedlex per parole nel titolo. Usala quando la legge non e in archivio.",
          {"parole": {"type": "string", "description": "es. 'protezione dei dati', 'obbligazioni'"}, "lingua": _LANG,
           "anche_abrogate": {"type": "boolean"}}, ["parole"]),
    _tool("importa_legge", "Scarica da Fedlex nell'archivio locale tutte le versioni di una legge (poi usa leggi_articolo).",
          {"rs": _RS, "lingua": _LANG}, ["rs"]),
    _tool("modifiche_in_arrivo", "Modifiche gia decise ma non ancora in vigore: versioni future di una legge (con rs) oppure "
          "nuovi atti federali in entrata in vigore nei prossimi giorni (senza rs).",
          {"rs": {"type": "string"}, "giorni": {"type": "integer", "description": "orizzonte, predefinito 180"}, "lingua": _LANG}),
    _tool("novita_ru", "Pubblicazioni recenti nella Raccolta ufficiale (RU) e nel Foglio federale (FF).",
          {"giorni": {"type": "integer", "description": "predefinito 30"}, "parole": {"type": "string"}, "lingua": _LANG}),
    _tool("consultazioni", "Procedure di consultazione federali: progetti di legge su cui si puo prendere posizione.",
          {"parole": {"type": "string"}, "solo_aperte": {"type": "boolean"}, "lingua": _LANG}),
    _tool("consultazione_dettaglio", "Dettagli di una consultazione (descrizione, termine, atti toccati).",
          {"id": {"type": "string"}, "lingua": _LANG}, ["id"]),
    # Parlamento
    _tool("parlamento_cerca", "Oggetti parlamentari (mozioni, iniziative, postulati, progetti) per parole nel titolo.",
          {"parole": {"type": "string"}, "stato": {"type": "string"}, "depositati_dopo": {"type": "string", "description": "AAAA-MM-GG"}, "lingua": _LANG}, ["parole"]),
    _tool("parlamento_oggetto", "Dettaglio di un oggetto parlamentare: testo, situazione iniziale, risposta del Consiglio federale, procedura.",
          {"id": {"type": "integer", "description": "id numerico da parlamento_cerca"}, "lingua": _LANG}, ["id"]),
    _tool("parlamento_voti", "Votazioni in Consiglio nazionale e degli Stati sugli oggetti con queste parole nel titolo.",
          {"parole": {"type": "string"}, "lingua": _LANG}, ["parole"]),
    # Tribunale federale
    _tool("giurisprudenza_cerca", "Sentenze del Tribunale federale a testo pieno. raccolta: 'tutte' oppure 'dtf' (decisioni principali).",
          {"query": {"type": "string"}, "raccolta": {"type": "string", "enum": ["tutte", "dtf"]}, "lingua": _LANG,
           "dal": {"type": "string", "description": "GG.MM.AAAA"}, "al": {"type": "string"}}, ["query"]),
    _tool("giurisprudenza_leggi", "Testo (fatti e considerandi) di una sentenza dal suo identificativo docid.",
          {"docid": {"type": "string", "description": "es. aza://12-03-2024-4A_123-2023 o atf://145-III-225"}, "lingua": _LANG}, ["docid"]),
    # Cantoni
    _tool("cantone_cerca", "Leggi del Cantone Ticino per numero RL (es. 161.100) o parole del titolo.",
          {"query": {"type": "string"}, "cantone": {"type": "string", "enum": ["TI"]}}, ["query"]),
    _tool("cantone_leggi", "Testo di una legge cantonale dal suo URL (da cantone_cerca).",
          {"url": {"type": "string"}}, ["url"]),
    # Giurisprudenza di tutti i tribunali (OpenCaseLaw)
    _tool("sentenze_cerca", "Sentenze dei tribunali svizzeri, federali e cantonali (anche ticinesi), dal 1875. Restituisce elenchi con regesto: "
          "per citare apri la sentenza con sentenza_leggi.",
          {"query": {"type": "string", "description": "parole, articolo (es. 'art. 271 CO') o numero di incarto"},
           "cantone": {"type": "string", "description": "es. TI"}, "tribunale": {"type": "string"}, "lingua": _LANG,
           "offset": {"type": "integer"}}, ["query"]),
    _tool("sentenza_leggi", "Testo di una sentenza (o di un solo considerando con 'considerando', es. '2.3') dal suo id di sentenze_cerca.",
          {"id": {"type": "string"}, "considerando": {"type": "string"}, "parte": {"type": "integer"}}, ["id"]),
    _tool("sentenza_citazioni", "Sentenze citate da questa sentenza e sentenze che la citano (grafo delle citazioni).",
          {"id": {"type": "string"}, "offset": {"type": "integer"}}, ["id"]),
    _tool("commentari_cerca", "Estratti di commentari giuridici ad accesso aperto (livello dottrina, licenza CC-BY: cita autore e fonte).",
          {"query": {"type": "string", "description": "es. 'art. 336c CO' o un tema"}}, ["query"]),
    # Fonti documentali (archivio comune)
    _tool("elenca_fonti", "Fonti collegate, con livello giuridico (legge, prassi, informativo...) e documenti in archivio.", {}),
    _tool("fonti_cerca", "Ricerca a testo pieno nelle fonti documentali archiviate (direttive UFAS, circolari FINMA, guide IFPDT, "
          "promemoria AVS/AI, votazioni popolari, sentenze cantonali e dei tribunali federali di prima istanza, leggi ticinesi). "
          "Restituisce solo ESTRATTI: per citare apri il documento con documento_leggi.",
          {"query": {"type": "string"}, "fonte": {"type": "string", "description": "id della fonte, vedi elenca_fonti (facoltativo)"},
           "tipo": {"type": "string", "description": "es. direttiva, circolare, promemoria, guida, sentenza, votazione"}}, ["query"]),
    _tool("documento_leggi", "Testo di un documento archiviato. Con 'cerca' restituisce solo i passaggi che contengono quelle parole "
          "(usalo per i documenti lunghi, come le direttive); con 'parte' le parti successive del testo; con 'data' la versione valida a quella data.",
          {"fonte": {"type": "string"}, "chiave": {"type": "string", "description": "identificativo da fonti_cerca"},
           "articolo": {"type": "string", "description": "es. '33': solo quell'articolo (atti UE e documenti divisi in articoli)"},
           "cerca": {"type": "string"}, "parte": {"type": "integer"}, "data": {"type": "string", "description": "AAAA-MM-GG"}},
          ["fonte", "chiave"]),
    _tool("documento_storia", "Versioni archiviate di un documento, con la data dichiarata dalla fonte e quella di lettura.",
          {"fonte": {"type": "string"}, "chiave": {"type": "string"}}, ["fonte", "chiave"]),
]

TOOL_NAMES = {t["function"]["name"] for t in TOOLS}
MAX_STEPS = 16
VERIFY_ROUNDS = 2
MAX_TOOL_CHARS = 9000
# Leggi gia in archivio e confrontate con Fedlex da meno di tanti giorni: importa_legge non va in rete
FRESCHEZZA_GIORNI = float(os.environ.get("NN_FRESCHEZZA_GIORNI", "7") or 7)
# Da quante leggi in vigore in archivio la ricerca dei titoli resta locale (la RS interna in italiano: circa 1800 atti in vigore)
SOGLIA_CATALOGO = int(os.environ.get("NN_SOGLIA_CATALOGO", "1500") or 1500)


class ChatModel(Protocol):
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict: ...


@dataclass
class Source:
    sr: str
    act_uri: str
    lang: str
    eid: str
    num: str
    heading: str
    date: str
    kind: str = "rs"       # rs | tf | parlamento | consultazione | cantone | ru
    url: str = ""          # fonte esterna ufficiale (per tutto cio che non e nell'archivio)
    label: str = ""        # etichetta leggibile, es. "TF 4A_123/2023"


@dataclass
class Answer:
    text: str
    sources: list[Source] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)  # strumenti chiamati, per trasparenza
    unverified: list[str] = field(default_factory=list)  # citazioni di articoli mai aperti, dopo i tentativi di correzione
    absent: list[str] = field(default_factory=list)  # articoli cercati e risultati inesistenti: nominarli per dirlo non e citarli


class Archive:
    """Gli strumenti dell'agente, eseguiti sull'archivio SQLite."""

    def __init__(self, con: sqlite3.Connection, default_lang: str = "it", registro=None, chi: str = "", raw_dir=None):
        from pathlib import Path
        self.con = con
        if raw_dir is None:   # accanto all'archivio in uso (data/raw per quello predefinito); None se in memoria
            try:
                f = next((r[2] for r in con.execute("PRAGMA database_list") if r[1] == "main"), "")
            except sqlite3.Error:
                f = ""
            raw_dir = Path(f).parent / "raw" if f else None
        self.raw_dir = Path(raw_dir) if raw_dir else None
        self.lang = default_lang
        self.sources: dict[tuple, Source] = {}
        self.registro = registro  # formati.Registro, facoltativo: ogni fonte APERTA vi viene annotata
        self.chi = chi            # chi apre le fonti, es. "passo5:d1"
        self.absent: set[tuple[str, str]] = set()  # (RS, articolo) per cui leggi_articolo ha risposto "non trovato"

    def _act(self, rs: str):
        act = store.find_act(self.con, rs.strip().removeprefix("RS").strip())
        if act is None:
            raise LookupError(f"La legge RS {rs} non e in archivio. Leggi disponibili: vedi elenca_leggi.")
        return act

    def _lang(self, act_uri: str, lang: str | None) -> str:
        wanted = lang or self.lang
        if store.list_dates(self.con, act_uri, wanted):
            return wanted
        for (l,) in self.con.execute("SELECT DISTINCT lang FROM versions WHERE act_uri=?", (act_uri,)):
            return l
        return wanted

    def elenca_leggi(self) -> list[dict]:
        rows = self.con.execute("""
            SELECT a.sr_number AS rs, a.title, GROUP_CONCAT(DISTINCT v.lang) AS lingue,
                   MAX(v.date_applicability) AS ultima_versione
            FROM acts a JOIN versions v ON v.act_uri = a.uri GROUP BY a.uri ORDER BY a.sr_number""")
        return [dict(r) for r in rows]

    def cerca_articoli(self, query: str, rs: str | None = None, lingua: str | None = None) -> list[dict]:
        if not self.con.execute("SELECT 1 FROM sqlite_master WHERE name='search'").fetchone():
            store.rebuild_search(self.con)
        hits = store.search(self.con, query, lang=lingua, sr=rs, limit=8)
        return [{"rs": h["sr"], "legge": h["title"], "articolo": h["num"], "rubrica": h["heading"],
                 "versione": h["date"], "lingua": h["lang"], "estratto": h["excerpt"]} for h in hits]

    def leggi_articolo(self, rs: str, articolo: str, data: str | None = None, lingua: str | None = None) -> dict:
        act = self._act(rs)
        lang = self._lang(act["uri"], lingua)
        art = store.find_article(self.con, act["uri"], lang, articolo, data)
        if art is None:
            self.absent.add((act["sr_number"] or "", store.art_key(articolo)))
            raise LookupError(f"Articolo {articolo} non trovato nella RS {rs}" + (f" alla data {data}" if data else ""))
        dates = store.list_dates(self.con, act["uri"], lang)
        version = max((d for d in dates if d <= data), default=None) if data else store.in_force_date(dates)
        self.sources[(act["uri"], lang, art.eid, version)] = Source(
            act["sr_number"] or "", act["uri"], lang, art.eid, art.num, art.heading, version)
        cita = f"[RS {act['sr_number']} art. {store.art_key(art.num)}, {version}]"
        self._registra("articolo", cita, fedlex.public_url(act["uri"], lang), art.text, version,
                       dates[-1] if dates[-1] > version else "")
        out = {"rs": act["sr_number"], "legge": act["title"], "articolo": art.num, "rubrica": art.heading,
               "versione_in_vigore_dal": version, "versione_piu_recente": dates[-1],
               "sezione": " > ".join(art.path), "testo": art.text, "cita_come": cita}
        if not data and dates[-1] > version:
            out["AVVISO_VERSIONE_FUTURA"] = (f"Esiste una versione futura dal {dates[-1]}: non e ancora in vigore. Il testo qui sopra e "
                                             f"quello vigente oggi; cita la data {version}. Se serve, confrontale con `differenze`.")
        if not act["in_force"]:
            out["AVVISO"] = "ATTO ABROGATO: questo testo non e piu in vigore. Usalo solo come storia e dillo esplicitamente."
        return out

    def storia_articolo(self, rs: str, articolo: str, lingua: str | None = None) -> list[dict]:
        act = self._act(rs)
        lang = self._lang(act["uri"], lingua)
        out, prev = [], None
        for d in store.list_dates(self.con, act["uri"], lang):
            a = store.find_article(self.con, act["uri"], lang, articolo, d)
            h = a.text_hash if a else None
            state = ("non presente" if h is None else "compare" if prev is None
                     else "modificato" if h != prev else "invariato")
            if state != "invariato":
                out.append({"versione": d, "stato": state})
            prev = h
        return out

    def differenze(self, rs: str, da: str | None = None, a: str | None = None, lingua: str | None = None) -> dict:
        act = self._act(rs)
        lang = self._lang(act["uri"], lingua)
        dates = store.list_dates(self.con, act["uri"], lang)
        if len(dates) < 2 and not (da and a):
            return {"nota": "In archivio c'e una sola versione: nessun confronto possibile."}
        cur = store.in_force_date(dates)
        if not (da or a):  # senza date: la modifica in arrivo se c'e, altrimenti l'ultima gia entrata in vigore
            da, a = (cur, dates[-1]) if dates[-1] > cur else (dates[-2], cur)
        else:
            da, a = da or dates[-2], a or cur
        changes = diff.compare(store.load_articles(self.con, act["uri"], lang, da),
                               store.load_articles(self.con, act["uri"], lang, a))
        return {"da": da, "a": a, "articoli_cambiati": [
            {"articolo": c.num, "rubrica": c.heading, "tipo": c.kind,
             "modifica": c.word_diff()[:800] if c.kind == "modificato" else (c.new or c.old)[:400]}
            for c in changes[:40]]}

    # ---- Fedlex ----
    def cerca_legge(self, parole: str, lingua: str | None = None, anche_abrogate: bool = False) -> list[dict]:
        lang = lingua or self.lang
        locali = [] if anche_abrogate else self._titoli_locali(parole, lang)
        if locali and self._catalogo_completo():
            return locali   # tutta la RS e in archivio: nessuna rete
        dal_vivo = self._rete("fedlex.search_titles", 7, fedlex.search_titles, parole, lang,
                              in_force_only=not anche_abrogate)
        visti = {r.get("uri") for r in locali}
        return locali + [r for r in dal_vivo if r.get("uri") not in visti][:max(0, 15 - len(locali))]

    def _rete(self, fonte: str, giorni: float, fn, *args, **kwargs):
        """Una fonte dal vivo, passando dalla memoria locale (cache_rete)."""
        return cache_rete.ricorda(self.con, fonte, giorni, fn, *args, **kwargs)

    def _catalogo_completo(self) -> bool:
        """L'archivio contiene la RS intera (importa-catalogo): la ricerca dei titoli resta locale."""
        try:
            n = self.con.execute("SELECT COUNT(*) FROM acts WHERE in_force = 1").fetchone()[0]
        except sqlite3.Error:
            return False
        return n >= SOGLIA_CATALOGO

    def _titoli_locali(self, parole: str, lang: str, limite: int = 15) -> list[dict]:
        """Come fedlex.search_titles, ma sulle leggi gia in archivio: tutte le parole nel titolo."""
        words = [w for w in re.findall(r"\w+", (parole or "").lower()) if len(w) >= 3][:6]
        if not words:
            return []
        dove = " AND ".join("LOWER(a.title) LIKE ?" for _ in words)
        rows = self.con.execute(
            f"""SELECT DISTINCT a.uri, a.sr_number, a.title FROM acts a JOIN versions v ON v.act_uri = a.uri
                WHERE a.in_force = 1 AND v.lang = ? AND {dove}""",
            (lang, *[f"%{w}%" for w in words])).fetchall()
        frase = " ".join(re.findall(r"\w+", (parole or "").lower()))

        def rango(r):
            t = (r["title"] or "").lower()
            tipo = (0 if t.startswith(("legge", "bundesgesetz", "loi")) else
                    1 if t.startswith(("ordinanza", "verordnung", "ordonnance")) else 2)
            return ((r["sr_number"] or "").startswith("0."), frase not in t, tipo, len(t))
        return [{"rs": r["sr_number"] or "", "titolo": r["title"] or "", "sigla": "", "stato": "in vigore",
                 "uri": r["uri"], "url": fedlex.public_url(r["uri"], lang), "da_archivio": True}
                for r in sorted(rows, key=rango)[:limite]]

    def importa_legge(self, rs: str, lingua: str | None = None) -> dict:
        from . import cli
        lang = lingua or self.lang
        numero = rs.strip().removeprefix("RS").strip()
        act = store.find_act(self.con, numero)
        # Gia in archivio e confrontata con Fedlex di recente: nessuna rete durante la domanda.
        # L'aggiornamento notturno (importa-catalogo --aggiorna) tiene fresche tutte le leggi.
        if act is not None and act["in_force"] and store.list_dates(self.con, act["uri"], lang) \
                and store.checked_within(act, FRESCHEZZA_GIORNI):
            return {"importata": True, "rs": act["sr_number"], "titolo": act["title"], "in_vigore": True,
                    "versioni": store.list_dates(self.con, act["uri"], lang), "da_archivio": True}
        log: list[str] = []
        uri = cli.importa(self.con, rs.strip().removeprefix("RS").strip(), lingua or self.lang, log=log.append)
        act = store.find_act(self.con, uri)
        return {"importata": True, "rs": act["sr_number"], "titolo": act["title"],
                "in_vigore": bool(act["in_force"]), "versioni": store.list_dates(self.con, uri, lingua or self.lang),
                "log": log[-6:]}

    def modifiche_in_arrivo(self, rs: str | None = None, giorni: int = 180, lingua: str | None = None) -> dict:
        lang = lingua or self.lang
        if rs:
            act = self._act(rs)
            fut = self._rete("fedlex.future_versions", 1, fedlex.future_versions, act["uri"], lang)
            return {"rs": act["sr_number"], "titolo": act["title"], "versioni_future": fut,
                    "nota": "" if fut else "Nessuna versione futura gia pubblicata per questa legge."}
        rows = self._rete("fedlex.upcoming_entries", 1, fedlex.upcoming_entries, int(giorni or 180), lang)
        for r in rows:
            r["cita_come"] = self._cite("Fedlex", r["rs"] or r["titolo"][:60], r["url"], r["titolo"], r["entrata_in_vigore"])
        return {"nuovi_atti_in_entrata_in_vigore": rows}

    def novita_ru(self, giorni: int = 30, parole: str = "", lingua: str | None = None) -> list[dict]:
        rows = self._rete("fedlex.recent_publications", 1, fedlex.recent_publications, int(giorni or 30), lingua or self.lang, parole or "")
        for r in rows:
            r["cita_come"] = self._cite("Fedlex", f"{r['raccolta']} {r['titolo'][:50]}", r["url"], r["titolo"], r["pubblicato"])
        return rows

    def consultazioni(self, parole: str = "", solo_aperte: bool = True, lingua: str | None = None) -> list[dict]:
        rows = self._rete("fedlex.consultations", 1, fedlex.consultations, parole or "", lingua or self.lang, open_only=solo_aperte)
        for r in rows:
            self._src("consultazione", f"Consultazione {r['id']}", r["url"], r["titolo"])
            r["cita_come"] = f"[Consultazione {r['id']}]"
        return rows

    def consultazione_dettaglio(self, id: str, lingua: str | None = None) -> dict:
        d = self._rete("fedlex.consultation_detail", 1, fedlex.consultation_detail, id, lingua or self.lang)
        url = f"https://www.fedlex.admin.ch/{lingua or self.lang}/consultation-procedures/ongoing"
        self._src("consultazione", f"Consultazione {id}", url, d["titolo"])
        d["cita_come"] = f"[Consultazione {id}]"
        self._registra("consultazione", d["cita_come"], url, f"{d['titolo']}\n{d.get('descrizione', '')}", d.get("apertura", ""))
        return d

    # ---- Parlamento ----
    def parlamento_cerca(self, parole: str, stato: str | None = None, depositati_dopo: str | None = None,
                         lingua: str | None = None) -> list[dict]:
        rows = self._rete("parlamento.search_business", 1, parlamento.search_business, parole, lingua or self.lang, status=stato, submitted_after=depositati_dopo)
        for r in rows:
            self._src("parlamento", f"Curia Vista {r['numero']}", r["url"], r["titolo"])
            r["cita_come"] = f"[Curia Vista {r['numero']}]"
        return rows

    def parlamento_oggetto(self, id: int, lingua: str | None = None) -> dict:
        d = self._rete("parlamento.business_detail", 1, parlamento.business_detail, int(id), lingua or self.lang)
        self._src("parlamento", f"Curia Vista {d['numero']}", d["url"], d["titolo"])
        d["cita_come"] = f"[Curia Vista {d['numero']}]"
        self._registra("oggetto_parlamentare", d["cita_come"], d["url"],
                       "\n".join(str(v) for v in d.values() if isinstance(v, str)))
        return d

    def parlamento_voti(self, parole: str, lingua: str | None = None) -> list[dict]:
        return self._rete("parlamento.votes", 1, parlamento.votes, parole, lingua or self.lang)

    # ---- Tribunale federale ----
    def giurisprudenza_cerca(self, query: str, raccolta: str = "tutte", lingua: str | None = None,
                             dal: str = "", al: str = "") -> list[dict]:
        rows = self._rete("giurisprudenza.search", 7, giurisprudenza.search, query, lingua or self.lang, raccolta or "tutte", from_date=dal or "", to_date=al or "")
        for r in rows:
            self._src("tf", f"{r['tipo']} {r['numero']}", r["url"], r.get("data", ""))
            r["cita_come"] = f"[{r['tipo']} {r['numero']}" + (f", {r['data']}" if r.get("data") else "") + "]"
        return rows or [{"nota": "Nessuna sentenza riconosciuta per questa ricerca."}]

    def giurisprudenza_leggi(self, docid: str, lingua: str | None = None) -> dict:
        d = self._rete("giurisprudenza.decision_text", 365, giurisprudenza.decision_text, docid, lingua or self.lang)
        kind, numero, data = giurisprudenza.describe_docid(docid)
        self._src("tf", f"{kind} {numero}", d["url"], data)
        d["cita_come"] = f"[{kind} {numero}" + (f", {data}" if data else "") + "]"
        self._registra("sentenza", d["cita_come"], d["url"], d.get("testo", ""), data)
        return d

    # ---- Cantoni ----
    @staticmethod
    def _canton(value: str | None) -> str:
        v = (value or "TI").strip()
        return {"ticino": "TI", "tessin": "TI", "tessin (ti)": "TI"}.get(v.lower(), v.upper())

    def cantone_cerca(self, query: str, cantone: str = "TI") -> list[dict]:
        canton = self._canton(cantone)  # il modello puo scrivere "Ticino" o "ti": si normalizza
        if canton != "TI":
            return [{"nota": f"Per ora e indicizzato solo il Canton Ticino (TI), non '{canton}'."}]
        rows = cantoni.search(self.con, query, canton)
        if not rows and cantoni.count(self.con, canton) == 0:
            return [{"nota": "L'indice del Canton Ticino e vuoto: esegui  py -m nn indicizza-ticino  una volta."}]
        for r in rows:
            if r["numero"]:
                self._src("cantone", f"RL-TI {r['numero']}", r["url"], r["titolo"])
                r["cita_come"] = f"[RL-TI {r['numero']}]"
        return rows

    def cantone_leggi(self, url: str) -> dict:
        d = self._cantone_archiviato(url) or cantoni.text(self.con, url)
        self._src("cantone", f"RL-TI {d['numero'] or ''}".strip(), d["url"], d["titolo"])
        d["cita_come"] = f"[RL-TI {d['numero'] or d['url']}]"
        self._registra("legge_cantonale", d["cita_come"], d["url"], d.get("testo", ""))
        return d

    # ---- Giurisprudenza (OpenCaseLaw) ----
    def sentenze_cerca(self, query: str, cantone: str | None = None, tribunale: str | None = None,
                       lingua: str | None = None, offset: int | None = None) -> dict:
        r = self._rete("opencaselaw.cerca", 7, opencaselaw.cerca, query, lingua or "", self._canton(cantone) if cantone else "", tribunale or "", 10, offset or 0)
        r["provenienza"] = "OpenCaseLaw (copia delle sentenze pubblicate dai tribunali); verifica il testo all'indirizzo 'url' del tribunale"
        for x in r["risultati"]:
            x["apri_con"] = {"strumento": "sentenza_leggi", "id": x["id"]}
        return r

    def _archivia_sentenza(self, d: dict) -> None:
        """Le sentenze aperte entrano nell'archivio comune: si sa cosa e stato letto e quando."""
        if self.raw_dir is None:
            return
        try:
            documenti.ensure(self.con)
            it = documenti.Item("opencaselaw", d["id"], f"{d.get('tribunale') or ''} {d['id']} {d.get('titolo') or ''}".strip(),
                                "sentenza", f"{opencaselaw.BASE}/decisions/{urllib.parse.quote(d['id'], safe='')}", "it",
                                page_url=d.get("url") or "", valid_from=d.get("data") or "",
                                meta={"tribunale": d.get("tribunale"), "lingua_testo": d.get("lingua")})
            documenti.save_item(self.con, it)
            raw = json.dumps(d.get("grezzo") or d, ensure_ascii=False).encode("utf-8")
            documenti.save_version(self.con, it, raw, self.raw_dir, "application/json", text=d.get("testo") or "")
            self.con.commit()
        except Exception:
            pass   # l'archiviazione non deve mai impedire la lettura

    def sentenza_leggi(self, id: str, considerando: str | None = None, parte: int | None = None) -> dict:
        d = self._rete("opencaselaw.sentenza", 365, opencaselaw.sentenza, id)
        self._archivia_sentenza(d)
        label = f"Sentenza {d['id']}"
        out = {k: d.get(k) for k in ("id", "tribunale", "data", "lingua", "titolo", "regesto", "citazione_ufficiale", "url")}
        out["livello"] = "giurisprudenza"
        out["provenienza"] = "OpenCaseLaw, copia della sentenza pubblicata dal tribunale (indirizzo in 'url')"
        if considerando:
            c = self._rete("opencaselaw.considerando", 365, opencaselaw.considerando, d["id"], considerando)
            out["considerando"] = considerando
            out["testo"] = c.get("text") if isinstance(c, dict) and c.get("text") else json.dumps(c, ensure_ascii=False)[:8000]
            label += f" consid. {considerando}"
        else:
            size, k = 8000, max(0, int(parte or 0))
            testo = d.get("testo") or ""
            out.update(parte=k, parti_totali=max(1, -(-len(testo) // size)), testo=testo[k * size:(k + 1) * size])
        out["cita_come"] = f"[{label}, {d['data']}]" if d.get("data") else f"[{label}]"
        self._src("sentenza", label, d.get("url") or "", d.get("titolo") or "")
        self._registra("sentenza", out["cita_come"], d.get("url") or "", out.get("testo") or "", d.get("data") or "")
        return out

    def sentenza_citazioni(self, id: str, offset: int | None = None) -> object:
        return self._rete("opencaselaw.citazioni", 7, opencaselaw.citazioni, id, offset or 0)

    def commentari_cerca(self, query: str) -> object:
        r = self._rete("opencaselaw.commentari", 7, opencaselaw.commentari, query)
        return {"livello": "dottrina", "significato_livello": fonti.LIVELLI["dottrina"],
                "licenza": "CC-BY (OnlineKommentar) o CC BY-SA: cita autore e fonte", "risultati": r}

    # ---- Fonti documentali ----
    def _fonte(self, fonte: str):
        f = fonti.SOURCES.get((fonte or "").strip().lower())
        if f is None:
            raise LookupError(f"Fonte sconosciuta: {fonte}. Fonti disponibili: vedi elenca_fonti.")
        return f

    def elenca_fonti(self) -> list[dict]:
        documenti.ensure(self.con)
        conti = {r["source"]: r for r in documenti.stats(self.con)}
        out = []
        for f in fonti.SOURCES.values():
            c = conti.get(f.id)
            out.append({"fonte": f.id, "nome": f.name, "autorita": f.authority, "livello": f.livello_effettivo,
                        "significato_livello": fonti.LIVELLI.get(f.livello_effettivo, ""),
                        "documenti_in_archivio": c["documenti"] if c else None,
                        "ultimo_controllo": c["ultimo_controllo"] if c else None})
        return out

    def fonti_cerca(self, query: str, fonte: str | None = None, tipo: str | None = None) -> list[dict]:
        documenti.ensure(self.con)
        srcs = [self._fonte(fonte).id] if fonte else None
        rows = documenti.search(self.con, query, srcs, tipo)
        if not rows and srcs and not self.con.execute("SELECT 1 FROM doc_items WHERE source=? LIMIT 1", srcs).fetchone():
            return [{"nota": f"La fonte '{srcs[0]}' non ha ancora documenti in archivio (si scaricano con  py -m nn aggiorna-raccolte {srcs[0]})."}]
        for r in rows:
            f = fonti.SOURCES.get(r["source"])
            r["livello"] = r.pop("livello_documento", "") or (f.livello_effettivo if f else "")
            r["apri_con"] = {"strumento": "documento_leggi", "fonte": r["source"], "chiave": r["key"]}
        return rows

    @staticmethod
    def _passaggi(text: str, cerca: str, max_chars: int = 7000) -> list[str]:
        terms = documenti._terms(cerca)
        paras = [p for p in re.split(r"\n\s*\n|\n(?=\s*(?:\d+(?:\.\d+)*\s|[A-Z]\.|Art\.|Cifra|N\.\s?\d))", text) if p.strip()]
        scored = []
        for i, p in enumerate(paras):
            low = p.lower()
            sc = sum(low.count(t) for t in terms)
            if sc:
                scored.append((sc, i))
        chosen = sorted(i for _, i in sorted(scored, reverse=True)[:8])
        out, used = [], 0
        for i in chosen:
            chunk = "\n".join(paras[max(0, i - 1):i + 2]).strip()
            if used + len(chunk) > max_chars:
                break
            out.append(chunk)
            used += len(chunk)
        return out

    @staticmethod
    def _articolo(text: str, num: str) -> str:
        n = re.escape(str(num).strip().lower().removeprefix("art.").removeprefix("articolo").strip())
        m = re.search(rf"(?im)^\s*(?:articolo|art\.?|article|artikel)\s+{n}\s*$|^\s*(?:articolo|art\.)\s+{n}\b", text)
        if not m:
            return ""
        fine = re.search(r"(?im)^\s*(?:articolo|article|artikel)\s+\d+[a-z]*\s*$", text[m.end():])
        return text[m.start(): m.end() + (fine.start() if fine else 8000)].strip()[:8000]

    def documento_leggi(self, fonte: str, chiave: str, cerca: str | None = None, parte: int | None = None,
                        data: str | None = None, articolo: str | None = None) -> dict:
        documenti.ensure(self.con)
        f = self._fonte(fonte)
        d = documenti.find(self.con, f.id, chiave)
        if d is None:
            raise LookupError(f"Nessun documento '{chiave}' nella fonte {f.id}. Cerca prima con fonti_cerca.")
        if data:
            v = self.con.execute("SELECT * FROM doc_versions WHERE source=? AND key=? AND lang=? AND COALESCE(valid_from, substr(fetched_at,1,10)) <= ? "
                                 "ORDER BY COALESCE(valid_from,'') DESC, fetched_at DESC LIMIT 1", (f.id, d["key"], d["lang"], data)).fetchone()
            if v:
                d.update(text=v["text"], valid_from=v["valid_from"], fetched_at=v["fetched_at"], version_id=v["id"])
        text = d["text"] or ""
        meta = json.loads(d.get("meta") or "{}")
        quando = d.get("valid_from") or (d.get("fetched_at") or "")[:10]
        label = f"{f.sigla or f.id.upper()} {meta.get('sigla') or d['key']}"
        livello = meta.get("livello") or f.livello_effettivo
        out = {"fonte": f.name, "autorita": f.authority, "livello": livello,
               "significato_livello": fonti.LIVELLI.get(livello, ""), "chiave": d["key"], "titolo": d["title"],
               "lingua": meta.get("lingua_testo") or d["lang"], "numero": meta.get("numero", ""),
               "valido_dal": d.get("valid_from") or "non indicato dalla fonte",
               "letto_il": (d.get("fetched_at") or "")[:10], "url": d.get("page_url") or d.get("url"),
               "non_piu_pubblicato": bool(d.get("gone"))}
        if meta.get("nota_lingua"):
            out["nota_lingua"] = meta["nota_lingua"]
        if out["non_piu_pubblicato"]:
            out["avviso"] = "La fonte non pubblica piu questo documento: potrebbe essere stato abrogato o sostituito."
        size = 8000
        if articolo:
            t = self._articolo(text, articolo)
            out["articolo"] = articolo
            out["testo"] = t
            if not t:
                out["nota"] = f"Articolo {articolo} non trovato in questo documento: usa 'cerca' o leggi le parti."
            else:
                label = f"{label} art. {articolo}"
        elif cerca:
            ps = self._passaggi(text, cerca)
            out["passaggi"] = ps or []
            if not ps:
                out["nota"] = "Nessun passaggio con queste parole: prova sinonimi o leggi le parti del testo con 'parte'."
        else:
            k = max(0, int(parte or 0))
            out["parte"] = k
            out["parti_totali"] = max(1, -(-len(text) // size))
            out["testo"] = text[k * size:(k + 1) * size]
        out["cita_come"] = f"[{label}, {quando}]" if quando else f"[{label}]"
        self._src(f.id, label, out["url"], d["title"])
        self._registra(livello, out["cita_come"], out["url"],
                       "\n".join(out.get("passaggi") or []) or out.get("testo", ""), quando)
        return out

    def documento_storia(self, fonte: str, chiave: str) -> list[dict]:
        documenti.ensure(self.con)
        f = self._fonte(fonte)
        d = documenti.find(self.con, f.id, chiave)
        if d is None:
            raise LookupError(f"Nessun documento '{chiave}' nella fonte {f.id}.")
        return [{"valido_dal": h["valid_from"] or "", "letto_il": h["fetched_at"][:10], "impronta": h["sha256"][:12],
                 "caratteri": h["caratteri"]} for h in documenti.history(self.con, f.id, d["key"], d["lang"])]

    def _cantone_archiviato(self, url: str) -> dict | None:
        """Il testo ticinese gia in archivio (aggiorna-raccolte ticino), se c'e: niente rete e una versione datata."""
        try:
            documenti.ensure(self.con)
            r = self.con.execute("SELECT key FROM doc_items WHERE source='ticino' AND (page_url=? OR url=?) LIMIT 1",
                                 (url, url)).fetchone()
        except sqlite3.Error:
            return None
        d = documenti.latest(self.con, "ticino", r["key"]) if r else None
        if not d:
            return None
        meta = json.loads(d.get("meta") or "{}")
        txt = d["text"] or ""
        return {"cantone": "TI", "numero": meta.get("numero_rl"), "titolo": d["title"], "url": d["page_url"] or url,
                "testo": txt[:15000], "troncato": len(txt) > 15000, "archiviato_il": (d["fetched_at"] or "")[:10]}

    def _cite(self, kind: str, ref: str, url: str, heading: str, date: str | None = None) -> str:
        """Registra la fonte e restituisce la citazione pronta, es. [Fedlex 741.62, 2026-11-01]."""
        ref = re.sub(r"\s+", " ", re.sub(r"[\[\],]", " ", ref)).strip()
        label = f"{kind} {ref}"
        self._src("ru", label, url, heading)
        cita = f"[{label}" + (f", {date}" if date else "") + "]"
        self._registra("pubblicazione", cita, url, heading, date or "")
        return cita

    def _registra(self, tipo: str, citazione: str, url: str, testo: str, vigenza: str = "", futura: str = "") -> None:
        """Annota nel registro una fonte aperta (le ricerche, che mostrano solo elenchi, non vi entrano)."""
        if self.registro is not None:
            self.registro.registra(tipo=tipo, citazione=citazione, url=url, testo=testo or "", vigenza=vigenza or "",
                                   versione_futura=futura or "", aperta_da=self.chi)

    def _src(self, kind: str, label: str, url: str, heading: str) -> None:
        self.sources[(kind, label)] = Source("", "", self.lang, "", label, heading, "", kind=kind, url=url, label=label)

    def call(self, name: str, args: dict) -> str:
        fn = getattr(self, name, None) if name in TOOL_NAMES else None
        if fn is None:
            return json.dumps({"errore": f"Strumento sconosciuto: {name}"}, ensure_ascii=False)
        try:
            result = fn(**{k: v for k, v in args.items() if v not in (None, "")})
        except (LookupError, TypeError, ValueError) as e:
            result = {"errore": str(e)}
        except Exception as e:  # rete, fonte non raggiungibile: il modello deve saperlo e dirlo
            result = {"errore": f"Fonte non raggiungibile o errore nello strumento {name}: {type(e).__name__}: {str(e)[:300]}"}
        if isinstance(result, list) and not result:
            result = [{"nota": "Nessun risultato per questa ricerca. Riprova con meno parole, sinonimi o un numero (RS, RL) "
                               "prima di concludere che non c'e nulla."}]
        text = json.dumps(result, ensure_ascii=False)
        return text if len(text) <= MAX_TOOL_CHARS else text[:MAX_TOOL_CHARS] + ' ..."(troncato)"'


def ask(model: ChatModel, con: sqlite3.Connection, question: str, lang: str = "it",
        history: list[dict] | None = None, on_step=None, max_steps: int | None = None,
        verify_rounds: int | None = None) -> Answer:
    """on_step(evento, dettagli): facoltativo, per mostrare l'avanzamento.
    max_steps e verify_rounds riducono il lavoro (es. per l'esito parziale dopo un'interruzione)."""
    max_steps = MAX_STEPS if max_steps is None else max_steps
    verify_rounds = VERIFY_ROUNDS if verify_rounds is None else verify_rounds
    import time

    def note(event: str, info: str = "") -> None:
        if on_step:
            on_step(event, info)

    archive = Archive(con, lang)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *(history or []),
                {"role": "user", "content": question}]
    steps: list[dict] = []
    rounds = 0
    for step in range(max_steps):
        note("pensa", f"passaggio {step + 1}")
        t0 = time.monotonic()
        msg = model.chat(messages, tools=TOOLS)
        note("risposta", f"{time.monotonic() - t0:.1f} s")
        calls = msg.get("tool_calls") or []
        if not calls:
            text = (msg.get("content") or "").strip()
            missing = unread_citations(text, archive.sources.values(), archive.absent)
            if missing and rounds < verify_rounds:
                rounds += 1
                note("verifica", f"articoli citati ma non letti: {', '.join(missing)}")
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": (
                    "CONTROLLO AUTOMATICO: hai citato articoli che non hai aperto con leggi_articolo in questa conversazione: "
                    + ", ".join(missing) + ". Aprili ora con leggi_articolo e riscrivi la risposta completa citando solo "
                    "cio che hai letto; se un articolo non serve, toglilo dalla risposta insieme alle affermazioni che reggeva.")})
                continue
            if missing:
                text += ("\n\nAttenzione: le citazioni seguenti NON sono state verificate in questa ricerca (articoli non aperti): "
                         + ", ".join(missing) + ". Controllale sul testo ufficiale prima di fare affidamento.")
            return Answer(text or "Nessuna risposta dal modello.", list(archive.sources.values()), steps, missing,
                          sorted(f"RS {sr} art. {a}" for sr, a in archive.absent))
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls:
            fn = c.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            note("strumento", f"{fn.get('name', '')} {json.dumps(args, ensure_ascii=False)}")
            result = archive.call(fn.get("name", ""), args)
            steps.append({"strumento": fn.get("name"), "argomenti": args})
            messages.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": result})
    return Answer("Non sono riuscito a completare la ricerca in un numero ragionevole di passaggi. "
                  "Prova a riformulare la domanda in modo piu specifico.",
                  list(archive.sources.values()), steps)


def unread_citations(text: str, sources, absent=()) -> list[str]:
    """Articoli citati nel testo che non risultano aperti con leggi_articolo in questa ricerca.
    Gli articoli che il modello ha cercato e non esistono (`absent`) non contano: li nomina per dire che non ci sono."""
    read = {(src.sr, store.art_key(src.num)) for src in sources if src.kind == "rs"} | set(absent)
    missing: list[str] = []
    for c in find_citations(text):
        for art, _ in c.articles:
            if (c.sr, art) not in read:
                label = f"RS {c.sr} art. {art}"
                if label not in missing:
                    missing.append(label)
    return missing


BRACKET_RE = re.compile(r"\[RS\s*([\d.]+)\s*,?([^\]]*)\]", re.IGNORECASE)
ART_RE = re.compile(r"art\.?\s*(\d+\s*[a-z]{0,10})((?:\s*cpv\.?\s*[\w\s,–\-e]+?)?)(?=\s*(?:[;,]|$|art\.?))", re.IGNORECASE)
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass
class Citation:
    sr: str
    articles: list[tuple[str, str]]  # (numero articolo, eventuale "cpv. ...")
    date: str | None
    span: tuple[int, int]


_SIGLE = ["TF", "DTF", "ATF", "BGE", "Curia Vista", "Consultazione", "RL-TI", "RU", "FF", "Fedlex"]
_SIGLE += [f.sigla for f in fonti.SOURCES.values() if f.sigla and f.sigla not in _SIGLE]
OTHER_CIT_RE = re.compile(
    r"\[(?P<kind>" + "|".join(re.escape(k) for k in sorted(_SIGLE, key=len, reverse=True)) +
    r")\s+(?P<ref>[^\],]+?)(?:,\s*(?P<date>\d{4}-\d{2}-\d{2}))?\]")


@dataclass
class OtherCitation:
    kind: str
    ref: str
    date: str | None
    span: tuple[int, int]

    @property
    def label(self) -> str:
        kind = {"ATF": "DTF", "BGE": "DTF"}.get(self.kind, self.kind)
        ref = self.ref
        if kind == "RL-TI":  # "[RL-TI 161.100 art. 5]" o "[RL-TI 161.100 art. 10; RPU art. 4]": la fonte e l'atto intero
            ref = re.split(r"\s+art\.?|\s*;", ref, maxsplit=1)[0].strip()
        return f"{kind} {ref}"


def find_other_citations(text: str) -> list[OtherCitation]:
    return [OtherCitation(m.group("kind"), m.group("ref").strip(), m.group("date"), m.span())
            for m in OTHER_CIT_RE.finditer(text)]


def find_citations(text: str) -> list[Citation]:
    """Citazioni tra parentesi quadre, anche con capoversi e piu articoli:
    [RS 235.1 art. 24 cpv. 4–5; art. 26, 2025-07-07]."""
    out = []
    for m in BRACKET_RE.finditer(text):
        body = m.group(2)
        date = DATE_RE.search(body)
        body_wo_date = DATE_RE.sub("", body)
        arts = [(re.sub(r"\s+", "", a.group(1)).lower(), a.group(2).strip(" ,;"))
                for a in ART_RE.finditer(body_wo_date)]
        if arts:
            out.append(Citation(m.group(1), arts, date.group(0) if date else None, m.span()))
    return out
