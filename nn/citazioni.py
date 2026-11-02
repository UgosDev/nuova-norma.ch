"""Riferimenti leggibili nel testo: la parte citata di un articolo, per la bolla, la nota a fianco e l'articolo completo.

Il testo arriva sempre dall'archivio, nella versione citata. Il codice divide l'articolo in capoversi e lettere,
segna le righe citate (dai passaggi letti dalle squadre o da «cpv. 2 lett. b») e calcola da quando il testo e
in vigore e se e gia decisa una modifica. Usato da nuova-norma, Anorma e PPaToS con la route /nn/citazione.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import unicodedata

from . import fedlex, store

# «1 Testo», «2bis Testo», «a. Testo», «c bis. Testo», «1. Testo» (numeri dentro una lettera)
_SUFFISSI = r"(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies)"
_CPV = re.compile(rf"^(\d+[a-z]?(?:\s?{_SUFFISSI})?)\s+(?=\S)")
_LETT = re.compile(rf"^([a-z](?:\s?{_SUFFISSI})?)\.\s+")
_NUM = re.compile(r"^(\d+)\.\s+")
_CITA_RS = re.compile(r"^\[?\s*RS\s+([\d.]+)\s+art\.\s*([0-9]+\s*[a-z]*(?:\s?" + _SUFFISSI + r")?)\s*(?:,\s*(\d{4}-\d{2}-\d{2}))?",
                      re.IGNORECASE)
_PARTE = re.compile(rf"(?:cpv\.?|capoverso|abs\.?|al\.?)\s*(\d+[a-z]?(?:\s?{_SUFFISSI})?)"
                    rf"(?:\s*(?:lett\.?|lettera|bst\.?|let\.?)\s*([a-z](?:\s?{_SUFFISSI})?))?", re.IGNORECASE)
MAX_ESTRATTO = 260


def dividi(testo: str) -> list[dict]:
    """Le righe di un articolo con la loro sigla: livello 0 capoverso, 1 lettera, 2 numero dentro una lettera."""
    righe: list[dict] = []
    cpv, lett = "", ""
    for riga in (testo or "").split("\n"):
        riga = riga.strip()
        if not riga:
            continue
        livello, sigla, corpo = 0, "", riga
        m = _LETT.match(riga)
        if m and righe:
            livello, sigla, corpo = 1, m.group(1) + ".", riga[m.end():]
            lett = m.group(1).replace(" ", "")
        else:
            m = _NUM.match(riga)
            if m and lett:
                livello, sigla, corpo = 2, m.group(1) + ".", riga[m.end():]
            else:
                m = _CPV.match(riga)
                if m:
                    sigla, corpo = m.group(1), riga[m.end():]
                    cpv, lett = m.group(1).replace(" ", ""), ""
                else:
                    lett = ""
        righe.append({"n": len(righe), "sigla": sigla, "testo": corpo, "livello": livello,
                      "cpv": cpv, "lett": lett if livello else "", "citata": False, "contesto": False})
    return righe


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower().replace("’", "'").replace("«", '"').replace("»", '"')
    s = re.sub(r"^\s*art\.\s*\d+\s*[a-z]*\s*", "", s)
    return re.sub(r"\s+", " ", s).strip(" .;:,")


_ART = re.compile(r"^\s*art\.\s*\d+\s*[a-z]*(?:\s?" + _SUFFISSI + r")?\s+", re.IGNORECASE)


def _senza_sigla(s: str) -> str:
    s = _ART.sub("", s.strip(), count=1)
    for r in (_LETT, _NUM, _CPV):
        s = r.sub("", s.strip(), count=1)
    return s


def parse_parte(parte: str) -> tuple[str, str]:
    """«cpv. 1 lett. b» -> ("1", "b"); «Abs. 2» -> ("2", ""); niente -> ("", "")."""
    m = _PARTE.search(parte or "")
    if not m:
        return "", ""
    return m.group(1).replace(" ", ""), (m.group(2) or "").replace(" ", "").lower()


def segna(righe: list[dict], passi=(), parte: str = "") -> list[dict]:
    """Segna le righe citate: quelle che compaiono nei passaggi letti, oppure il capoverso/lettera indicati.
    La riga d'attacco di un capoverso di cui si cita solo una lettera diventa «contesto»."""
    cpv, lett = parse_parte(parte)
    if cpv:
        for r in righe:
            if r["cpv"] == cpv and (not lett or r["lett"] == lett):
                r["citata"] = True
    pezzi = []
    for p in passi or ():
        for riga in str(p).split("\n"):
            n = _norm(_senza_sigla(riga))
            if len(n) >= 12:
                pezzi.append(n)
    if pezzi:
        tutto = " ".join(pezzi)
        for r in righe:
            t = _norm(r["testo"])
            if len(t) < 6:
                continue
            if t in tutto or any(p[:90] in t for p in pezzi if len(p) >= 25):
                r["citata"] = True
    # attacco del capoverso per le lettere citate
    for r in righe:
        if r["citata"] and r["livello"] > 0:
            capo = next((x for x in reversed(righe[:r["n"]]) if x["livello"] == 0), None)
            if capo and not capo["citata"]:
                capo["contesto"] = True
    return righe


def taglia(testo: str, n: int = MAX_ESTRATTO) -> str:
    if len(testo) <= n:
        return testo
    cut = testo[:n].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + " …"


