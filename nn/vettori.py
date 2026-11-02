"""Vettori degli articoli: trovano articoli che dicono la stessa cosa con parole diverse ("licenziamento" e "disdetta").

Il calcolo massivo si fa una volta, fuori dal PC (notebook `colab/vettori.ipynb`): i testi sono pubblici.
Le domande degli utenti invece NON escono mai: la domanda si codifica in locale con lo stesso modello aperto.

Flusso:
  py -m nn esporta-vettori            -> data/vettori/da-calcolare.jsonl (solo articoli vigenti senza vettore)
  (Colab) jsonl -> vettori.npz
  py -m nn importa-vettori vettori.npz
Il file dei vettori e una matrice float16 normalizzata (data/vettori/<modello>.f16), letta con memmap; la tabella
`vettori` dice a quale articolo corrisponde ogni riga e con quale impronta del testo e stata calcolata: se il testo
cambia (nuova versione), il vettore non vale piu per quella versione e l'articolo torna tra quelli da calcolare.

Senza numpy, senza il file o senza il modello in locale la ricerca resta solo testuale (FTS5): nulla si rompe.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from pathlib import Path

# Da dove vengono i vettori: "locale" (sentence-transformers, GPU se c'e: sviluppo sul PC) oppure "infomaniak"
# (API in Svizzera: produzione). Si leggono a ogni uso, dopo il file .env.
PREDEFINITI = {"locale": "BAAI/bge-m3", "infomaniak": "bge_multilingual_gemma2"}
DIMENSIONI = {"BAAI/bge-m3": 1024, "bge_multilingual_gemma2": 3584}
MODELLO = "BAAI/bge-m3"   # solo per compatibilita: usare modello_attivo()
DIM = int(os.environ["NN_VETTORI_DIM"]) if os.environ.get("NN_VETTORI_DIM") else None   # forza la dimensione


def _env() -> None:
    try:
        from . import ai
        ai.load_env()
    except Exception:
        pass


def fonte() -> str:
    _env()
    return os.environ.get("NN_VETTORI_FONTE", "locale").strip().lower() or "locale"


def modello_attivo() -> str:
    _env()
    return os.environ.get("NN_VETTORI_MODELLO", "").strip() or PREDEFINITI.get(fonte(), "BAAI/bge-m3")


def _dim(con: sqlite3.Connection | None, modello: str) -> int | None:
    """Dimensione dei vettori di un modello: quella registrata al primo import, altrimenti quella nota."""
    if con is not None:
        try:
            r = con.execute("SELECT dim FROM vettori_modelli WHERE modello = ?", (modello,)).fetchone()
            if r:
                return int(r[0])
        except sqlite3.Error:
            pass
    return DIM or DIMENSIONI.get(modello)
# Ricetta del testo da cui si calcola il vettore: se cambia, tutti i vettori vanno ricalcolati (calcola-vettori lo fa).
# 2: rubrica dai titoli marginali e sezioni di contesto (1.11.2026)
RICETTA = 2
MAX_CARATTERI = 6000   # circa 1500 token: piu che sufficiente per un articolo, evita i rari articoli enormi

SCHEMA = """
CREATE TABLE IF NOT EXISTS vettori (
  modello    TEXT NOT NULL,
  riga       INTEGER NOT NULL,          -- riga nella matrice del file .f16
  version_id INTEGER NOT NULL,
  eid        TEXT NOT NULL,
  text_hash  TEXT NOT NULL,
  PRIMARY KEY (modello, riga)
);
CREATE INDEX IF NOT EXISTS idx_vettori_versione ON vettori(version_id, eid);
CREATE TABLE IF NOT EXISTS vettori_modelli (
  modello TEXT PRIMARY KEY,
  dim     INTEGER NOT NULL
);
"""

_LOCK = threading.Lock()
_MATRICI: dict = {}        # (percorso, righe) -> matrice memmap
_CODIFICATORE: dict = {}   # modello -> oggetto con .encode, oppure None se non disponibile


def slug(modello: str | None = None) -> str:
    modello = modello or modello_attivo()
    return re.sub(r"[^A-Za-z0-9]+", "-", modello).strip("-").lower()


def cartella(con: sqlite3.Connection) -> Path | None:
    f = next((r[2] for r in con.execute("PRAGMA database_list") if r[1] == "main"), "") or ""
    return Path(f).parent / "vettori" if f else None


def file_matrice(con: sqlite3.Connection, modello: str | None = None) -> Path | None:
    modello = modello or modello_attivo()
    c = cartella(con)
    return c / f"{slug(modello)}.f16" if c else None


def assicura(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(vettori)")}
    if "ricetta" not in cols:
        con.execute("ALTER TABLE vettori ADD COLUMN ricetta INTEGER NOT NULL DEFAULT 1")
        con.commit()
    con.execute("DROP INDEX IF EXISTS idx_vettori_articolo")


def _fatti(con: sqlite3.Connection, modello: str) -> set:
    return {(x[0], x[1], x[2]) for x in con.execute(
        "SELECT version_id, eid, text_hash FROM vettori WHERE modello = ? AND ricetta = ?", (modello, RICETTA))}


def _vigenti(con: sqlite3.Connection, lang: str | None = None):
    """Gli articoli nell'indice di ricerca (versione vigente di ogni atto in vigore), con versione e impronta."""
    filtro = "AND s.lang = ?" if lang else ""
    return con.execute(f"""
        SELECT v.id AS version_id, s.eid, ar.text_hash, ar.path, s.lang, s.sr, s.title, s.num, s.heading, s.text
        FROM search s
        JOIN versions v ON v.act_uri = s.act_uri AND v.lang = s.lang AND v.date_applicability = s.date
        JOIN articles ar ON ar.version_id = v.id AND ar.eid = s.eid
        WHERE 1 = 1 {filtro}""", (lang,) if lang else ())


