"""Lettori delle fonti documentali e aggiornamento dell'archivio comune (documenti.py).

Ogni fonte ha un lettore con due compiti:
  elenca()      -> i documenti che la fonte pubblica oggi (Item)
  scarica(item) -> i byte del documento (PDF o HTML); il testo lo estrae documenti.extract()

aggiorna() mette insieme le due cose: salva l'elenco, scarica solo cio che manca o che e cambiato,
conserva ogni versione e marca come "non piu pubblicati" i documenti spariti dall'elenco.
I siti cambiano: ogni lettore e scritto in modo tollerante e `py -m nn verifica-raccolte` mostra subito
quanti documenti trova, cosi un cambiamento del sito si vede invece di passare inosservato.
"""

from __future__ import annotations

import html
import re
import sqlite3
import time
import urllib.error
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

from . import documenti, sources
from .documenti import Item


def links(page: str, base: str) -> list[tuple[str, str]]:
    """Tutti i link (url assoluto, testo visibile) di una pagina HTML."""
    out = []
    for m in re.finditer(r"<a\s[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", page, re.IGNORECASE | re.DOTALL):
        href = html.unescape(m.group(1).strip())
        if href.startswith(("javascript:", "#", "mailto:", "tel:")):
            continue
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        out.append((urllib.parse.urljoin(base, href), text))
    return out


class Lettore:
    """Base dei lettori. `completo` = l'elenco restituito e tutto cio che la fonte pubblica (serve per marcare
    i documenti spariti); un lettore che fa ricerche puntuali (sentenze) lo lascia a False."""
    source: str = ""
    completo: bool = True
    descrizione: str = ""

    def elenca(self, log: Callable[[str], None] = lambda *_: None) -> list[Item]:
        raise NotImplementedError

    def scarica(self, item: Item) -> tuple[bytes, str]:
        raw = sources.fetch(item.url, timeout=120)
        return raw, ""

    def testo(self, raw: bytes, ctype: str, item: Item) -> str | None:
        """Facoltativo: testo gia ripulito. None = estrazione generica di documenti.extract()."""
        return None


@dataclass
class Esito:
    source: str
    elencati: int = 0
    nuove_versioni: int = 0
    invariati: int = 0
    saltati: int = 0
    errori: int = 0
    spariti: int = 0
    note: list = None

    def riga(self) -> str:
        return (f"{self.source}: {self.elencati} elencati, {self.nuove_versioni} nuove versioni, {self.invariati} invariati, "
                f"{self.saltati} non riletti, {self.spariti} non piu pubblicati, {self.errori} errori")


def aggiorna(con: sqlite3.Connection, lettore: Lettore, raw_dir: Path, limite: int | None = None,
             rileggi_dopo_giorni: int = 7, solo: Iterable[str] = (), log: Callable[[str], None] = print) -> Esito:
    """Aggiorna una fonte. I documenti letti da meno di `rileggi_dopo_giorni` non si riscaricano."""
    documenti.ensure(con)
    es = Esito(lettore.source, note=[])
    items = lettore.elenca(log=log)
    solo = {s.lower() for s in solo}
    if solo:
        items = [i for i in items if i.key.lower() in solo]
    es.elencati = len(items)
    seen_at = documenti.now()
    soglia = (datetime.now(timezone.utc) - timedelta(days=rileggi_dopo_giorni)).isoformat(timespec="seconds")
    for n, it in enumerate(items):
        documenti.save_item(con, it, seen_at)
        last = con.execute("SELECT MAX(fetched_at) FROM doc_versions WHERE source=? AND key=? AND lang=?",
                           (it.source, it.key, it.lang)).fetchone()[0]
        if limite is not None and n >= limite:
            es.saltati += 1
            continue
        if last and rileggi_dopo_giorni > 0 and last >= soglia:
            es.saltati += 1
            continue
        try:
            if not sources.robots_ok(it.url):
                es.saltati += 1
                es.note.append(f"{it.key}: escluso dal robots.txt del sito")
                continue
            raw, ctype = lettore.scarica(it)
            documenti.save_item(con, it, seen_at)  # lo scaricamento puo aver precisato la lingua del testo
            r = documenti.save_version(con, it, raw, raw_dir, ctype, lettore.testo(raw, ctype, it))
            if r["nuova"]:
                es.nuove_versioni += 1
                log(f"  nuovo  {it.key:<18} {r['valid_from'] or '':10}  {it.title[:70]}")
            else:
                es.invariati += 1
                # rilettura senza cambiamenti: si annota comunque il controllo
                con.execute("UPDATE doc_versions SET fetched_at=? WHERE id=?", (documenti.now(), r["id"]))
        except Exception as e:  # un documento rotto non ferma la fonte
            es.errori += 1
            es.note.append(f"{it.key}: {type(e).__name__}: {str(e)[:160]}")
            log(f"  errore {it.key}: {type(e).__name__}: {str(e)[:160]}")
        if n % 20 == 19:
            con.commit()
    if lettore.completo and items and not solo and limite is None:
        es.spariti = documenti.mark_gone(con, lettore.source, {(i.key, i.lang) for i in items})
    con.commit()
    return es


# ---------------------------------------------------------------- Ticino: la Raccolta delle leggi in archivio

class TicinoRL(Lettore):
    """Archivia il testo di ogni atto della Raccolta ticinese con le sue versioni.

    L'elenco viene dall'indice gia costruito con `indicizza-ticino` (tabella cantonal_acts): qui si scarica
    la pagina 'legge-piatta' di ogni atto, che contiene il testo intero in HTML."""
    source = "ticino"
    descrizione = "Raccolta delle leggi del Cantone Ticino: testo di ogni atto, con versioni"

    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def elenca(self, log=lambda *_: None) -> list[Item]:
        from . import cantoni
        cantoni._ensure(self.con)
        out = []
        for r in self.con.execute("SELECT * FROM cantonal_acts WHERE canton='TI'"):
            url = r["url"]
            m = cantoni.ACT_ID_RE.search(url)
            if m and "/pdfatto/" not in url:
                url = re.sub(r"/raccolta-leggi/legge(?:-piatta)?/", "/raccolta-leggi/legge-piatta/", url)
            key = r["number"] or f"id-{r['act_key']}"
            out.append(Item(self.source, key, r["title"], "legge_cantonale", url, "it", page_url=r["url"],
                            meta={"act_key": r["act_key"], "numero_rl": r["number"]}))
        if not out:
            log("  indice ticinese vuoto: esegui prima  py -m nn indicizza-ticino")
        return out

    def testo(self, raw: bytes, ctype: str, item: Item) -> str | None:
        from . import cantoni
        if raw[:5] == b"%PDF-":
            return None
        # stessa pulizia di cantoni.text(), che conosce la struttura delle pagine della RL
        page = raw.decode("utf-8", "replace")
        txt = documenti.html_text(page, main=False)
        base = re.split(r"\s[\(\-–]", item.title or "")[0].strip()
        m = re.search(r"\s+".join(re.escape(w) for w in base.split()[:8]), txt, re.IGNORECASE) if base else None
        k = m.start() if m else (txt.find(item.meta.get("numero_rl") or "\x00"))
        return txt[k:] if 0 < k < 3000 else txt


# ---------------------------------------------------------------- UFAS: direttive AVS, AI, IPG, PC

_RE_DOC = re.compile(r"/(it|de|fr)/d/(\d+)(?:[/?#]|$)")
_RE_NUM_UFAS = re.compile(r"\b(3\d{2}\.\d{3}(?:\.\d{1,2})?)\s*([idf])?\b")
_RE_SIGLA = re.compile(r"\(([A-ZÄÖÜ][A-Za-zÄÖÜäöü\-]{1,14}(?:\s[A-Z]{1,4})?)\)|^\s*([A-ZÄÖÜ]{2,10}(?:-[A-Z]{1,6})?)\b")


