"""Regole del design della triade (Nuova-Norma, Anorma, PPaToS) in codice.

Fonte: canvas «PPaToS — design», pagina «Regole della triade» (versione 1, novembre 2026), e canvas
«Copia e incolla — menu della triade». Le tre pagine condividono neutri, forme, caratteri e componenti; cambia solo
l'accento, che e uno per prodotto:

  Nuova-Norma  sa        verde  #1f6f5c / scuro #6cc7b8
  Anorma       risponde  prugna #5b2a6e / scuro #d9c2ea
  PPaToS       scrive    blu    #2b5c9e / scuro #8fb3e6
  avviso, punto aperto   arancione #b4531b / scuro #e8a33d (mai rosso), fondo #fbeadf

Atrium, lo spazio condiviso tra le tre stanze, non e un prodotto: ha la cornice in pietra #5c4e40 / scuro #e3d3bd
(vedi SPAZI). Gli oggetti che vi arrivano tengono il colore del prodotto da cui vengono.

Uso in una pagina: CSS condiviso (nn.web.CSS, che include CSS_TRIADE), poi tema_css(prodotto) che sovrascrive
l'accento, favicon_init(prodotto) nella testa e copia_init(prodotto) in fondo al corpo.
"""

from __future__ import annotations

import base64
import json
import os
from html import escape

DELTA = "M121.85,0L0,248.78h243.7L121.85,0ZM121.85,37.81l64.88,196.29H25.71L121.85,37.81Z"

# accento, accento nel tema scuro, tinta chiara (fondo di righe attive), tinta scura, selezione chiara e scura,
# riflesso del logo (animazione Riflesso) in chiaro e in scuro
PRODOTTI = {
    "nuova-norma": {"nome": "Nuova-Norma", "verbo": "sa", "accento": "#1f6f5c", "scuro": "#6cc7b8",
                    "tinta": "#e7f2ef", "tinta_scura": "#183029", "sel": "#c9e2db", "sel_scura": "#2c5249",
                    "riflesso": "#6cc7b8", "riflesso_scuro": "#b9ebe0", "porta": 8765,
                    "descrizione": "Le norme in vigore, con versioni, prassi e sentenze"},
    "anorma": {"nome": "Anorma", "verbo": "risponde", "accento": "#5b2a6e", "scuro": "#d9c2ea",
               "tinta": "#f3edf6", "tinta_scura": "#2b2331", "sel": "#e2d3ea", "sel_scura": "#4a3a55",
               "riflesso": "#b48fc8", "riflesso_scuro": "#efe3f7", "porta": 8766,
               "descrizione": "Sei a norma? Una risposta verificata sul tuo caso"},
    "ppatos": {"nome": "PPaToS", "verbo": "scrive", "accento": "#2b5c9e", "scuro": "#8fb3e6",
               "tinta": "#ebf1f9", "tinta_scura": "#1e2834", "sel": "#cfdcef", "sel_scura": "#33465e",
               "riflesso": "#8fb3e6", "riflesso_scuro": "#cddff6", "porta": 8767,
               "descrizione": "I documenti della tua attività, scritti su misura"},
}


# Spazi che non sono prodotti: hanno un tema proprio ma non compaiono nella famiglia (famiglia_html).
# Atrium: pietra calda, il travertino dell'atrio romano. L* 34 (tra la prugna 27 e il blu 39), 8:1 su bianco.
SPAZI = {
    "atrium": {"nome": "Atrium", "verbo": "riunisce", "accento": "#5c4e40", "scuro": "#e3d3bd",
               "tinta": "#f6f1ea", "tinta_scura": "#2a241e", "sel": "#ebe1d3", "sel_scura": "#4a3f33",
               "riflesso": "#b8a68f", "riflesso_scuro": "#f1e6d6", "porta": 8768,
               "descrizione": "Lo spazio dove la questione si affronta insieme"},
}

