"""Archivio comune per le fonti che non sono testi di legge in XML: direttive, circolari, promemoria,
guide, sentenze cantonali, votazioni popolari, leggi cantonali in PDF/HTML.

Stesso principio dell'archivio Fedlex:
  - ogni file scaricato si conserva in data/raw/ con il nome della sua impronta SHA-256 e non si sovrascrive mai;
  - una nuova impronta per lo stesso documento e una nuova versione, con la data dichiarata dalla fonte
    ("Stato al", "valido dal") e il momento in cui l'abbiamo letta;
  - un documento che la fonte non elenca piu resta in archivio, marcato "non piu pubblicato".

Ogni fonte ha un livello (vedi sources.LIVELLI): l'agente lo mostra, cosi una direttiva non viene mai
presentata come legge.
"""

from __future__ import annotations

import hashlib
import html as _html
import io
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS doc_items (
  source        TEXT NOT NULL,             -- id della fonte in sources.SOURCES
  key           TEXT NOT NULL,             -- identificativo stabile nella fonte (es. "CIGI", "2023/1", "1.01")
  lang          TEXT NOT NULL DEFAULT 'it',
  title         TEXT NOT NULL,
  kind          TEXT NOT NULL,             -- direttiva | circolare | promemoria | guida | sentenza | votazione | legge_cantonale ...
  url           TEXT NOT NULL,             -- da dove si scarica il testo
  page_url      TEXT,                      -- pagina pubblica da mostrare all'utente, se diversa
  meta          TEXT NOT NULL DEFAULT '{}',
  discovered_at TEXT NOT NULL,
  last_seen     TEXT NOT NULL,
  gone          INTEGER NOT NULL DEFAULT 0, -- 1 = la fonte non lo elenca piu
  PRIMARY KEY (source, key, lang)
);
CREATE TABLE IF NOT EXISTS doc_versions (
  id           INTEGER PRIMARY KEY,
  source       TEXT NOT NULL,
  key          TEXT NOT NULL,
  lang         TEXT NOT NULL,
  valid_from   TEXT,                       -- data dichiarata dalla fonte (AAAA-MM-GG), se c'e
  sha256       TEXT NOT NULL,
  ext          TEXT NOT NULL,
  url          TEXT NOT NULL,
  fetched_at   TEXT NOT NULL,
  text         TEXT NOT NULL,
  UNIQUE (source, key, lang, sha256)
);
CREATE INDEX IF NOT EXISTS idx_doc_versions ON doc_versions(source, key, lang, fetched_at);
"""
FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS doc_search USING fts5(
  source UNINDEXED, key UNINDEXED, lang UNINDEXED, version_id UNINDEXED, kind UNINDEXED, title, text,
  tokenize = 'unicode61 remove_diacritics 2'
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure(con: sqlite3.Connection) -> bool:
    """Crea le tabelle. Vero se e disponibile la ricerca a testo pieno (FTS5)."""
    con.executescript(SCHEMA)
    try:
        con.executescript(FTS)
        return True
    except sqlite3.OperationalError:
        return False


@dataclass
class Item:
    """Un documento come lo elenca la fonte."""
    source: str
    key: str
    title: str
    kind: str
    url: str
    lang: str = "it"
    page_url: str = ""
    valid_from: str = ""                      # se la fonte la dichiara gia nell'elenco
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------- estrazione del testo

def pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # dipendenza facoltativa: py -m pip install pypdf
    except ImportError as e:
        raise RuntimeError("Per leggere i PDF serve il pacchetto pypdf: esegui  py -m pip install pypdf") from e
    reader = PdfReader(io.BytesIO(data))
    pages = [(p.extract_text() or "") for p in reader.pages]
    return _tidy("\n".join(pages))


def html_text(page: str, main: bool = True) -> str:
    """Testo leggibile di una pagina HTML: niente menu, script e piedi di pagina; a capo tra i blocchi.
    main=True: se la pagina ha <main> o <article>, si tiene solo quello."""
    m = main and re.search(r"(?is)<main\b[^>]*>(.*)</main>", page) or re.search(r"(?is)<article\b[^>]*>(.*)</article>", page)
    if m and len(m.group(1)) > 500:
        page = m.group(1)
    page = re.sub(r"(?is)<(script|style|nav|header|footer|noscript|svg|form)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?s)<!--.*?-->", " ", page)
    page = re.sub(r"(?i)</(p|div|li|h\d|tr|section|table|ul|ol|dd|dt)>|<br\s*/?>", "\n", page)
    text = _html.unescape(re.sub(r"<[^>]+>", " ", page))
    return _tidy(text)


def _tidy(text: str) -> str:
    text = re.sub(r"[﻿​‌‍\xad]", "", text)
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"-\n(?=[a-zàèéìòù])", "", text)          # parola spezzata a fine riga nei PDF
    text = re.sub(r" ([,.;:)\]])", r"\1", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract(raw: bytes, content_type: str = "") -> tuple[str, str]:
    """(testo, estensione) da un file scaricato, PDF o HTML."""
    if raw[:5] == b"%PDF-" or "pdf" in content_type:
        return pdf_text(raw), "pdf"
    for enc in ("utf-8", "iso-8859-1"):
        try:
            page = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        page = raw.decode("utf-8", "replace")
    if "<" in page[:2000] and re.search(r"(?i)<(html|body|div|p)\b", page[:5000]):
        return html_text(page), "html"
    return _tidy(page), "txt"


# ---------------------------------------------------------------- date dichiarate dalle fonti

MESI = {m: i for i, m in enumerate(
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split(), 1)}
MESI.update({m: i for i, m in enumerate(
    "januar februar märz april mai juni juli august september oktober november dezember".split(), 1)})
MESI.update({m: i for i, m in enumerate(
    "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split(), 1)})
_DATA_LUNGA = re.compile(r"(\d{1,2})\.?\s*(?:°|º|o|er)?\s+([a-zäöüéèû]+)\s+(\d{4})", re.IGNORECASE)
_DATA_NUM = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_ANNUNCI = re.compile(
    r"(?:stato\s+al|valid[ao]\s+dal|in\s+vigore\s+dal|entrat[ao]\s+in\s+vigore\s+il|stand\s*(?:am|:)?|"
    r"gültig\s+ab|g[üu]ltig\s+seit|in\s+kraft\s+(?:seit|ab)|état\s+au|valable\s+(?:dès|à\s+partir)\s+du|"
    r"en\s+vigueur\s+(?:dès|depuis)\s+le)\s*:?\s*", re.IGNORECASE)


def parse_date(text: str) -> str:
    """'1° gennaio 2026' / '1.1.2026' / '1er janvier 2026' -> '2026-01-01'; '' se non riconosciuta."""
    m = _DATA_NUM.search(text)
    if m:
        g, me, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= me <= 12 and 1 <= g <= 31:
            return f"{a:04d}-{me:02d}-{g:02d}"
    m = _DATA_LUNGA.search(text)
    if m and m.group(2).lower() in MESI:
        return f"{int(m.group(3)):04d}-{MESI[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre|"
                  r"januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember|"
                  r"janvier|février|mars|avril|juin|juillet|août|septembre|octobre|décembre)\s+(\d{4})", text, re.IGNORECASE)
    if m:
        return f"{int(m.group(1)):04d}-{MESI[m.group(0).split()[0].lower()]:02d}-01"
    return ""


def declared_date(text: str, head: int = 4000) -> str:
    """Data di validita dichiarata nelle prime righe del documento ("Stato al 1° gennaio 2026")."""
    part = text[:head]
    for m in _ANNUNCI.finditer(part):
        d = parse_date(part[m.end():m.end() + 40])
        if d:
            return d
    return ""


# ---------------------------------------------------------------- archivio

def save_item(con: sqlite3.Connection, it: Item, seen_at: str | None = None) -> None:
    t = seen_at or now()
    con.execute(
        "INSERT INTO doc_items(source, key, lang, title, kind, url, page_url, meta, discovered_at, last_seen, gone) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,0) ON CONFLICT(source, key, lang) DO UPDATE SET title=excluded.title, "
        "kind=excluded.kind, url=excluded.url, page_url=excluded.page_url, meta=excluded.meta, last_seen=excluded.last_seen, gone=0",
        (it.source, it.key, it.lang, it.title, it.kind, it.url, it.page_url or it.url,
         json.dumps(it.meta, ensure_ascii=False), t, t))


def mark_gone(con: sqlite3.Connection, source: str, seen_keys: set[tuple[str, str]]) -> int:
    """Marca 'non piu pubblicati' i documenti di una fonte che l'ultimo elenco completo non contiene."""
    n = 0
    for r in con.execute("SELECT key, lang FROM doc_items WHERE source=? AND gone=0", (source,)).fetchall():
        if (r["key"], r["lang"]) not in seen_keys:
            con.execute("UPDATE doc_items SET gone=1 WHERE source=? AND key=? AND lang=?", (source, r["key"], r["lang"]))
            n += 1
    return n


