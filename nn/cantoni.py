"""Diritto cantonale. Primo cantone: Ticino (Raccolta delle leggi, RL).

La RL ticinese non offre un'API e i testi sono PDF. Strategia:
  1. `discover()` legge la pagina iniziale e le pagine di categoria e raccoglie tutti gli atti
     (numero RL, titolo, URL), salvandoli nell'archivio locale. Si fa una volta, poi si aggiorna.
  2. `search()` cerca nell'indice locale per numero o parole del titolo.
  3. `text()` scarica il PDF dell'atto e ne estrae il testo (serve il pacchetto `pypdf`).

Il sito puo cambiare: `verifica-fonti` stampa gli schemi di URL trovati, cosi un cambiamento si vede.
"""

from __future__ import annotations

import collections
import html
import json
import re
import sqlite3
import urllib.parse

from . import sources

TICINO_HOME = "https://m3.ti.ch/CAN/RLeggi/public/index.php"
RL_NUMBER = re.compile(r"\b(\d{3}\.\d{3}(?:\.\d{1,3})?)\b")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cantonal_acts (
  canton TEXT NOT NULL, act_key TEXT NOT NULL, number TEXT, title TEXT NOT NULL, url TEXT NOT NULL,
  pdf_url TEXT, discovered_at TEXT NOT NULL,
  PRIMARY KEY (canton, act_key)
);
"""

# Nella RL ticinese ogni atto ha piu indirizzi: legge/num/N (strutturato), legge-piatta/num/N (testo intero
# in una pagina), pdfatto/atto/N (PDF). Chiave = N; per il testo preferiamo la versione piatta in HTML.
ACT_ID_RE = re.compile(r"/(?:legge-piatta|legge|pdfatto)/(?:num|atto)/(\d+)")
PREFERRED = ("legge-piatta", "legge", "pdfatto")


def _rank(url: str) -> int:
    for i, kind in enumerate(PREFERRED):
        if f"/{kind}/" in url:
            return i
    return len(PREFERRED)


def _ensure(con: sqlite3.Connection) -> None:
    """Crea la tabella; se esiste con una struttura vecchia la ricrea (e un indice derivato dal sito)."""
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(cantonal_acts)")}
    if "act_key" not in cols:
        con.executescript("DROP TABLE cantonal_acts;" + SCHEMA)
        con.commit()


def _links(page: str, base: str) -> list[tuple[str, str]]:
    """Tutti i link (url assoluto, testo) di una pagina HTML."""
    out = []
    for m in re.finditer(r"<a\s[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", page, re.IGNORECASE | re.DOTALL):
        href = html.unescape(m.group(1).strip())
        if href.startswith(("javascript:", "#", "mailto:")):
            continue
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        out.append((urllib.parse.urljoin(base, href), text))
    return out


def discover(con: sqlite3.Connection, max_pages: int = 80, log=lambda *_: None) -> dict:
    """Esplora la RL ticinese a partire dalla pagina iniziale e indicizza gli atti trovati."""
    import datetime as _dt
    _ensure(con)
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    con.execute("DELETE FROM cantonal_acts WHERE canton='TI'")
    best: dict[str, tuple[int, str | None, str, str]] = {}  # act_key -> (rank, number, title, url)
    queue, seen, patterns = [TICINO_HOME], set(), {}
    while queue and len(seen) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            page = sources.fetch_text(url, timeout=45)
        except Exception as e:  # una pagina rotta non ferma l'esplorazione
            log(f"  pagina non letta: {url} ({e})")
            continue
        for href, text in _links(page, url):
            if "m3.ti.ch" not in href or "RLeggi" not in href:
                continue
            path = urllib.parse.urlparse(href).path
            shape = re.sub(r"/\d+", "/N", path)
            patterns[shape] = patterns.get(shape, 0) + 1
            num = RL_NUMBER.search(text)
            act = ACT_ID_RE.search(path)
            is_pdf = "pdfatto" in href or href.lower().endswith(".pdf")
            if act or num or is_pdf:
                key = act.group(1) if act else href
                title = RL_NUMBER.sub("", text).strip(" -–:") or text
                if not title:
                    continue
                cand = (_rank(href), num.group(1) if num else None, title[:300], href)
                prev = best.get(key)
                if prev is None or cand[0] < prev[0] or (cand[0] == prev[0] and not prev[1] and cand[1]):
                    # tieni il numero RL gia noto se la nuova forma non lo porta
                    best[key] = (cand[0], cand[1] or (prev[1] if prev else None), cand[2], cand[3])
            elif href not in seen and len(queue) < 400:
                queue.append(href)  # pagina di navigazione (libro, elenco)
        log(f"  letta {url} ({len(best)} atti finora)")
    for key, (_, number, title, href) in best.items():
        con.execute("INSERT OR REPLACE INTO cantonal_acts(canton, act_key, number, title, url, pdf_url, discovered_at) "
                    "VALUES ('TI', ?, ?, ?, ?, ?, ?)", (key, number, title, href, href if "pdfatto" in href else None, now))
    con.commit()
    return {"pagine_lette": len(seen), "atti_trovati": len(best),
            "schemi_url": dict(sorted(patterns.items(), key=lambda kv: -kv[1])[:12])}


def search(con: sqlite3.Connection, query: str, canton: str = "TI", limit: int = 10) -> list[dict]:
    _ensure(con)
    q = query.strip()
    rows = []
    if RL_NUMBER.fullmatch(q):
        rows = con.execute("SELECT * FROM cantonal_acts WHERE canton=? AND number=? LIMIT ?", (canton, q, limit)).fetchall()
    if not rows:
        words = [w for w in re.findall(r"\w+", q.lower()) if len(w) >= 3][:5]
        if not words:
            return []
        cond = " AND ".join("LOWER(title) LIKE ?" for _ in words)
        rows = con.execute(f"SELECT * FROM cantonal_acts WHERE canton=? AND {cond} LIMIT ?",
                           (canton, *[f"%{w}%" for w in words], limit)).fetchall()
    return [{"cantone": r["canton"], "numero": r["number"], "titolo": r["title"], "url": r["url"]} for r in rows]


def count(con: sqlite3.Connection, canton: str = "TI") -> int:
    _ensure(con)
    return con.execute("SELECT COUNT(*) FROM cantonal_acts WHERE canton=?", (canton,)).fetchone()[0]


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # dipendenza facoltativa: pip install pypdf
    except ImportError as e:
        raise RuntimeError("Per leggere i PDF della Raccolta ticinese serve il pacchetto pypdf: "
                           "esegui  py -m pip install pypdf") from e
    import io
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def text(con: sqlite3.Connection, url: str, max_chars: int = 15000) -> dict:
    """Testo di un atto cantonale (PDF o HTML) a partire dal suo URL nell'indice."""
    _ensure(con)
    row = con.execute("SELECT * FROM cantonal_acts WHERE url=?", (url,)).fetchone()
    target = (row["pdf_url"] or row["url"]) if row else url
    sources.assert_allowed(target)
    raw = sources.fetch(target, timeout=90)
    if raw[:5] == b"%PDF-":
        txt = _pdf_text(raw)
    else:
        page = raw.decode("utf-8", "replace")
        page = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", page)
        page = re.sub(r"(?s)<!--.*?-->", " ", page)
        # a capo tra blocchi, cosi articoli e capoversi restano distinti
        page = re.sub(r"(?i)</(p|div|li|h\d|tr|br)>|<br\s*/?>", "\n", page)
        txt = html.unescape(re.sub(r"<[^>]+>", " ", page))
        txt = re.sub(r"(<!--|-->)", " ", txt)
        txt = re.sub(r"[\ufeff\u200b\u200c\u200d\xad]", "", txt)  # caratteri invisibili (BOM, spazi a larghezza zero)
        txt = re.sub(r"[ \t]+", " ", txt)
        txt = re.sub(r" ([,.;:)\]])", r"\1", txt)  # "( del 2014 )" -> "(del 2014)"
        txt = re.sub(r"([(\[]) ", r"\1", txt)
        txt = "\n".join(line.strip() for line in txt.splitlines())
        txt = re.sub(r"\n{2,}", "\n", txt)
        # il testo utile comincia dal titolo dell'atto o, in mancanza, dal suo numero RL
        if row:
            base = re.split(r"\s[\(\-–]", row["title"] or "")[0].strip()  # titolo senza sigla e data
            m = re.search(r"\s+".join(re.escape(w) for w in base.split()[:8]), txt, re.IGNORECASE) if base else None
            k = m.start() if m else -1  # il titolo puo essere spezzato su piu righe
            if k <= 0 and row["number"]:
                k = txt.find(row["number"])
            if 0 < k < 3000:
                txt = txt[k:]
    txt = txt.strip()
    return {"cantone": row["canton"] if row else "TI", "numero": row["number"] if row else None,
            "titolo": row["title"] if row else "", "url": target,
            "testo": txt[:max_chars], "troncato": len(txt) > max_chars}