# Componenti delle Regole: pulsanti (accento, bordo, scuro), etichette di stato, riga con fonte, icone di stato,
# clausola con norma a margine, conferme. Tutti con altezza minima 44 px e fuoco visibile.
CSS_TRIADE = """
:root{--ctrl:#c9d0cd;--warn-bg:#fbeadf;--on-accent:#ffffff;--tint:#e7f2ef;--sel:#c9e2db;
--r-pill:999px;--r-pannello:20px;--r-elenco:16px;--r-campo:12px;
--serif:Georgia,"Iowan Old Style","Times New Roman",serif;--mono:ui-monospace,"SF Mono",Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--ctrl:#3a4247;--warn-bg:#3a2a1a;--on-accent:#111416}}
/* i colori dei tre prodotti, per quando sono nominati (famiglia, link tra i siti): seguono il tema */
:root{--c-nn:#1f6f5c;--c-an:#5b2a6e;--c-pp:#2b5c9e;--c-at:#5c4e40}
@media (prefers-color-scheme:dark){:root{--c-nn:#6cc7b8;--c-an:#d9c2ea;--c-pp:#8fb3e6;--c-at:#e3d3bd}}
/* il delta dell'intestazione e nell'accento del prodotto */
header a.marchio .nn-tracciato{color:var(--accent)}
/* su un fondo nell'accento o arancione il testo segue il tema (nel tema scuro l'accento e chiaro) */
.nn-btn.pieno,.btn-stop.pieno{color:var(--on-accent)} .btn-stop.pieno .sq{background:var(--on-accent)}
/* stati delle domande e delle fonti: accento per cio che regge, arancione per l'incerto, grigio per lo scartato.
   Niente verde fisso (in Anorma e PPaToS sarebbe un secondo accento) e mai rosso. */
.p-acc{background:var(--tint);color:var(--accent)} .p-mar{background:var(--warn-bg);color:var(--warn)}
.p-sca{background:var(--soft);color:var(--muted);box-shadow:inset 0 0 0 1px var(--line)}
.p-avv{background:transparent;color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
.f-acc{border-left-color:var(--accent)} .f-mar{border-left-color:var(--warn)} .f-sca{border-left-color:var(--ctrl)}
::selection{background:var(--sel);color:var(--fg)}
/* l'azione principale ha l'accento del prodotto; le classi (.btn-sec, .btn-stop, .btn-scuro...) restano come sono */
button{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:10px;min-height:48px;padding:0 22px;
 border-radius:var(--r-pill);font:inherit;font-size:16px;text-decoration:none;cursor:pointer;border:1px solid transparent;
 transition:transform .12s cubic-bezier(.3,1.6,.5,1),background .15s;line-height:1.2}
.btn:active{transform:translateY(1px) scale(.97)}
.btn-grande{min-height:52px;padding:0 26px}
.btn-piccolo{min-height:44px;padding:0 16px;font-size:15px}
.btn-primario{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.btn-bordo{background:var(--card);border-color:var(--ctrl);color:var(--fg)}
.btn-bordo:hover{border-color:var(--accent)}
.btn-scuro{background:var(--fg);border-color:var(--fg);color:var(--bg)}
.btn-testo{background:transparent;border-color:transparent;color:var(--muted)}
.btn-testo:hover{color:var(--fg)}
.btn[disabled],.btn[aria-disabled=true]{opacity:.55;cursor:default;transform:none}
.etichetta{display:inline-flex;align-items:center;gap:6px;font-size:14px;line-height:1.3;padding:6px 12px;border-radius:var(--r-pill);
 border:1px solid var(--line);color:var(--fg);white-space:nowrap}
.etichetta.e-arrivo{border-style:dashed;border-color:var(--ctrl);color:var(--muted)}
.etichetta.e-prodotto{border-color:var(--accent);color:var(--accent)}
.etichetta.e-aperto{border-color:transparent;background:var(--warn-bg);color:var(--warn)}
.occhiello{margin:0 0 10px;font-size:13px;color:var(--muted);letter-spacing:.04em;text-transform:uppercase}
.riga-fonte{display:flex;justify-content:space-between;align-items:baseline;gap:16px;padding:16px 20px;border:1px solid var(--line);border-radius:var(--r-elenco)}
.riga-fonte .rs{font-size:14px;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}
.ic-stato{flex:none;display:inline-block;vertical-align:middle}
.serif{font-family:var(--serif)}
.mono{font-family:var(--mono)}
.tabular{font-variant-numeric:tabular-nums}
/* Porta verso Atrium (porta_atrium_html): Atrium e nominato, quindi compare con la sua pietra */
.porta-atrium{display:flex;flex-direction:column;gap:10px;margin:24px 0;padding:20px 22px;border:1px solid var(--line);
 border-radius:var(--r-pannello);background:var(--card)}
.porta-atrium .pa-testa{display:flex;align-items:center;gap:10px;font-size:17px;font-weight:600;color:var(--fg)}
.porta-atrium p{margin:0;color:var(--muted);font-size:15px;line-height:1.55}
.porta-atrium .btn{align-self:flex-start;color:var(--fg)}
.porta-atrium .btn:hover{border-color:var(--c-at)}
/* Menu del clic destro e conferme (nn/copia.js) */
.tr-menu{position:fixed;z-index:80;width:316px;max-width:calc(100vw - 16px);box-sizing:border-box;background:var(--card);
 color:var(--fg);border:1px solid var(--ctrl);border-radius:var(--r-pannello);box-shadow:0 12px 32px rgba(17,20,22,.12);
 padding:8px;display:flex;flex-direction:column;gap:2px;font:15px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
 transform-origin:top left;animation:tr-apri .14s ease-out}
.tr-menu .tr-testa{display:flex;gap:10px;padding:10px 12px 12px;border-bottom:1px solid var(--line);margin-bottom:6px}
.tr-menu .tr-testa svg{flex:none;margin-top:3px;color:var(--accent)}
.tr-menu .tr-ant{font-family:var(--serif);font-size:15px;line-height:1.4;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.tr-menu .tr-info{font-size:13px;color:var(--muted)}
.tr-menu .tr-voce{display:flex;align-items:center;gap:12px;width:100%;min-height:44px;padding:0 12px;border:0;border-radius:12px;
 background:transparent;color:var(--fg);font:inherit;font-size:15px;text-align:left;cursor:pointer;transform:none}
.tr-menu .tr-voce:hover,.tr-menu .tr-voce:focus-visible{background:var(--tint);outline:none}
.tr-menu .tr-voce:focus-visible{box-shadow:0 0 0 2px var(--accent)}
.tr-menu .tr-voce[disabled]{cursor:default;color:var(--muted);background:transparent}
.tr-menu .tr-voce svg{flex:none}
.tr-menu .tr-voce .tr-princ{font-weight:600}
.tr-menu .tr-tasto{margin-left:auto;font-family:var(--mono);font-size:13px;color:var(--muted)}
.tr-menu .tr-sep{height:1px;background:var(--line);margin:6px 4px}
.tr-menu .tr-nota{margin:6px 12px 4px;font-size:13px;color:var(--muted)}
.tr-toast{position:fixed;left:50%;bottom:32px;z-index:90;transform:translateX(-50%);display:flex;align-items:center;gap:12px;
 background:var(--fg);color:var(--bg);border-radius:var(--r-pill);padding:12px 20px 12px 16px;font-size:15px;max-width:calc(100vw - 32px);
 animation:tr-atterra .22s ease-out}
.tr-toast svg{flex:none;color:var(--accent-su-scuro,#e9edee)}
.tr-toast.tr-errore{background:var(--warn-bg);color:var(--fg);border:1px solid var(--warn)} .tr-toast.tr-errore svg{color:var(--warn)}
@keyframes tr-apri{from{opacity:0;transform:scale(.97)}to{opacity:1;transform:none}}
@keyframes tr-atterra{from{opacity:0;transform:translate(-50%,12px)}to{opacity:1;transform:translate(-50%,0)}}
@media (prefers-reduced-motion:reduce){.tr-menu,.tr-toast{animation:none}}
@media print{.tr-menu,.tr-toast{display:none!important}}
"""