def parse_cita(cita: str) -> tuple[str, str, str] | None:
    """«[RS 220 art. 336c, 2026-10-01]» -> ("220", "336c", "2026-10-01")."""
    m = _CITA_RS.match((cita or "").strip())
    if not m:
        return None
    return m.group(1), re.sub(r"\s+", "", m.group(2)).lower(), m.group(3) or ""


def _storia(con, uri: str, lang: str, eid: str) -> list[tuple[str, str | None]]:
    return [(r[0], r[1]) for r in con.execute(
        "SELECT v.date_applicability, a.text_hash FROM versions v LEFT JOIN articles a ON a.version_id = v.id AND a.eid = ? "
        "WHERE v.act_uri = ? AND v.lang = ? ORDER BY v.date_applicability", (eid, uri, lang))]


def _trova(con, uri: str, lang: str, art: str = "", eid: str = "", data: str = ""):
    """La riga dell'articolo nella versione in vigore alla data (o oggi), cercando per eid o per numero."""
    dates = store.list_dates(con, uri, lang)
    if not dates:
        return None, ""
    versione = max((d for d in dates if d <= data), default="") if data else store.in_force_date(dates)
    if not versione:
        return None, ""
    vid = con.execute("SELECT id FROM versions WHERE act_uri=? AND lang=? AND date_applicability=?",
                      (uri, lang, versione)).fetchone()[0]
    if eid:
        row = con.execute("SELECT * FROM articles WHERE version_id=? AND eid=?", (vid, eid)).fetchone()
        if row:
            return row, versione
    if art:
        key = store.art_key(art)
        for row in con.execute("SELECT * FROM articles WHERE version_id=? ORDER BY position", (vid,)):
            if store.art_key(row["num"] or "") == key or row["eid"] == art:
                return row, versione
    return None, versione


def scheda(con, *, cita: str = "", uri: str = "", eid: str = "", art: str = "", lingua: str = "",
           data: str = "", passi=(), parte: str = "", impronta: str = "", oggi: str | None = None) -> dict | None:
    """Tutto quello che serve alla bolla, alla nota e all'articolo completo. None se l'articolo non e in archivio."""
    oggi = oggi or datetime.date.today().isoformat()
    sr = ""
    if cita and not uri:
        p = parse_cita(cita)
        if not p:
            return None
        sr, art, data = p[0], p[1], data or p[2]
        act = store.find_act(con, sr)
    else:
        act = store.find_act(con, uri) if uri else None
    if act is None:
        return None
    uri = act["uri"]
    langs = [lingua or "it"] + [l for (l,) in con.execute("SELECT DISTINCT lang FROM versions WHERE act_uri=?", (uri,))
                                if l != (lingua or "it")]
    row, versione, lang = None, "", ""
    for l in langs:
        row, versione = _trova(con, uri, l, art, eid, data)
        if row is not None:
            lang = l
            break
    if row is None:
        return None
    eid = row["eid"]
    storia = _storia(con, uri, lang, eid)
    h = row["text_hash"]
    vigore_dal = versione
    for d, hh in reversed([x for x in storia if x[0] <= versione]):
        if hh != h:
            break
        vigore_dal = d
    dopo = next(((d, hh) for d, hh in storia if d > versione and hh != h), None)
    cambiato_il = futura = abrogato_il = ""
    if dopo:
        if dopo[0] > oggi:
            futura = dopo[0]
        elif dopo[1] is None:
            abrogato_il = dopo[0]
        else:
            cambiato_il = dopo[0]
    righe = segna(dividi(row["text"]), passi, parte)
    citate = [r for r in righe if r["citata"]]
    scelte = citate or righe[:1]
    estratto = taglia(" ".join((r["sigla"] + " " if r["sigla"] else "") + r["testo"] for r in scelte))
    percorso = json.loads(row["path"] or "[]")
    versioni = sum(1 for i, (d, hh) in enumerate(storia) if hh and (i == 0 or storia[i - 1][1] != hh))
    return {
        "tipo": "articolo", "livello": "legge",
        "rs": act["sr_number"] or sr, "legge": act["title"] or "", "atto": uri, "lingua": lang,
        "eid": eid, "num": row["num"] or "", "rubrica": store.rubrica(row["heading"], percorso),
        "percorso": " › ".join(percorso[-3:]), "versione": versione, "vigore_dal": vigore_dal,
        "futura": futura, "cambiato_il": cambiato_il, "abrogato_il": abrogato_il,
        "atto_abrogato": not act["in_force"], "versioni": versioni,
        "impronta": impronta_testo(row["text"]), "diversa": bool(impronta) and impronta != impronta_testo(row["text"]),
        "righe": righe, "parte_trovata": bool(citate), "estratto": estratto,
        "originale": fedlex.public_url(uri, lang) + "#" + eid if "fedlex" in uri else uri,
        "fonte_originale": "Fedlex" if "fedlex" in uri else "",
        "nn": "/articolo?" + "&".join(f"{k}={_q(v)}" for k, v in (("uri", uri), ("lingua", lang), ("eid", eid))),
    }


def _q(v: str) -> str:
    import urllib.parse
    return urllib.parse.quote(v, safe="")


def impronta_testo(testo: str) -> str:
    return hashlib.sha256((testo or "").encode("utf-8")).hexdigest()
