"""Client Fedlex: interroga l'endpoint SPARQL ufficiale e scarica i file dei testi.

Modello dati (JOLux, basato su FRBR):
  ConsolidationAbstract (l'atto nella RS, es. eli/cc/2022/491)
    <- jolux:isMemberOf -- Consolidation (una versione, con jolux:dateApplicability)
        -- jolux:isRealizedBy --> Expression (una lingua, jolux:language)
            -- jolux:isEmbodiedBy --> Manifestation (un formato, jolux:format)
                -- jolux:isExemplifiedBy --> URL del file
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import sources

SPARQL_ENDPOINT = "https://fedlex.data.admin.ch/sparqlendpoint"
PREFIX = ("PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>\n"
          "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"
          "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\n")
STATUS_IN_FORCE = "https://fedlex.data.admin.ch/vocabulary/enforcement-status/0"
STATUS_REPEALED = "https://fedlex.data.admin.ch/vocabulary/enforcement-status/3"

LANGUAGES = {
    "it": "http://publications.europa.eu/resource/authority/language/ITA",
    "de": "http://publications.europa.eu/resource/authority/language/DEU",
    "fr": "http://publications.europa.eu/resource/authority/language/FRA",
    "rm": "http://publications.europa.eu/resource/authority/language/ROH",
    "en": "http://publications.europa.eu/resource/authority/language/ENG",
}

def _http(req: urllib.request.Request, timeout: int = 60, retries: int = 3) -> bytes:
    return sources.fetch(req.full_url, data=req.data, headers=dict(req.header_items()),
                         timeout=timeout, retries=retries)


def sparql_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def sparql(query: str) -> list[dict[str, str]]:
    """Esegue una query SELECT e restituisce le righe come dizionari {variabile: valore}."""
    data = urllib.parse.urlencode({"query": PREFIX + query}).encode()
    req = urllib.request.Request(
        SPARQL_ENDPOINT,
        data=data,
        headers={
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    payload = json.loads(_http(req))
    return [{k: v["value"] for k, v in b.items()} for b in payload["results"]["bindings"]]


def sr_candidates(sr_number: str) -> list[dict[str, str]]:
    """Tutti gli atti che portano (o hanno portato) questo numero RS, con stato e date."""
    sr = sr_number.replace('"', "").strip()
    rows = sparql(f"""
SELECT DISTINCT ?ca ?status ?entry ?end WHERE {{
  ?ca a jolux:ConsolidationAbstract ; jolux:isRealizedBy ?expr .
  ?expr jolux:historicalLegalId ?sr .
  FILTER(str(?sr) = "{sr}")
  OPTIONAL {{ ?ca jolux:inForceStatus ?status . }}
  OPTIONAL {{ ?ca jolux:dateEntryInForce ?entry . }}
  OPTIONAL {{ ?ca jolux:dateNoLongerInForce ?end . }}
}}""")
    merged: dict[str, dict[str, str]] = {}
    for r in rows:
        merged.setdefault(r["ca"], {}).update({k: v for k, v in r.items() if v})
    out = list(merged.values())
    for c in out:
        titles = sparql(f"""
SELECT ?title WHERE {{ <{c['ca']}> jolux:isRealizedBy ?e . ?e jolux:language <{LANGUAGES['it']}> ; jolux:title ?title . }} LIMIT 1""")
        c["title"] = titles[0]["title"] if titles else ""
    return out


def _rank(c: dict[str, str]) -> tuple:
    """Ordina i candidati: prima quelli non abrogati, poi il piu recente."""
    import datetime
    import re

    today = datetime.date.today().isoformat()
    status = c.get("status", "")
    end = c.get("end", "")[:10]
    abrogated = status.endswith("/enforcement-status/3") or (end and end <= today)
    entry = c.get("entry", "")[:10]
    if not entry:  # ripiego: anno nell'URI ELI, es. eli/cc/2022/491
        m = re.search(r"/eli/cc/(\d{4})/", c["ca"])
        entry = f"{m.group(1)}-01-01" if m else ""
    return (not abrogated, entry)


def resolve_sr(sr_number: str) -> dict[str, str]:
    """Da un numero RS (es. '235.1') all'atto in vigore. Se ce ne sono piu, sceglie il piu recente non abrogato."""
    cands = sr_candidates(sr_number)
    if not cands:
        raise LookupError(f"Nessun atto trovato con numero RS {sr_number}")
    cands.sort(key=_rank, reverse=True)
    best = dict(cands[0])
    best["candidates"] = cands
    return best


@dataclass
class VersionFile:
    act_uri: str
    consolidation_uri: str
    date_applicability: str  # AAAA-MM-GG, da quando questa versione vale
    lang: str
    fmt: str  # URI del formato, es. .../file-type/XML
    url: str


