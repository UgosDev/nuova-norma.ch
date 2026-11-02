"""Confronto strutturato tra due versioni di un atto: articolo per articolo, poi parola per parola."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from .akn import Article


@dataclass
class Change:
    kind: str  # "aggiunto" | "abrogato" | "modificato"
    eid: str
    num: str
    heading: str
    old: str = ""
    new: str = ""

    def word_diff(self) -> str:
        """Testo con le parole tolte tra [- -] e quelle aggiunte tra {+ +}."""
        return word_diff(self.old, self.new)


def _tokens(s: str) -> list[str]:
    return re.findall(r"\n|\w+|[^\w\s]", s)


def word_diff(old: str, new: str) -> str:
    a, b = _tokens(old), _tokens(new)
    out: list[str] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(" ".join(a[i1:i2]))
        if op in ("delete", "replace"):
            out.append("[-" + " ".join(a[i1:i2]) + "-]")
        if op in ("insert", "replace"):
            out.append("{+" + " ".join(b[j1:j2]) + "+}")
    return _tidy(" ".join(out))


def _tidy(text: str) -> str:
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r" +([,.;:)])", r"\1", text)


def word_diff_html(old: str, new: str) -> str:
    """Come word_diff, ma in HTML: <del> per le parole tolte, <ins> per quelle aggiunte."""
    from html import escape

    a, b = _tokens(old), _tokens(new)
    out: list[str] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(escape(" ".join(a[i1:i2])))
        if op in ("delete", "replace"):
            out.append("<del>" + escape(" ".join(a[i1:i2])) + "</del>")
        if op in ("insert", "replace"):
            out.append("<ins>" + escape(" ".join(b[j1:j2])) + "</ins>")
    return _tidy(" ".join(out))


def _is_repealed(a: Article) -> bool:
    # Fedlex lascia spesso l'articolo abrogato con il solo testo "Abrogato" / "Aufgehoben" / "Abrogé"
    t = a.text.lower().strip(" .")
    return t in {"abrogato", "aufgehoben", "abrogé", "abrogée", "abrogà", "repealed"}


def compare(old: list[Article], new: list[Article]) -> list[Change]:
    old_by = {a.eid: a for a in old}
    new_by = {a.eid: a for a in new}
    changes: list[Change] = []

    for a in new:
        prev = old_by.get(a.eid)
        if prev is None:
            changes.append(Change("aggiunto", a.eid, a.num, a.heading, "", a.text))
        elif prev.text_hash != a.text_hash:
            kind = "abrogato" if _is_repealed(a) and not _is_repealed(prev) else "modificato"
            changes.append(Change(kind, a.eid, a.num, a.heading or prev.heading, prev.text, a.text))

    for a in old:
        if a.eid not in new_by:
            changes.append(Change("abrogato", a.eid, a.num, a.heading, a.text, ""))
    return changes