def testo_per_vettore(r) -> str:
    try:
        sezioni = json.loads(r["path"] or "[]")
    except (ValueError, TypeError, IndexError, KeyError):
        sezioni = []
    contesto = " > ".join(str(x) for x in sezioni[-3:])
    righe = [f"{r['title']} (RS {r['sr']})", contesto, f"{r['num']} {r['heading'] or ''}".strip(), r["text"]]
    return "\n".join(x for x in righe if x)[:MAX_CARATTERI]


def esporta(con: sqlite3.Connection, destinazione: Path, modello: str | None = None, lang: str | None = None) -> int:
    """Scrive in JSONL gli articoli vigenti che non hanno ancora un vettore per questo modello."""
    modello = modello or modello_attivo()
    assicura(con)
    fatti = _fatti(con, modello)
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(destinazione, "w", encoding="utf-8") as f:
        for r in _vigenti(con, lang):
            if (r["version_id"], r["eid"], r["text_hash"]) in fatti:
                continue
            f.write(json.dumps({"r": r["version_id"], "e": r["eid"], "h": r["text_hash"],
                                "t": testo_per_vettore(r)}, ensure_ascii=False) + "\n")
            n += 1
    return n


def _np():
    try:
        import numpy as np
        return np
    except ImportError:
        return None


def importa(con: sqlite3.Connection, sorgente: Path, modello: str | None = None) -> dict:
    """Aggiunge i vettori calcolati (npz con r, e, h, v) in fondo alla matrice. Salta quelli di testi cambiati."""
    modello = modello or modello_attivo()
    np = _np()
    if np is None:
        raise RuntimeError("Serve numpy: py -m pip install numpy")
    assicura(con)
    dati = np.load(sorgente, allow_pickle=False)
    return _aggiungi(con, modello, dati["r"], dati["e"], dati["h"], dati["v"])


