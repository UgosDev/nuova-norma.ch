"""Giurisprudenza svizzera (tribunali federali e dei 26 cantoni), grafo delle citazioni e commentari aperti,
tramite l'interfaccia pubblica di OpenCaseLaw.

OpenCaseLaw non e un'autorita: raccoglie le sentenze che i tribunali pubblicano (dati CC0, aggiornati ogni giorno).
Per questo ogni risposta porta l'indirizzo canonico della sentenza presso il tribunale, da cui si verifica il testo.
I commentari sono in CC-BY: si citano con autore e licenza. Limite consigliato dal servizio: 5 richieste al secondo.
"""

from __future__ import annotations

import json
import urllib.parse

from . import sources

BASE = "https://mcp.opencaselaw.ch/api"
TESTO = ("full_text", "text", "content", "body", "decision_text")


def _get(path: str, **params):
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return sources.fetch_json(f"{BASE}{path}" + (f"?{q}" if q else ""), timeout=60)


def cerca(query: str, lingua: str = "", cantone: str = "", tribunale: str = "", limite: int = 10, offset: int = 0) -> dict:
    d = _get("/decisions", q=query, language=lingua, canton=cantone, court=tribunale, limit=limite, offset=offset)
    risultati = [{"id": r.get("decision_id"), "tribunale": r.get("court"), "data": (r.get("decision_date") or "")[:10],
                  "lingua": r.get("language"), "titolo": r.get("title"), "regesto": (r.get("regeste") or "")[:600],
                  "citazione_ufficiale": r.get("citation_string_de"), "url": r.get("canonical_url")}
                 for r in (d.get("results") or [])]
    return {"totale": d.get("total"), "totale_minimo": bool(d.get("total_is_lower_bound")),
            "altri": bool(d.get("has_more")), "prossimo_offset": d.get("next_offset"), "risultati": risultati}


def sentenza(decision_id: str) -> dict:
    """Sentenza completa: metadati e testo. Il campo del testo si cerca tra i nomi possibili."""
    d = _get("/decisions/" + urllib.parse.quote(decision_id, safe=""))
    testo = next((d[k] for k in TESTO if isinstance(d.get(k), str) and d.get(k)), "")
    return {"id": d.get("decision_id") or decision_id, "tribunale": d.get("court"), "data": (d.get("decision_date") or "")[:10],
            "lingua": d.get("language"), "titolo": d.get("title"), "regesto": d.get("regeste") or "",
            "citazione_ufficiale": d.get("citation_string_de"), "url": d.get("canonical_url"), "testo": testo,
            "grezzo": d}


def considerando(decision_id: str, numero: str) -> dict:
    return _get(f"/erwaegung/{urllib.parse.quote(decision_id, safe='')}/{urllib.parse.quote(str(numero), safe='.')}")


def citazioni(decision_id: str, offset: int = 0) -> dict:
    return _get("/citations/" + urllib.parse.quote(decision_id, safe=""), offset=offset or None)


def commentari(query: str) -> object:
    return _get("/commentaries/search", q=query)


def materiali(legge: str) -> object:
    return _get("/materialien/" + urllib.parse.quote(legge, safe=""))