def _clean(page: str) -> str:
    page = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?s)<!--.*?-->", " ", page)
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    text = re.sub(r"(<!--|-->)", " ", text)  # residui di commenti spezzati
    text = re.sub(r"[\ufeff\u200b\u200c\u200d\xad]", "", text)  # caratteri invisibili
    return re.sub(r"\s+", " ", text).strip()


ART_RE = re.compile(r"\bArt\.?\s*\d")
BASE_ACT = "https://m3.ti.ch/CAN/RLeggi/public/index.php/raccolta-leggi/legge/num/"


def check_gaps(con: sqlite3.Connection, sample: int = 25, log=lambda *_: None) -> dict:
    """Verifica la completezza dell'indice su un campione dei numeri interni mancanti.

    Il sito risponde "pagina trovata" anche a numeri che non sono atti, quindi non basta il codice HTTP:
    ogni risposta si confronta con una pagina di controllo (numero sicuramente inesistente) e si cerca
    nel testo la presenza di articoli. Come prova che il metodo funziona, si controlla anche un atto noto."""
    import urllib.error
    _ensure(con)
    keys = sorted(int(r[0]) for r in con.execute("SELECT act_key FROM cantonal_acts WHERE canton='TI'") if str(r[0]).isdigit())
    if not keys:
        return {"errore": "indice vuoto: esegui prima  py -m nn indicizza-ticino"}
    have = set(keys)
    missing = [n for n in range(1, keys[-1] + 1) if n not in have]
    base = BASE_ACT

    def read(n: int) -> str | None:
        try:
            return _clean(sources.fetch_text(f"{base}{n}", timeout=30))
        except urllib.error.HTTPError as e:
            return f"HTTP {e.code}"
        except Exception as e:
            return f"errore {type(e).__name__}"

    control = read(999999) or ""
    known = read(keys[len(keys) // 2]) or ""
    control_ok = not ART_RE.search(control)
    known_ok = bool(ART_RE.search(known)) and known != control
    log(f"  controllo (numero inesistente): {len(control)} caratteri, articoli: {bool(ART_RE.search(control))}")
    log(f"  atto noto (id {keys[len(keys) // 2]}): {len(known)} caratteri, articoli: {bool(ART_RE.search(known))}")

    upcoming: dict[int, dict] = {}

    def classify(text: str, n: int = 0) -> str:
        if text.startswith(("HTTP ", "errore ")):
            return text
        if "non è contenuto nella Raccolta delle leggi" in text:
            # il sito usa la stessa pagina per i numeri inesistenti e per gli atti nuovi non ancora in vigore:
            # questi ultimi portano sotto la voce "PROSSIME VARIAZIONI" con numero RL e data
            m = re.search(r"NUOVO\s*(?:chiudi\s*-?\s*)?(?:NUOVO\s*)?(\d{3}\.\d{3}(?:\.\d+)?)\s*NUOVO.{0,40}?Variazione in vigore dal (\d{2}\.\d{2}\.\d{4})", text) \
                or re.search(r"(\d{3}\.\d{3}(?:\.\d+)?)\s*NUOVO.{0,40}?Variazione in vigore dal (\d{2}\.\d{2}\.\d{4})", text)
            if m:
                upcoming[n] = {"id": n, "numero": m.group(1), "dal": m.group(2)}
                return "atto in arrivo (non ancora in vigore)"
            return "inesistente (pagina vuota del sito)"
        if text == control or (not ART_RE.search(text) and abs(len(text) - len(control)) < 40):
            return "inesistente (pagina vuota del sito)"
        return "esiste: atto con articoli" if ART_RE.search(text) else "dubbio"

    step = max(1, len(missing) // sample)
    out = {"in_indice": len(keys), "massimo_id": keys[-1], "mancanti": len(missing), "campione": [],
           "controllo_affidabile": control_ok and known_ok, "esistenti": []}
    for n in missing[::step][:sample]:
        text = read(n) or ""
        state = classify(text, n)
        if state.startswith("esiste"):
            out["esistenti"].append(n)
        out["campione"].append({"id": n, "esito": state, "inizio": text[:400]})
        log(f"  id {n:4d}  {state}")
    out["riepilogo"] = dict(collections.Counter(c["esito"] for c in out["campione"]))
    out["dubbi"] = [c for c in out["campione"] if c["esito"] == "dubbio"]
    out["in_arrivo"] = sorted(upcoming.values(), key=lambda u: u["id"])
    return out


def page_text(n: int, max_chars: int = 3500) -> str:
    """Contenuto leggibile della pagina di un atto (per capire cosa e un numero dubbio)."""
    text = _clean(sources.fetch_text(f"{BASE_ACT}{int(n)}", timeout=30))
    k = text.find("DATA ULTIMO BU")  # salta l'intestazione comune a tutte le pagine
    return (text[k:] if k >= 0 else text)[:max_chars]