def _aggiungi(con: sqlite3.Connection, modello: str, r, e, h, v) -> dict:
    """Aggiunge in fondo alla matrice i vettori di articoli ancora vigenti e non gia presenti."""
    np = _np()
    assicura(con)
    dim = _dim(con, modello)
    if v.ndim != 2 or (dim and v.shape[1] != dim):
        raise ValueError(f"Vettori di dimensione {v.shape[1] if v.ndim == 2 else '?'}, attesi {dim} ({modello})")
    dim = int(v.shape[1])
    con.execute("INSERT OR IGNORE INTO vettori_modelli(modello, dim) VALUES (?, ?)", (modello, dim))
    attuali = {(x["version_id"], x["eid"]): x["text_hash"] for x in _vigenti(con)}
    gia = _fatti(con, modello)
    tieni = [i for i in range(len(r))
             if attuali.get((int(r[i]), str(e[i]))) == str(h[i]) and (int(r[i]), str(e[i]), str(h[i])) not in gia]
    percorso = file_matrice(con, modello)
    if percorso is None:
        raise RuntimeError("Archivio in memoria: i vettori servono su un archivio su file")
    percorso.parent.mkdir(parents=True, exist_ok=True)
    righe = con.execute("SELECT COALESCE(MAX(riga) + 1, 0) FROM vettori WHERE modello = ?", (modello,)).fetchone()[0]
    blocco = v[tieni].astype("float32")
    norme = np.linalg.norm(blocco, axis=1, keepdims=True)
    norme[norme == 0] = 1
    blocco = (blocco / norme).astype("<f2")
    # la matrice deve avere esattamente `righe` righe prima di aggiungere: si tronca un'eventuale coda interrotta
    with open(percorso, "ab") as f:
        f.truncate(righe * dim * 2)
        f.seek(righe * dim * 2)
        f.write(blocco.tobytes())
    # i vettori della ricetta precedente per gli stessi articoli escono dalla tabella (la riga resta nel file, orfana)
    con.executemany("DELETE FROM vettori WHERE modello = ? AND version_id = ? AND eid = ? AND ricetta <> ?",
                    [(modello, int(r[i]), str(e[i]), RICETTA) for i in tieni])
    con.executemany("INSERT INTO vettori(modello, riga, version_id, eid, text_hash, ricetta) VALUES (?,?,?,?,?,?)",
                    [(modello, righe + k, int(r[i]), str(e[i]), str(h[i]), RICETTA) for k, i in enumerate(tieni)])
    con.commit()
    with _LOCK:
        _MATRICI.clear()
        _PRONTE.clear()
    return {"importati": len(tieni), "scartati": len(r) - len(tieni), "totale": righe + len(tieni)}


def dispositivo() -> str:
    """GPU NVIDIA se PyTorch la vede (NN_VETTORI_DISPOSITIVO per forzare: cuda, cpu)."""
    scelto = os.environ.get("NN_VETTORI_DISPOSITIVO", "")
    if scelto:
        return scelto
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def azzera(con: sqlite3.Connection, modello: str | None = None) -> None:
    """Toglie tutti i vettori di un modello (tabella e file), per ricalcolarli da capo senza righe orfane."""
    modello = modello or modello_attivo()
    assicura(con)
    con.execute("DELETE FROM vettori WHERE modello = ?", (modello,))
    con.commit()
    percorso = file_matrice(con, modello)
    with _LOCK:
        _MATRICI.clear()
        _PRONTE.clear()
    if percorso is not None and percorso.exists():
        with open(percorso, "r+b") as f:
            f.truncate(0)


