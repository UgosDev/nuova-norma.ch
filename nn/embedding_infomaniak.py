"""Vettori tramite l'API di Infomaniak (server in Svizzera): per la produzione, dove non c'e una GPU.

Stessa interfaccia del modello locale (metodo `encode`), cosi il resto del codice non cambia.
Endpoint: POST /1/ai/{product_id}/openai/v1/embeddings (formato OpenAI). Credenziali dal file .env:
INFOMANIAK_API_TOKEN (token con accesso ad AI Tools) e INFOMANIAK_PRODUCT_ID.
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request

BASE = "https://api.infomaniak.com"
# Istruzione per le DOMANDE (non per gli articoli), come raccomandato per i modelli bge-*-gemma2.
COMPITO = "Data una domanda giuridica, trova gli articoli di legge svizzeri che rispondono."
ISTRUZIONE = {   # parte del nome del modello -> prefisso per le domande
    "gemma2": f"<instruct>{COMPITO}\n<query>",
    "qwen3": f"Instruct: {COMPITO}\nQuery:",
}


def istruzione(modello: str) -> str:
    m = (modello or "").lower()
    return next((v for k, v in ISTRUZIONE.items() if k in m), "")


class Infomaniak:
    def __init__(self, modello: str, token: str | None = None, product_id: str | None = None,
                 base: str | None = None, per_richiesta: int = 32):
        from . import ai
        ai.load_env()
        self.modello = modello
        self.token = token or os.environ.get("INFOMANIAK_API_TOKEN", "")
        self.product_id = product_id or os.environ.get("INFOMANIAK_PRODUCT_ID", "")
        if not self.token or not self.product_id:
            raise RuntimeError("Mancano INFOMANIAK_API_TOKEN o INFOMANIAK_PRODUCT_ID nel file .env")
        self.url = f"{(base or os.environ.get('NN_INFOMANIAK_BASE', BASE)).rstrip('/')}" \
                   f"/1/ai/{self.product_id}/openai/v1/embeddings"
        self.per_richiesta = per_richiesta
        self.paralleli = int(os.environ.get("NN_VETTORI_PARALLELI", "4") or 4)
        self.token_usati = 0
        self._lock = __import__("threading").Lock()

    def _richiesta(self, testi: list[str]) -> list[list[float]]:
        corpo = json.dumps({"model": self.modello, "input": testi}).encode()
        for tentativo in range(6):
            req = urllib.request.Request(self.url, data=corpo, headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                "User-Agent": "NuovaNorma/0.4"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    dati = json.loads(r.read())
                with self._lock:
                    self.token_usati += int((dati.get("usage") or {}).get("total_tokens") or 0)
                righe = sorted(dati["data"], key=lambda x: x.get("index", 0))
                return [x["embedding"] for x in righe]
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and tentativo < 5:
                    time.sleep(min(60, 2 ** tentativo) + random.random())
                    continue
                dettaglio = e.read()[:300].decode("utf-8", "replace")
                raise RuntimeError(f"Infomaniak embeddings: HTTP {e.code} {dettaglio}") from None
            except urllib.error.URLError:
                if tentativo < 5:
                    time.sleep(min(60, 2 ** tentativo))
                    continue
                raise
        raise RuntimeError("Infomaniak embeddings: troppi tentativi")

    def encode(self, testi, normalize_embeddings: bool = True, batch_size: int | None = None,
               domanda: bool = False, **_):
        import numpy as np
        testi = list(testi)
        if domanda:
            pref = istruzione(self.modello)
            testi = [pref + t for t in testi]
        passo = batch_size or self.per_richiesta
        lotti = [testi[i:i + passo] for i in range(0, len(testi), passo)]
        if len(lotti) > 1 and self.paralleli > 1:   # piu richieste insieme: il calcolo massivo va molto piu veloce
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(self.paralleli) as pool:
                risultati = list(pool.map(self._richiesta, lotti))
        else:
            risultati = [self._richiesta(l) for l in lotti]
        righe = [r for parte in risultati for r in parte]
        v = np.asarray(righe, dtype="float32")
        taglio = int(os.environ.get("NN_VETTORI_TAGLIO", "0") or 0)
        if taglio and v.ndim == 2 and v.shape[1] > taglio:
            v = v[:, :taglio]   # solo per modelli addestrati a reggere il taglio (es. Qwen3-Embedding)
        if normalize_embeddings and len(v):
            n = np.linalg.norm(v, axis=1, keepdims=True)
            n[n == 0] = 1
            v = v / n
        return v


def modelli(token: str | None = None) -> list[dict]:
    """I modelli disponibili su AI Tools (GET /1/ai/models), con il loro tipo."""
    from . import ai
    ai.load_env()
    token = token or os.environ.get("INFOMANIAK_API_TOKEN", "")
    req = urllib.request.Request(f"{os.environ.get('NN_INFOMANIAK_BASE', BASE)}/1/ai/models",
                                 headers={"Authorization": f"Bearer {token}", "User-Agent": "NuovaNorma/0.4"})
    with urllib.request.urlopen(req, timeout=30) as r:
        dati = json.loads(r.read())
    return [{"nome": m.get("name"), "tipo": m.get("type"), "id": m.get("id")} for m in dati.get("data") or []]


def diagnosi() -> list[str]:
    """Prove per capire un rifiuto (403): prodotti AI visibili con il token, prodotto nel .env, percorsi v1 e v2."""
    from . import ai
    ai.load_env()
    token = os.environ.get("INFOMANIAK_API_TOKEN", "")
    pid = os.environ.get("INFOMANIAK_PRODUCT_ID", "")
    base = os.environ.get("NN_INFOMANIAK_BASE", BASE)
    righe = []

    def chiama(url, corpo=None):
        req = urllib.request.Request(url, data=json.dumps(corpo).encode() if corpo else None, headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "NuovaNorma/0.4"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()[:200]
        except Exception as e:
            return type(e).__name__, str(e)[:150].encode()

    stato, corpo = chiama(f"{base}/1/ai")
    if stato == 200:
        try:
            prodotti = json.loads(corpo).get("data") or []
        except ValueError:
            prodotti = []
        ids = [str(p.get("product_id") or p.get("id")) for p in prodotti if isinstance(p, dict)]
        righe.append(f"Prodotti AI visibili con questo token: {', '.join(ids) or 'nessuno'}")
        righe.append("INFOMANIAK_PRODUCT_ID nel .env: " + ("corrisponde" if pid in ids else f"NON corrisponde ({pid})"))
    else:
        righe.append(f"Elenco dei prodotti AI: risposta {stato} {corpo[:150]!r}")
    prova = {"model": "bge_multilingual_gemma2", "input": ["prova"]}
    for v in ("1", "2"):
        stato, corpo = chiama(f"{base}/{v}/ai/{pid}/openai/v1/embeddings", prova)
        righe.append(f"Embeddings (percorso v{v}): {stato}" + ("" if stato == 200 else f" {corpo[:120]!r}"))
    stato, corpo = chiama(f"{base}/2/ai/{pid}/openai/v1/chat/completions",
                          {"model": "mistralai/Mistral-Small-4-119B-2603", "max_tokens": 5,
                           "messages": [{"role": "user", "content": "ciao"}]})
    righe.append(f"Chat (percorso v2): {stato}" + ("" if stato == 200 else f" {corpo[:120]!r}"))
    return righe