def _p(prodotto: str) -> dict:
    if prodotto in PRODOTTI:
        return PRODOTTI[prodotto]
    if prodotto in SPAZI:
        return SPAZI[prodotto]
    raise ValueError(f"prodotto sconosciuto: {prodotto} (uno di: {', '.join([*PRODOTTI, *SPAZI])})")


def tema_css(prodotto: str) -> str:
    """L'accento del prodotto, in chiaro e in scuro. Va dopo il CSS condiviso, che resta quello di Nuova-Norma."""
    p = _p(prodotto)
    return (f":root{{--accent:{p['accento']};--tint:{p['tinta']};--sel:{p['sel']};--nn-c-shine:{p['riflesso']};"
            f"--accent-su-scuro:{p['scuro']}}}"
            f"@media (prefers-color-scheme:dark){{:root{{--accent:{p['scuro']};--tint:{p['tinta_scura']};"
            f"--sel:{p['sel_scura']};--nn-c-shine:{p['riflesso_scuro']};--accent-su-scuro:{p['scuro']}}}}}")


def favicon_init(prodotto: str) -> str:
    """Favicon come nella tavola Logo: il solo delta, bianco, sul quadrato nel colore del prodotto.
    Il puntino delle novita (una norma seguita e cambiata) e arancione, visibile su tutti e tre gli accenti."""
    p = _p(prodotto)
    return ('<script src="/nn/favicon.js"></script><script>NNFavicon.init({color:\'#1a1d1c\',colorDark:\'#e9edee\','
            f"bg:'{p['accento']}',dot:'#b4531b'}})</script>")