class UFAS(Lettore):
    """Direttive, circolari e supplementi dell'UFAS su sozialversicherungen.admin.ch.

    Ogni cartella e una pagina HTML statica (/it/f/<cartella>) con, per ogni documento, il link alla pagina
    /it/d/<id>; il PDF in vigore si scarica da /it/d/<id>/download. Se manca la versione italiana si prende
    quella francese o tedesca, e lo si dichiara."""
    source = "ufas"
    descrizione = "Direttive e circolari dell'UFAS su AVS, AI, IPG e prestazioni complementari"
    BASE = "https://sozialversicherungen.admin.ch"
    CARTELLE = {
        5621: ("AVS", "contributi"), 5622: ("AVS", "rendite"), 5623: ("AVS", "vigilanza e organizzazione"),
        5625: ("AVS", "sistemi d'informazione"), 5624: ("AVS/AI", "regresso"),
        5665: ("AVS", "contributi, supplementi"), 5666: ("AVS", "rendite, supplementi"), 5667: ("AVS", "vigilanza, supplementi"),
        5661: ("AI", "prestazioni individuali, circolari"), 5662: ("AI", "prestazioni individuali, lettere circolari"),
        5659: ("AI", "prestazioni collettive, circolari"), 5660: ("AI", "prestazioni collettive, lettere circolari"),
        5637: ("AI", "regresso"),
        5619: ("IPG", "direttive"), 5620: ("IPG", "supplementi"),
        5638: ("PC", "direttive"), 5639: ("PC", "commenti"), 5640: ("PC", "supplementi"),
        17490: ("PT", "prestazioni transitorie, direttive"),
        5579: ("PP", "previdenza professionale, istruzioni"), 5578: ("PP", "Bollettino della previdenza professionale"),
        5583: ("PP", "previdenza professionale, compilazioni"),
        5599: ("AFam", "assegni familiari, direttive"),
        5574: ("AMal", "assicurazione malattie, esecuzione"), 5573: ("AInf", "assicurazione infortuni, esecuzione"),
        12384: ("LPGA", "osservazioni sulla parte generale"),
    }

    def __init__(self, con=None):
        self.con = con

    def _pagina(self, cartella: int) -> str:
        return sources.fetch_text(f"{self.BASE}/it/f/{cartella}", timeout=60)

    def elenca(self, log=lambda *_: None) -> list[Item]:
        out: dict[str, Item] = {}
        for cartella, (ramo, tipo) in self.CARTELLE.items():
            try:
                page = self._pagina(cartella)
            except Exception as e:
                log(f"  cartella {cartella} ({ramo}, {tipo}) non letta: {type(e).__name__}")
                continue
            trovati = self.leggi_cartella(page, ramo, tipo, cartella)
            log(f"  cartella {cartella} {ramo} {tipo}: {len(trovati)} documenti")
            for it in trovati:
                out.setdefault(it.key, it)
        return list(out.values())

    def leggi_cartella(self, page: str, ramo: str, tipo: str, cartella: int) -> list[Item]:
        """Riconosce i documenti di una pagina-cartella: id e titolo. Numero, sigla e date si leggono dalla pagina
        di dettaglio di ciascuno (dettaglio()), dove non c'e ambiguita su a quale documento appartengono."""
        posti = [(m.start(), m) for m in re.finditer(r"<a\s[^>]*?href=[\"']([^\"']*/d/\d+[^\"']*)[\"'][^>]*>(.*?)</a>", page, re.I | re.S)]
        items: dict[str, Item] = {}
        for k, (pos, m) in enumerate(posti):
            href = html.unescape(m.group(1))
            d = _RE_DOC.search(href)
            if not d:
                continue
            docid = d.group(2)
            lingua_link = d.group(1)
            titolo = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
            it = items.get(docid)
            if it is None:
                if not titolo or titolo.lower() in ("download", "scarica", "pdf"):
                    titolo = ""
                it = Item(self.source, docid, titolo, "direttiva", f"{self.BASE}/it/d/{docid}/download", "it",
                          page_url=f"{self.BASE}/it/d/{docid}", meta={"ramo": ramo, "categoria": tipo, "cartella": cartella})
                items[docid] = it
            if lingua_link != "it":
                it.meta["manca_italiano"] = True   # l'elenco rimanda direttamente alla versione tedesca o francese
            if titolo and not it.title and titolo.lower() not in ("download", "scarica", "pdf"):
                it.title = titolo
        for it in items.values():
            if not it.title:
                it.title = f"Documento UFAS {it.key}"
            it.title = f"{it.meta['ramo']} · {it.title}"
        return list(items.values())

    def dettaglio(self, page: str, item: Item) -> None:
        """Numero ufficiale, sigla e date dalla pagina /it/d/<id>. La prima occorrenza e quella della versione
        in vigore (la tabella delle versioni precedenti viene dopo)."""
        txt = documenti.html_text(page)
        num = _RE_NUM_UFAS.search(txt)
        if num:
            item.meta["numero"] = num.group(1)
        sig = _RE_SIGLA.search(item.title.split("·", 1)[-1])
        if sig:
            item.meta["sigla"] = (sig.group(1) or sig.group(2)).strip()
        stato = re.search(r"\b[Ss]tato(?: al)?\s*:?\s*(\d{1,2}\.?\s*°?\s*[a-z]+\s+\d{4}|\d{1,2}\.\d{1,2}\.\d{4})", txt)
        dal = re.search(r"[Vv]alid[ao] dal\s*:?\s*(\d{1,2}\.\d{1,2}\.\d{4})", txt)
        if dal:
            item.meta["valida_dal"] = documenti.parse_date(dal.group(1))
        item.valid_from = (documenti.parse_date(stato.group(1)) if stato else "") or item.meta.get("valida_dal", "")
        if re.search(r"non [eè] stata trovata alcuna versione valida nella lingua selezionata", txt, re.I):
            item.meta["manca_italiano"] = True

    def scarica(self, item: Item) -> tuple[bytes, str]:
        try:
            self.dettaglio(sources.fetch_text(item.page_url, timeout=60), item)
        except Exception as e:  # senza dettaglio si va avanti: la data si cerca nel PDF
            item.meta["dettaglio"] = f"non letto: {type(e).__name__}"
        errori = []
        for lang in (("de", "fr") if item.meta.get("manca_italiano") else ("it", "fr", "de")):
            url = f"{self.BASE}/{lang}/d/{item.key}/download"
            try:
                raw = sources.fetch(url, timeout=120, retries=2)
            except Exception as e:
                errori.append(f"{lang}: {type(e).__name__}")
                continue
            if raw[:5] == b"%PDF-":
                item.meta["lingua_testo"] = lang
                if lang != "it":
                    item.meta["nota_lingua"] = "versione italiana non pubblicata: testo in " + {"fr": "francese", "de": "tedesco"}[lang]
                return raw, "application/pdf"
            errori.append(f"{lang}: non e un PDF")
        raise RuntimeError("nessun PDF scaricabile (" + ", ".join(errori) + ")")


# ---------------------------------------------------------------- CAV PP (alta vigilanza previdenza professionale)

_RE_CAV_SLUG = re.compile(r"/it/(direttive-d|comunicazioni-c)-(\d{1,2})-(\d{4})/?$")
_RE_CAV_PDF = re.compile(r"\b([DCMW])\s*[-–]?\s*(\d{1,2})[_/](\d{4})", re.I)


