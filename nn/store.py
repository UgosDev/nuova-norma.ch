"""Archivio locale in SQLite. Lo schema e pensato per passare a PostgreSQL senza cambiamenti di sostanza.

Ogni versione ha due tempi:
  - date_applicability: da quando vale per legge (data Fedlex)
  - fetched_at: quando l'abbiamo letta noi (serve a dimostrare cosa sapevamo e quando)
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .akn import ActText, Article

SCHEMA = """
CREATE TABLE IF NOT EXISTS acts (
  uri        TEXT PRIMARY KEY,           -- es. https://fedlex.data.admin.ch/eli/cc/2022/491
  sr_number  TEXT,
  title      TEXT,
  in_force   INTEGER NOT NULL DEFAULT 1  -- 0 = abrogato: resta consultabile come storia, fuori dalla ricerca
);
CREATE TABLE IF NOT EXISTS versions (
  id                 INTEGER PRIMARY KEY,
  act_uri            TEXT NOT NULL REFERENCES acts(uri),
  lang               TEXT NOT NULL,
  date_applicability TEXT NOT NULL,
  title              TEXT,
  source_url         TEXT NOT NULL,
  sha256             TEXT NOT NULL,      -- impronta del file grezzo archiviato
  fetched_at         TEXT NOT NULL,
  UNIQUE (act_uri, lang, date_applicability)
);
CREATE TABLE IF NOT EXISTS articles (
  version_id INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
  position   INTEGER NOT NULL,
  eid        TEXT NOT NULL,
  num        TEXT,
  heading    TEXT,
  text       TEXT NOT NULL,
  text_hash  TEXT NOT NULL,
  path       TEXT,                       -- JSON: capitoli e sezioni
  notes      TEXT,                       -- JSON: note a pie di pagina
  PRIMARY KEY (version_id, eid)
);
CREATE INDEX IF NOT EXISTS idx_versions_act ON versions(act_uri, lang, date_applicability);
"""


def _modo_wal(con: sqlite3.Connection) -> None:
    """Giornale WAL: chi legge non aspetta chi scrive (le squadre leggono in parallelo mentre altre importano).
    Si chiede una volta sola per archivio, poi resta. Dove il file system non lo permette (cartelle di rete,
    certe cartelle condivise) SQLite resta nel modo precedente e tutto funziona come prima.
    NN_WAL=0 lo disattiva."""
    if os.environ.get("NN_WAL", "1") == "0":
        return
    try:
        if con.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
            con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = NORMAL")   # sicuro con WAL: si puo perdere solo l'ultima scrittura
    except sqlite3.Error:
        pass


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 30000")  # due processi sullo stesso archivio si aspettano invece di fallire
    _modo_wal(con)
    con.executescript(SCHEMA)
    from . import cache_rete
    con.executescript(cache_rete.SCHEMA)
    # migrazione per archivi creati prima della colonna in_force
    cols = {r[1] for r in con.execute("PRAGMA table_info(acts)")}
    if "in_force" not in cols:
        con.execute("ALTER TABLE acts ADD COLUMN in_force INTEGER NOT NULL DEFAULT 1")
        con.execute("UPDATE acts SET in_force = 0 WHERE sr_number LIKE '%(abrogata)%'")
        con.commit()
    if "checked_at" not in cols:   # quando l'atto e stato confrontato con Fedlex l'ultima volta
        con.execute("ALTER TABLE acts ADD COLUMN checked_at TEXT")
        con.commit()
    return con


def mark_checked(con: sqlite3.Connection, act_uri: str) -> None:
    con.execute("UPDATE acts SET checked_at = ? WHERE uri = ?",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), act_uri))


def checked_within(act: sqlite3.Row, days: float) -> bool:
    """L'atto e stato confrontato con Fedlex da meno di `days` giorni."""
    try:
        quando = act["checked_at"]
    except (IndexError, KeyError):
        return False
    if not quando:
        return False
    try:
        t = datetime.fromisoformat(quando)
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() < days * 86400


