"""Curia Vista: oggetti parlamentari e votazioni dell'Assemblea federale (API OData ufficiale, senza chiave).

Fonte: https://ws.parlament.ch/odata.svc  (Servizi del Parlamento, licenza CC BY 4.0)
"""

from __future__ import annotations

import datetime as _dt
import html
import re
import urllib.parse

from . import sources

BASE = "https://ws.parlament.ch/odata.svc"
LANGS = {"it": "IT", "de": "DE", "fr": "FR", "en": "EN", "rm": "DE"}


def _odata(entity: str, filters: list[str], orderby: str | None = None, top: int = 20,
           select: list[str] | None = None, lang: str = "it") -> list[dict]:
    params = {"$format": "json", "$top": str(min(max(top, 1), 100)),
              "$filter": " and ".join(f"({f})" for f in [f"Language eq '{LANGS.get(lang, 'IT')}'", *filters])}
    if orderby:
        params["$orderby"] = orderby
    if select:
        params["$select"] = ",".join(select)
    data = sources.fetch_json(f"{BASE}/{entity}?{urllib.parse.urlencode(params)}", timeout=45)
    d = data.get("d", data) if isinstance(data, dict) else data
    return d.get("results", d) if isinstance(d, dict) else d


def _q(s: str) -> str:
    return s.replace("'", "''")


def _date(v) -> str:
    """OData v3 scrive le date come /Date(1700000000000)/."""
    if not v:
        return ""
    m = re.search(r"/Date\((-?\d+)", str(v))
    if m:
        return _dt.datetime.fromtimestamp(int(m.group(1)) / 1000, tz=_dt.timezone.utc).strftime("%Y-%m-%d")
    return str(v)[:10]


def _business(b: dict) -> dict:
    return {
        "id": b.get("ID"), "numero": b.get("BusinessShortNumber"), "tipo": b.get("BusinessTypeName"),
        "titolo": b.get("Title"), "stato": b.get("BusinessStatusText"), "data_stato": _date(b.get("BusinessStatusDate")),
        "depositato_da": b.get("SubmittedBy"), "depositato_il": _date(b.get("SubmissionDate")),
        "consiglio": b.get("SubmissionCouncilAbbreviation"), "dipartimento": b.get("ResponsibleDepartmentAbbreviation"),
        "url": f"https://www.parlament.ch/it/ratsbetrieb/suche-curia-vista/geschaeft?AffairId={b.get('ID')}",
    }


def search_business(keyword: str, lang: str = "it", limit: int = 15, status: str | None = None,
                    submitted_after: str | None = None) -> list[dict]:
    """Oggetti parlamentari il cui titolo contiene le parole indicate (ogni parola deve comparire)."""
    words = [w for w in re.findall(r"\w+", keyword) if len(w) >= 3][:4]
    filters = [f"substringof('{_q(w)}',Title)" for w in words]
    if status:
        filters.append(f"BusinessStatusText eq '{_q(status)}'")
    if submitted_after:
        filters.append(f"SubmissionDate gt datetime'{submitted_after}T00:00:00'")
    rows = _odata("Business", filters, orderby="SubmissionDate desc", top=limit, lang=lang)
    return [_business(b) for b in rows]


def business_detail(business_id: int, lang: str = "it") -> dict:
    url = f"{BASE}/Business(ID={int(business_id)},Language='{LANGS.get(lang, 'IT')}')?$format=json"
    data = sources.fetch_json(url, timeout=45)
    b = data.get("d", data)
    out = _business(b)
    for key, field in (("testo", "SubmittedText"), ("testo_mozione", "MotionText"),
                       ("risposta_consiglio_federale", "FederalCouncilResponseText"),
                       ("situazione_iniziale", "InitialSituation"), ("descrizione", "Description"),
                       ("procedura", "Proceedings")):
        val = b.get(field)
        if val:
            out[key] = html.unescape(re.sub(r"<[^>]+>", " ", val))
            out[key] = re.sub(r"\s+", " ", out[key]).strip()[:3000]
    return out


def votes(keyword: str, lang: str = "it", limit: int = 15) -> list[dict]:
    """Votazioni in Consiglio nazionale / degli Stati sugli oggetti il cui titolo contiene le parole indicate."""
    words = [w for w in re.findall(r"\w+", keyword) if len(w) >= 3][:3]
    filters = [f"substringof('{_q(w)}',BusinessTitle)" for w in words]
    rows = _odata("Vote", filters, orderby="ID desc", top=limit, lang=lang)
    return [{
        "id": v.get("ID"), "oggetto": v.get("BusinessTitle"), "numero": v.get("BusinessShortNumber"),
        "tema": v.get("Subject"), "significato_si": v.get("MeaningYes"), "significato_no": v.get("MeaningNo"),
        "data": _date(v.get("VoteEnd")), "consiglio": v.get("CouncilName"),
    } for v in rows]