def calcola(con: sqlite3.Connection, modello: str | None = None, batch: int = 32, blocco: int = 2048,
            lang: str | None = None, log=print) -> dict:
    """Calcola in locale (GPU se c'e) i vettori degli articoli vigenti che non li hanno ancora, a blocchi:
    un'interruzione non perde il lavoro gia salvato, e al riavvio si riparte da dove si era rimasti."""
    modello = modello or modello_attivo()
    np = _np()
    if np is None:
        raise RuntimeError("Serve numpy: py -m pip install numpy")
    import time
    assicura(con)
    fatti = _fatti(con, modello)
    da_fare = [(x["version_id"], x["eid"], x["text_hash"], testo_per_vettore(x)) for x in _vigenti(con, lang)
               if (x["version_id"], x["eid"], x["text_hash"]) not in fatti]
    if not da_fare:
        return {"importati": 0, "scartati": 0, "totale": len(fatti)}
    if fonte() == "infomaniak":
        from .embedding_infomaniak import Infomaniak
        enc, dev = Infomaniak(modello), "API Infomaniak"
        blocco = min(blocco, 1024)
    else:
        from sentence_transformers import SentenceTransformer
        dev = dispositivo()
        kw = {}
        if dev.startswith("cuda"):
            import torch
            kw["model_kwargs"] = {"torch_dtype": torch.float16}
        enc = SentenceTransformer(modello, device=dev, **kw)
        enc.max_seq_length = 2048
    da_fare.sort(key=lambda x: len(x[3]))   # testi di lunghezza simile insieme: molto piu veloce
    log(f"{len(da_fare)} articoli da calcolare con {modello} su {dev}")
    t0, tot = time.time(), {"importati": 0, "scartati": 0, "totale": 0}
    for i in range(0, len(da_fare), blocco):
        parte = da_fare[i:i + blocco]
        v = enc.encode([x[3] for x in parte], batch_size=batch, normalize_embeddings=True, convert_to_numpy=True)
        esito = _aggiungi(con, modello, np.asarray([x[0] for x in parte]), np.asarray([x[1] for x in parte]),
                          np.asarray([x[2] for x in parte]), v)
        tot["importati"] += esito["importati"]
        tot["scartati"] += esito["scartati"]
        tot["totale"] = esito["totale"]
        fatti_ora = i + len(parte)
        resto = (time.time() - t0) / fatti_ora * (len(da_fare) - fatti_ora)
        log(f"  {fatti_ora}/{len(da_fare)}  ({time.time() - t0:.0f} s, mancano circa {resto / 60:.0f} min)")
    if hasattr(enc, "token_usati"):
        log(f"Token usati: {enc.token_usati}")
    return tot


def _matrice(con: sqlite3.Connection, modello: str):
    np = _np()
    percorso = file_matrice(con, modello)
    if np is None or percorso is None or not percorso.exists():
        return None
    dim = _dim(con, modello)
    if not dim:
        return None
    righe = os.path.getsize(percorso) // (dim * 2)
    if righe == 0:
        return None
    k = (str(percorso), righe)
    with _LOCK:
        if k not in _MATRICI:
            _MATRICI.clear()
            _MATRICI[k] = np.memmap(percorso, dtype="<f2", mode="r", shape=(righe, dim))
        return _MATRICI[k]


def codificatore(modello: str | None = None):
    """Il modello in locale per codificare le domande, oppure None (sentence-transformers non installato,
    modello non scaricato). NN_VETTORI=0 disattiva la ricerca per vettori."""
    modello = modello or modello_attivo()
    if os.environ.get("NN_VETTORI", "1") == "0":
        return None
    with _LOCK:
        if modello not in _CODIFICATORE:
            try:
                if fonte() == "infomaniak":
                    from .embedding_infomaniak import Infomaniak
                    _CODIFICATORE[modello] = Infomaniak(modello)
                else:
                    from sentence_transformers import SentenceTransformer
                    _CODIFICATORE[modello] = SentenceTransformer(modello, device=dispositivo())
            except Exception:   # libreria assente, modello non scaricabile: si resta sulla ricerca testuale
                _CODIFICATORE[modello] = None
        return _CODIFICATORE[modello]


def codifica_domanda(enc, testo: str):
    """Il vettore di una domanda. I modelli via API vogliono un'istruzione davanti alle domande (non agli articoli)."""
    from .embedding_infomaniak import Infomaniak
    if isinstance(enc, Infomaniak):
        return enc.encode([testo], normalize_embeddings=True, domanda=True)[0]
    return enc.encode([testo], normalize_embeddings=True)[0]


def scalda(con: sqlite3.Connection, modello: str | None = None) -> bool:
    """Carica modello e matrice (sulla GPU se c'e) e fa qualche domanda di prova di lunghezze diverse, cosi la prima
    domanda vera non paga i tempi di avvio. Restituisce False se i vettori non sono disponibili."""
    modello = modello or modello_attivo()
    if _matrice(con, modello) is None or codificatore(modello) is None:
        return False
    for prova in ("disdetta", "Il datore di lavoro puo disdire il contratto durante la malattia?",
                  "Posso disdire il contratto di locazione prima della scadenza? " * 3):
        cerca(con, prova, k=1, modello=modello)
    return True