def _lingua_da_nome(nome: str) -> str:
    n = nome.lower()
    if "première" in n or "premiere" in n or "révisée" in n or "chs pp" in n:
        return "fr"
    if "erstversion" in n or "überarbeitet" in n or "ueberarbeitet" in n or "oak bv" in n:
        return "de"
    return "it"


class CAVPP(Lettore):
    """Direttive e comunicazioni della Commissione di alta vigilanza della previdenza professionale.
    Le pagine di dettaglio stanno nella sitemap italiana; il PDF (indirizzo non deducibile) si legge dalla pagina.
    Molti PDF della pagina italiana sono solo in francese: la lingua si deduce dal nome del file e si dichiara."""
    source = "cavpp"
    descrizione = "CAV PP: direttive e comunicazioni sulla vigilanza della previdenza professionale"
    BASE = "https://www.oak-bv.admin.ch"

    def __init__(self, con=None):
        self.con = con

    def pdf_piu_recente(self, page: str, url: str) -> tuple[str, str, str] | None:
        """(url del PDF, data AAAA-MM-GG, lingua) della versione piu recente sulla pagina."""
        best = None
        for href, testo in links(page, url):
            p = urllib.parse.urlparse(href)
            if not (p.netloc.endswith("oak-bv.admin.ch") and p.path.lower().endswith(".pdf")):
                continue
            nome = urllib.parse.unquote(p.path.rsplit("/", 1)[-1])
            d = _DATA_NOME.search(nome)
            data = documenti.parse_date(d.group(0)) if d else ""
            cand = (data, href, _lingua_da_nome(nome + " " + testo))
            if best is None or cand[0] > best[0]:
                best = cand
        return (best[1], best[0], best[2]) if best else None

    def elenca(self, log=lambda *_: None) -> list[Item]:
        out: dict[str, Item] = {}
        urls = IFPDT.sitemap_urls(sources.fetch_text(self.BASE + "/sitemap/it.xml", timeout=60))
        for u in urls:
            m = _RE_CAV_SLUG.search(urllib.parse.urlparse(u).path)
            if not m:
                continue
            tipo = "direttiva" if m.group(1).startswith("direttive") else "comunicazione"
            key = f"{'D' if tipo == 'direttiva' else 'C'}-{int(m.group(2)):02d}/{m.group(3)}"
            try:
                page = sources.fetch_text(u, timeout=60)
            except Exception as e:
                log(f"  {key}: pagina non letta ({type(e).__name__})")
                continue
            pdf = self.pdf_piu_recente(page, u)
            if not pdf:
                log(f"  {key}: nessun PDF sulla pagina")
                continue
            t = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", page)
            titolo = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t.group(1)))).strip() if t else key
            meta = {"lingua_testo": pdf[2]} if pdf[2] != "it" else {}
            if pdf[2] != "it":
                meta["nota_lingua"] = "versione italiana non pubblicata: testo in " + {"fr": "francese", "de": "tedesco"}[pdf[2]]
            out[key] = Item(self.source, key, titolo, tipo, pdf[0], "it", page_url=u, valid_from=pdf[1], meta=meta)
        log(f"  {len(out)} direttive e comunicazioni in vigore")
        return list(out.values())


_DATA_NOME = re.compile(r"\d{1,2}\.\d{1,2}\.\d{4}")


# ---------------------------------------------------------------- Promemoria AVS/AI (ahv-iv.ch)

class Promemoria(Lettore):
    """Promemoria del Centro d'informazione AVS/AI: pagine-categoria statiche con numero, titolo e link al PDF
    (/p/<numero>.i). La data si legge nel PDF ("Stato al 1° gennaio 2026"), non nell'elenco."""
    source = "promemoria"
    descrizione = "Promemoria AVS/AI (spiegazioni ufficiali divulgative, aggiornate ogni anno)"
    INDICE = "https://www.ahv-iv.ch/it/Opuscoli"

    def __init__(self, con=None):
        self.con = con

    def categorie(self, page: str) -> list[str]:
        out = []
        for href, _ in links(page, self.INDICE):
            p = urllib.parse.urlparse(href)
            if p.netloc.endswith("ahv-iv.ch") and re.fullmatch(r"/it/Opuscoli/[^/]+", p.path) and href not in out:
                out.append(href.split("#")[0])
        return out

    def leggi_categoria(self, page: str, url: str) -> list[Item]:
        items: dict[str, Item] = {}
        nome_cat = urllib.parse.unquote(url.rsplit("/", 1)[-1]).replace("-", " ")
        posti = list(re.finditer(r"<a\s[^>]*?href=[\"']([^\"']*/p/(\d{1,2}\.\d{2})\.i)[\"'][^>]*>(.*?)</a>", page, re.I | re.S))
        for k, m in enumerate(posti):
            num = m.group(2)
            inizio = posti[k - 1].end() if k else max(0, m.start() - 1500)
            fine = posti[k + 1].start() if k + 1 < len(posti) else m.end() + 1500
            ctx = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page[inizio:fine])))
            testo_link = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(3)))).strip()
            it = items.get(num)
            if it is None:
                it = Item(self.source, num, "", "promemoria", urllib.parse.urljoin(url, html.unescape(m.group(1))), "it",
                          page_url=url, meta={"categoria": nome_cat})
                items[num] = it
            if testo_link and not re.fullmatch(r"(?i)pdf|scarica|download|[\d.]+", testo_link) and not it.title:
                it.title = testo_link
            if not it.title:
                t = re.search(re.escape(num) + r"\s*[-–:]?\s*([^\d][^|]{5,120}?)\s+(?:Stato|Ultimo|PDF|\d{2}\.\d{2}\.\d{4})", ctx)
                if t:
                    it.title = t.group(1).strip(" -–:")
        for it in items.values():
            it.title = it.title or f"Promemoria {it.key}"
        return list(items.values())

    def elenca(self, log=lambda *_: None) -> list[Item]:
        indice = sources.fetch_text(self.INDICE, timeout=60)
        cats = self.categorie(indice)
        out: dict[str, Item] = {}
        for it in self.leggi_categoria(indice, self.INDICE):
            out.setdefault(it.key, it)
        for url in cats:
            try:
                page = sources.fetch_text(url, timeout=60)
            except Exception as e:
                log(f"  categoria non letta: {url} ({type(e).__name__})")
                continue
            trovati = self.leggi_categoria(page, url)
            log(f"  {urllib.parse.unquote(url.rsplit('/', 1)[-1])}: {len(trovati)} promemoria")
            for it in trovati:
                out.setdefault(it.key, it)
        return list(out.values())


# ---------------------------------------------------------------- IFPDT (edoeb.admin.ch)