def delta_svg(size: int = 16, colore: str = "currentColor", stile: str = "", etichetta: str = "") -> str:
    h = round(size * 248.78 / 243.7)
    aria = f'role="img" aria-label="{escape(etichetta)}"' if etichetta else 'aria-hidden="true"'
    return (f'<svg {aria} width="{size}" height="{h}" viewBox="0 0 243.7 248.78" style="color:{colore};{stile}">'
            f'<path fill="currentColor" fill-rule="evenodd" d="{DELTA}"/></svg>')


def marchio_html(prodotto: str, size: int = 22) -> str:
    """Il nome del prodotto come nelle tavole. PPaToS: la «a» di And e il delta, all'altezza delle maiuscole."""
    p = _p(prodotto)
    if prodotto == "ppatos":
        d = round(size * 0.68)
        return (f'<span class="marchio-pp" role="img" aria-label="PPaToS" style="display:inline-flex;align-items:baseline;'
                f'font-size:{size}px;font-weight:600;letter-spacing:-.01em;line-height:1">'
                f'<span aria-hidden="true">PP</span>{delta_svg(d, "var(--accent)", "margin:0 1px")}'
                f'<span aria-hidden="true">ToS</span></span>')
    if prodotto == "atrium":
        d = round(size * 0.74)
        return (f'<span class="marchio-at" role="img" aria-label="Atrium" style="display:inline-flex;align-items:baseline;'
                f'font-size:{size}px;font-weight:500;letter-spacing:-.03em;line-height:1">'
                f'{delta_svg(d, "var(--accent)", "margin-right:1px")}<span aria-hidden="true">trium</span></span>')
    return escape(p["nome"])


VAR_PRODOTTO = {"nuova-norma": "var(--c-nn)", "anorma": "var(--c-an)", "ppatos": "var(--c-pp)", "atrium": "var(--c-at)"}

_ICONE = {
    # cerchio con spunta (fatto), cerchio vuoto (da fare), cerchio pieno al centro (ora), triangolo con «!» (punto aperto)
    "fatto": ('<circle cx="11" cy="11" r="8"/><path d="M7.5 11l2.5 2.5 4.5-5"/>', "var(--accent)", "fatto"),
    "da_fare": ('<circle cx="11" cy="11" r="8"/>', "var(--muted)", "da fare"),
    "ora": ('<circle cx="11" cy="11" r="8"/><circle cx="11" cy="11" r="3" fill="currentColor" stroke="none"/>',
            "var(--accent)", "in corso"),
    "aperto": ('<path d="M11 3.5l8 14H3z"/><path d="M11 9v4M11 15.5v.5"/>', "var(--warn)", "punto aperto"),
    "verificata": ('<path d="M5 11.5l4 4 8-9"/>', "var(--accent)", "verificata"),
}


def icona_stato(stato: str, size: int = 20, parlante: bool = False) -> str:
    """Icone di stato a tratto (1,6 px, estremi arrotondati). Il significato non sta mai solo nel colore."""
    disegno, colore, nome = _ICONE[stato]
    aria = f'role="img" aria-label="{nome}"' if parlante else 'aria-hidden="true"'
    return (f'<svg class="ic-stato" {aria} width="{size}" height="{size}" viewBox="0 0 22 22" fill="none" '
            f'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" '
            f'style="color:{colore}">{disegno}</svg>')


