"""Client per i modelli AI. Due fornitori, stessa API (formato OpenAI chat/completions):

  - infomaniak (predefinito): server in Svizzera, solo modelli sviluppati in Europa. Il controllo
    e nel codice: un modello fuori elenco viene rifiutato prima di inviare qualsiasi dato.
  - openai: soluzione temporanea, server negli Stati Uniti.

Configurazione nel file .env nella cartella del progetto (vedi env-esempio.txt):
  NN_PROVIDER=infomaniak | openai
  INFOMANIAK_API_TOKEN=...   INFOMANIAK_PRODUCT_ID=...
  OPENAI_API_KEY=...
  NN_MODEL=...               (facoltativo, dipende dal fornitore)
  NN_MODEL_FORTE=...         (solo openai: modello per scomposizione, ricerca e affermazioni; "no" per usarne uno solo)
"""

from __future__ import annotations

import json
import random
import re
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "mistralai/Mistral-Small-4-119B-2603"
OPENAI_DEFAULT_MODEL = "gpt-6-luna"        # 0.10 $ ingresso / 0.50 $ uscita per milione di token (ottobre 2026)
OPENAI_FORTE_MODEL = "gpt-6.1-terra"       # 1 $ / 5 $: per i ruoli che cercano e scrivono (NN_MODEL_FORTE nel .env)

# Ruoli brevi e chiusi: bastano al modello leggero. Tutto il resto (scomposizione, squadre, affermazioni,
# ricerca libera) va al modello forte.
RUOLI_LEGGERI = ("AMBITI", "AMMISSIONE", "RICONTROLLO", "RIFORMULAZIONE", "GENERAZIONE", "PERTINENZA", "SMISTAMENTO", "DOMANDE_UTENTE")

# Dollari per milione di token: ingresso, ingresso gia in memoria (prompt caching), uscita. Listino OpenAI, ottobre 2026.
PREZZI = {
    "gpt-6-astra": (10.0, 1.0, 50.0), "gpt-6.1-sol": (2.0, 0.10, 10.0), "gpt-6.1-terra": (1.0, 0.05, 5.0),
    "gpt-6-luna": (0.10, 0.01, 0.50), "gpt-6-sol": (2.0, 0.20, 10.0), "gpt-5.6-sol": (4.0, 0.40, 20.0),
    "gpt-5.6-terra": (2.0, 0.20, 12.0), "gpt-5.6-luna": (0.20, 0.02, 1.20),
}
OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_BASE = "https://api.infomaniak.com/2/ai/{product_id}/openai/v1"

# Sviluppatori europei ammessi: Mistral AI (Francia) e Swiss AI Initiative (EPFL, ETH, CSCS).
EUROPEAN_PREFIXES = ("mistralai/", "swiss-ai/")


class AIConfigError(RuntimeError):
    pass


class ServizioNonDisponibile(RuntimeError):
    """Il fornitore non risponde (rete, timeout, errori 5xx dopo i tentativi). Diverso da un errore di configurazione:
    qui ha senso proporre all'utente di aspettare o di usare il fornitore di riserva."""

    def __init__(self, fornitore: str, dettaglio: str = ""):
        super().__init__(f"{fornitore} non risponde" + (f": {dettaglio}" if dettaglio else ""))
        self.fornitore = fornitore


_ENV_LOADED: dict[str, str] = {}


def load_env(path: Path | None = None) -> None:
    """Legge un file .env semplice (CHIAVE=valore). Se una chiave compare piu volte vale l'ultima.
    Le variabili impostate fuori dal file (nel sistema) hanno la precedenza."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    values: dict[str, str] = {}
    # utf-8-sig: il Blocco note di Windows puo aggiungere un BOM invisibile in testa al file
    for line in path.read_text("utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    for key, value in values.items():
        if key not in os.environ or os.environ.get(key) == _ENV_LOADED.get(key):
            os.environ[key] = value
            _ENV_LOADED[key] = value


# Modelli aperti non europei eseguiti da Infomaniak in Svizzera: i dati restano in CH, cambia solo
# l'origine dei pesi. Ammessi per default; NN_MODELLI_OSPITATI_CH=0 nel .env torna ai soli europei.
OSPITATI_CH_PREFIXES = ("Qwen/", "moonshotai/", "google/")


def is_european(model: str) -> bool:
    """Vero per i modelli che Infomaniak esegue in Svizzera e che Anorma accetta (nome storico)."""
    if model.startswith(EUROPEAN_PREFIXES):
        return True
    return os.environ.get("NN_MODELLI_OSPITATI_CH", "1").strip() != "0" and model.startswith(OSPITATI_CH_PREFIXES)


def _senza_ragionamento(testo):
    """Toglie il ragionamento <think>...</think> che alcuni modelli mettono nel testo della risposta."""
    if isinstance(testo, str) and "</think>" in testo:
        return testo.split("</think>")[-1].lstrip()
    return testo


def _error_detail(e: "urllib.error.HTTPError") -> str:
    """Il messaggio d'errore restituito dal fornitore, senza intestazioni (quindi senza token)."""
    raw = e.read().decode("utf-8", "replace")[:800]
    try:
        data = json.loads(raw)
        err = data.get("error", data)
        if isinstance(err, dict):
            return " ".join(str(err.get(k)) for k in ("code", "message", "description") if err.get(k)) or raw
        return str(err)
    except (json.JSONDecodeError, AttributeError):
        return raw