def save_version(con: sqlite3.Connection, it: Item, raw: bytes, raw_dir: Path, content_type: str = "",
                 text: str | None = None) -> dict:
    """Archivia il file e il suo testo. Se la stessa impronta c'e gia, non crea nulla."""
    sha = hashlib.sha256(raw).hexdigest()
    old = con.execute("SELECT id, valid_from FROM doc_versions WHERE source=? AND key=? AND lang=? AND sha256=?",
                      (it.source, it.key, it.lang, sha)).fetchone()
    if old:
        return {"nuova": False, "id": old["id"], "sha256": sha, "valid_from": old["valid_from"]}
    if text is None:
        text, ext = extract(raw, content_type)
    else:
        ext = "pdf" if raw[:5] == b"%PDF-" else "html" if b"<" in raw[:200] else "txt"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{sha}.{ext}"
    if not path.exists():
        path.write_bytes(raw)
    valid = it.valid_from or declared_date(text)
    cur = con.execute("INSERT INTO doc_versions(source, key, lang, valid_from, sha256, ext, url, fetched_at, text) "
                      "VALUES (?,?,?,?,?,?,?,?,?)", (it.source, it.key, it.lang, valid or None, sha, ext, it.url, now(), text))
    _index(con, it, cur.lastrowid, text)
    return {"nuova": True, "id": cur.lastrowid, "sha256": sha, "valid_from": valid}