def list_versions(act_uri: str, lang: str = "it") -> list[VersionFile]:
    """Tutte le versioni consolidate di un atto, in una lingua, con i file disponibili per formato."""
    rows = sparql(f"""
SELECT ?cons ?date ?fmt ?url WHERE {{
  ?cons jolux:isMemberOf <{act_uri}> ;
        jolux:dateApplicability ?date ;
        jolux:isRealizedBy ?expr .
  ?expr jolux:language <{LANGUAGES[lang]}> ;
        jolux:isEmbodiedBy ?man .
  ?man jolux:format ?fmt ;
       jolux:isExemplifiedBy ?url .
}} ORDER BY ?date""")
    return [
        VersionFile(act_uri, r["cons"], r["date"][:10], lang, r["fmt"], r["url"])
        for r in rows
    ]


def xml_versions(versions: list[VersionFile]) -> list[VersionFile]:
    """Tiene un solo file XML (Akoma Ntoso) per data. Fedlex pubblica l'XML dal 2022 in poi."""
    by_date: dict[str, VersionFile] = {}
    for v in versions:
        if v.fmt.rstrip("/").upper().endswith("XML") and v.date_applicability not in by_date:
            by_date[v.date_applicability] = v
    return [by_date[d] for d in sorted(by_date)]


def download(url: str, raw_dir: Path) -> tuple[Path, str]:
    """Scarica un file una sola volta. Il nome e l'impronta SHA-256: l'archivio grezzo resta immutabile."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    index = raw_dir / "index.json"
    known = json.loads(index.read_text("utf-8")) if index.exists() else {}
    if url in known and (raw_dir / known[url]).exists():
        path = raw_dir / known[url]
        return path, path.stem

    req = urllib.request.Request(url)
    body = _http(req, timeout=120)
    digest = hashlib.sha256(body).hexdigest()
    path = raw_dir / f"{digest}.xml"
    if not path.exists():
        path.write_bytes(body)
    known[url] = path.name
    index.write_text(json.dumps(known, indent=1, ensure_ascii=False), "utf-8")
    return path, digest


# ---------------------------------------------------------------------------
# Ricerca diretta nella RS, Raccolta ufficiale, entrate in vigore, consultazioni
# ---------------------------------------------------------------------------

def public_url(uri: str, lang: str = "it") -> str:
    return uri.replace("fedlex.data.admin.ch", "www.fedlex.admin.ch") + f"/{lang}"


def _status_label(uri: str) -> str:
    return {"0": "in vigore", "1": "non ancora in vigore", "3": "abrogato"}.get(uri.rsplit("/", 1)[-1], "sconosciuto")


def _merge_rows(rows: list[dict], key: str) -> list[dict]:
    """Fedlex restituisce lo stesso atto in piu righe (una per espressione): le unisce, tenendo i campi non vuoti."""
    merged: dict[str, dict] = {}
    for r in rows:
        cur = merged.setdefault(r[key], {})
        for k, v in r.items():
            if v and not cur.get(k):
                cur[k] = v
    return list(merged.values())


def search_titles(keywords: str, lang: str = "it", in_force_only: bool = True, limit: int = 15) -> list[dict]:
    """Cerca nella Raccolta sistematica per parole nel titolo. Piu parole = tutte devono comparire."""
    words = [w for w in re.findall(r"\w+", keywords.lower()) if len(w) >= 3][:6]
    if not words:
        return []
    filters = " ".join(f'FILTER(CONTAINS(LCASE(STR(?title)), "{sparql_escape(w)}"))' for w in words)
    force = f"?ca jolux:inForceStatus <{STATUS_IN_FORCE}> ." if in_force_only else ""
    rows = sparql(f"""
SELECT DISTINCT ?ca ?title ?titleShort ?sr ?status WHERE {{
  ?ca a jolux:ConsolidationAbstract ; jolux:isRealizedBy ?expr .
  ?expr jolux:title ?title .
  OPTIONAL {{ ?expr jolux:titleShort ?titleShort . }}
  OPTIONAL {{ ?expr jolux:historicalLegalId ?sr . }}
  OPTIONAL {{ ?ca jolux:inForceStatus ?status . }}
  FILTER(STRENDS(STR(?expr), "/{lang}"))
  FILTER(STRSTARTS(STR(?ca), "https://fedlex.data.admin.ch/eli/cc/"))
  {filters}
  {force}
}} ORDER BY ?sr LIMIT {min(int(limit) * 3, 60)}""")
    rows = _merge_rows(rows, "ca")
    out = [{"rs": r.get("sr", ""), "titolo": r["title"], "sigla": r.get("titleShort", ""),
            "stato": _status_label(r.get("status", "")), "uri": r["ca"], "url": public_url(r["ca"], lang)}
           for r in rows]
    # pertinenza: prima le leggi con l'espressione esatta nel titolo, poi le ordinanze, i trattati (RS 0.x) in fondo
    phrase = " ".join(re.findall(r"\w+", keywords.lower()))

    def rank(r):
        t = r["titolo"].lower()
        kind = (0 if t.startswith(("legge", "bundesgesetz", "loi")) else
                1 if t.startswith(("ordinanza", "verordnung", "ordonnance")) else 2)
        return (r["rs"].startswith("0."), phrase not in t, kind, len(t))

    out.sort(key=rank)
    return out[:int(limit)]


def upcoming_entries(days_ahead: int = 180, lang: str = "it", limit: int = 30) -> list[dict]:
    """Atti della RS con entrata in vigore futura (nuove leggi e ordinanze gia decise)."""
    today = _dt.date.today()
    until = today + _dt.timedelta(days=days_ahead)
    rows = sparql(f"""