class InfomaniakClient:
    provider = "infomaniak"
    label = "Infomaniak, Svizzera"
    european = True
    send_temperature = True
    json_mode = True   # response_format json_object per i ruoli che rispondono in JSON

    def __init__(self, token: str | None = None, product_id: str | None = None,
                 model: str | None = None, base_url: str | None = None):
        load_env()
        self.token = token or os.environ.get("INFOMANIAK_API_TOKEN", "")
        self.product_id = product_id or os.environ.get("INFOMANIAK_PRODUCT_ID", "")
        self.model = model or os.environ.get("NN_MODEL", DEFAULT_MODEL)
        base = base_url or os.environ.get("NN_AI_BASE_URL", DEFAULT_BASE)
        if not self.token or not self.product_id:
            raise AIConfigError(
                "Manca la configurazione Infomaniak. Crea il file .env nella cartella del progetto "
                "(vedi env-esempio.txt) con INFOMANIAK_API_TOKEN e INFOMANIAK_PRODUCT_ID."
            )
        if not is_european(self.model):
            shown = self.model if len(self.model) <= 60 and "=" not in self.model else "(valore non mostrato)"
            raise AIConfigError(
                f"Il modello '{shown}' non e tra quelli europei ammessi "
                f"({', '.join(EUROPEAN_PREFIXES)}). Correggi NN_MODEL nel file .env."
            )
        self.base_url = base.format(product_id=self.product_id).rstrip("/")

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             temperature: float = 0.1, timeout: int = 120) -> dict:
        """Una chiamata a /chat/completions. Restituisce il messaggio dell'assistente."""
        body = {"model": self.model, "messages": messages}
        sistema = messages[0].get("content", "") if messages and messages[0].get("role") == "system" else ""
        if self.json_mode and not tools and isinstance(sistema, str) and "SOLO con JSON" in sistema:
            # i ruoli che devono rispondere in JSON lo chiedono anche al server: molti meno errori di formato
            body["response_format"] = {"type": "json_object"}
        if self.send_temperature:
            body["temperature"] = temperature
        body.update(self.extra_body(bool(tools)))
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "NuovaNorma/0.4",
            },
        )
        tentativi = 5
        for attempt in range(tentativi):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read())
                msg = data["choices"][0]["message"]
                msg["content"] = _senza_ragionamento(msg.get("content"))
                msg.pop("reasoning_content", None)
                msg.pop("reasoning", None)
                uso = data.get("usage") or {}
                if isinstance(uso, dict) and uso:
                    dettagli = uso.get("prompt_tokens_details") or {}
                    # chiave privata: pipeline.Misurato la toglie prima che il messaggio torni nella conversazione
                    msg["_uso"] = {"modello": self.model, "ingresso": int(uso.get("prompt_tokens") or 0),
                                   "in_memoria": int(dettagli.get("cached_tokens") or 0) if isinstance(dettagli, dict) else 0,
                                   "uscita": int(uso.get("completion_tokens") or 0)}
                return msg
            except urllib.error.HTTPError as e:
                detail = _error_detail(e)
                if e.code == 400 and "response_format" in body and ("response_format" in detail or "json" in detail.lower()):
                    body.pop("response_format")   # il modello non lo accetta: si riprova senza, e non si chiede piu
                    self.json_mode = False
                    req.data = json.dumps(body).encode()
                    continue
                if e.code == 400 and "chat_template_kwargs" in body:
                    body.pop("chat_template_kwargs")   # parametro non accettato: si riprova senza
                    self.senza_pensiero = False
                    req.data = json.dumps(body).encode()
                    continue
                if e.code == 400 and "reasoning_effort" in detail and "reasoning_effort" in body:
                    # modello che non accetta il parametro: si riprova senza
                    body.pop("reasoning_effort")
                    self.reasoning = None
                    req.data = json.dumps(body).encode()
                    continue
                if e.code in (429, 500, 502, 503, 504) and attempt < tentativi - 1:
                    # con molte richieste in parallelo il fornitore puo chiedere di rallentare: si rispetta
                    # Retry-After se c'e, altrimenti attesa crescente con un po' di casualita
                    try:
                        attesa = float(e.headers.get("Retry-After") or 0)
                    except (TypeError, ValueError, AttributeError):
                        attesa = 0
                    time.sleep(min(30.0, attesa or (1.5 * 2 ** attempt + random.random())))
                    continue
                name = self.provider.capitalize()
                if e.code in (401, 403):
                    raise AIConfigError(
                        f"{name} ha rifiutato la richiesta (HTTP {e.code}): {detail}. "
                        "Controlla il file .env, poi esegui: py -m nn verifica-ai") from e
                if e.code in (429, 500, 502, 503, 504):
                    raise ServizioNonDisponibile(name, f"HTTP {e.code}") from e
                raise RuntimeError(f"Errore {name} HTTP {e.code}: {detail}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                # rete giu, DNS, connessione rifiutata o tempo scaduto: si riprova, poi si dichiara il servizio non disponibile
                if attempt < tentativi - 1:
                    time.sleep(min(20.0, 1.5 * 2 ** attempt + random.random()))
                    continue
                raise ServizioNonDisponibile(self.provider.capitalize(), type(e).__name__) from e
        raise ServizioNonDisponibile(self.provider.capitalize(), "nessuna risposta dopo i tentativi")

    senza_pensiero = True

    def extra_body(self, tools: bool = False) -> dict:
        # Qwen ragiona a lungo per default: qui serve velocita, il lavoro vero lo fanno le ricerche
        if self.senza_pensiero and self.model.startswith("Qwen/") and "Embedding" not in self.model:
            return {"chat_template_kwargs": {"enable_thinking": False}}
        return {}

    def get(self, url: str, timeout: int = 30):
        """GET di servizio per la diagnosi. Restituisce (stato HTTP, contenuto)."""
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}", "User-Agent": "NuovaNorma/0.5"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, _error_detail(e)


