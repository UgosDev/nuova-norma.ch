"""Lettura dei testi Fedlex in formato Akoma Ntoso (XML) e scomposizione in articoli.

Il parser ignora gli spazi dei nomi XML e lavora sui nomi locali degli elementi, cosi regge
piccole differenze tra versioni dello schema.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# Le note a pie di pagina di Fedlex riportano i riferimenti alle modifiche (RU ...):
# cambiano a ogni revisione anche se il testo dell'articolo e identico, quindi le escludiamo
# dal testo normativo e le conserviamo a parte.
# A capo strutturale (capoversi, voci di elenco): distinto dagli a capo casuali del file XML.
BR = "\ue000"
SKIP_IN_TEXT = {"authorialNote", "noteRef"}
CONTAINERS = {"book", "part", "title", "chapter", "section", "subsection", "division", "level"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(el: ET.Element, skip: set[str] = SKIP_IN_TEXT) -> str:
    parts: list[str] = []

    def walk(e: ET.Element) -> None:
        if _local(e.tag) in skip:
            if e.tail:
                parts.append(e.tail)
            return
        if e.text:
            parts.append(e.text)
        for child in e:
            # Capoversi e voci di elenco vanno a capo; titoli e numeri separati da uno spazio
            if _local(child.tag) in {"item", "point"}:
                parts.append(BR)
            walk(child)
            if _local(child.tag) in {"item", "point", "paragraph"}:
                parts.append(BR)
            elif _local(child.tag) in {"p", "num", "heading"}:
                parts.append(" ")
        if e.tail:
            parts.append(e.tail)

    if el.text:
        parts.append(el.text)
    for child in el:
        walk(child)
        parts.append(" ")
    return normalize(" ".join(parts))


def normalize(s: str) -> str:
    """Spazi singoli; gli unici a capo sono quelli strutturali."""
    s = re.sub(r"\s+", " ", s.replace("\u00a0", " "))
    s = re.sub(r" ?\ue000[\ue000 ]*", "\n", s)
    # gli elementi in linea (corsivi, termini definiti) lasciano spazi prima della punteggiatura
    s = re.sub(r" +([:;,.)\]])", r"\1", s)
    s = re.sub(r"([(\[]) +", r"\1", s)
    return s.strip()


def _child(el: ET.Element, name: str) -> ET.Element | None:
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


@dataclass
class Article:
    eid: str  # identificativo stabile nel documento, es. "art_6"
    num: str  # come appare nel testo, es. "Art. 6"
    heading: str
    text: str  # testo normativo senza note
    path: list[str] = field(default_factory=list)  # capitoli e sezioni che lo contengono
    notes: list[str] = field(default_factory=list)

    @property
    def text_hash(self) -> str:
        return hashlib.sha256(f"{self.heading}\n{self.text}".encode()).hexdigest()


@dataclass
class ActText:
    title: str
    short_title: str
    articles: list[Article]


def parse(source: Path | bytes) -> ActText:
    root = ET.fromstring(source) if isinstance(source, bytes) else ET.parse(source).getroot()

    title = short = ""
    for el in root.iter():
        name = _local(el.tag)
        if name == "docTitle" and not title:
            title = _text(el)
        elif name == "shortTitle" and not short:
            short = _text(el)

    body = next((e for e in root.iter() if _local(e.tag) == "body"), root)
    articles: list[Article] = []

    def walk(el: ET.Element, path: list[str]) -> None:
        for child in el:
            name = _local(child.tag)
            if name == "article":
                articles.append(_article(child, path))
            elif name in CONTAINERS:
                n, h = _child(child, "num"), _child(child, "heading")
                label = " ".join(
                    x for x in (
                        _text(n) if n is not None else "",
                        _text(h) if h is not None else "",
                    ) if x
                )
                walk(child, path + ([label] if label else []))
            else:
                walk(child, path)

    walk(body, [])
    return ActText(title=title, short_title=short, articles=articles)


def _article(el: ET.Element, path: list[str]) -> Article:
    num_el, head_el = _child(el, "num"), _child(el, "heading")
    num = _text(num_el) if num_el is not None else ""
    heading = _text(head_el) if head_el is not None else ""
    content = [c for c in el if _local(c.tag) not in {"num", "heading"}]
    blocks = [_text(c) for c in content]
    notes = [
        _text(n, skip=set()) for n in el.iter() if _local(n.tag) == "authorialNote"
    ]
    return Article(
        eid=el.get("eId") or el.get("id") or num,
        num=num,
        heading=heading,
        text="\n".join(b for b in blocks if b),  # un capoverso per riga
        path=list(path),
        notes=notes,
    )
