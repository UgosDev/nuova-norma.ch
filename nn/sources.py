"""Registro delle fonti ufficiali e accesso HTTP controllato.

Regola del progetto: l'agente legge solo fonti ufficiali. L'elenco dei domini e chiuso e sta qui;
qualsiasi richiesta verso un dominio non elencato viene rifiutata prima di partire.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

USER_AGENT = "NuovaNorma/0.7 (+https://nuova-norma.ch; ricerca giuridica su fonti ufficiali)"


# Livello giuridico di ogni fonte: l'agente lo dichiara, cosi una direttiva non viene presentata come legge.
LIVELLI = {
    "legge": "atto normativo vincolante (legge, ordinanza, legge cantonale)",
    "giurisprudenza": "decisione di un tribunale: vincola le parti, orienta l'applicazione",
    "parlamento": "atto parlamentare o progetto: non e diritto in vigore",
    "prassi": "prassi dell'autorita (direttiva, circolare, guida): vincola l'amministrazione, non i tribunali",
    "informativo": "informazione ufficiale divulgativa: spiega il diritto, non lo sostituisce",
    "dati": "dato ufficiale (es. risultato di una votazione)",
    "decisione": "decisione di un'autorita amministrativa su un caso: vincola le parti, si puo impugnare, orienta i casi simili",
    "diritto_ue": "atto dell'Unione europea: in Svizzera vale solo se un accordo bilaterale o il diritto svizzero lo richiama, "
                  "oppure per chi offre beni o servizi nell'UE",
    "dottrina": "opinione di autori (commentario): autorevole, ma non vincola ne le autorita ne i tribunali",
    "privato": "fonte privata (es. fondazione di mediazione): orienta, non vincola nessuno e non e un'autorita",
}


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    authority: str
    domains: tuple[str, ...]
    kind: str  # legge | parlamento | consultazione | giurisprudenza | cantone | prassi | informativo | dati
    note: str = ""
    livello: str = ""   # chiave di LIVELLI; vuoto = dedotto da kind
    sigla: str = ""     # prefisso delle citazioni, es. "UFAS" -> [UFAS CIGI, 2026-01-01]

    @property
    def livello_effettivo(self) -> str:
        return self.livello or {"cantone": "legge", "consultazione": "parlamento"}.get(self.kind, self.kind)


SOURCES: dict[str, Source] = {s.id: s for s in [
    Source("fedlex", "Fedlex: RS, RU, FF", "Cancelleria federale",
           ("fedlex.data.admin.ch", "www.fedlex.admin.ch", "fedlex.admin.ch"), "legge",
           "Diritto federale: testi consolidati (RS), Raccolta ufficiale (RU), Foglio federale (FF)"),
    Source("consultazioni", "Procedure di consultazione", "Cancelleria federale",
           ("fedlex.data.admin.ch",), "consultazione", "Progetti di legge in consultazione"),
    Source("parlamento", "Curia Vista", "Servizi del Parlamento",
           ("ws.parlament.ch", "www.parlament.ch"), "parlamento",
           "Oggetti parlamentari, votazioni in Consiglio, dal 1978"),
    Source("tf", "Tribunale federale", "Tribunale federale",
           ("www.bger.ch", "bger.ch"), "giurisprudenza",
           "Sentenze dal 2000 (tutte dal 2007) e raccolta ufficiale DTF"),
    Source("ticino", "Raccolta delle leggi del Cantone Ticino", "Cancelleria dello Stato, Ticino",
           ("m3.ti.ch", "www4.ti.ch", "www.ti.ch"), "cantone", "Diritto cantonale ticinese", sigla="RL-TI"),
    # Fonti documentali (archivio comune: nn/documenti.py e nn/raccolte.py)
    Source("ufas", "Direttive e circolari dell'UFAS (AVS, AI, IPG, PC, PP, assegni familiari)", "Ufficio federale delle assicurazioni sociali",
           ("sozialversicherungen.admin.ch",), "prassi",
           "Istruzioni alle casse di compensazione e agli uffici AI: come l'amministrazione applica la legge", sigla="UFAS"),
    Source("promemoria", "Promemoria AVS/AI", "Centro d'informazione AVS/AI (casse di compensazione e UFAS)",
           ("www.ahv-iv.ch", "ahv-iv.ch"), "informativo",
           "Spiegazioni brevi aggiornate ogni anno con gli importi in vigore", sigla="Promemoria"),
    Source("cavpp", "Direttive e comunicazioni della CAV PP", "Commissione di alta vigilanza della previdenza professionale",
           ("www.oak-bv.admin.ch", "oak-bv.admin.ch"), "prassi",
           "Vigilanza su casse pensioni, fondazioni collettive e autorita di vigilanza regionali", sigla="CAV PP"),
    Source("seco_ladi", "Istruzioni della SECO sull'assicurazione contro la disoccupazione (Prassi LADI)",
           "Segreteria di Stato dell'economia (SECO), ufficio di compensazione AD", ("www.arbeit.swiss", "arbeit.swiss"), "prassi",
           "Istruzioni alle casse di disoccupazione e agli uffici regionali di collocamento", sigla="SECO-LADI"),
    Source("seco_ll", "Indicazioni della SECO sulla legge sul lavoro", "Segreteria di Stato dell'economia (SECO)",
           ("www.seco.admin.ch", "seco.admin.ch"), "prassi", "Commento della SECO alla LL e alle ordinanze 1-5", sigla="SECO-LL"),
    Source("afc", "Circolari dell'AFC", "Amministrazione federale delle contribuzioni",
           ("www.estv.admin.ch", "estv.admin.ch"), "prassi", "Imposta federale diretta, imposta preventiva, tasse di bollo, prassi IVA", sigla="AFC"),
    Source("ufsp", "Circolari dell'UFSP agli assicuratori", "Ufficio federale della sanita pubblica",
           ("www.bag.admin.ch", "bag.admin.ch"), "prassi", "Assicurazione malattie (LAMal) e infortuni (LAINF)", sigla="UFSP"),
    Source("seco_oip", "Indicazioni della SECO sull'indicazione dei prezzi", "Segreteria di Stato dell'economia (SECO)",
           ("www.seco.admin.ch", "seco.admin.ch"), "prassi", "Guide all'OIP per settore (telecomunicazioni, viaggi, e-commerce...)", sigla="SECO-OIP"),
    Source("ufcom", "Prescrizioni tecniche e amministrative dell'UFCOM", "Ufficio federale delle comunicazioni",
           ("www.bakom.admin.ch", "bakom.admin.ch"), "prassi", "Telecomunicazioni: prescrizioni RS 784.101.113/x", sigla="UFCOM"),
    Source("comcom", "Decisioni della ComCom", "Commissione federale delle comunicazioni",
           ("www.comcom.admin.ch", "comcom.admin.ch"), "decisione", "Concessioni, interconnessione, accesso", sigla="ComCom"),
    Source("comco", "Decisioni della Commissione della concorrenza (DPC)", "Commissione della concorrenza",
           ("www.weko.admin.ch", "weko.admin.ch"), "decisione", "Raccolta DPC dal 1997 e decisioni recenti", sigla="COMCO"),
    Source("elcom", "Istruzioni, comunicazioni e decisioni dell'ElCom", "Commissione federale dell'energia elettrica",
           ("www.elcom.admin.ch", "elcom.admin.ch"), "prassi", "Approvvigionamento elettrico: tariffe, reti, riserve", sigla="ElCom"),
    Source("ufam", "Aiuti all'esecuzione dell'UFAM", "Ufficio federale dell'ambiente",
           ("www.bafu.admin.ch", "bafu.admin.ch"), "prassi", "Come applicare le ordinanze ambientali (rumore, rifiuti, acque, siti inquinati...)", sigla="UFAM"),
    Source("swissmedic", "Guide e promemoria di Swissmedic", "Istituto svizzero per gli agenti terapeutici",
           ("www.swissmedic.ch", "swissmedic.ch"), "prassi", "Medicamenti e dispositivi medici", sigla="Swissmedic"),
    Source("eurlex", "Diritto dell'Unione europea (EUR-Lex / CELLAR)", "Ufficio delle pubblicazioni dell'Unione europea",
           ("publications.europa.eu", "op.europa.eu"), "diritto_ue",
           "Testo ufficiale in italiano, versione consolidata piu recente; riuso libero citando la fonte (decisione 2011/833/UE)",
           sigla="UE"),
    Source("opencaselaw", "Giurisprudenza svizzera e commentari aperti (OpenCaseLaw)", "Progetto indipendente (non un'autorita); sentenze pubblicate dai tribunali",
           ("mcp.opencaselaw.ch", "opencaselaw.ch"), "giurisprudenza",
           "Tribunali federali e dei 26 cantoni dal 1875, grafo delle citazioni; sentenze CC0, commentari CC-BY", sigla="Sentenza"),
    Source("sem", "Istruzioni e circolari della SEM", "Segreteria di Stato della migrazione",
           ("www.sem.admin.ch", "sem.admin.ch"), "prassi", "Stranieri, libera circolazione, asilo, cittadinanza", sigla="SEM"),
    Source("ombudsman", "Ombudsman dell'assicurazione privata e della Suva", "Fondazione privata (non e un'autorita)",
           ("ombudsman-assicurazione.ch", "versicherungsombudsman.ch", "ombudsman-assurance.ch", "insuranceombudsman.ch"),
           "privato", "Casi esemplari e rapporti annuali della mediazione", sigla="Ombudsman"),
    Source("ifpdt", "Guide, promemoria e decisioni dell'IFPDT", "Incaricato federale della protezione dei dati e della trasparenza",
           ("www.edoeb.admin.ch", "edoeb.admin.ch"), "prassi",
           "Come l'autorita di vigilanza interpreta la LPD: guide, FAQ, decisioni, raccomandazioni", sigla="IFPDT"),
    Source("finma", "Circolari FINMA", "Autorita federale di vigilanza sui mercati finanziari",
           ("www.finma.ch", "finma.ch"), "prassi", "Prassi di vigilanza su banche, assicurazioni, intermediari", sigla="FINMA"),
    Source("votazioni", "Risultati delle votazioni popolari federali", "Ufficio federale di statistica",
           ("dam-api.bfs.admin.ch",), "dati", "Ogni votazione federale dal 1848, con i risultati per cantone", sigla="Votazione"),
]}

ALLOWED_HOSTS: frozenset[str] = frozenset(h for s in SOURCES.values() for h in s.domains)


class SourceNotAllowed(PermissionError):
    pass


def assert_allowed(url: str) -> None:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise SourceNotAllowed(f"Dominio non ammesso: {host or url}. Nuova-Norma legge solo fonti ufficiali.")


def _ssl_context() -> ssl.SSLContext | None:
    """Verifica TLS sempre attiva. Su Windows la lista di certificati di Python e incompleta (bger.ch non
    passa): si usano i certificati di sistema (pacchetto truststore) o quelli di certifi, se installati."""
    try:
        import truststore  # py -m pip install truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        pass
    try:
        import certifi  # py -m pip install certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return None


class _SoloDominiAmmessi(urllib.request.HTTPRedirectHandler):
    """Un reindirizzamento verso un dominio fuori elenco viene rifiutato come una richiesta diretta."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        assert_allowed(urllib.parse.urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_SSL = _ssl_context()
