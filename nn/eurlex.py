"""Diritto dell'Unione europea dall'archivio CELLAR dell'Ufficio delle pubblicazioni (stesso contenuto di EUR-Lex).

eur-lex.europa.eu protegge le pagine con controlli anti-bot; CELLAR offre invece una base SPARQL e i file ufficiali
(XHTML, PDF, Formex). Per ogni atto si cerca la versione consolidata piu recente in italiano; se non ce n'e una,
il testo originale pubblicato nella Gazzetta ufficiale.
"""

from __future__ import annotations

import json
import urllib.parse

from . import sources

SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
LINGUE = {"it": "ITA", "de": "DEU", "fr": "FRA", "en": "ENG"}

# Atti selezionati: protezione dei dati, digitale, consumatori, assicurazioni e finanza, sicurezza sociale (ALC).
ATTI: dict[str, str] = {
    "32016R0679": "Regolamento generale sulla protezione dei dati (GDPR)",
    "32024R1689": "Regolamento sull'intelligenza artificiale (AI Act)",
    "32022R2065": "Regolamento sui servizi digitali (DSA)",
    "32022R1925": "Regolamento sui mercati digitali (DMA)",
    "32023R2854": "Regolamento sui dati (Data Act)",
    "32002L0058": "Direttiva relativa alla vita privata e alle comunicazioni elettroniche (ePrivacy)",
    "32022L2555": "Direttiva NIS 2 sulla cibersicurezza",
    "32014R0910": "Regolamento eIDAS sull'identificazione elettronica",
    "32000L0031": "Direttiva sul commercio elettronico",
    "32011L0083": "Direttiva sui diritti dei consumatori",
    "31993L0013": "Direttiva sulle clausole abusive nei contratti con i consumatori",
    "32023R0988": "Regolamento sulla sicurezza generale dei prodotti (GPSR)",
    "32024L2853": "Direttiva sulla responsabilita per danno da prodotti difettosi (2024)",
    "32019L0882": "Atto europeo sull'accessibilita",
    "32016L2102": "Direttiva sull'accessibilita dei siti web degli enti pubblici",
    "32008R0593": "Regolamento Roma I sulla legge applicabile ai contratti",
    "32012R1215": "Regolamento Bruxelles I bis sulla competenza giurisdizionale",
    "32016L0097": "Direttiva sulla distribuzione assicurativa (IDD)",
    "32009L0138": "Direttiva Solvibilita II",
    "32014L0065": "Direttiva sui mercati degli strumenti finanziari (MiFID II)",
    "32015L2366": "Direttiva sui servizi di pagamento (PSD2)",
    "32004R0883": "Regolamento sul coordinamento dei sistemi di sicurezza sociale",
    "32009R0987": "Regolamento di applicazione del regolamento 883/2004",
}


def sparql(query: str) -> list[dict[str, str]]:
    data = urllib.parse.urlencode({"query": query, "format": "application/sparql-results+json"}).encode()
    raw = sources.fetch(SPARQL, data=data, headers={"Accept": "application/sparql-results+json",
                                                     "Content-Type": "application/x-www-form-urlencoded"}, timeout=90)
    payload = json.loads(raw)
    return [{k: v["value"] for k, v in b.items()} for b in payload["results"]["bindings"]]


def query_versioni(celex: str, lang: str = "it") -> str:
    """Originale e versioni consolidate di un atto, con i file XHTML nella lingua richiesta."""
    c = celex.replace('"', "")
    lingua = LINGUE[lang]
    return f"""PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?celex ?date ?manif ?type ?item WHERE {{
  ?base owl:sameAs <http://publications.europa.eu/resource/celex/{c}> .
  {{ ?w owl:sameAs <http://publications.europa.eu/resource/celex/{c}> . }}
  UNION
  {{ ?w cdm:act_consolidated_based_on_resource_legal ?base ; cdm:act_consolidated_date ?date . }}
  ?w cdm:resource_legal_id_celex ?celex .
  ?expr cdm:expression_belongs_to_work ?w ;
        cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/{lingua}> .
  ?manif cdm:manifestation_manifests_expression ?expr ; cdm:manifestation_type ?type .
  OPTIONAL {{ ?item cdm:item_belongs_to_manifestation ?manif . }}
}}"""


def versioni(celex: str, lang: str = "it") -> list[dict]:
    """[{celex, data, url}] ordinate per data (l'originale ha data vuota e viene per primo). Solo XHTML/HTML."""
    righe = sparql(query_versioni(celex, lang))
    per_celex: dict[str, dict] = {}
    for r in righe:
        tipo = (r.get("type") or "").lower()
        if tipo not in ("xhtml", "html"):
            continue
        url = r.get("item") or (r["manif"] + "/DOC_1")
        url = url.replace("http://publications.europa.eu/", "https://publications.europa.eu/")
        v = per_celex.setdefault(r["celex"], {"celex": r["celex"], "data": (r.get("date") or "")[:10], "url": url, "tipo": tipo})
        if tipo == "xhtml" and v["tipo"] != "xhtml":
            v.update(url=url, tipo=tipo)
    return sorted(per_celex.values(), key=lambda v: v["data"])


def pagina_pubblica(celex: str, lang: str = "it") -> str:
    return f"https://eur-lex.europa.eu/legal-content/{lang.upper()}/TXT/?uri=CELEX:{celex}"