class OpenAIClient(InfomaniakClient):
    """OpenAI, temporaneo. Stessa interfaccia; i modelli GPT-5 e GPT-6 non accettano 'temperature'."""

    provider = "openai"
    label = "OpenAI, Stati Uniti · temporaneo"
    european = False
    send_temperature = False
    json_mode = False

    def __init__(self, token: str | None = None, model: str | None = None, base_url: str | None = None):
        load_env()
        self.token = token or os.environ.get("OPENAI_API_KEY", "")
        model = model or os.environ.get("NN_MODEL", "")
        # Un modello Infomaniak rimasto nel .env non ha senso qui: si usa quello predefinito OpenAI
        self.model = model if model and not is_european(model) else OPENAI_DEFAULT_MODEL
        if not self.token:
            raise AIConfigError("Manca OPENAI_API_KEY nel file .env (vedi env-esempio.txt).")
        self.base_url = (base_url or os.environ.get("NN_OPENAI_BASE_URL", OPENAI_BASE)).rstrip("/")
        # Ragionamento breve: molto piu veloce, e qui il lavoro vero lo fanno le ricerche nell'archivio.
        # Valori: minimal, low, medium, high (NN_REASONING nel .env). Solo per i modelli che lo supportano.
        self.reasoning = os.environ.get("NN_REASONING", "low").strip().lower() or None

    def extra_body(self, tools: bool = False) -> dict:
        if self.model.startswith("gpt-6") and tools:
            # GPT-6 su Chat Completions: con gli strumenti il ragionamento deve essere "none" (documentazione OpenAI)
            return {"reasoning_effort": "none"}
        if self.reasoning and self.model.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")):
            return {"reasoning_effort": self.reasoning}
        return {}


