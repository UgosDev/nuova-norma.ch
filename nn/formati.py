"""Formati dei dati della pipeline, registro delle fonti e cancello di codice.

Gli oggetti che passano da un passo all'altro (domanda, fonte, dossier, affermazione, collegamento) e i
controlli meccanici che non devono dipendere da un modello. Nessuna chiamata di rete, nessun modello.
Riferimento: la pagina "Nuova Norma: architettura dei passi".
"""
from __future__ import annotations

import datetime
import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

# ---------------------------------------------------------------------------
# Vocabolari chiusi
# ---------------------------------------------------------------------------

ASSI = ("dove", "quando", "chi", "che cosa")
ORIGINI = ("agente", "avvocato")
FASCE = ("scartata", "marchiata", "accettata")
SQUADRE = ("federale", "giurisprudenza", "cantone", "parlamento", "prassi", "ue")
MAX_SQUADRE = 2

TIPI_FONTE = ("articolo", "sentenza", "oggetto_parlamentare", "consultazione", "legge_cantonale", "pubblicazione", "atto_ue")

TIPI_AFFERMAZIONE = ("norma", "sentenza", "eccezione", "modifica_in_arrivo", "lacuna")
ORDINAMENTI = ("CH", "TI", "UE")
ESITI = ("confermata", "incerta", "contestata")
RELAZIONI = ("limita", "eccezione_di", "contraddice", "duplica")
MOTIVI_LACUNA = ("non_trovato", "fonte_non_coperta", "tetto_raggiunto")
STATI_DOSSIER = ("completo", "parziale", "tetto_raggiunto")
SEZIONI = ("risposta_breve", "base_legale", "giurisprudenza", "eccezioni_e_limiti", "come_procedere", "incerti_o_contestati",
           "cosa_cambia_e_cosa_manca")
VERIFICHE_FINALI = ("verificata", "segnalata")

# ---------------------------------------------------------------------------
# Passo 3: punteggio calcolato dal codice a partire da giudizi chiusi
# ---------------------------------------------------------------------------

# pesi iniziali, da tarare sul banco di prova; la somma fa 100
CRITERI = {"pertinenza": 30, "utilita": 25, "perimetro": 20, "non_presuppone": 15, "non_duplica": 10}
GIUDIZI = {"si": 1.0, "in_parte": 0.5, "no": 0.0}
SOGLIA_SCARTO = 30
SOGLIA_ACCETTAZIONE = 50


def calcola_punteggio(giudizi: dict[str, str]) -> int:
    """giudizi: {criterio: "si" | "in_parte" | "no"}. Un criterio mancante vale "no"."""
    sconosciuti = set(giudizi) - set(CRITERI)
    if sconosciuti:
        raise ValueError(f"Criteri sconosciuti: {', '.join(sorted(sconosciuti))}")
    totale = 0.0
    for criterio, peso in CRITERI.items():
        valore = giudizi.get(criterio, "no")
        if valore not in GIUDIZI:
            raise ValueError(f"Giudizio non valido per {criterio}: {valore!r} (ammessi: si, in_parte, no)")
        totale += peso * GIUDIZI[valore]
    punteggio = int(totale + 0.5)  # arrotondamento commerciale: 42.5 -> 43
    # sbarramento: una domanda inutile non puo essere accettata, qualunque sia la somma degli altri criteri
    if giudizi.get("utilita") == "no":
        punteggio = min(punteggio, SOGLIA_SCARTO - 1 if giudizi.get("pertinenza") == "no" else SOGLIA_ACCETTAZIONE - 1)
    return punteggio


def fascia(punteggio: int) -> str:
    if punteggio < SOGLIA_SCARTO:
        return "scartata"
    if punteggio < SOGLIA_ACCETTAZIONE:
        return "marchiata"
    return "accettata"


# ---------------------------------------------------------------------------
# Oggetti
# ---------------------------------------------------------------------------

@dataclass
class Domanda:
    id: str
    testo: str
    parte: str = ""            # la parte del Passo 1 da cui nasce: riferimento per il Passo 3
    segmento: str = ""
    asse: str = ""
    motivo: str = ""
    origine: str = "agente"    # nascosto a tutti i modelli
    giudizi: dict = field(default_factory=dict)
    punteggio: int | None = None
    fascia: str | None = None
    squadre: list = field(default_factory=list)
    riferimento: bool = False  # e una parte del passo 1: fa da metro al passo 3, non viene giudicata
    per_utente: bool = False   # la risposta e un fatto del caso che conosce solo l'utente: si chiede, non si cerca

    def valuta(self, giudizi: dict[str, str]) -> None:
        """Passo 3: registra i giudizi del modello; punteggio e fascia li calcola il codice."""
        self.giudizi = dict(giudizi)
        self.punteggio = calcola_punteggio(self.giudizi)
        self.fascia = fascia(self.punteggio)

    @property
    def marchiata(self) -> bool:
        return self.fascia == "marchiata"