def upsert_act(con: sqlite3.Connection, uri: str, sr_number: str, title: str, in_force: bool = True) -> None:
    if sr_number and in_force:
        # Un numero RS puo passare da una legge abrogata a quella nuova (es. 235.1 LPD 1992 -> nLPD 2023):
        # quella vecchia resta in archivio come storia, marcata abrogata e fuori dalla ricerca.
        con.execute(
            "UPDATE acts SET sr_number = sr_number || ' (abrogata)', in_force = 0 "
            "WHERE sr_number = ? AND uri <> ?", (sr_number, uri),
        )
    con.execute(
        "INSERT INTO acts(uri, sr_number, title, in_force) VALUES (?,?,?,?) "
        "ON CONFLICT(uri) DO UPDATE SET sr_number=excluded.sr_number, title=excluded.title, in_force=excluded.in_force",
        (uri, sr_number, title, 1 if in_force else 0),
    )


def has_version(con: sqlite3.Connection, act_uri: str, lang: str, date: str) -> bool:
    return con.execute(
        "SELECT 1 FROM versions WHERE act_uri=? AND lang=? AND date_applicability=?",
        (act_uri, lang, date),
    ).fetchone() is not None


def save_version(
    con: sqlite3.Connection, act_uri: str, lang: str, date: str,
    source_url: str, sha256: str, act: ActText,
) -> int:
    cur = con.execute(
        "INSERT INTO versions(act_uri, lang, date_applicability, title, source_url, sha256, fetched_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (act_uri, lang, date, act.title, source_url, sha256,
         datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    vid = cur.lastrowid
    seen: set[str] = set()
    for i, a in enumerate(act.articles):
        eid = a.eid
        # Difesa contro identificativi duplicati nel sorgente
        while eid in seen:
            eid += "_dup"
        seen.add(eid)
        con.execute(
            "INSERT INTO articles(version_id, position, eid, num, heading, text, text_hash, path, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (vid, i, eid, a.num, a.heading, a.text, a.text_hash,
             json.dumps(a.path, ensure_ascii=False), json.dumps(a.notes, ensure_ascii=False)),
        )
    con.commit()
    return vid


def replace_articles(con: sqlite3.Connection, version_id: int, act: ActText) -> None:
    """Sostituisce gli articoli di una versione (dopo una nuova lettura del file originale)."""
    con.execute("DELETE FROM articles WHERE version_id=?", (version_id,))
    seen: set[str] = set()
    for i, a in enumerate(act.articles):
        eid = a.eid
        while eid in seen:
            eid += "_dup"
        seen.add(eid)
        con.execute(
            "INSERT INTO articles(version_id, position, eid, num, heading, text, text_hash, path, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (version_id, i, eid, a.num, a.heading, a.text, a.text_hash,
             json.dumps(a.path, ensure_ascii=False), json.dumps(a.notes, ensure_ascii=False)),
        )


def load_articles(con: sqlite3.Connection, act_uri: str, lang: str, date: str) -> list[Article]:
    row = con.execute(
        "SELECT id FROM versions WHERE act_uri=? AND lang=? AND date_applicability=?",
        (act_uri, lang, date),
    ).fetchone()
    if row is None:
        raise LookupError(f"Versione {date} ({lang}) non presente in archivio")
    return [
        Article(r["eid"], r["num"] or "", r["heading"] or "", r["text"],
                json.loads(r["path"] or "[]"), json.loads(r["notes"] or "[]"))
        for r in con.execute(
            "SELECT * FROM articles WHERE version_id=? ORDER BY position", (row["id"],)
        )
    ]


def list_dates(con: sqlite3.Connection, act_uri: str, lang: str) -> list[str]:
    return [
        r[0] for r in con.execute(
            "SELECT date_applicability FROM versions WHERE act_uri=? AND lang=? ORDER BY 1",
            (act_uri, lang),
        )
    ]


