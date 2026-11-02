"""Gli ambiti del diritto (nuova-norma/ambiti.json): l'elenco che dice in quali "scaffali" sta una domanda.

Il file si modifica a mano o si rigenera; questo modulo lo carica, lo controlla e lo prepara per il modello veloce
che assegna i punteggi (Anorma, prima della scomposizione). Il modello legge solo nome, descrizione, cose da non
confondere; il codice usa prefissi RS, atti, squadre, collegati e soglia.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

FILE = Path(__file__).resolve().parent.parent / "ambiti.json"
SOGLIA = 0.4
OBBLIGATORI = ("id", "nome", "descrizione", "non_confondere", "esempi", "rs", "atti", "livelli", "squadre",
               "collegati", "padre")


def percorso() -> Path:
    return Path(os.environ["NN_AMBITI"]) if os.environ.get("NN_AMBITI") else FILE


@lru_cache(maxsize=4)
def _carica(p: str, mtime: float) -> tuple:
    dati = json.loads(Path(p).read_text(encoding="utf-8"))
    return tuple(a for a in dati if isinstance(a, dict) and a.get("id") and a.get("nome"))


def tutti() -> list[dict]:
    """Tutti gli ambiti, o [] se il file manca (la pipeline funziona anche senza)."""
    p = percorso()
    try:
        return list(_carica(str(p), p.stat().st_mtime))
    except (OSError, ValueError):
        return []


def per_id() -> dict[str, dict]:
    return {a["id"]: a for a in tutti()}


def foglie() -> list[dict]:
    """Gli ambiti da valutare: tutti tranne i 9 rami principali (troppo generici per guidare la ricerca)."""
    return [a for a in tutti() if a.get("padre") is not None]


def riga(a: dict) -> str:
    """Come il modello veloce vede un ambito: una riga corta."""
    nc = "; ".join(a.get("non_confondere") or [])
    return f"{a['id']}: {a['nome']} - {a.get('descrizione', '')}" + (f" (non confondere: {nc})" if nc else "")


def prefissi(ids) -> list[str]:
    d = per_id()
    out = []
    for i in ids:
        for r in (d.get(i) or {}).get("rs") or []:
            if r not in out:
                out.append(str(r))
    return out


def controlla(elenco: list[dict] | None = None, sr_validi: set | None = None) -> list[str]:
    """Problemi del file: campi mancanti, id ripetuti, collegamenti a id inesistenti, numeri RS sconosciuti."""
    elenco = tutti() if elenco is None else elenco
    errori, visti = [], set()
    ids = {a.get("id") for a in elenco}
    for a in elenco:
        i = a.get("id", "?")
        if i in visti:
            errori.append(f"{i}: id ripetuto")
        visti.add(i)
        for k in OBBLIGATORI:
            if k not in a:
                errori.append(f"{i}: manca {k}")
        for k in (a.get("collegati") or []):
            if k not in ids:
                errori.append(f"{i}: collegato inesistente {k}")
        if a.get("padre") is not None and a.get("padre") not in ids:
            errori.append(f"{i}: padre inesistente {a.get('padre')}")
        if sr_validi is not None:
            for t in a.get("atti") or []:
                if t not in sr_validi:
                    errori.append(f"{i}: atto non in archivio {t}")
    return errori