@dataclass
class Fonte:
    """Voce del registro: una fonte ufficiale effettivamente aperta da un passo."""
    id: str
    tipo: str
    citazione: str
    url: str = ""
    vigenza: str = ""             # data della versione aperta
    versione_futura: str = ""     # data, se esiste una versione non ancora in vigore
    aperta_da: list = field(default_factory=list)   # es. ["passo5:d1", "passo6:a3"]
    aperta_il: str = ""
    impronta: str = ""            # SHA-256 del testo letto
    estratto: str = ""


@dataclass
class Lacuna:
    descrizione: str
    motivo: str = "non_trovato"


@dataclass
class Passaggio:
    fonte: str        # id del registro
    testo: str
    rilevanza: str = ""


@dataclass
class Ricerca:
    strumento: str
    parametri: dict = field(default_factory=dict)
    risultati: int = 0


@dataclass
class Dossier:
    domanda: str
    squadre: list = field(default_factory=list)
    fonti: list = field(default_factory=list)       # id del registro
    passaggi: list = field(default_factory=list)    # Passaggio
    ricerche: list = field(default_factory=list)    # Ricerca
    lacune: list | None = None                      # None = non dichiarate (rifiutato); [] = "nessuna lacuna"
    stato: str = "completo"


@dataclass
class Affermazione:
    id: str
    testo: str
    tipo: str
    istituto: str = ""
    ordinamento: str = ""
    soggetto: str = ""
    data_riferimento: str = ""
    fonti: list = field(default_factory=list)
    domanda: str = ""          # nascosto ai passi 6 e 7
    marchio: bool = False      # nascosto ai passi 5-7
    esito: str | None = None
    fonti_verifica: list = field(default_factory=list)
    alternativa: dict | None = None   # {"testo": ..., "fonti": [...]} solo se contestata
    sezione: str | None = None
    verifica_finale: dict | None = None  # {"esito": "verificata" | "segnalata", "motivo": ...}


@dataclass
class Collegamento:
    da: str
    a: str
    relazione: str
    motivo: str = ""


# ---------------------------------------------------------------------------
# Cosa vede ogni passo
# ---------------------------------------------------------------------------

TUTTI = frozenset(range(1, 11))
NASCOSTI = {
    "Domanda": {"origine": TUTTI},
    "Affermazione": {"domanda": frozenset({6, 7}), "marchio": frozenset({5, 6, 7})},
}


def vista(obj, passo: int) -> dict:
    """I campi di un oggetto che il codice puo passare al modello del passo indicato."""
    nascosti = NASCOSTI.get(type(obj).__name__, {})
    return {k: v for k, v in asdict(obj).items() if passo not in nascosti.get(k, ())}


# ---------------------------------------------------------------------------
# Registro delle fonti
# ---------------------------------------------------------------------------

def _oggi() -> str:
    return datetime.date.today().isoformat()