def _index(con: sqlite3.Connection, it: Item, version_id: int, text: str) -> None:
    """Nell'indice di ricerca resta solo l'ultima versione di ogni documento."""
    try:
        con.execute("DELETE FROM doc_search WHERE source=? AND key=? AND lang=?", (it.source, it.key, it.lang))
        con.execute("INSERT INTO doc_search(source, key, lang, version_id, kind, title, text) VALUES (?,?,?,?,?,?,?)",
                    (it.source, it.key, it.lang, version_id, it.kind, it.title, text))
    except sqlite3.OperationalError:
        pass  # senza FTS5 la ricerca usa il ripiego in search()


def latest(con: sqlite3.Connection, source: str, key: str, lang: str | None = None) -> dict | None:
    q = ("SELECT i.*, v.id AS version_id, v.valid_from, v.sha256, v.fetched_at, v.text, v.ext "
         "FROM doc_items i JOIN doc_versions v ON v.source=i.source AND v.key=i.key AND v.lang=i.lang "
         "WHERE i.source=? AND i.key=?" + (" AND i.lang=?" if lang else "") +
         " ORDER BY (i.lang='it') DESC, COALESCE(v.valid_from,'') DESC, v.fetched_at DESC LIMIT 1")
    r = con.execute(q, (source, key, lang) if lang else (source, key)).fetchone()
    return dict(r) if r else None


def history(con: sqlite3.Connection, source: str, key: str, lang: str = "it") -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT id, valid_from, sha256, fetched_at, url, LENGTH(text) AS caratteri FROM doc_versions "
        "WHERE source=? AND key=? AND lang=? ORDER BY COALESCE(valid_from,''), fetched_at", (source, key, lang))]