class IFPDT(Lettore):
    """Sito statico dell'IFPDT. Le pagine si elencano dalla sitemap italiana; i PDF (guide, promemoria, decisioni,
    raccomandazioni) dai link delle pagine di documentazione."""
    source = "ifpdt"
    descrizione = "IFPDT: guide, promemoria, FAQ, decisioni e raccomandazioni sulla protezione dei dati"
    BASE = "https://www.edoeb.admin.ch"
    SITEMAP = BASE + "/sitemap/it.xml"
    PAGINE_PDF = {"/it/documentazione-protezione-dei-dati": "guida", "/it/decisioni": "decisione",
                  "/it/raccomandazioni-secondo-ltras": "raccomandazione"}

    def __init__(self, con=None):
        self.con = con

    @staticmethod
    def sitemap_urls(xml: str) -> list[str]:
        return [html.unescape(u.strip()) for u in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml)]

    def pdf_da_pagina(self, page: str, url: str, kind: str) -> list[Item]:
        out = {}
        for href, testo in links(page, url):
            p = urllib.parse.urlparse(href)
            if p.netloc.endswith("edoeb.admin.ch") and "/dam/" in p.path and p.path.lower().endswith(".pdf"):
                nome = p.path.rsplit("/", 1)[-1][:-4]
                lang = (re.search(r"/dam/(it|de|fr|en)/", p.path) or [None, "it"])[1]
                key = f"pdf:{nome}"
                out.setdefault(key, Item(self.source, key, testo or nome.replace("_", " "), kind, href, "it", page_url=url,
                                         meta={"lingua_testo": lang} if lang != "it" else {}))
        return list(out.values())

    def elenca(self, log=lambda *_: None) -> list[Item]:
        out: dict[str, Item] = {}
        try:
            urls = self.sitemap_urls(sources.fetch_text(self.SITEMAP, timeout=60))
        except Exception as e:
            urls = []
            log(f"  sitemap non letta: {type(e).__name__}")
        for u in urls:
            p = urllib.parse.urlparse(u)
            if not p.path.startswith("/it/") or len(p.path) <= 4:
                continue
            slug = p.path[4:].strip("/")
            out.setdefault(slug, Item(self.source, slug, slug.replace("-", " ").capitalize(), "pagina", u, "it"))
        log(f"  pagine dalla sitemap: {len(out)}")
        for path, kind in self.PAGINE_PDF.items():
            try:
                page = sources.fetch_text(self.BASE + path, timeout=60)
            except Exception as e:
                log(f"  {path} non letta: {type(e).__name__}")
                continue
            trovati = self.pdf_da_pagina(page, self.BASE + path, kind)
            log(f"  {path}: {len(trovati)} PDF")
            for it in trovati:
                out.setdefault(it.key, it)
        return list(out.values())

    def testo(self, raw: bytes, ctype: str, item: Item) -> str | None:
        if raw[:5] == b"%PDF-":
            return None
        page = raw.decode("utf-8", "replace")
        t = re.search(r"(?is)<title>(.*?)</title>", page)
        if t and item.kind == "pagina":
            item.title = re.sub(r"\s+", " ", html.unescape(t.group(1))).split(" - ")[0].strip() or item.title
        return documenti.html_text(page)


# ---------------------------------------------------------------- siti della Confederazione (stesso sistema di pubblicazione)

_RE_DATE_NOME = re.compile(r"(?:[_\- ]?(?:\d{1,2}[._]\d{1,2}[._]\d{4}|\d{8}|\d{4}-\d{2}-\d{2}))")
_RE_VERSIONE_NOME = re.compile(r"(?i)[_\- ](prima[_ ]versione|versione[_ ]revisionata|premi[eè]re[_ ]version|version[_ ]r[ée]vis[ée]e|"
                               r"erstversion|[üu]berarbeitete[_ ]version|v\d+|stand)")


def chiave_da_file(nome: str) -> str:
    """Chiave stabile da un nome di file: senza estensione, date e indicazioni di versione, cosi una nuova
    edizione dello stesso documento diventa una nuova versione e non un documento diverso."""
    base = urllib.parse.unquote(nome).rsplit("/", 1)[-1]
    base = re.sub(r"\.pdf$", "", base, flags=re.I)
    base = _RE_VERSIONE_NOME.sub("", base)
    base = _RE_DATE_NOME.sub("", base)
    return re.sub(r"[\s_]+", "_", base).strip("_-. ") or nome


class SitoConfederazione(Lettore):
    """Lettore generico per i siti dell'amministrazione federale: pagine di sezione HTML statiche con link ai PDF
    (di solito sotto /dam/). Si leggono le pagine indicate e, se profondita=1, le sottopagine dello stesso sito
    sotto lo stesso percorso. Per ogni documento si tiene il PDF piu recente (data nel nome, se c'e)."""
    source = ""
    descrizione = ""
    BASE = ""
    SEZIONI: dict[str, str] = {}      # percorso -> tipo di documento (guida, direttiva, decisione...)
    FILTRO = r"\.pdf$"                # quali link sono documenti
    PROFONDITA = 0
    MAX_SOTTOPAGINE = 60

    def __init__(self, con=None):
        self.con = con

    def documenti_pagina(self, page: str, url: str, kind: str) -> list[Item]:
        out: dict[str, Item] = {}
        host = urllib.parse.urlparse(self.BASE).netloc.split(":")[0].removeprefix("www.")
        for href, testo in links(page, url):
            p = urllib.parse.urlparse(href)
            if not p.netloc.endswith(host) or not re.search(self.FILTRO, urllib.parse.unquote(p.path), re.I):
                continue
            nome = urllib.parse.unquote(p.path.rsplit("/", 1)[-1])
            key = self.chiave(nome, testo)
            d = _DATA_NOME.search(nome) or re.search(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)", nome)
            data = (documenti.parse_date(d.group(0)) if d and "." in d.group(0)
                    else f"{d.group(1)}-{d.group(2)}-{d.group(3)}" if d and d.lastindex == 3 else "")
            lang_dam = (re.search(r"/dam/(it|de|fr|en)/", p.path) or [None, "it"])[1]
            lingua = _lingua_da_nome(nome) if lang_dam == "it" else lang_dam
            if re.search(r"(?i)[_\-](de|ger|deutsch)\.pdf$", nome):
                lingua = "de"
            elif re.search(r"(?i)[_\-](fr|franz|français)\.pdf$", nome):
                lingua = "fr"
            prima = out.get(key)
            if prima and prima.valid_from >= data:
                continue
            meta = {"pagina": url}
            if kind.startswith("decision"):
                meta["livello"] = "decisione"
            if lingua != "it":
                meta["lingua_testo"] = lingua
                meta["nota_lingua"] = "versione italiana non pubblicata: testo in " + {"fr": "francese", "de": "tedesco", "en": "inglese"}.get(lingua, lingua)
            titolo = testo if testo and len(testo) > 3 and not re.fullmatch(r"(?i)pdf|scarica|download|[\d.,\s]+(kb|mb)?", testo) else key.replace("_", " ")
            out[key] = Item(self.source, key, titolo[:300], kind, href.split("#")[0], "it", page_url=url, valid_from=data, meta=meta)
        return list(out.values())

    def chiave(self, nome: str, testo: str) -> str:
        return chiave_da_file(nome)

    def sottopagine(self, page: str, url: str) -> list[str]:
        p0 = urllib.parse.urlparse(url)
        radice = re.sub(r"\.html?$", "", p0.path).rstrip("/") + "/"
        out = []
        for href, _ in links(page, url):
            p = urllib.parse.urlparse(href)
            if p.netloc == p0.netloc and p.path.startswith(radice) and ".pdf" not in p.path.lower():
                u = href.split("#")[0]
                if u not in out:
                    out.append(u)
        return out[:self.MAX_SOTTOPAGINE]

    def elenca(self, log=lambda *_: None) -> list[Item]:
        out: dict[str, Item] = {}
        for path, kind in self.SEZIONI.items():
            url = self.BASE + path
            try:
                page = sources.fetch_text(url, timeout=60)
            except Exception as e:
                log(f"  {path} non letta: {type(e).__name__}")
                continue
            pagine = [(page, url)]
            visti, frontiera = {url}, [(page, url)]
            for _ in range(self.PROFONDITA):
                nuova = []
                for pg, u in frontiera:
                    for sub in self.sottopagine(pg, u):
                        if sub in visti or len(visti) > self.MAX_SOTTOPAGINE:
                            continue
                        visti.add(sub)
                        try:
                            nuova.append((sources.fetch_text(sub, timeout=60), sub))
                        except Exception:
                            continue
                pagine += nuova
                frontiera = nuova
            n = 0
            for pg, u in pagine:
                for it in self.documenti_pagina(pg, u, kind):
                    prima = out.get(it.key)
                    if prima is None or it.valid_from > prima.valid_from:
                        out[it.key] = it
                        n += 1
            log(f"  {path}: {n} documenti ({len(pagine)} pagine lette)")
        return list(out.values())