class Registro:
    """Ogni fonte aperta da qualsiasi passo, con chi l'ha aperta e quando. La verifica finale controlla qui."""

    def __init__(self, oggi: str | None = None):
        self.oggi = oggi or _oggi()
        self.voci: dict[str, Fonte] = {}
        self._chiavi: dict[tuple, str] = {}
        self._lock = threading.Lock()   # piu squadre scrivono insieme

    def registra(self, *, tipo: str, citazione: str, url: str = "", testo: str = "", vigenza: str = "",
                 versione_futura: str = "", aperta_da: str = "") -> Fonte:
        if tipo not in TIPI_FONTE:
            raise ValueError(f"Tipo di fonte sconosciuto: {tipo!r}")
        chiave = (tipo, citazione, vigenza)
        with self._lock:
            if chiave in self._chiavi:  # stessa fonte aperta di nuovo: si aggiunge solo chi l'ha aperta
                voce = self.voci[self._chiavi[chiave]]
                if aperta_da and aperta_da not in voce.aperta_da:
                    voce.aperta_da.append(aperta_da)
                return voce
            voce = Fonte(id=f"f{len(self.voci) + 1}", tipo=tipo, citazione=citazione, url=url, vigenza=vigenza,
                         versione_futura=versione_futura, aperta_da=[aperta_da] if aperta_da else [],
                         aperta_il=datetime.datetime.now().isoformat(timespec="seconds"),
                         impronta=hashlib.sha256(testo.encode("utf-8")).hexdigest() if testo else "",
                         estratto=testo[:2000])
            self.voci[voce.id] = voce
            self._chiavi[chiave] = voce.id
            return voce

    def aperte_da(self, chi: str) -> list:
        """Le fonti aperte da un certo passo e domanda (es. "passo4:d3")."""
        return [v for v in self.voci.values() if chi in v.aperta_da]

    def get(self, id: str) -> Fonte | None:
        return self.voci.get(id)

    def per_citazione(self, citazione: str) -> Fonte | None:
        return next((v for v in self.voci.values() if v.citazione == citazione), None)

    def __len__(self) -> int:
        return len(self.voci)

    def to_dict(self) -> dict:
        return {"oggi": self.oggi, "voci": [asdict(v) for v in self.voci.values()]}

    @classmethod
    def from_dict(cls, data: dict) -> "Registro":
        reg = cls(data.get("oggi"))
        for v in data.get("voci", []):
            voce = Fonte(**v)
            reg.voci[voce.id] = voce
            reg._chiavi[(voce.tipo, voce.citazione, voce.vigenza)] = voce.id
        return reg

    def salva(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), "utf-8")

    @classmethod
    def carica(cls, path: Path) -> "Registro":
        return cls.from_dict(json.loads(path.read_text("utf-8")))


# ---------------------------------------------------------------------------
# Cancello di codice
# ---------------------------------------------------------------------------

@dataclass
class Controllo:
    errori: list = field(default_factory=list)   # bloccano: l'oggetto torna al passo che l'ha prodotto
    avvisi: list = field(default_factory=list)   # non bloccano: vanno mostrati nella risposta

    @property
    def ok(self) -> bool:
        return not self.errori


def controlla_domanda(d: Domanda) -> Controllo:
    c = Controllo()
    if not d.id or not d.testo.strip():
        c.errori.append("domanda senza id o senza testo")
    elif not d.testo.rstrip().endswith("?"):
        c.errori.append(f"{d.id}: il testo non e una domanda")
    if d.asse and d.asse not in ASSI:
        c.errori.append(f"{d.id}: asse sconosciuto {d.asse!r}")
    if d.origine not in ORIGINI:
        c.errori.append(f"{d.id}: origine sconosciuta {d.origine!r}")
    if d.punteggio is not None and d.fascia != fascia(d.punteggio):
        c.errori.append(f"{d.id}: la fascia non corrisponde al punteggio")
    if len(d.squadre) > MAX_SQUADRE:
        c.errori.append(f"{d.id}: piu di {MAX_SQUADRE} squadre")
    for s in d.squadre:
        if s not in SQUADRE:
            c.errori.append(f"{d.id}: squadra sconosciuta {s!r}")
    if d.squadre and d.fascia == "scartata":
        c.errori.append(f"{d.id}: una domanda scartata non va assegnata")
    return c


def controlla_dossier(d: Dossier, registro: Registro) -> Controllo:
    c = Controllo()
    if d.lacune is None:
        c.errori.append(f"dossier {d.domanda}: lacune non dichiarate (se non ce ne sono, va scritto)")
    else:
        for l in d.lacune:
            if l.motivo not in MOTIVI_LACUNA:
                c.errori.append(f"dossier {d.domanda}: motivo di lacuna sconosciuto {l.motivo!r}")
    if d.stato not in STATI_DOSSIER:
        c.errori.append(f"dossier {d.domanda}: stato sconosciuto {d.stato!r}")
    if len(d.squadre) > MAX_SQUADRE:
        c.errori.append(f"dossier {d.domanda}: piu di {MAX_SQUADRE} squadre")
    for f in d.fonti:
        if registro.get(f) is None:
            c.errori.append(f"dossier {d.domanda}: fonte {f} non presente nel registro")
    for p in d.passaggi:
        if p.fonte not in d.fonti:
            c.errori.append(f"dossier {d.domanda}: passaggio da una fonte ({p.fonte}) non elencata nel dossier")
    if not d.fonti and not d.lacune:
        c.errori.append(f"dossier {d.domanda}: nessuna fonte e nessuna lacuna")
    return c