def in_force_date(dates: list[str], today: str | None = None) -> str:
    """Versione in vigore oggi: l'ultima con data <= oggi (le versioni future sono modifiche in arrivo, non testo vigente).
    Se tutte le versioni sono future (atto non ancora in vigore) restituisce la piu vicina."""
    import datetime
    today = today or datetime.date.today().isoformat()
    past = [d for d in dates if d <= today]
    return past[-1] if past else dates[0]


def find_act(con: sqlite3.Connection, ref: str) -> sqlite3.Row | None:
    """Per numero RS preferisce l'atto in vigore; un atto abrogato si trova con 'RS (abrogata)' o per URI."""
    return con.execute(
        "SELECT * FROM acts WHERE uri=? OR sr_number=? ORDER BY in_force DESC LIMIT 1", (ref, ref)
    ).fetchone()


# ---------------------------------------------------------------------------
# Riferimenti agli articoli ("Art. 958f" -> "958f")
# ---------------------------------------------------------------------------

def art_key(num: str) -> str:
    import re
    return re.sub(r"^(art|articolo|artikel|article)", "", re.sub(r"[\s.]", "", num.lower()))


def find_article(con: sqlite3.Connection, uri: str, lang: str, art: str, date: str | None = None) -> Article | None:
    dates = list_dates(con, uri, lang)
    if not dates:
        return None
    if date is None:
        date = in_force_date(dates)
    elif date not in dates:
        # versione in vigore a quella data: l'ultima con data di validita <= data richiesta
        earlier = [d for d in dates if d <= date]
        if not earlier:
            return None
        date = earlier[-1]
    key = art_key(art)
    for a in load_articles(con, uri, lang, date):
        if art_key(a.num) == key or a.eid == art:
            return a
    return None


# ---------------------------------------------------------------------------
# Ricerca full-text sulle versioni piu recenti (SQLite FTS5, con ripiego semplice)
# ---------------------------------------------------------------------------

SEARCH_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
  sr UNINDEXED, lang UNINDEXED, act_uri UNINDEXED, eid UNINDEXED, date UNINDEXED,
  title, num, heading, text,
  tokenize = 'unicode61 remove_diacritics 2'
);
"""


def _has_fts5(con: sqlite3.Connection) -> bool:
    try:
        con.executescript(SEARCH_SCHEMA)
        return True
    except sqlite3.OperationalError:
        return False


def rubrica(heading: str | None, path) -> str:
    """La rubrica dell'articolo. Nei codici (CO, CC...) gli articoli non ne hanno una propria: il titolo marginale sta
    nelle sezioni che li contengono ("III. Protezione dalla disdetta > 2. Disdetta in tempo inopportuno"), e senza
    di esso la ricerca non capisce di che cosa parla l'articolo. Si usano le ultime due sezioni."""
    if heading and heading.strip():
        return heading.strip()
    if isinstance(path, str):
        try:
            path = json.loads(path or "[]")
        except ValueError:
            path = []
    sezioni = [str(x).strip() for x in (path or []) if str(x).strip()]
    return " > ".join(sezioni[-2:])