# ---------------------------------------------------------------- SECO: Prassi LADI (arbeit.swiss)

_RE_VALIDO = re.compile(r"(?i)\(?\s*(?:valid[ao]|in vigore|stato)\s+(?:dal|al)?\s*:?\s*(\d{1,2}\.\s*\d{1,2}\.\s*\d{4}|\d{1,2}\.?\s*°?\s*[a-z]+\s+\d{4})\s*\)?")


class SECOLADI(Lettore):
    """Prassi LADI e direttive della SECO su arbeit.swiss. La pagina delle pubblicazioni e HTML statico; i PDF stanno
    sotto /api/media/fileservice/... con un nome casuale, quindi la chiave e la data vengono dal testo del link
    ("Prassi LADI ID valida dal 1.7.2026")."""
    source = "seco_ladi"
    descrizione = "SECO: Prassi LADI e direttive sull'assicurazione contro la disoccupazione"
    PAGINA = "https://www.arbeit.swiss/it/centro-dinformazione/pubblicazioni"
    completo = False   # un cambio di titolo cambierebbe la chiave: meglio non marcare spariti

    def __init__(self, con=None):
        self.con = con

    @staticmethod
    def chiave(titolo: str) -> str:
        t = _RE_VALIDO.sub("", titolo)
        t = re.sub(r"\s*\((?:pdf|[\d.,]+\s*(?:kb|mb))[^)]*\)", "", t, flags=re.I)
        return re.sub(r"\s+", " ", t).strip(" -–:,") or titolo

    def leggi_pagina(self, page: str, url: str) -> list[Item]:
        out: dict[str, Item] = {}
        for href, testo in links(page, url):
            p = urllib.parse.urlparse(href)
            if not (p.netloc.endswith("arbeit.swiss") and "/fileservice/" in p.path and p.path.lower().endswith(".pdf")):
                continue
            if not testo or re.fullmatch(r"(?i)pdf|scarica|download|[\d.,\s]+(kb|mb)", testo):
                continue
            key = self.chiave(testo)
            v = _RE_VALIDO.search(testo)
            data = documenti.parse_date(v.group(1).replace(" ", "")) if v else ""
            prima = out.get(key)
            if prima and prima.valid_from >= data:
                continue
            out[key] = Item(self.source, key, testo, "direttiva", href, "it", page_url=url, valid_from=data)
        return list(out.values())

    def elenca(self, log=lambda *_: None) -> list[Item]:
        items = self.leggi_pagina(sources.fetch_text(self.PAGINA, timeout=60), self.PAGINA)
        log(f"  {len(items)} istruzioni e direttive")
        return items


# ---------------------------------------------------------------- Ombudsman (fondazione privata, WordPress)

class Ombudsman(Lettore):
    """Casi esemplari (articoli WordPress, interfaccia JSON pubblica) e rapporti annuali in PDF dell'Ombudsman
    dell'assicurazione privata. Fonte privata: livello 'privato'."""
    source = "ombudsman"
    descrizione = "Ombudsman dell'assicurazione privata: casi esemplari e rapporti annuali (fonte privata)"
    POST = "https://ombudsman-assicurazione.ch/wp-json/wp/v2/posts?per_page=100&page={n}"
    MEDIA = "https://versicherungsombudsman.ch/wp-json/wp/v2/media?mime_type=application/pdf&per_page=100&page={n}"

    def __init__(self, con=None):
        self.con = con
        self._testi: dict[str, str] = {}

    def _pagine(self, modello: str, log) -> list[dict]:
        out = []
        for n in range(1, 11):
            try:
                dati = sources.fetch_json(modello.format(n=n), timeout=60, retries=1)
            except urllib.error.HTTPError as e:
                if e.code == 400:   # WordPress: pagina oltre l'ultima
                    break
                raise
            if not dati:
                break
            out += dati
            if len(dati) < 100:
                break
        return out

    def da_json(self, posts: list[dict], media: list[dict]) -> list[Item]:
        items = []
        for p in posts:
            titolo = html.unescape(re.sub(r"<[^>]+>", "", (p.get("title") or {}).get("rendered", ""))).strip()
            key = f"caso:{p.get('slug') or p.get('id')}"
            self._testi[key] = titolo + "\n\n" + documenti.html_text((p.get("content") or {}).get("rendered", ""), main=False)
            items.append(Item(self.source, key, titolo or key, "caso", p.get("link", ""), "it", page_url=p.get("link", ""),
                              valid_from=(p.get("date") or "")[:10]))
        for m in media:
            url = m.get("source_url", "")
            if not url.lower().endswith(".pdf"):
                continue
            nome = url.rsplit("/", 1)[-1]
            lingua = "it" if re.search(r"(?i)riassunto|rapporto", nome) else "fr" if re.search(r"(?i)rapport_annuel|rapport-annuel", nome) else "de"
            titolo = html.unescape(re.sub(r"<[^>]+>", "", (m.get("title") or {}).get("rendered", ""))).strip() or nome
            meta = {} if lingua == "it" else {"lingua_testo": lingua, "nota_lingua": "documento in " + {"fr": "francese", "de": "tedesco"}[lingua]}
            items.append(Item(self.source, f"pdf:{nome[:-4]}", titolo, "rapporto", url, "it", valid_from=(m.get("date") or "")[:10], meta=meta))
        return items

    def elenca(self, log=lambda *_: None) -> list[Item]:
        posts = self._pagine(self.POST, log)
        try:
            media = self._pagine(self.MEDIA, log)
        except Exception as e:
            log(f"  rapporti annuali non letti: {type(e).__name__}")
            media = []
        items = self.da_json(posts, media)
        log(f"  {len(posts)} casi esemplari, {len(items) - len(posts)} PDF")
        return items

    def scarica(self, item: Item) -> tuple[bytes, str]:
        if item.key in self._testi:
            return self._testi[item.key].encode("utf-8"), "text/plain"
        return sources.fetch(item.url, timeout=120), ""

    def testo(self, raw: bytes, ctype: str, item: Item) -> str | None:
        return raw.decode("utf-8") if ctype == "text/plain" else None


# ---------------------------------------------------------------- AFC, SEM, SECO (legge sul lavoro)

_RE_AFC = re.compile(r"(?i)-ks-\d{4}-\d-(\d{3})([a-z]?)-([dvs]+)-")


class AFC(SitoConfederazione):
    """Circolari dell'Amministrazione federale delle contribuzioni (imposta federale diretta, imposta preventiva,
    tasse di bollo) e aggiornamenti della prassi IVA. La chiave e il numero della circolare: '50a' = n. 50, revisione a."""
    source = "afc"
    descrizione = "AFC: circolari su imposta federale diretta, imposta preventiva, tasse di bollo; prassi IVA"
    BASE = "https://www.estv.admin.ch"
    SEZIONI = {"/it/circolari-imposta-federale-diretta": "circolare", "/it/circolari-imposta-preventiva": "circolare",
               "/it/circolari-tasse-di-bollo": "circolare", "/it/lettere-circolari-imposta-federale-diretta": "lettera circolare",
               "/it/aggiornamenti-della-prassi-iva": "prassi IVA (progetto)"}

    def chiave(self, nome: str, testo: str) -> str:
        m = _RE_AFC.search(nome)
        if m:
            return f"n. {int(m.group(1))}{m.group(2).lower()}"
        return re.sub(r"(?i)[-_](it|ita)$", "", chiave_da_file(nome))