SELECT DISTINCT ?ca ?title ?sr ?entry WHERE {{
  ?ca a jolux:ConsolidationAbstract ; jolux:isRealizedBy ?expr ; jolux:dateEntryInForce ?entry .
  ?expr jolux:title ?title .
  OPTIONAL {{ ?expr jolux:historicalLegalId ?sr . }}
  FILTER(STRENDS(STR(?expr), "/{lang}"))
  FILTER(STRSTARTS(STR(?ca), "https://fedlex.data.admin.ch/eli/cc/"))
  FILTER(xsd:date(?entry) > "{today.isoformat()}"^^xsd:date)
  FILTER(xsd:date(?entry) <= "{until.isoformat()}"^^xsd:date)
}} ORDER BY ASC(?entry) LIMIT {int(limit)}""")
    rows = _merge_rows(rows, "ca")
    return [{"rs": r.get("sr", ""), "titolo": r["title"], "entrata_in_vigore": r["entry"][:10],
             "url": public_url(r["ca"], lang)} for r in rows]


def recent_publications(days: int = 30, lang: str = "it", keywords: str = "", limit: int = 30) -> list[dict]:
    """Pubblicazioni recenti nella Raccolta ufficiale (RU) e nel Foglio federale (FF): modifiche appena decise."""
    since = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    words = [w for w in re.findall(r"\w+", keywords.lower()) if len(w) >= 3][:4]
    filters = " ".join(f'FILTER(CONTAINS(LCASE(STR(?title)), "{sparql_escape(w)}"))' for w in words)
    rows = sparql(f"""
SELECT DISTINCT ?act ?title ?pubDate WHERE {{
  ?act a jolux:Act ; jolux:isRealizedBy ?expr ; jolux:publicationDate ?pubDate .
  ?expr jolux:title ?title .
  FILTER(STRENDS(STR(?expr), "/{lang}"))
  FILTER(xsd:date(?pubDate) >= "{since}"^^xsd:date)
  {filters}
}} ORDER BY DESC(?pubDate) LIMIT {int(limit)}""")
    rows = _merge_rows(rows, "act")
    out = []
    for r in rows:
        coll = "RU" if "/eli/oc/" in r["act"] else "FF" if "/eli/fga/" in r["act"] else "altro"
        out.append({"raccolta": coll, "titolo": r["title"], "pubblicato": r["pubDate"][:10],
                    "url": public_url(r["act"], lang)})
    return out


def future_versions(act_uri: str, lang: str = "it") -> list[dict]:
    """Versioni consolidate di un atto con data di validita futura: modifiche gia decise, non ancora in vigore."""
    today = _dt.date.today().isoformat()
    rows = sparql(f"""
SELECT DISTINCT ?cons ?date WHERE {{
  ?cons jolux:isMemberOf <{act_uri}> ; jolux:dateApplicability ?date .
  FILTER(xsd:date(?date) > "{today}"^^xsd:date)
}} ORDER BY ?date""")
    return [{"in_vigore_dal": r["date"][:10], "uri": r["cons"]} for r in rows]


CONSULTATION_STATUS = {"0": "in preparazione", "1": "pianificata", "2": "in corso", "3": "conclusa",
                       "4": "chiusa", "5": "conclusa"}


def consultations(keywords: str = "", lang: str = "it", open_only: bool = True, limit: int = 20) -> list[dict]:
    """Procedure di consultazione federali (progetti di legge su cui si puo prendere posizione)."""
    words = [w for w in re.findall(r"\w+", keywords.lower()) if len(w) >= 3][:5]
    kw = (" FILTER(" + " || ".join(f'CONTAINS(LCASE(STR(?title)), "{sparql_escape(w)}")' for w in words) + ")") if words else ""
    today = _dt.date.today().isoformat()
    deadline = f'FILTER(BOUND(?end) && xsd:date(?end) >= "{today}"^^xsd:date)' if open_only else ""
    order = "ASC(?end)" if open_only else "DESC(?eventId)"
    rows = sparql(f"""
