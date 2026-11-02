"""Tribunale federale: ricerca nelle banche dati ufficiali delle sentenze.

Due raccolte sul sito del Tribunale federale (bger.ch):
  - "Tutte le sentenze" (aza): gran parte delle decisioni dal 2000, tutte le decisioni finali dal 2007
  - "DTF" (clir): decisioni principali pubblicate nella raccolta ufficiale (es. DTF 145 III 225)

Il sito non offre un'API: si legge l'HTML delle pagine di ricerca. Il lettore e volutamente
tollerante (cerca i link alle decisioni, non una struttura precisa) e la prima esecuzione reale
serve a confermarlo: il comando `verifica-fonti` dice quanti risultati ha riconosciuto.
"""

from __future__ import annotations

import html
import re
import urllib.parse

from . import sources

BASE = "https://www.bger.ch/ext/eurospider/live/{lang}/php/{coll}/http/index.php"
LANGS = {"it": "it", "de": "de", "fr": "fr", "en": "de", "rm": "de"}


def _search_url(coll: str, query: str, lang: str, from_date: str = "", to_date: str = "") -> str:
    lang = LANGS.get(lang, "it")
    params = {"lang": lang, "type": "simple_query", "query_words": query, "from_date": from_date,
              "to_date": to_date, "x": "0", "y": "0"}
    if coll == "aza":
        params["top_subcollection_aza"] = "all"
    else:
        params["top_subcollection_clir"] = "all"
    return BASE.format(lang=lang, coll=coll) + "?" + urllib.parse.urlencode(params)


def _doc_url(coll: str, docid: str, lang: str) -> str:
    lang = LANGS.get(lang, "it")
    return BASE.format(lang=lang, coll=coll) + "?" + urllib.parse.urlencode(
        {"highlight_docid": docid, "lang": lang, "type": "show_document"})


def _strip(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


# il docid compare sia in chiaro (aza://...) sia codificato nell'URL (aza%3A%2F%2F...)
DOCID_RE = re.compile(r"highlight_docid=((?:aza|atf)(?:://|%3A%2F%2F)[^&\"'\s]+)", re.IGNORECASE)


def parse_results(page: str, coll: str, lang: str, limit: int) -> list[dict]:
    """Estrae le decisioni da una pagina di risultati: identificativo, numero, data, estratto."""
    out, seen = [], set()
    for m in DOCID_RE.finditer(page):
        docid = urllib.parse.unquote(m.group(1))
        if docid in seen:
            continue
        seen.add(docid)
        # testo attorno al link: numero di incarto, data e un estratto
        window = page[m.start(): m.start() + 1500]
        text = _strip(window)
        kind = "DTF" if docid.startswith("atf://") else "TF"
        ref = re.sub(r":[a-z]{2}$", "", docid.split("://", 1)[1])  # via il suffisso di lingua (":it")
        if kind == "DTF":
            numero = ref.replace("-", " ")  # atf://145-III-225 -> 145 III 225
            data = ""
        else:
            # aza://12-03-2024-4A_123-2023 -> data 2024-03-12, incarto 4A_123/2023
            mm = re.match(r"(\d{2})-(\d{2})-(\d{4})-(.+)$", ref)
            if mm:
                data = f"{mm.group(3)}-{mm.group(2)}-{mm.group(1)}"
                numero = mm.group(4).replace("-", "/")
            else:
                data, numero = "", ref
        out.append({"tipo": kind, "numero": numero, "data": data, "docid": docid,
                    "estratto": text[:300], "url": _doc_url(coll, docid, lang)})
        if len(out) >= limit:
            break
    return out


def describe_docid(docid: str) -> tuple[str, str, str]:
    """(tipo, numero, data) da un identificativo: aza://12-03-2024-4A_123-2023 -> ('TF', '4A_123/2023', '2024-03-12')."""
    kind = "DTF" if docid.startswith("atf://") else "TF"
    ref = re.sub(r":[a-z]{2}$", "", docid.split("://", 1)[1])
    if kind == "DTF":
        return kind, ref.replace("-", " "), ""
    mm = re.match(r"(\d{2})-(\d{2})-(\d{4})-(.+)$", ref)
    if mm:
        return kind, mm.group(4).replace("-", "/"), f"{mm.group(3)}-{mm.group(2)}-{mm.group(1)}"
    return kind, ref, ""


def search(query: str, lang: str = "it", collection: str = "tutte", limit: int = 10,
           from_date: str = "", to_date: str = "") -> list[dict]:
    """Ricerca a testo pieno. collection: 'tutte' (aza) oppure 'dtf' (decisioni principali)."""
    coll = "clir" if collection.lower() in ("dtf", "atf", "bge", "clir") else "aza"
    page = sources.fetch_text(_search_url(coll, query, lang, from_date, to_date), timeout=60)
    return parse_results(page, coll, lang, limit)


def decision_text(docid: str, lang: str = "it", max_chars: int = 12000) -> dict:
    """Testo di una decisione a partire dal suo identificativo (aza://... o atf://...)."""
    coll = "clir" if docid.startswith("atf://") else "aza"
    url = _doc_url(coll, docid, lang)
    page = sources.fetch_text(url, timeout=60)
    # il corpo della decisione e la parte piu lunga della pagina: togliamo testa e navigazione
    body = page
    for marker in ("<div class=\"content\"", "<div id=\"content\"", "<body"):
        k = page.find(marker)
        if k >= 0:
            body = page[k:]
            break
    text = _strip(body)
    # considerandi: il testo utile inizia di solito con "Fatti" / "Sachverhalt" / "Faits"
    for start in ("Fatti", "Sachverhalt", "Faits", "Considerando", "Erwägungen", "Considérant"):
        k = text.find(start)
        if 0 <= k < 4000:
            text = text[k:]
            break
    return {"docid": docid, "url": url, "testo": text[:max_chars], "troncato": len(text) > max_chars}