class SEM(SitoConfederazione):
    """Istruzioni e circolari della Segreteria di Stato della migrazione: pagina indice e capitoli (due livelli)."""
    source = "sem"
    descrizione = "SEM: istruzioni e circolari su stranieri (LStrI), libera circolazione, asilo, cittadinanza"
    BASE = "https://www.sem.admin.ch"
    SEZIONI = {"/sem/it/home/publiservice/weisungen-kreisschreiben.html": "istruzione"}
    PROFONDITA = 2
    MAX_SOTTOPAGINE = 80

    def chiave(self, nome: str, testo: str) -> str:
        return re.sub(r"(?i)[-_](i|it|ita)$", "", chiave_da_file(nome))


class SECOLavoro(SitoConfederazione):
    """Indicazioni della SECO sulla legge sul lavoro e sulle ordinanze 1-5: documento completo e PDF per articolo.
    L'anno nel nome del file e l'edizione: la chiave lo toglie, cosi ogni edizione e una versione dello stesso articolo."""
    source = "seco_ll"
    descrizione = "SECO: indicazioni sulla legge sul lavoro e sulle ordinanze 1-5 (anche per articolo)"
    BASE = "https://www.seco.admin.ch"
    SEZIONI = {"/it/indicazioni": "indicazioni", "/it/legge-sul-lavoro": "indicazioni",
               **{f"/it/indicazioni-oll-{n}": "indicazioni" for n in range(1, 6)}}

    def chiave(self, nome: str, testo: str) -> str:
        k = chiave_da_file(nome)
        k = re.sub(r"(?i)-SECO-AB(?:-\d{4})?", "", k)
        return re.sub(r"(?i)[-_](it|ita)$", "", k)

    def documenti_pagina(self, page, url, kind):
        items = super().documenti_pagina(page, url, kind)
        for it in items:
            anno = re.search(r"(?i)-SECO-AB-(\d{4})", it.url)
            if anno and not it.valid_from:
                it.meta["edizione"] = anno.group(1)
        return items


class UFSP(SitoConfederazione):
    """Circolari e lettere d'informazione dell'Ufficio federale della sanita pubblica agli assicuratori malattia (LAMal)
    e infortuni (LAINF). Le circolari LAMal precedenti esistono solo in tedesco e francese: si leggono dalla pagina
    tedesca e si dichiara la lingua. Gli elenchi tariffali in Excel (EA, EMAp, EMT) per ora restano fuori."""
    source = "ufsp"
    descrizione = "UFSP: circolari e lettere d'informazione agli assicuratori malattia e infortuni"
    BASE = "https://www.bag.admin.ch"
    SEZIONI = {"/it/assicurazione-malattie-circolari-e-lettere-dinformazione": "circolare LAMal",
               "/de/krankenversicherung-fruehere-kreis-und-informationsschreiben": "circolare LAMal (precedente)",
               "/it/assicurazione-infortuni-circolari-e-lettere-informative": "circolare LAINF"}


class SECOPrezzi(SitoConfederazione):
    source = "seco_oip"
    descrizione = "SECO: guide sull'indicazione dei prezzi (OIP), per settore"
    BASE = "https://www.seco.admin.ch"
    SEZIONI = {"/it/opuscoli-oip": "guida", "/it/principi-oip": "guida", "/it/faq-indicazione-dei-prezzi": "guida"}

    def chiave(self, nome, testo):
        k = re.sub(r"(?i)-SECO(?:-\d{4})?", "", chiave_da_file(nome))
        return re.sub(r"(?i)[-_ ](it|ita|i)$", "", k)


class UFCOM(SitoConfederazione):
    source = "ufcom"
    descrizione = "UFCOM: prescrizioni tecniche e amministrative sulle telecomunicazioni"
    BASE = "https://www.bakom.admin.ch"
    SEZIONI = {"/it/prescrizioni-tecniche-e-amministrative": "prescrizione"}

    def chiave(self, nome, testo):
        m = re.search(r"(?i)sr[_ ]?(784[._]101[._]113)[-_/]?(\d+)[._](\d+)", nome)
        return f"RS 784.101.113/{m.group(2)}.{m.group(3)}" if m else chiave_da_file(nome)


class ComCom(SitoConfederazione):
    source = "comcom"
    descrizione = "ComCom: decisioni dal 1998"
    BASE = "https://www.comcom.admin.ch"

    @property
    def SEZIONI(self):
        anno = datetime.now().year
        sez = {"/it/decisioni": "decisione"}
        sez.update({f"/it/decisioni-{a}-{a + 1}": "decisione" for a in range(1998, anno + 1, 2)})
        return sez


class COMCO(SitoConfederazione):
    source = "comco"
    descrizione = "Commissione della concorrenza: raccolta DPC e decisioni"
    BASE = "https://www.weko.admin.ch"
    SEZIONI = {"/it/diritto-e-politica-della-concorrenza-dpc": "decisione (raccolta DPC)", "/it/decisioni": "decisione"}

    def chiave(self, nome, testo):
        m = re.search(r"(?i)rpw[ _](\d{4})[ _](\d[a-z]?)", nome)
        return f"DPC {m.group(1)}/{m.group(2).lower()}" if m else chiave_da_file(nome)


class ElCom(SitoConfederazione):
    source = "elcom"
    descrizione = "ElCom: istruzioni, comunicazioni e decisioni sull'approvvigionamento elettrico"
    BASE = "https://www.elcom.admin.ch"
    SEZIONI = {"/it/istruzioni": "istruzione", "/it/istruzioni-precedenti": "istruzione (precedente)",
               "/it/comunicazioni": "comunicazione", "/it/decisioni": "decisione"}

    def chiave(self, nome, testo):
        return re.sub(r"(?i)[-_ ](it|ita|i)$", "", chiave_da_file(nome))


class UFAM(SitoConfederazione):
    source = "ufam"
    descrizione = "UFAM: aiuti all'esecuzione (elenco cronologico completo)"
    BASE = "https://www.bafu.admin.ch"
    SEZIONI = {"/it/in-ordine-cronologico": "aiuto all'esecuzione"}

    def chiave(self, nome, testo):
        m = re.search(r"(?i)\b(UV|UW|UD|UZ)-(\d{4})", nome)
        return f"{m.group(1).upper()}-{m.group(2)}" if m else re.sub(r"(?i)[-_ ](it|ita|i)$", "", chiave_da_file(nome))


_RE_SWISSMEDIC = re.compile(r"(?i)\b([A-Z]{2,3}\d{3}_\d{2}_\d{3})([dfie])(?:_([A-Z]{2}))?")


class Swissmedic(SitoConfederazione):
    """Guide (WL), promemoria (MB) e altri documenti di Swissmedic: indice e pagine di categoria (vecchio CMS,
    PDF sotto /dam/swissmedic/<lingua>/...). La chiave e il codice del documento senza la lettera della lingua."""
    source = "swissmedic"
    descrizione = "Swissmedic: guide e promemoria su medicamenti e dispositivi medici"
    BASE = "https://www.swissmedic.ch"
    SEZIONI = {"/swissmedic/it/home/services/documents.html": "guida"}
    PROFONDITA = 1
    MAX_SOTTOPAGINE = 30

    def chiave(self, nome, testo):
        m = _RE_SWISSMEDIC.search(nome)
        return (m.group(1).upper() + (f"_{m.group(3).upper()}" if m.group(3) else "")) if m else chiave_da_file(nome)

    def documenti_pagina(self, page, url, kind):
        items = super().documenti_pagina(page, url, kind)
        for it in items:
            m = _RE_SWISSMEDIC.search(urllib.parse.unquote(it.url))
            lingua = {"d": "de", "f": "fr", "i": "it", "e": "en"}.get(m.group(2).lower()) if m else None
            if lingua and lingua != "it":
                it.meta["lingua_testo"] = lingua
                it.meta["nota_lingua"] = "versione italiana non trovata su questa pagina: testo in " + {"de": "tedesco", "fr": "francese", "en": "inglese"}[lingua]
            elif lingua == "it":
                it.meta.pop("lingua_testo", None)
                it.meta.pop("nota_lingua", None)
        return items