class MistoClient:
    """Due modelli OpenAI: il leggero per i ruoli brevi e chiusi, il forte per cercare e scrivere.
    Il ruolo si legge dalla prima riga delle istruzioni ("Ruolo: ...")."""

    provider = "openai"
    label = "OpenAI, Stati Uniti · temporaneo · modello per ruolo"
    european = False

    def __init__(self, leggero, forte):
        self.leggero, self.forte = leggero, forte
        self.provider = getattr(leggero, "provider", "openai")
        self.european = getattr(leggero, "european", False)
        self.label = str(getattr(leggero, "label", "OpenAI, Stati Uniti")).split(" · ")[0] + " · modello per ruolo"
        self.model = f"{leggero.model} + {forte.model}"
        self.token, self.base_url = leggero.token, leggero.base_url

    def scegli(self, messages: list[dict]) -> OpenAIClient:
        system = messages[0].get("content") if messages and messages[0].get("role") == "system" else ""
        m = re.search(r"Ruolo:\s*([A-Z_]+)", system) if isinstance(system, str) else None
        ruolo = m.group(1) if m else ""
        return self.leggero if ruolo in RUOLI_LEGGERI else self.forte

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             temperature: float = 0.1, timeout: int = 120) -> dict:
        return self.scegli(messages).chat(messages, tools=tools, temperature=temperature, timeout=timeout)

    def get(self, url: str, timeout: int = 30):
        return self.leggero.get(url, timeout)


# Dove il fornitore di riserva elabora i dati: mostrato all'utente prima che scelga
LUOGO_RISERVA = {"openai": "OpenAI, negli Stati Uniti"}
_STATO_SERVIZIO: dict = {}   # fornitore -> (istante del controllo, disponibile)


def disponibile(client, massimo_s: float = 30.0, timeout: int = 8) -> bool:
    """Il fornitore principale risponde? Controllo leggero (elenco dei modelli), ricordato per `massimo_s` secondi.
    Solo per Infomaniak: con un altro fornitore principale (sviluppo, prove) risponde sempre vero."""
    if getattr(client, "provider", "") != "infomaniak":
        return True
    adesso = time.time()
    prima = _STATO_SERVIZIO.get("infomaniak")
    if prima and adesso - prima[0] < massimo_s:
        return prima[1]
    try:
        stato, _ = client.get(f"{client.base_url}/models", timeout=timeout)
        ok = stato == 200 or stato in (401, 403)   # 401/403: il servizio risponde, e un problema di configurazione
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        ok = False
    _STATO_SERVIZIO["infomaniak"] = (adesso, ok)
    return ok


def segna_non_disponibile() -> None:
    _STATO_SERVIZIO["infomaniak"] = (time.time(), False)


def make_riserva():
    """Il fornitore di riserva (OpenAI), solo se configurato; None altrimenti. Si usa solo con il consenso dell'utente."""
    load_env()
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    leggero = OpenAIClient(model=os.environ.get("NN_OPENAI_MODEL") or None)
    forte = os.environ.get("NN_MODEL_FORTE", OPENAI_FORTE_MODEL).strip()
    if not forte or forte.lower() in ("no", "nessuno", "off") or forte == leggero.model or is_european(forte):
        return leggero
    return MistoClient(leggero, OpenAIClient(model=forte))


class ConRiserva:
    """Il client principale (Infomaniak) con il passaggio alla riserva SOLO se l'utente ha acconsentito.
    Senza consenso, quando il principale cade chiama `al_guasto` (che ferma la ricerca) e rilancia l'errore."""

    def __init__(self, principale, riserva_factory=None, consenso: bool = False, al_guasto=None):
        self.principale = principale
        self.riserva_factory = riserva_factory or make_riserva
        self.consenso = consenso
        self.al_guasto = al_guasto
        self._riserva = None
        self.usata_riserva = False

    def _attivo(self):
        return self._riserva if self.usata_riserva else self.principale

    @property
    def model(self):
        return self._attivo().model

    @property
    def label(self):
        return self._attivo().label

    @property
    def provider(self):
        return self._attivo().provider

    def _passa_alla_riserva(self) -> bool:
        if not self.consenso:
            return False
        if self._riserva is None:
            self._riserva = self.riserva_factory()
        if self._riserva is None:
            return False
        self.usata_riserva = True
        return True

    def chat(self, messages, tools=None, temperature: float = 0.1, timeout: int = 120) -> dict:
        if not self.usata_riserva and self.consenso and not disponibile(self.principale):
            self._passa_alla_riserva()
        if self.usata_riserva:
            return self._riserva.chat(messages, tools=tools, temperature=temperature, timeout=timeout)
        try:
            return self.principale.chat(messages, tools=tools, temperature=temperature, timeout=timeout)
        except ServizioNonDisponibile:
            segna_non_disponibile()
            if self._passa_alla_riserva():
                return self._riserva.chat(messages, tools=tools, temperature=temperature, timeout=timeout)
            if self.al_guasto:
                self.al_guasto()
            raise

    def get(self, url: str, timeout: int = 30):
        return self._attivo().get(url, timeout)