def disponibile(con: sqlite3.Connection, modello: str | None = None) -> bool:
    modello = modello or modello_attivo()
    return _matrice(con, modello) is not None


def cerca(con: sqlite3.Connection, domanda: str, lang: str | None = None, k: int = 8,
          modello: str | None = None, vettore=None) -> list[dict]:
    """Articoli vigenti piu vicini alla domanda. `vettore`: domanda gia codificata (prove)."""
    modello = modello or modello_attivo()
    np = _np()
    m = _matrice(con, modello)
    if np is None or m is None:
        return []
    if vettore is None:
        enc = codificatore(modello)
        if enc is None:
            return []
        vettore = codifica_domanda(enc, domanda)
    q = np.asarray(vettore, dtype="float32")
    q = q / (np.linalg.norm(q) or 1)
    punteggi = _punteggi(np, m, q)
    ordine = np.argsort(-punteggi)[: k * 25]
    if not len(ordine):
        return []
    posti = ",".join("?" * len(ordine))
    righe = {int(x["riga"]): x for x in con.execute(f"""
        SELECT ve.riga, COALESCE(a.sr_number, '') AS sr, v.lang, v.act_uri, ar.eid, v.date_applicability AS date,
               COALESCE(a.title, v.title, '') AS title, ar.num, ar.heading, ar.path, substr(ar.text, 1, 300) AS excerpt
        FROM vettori ve
        JOIN versions v ON v.id = ve.version_id
        JOIN acts a ON a.uri = v.act_uri AND a.in_force = 1
        JOIN articles ar ON ar.version_id = ve.version_id AND ar.eid = ve.eid AND ar.text_hash = ve.text_hash
        WHERE ve.modello = ? AND ve.riga IN ({posti})
          AND v.date_applicability = (SELECT MAX(w.date_applicability) FROM versions w
                                      WHERE w.act_uri = v.act_uri AND w.lang = v.lang
                                        AND w.date_applicability <= date('now'))""",
        (modello, *[int(i) for i in ordine]))}
    out = []
    for i in ordine:
        r = righe.get(int(i))
        if r is None or (lang and r["lang"] != lang):
            continue   # vettore di una versione non piu vigente, o altra lingua
        d = {c: r[c] for c in r.keys() if c not in ("riga", "path")}
        from .store import rubrica
        d["heading"] = rubrica(r["heading"], r["path"])
        d["somiglianza"] = round(float(punteggi[i]), 4)
        out.append(d)
        if len(out) >= k:
            break
    return out


RAM_MAX = int(os.environ.get("NN_VETTORI_RAM_MB", "600") or 600) * 1_000_000   # copia float32 in memoria (CPU)
_PRONTE: dict = {}   # (id della matrice, dispositivo) -> matrice pronta per il prodotto (GPU o float32 in memoria)


def _punteggi(np, m, q):
    """Somiglianza con tutte le righe. La matrice viene preparata una volta sola: sulla GPU se PyTorch la vede
    (140 MB in float16 per la RS, un millisecondo a domanda), altrimenti in float32 in memoria."""
    dev = dispositivo()
    k = (id(m), m.shape[0], dev)
    with _LOCK:
        pronta = _PRONTE.get(k)
        if pronta is None:
            _PRONTE.clear()
            if dev.startswith("cuda"):
                import torch
                pronta = torch.from_numpy(np.array(m)).to(dev)
            elif m.shape[0] * m.shape[1] * 4 <= RAM_MAX:
                pronta = np.asarray(m, dtype="float32")
            else:
                pronta = m   # troppo grande per una copia in float32: si calcola a blocchi
            _PRONTE[k] = pronta
    if dev.startswith("cuda"):
        import torch
        qt = torch.from_numpy(q.astype("float16")).to(dev)
        return (pronta @ qt).float().cpu().numpy()
    if pronta.dtype != np.float32:
        return _a_blocchi(np, pronta, q)
    return pronta @ q


def _a_blocchi(np, m, q, passo: int = 50000):
    return np.concatenate([m[i:i + passo].astype("float32") @ q for i in range(0, m.shape[0], passo)])