def famiglia_html(corrente: str, siti: dict | None = None) -> str:
    """«Fa parte della stessa famiglia»: i tre prodotti; il corrente ha il bordo nell'accento, gli altri sono link.
    Gli altri prodotti compaiono con il loro colore solo quando sono nominati (qui), mai come accento di pagina."""
    siti = siti or {}
    out = []
    for k, p in PRODOTTI.items():
        corpo = (f'<span style="display:flex;align-items:center;gap:10px;font-size:17px;font-weight:600">'
                 f'{delta_svg(18, "var(--accent)" if k == corrente else VAR_PRODOTTO[k])}{escape(p["nome"])}</span>'
                 f'<span class="muted" style="font-size:15px">{escape(p["descrizione"])}</span>')
        stile = "border:1px solid {};border-radius:16px;padding:22px 24px;display:flex;flex-direction:column;gap:6px;text-decoration:none;color:var(--fg)"
        if k == corrente or not siti.get(k):
            bordo = "var(--accent)" if k == corrente else "var(--line)"
            attuale = ' aria-current="page"' if k == corrente else ""
            out.append(f'<div style="{stile.format(bordo)}"{attuale}>{corpo}</div>')
        else:
            out.append(f'<a href="{escape(siti[k])}" style="{stile.format("var(--line)")}">{corpo}</a>')
    return ('<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px">'
            + "".join(out) + "</div>")


def copia_init(prodotto: str, sito_nn: str = "", azione: dict | None = None, sito_atrium: str | None = None) -> str:
    """Il menu del clic destro e la copia con la fonte. azione: voce propria del prodotto (vedi copia.js).
    sito_atrium: dove si apre «Porta in Atrium» (predefinito ATRIUM_SITO; stringa vuota per toglierla)."""
    p = _p(prodotto)
    conf = {"prodotto": prodotto, "nome": p["nome"], "sitoNN": sito_nn.rstrip("/"),
            "sitoAtrium": (ATRIUM_SITO if sito_atrium is None else sito_atrium).rstrip("/")}
    if azione:
        conf["azione"] = azione
    return (f"<script>window.NNCopia={json.dumps(conf, ensure_ascii=False)}</script>"
            '<script src="/nn/copia.js" defer></script>')


# --- Porte verso Atrium --------------------------------------------------------------------------------------------
# Ogni prodotto puo aprire una questione su Atrium con un oggetto gia dentro: la risposta breve di Anorma, un articolo
# di Nuova-Norma, i punti aperti di una bozza di PPaToS. L'oggetto viaggia nel frammento del link (#o=...), che il
# browser non invia al server: Atrium lo mostra prima di aprire la questione, poi lo cifra con la chiave della stanza.
# Stesse regole di atrium/statico/atrium.js (pulisciOggetto) e di atrium/porta.py.

ATRIUM_SITO = os.environ.get("NN_ATRIUM_SITO", "http://127.0.0.1:8768").rstrip("/")
LIMITI_ATRIUM = {"prodotto": 20, "titolo": 200, "testo": 1800, "fonte": 200, "url": 500}


def oggetto_atrium(oggetto: dict) -> dict:
    o = {}
    for k, n in LIMITI_ATRIUM.items():
        v = " ".join(str(oggetto.get(k) or "").split()) if k != "testo" else str(oggetto.get(k) or "").strip()
        if len(v) > n:
            v = v[: n - 1].rstrip() + "\u2026"
        if v:
            o[k] = v
    if o.get("prodotto") not in PRODOTTI:
        o["prodotto"] = "anorma"
    if o.get("url") and not o["url"].startswith(("https://", "http://")):
        o.pop("url")
    return o


def link_atrium(oggetto: dict, base: str | None = None) -> str:
    dati = json.dumps(oggetto_atrium(oggetto), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return (ATRIUM_SITO if base is None else base).rstrip("/") + "/#o=" + \
        base64.urlsafe_b64encode(dati).rstrip(b"=").decode("ascii")


def porta_atrium_html(oggetto: dict, titolo: str, testo: str, pulsante: str, base: str | None = None) -> str:
    """Il riquadro che apre una questione su Atrium con l'oggetto dentro. Vuoto se Atrium non e configurato."""
    sito = ATRIUM_SITO if base is None else base
    if not sito:
        return ""
    return (f'<aside class="porta-atrium" aria-label="Atrium"><div class="pa-testa">{delta_svg(18, "var(--c-at)")}'
            f'<span>{escape(titolo)}</span></div><p>{escape(testo)}</p>'
            f'<a class="btn btn-bordo btn-piccolo" href="{escape(link_atrium(oggetto, sito))}" target="_blank" rel="noopener">'
            f'{escape(pulsante)}</a></aside>')