_opener = (urllib.request.build_opener(urllib.request.HTTPSHandler(context=_SSL), _SoloDominiAmmessi) if _SSL
           else urllib.request.build_opener(_SoloDominiAmmessi))


# Pausa minima tra due richieste allo stesso host: sono servizi pubblici, li trattiamo con riguardo.
MIN_INTERVAL_S = 0.5
_last: dict[str, float] = {}


def _throttle(url: str) -> None:
    host = urllib.parse.urlparse(url).hostname or ""
    wait = MIN_INTERVAL_S - (time.monotonic() - _last.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.monotonic()


def fetch(url: str, *, data: bytes | None = None, headers: dict | None = None,
          timeout: int = 60, retries: int = 3) -> bytes:
    """GET (o POST se data) con allowlist, User-Agent, pausa e nuovi tentativi sugli errori temporanei."""
    assert_allowed(url)
    hdrs = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs)
    last_err: Exception | None = None
    for attempt in range(retries):
        _throttle(url)
        try:
            with _opener.open(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(e):
                raise RuntimeError(
                    f"Certificato TLS di {urllib.parse.urlparse(url).hostname} non verificabile con i certificati di Python. "
                    "Installa i certificati di sistema:  py -m pip install truststore   (oppure certifi) e riprova.") from e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError(str(last_err))


def fetch_text(url: str, **kw) -> str:
    raw = fetch(url, **kw)
    for enc in ("utf-8", "iso-8859-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def fetch_json(url: str, **kw):
    kw.setdefault("headers", {})
    kw["headers"].setdefault("Accept", "application/json")
    return json.loads(fetch(url, **kw) or b"null")


# robots.txt: le fonti nuove lo rispettano (il Tribunale federale e un'eccezione documentata nel README:
# si interroga solo su richiesta esplicita, con pause).
_robots: dict[str, object] = {}


def _leggi_robots(base: str) -> list[str] | None:
    """Righe del robots.txt; [] se il sito non ne ha (404); None se non si e potuto leggere.
    E l'unica lettura permessa anche fuori dall'elenco dei domini: serve a decidere se una fonte si puo collegare."""
    url = base + "/robots.txt"
    host = urllib.parse.urlparse(url).hostname or ""
    try:
        if host in ALLOWED_HOSTS:
            raw = fetch(url, timeout=20, retries=1)
        else:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            _throttle(url)
            with _opener_robots.open(req, timeout=20) as resp:
                raw = resp.read()
        return raw.decode("utf-8", "replace").splitlines()
    except urllib.error.HTTPError as e:
        return [] if e.code in (404, 410) else None
    except Exception:
        return None


_opener_robots = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_SSL)) if _SSL else urllib.request.build_opener()


def robots_stato(url: str) -> bool | None:
    """True = permesso, False = escluso dal robots.txt, None = robots.txt non leggibile (rete, errore)."""
    import urllib.robotparser
    parts = urllib.parse.urlparse(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _robots:
        righe = _leggi_robots(base)
        if righe is None:
            return None
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(righe)
        _robots[base] = rp
    return _robots[base].can_fetch(USER_AGENT, url)


def robots_ok(url: str) -> bool:
    """Per aggiorna(): si procede se il robots.txt permette o non e leggibile (la richiesta poi fallira da sola)."""
    return robots_stato(url) is not False