def rebuild_search(con: sqlite3.Connection, act_uri: str | None = None) -> int:
    """Ricostruisce l'indice con la versione in vigore oggi di ogni atto e lingua. Restituisce il numero di articoli.
    Con act_uri ricostruisce solo quell'atto (dopo un'importazione): le altre leggi restano come sono e
    l'operazione dura millisecondi invece di riscrivere tutto l'archivio. L'aggiornamento notturno fa quella completa,
    che tiene conto anche delle versioni entrate in vigore nel frattempo."""
    solo = "AND v.act_uri = ?" if act_uri else ""
    latest = con.execute(f"""
        SELECT v.id, v.act_uri, v.lang, v.date_applicability, COALESCE(a.sr_number, '') AS sr,
               COALESCE(a.title, v.title, '') AS title
        FROM versions v JOIN acts a ON a.uri = v.act_uri
        WHERE a.in_force = 1
          AND v.date_applicability = (SELECT MAX(date_applicability) FROM versions w
                                      WHERE w.act_uri = v.act_uri AND w.lang = v.lang
                                        AND w.date_applicability <= date('now'))
          {solo}""", (act_uri,) if act_uri else ()).fetchall()
    if not _has_fts5(con):
        return 0
    if act_uri:
        con.execute("DELETE FROM search WHERE act_uri = ?", (act_uri,))
        # un'importazione puo aver marcato abrogata la legge che aveva lo stesso numero RS: esce dalla ricerca
        con.execute("DELETE FROM search WHERE act_uri IN (SELECT uri FROM acts WHERE in_force = 0)")
    else:
        con.execute("DELETE FROM search")
    n = 0
    for v in latest:
        for r in con.execute("SELECT eid, num, heading, path, text FROM articles WHERE version_id=?", (v["id"],)).fetchall():
            con.execute(
                "INSERT INTO search(sr, lang, act_uri, eid, date, title, num, heading, text) VALUES (?,?,?,?,?,?,?,?,?)",
                (v["sr"], v["lang"], v["act_uri"], r["eid"], v["date_applicability"], v["title"],
                 r["num"], rubrica(r["heading"], r["path"]), r["text"]),
            )
            n += 1
    con.commit()
    return n


def _terms(query: str) -> list[str]:
    import re
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) >= 3]
    # Radice grezza: "conservazione" e "conservare" condividono "conser"
    return list(dict.fromkeys(w[:6] if len(w) > 6 else w for w in words))[:12]


def search(con: sqlite3.Connection, query: str, lang: str | None = None,
           sr: str | None = None, limit: int = 8) -> list[dict]:
    terms = _terms(query)
    if not terms:
        return []
    where, params = [], []
    if lang:
        where.append("lang = ?")
        params.append(lang)
    if sr:
        where.append("sr = ?")
        params.append(sr)
    if _has_fts5(con):
        match = " OR ".join(f'"{t}"*' for t in terms)
        sql = ("SELECT sr, lang, act_uri, eid, date, title, num, heading, "
               "snippet(search, 8, '', '', ' ... ', 24) AS excerpt "
               "FROM search WHERE search MATCH ?" + "".join(f" AND {w}" for w in where) +
               " ORDER BY bm25(search, 0, 0, 0, 0, 0, 1.0, 2.0, 4.0, 1.0) LIMIT ?")
        rows = con.execute(sql, [match, *params, limit]).fetchall()
    else:  # ripiego senza FTS5: conta i termini presenti
        rows = []
        for r in con.execute("""
            SELECT COALESCE(a.sr_number,'') AS sr, v.lang, v.act_uri, ar.eid, v.date_applicability AS date,
                   COALESCE(a.title,'') AS title, ar.num, ar.heading, ar.text
            FROM articles ar JOIN versions v ON v.id = ar.version_id JOIN acts a ON a.uri = v.act_uri
            WHERE a.in_force = 1
              AND v.date_applicability = (SELECT MAX(date_applicability) FROM versions w
                                          WHERE w.act_uri = v.act_uri AND w.lang = v.lang
                                            AND w.date_applicability <= date('now'))""").fetchall():
            if (lang and r["lang"] != lang) or (sr and r["sr"] != sr):
                continue
            low = f"{r['heading']} {r['text']}".lower()
            score = sum(low.count(t) for t in terms)
            if score:
                d = dict(r)
                d["excerpt"] = r["text"][:200]
                rows.append((score, d))
        rows = [d for _, d in sorted(rows, key=lambda x: -x[0])[:limit]]
    return [dict(r) for r in rows]