# ---------------------------------------------------------------- Diritto UE (CELLAR)

class EURLex(Lettore):
    """Atti UE selezionati (eurlex.ATTI): per ognuno la versione consolidata piu recente in italiano. Le versioni
    precedenti si accumulano in archivio a ogni aggiornamento, come per le altre fonti."""
    source = "eurlex"
    descrizione = "Diritto UE: GDPR, AI Act, DSA, consumatori, assicurazioni, finanza, sicurezza sociale (CELLAR)"
    completo = False

    def __init__(self, con=None):
        self.con = con

    def elenca(self, log=lambda *_: None) -> list[Item]:
        from . import eurlex
        out = []
        for celex, titolo in eurlex.ATTI.items():
            try:
                vs = eurlex.versioni(celex)
            except Exception as e:
                log(f"  {celex}: versioni non lette ({type(e).__name__}: {str(e)[:100]})")
                continue
            if not vs:
                log(f"  {celex}: nessun testo XHTML in italiano")
                continue
            v = vs[-1]
            out.append(Item(self.source, celex, titolo, "atto UE", v["url"], "it", page_url=eurlex.pagina_pubblica(v["celex"]),
                            valid_from=v["data"], meta={"celex_versione": v["celex"], "versioni_note": len(vs),
                                                        "consolidata": bool(v["data"])}))
            log(f"  {celex}: {len(vs)} versioni, ultima {v['data'] or 'originale'}")
        return out

    def scarica(self, item: Item) -> tuple[bytes, str]:
        raw = sources.fetch(item.url, headers={"Accept": "application/xhtml+xml, text/html;q=0.9"}, timeout=180)
        return raw, "text/html"

    def testo(self, raw: bytes, ctype: str, item: Item) -> str | None:
        return documenti.html_text(raw.decode("utf-8", "replace"), main=False)


# ---------------------------------------------------------------- FINMA: circolari

_RE_FINMA_PDF = re.compile(r"(?:finma-rs-(\d{4})-(\d{1,2})-(\d{8})|rs-(\d{2})-(\d{1,2})(?:-letzte-aenderung-(\d{8}))?)[^/]*\.pdf", re.I)


class FINMA(Lettore):
    """Circolari FINMA. Le pagine dell'archivio (una per anno) sono HTML statico; l'elenco di quelle in vigore e
    caricato con JavaScript e di solito non porta link leggibili: si raccolgono i PDF che si trovano.
    I PDF stanno sotto /~/media/, che il robots.txt di finma.ch permette (esclude solo /sitecore/media library/)."""
    source = "finma"
    descrizione = "Circolari FINMA (archivio per anno; quelle in vigore se l'elenco e leggibile senza JavaScript)"
    BASE = "https://www.finma.ch"
    completo = False   # l'elenco delle circolari in vigore non e garantito: non si marcano documenti come spariti

    def __init__(self, con=None):
        self.con = con

    def pagine(self) -> list[tuple[str, bool]]:
        anno = datetime.now().year
        out = [(f"{self.BASE}/it/documentazione/circolari/", False)]
        out += [(f"{self.BASE}/it/documentazione/archiv/rundschreiben/archiv-{a}/", True) for a in range(2008, anno + 1) if a != 2014]
        return out

    def leggi_pagina(self, page: str, url: str, archivio: bool) -> list[Item]:
        out: dict[str, Item] = {}
        for href, testo in links(page, url):
            m = _RE_FINMA_PDF.search(urllib.parse.unquote(href))
            if not m or "finma.ch" not in urllib.parse.urlparse(href).netloc:
                continue
            if m.group(1):
                anno, num, data = m.group(1), int(m.group(2)), m.group(3)
            else:
                yy = int(m.group(4))
                anno, num, data = str(2000 + yy), int(m.group(5)), m.group(6) or ""
            key = f"{anno}/{num:02d}"
            data_iso = f"{data[:4]}-{data[4:6]}-{data[6:]}" if data else ""
            prima = out.get(key)
            if prima and (prima.meta.get("data_file", "") >= data_iso):
                continue   # tieni la versione piu recente della stessa circolare
            titolo = testo if testo and not re.fullmatch(r"(?i)pdf|scarica|download|[\d./ ]+", testo) else f"Circolare FINMA {key}"
            out[key] = Item(self.source, key, ("Archivio · " if archivio else "") + titolo, "circolare",
                            href.split("&hash=")[0], "it", page_url=url,
                            meta={"data_file": data_iso, "archivio": archivio,
                                  **({"lingua_testo": "de"} if re.search(r"_de\.pdf", href, re.I) else {})})
        return list(out.values())

    def elenca(self, log=lambda *_: None) -> list[Item]:
        out: dict[str, Item] = {}
        for url, archivio in self.pagine():
            try:
                page = sources.fetch_text(url, timeout=60)
            except Exception as e:
                log(f"  {url} non letta: {type(e).__name__}")
                continue
            trovati = self.leggi_pagina(page, url, archivio)
            if trovati or not archivio:
                log(f"  {url.replace(self.BASE, '')}: {len(trovati)} circolari")
            for it in trovati:
                prima = out.get(it.key)
                # la versione in vigore (non archivio) vince; poi la piu recente
                if prima is None or (prima.meta["archivio"] and not it.meta["archivio"]) or \
                        (prima.meta["archivio"] == it.meta["archivio"] and it.meta["data_file"] > prima.meta["data_file"]):
                    out[it.key] = it
        return list(out.values())


# ---------------------------------------------------------------- Votazioni popolari (UST, dati aperti)

CANTONI = {1: "ZH", 2: "BE", 3: "LU", 4: "UR", 5: "SZ", 6: "OW", 7: "NW", 8: "GL", 9: "ZG", 10: "FR", 11: "SO", 12: "BS",
           13: "BL", 14: "SH", 15: "AR", 16: "AI", 17: "SG", 18: "GR", 19: "AG", 20: "TG", 21: "TI", 22: "VD", 23: "VS",
           24: "NE", 25: "GE", 26: "JU"}
SEMICANTONI = {6, 7, 12, 13, 15, 16}


def _col(cols: list[str], *nomi: str) -> str | None:
    low = {c.lower().strip(): c for c in cols}
    for n in nomi:
        if n in low:
            return low[n]
    for n in nomi:
        for c in low:
            if n in c:
                return low[c]
    return None