SELECT DISTINCT ?c ?eventId ?title ?status ?start ?end ?instLabel WHERE {{
  ?c a jolux:Consultation ; jolux:eventId ?eventId ; jolux:eventTitle ?title .
  OPTIONAL {{ ?c jolux:consultationStatus ?status . }}
  OPTIONAL {{ ?c jolux:hasSubTask ?t .
    OPTIONAL {{ ?t jolux:eventStartDate ?start . }}
    OPTIONAL {{ ?t jolux:eventEndDate ?end . }}
    OPTIONAL {{ ?t jolux:institutionInChargeOfTheEvent ?inst .
      OPTIONAL {{ ?inst skos:prefLabel ?instLabel . FILTER(LANG(?instLabel) = "{lang}") }} }} }}
  FILTER(LANG(?title) = "{lang}")
  {kw}
  {deadline}
}} ORDER BY {order} LIMIT {int(limit)}""")
    seen, out = set(), []
    for r in rows:
        if r["eventId"] in seen:
            continue
        seen.add(r["eventId"])
        out.append({"id": r["eventId"], "titolo": r["title"],
                    "stato": CONSULTATION_STATUS.get(r.get("status", "").rsplit("/", 1)[-1], "sconosciuto"),
                    "apertura": r.get("start", "")[:10], "termine": r.get("end", "")[:10],
                    "ufficio": r.get("instLabel", ""),
                    "url": f"https://www.fedlex.admin.ch/{lang}/consultation-procedures/ongoing"})
    return out


def consultation_detail(event_id: str, lang: str = "it") -> dict:
    rows = sparql(f"""
SELECT ?title ?desc ?status ?start ?end ?draft ?impact WHERE {{
  ?c a jolux:Consultation ; jolux:eventId "{sparql_escape(event_id)}" .
  OPTIONAL {{ ?c jolux:eventTitle ?title . FILTER(LANG(?title) = "{lang}") }}
  OPTIONAL {{ ?c jolux:eventDescription ?desc . FILTER(LANG(?desc) = "{lang}") }}
  OPTIONAL {{ ?c jolux:consultationStatus ?status . }}
  OPTIONAL {{ ?c jolux:foreseenImpactToLegalResource ?impact . }}
  OPTIONAL {{ ?c jolux:hasSubTask ?t .
    OPTIONAL {{ ?t jolux:eventStartDate ?start . }}
    OPTIONAL {{ ?t jolux:eventEndDate ?end . }}
    OPTIONAL {{ ?t jolux:opinionHasDraftRelatedDocument ?draft . }} }}
}} LIMIT 20""")
    if not rows:
        raise LookupError(f"Consultazione {event_id} non trovata")
    r = {}
    for row in rows:
        r.update({k: v for k, v in row.items() if v})
    return {"id": event_id, "titolo": r.get("title", ""), "descrizione": r.get("desc", "")[:1500],
            "stato": CONSULTATION_STATUS.get(r.get("status", "").rsplit("/", 1)[-1], "sconosciuto"),
            "apertura": r.get("start", "")[:10], "termine": r.get("end", "")[:10],
            "atti_toccati": r.get("impact", ""), "documento": r.get("draft", "")}


def catalog(lang: str = "it", prefix: str = "", include_treaties: bool = False) -> list[dict]:
    """Tutti gli atti in vigore della Raccolta sistematica (RS), con numero e titolo.

    prefix: limita a un settore per numero RS (es. "8" sanita e sicurezza sociale, "22" diritto delle obbligazioni).
    I trattati internazionali (RS 0.x) sono esclusi salvo include_treaties."""
    rows = sparql(f"""
SELECT DISTINCT ?ca ?sr ?title WHERE {{
  ?ca a jolux:ConsolidationAbstract ; jolux:inForceStatus <{STATUS_IN_FORCE}> ; jolux:isRealizedBy ?expr .
  ?expr jolux:historicalLegalId ?sr ; jolux:title ?title .
  FILTER(STRENDS(STR(?expr), "/{lang}"))
  FILTER(STRSTARTS(STR(?ca), "https://fedlex.data.admin.ch/eli/cc/"))
  {f'FILTER(STRSTARTS(STR(?sr), "{sparql_escape(prefix)}"))' if prefix else ""}
}} ORDER BY ?sr""")
    seen, out = set(), []
    for r in rows:
        if r["ca"] in seen or (not include_treaties and r["sr"].startswith("0.")):
            continue
        seen.add(r["ca"])
        out.append({"rs": r["sr"], "titolo": r["title"], "uri": r["ca"]})
    return out