def find(con: sqlite3.Connection, source: str, ref: str) -> dict | None:
    """Un documento per chiave esatta, poi per chiave senza spazi e maiuscole, poi per titolo."""
    ref = ref.strip()
    r = latest(con, source, ref)
    if r:
        return r
    norm = re.sub(r"\s+", "", ref).lower()
    for row in con.execute("SELECT key FROM doc_items WHERE source=?", (source,)):
        if re.sub(r"\s+", "", row["key"]).lower() == norm:
            return latest(con, source, row["key"])
    for row in con.execute("SELECT key, meta FROM doc_items WHERE source=?", (source,)):
        m = json.loads(row["meta"] or "{}")
        if norm in {re.sub(r"\s+", "", str(m.get(k, ""))).lower() for k in ("sigla", "numero")} - {""}:
            return latest(con, source, row["key"])
    row = con.execute("SELECT key FROM doc_items WHERE source=? AND LOWER(title) LIKE ? ORDER BY gone LIMIT 1",
                      (source, f"%{ref.lower()}%")).fetchone()
    return latest(con, source, row["key"]) if row else None


def _terms(query: str) -> list[str]:
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) >= 3]
    return list(dict.fromkeys(w[:6] if len(w) > 6 else w for w in words))[:12]


def search(con: sqlite3.Connection, query: str, sources: list[str] | None = None, kind: str | None = None,
           lang: str | None = None, limit: int = 10) -> list[dict]:
    """Ricerca a testo pieno sull'ultima versione dei documenti. Restituisce estratti, non testi completi."""
    terms = _terms(query)
    if not terms:
        return []
    where, params = [], []
    if sources:
        where.append("source IN (%s)" % ",".join("?" * len(sources)))
        params += sources
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if lang:
        where.append("lang = ?")
        params.append(lang)
    try:
        match = " OR ".join(f'"{t}"*' for t in terms)
        rows = con.execute(
            "SELECT source, key, lang, version_id, kind, title, snippet(doc_search, 6, '', '', ' ... ', 28) AS estratto "
            "FROM doc_search WHERE doc_search MATCH ?" + "".join(f" AND {w}" for w in where) +
            " ORDER BY bm25(doc_search, 0, 0, 0, 0, 0, 3.0, 1.0) LIMIT ?", [match, *params, limit]).fetchall()
        out = [dict(r) for r in rows]
    except sqlite3.OperationalError:
        out = []
        sql = ("SELECT v.source, v.key, v.lang, v.id AS version_id, i.kind, i.title, v.text FROM doc_versions v "
               "JOIN doc_items i ON i.source=v.source AND i.key=v.key AND i.lang=v.lang "
               "WHERE v.id = (SELECT MAX(id) FROM doc_versions w WHERE w.source=v.source AND w.key=v.key AND w.lang=v.lang)")
        scored = []
        for r in con.execute(sql):
            if (sources and r["source"] not in sources) or (kind and r["kind"] != kind) or (lang and r["lang"] != lang):
                continue
            low = f"{r['title']} {r['text']}".lower()
            s = sum(low.count(t) for t in terms)
            if s:
                d = dict(r)
                d["estratto"] = d.pop("text")[:240]
                scored.append((s, d))
        out = [d for _, d in sorted(scored, key=lambda x: -x[0])[:limit]]
    for d in out:
        meta = con.execute("SELECT gone, page_url, meta FROM doc_items WHERE source=? AND key=? AND lang=?",
                           (d["source"], d["key"], d["lang"])).fetchone()
        d["non_piu_pubblicato"] = bool(meta and meta["gone"])
        d["url"] = meta["page_url"] if meta else ""
        m = json.loads(meta["meta"] or "{}") if meta else {}
        if m.get("livello"):
            d["livello_documento"] = m["livello"]
        if m.get("lingua_testo"):
            d["lingua_testo"] = m["lingua_testo"]
    return out


def stats(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT i.source, COUNT(DISTINCT i.key || '|' || i.lang) AS documenti, SUM(i.gone) AS non_piu_pubblicati, "
        "(SELECT COUNT(*) FROM doc_versions v WHERE v.source=i.source) AS versioni, MAX(i.last_seen) AS ultimo_controllo "
        "FROM doc_items i GROUP BY i.source ORDER BY i.source")]