class Votazioni(Lettore):
    """Risultati per cantone di tutte le votazioni federali (UST, opendata.swiss, uso libero con indicazione
    della fonte). Ogni oggetto in votazione diventa un documento con il risultato nazionale calcolato dai
    cantoni. Il tipo di oggetto (iniziativa, referendum) non sta in questo file: per questo il testo riporta
    maggioranza dei votanti e cantoni favorevoli, senza dichiarare da solo se l'oggetto e stato accettato."""
    source = "votazioni"
    descrizione = "Votazioni popolari federali dal 1848 (risultati per cantone, UST)"
    CSV = "https://dam-api.bfs.admin.ch/hub/api/dam/assets/33707737/master"

    def __init__(self, con=None):
        self.con = con
        self._testi: dict[str, str] = {}
        self.colonne: list[str] = []

    def analizza(self, csv_text: str) -> list[Item]:
        import csv
        import io
        rd = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")), delimiter=";" if csv_text[:2000].count(";") > csv_text[:2000].count(",") else ",")
        cols = rd.fieldnames or []
        self.colonne = cols
        c_id = _col(cols, "vorlage_id", "vorlagen_id", "vorlage_nr")
        c_data = _col(cols, "urnengang_datum", "abstimmungsdatum", "datum")
        c_kt = _col(cols, "kanton_nummer", "kantons_nummer", "kanton_id")
        c_ja = _col(cols, "stimmen_ja", "ja_stimmen", "jastimmen")
        c_nein = _col(cols, "stimmen_nein", "nein_stimmen", "neinstimmen")
        c_aventi = _col(cols, "stimmberechtigte")
        c_votanti = _col(cols, "stimmende", "eingelegte_stimmzettel", "abgegebene_stimmen")
        c_tit = _col(cols, "vorlage_titel_i", "titel_i", "vorlagen_titel_it", "titel_kurz_i", "vorlage_titel_d", "titel_d", "vorlagen_titel", "titel")
        if not (c_id and c_data and c_kt and c_ja and c_nein):
            raise RuntimeError("colonne attese non trovate nel file dell'UST; colonne presenti: " + ", ".join(cols[:30]))
        voti: dict[str, dict] = {}
        for r in rd:
            vid = (r.get(c_id) or "").strip()
            if not vid:
                continue
            v = voti.setdefault(vid, {"data": "", "titolo": "", "ja": 0, "nein": 0, "aventi": 0, "votanti": 0, "cantoni": {}})
            v["data"] = v["data"] or (r.get(c_data) or "").strip()[:10]
            v["titolo"] = v["titolo"] or ((r.get(c_tit) or "").strip() if c_tit else "")
            try:
                ja, nein = int(float(r.get(c_ja) or 0)), int(float(r.get(c_nein) or 0))
                kt = int(float(r.get(c_kt) or 0))
            except ValueError:
                continue
            v["ja"] += ja
            v["nein"] += nein
            for c, k in ((c_aventi, "aventi"), (c_votanti, "votanti")):
                if c:
                    try:
                        v[k] += int(float(r.get(c) or 0))
                    except ValueError:
                        pass
            if kt in CANTONI:
                v["cantoni"][CANTONI[kt]] = (ja, nein)
        items = []
        for vid, v in voti.items():
            data = documenti.parse_date(v["data"]) if "." in v["data"] else v["data"]
            tot = v["ja"] + v["nein"]
            pct = 100 * v["ja"] / tot if tot else 0
            favorevoli = sum(0.5 if [k for k, s in CANTONI.items() if s == c][0] in SEMICANTONI else 1
                             for c, (j, n) in v["cantoni"].items() if j > n)
            ti = v["cantoni"].get("TI")
            titolo = v["titolo"] or f"Oggetto {vid}"
            data_it = ".".join(str(int(x)) for x in reversed(data.split("-"))) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", data) else data
            righe = [f"Votazione popolare federale del {data_it}: {titolo}",
                     f"Numero dell'oggetto (UST): {vid}",
                     f"Voti validi: si {v['ja']:,} · no {v['nein']:,}".replace(",", "'"),
                     f"Maggioranza dei votanti: {'si' if v['ja'] > v['nein'] else 'no'} ({pct:.1f}% di si)",
                     f"Cantoni con maggioranza di si: {favorevoli:g} su 23 (i semicantoni contano mezzo voto). "
                     "La maggioranza dei cantoni serve solo per le modifiche costituzionali (iniziative e referendum obbligatori).",
                     ]
            if v["aventi"] and v["votanti"]:
                righe.append(f"Partecipazione: {100 * v['votanti'] / v['aventi']:.1f}%")
            if ti:
                tj, tn = ti
                righe.append(f"Ticino: si {tj:,} · no {tn:,} ({100 * tj / (tj + tn):.1f}% di si)".replace(",", "'") if tj + tn else "Ticino: nessun dato")
            righe.append("Per cantone: " + "; ".join(f"{c} {100 * j / (j + n):.1f}% si" for c, (j, n) in sorted(v["cantoni"].items()) if j + n))
            righe.append("Fonte: Ufficio federale di statistica, risultati delle votazioni popolari federali (opendata.swiss).")
            self._testi[vid] = "\n".join(righe)
            items.append(Item(self.source, vid, f"{data} · {titolo}", "votazione", self.CSV, "it", valid_from=data,
                              page_url="https://opendata.swiss/it/dataset/eidgenossische-abstimmungsresultate",
                              meta={"data": data}))
        return items

    def elenca(self, log=lambda *_: None) -> list[Item]:
        raw = sources.fetch(self.CSV, timeout=180)
        items = self.analizza(raw.decode("utf-8-sig", "replace"))
        log(f"  {len(items)} oggetti in votazione; colonne del file: {', '.join(self.colonne[:12])}...")
        return items

    def scarica(self, item: Item) -> tuple[bytes, str]:
        return self._testi[item.key].encode("utf-8"), "text/plain"

    def testo(self, raw: bytes, ctype: str, item: Item) -> str | None:
        return raw.decode("utf-8")


LETTORI: dict[str, Callable[[sqlite3.Connection], Lettore]] = {
    "ticino": TicinoRL,
    "ufas": UFAS,
    "promemoria": Promemoria,
    "cavpp": CAVPP,
    "seco_ladi": SECOLADI,
    "seco_ll": SECOLavoro,
    "afc": AFC,
    "sem": SEM,
    "ufsp": UFSP,
    "seco_oip": SECOPrezzi,
    "ufcom": UFCOM,
    "comcom": ComCom,
    "comco": COMCO,
    "elcom": ElCom,
    "ufam": UFAM,
    "swissmedic": Swissmedic,
    "eurlex": EURLex,
    "ombudsman": Ombudsman,
    "ifpdt": IFPDT,
    "finma": FINMA,
    "votazioni": Votazioni,
}

# Fonti studiate ma non ancora collegate: verifica-raccolte controlla almeno il loro robots.txt dal tuo computer.
DA_VALUTARE = {
    "Sentenze ticinesi (sentenze.ti.ch)": "https://www.sentenze.ti.ch/cgi-bin/nph-omniscgi",
    "IAS Ticino (www4.ti.ch)": "https://www4.ti.ch/dss/ias/",
    "PDF delle circolari FINMA": "https://www.finma.ch/it/~/media/finma/dokumente/dokumentencenter/myfinma/rundschreiben/x.pdf",
    "Tribunale penale federale (API Weblaw)": "https://bstger.weblaw.ch/api/getDocuments",
    "Tribunale amministrativo federale (Weblaw)": "https://bvger.weblaw.ch/api/getDocuments",
    "FUSC e Foglio ufficiale TI (API amtsblattportal.ch)": "https://amtsblattportal.ch/api/v1/publications",
    "Zefix (API ufficiale, credenziali gratuite su richiesta)": "https://www.zefix.admin.ch/ZefixPublicREST/api/v1",
    "Pubblicazioni IVA in vigore (gate.estv.admin.ch)": "https://www.gate.estv.admin.ch/mwst-webpublikationen/public",
    "Circolari della Divisione delle contribuzioni TI (www4.ti.ch)": "https://www4.ti.ch/fileadmin/DFE/DC/",
    "Dati ufficiali sui premi LAMal (opendata.bagnet.ch)": "https://opendata.bagnet.ch/?r=/download",
    "Sorveglianza dei prezzi (elenchi paginati con JavaScript)": "https://www.preisueberwacher.admin.ch/pue/it/home/documentazione/pubblicazioni/raccomandazioni.html",
    "Banca dati delle decisioni UFCOM (applicazione JavaScript)": "https://entdb.ofcomnet.ch/",
    "simap.ch (appalti pubblici)": "https://www.simap.ch/api/publications/v2/project/project-search",
}
