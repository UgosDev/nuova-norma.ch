"""Memoria locale delle risposte delle fonti consultate dal vivo (bger.ch, Fedlex SPARQL, Curia Vista, opencaselaw).

Durante una domanda le squadre ripetono spesso le stesse ricerche: la seconda volta la risposta arriva
dall'archivio in millisecondi invece che dalla rete in secondi. Ogni voce ha una durata:
- testo di una sentenza: non cambia, resta un anno;
- ricerche (sentenze, titoli delle leggi): una settimana;
- novita, consultazioni, modifiche in arrivo, oggetti parlamentari: un giorno.

Non si conservano gli errori ne le risposte vuote: una ricerca fallita o senza risultati si ripete dal vivo.
La memoria sta nello stesso archivio SQLite, tabella `cache_rete`; se non si puo scrivere (archivio in sola
lettura, occupato) si va avanti senza: la memoria e un di piu, mai un requisito.
NN_CACHE_RETE=0 la disattiva."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_rete (
  chiave   TEXT PRIMARY KEY,   -- impronta di fonte + argomenti
  fonte    TEXT NOT NULL,      -- es. 'tf.sentenza', 'fedlex.titoli'
  valore   TEXT NOT NULL,      -- JSON
  salvato  REAL NOT NULL       -- secondi dall'epoca
);
CREATE INDEX IF NOT EXISTS idx_cache_rete_fonte ON cache_rete(fonte, salvato);
"""

GIORNO = 86400.0


def attiva() -> bool:
    return os.environ.get("NN_CACHE_RETE", "1") != "0"


def _pronta(con: sqlite3.Connection) -> bool:
    """La tabella esiste (la crea store.connect). Nessun executescript qui: chiuderebbe la transazione di chi chiama."""
    try:
        return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cache_rete'").fetchone() is not None
    except sqlite3.Error:
        return False


def _file(con: sqlite3.Connection) -> str:
    try:
        return next((r[2] for r in con.execute("PRAGMA database_list") if r[1] == "main"), "") or ""
    except sqlite3.Error:
        return ""


def chiave(fonte: str, args: tuple, kwargs: dict) -> str:
    testo = json.dumps([fonte, list(args), kwargs], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(testo.encode("utf-8")).hexdigest()


def prendi(con: sqlite3.Connection, k: str, giorni: float):
    """Il valore salvato da meno di `giorni` giorni, altrimenti None."""
    try:
        r = con.execute("SELECT valore, salvato FROM cache_rete WHERE chiave = ?", (k,)).fetchone()
    except sqlite3.Error:
        return None
    if r is None or time.time() - r[1] > giorni * GIORNO:
        return None
    try:
        return json.loads(r[0])
    except (TypeError, ValueError):
        return None


def metti(con: sqlite3.Connection, k: str, fonte: str, valore) -> None:
    """Scrive con una connessione propria e breve: la transazione di chi chiama resta com'e."""
    try:
        testo = json.dumps(valore, ensure_ascii=False)
    except (TypeError, ValueError):
        return
    riga = (k, fonte, testo, time.time())
    sql = "INSERT OR REPLACE INTO cache_rete(chiave, fonte, valore, salvato) VALUES (?,?,?,?)"
    percorso = _file(con)
    try:
        if percorso:
            altra = sqlite3.connect(percorso, timeout=2)
            try:
                altra.execute(sql, riga)
                altra.commit()
            finally:
                altra.close()
        else:   # archivio in memoria (prove): stessa connessione, senza commit
            con.execute(sql, riga)
    except sqlite3.Error:
        pass


def ricorda(con: sqlite3.Connection | None, fonte: str, giorni: float, fn, *args, **kwargs):
    """fn(*args, **kwargs), passando dalla memoria se c'e una risposta abbastanza recente."""
    if con is None or not attiva() or not _pronta(con):
        return fn(*args, **kwargs)
    k = chiave(fonte, args, kwargs)
    valore = prendi(con, k, giorni)
    if valore is not None:
        return valore
    valore = fn(*args, **kwargs)
    if valore not in (None, [], {}, ""):
        metti(con, k, fonte, valore)
    return valore


def pulisci(con: sqlite3.Connection, giorni: float = 400) -> int:
    """Toglie le voci piu vecchie di `giorni` (usato dall'aggiornamento notturno)."""
    if not _pronta(con):
        return 0
    cur = con.execute("DELETE FROM cache_rete WHERE salvato < ?", (time.time() - giorni * GIORNO,))
    con.commit()
    return cur.rowcount