def make_client():
    """Il client scelto con NN_PROVIDER nel file .env (predefinito: infomaniak)."""
    load_env()
    provider = os.environ.get("NN_PROVIDER", "infomaniak").strip().lower()
    if provider == "openai":
        leggero = OpenAIClient()
        forte = os.environ.get("NN_MODEL_FORTE", OPENAI_FORTE_MODEL).strip()
        if not forte or forte.lower() in ("no", "nessuno", "off") or forte == leggero.model or is_european(forte):
            return leggero
        return MistoClient(leggero, OpenAIClient(model=forte))
    if provider == "infomaniak":
        leggero = InfomaniakClient()
        # NN_MODEL_FORTE_CH: un modello piu grande eseguito in Svizzera per i ruoli che cercano e scrivono (facoltativo)
        forte = os.environ.get("NN_MODEL_FORTE_CH", "").strip()
        if forte and forte != leggero.model:
            return MistoClient(leggero, InfomaniakClient(model=forte))
        return leggero
    # Il valore non viene mostrato: in un .env mal formattato potrebbe contenere una chiave segreta
    raise AIConfigError("NN_PROVIDER nel file .env non e valido: deve essere esattamente "
                        "NN_PROVIDER=infomaniak oppure NN_PROVIDER=openai, su una riga da solo.")


def diagnose(log=print) -> None:
    """Controlla la configurazione AI senza mai stampare il token."""
    try:
        c = make_client()
    except AIConfigError as e:
        log(f"Configurazione: {e}")
        return
    log(f"Fornitore: {c.label}")
    log(f"Modello:   {c.model}")
    log(f"Indirizzo: {c.base_url}")
    log(f"Token:     presente, {len(c.token)} caratteri (non mostrato)")
    if c.provider == "openai":
        status, data = c.get(f"{c.base_url}/models")
        if status == 200:
            ids = sorted(m["id"] for m in data.get("data", []) if isinstance(m, dict))
            nomi = c.model.split(" + ")
            mancanti = [m for m in nomi if m not in ids]
            ok = not mancanti
            log(f"Elenco modelli: OK ({len(ids)} disponibili). "
                + ("Modelli configurati presenti." if ok else f"NON presenti: {', '.join(mancanti)}."))
            if not ok:
                log("  Modelli simili disponibili: " + ", ".join(i for i in ids if i.startswith("gpt-"))[:600])
        else:
            log(f"Elenco modelli: HTTP {status} - {data}")
    else:
        status, data = c.get("https://api.infomaniak.com/1/ai")
        log(f"Prodotti AI visibili dal token: HTTP {status}")
        if status == 200:
            items = data.get("data", data) if isinstance(data, dict) else data
            ids = [str(p.get("product_id") or p.get("id")) for p in (items or []) if isinstance(p, dict)]
            log(f"  Product ID trovati: {', '.join(ids) or 'nessuno'}; nel .env: {c.product_id}"
                + ("" if c.product_id in ids else "  <- NON corrisponde"))
        else:
            log(f"  {data}")
            log("  Un 403 qui indica di solito un token creato senza l'accesso ad AI Tools.")
        status, data = c.get(f"{c.base_url}/models")
        log(f"Elenco modelli del prodotto: HTTP {status}")
        if status == 200 and isinstance(data, dict):
            ids = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
            log("  " + ", ".join(i for i in ids if i)[:600])
    prove = [(c.leggero, "leggero"), (c.forte, "forte")] if isinstance(c, MistoClient) else [(c, "")]
    for client, nome in prove:
        etichetta = f"Prova di chat {nome} ({client.model})" if nome else "Prova di chat"
        try:
            msg = client.chat([{"role": "user", "content": "Rispondi solo con la parola: funziona"}], timeout=60)
            log(f"{etichetta}: OK - {(msg.get('content') or '').strip()[:80]}")
        except Exception as e:
            log(f"{etichetta}: ERRORE - {e}")