def controlla_affermazione(a: Affermazione, registro: Registro) -> Controllo:
    c = Controllo()
    oggi = registro.oggi
    pre = f"{a.id}:"
    if not a.testo.strip():
        c.errori.append(f"{pre} testo vuoto")
    if a.tipo not in TIPI_AFFERMAZIONE:
        c.errori.append(f"{pre} tipo sconosciuto {a.tipo!r}")
        return c
    if a.tipo != "lacuna":
        if not a.istituto.strip():
            c.errori.append(f"{pre} manca l'istituto: senza, l'affermazione non si capisce fuori dalla domanda")
        if a.ordinamento not in ORDINAMENTI:
            c.errori.append(f"{pre} ordinamento mancante o sconosciuto {a.ordinamento!r}")
        if not a.fonti:
            c.errori.append(f"{pre} nessuna fonte")
    fonti = []
    for f in a.fonti:
        voce = registro.get(f)
        if voce is None:
            c.errori.append(f"{pre} fonte {f} non presente nel registro: citata senza essere stata aperta")
        else:
            fonti.append(voce)

    data = a.data_riferimento or oggi
    if a.tipo == "modifica_in_arrivo":
        if not any((v.versione_futura and v.versione_futura > oggi) or (v.tipo == "pubblicazione" and v.vigenza > oggi)
                   for v in fonti):
            c.errori.append(f"{pre} modifica in arrivo senza una fonte con data futura")
    else:
        if data != oggi:
            c.errori.append(f"{pre} data di riferimento {data}: deve essere oggi ({oggi}) salvo modifiche in arrivo")
        for v in fonti:
            if v.vigenza and v.vigenza > oggi:
                c.errori.append(f"{pre} cita la versione del {v.vigenza}, non ancora in vigore")
            elif not v.vigenza and v.tipo == "legge_cantonale":  # testo consolidato senza cronologia
                c.avvisi.append(f"{pre} {v.citazione}: testo consolidato, data di vigenza non verificabile")
            if v.versione_futura and v.versione_futura > oggi:
                c.avvisi.append(f"{pre} {v.citazione}: esiste una versione futura dal {v.versione_futura}")

    if a.esito is not None and a.esito not in ESITI:
        c.errori.append(f"{pre} esito sconosciuto {a.esito!r}")
    for f in a.fonti_verifica:
        if registro.get(f) is None:
            c.errori.append(f"{pre} fonte di verifica {f} non presente nel registro")
    if a.esito == "contestata":
        alt = a.alternativa or {}
        if not str(alt.get("testo", "")).strip() or not alt.get("fonti"):
            c.errori.append(f"{pre} contestata senza lettura alternativa con fonte")
        for f in alt.get("fonti", []):
            if registro.get(f) is None:
                c.errori.append(f"{pre} fonte dell'alternativa {f} non presente nel registro")
    if a.sezione is not None and a.sezione not in SEZIONI:
        c.errori.append(f"{pre} sezione sconosciuta {a.sezione!r}")
    if a.verifica_finale is not None and a.verifica_finale.get("esito") not in VERIFICHE_FINALI:
        c.errori.append(f"{pre} esito della verifica finale sconosciuto")
    return c


def controlla_collegamento(k: Collegamento, ids: set[str]) -> Controllo:
    c = Controllo()
    if k.relazione not in RELAZIONI:
        c.errori.append(f"collegamento {k.da}-{k.a}: relazione sconosciuta {k.relazione!r}")
    if k.da == k.a:
        c.errori.append(f"collegamento {k.da}: un'affermazione non si collega a se stessa")
    for x in (k.da, k.a):
        if x not in ids:
            c.errori.append(f"collegamento {k.da}-{k.a}: affermazione {x} inesistente")
    return c


# ---------------------------------------------------------------------------
# Serializzazione
# ---------------------------------------------------------------------------

def da_dict(cls, data: dict):
    """Costruisce un oggetto ignorando i campi in piu (i modelli a volte ne aggiungono)."""
    nomi = {f.name for f in fields(cls)}
    data = {k: v for k, v in data.items() if k in nomi}
    if cls is Dossier:
        data["passaggi"] = [p if isinstance(p, Passaggio) else da_dict(Passaggio, p) for p in data.get("passaggi", [])]
        data["ricerche"] = [r if isinstance(r, Ricerca) else da_dict(Ricerca, r) for r in data.get("ricerche", [])]
        if data.get("lacune") is not None:
            data["lacune"] = [l if isinstance(l, Lacuna) else da_dict(Lacuna, l) for l in data["lacune"]]
    return cls(**data)


def perimetro(confermata: dict | None) -> str:
    """Il quadro confermato dall'utente (luogo, data, persone, istituto): righe brevi, senza la sua domanda."""
    ipotesi = [str(i).strip() for i in (confermata or {}).get("ipotesi") or [] if str(i).strip()]
    return "\n".join(f"- {i}" for i in ipotesi)
