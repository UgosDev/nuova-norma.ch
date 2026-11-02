"""Interfaccia web locale di Nuova-Norma (solo libreria standard, ascolta solo su questo computer)."""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
import webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import os
from pathlib import Path

from . import __version__, agent, ai, citazioni, cli, diff, fedlex, store, triade

# Sostituibile nei test con un modello simulato
MODEL_FACTORY = ai.make_client

LANG_NAMES = {"it": "Italiano", "de": "Deutsch", "fr": "Français", "rm": "Rumantsch", "en": "English"}

CSS = """
:root{--bg:#ffffff;--fg:#1a1d1c;--muted:#4b5250;--line:#e3e7e5;--card:#ffffff;--accent:#1f6f5c;--warn:#b4531b;
--ins-bg:#e4f1ec;--ins-fg:#164f42;--del-bg:#fbeee4;--del-fg:#8a3c00;--soft:#f5f7f6;
--nn-c-edge:#585e5c;--nn-c-warn:#b4531b;--nn-c-muted:#9aa3a0;--nn-c-dash:#8a929c;--nn-c-ring:#d6dbd9;
--nn-c-skel-a:#e3e7e5;--nn-c-skel-b:#f0f2f1;--nn-c-skel-mark:#d6dbd9;--nn-c-shadow:#1a1d1c;--nn-c-shine:#6cc7b8}
@media (prefers-color-scheme:dark){:root{--bg:#111416;--fg:#e9edee;--muted:#a3adb0;--line:#2a3135;--card:#1a1f22;
--accent:#6cc7b8;--warn:#e8a33d;--ins-bg:#1d2a2a;--ins-fg:#9fdccf;--del-bg:#3a2a1a;--del-fg:#f0c48a;--soft:#171c1f;
--nn-c-edge:#a3adb0;--nn-c-warn:#e8a33d;--nn-c-muted:#5b6260;--nn-c-dash:#6b7478;--nn-c-ring:#2a3135;
--nn-c-skel-a:#242b2f;--nn-c-skel-b:#323a3f;--nn-c-skel-mark:#3a4348;--nn-c-shadow:#000000;--nn-c-shine:#b9ebe0}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
header{border-bottom:1px solid var(--line)}
header .in{max-width:860px;margin:0 auto;padding:18px 24px;display:flex;align-items:center;gap:12px}
header a{color:var(--fg);text-decoration:none;font-weight:500;letter-spacing:.01em}
header a.marchio svg{transition:transform .12s cubic-bezier(.3,1.6,.5,1);transform-origin:50% 50%}
header a.marchio:active svg{transform:translateY(2px) scale(.88)}
header nav a{padding:10px 0}
main{max-width:860px;margin:0 auto;padding:32px 24px 80px}
h1{font-size:26px;line-height:1.25;font-weight:600;margin:0 0 6px}
h2{font-size:17px;font-weight:600;margin:36px 0 12px}
.muted{color:var(--muted)} .small{font-size:14px}
a{color:var(--accent)}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px 20px;margin:0 0 12px}
.row{display:flex;justify-content:space-between;align-items:baseline;gap:16px}
.list{list-style:none;padding:0;margin:0}
.list li{border-top:1px solid var(--line);padding:10px 0}
.list li:first-child{border-top:0}
.path{font-size:13px;color:var(--muted);text-transform:none;margin:22px 0 4px}
form{display:flex;gap:8px;flex-wrap:wrap}
input,select,button{font:inherit;padding:9px 14px;border:1px solid var(--line);border-radius:12px;background:var(--card);color:var(--fg)}
button{background:var(--fg);color:var(--bg);border-color:var(--fg);cursor:pointer;border-radius:999px;padding:9px 18px;transition:transform .12s cubic-bezier(.3,1.6,.5,1),background .15s}
button:active{transform:translateY(1px) scale(.97)}
button:focus-visible,a:focus-visible,textarea:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.tag{display:inline-block;font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);color:var(--muted);margin-right:8px}
.tag.mod{border-color:var(--accent);color:var(--accent)}
.tag.add{border-color:var(--ins-fg);color:var(--ins-fg)}
.tag.rep{border-color:var(--del-fg);color:var(--del-fg)}
ins{background:var(--ins-bg);color:var(--ins-fg);text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px;padding:0 2px;border-radius:3px}
del{background:var(--del-bg);color:var(--del-fg);padding:0 2px;border-radius:3px}
.text{white-space:pre-wrap}
.legend{font-size:14px;color:var(--muted);margin:8px 0 24px}
.timeline{list-style:none;padding:0;margin:0;border-left:2px solid var(--line)}
.timeline li{padding:4px 0 14px 18px;position:relative}
.timeline li:before{content:"";position:absolute;left:-6px;top:11px;width:10px;height:10px;border-radius:50%;background:var(--bg);border:2px solid var(--muted)}
.timeline li.changed:before{border-color:var(--accent);background:var(--accent)}
.error{border-color:var(--warn);color:var(--fg);display:flex;gap:12px;align-items:flex-start}
.error>.nn-logo{flex:none;margin-top:1px;color:var(--warn)}
.vuoto{display:flex;gap:18px;align-items:center;color:var(--muted);padding:12px 0}
.vuoto p{margin:0}
.nar-ic{display:inline-flex;align-items:flex-start;flex:none}
pre.log{font-size:13px;white-space:pre-wrap;margin:0}
textarea{font:inherit;width:100%;min-height:96px;padding:12px 14px;border:1px solid var(--line);border-radius:14px;background:var(--card);color:var(--fg);resize:vertical}
.answer{white-space:pre-wrap}
.answer a.cite{font-size:14px;text-decoration:none;border:1px solid var(--line);border-radius:6px;padding:1px 6px;white-space:nowrap}
.q{font-weight:600;margin:0 0 8px}
details{margin-top:12px} summary{cursor:pointer;color:var(--muted);font-size:14px}
.f-acc{border-left:4px solid #2e7d4f} .f-mar{border-left:4px dashed #a86b00} .f-sca{border-left:4px solid #9a3b3b;opacity:.65}
table.dom{width:100%;border-collapse:collapse;font-size:14px;margin-top:8px}
table.dom td,table.dom th{padding:7px 8px;border-top:1px solid var(--line);vertical-align:top;text-align:left}
table.dom th{font-size:12px;color:var(--muted);font-weight:600}
.pill{display:inline-block;font-size:12px;padding:1px 8px;border-radius:99px;white-space:nowrap}
.p-acc{background:#e7f4ec;color:#2e7d4f} .p-mar{background:#fff4e0;color:#a86b00} .p-sca{background:#fbeaea;color:#9a3b3b}
.p-avv{background:#f3eff9;color:#6b4fa0}
.orig{display:none} .mostra .orig{display:table-cell}
.ipotesi{margin:8px 0 0;padding-left:20px} .ipotesi li{margin:2px 0}
.attesa{display:none;color:var(--muted);font-size:14px;align-items:center;gap:10px} form.lavora .attesa{display:inline-flex}
.wrap{overflow-x:auto}
.diario{list-style:none;padding:0;margin:14px 0 0}
.diario li{padding:6px 0 6px 18px;position:relative;color:var(--muted);font-size:15px;line-height:1.5}
.diario li:before{content:"";position:absolute;left:2px;top:15px;width:6px;height:6px;border-radius:50%;background:var(--line)}
.diario li:last-child{color:var(--fg)} .diario li:last-child:before{background:var(--accent)}
.lavoro-testa{display:flex;gap:18px;align-items:center} .lavoro-testa svg,header svg{flex:none}
.timeline li.changed strong{color:var(--accent)}
.in-vigore{display:inline-flex;align-items:center;gap:8px}
@media (max-width:600px){header .in{flex-wrap:wrap;gap:6px 14px;padding:14px 16px} header .ver{display:none}
 header nav{margin-left:0!important;width:100%;gap:16px!important} main{padding:24px 16px 64px}}
fieldset.campo{border:1px solid var(--line);border-radius:14px;padding:12px 14px 14px;margin:0 0 12px;background:var(--card)}
fieldset.campo legend{padding:0 6px;font-weight:600;font-size:15px}
fieldset.campo input[type=text],fieldset.campo input[type=date],fieldset.campo input[type=number]{width:100%;margin-top:6px}
.opzioni{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.opz{position:relative} .opz input{position:absolute;opacity:0;width:1px;height:1px}
.opz span{display:inline-block;padding:7px 14px;border:1px solid var(--line);border-radius:99px;cursor:pointer;font-size:15px;background:var(--bg)}
.opz input:checked+span{background:var(--fg);color:var(--bg);border-color:var(--fg)}
.opz input:focus-visible+span{outline:2px solid var(--accent);outline-offset:2px}
input.altro{margin-top:10px}
.num{display:flex;gap:10px;align-items:center} .num input{max-width:200px}
.trovate .tit{font-weight:700;letter-spacing:.02em;text-transform:uppercase;font-size:13px;color:var(--accent)}
ul.aff{margin:0;padding-left:20px} ul.aff li{margin:6px 0}
ul.aff a.cite,.dos a.cite{font-size:13px;text-decoration:none;border:1px solid var(--line);border-radius:6px;padding:1px 6px;white-space:nowrap}
.dos{font-size:13px;color:var(--muted);margin-top:4px}
.risposta .breve{font-size:18px;line-height:1.55;margin:8px 0 4px}
.risposta h3{font-size:15px;margin:20px 0 6px}
.risposta p.blocco{margin:6px 0 10px;line-height:1.6}
.risposta a.cite,.risposta span.cite{font-size:13px;text-decoration:none;border:1px solid var(--line);border-radius:6px;padding:1px 6px;white-space:nowrap;margin-left:2px}
.risposta .bozza{font-size:13px;color:var(--muted);display:flex;align-items:center;gap:8px;margin:8px 0 0;flex-wrap:wrap}
.risposta .bozza .nn-logo{flex:none;color:var(--accent)}
.risposta .tit{display:flex;align-items:center;gap:10px}
details.tutte>summary{cursor:pointer;font-weight:600;padding:4px 0}
.chat .msg{margin:10px 0;padding:10px 14px;border-radius:16px;line-height:1.55;max-width:88%}
.chat .msg.utente{margin-left:auto;background:var(--bg);border:1px solid var(--line)}
.chat .msg.assistente{background:var(--soft);border:1px solid var(--line)}
.chat .proposta{margin:8px 0 0;padding:10px 12px;border:1px dashed var(--accent);border-radius:14px}
.chat textarea{width:100%;min-height:70px}
.chat span.cite{font-size:13px;border:1px solid var(--line);border-radius:6px;padding:1px 6px;white-space:nowrap;margin-left:2px}
.precedente{border-left:3px solid var(--line)}
.chat .rapide{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 2px}
.chat .rapide button{font-size:14px;padding:6px 12px;border-radius:99px;background:var(--bg);color:var(--fg);border:1px solid var(--line)}
.chat .rapide button:hover{border-color:var(--accent)}
.chat .msg .chi{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);margin-bottom:4px}
.chat .msg .chi svg{width:12px;height:auto}
.avviso{position:fixed;right:20px;bottom:20px;max-width:360px;background:var(--card);border:1px solid var(--line);
 border-radius:16px;padding:12px 14px;box-shadow:0 6px 24px rgba(0,0,0,.12);
 display:flex;gap:10px;align-items:flex-start;z-index:50;opacity:0;transform:translateY(12px);transition:opacity .35s,transform .35s}
.avviso.mostra{opacity:1;transform:none}
.avviso>.nn-logo{flex:none;margin-top:2px}
.avviso .testo{font-size:14px;line-height:1.45}
.avviso .azioni{display:flex;gap:8px;margin-top:8px}
.avviso button{font-size:14px;padding:6px 12px}
.avviso .chiudi{background:none;border:0;color:var(--muted);padding:0 2px;font-size:18px;line-height:1;cursor:pointer}
@media (max-width:600px){.avviso{left:12px;right:12px;bottom:12px;max-width:none}}
@media (prefers-reduced-motion:reduce){.avviso{transition:none}}
.flusso{display:grid;grid-template-columns:230px 1fr;gap:26px;align-items:start}
ol.passi{list-style:none;margin:0;padding:0;border-right:1px solid var(--line);padding-right:18px}
ol.passi li{display:flex;align-items:center;gap:9px;padding:5px 0;font-size:14px;color:var(--muted)}
ol.passi .n{font-variant-numeric:tabular-nums;min-width:20px;font-size:12px}
ol.passi .ic{display:none;flex:none}
ol.passi li.fatto .ic-fatto{display:inline-flex;color:var(--accent)}
ol.passi li.attivo .ic-attivo{display:inline-flex;color:var(--fg)}
ol.passi li.attesa .ic-attesa,ol.passi li.spento .ic-attesa{display:inline-flex;color:var(--muted)}
ol.passi li.spento .ic-attesa{opacity:.6}
ol.passi li.fatto{color:var(--fg)} ol.passi li.attivo{color:var(--fg);font-weight:600}
ol.passi li.spento{opacity:.55} .non-attivo{display:block;font-size:11px;line-height:1.2}
ol.passi .nome{display:flex;flex-direction:column}
.narratore{min-width:0}
.nar-riga{display:flex;gap:16px;align-items:flex-start}
.nar-riga>.nn-logo,.nar-riga>.nar-ic{flex:none;margin-top:2px}
.nar-ora{margin:4px 0 0;font-size:17px;line-height:1.55;color:var(--fg)}
.nar-tit{margin:18px 0 0;font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.nar-prima li:last-child{color:var(--muted)} .nar-prima li:last-child:before{background:var(--line)}
.entra{animation:nn-entra .5s ease-out both}
@keyframes nn-entra{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.numeri-lavoro{margin:12px 0 0 72px;font-size:13px;color:var(--muted)}
@media (max-width:700px){.flusso{grid-template-columns:1fr;gap:16px}
 ol.passi{border-right:0;padding-right:0;display:flex;flex-wrap:wrap;gap:4px 14px;border-bottom:1px solid var(--line);padding-bottom:12px}
 ol.passi li{padding:2px 0;font-size:13px} ol.passi li.spento,ol.passi .non-attivo{display:none}
 .nar-ora{font-size:16px} .numeri-lavoro{margin-left:0}}
@media (prefers-reduced-motion:reduce){.entra{animation:none}}
[hidden]{display:none!important}
.btn-stop{background:transparent;color:var(--warn);border:2px solid var(--warn);font-weight:600;display:inline-flex;align-items:center;gap:10px}
.btn-stop .sq{width:12px;height:12px;background:var(--warn);border-radius:2px;display:inline-block}
.btn-stop.pieno{background:var(--warn);color:#fff} .btn-stop.pieno .sq{background:#fff}
.btn-sec{background:var(--card);color:var(--fg);border-color:var(--line)}
.btn-arresto{display:inline-flex;align-items:center;gap:10px} .btn-arresto .sq{width:12px;height:12px;background:var(--fg);border-radius:2px;display:inline-block}
.conferma-stop{border:2px solid var(--warn);border-radius:16px;padding:14px 16px;margin-top:12px}
.parziale{border:2px solid var(--warn);background:var(--del-bg);color:var(--fg);border-radius:16px;padding:16px 18px;margin:0 0 16px}
.parziale .tit{font-weight:700;color:var(--warn);letter-spacing:.02em;text-transform:uppercase;font-size:13px;display:flex;align-items:center;gap:10px}
.parziale .tit .nn-logo{color:var(--warn)}
.avanz{font-size:15px} .avanz b{font-weight:600}
"""

# Riferimenti leggibili nel testo (bolla, nota a fianco, articolo completo): stessi colori del sito, accento del prodotto.
CSS_CITAZIONI = """
.nn-rif{cursor:pointer}
.nn-rif[aria-expanded=true]{background:color-mix(in srgb,var(--accent) 12%,var(--card));border-color:var(--accent)}
.nn-bolla{position:absolute;z-index:60;width:min(400px,calc(100vw - 16px));box-sizing:border-box;background:var(--card);
 border:1px solid var(--line);border-radius:16px;padding:12px 14px;box-shadow:0 8px 24px rgba(0,0,0,.12);
 display:flex;flex-direction:column;gap:8px;font-size:13px;line-height:1.45;color:var(--muted);text-align:left}
.nn-bolla .testa,.nn-bolla .pie{display:flex;justify-content:space-between;gap:12px}
.nn-bolla .t{color:var(--fg);font-weight:600} .nn-bolla .rs{font-variant-numeric:tabular-nums;white-space:nowrap}
.nn-bolla .es{font-family:Georgia,"Times New Roman",serif;font-size:15px;line-height:1.55;color:var(--fg)}
.nn-bolla .pie{border-top:1px solid var(--line);padding-top:8px}
.nn-nota{position:fixed;z-index:55;box-sizing:border-box;background:var(--card);color:var(--fg);border:1px solid var(--accent);
 overflow:auto;overscroll-behavior:contain;display:flex;flex-direction:column;gap:14px}
.nn-nota:focus{outline:none}
.nn-testa{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:-6px -8px -4px 0}
.nn-testa h2{margin:0;font-size:13px;font-weight:600;color:var(--muted);letter-spacing:.04em;text-transform:uppercase}
.nn-testa h2:focus{outline:none}
.nn-chiudi,.nn-indietro{background:none;border:0;color:var(--muted);min-width:44px;min-height:44px;border-radius:999px;
 display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:0 8px;font-size:15px}
.nn-indietro{color:var(--accent);padding:0 12px 0 4px}
.nn-fonte{border:1px solid var(--line);border-radius:16px;padding:12px 14px;display:flex;justify-content:space-between;gap:14px}
.nn-fonte span:first-child{color:var(--accent)} .nn-fonte span:last-child{color:var(--muted);font-size:14px;white-space:nowrap;font-variant-numeric:tabular-nums}
.nn-percorso,.nn-liv,.nn-fede{margin:0;font-size:13px;color:var(--muted)}
.nn-fede code{font-size:12px}
.nn-cit{margin:0;background:var(--soft);border-radius:16px;padding:16px 18px;font-family:Georgia,"Times New Roman",serif;
 font-size:17px;line-height:1.65;white-space:pre-line}
.nn-cit .ctx,.nn-cit .salto{color:var(--muted)}
.nn-cit mark,.nn-riga.citata{background:color-mix(in srgb,var(--accent) 13%,transparent);color:var(--fg);border-radius:4px;padding:1px 3px}
.nn-stato{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px;font-size:14px;color:var(--muted)}
.nn-stato li{display:flex;gap:8px;align-items:flex-start} .nn-stato svg{flex:none;margin-top:3px}
.nn-stato .ok svg{color:var(--accent)} .nn-stato .avv,.nn-stato .avv a{color:var(--warn)}
.nn-azioni{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.nn-btn{display:inline-flex;align-items:center;gap:8px;min-height:44px;padding:0 18px;border-radius:999px;border:1px solid var(--line);
 background:var(--card);color:var(--fg);font:inherit;font-size:15px;text-decoration:none;cursor:pointer}
.nn-btn.pieno{background:var(--accent);border-color:var(--accent);color:#fff}
.nn-nn{display:inline-flex;align-items:center;min-height:44px;font-size:15px}
.nn-art{margin:0;font-size:24px;font-weight:500;letter-spacing:-.01em}
.nn-art:focus{outline:none}
.nn-pill{display:flex;flex-wrap:wrap;gap:8px;font-size:13px}
.nn-pill span{border:1px solid var(--line);border-radius:999px;padding:3px 10px} .nn-pill .avv{color:var(--warn);border-color:var(--warn)}
.nn-testo{border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:8px 0;max-height:52vh;overflow:auto}
.nn-riga{margin:2px 0;padding:6px 10px;font-family:Georgia,"Times New Roman",serif;font-size:16px;line-height:1.6}
.nn-riga.citata{padding:6px 10px;box-shadow:inset 0 0 0 1px var(--accent);border-radius:10px}
.nn-riga.l1{margin-left:22px} .nn-riga.l2{margin-left:44px}
.nn-riga .sg{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:13px;color:var(--muted);display:inline-block;min-width:34px;font-variant-numeric:tabular-nums}
.nn-attesa,.nn-vuoto{margin:0;color:var(--muted)}
@media (min-width:1100px){
 .nn-nota{top:88px;right:max(16px,calc((100vw - 1340px)/2));width:440px;max-height:calc(100vh - 108px);border-radius:20px;padding:20px 22px}
 body.nn-con-nota main{margin-left:max(24px,calc((100vw - 1340px)/2));max-width:min(860px,calc(100vw - 520px))}}
@media (max-width:1099.98px){
 .nn-nota{left:0;right:0;bottom:0;max-height:78vh;border-radius:20px 20px 0 0;border-width:1px 0 0;padding:14px 18px 24px;
  box-shadow:0 -8px 24px rgba(0,0,0,.18)}
 .nn-nota.piena{top:0;max-height:none;border-radius:0} .nn-nota.piena .nn-testo{max-height:none}}
@media print{.nn-bolla,.nn-nota{display:none!important}}
"""
CSS = CSS + CSS_CITAZIONI + triade.CSS_TRIADE   # Regole della triade: pulsanti, etichette, menu, conferme

# Il delta di Nuova Norma (tracciato dalla tavola di design); il colore segue il testo.
DELTA = "M121.85,0L0,248.78h243.7L121.85,0ZM121.85,37.81l64.88,196.29H25.71L121.85,37.81Z"
_TRI_EST = "M121.85,0L0,248.78h243.7Z"            # solo il contorno esterno
_TRI_INT = "M121.85,37.81l64.88,196.29H25.71Z"   # solo il contorno interno

# Le animazioni del logo (tavole G-K del canvas di design) e la favicon con il segnale di novita: file accanto a questo
_QUI = Path(__file__).resolve().parent
LOGO_CSS = (_QUI / "logo.css").read_text("utf-8")
FAVICON_JS = (_QUI / "favicon.js").read_bytes()
CITAZIONI_JS = (_QUI / "citazioni.js").read_bytes()
COPIA_JS = (_QUI / "copia.js").read_bytes()   # menu del clic destro e copia con la fonte


def citazioni_init(sito: str = "") -> str:
    """Script dei riferimenti leggibili; sito = indirizzo di nuova-norma per i link «Apri in nuova-norma»."""
    return (f"<script>window.NNCitazioni={{sito:{json.dumps(sito)}}}</script>"
            '<script src="/nn/citazioni.js" defer></script>')
FAVICON_INIT = ("<script src=\"/nn/favicon.js\"></script><script>NNFavicon.init({color:'#1a1d1c',colorDark:'#e9edee',"
                "dot:'#1f6f5c'})</script>")


def logo_svg(size: int = 20, classe: str = "") -> str:  # noqa: D401
    h = round(size * 248.78 / 243.7)
    return (f'<svg class="{classe}" aria-hidden="true" width="{size}" height="{h}" viewBox="0 0 243.7 248.78">'
            f'<path fill="currentColor" fill-rule="evenodd" d="{DELTA}"/></svg>')


def _delta(classe: str = "", vb: str = "0 0 243.7 248.78", inner: str = "") -> str:
    cls = f' class="{classe}"' if classe else ""
    return (f'<svg{cls} viewBox="{vb}" aria-hidden="true"><path fill="currentColor" fill-rule="evenodd" d="{DELTA}"/>'
            f'{inner}</svg>')


# Le animazioni della libreria (nn/logo.css), con il nome della tavola di design:
#   scan   Scansione, lettura delle fonti         drop    Drop, ragionamento (cartoncino che ruota)
#   trio   Terna, piu fonti / attesa breve         orbit   Orbita, controllo continuo
#   pend   Pendolo, in attesa dell'utente          check   Spunta, verificato / salvato
#   shake  Scossa, errore                          fall    Caduto, pagina non trovata
#   dash   Tratteggio, nessun risultato            draw    Tracciato, caricamento
#   land   Atterraggio, risultato pronto           reveal  Comparsa, apertura
#   pulse  Impulso, una novita                     flip    Entrata in vigore
#   strike Barrata, abrogata                       outline contorno fermo (in attesa)
#   stack  Pila, elenco in costruzione             diff    Sovrapposizione, confronto
#   shine  Riflesso, passa in rassegna / verificato
_ANIM_LOOP = {"scan", "drop", "trio", "orbit", "pend", "dash", "stack", "diff", "shelf", "broken"}   # stati che durano
_ANIM_ONCE = {"check", "shake", "fall", "land", "reveal", "draw", "pulse", "flip", "strike", "shine",
              "handoff", "badge", "return", "mail", "seal"}   # reazioni: una volta
_DOC = ("M30,10H130L170,50V238H30Z M130,10V50H170 M60,110H140 M60,150H140 M60,190H115")   # il documento del Passaggio


def logo_anim(kind: str, size: int = 40, label: str = "", loop: bool | None = None, classe: str = "",
              valore: int | None = None) -> str:
    """Il delta animato della tavola di design. `label` lo rende un elemento di stato leggibile; senza, e decorativo.
    `valore`: il numero del Contatore (badge) o la percentuale dell'Avanzamento (prog)."""
    if kind == "shelf":   # Scaffali: tre delta in fila su uno scaffale
        aria = f' role="status" aria-label="{escape(label)}"' if label else ' aria-hidden="true"'
        return f'<span class="nn-shelf {classe}" style="--nn-size:{size}px"{aria}>{_delta() * 3}</span>'
    if kind == "prog":    # Avanzamento: il delta si riempie fino a `valore` per cento
        p = max(0, min(100, int(valore or 0)))
        aria = f' role="img" aria-label="{escape(label or f"{p} per cento")}"'
        return (f'<span class="nn-logo nn-prog {classe}" style="--nn-size:{size}px;--nn-p:{p}"{aria}>'
                f'<svg viewBox="-4 -4 251.7 256.78" aria-hidden="true"><path class="nn-prog__track" d="{_TRI_EST}"/>'
                f'<path class="nn-prog__fill" fill="currentColor" fill-rule="evenodd" d="{DELTA}"/></svg>'
                '<span class="nn-prog__pct"></span></span>')
    if kind == "outline":
        return (f'<span class="nn-logo nn-outline {classe}" style="--nn-size:{size}px" aria-hidden="true">'
                f'<svg viewBox="-8 -8 259.7 264.78"><path d="{_TRI_EST}"/><path d="{_TRI_INT}"/></svg></span>')
    if kind == "trio":
        aria = f' role="status" aria-label="{escape(label)}"' if label else ' aria-hidden="true"'
        return f'<span class="nn-trio {classe}" style="--nn-size:{size}px"{aria}>{_delta() * 3}</span>'
    if loop is None:
        loop = kind in _ANIM_LOOP
    cls = f"nn-logo nn-{kind}" + (" nn-loop" if loop and kind in _ANIM_ONCE else "") + (" nn-once" if kind == "pulse" and not loop else "")
    if classe:
        cls += " " + classe
    aria = f' role="{"status" if kind in _ANIM_LOOP else "img"}" aria-label="{escape(label)}"' if label else ' aria-hidden="true"'
    testa = f'<span class="{cls}" style="--nn-size:{size}px"{aria}>'
    if kind == "scan":
        corpo = _delta() + _delta("nn-scan__band")
    elif kind == "drop":   # spessore solido: due facce e sei pareti, una per lato dei due triangoli
        pareti = "".join(f'<span class="nn-drop__wall nn-drop__wall--{w}"></span>' for w in ("ab", "bc", "ca", "a2b2", "b2c2", "c2a2"))
        corpo = (f'<span class="nn-drop__bob"><span class="nn-drop__tilt"><span class="nn-drop__spin">'
                 f'{_delta("nn-drop__face nn-drop__face--back")}{pareti}{_delta("nn-drop__face nn-drop__face--front")}'
                 '</span></span></span><span class="nn-drop__shadow"></span>')
    elif kind == "orbit":
        corpo = (f'<span class="nn-orbit__ring"></span>{_delta("nn-orbit__mark")}'
                 '<span class="nn-orbit__track"><span class="nn-orbit__dot"></span></span>')
    elif kind == "pend":
        corpo = f'<span class="nn-pend__arm"><span class="nn-pend__pin"></span><span class="nn-pend__wire"></span>{_delta()}</span>'
    elif kind == "check":
        corpo = _delta(inner='<path class="nn-check__tick" pathLength="100" d="M84,164L112,192L154,128"/>')
    elif kind == "dash":
        corpo = (f'<svg viewBox="-5 -5 253.7 258.78" aria-hidden="true"><path pathLength="100" d="{_TRI_EST}"/>'
                 f'<path pathLength="100" d="{_TRI_INT}"/></svg>')
    elif kind == "draw":
        corpo = (f'<svg viewBox="-6 -6 255.7 260.78" aria-hidden="true"><path class="nn-draw__out" pathLength="100" d="{_TRI_EST}"/>'
                 f'<path class="nn-draw__in" pathLength="100" d="{_TRI_INT}"/>'
                 f'<path class="nn-draw__fill" fill-rule="evenodd" d="{DELTA}"/></svg>')
    elif kind == "land":
        corpo = f'<span class="nn-land__mark">{_delta()}</span><span class="nn-land__shadow"></span>'
    elif kind == "stack":
        corpo = _delta() * 3
    elif kind == "shine":
        corpo = _delta() + _delta("nn-shine__light")
    elif kind == "diff":
        corpo = (f'<svg class="nn-diff__ghost" viewBox="0 0 243.7 248.78" aria-hidden="true"><path d="{_TRI_EST}"/></svg>'
                 + _delta("nn-diff__mark"))
    elif kind == "pulse":
        corpo = (f'<svg class="nn-pulse__ring" viewBox="0 0 243.7 248.78" aria-hidden="true"><path d="{_TRI_EST}"/></svg>'
                 + _delta("nn-pulse__mark"))
    elif kind == "flip":
        corpo = (f'<span class="nn-flip__card"><svg class="nn-flip__front" viewBox="0 0 243.7 248.78" aria-hidden="true">'
                 f'<path d="M121.85,3.5L4,245h235.7Z"/><path d="M121.85,41l61,189.5H29Z"/></svg>{_delta("nn-flip__back")}</span>')
    elif kind == "handoff":
        corpo = (_delta("nn-handoff__mark") + f'<svg class="nn-handoff__doc" viewBox="0 0 200 248" aria-hidden="true">'
                 f'<path d="{_DOC}"/></svg>')
    elif kind == "badge":
        corpo = _delta() + f'<span class="nn-badge__pill">{escape(str(valore if valore is not None else ""))}</span>'
    elif kind == "broken":
        corpo = (_delta() + '<svg class="nn-broken__wire" viewBox="0 0 90 30" aria-hidden="true">'
                 '<path class="nn-broken__a" d="M5,15H40"/><path class="nn-broken__b" d="M50,15H85"/></svg>')
    elif kind == "mail":
        corpo = (_delta("nn-mail__mark") + '<svg class="nn-mail__env" viewBox="0 0 120 90" aria-hidden="true">'
                 '<rect x="5" y="20" width="110" height="65" rx="6"/><path class="nn-mail__flap" d="M5,20L60,58L115,20"/></svg>')
    elif kind == "seal":
        corpo = '<svg class="nn-seal__ring" viewBox="0 0 100 100" aria-hidden="true"><circle cx="50" cy="50" r="44"/></svg>' + _delta()
    elif kind == "strike":
        corpo = (f'<svg viewBox="-10 -10 263.7 268.78" aria-hidden="true"><path class="nn-strike__mark" fill="currentColor" '
                 f'fill-rule="evenodd" d="{DELTA}"/><path class="nn-strike__line" pathLength="100" d="M14,240L230,12"/></svg>')
    else:   # shake, fall, reveal
        corpo = _delta()
    return testa + corpo + "</span>"


def logo_scansione(size: int = 56, label: str = "Lettura delle fonti") -> str:
    """Logo animato durante la ricerca: una banda nel colore d'accento scorre sul delta (animazione 'Scansione')."""
    return logo_anim("scan", size, label)


def logo_tracciato(size: int = 18) -> str:
    """Il logo dell'intestazione: a ogni apertura di pagina si disegna in modo diverso (contorno esterno e interno da un
    vertice a caso, in un verso a caso, con tempi a caso), poi si riempie e resta fermo. Con movimento ridotto e' fermo subito."""
    h = round(size * 248.78 / 243.7)
    return (f'<svg class="nn-tracciato" aria-hidden="true" width="{size}" height="{h}" viewBox="-8 -8 259.7 264.78">'
            f'<path class="tr-out" pathLength="100" fill="none" stroke="var(--accent)" stroke-width="14" stroke-linejoin="round" stroke-linecap="round" d="{_TRI_EST}"/>'
            f'<path class="tr-in" pathLength="100" fill="none" stroke="var(--accent)" stroke-width="14" stroke-linejoin="round" stroke-linecap="round" d="{_TRI_INT}"/>'
            f'<path class="tr-fill" fill="currentColor" fill-rule="evenodd" d="{DELTA}"/></svg>')


# Il tracciato casuale del logo: sceglie vertice di partenza, verso, tempi e modo di riempimento, una volta per pagina.
TRACCIATO_JS = """<style>
.nn-tracciato .tr-out,.nn-tracciato .tr-in{stroke-dasharray:100;stroke-dashoffset:0;opacity:0}
.nn-tracciato .tr-fill{opacity:1}
@media (prefers-reduced-motion:no-preference){
.nn-tracciato.vivo .tr-out,.nn-tracciato.vivo .tr-in{opacity:1;animation:tr-draw var(--d) var(--e) var(--w) both,tr-out .4s linear var(--f2) both}
.nn-tracciato.vivo .tr-fill{opacity:0;animation:tr-fill var(--fd) var(--e2) var(--f) both}
@keyframes tr-draw{from{stroke-dashoffset:var(--from)}to{stroke-dashoffset:0}}
@keyframes tr-out{from{opacity:1}to{opacity:0}}
@keyframes tr-fill{from{opacity:1;clip-path:var(--clip)}to{opacity:1;clip-path:inset(0 0 0 0)}}}
</style><script>
(function(){
  if(window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  var EST=['M121.85,0L0,248.78H243.7Z','M121.85,0L243.7,248.78H0Z','M0,248.78H243.7L121.85,0Z','M0,248.78L121.85,0L243.7,248.78Z','M243.7,248.78L121.85,0L0,248.78Z','M243.7,248.78H0L121.85,0Z'];
  var INT=['M121.85,37.81L186.73,234.1H25.71Z','M121.85,37.81L25.71,234.1H186.73Z','M25.71,234.1H186.73L121.85,37.81Z','M25.71,234.1L121.85,37.81L186.73,234.1Z','M186.73,234.1L121.85,37.81L25.71,234.1Z','M186.73,234.1H25.71L121.85,37.81Z'];
  var EASE=['ease-in-out','cubic-bezier(.65,0,.35,1)','cubic-bezier(.2,.8,.2,1)','linear','cubic-bezier(.5,0,.2,1)'];
  var CLIP=['inset(100% 0 0 0)','inset(0 0 100% 0)','inset(0 100% 0 0)','inset(0 0 0 100%)','inset(50% 50% 50% 50%)'];
  function r(a,b){return a+Math.random()*(b-a)} function pick(l){return l[Math.floor(Math.random()*l.length)]}
  document.querySelectorAll('.nn-tracciato').forEach(function(svg){
    var o=svg.querySelector('.tr-out'),i=svg.querySelector('.tr-in'),f=svg.querySelector('.tr-fill');
    o.setAttribute('d',pick(EST)); i.setAttribute('d',pick(INT));
    var dO=r(.7,1.5),dI=r(.5,1.2),mode=pick(['out','in','both']),wO=0,wI=0;
    if(mode==='out')wI=dO*r(.3,.8); else if(mode==='in')wO=dI*r(.3,.8); else wI=r(0,.25);
    var end=Math.max(wO+dO,wI+dI),fS=end-r(0,.25),fD=r(.35,.8),e=pick(EASE);
    function st(el,d,w,from){el.style.setProperty('--d',d+'s');el.style.setProperty('--w',w+'s');el.style.setProperty('--e',e);
      el.style.setProperty('--from',from);el.style.setProperty('--f2',(fS+fD*.5)+'s')}
    st(o,dO,wO,pick([100,-100])); st(i,dI,wI,pick([100,-100]));
    f.style.setProperty('--fd',fD+'s');f.style.setProperty('--f',fS+'s');f.style.setProperty('--e2',pick(EASE));f.style.setProperty('--clip',pick(CLIP));
    svg.classList.add('vivo');
  });
})();
</script>"""


def errore_html(testo: str, grezzo: bool = False) -> str:
    """Il riquadro di errore: il delta che scuote la testa (Scossa) e il messaggio."""
    return f'<div class="card error">{logo_anim("shake", 24)}<div>{testo if grezzo else escape(testo)}</div></div>'


def non_trovato_html(testo: str, link: str = "") -> str:
    """Pagina non trovata: il delta caduto sul fianco."""
    return f'<div class="vuoto">{logo_anim("fall", 56)}<p>{testo}{(" " + link) if link else ""}</p></div>'


def vuoto_html(testo: str) -> str:
    """Un elenco ancora vuoto: solo il contorno tratteggiato."""
    return f'<div class="vuoto">{logo_anim("dash", 40)}<p>{testo}</p></div>'


# Disattiva i pulsanti dopo l'invio (niente doppi clic) e mostra l'attesa. Prima copia in un campo nascosto il pulsante
# premuto: il browser non invia il valore di un pulsante disattivato.
ATTESA_JS = ("<script>document.querySelectorAll('form.pl').forEach(function(f){f.addEventListener('submit',function(e){"
             "var b=e.submitter;if(b&&b.name){var h=document.createElement('input');h.type='hidden';h.name=b.name;"
             "h.value=b.value;f.appendChild(h);}"
             "f.classList.add('lavora');setTimeout(function(){f.querySelectorAll('button').forEach(function(x){x.disabled=true})},0)})})</script>")


def segnaposto_html(righe: int = 2, size: int = 28) -> str:
    """Segnaposto (22): righe grigie che respirano mentre il contenuto arriva."""
    larghe = ("72%", "48%", "64%", "40%")
    return "".join(f'<div class="nn-skel" style="--nn-size:{size}px" aria-hidden="true">{_delta()}<span class="nn-skel__lines">'
                   f'<span class="nn-skel__bar" style="width:{larghe[i % 4]}"></span>'
                   f'<span class="nn-skel__bar" style="width:{larghe[(i + 1) % 4]}"></span></span></div>'
                   for i in range(righe))


def attesa_html(testo: str, kind: str = "trio", size: int = 18) -> str:
    """Il segnale d'attesa dentro un modulo (visibile dopo l'invio, con form.pl + ATTESA_JS)."""
    return f'<span class="attesa">{logo_anim(kind, size)}{escape(testo)}</span>'


def serve_static(handler, path: str) -> bool:
    """Serve i file condivisi (favicon, script dei riferimenti) e la scheda di una citazione.
    Vero se il percorso e stato gestito. Anorma e PPaToS lo chiamano per primi, quindi valgono anche li."""
    if path in ("/nn/favicon.js", "/nn/citazioni.js", "/nn/copia.js"):
        body = {"/nn/favicon.js": FAVICON_JS, "/nn/citazioni.js": CITAZIONI_JS, "/nn/copia.js": COPIA_JS}[path]
        handler.send_response(200)
        handler.send_header("Content-Type", "application/javascript; charset=utf-8")
        handler.send_header("Cache-Control", "max-age=86400" if path == "/nn/favicon.js" else "no-cache")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return True
    if path == "/nn/citazione":
        _serve_citazione(handler)
        return True
    return False


def citazione_json(con, q: dict) -> dict | None:
    """La scheda di una citazione (bolla, nota, articolo completo) dai parametri della richiesta."""
    def uno(k):
        v = q.get(k) or [""]
        return (v[0] if isinstance(v, list) else v)[:400]
    passi = q.get("passo") or []
    passi = [passi] if isinstance(passi, str) else passi
    return citazioni.scheda(con, cita=uno("cita"), uri=uno("uri"), eid=uno("eid"), lingua=uno("lingua"),
                            data=uno("data"), parte=uno("parte"), impronta=uno("impronta"),
                            passi=[p[:600] for p in passi[:6]])


def _serve_citazione(handler) -> None:
    q = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
    try:
        con = store.connect(cli.DB)
        try:
            d = citazione_json(con, q)
        finally:
            con.close()
        status, body = (200, d) if d else (404, {"errore": "non in archivio"})
    except Exception as e:  # la pagina usa il ripiego: link all'originale
        status, body = 500, {"errore": str(e)}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "private, max-age=300")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


# ---- flusso dei passi e narratore (pagina di avanzamento e risultato) ----


def _page(title: str, body: str, azione: dict | None = None) -> bytes:
    """azione: voce propria di Nuova-Norma nel menu del clic destro (es. le versioni dell'articolo)."""
    return f"""<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · Nuova-Norma</title><style>{CSS}{LOGO_CSS}{triade.tema_css("nuova-norma")}</style>{triade.favicon_init("nuova-norma")}</head>
<body><header><div class="in"><a href="/" class="marchio" style="display:inline-flex;align-items:center;gap:9px">{logo_tracciato(18)}Nuova-Norma</a>
<span class="muted small ver">archivio locale · versione {__version__}</span>
<nav style="margin-left:auto;display:flex;gap:18px"><a href="/" style="font-weight:400">Archivio</a>
<a href="/chiedi" style="font-weight:400">Chiedi</a>
<a href="http://127.0.0.1:8766/" style="font-weight:400">Anorma</a></nav></div></header>
<main>{body}</main>{TRACCIATO_JS}{citazioni_init()}{triade.copia_init("nuova-norma", azione=azione)}</body></html>""".encode("utf-8")


def _q(**params) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v})


def _act_label(row) -> str:
    sr = f"RS {row['sr_number']} · " if row["sr_number"] else ""
    return sr + (row["title"] or row["uri"])


REF_RE = re.compile(
    r"^\s*(?:RS|SR)?\s*(?P<sr>\d+(?:\.\d+)*)?\s*,?\s*"
    r"(?:art(?:icolo|\.)?\s*(?P<art>\d+\s*[a-z]{0,10}))?\s*\.?\s*$",
    re.IGNORECASE,
)


def parse_ref(text: str) -> tuple[str | None, str | None]:
    """'220 art. 958f' -> ('220', '958f'); '235.1' -> ('235.1', None); 'Art. 6' -> (None, '6')."""
    m = REF_RE.match(text)
    if not m:
        return None, None
    art = m.group("art")
    return m.group("sr"), (re.sub(r"\s+", "", art).lower() if art else None)


_art_key = store.art_key


def find_article(con, uri: str, lang: str, art: str) -> str | None:
    a = store.find_article(con, uri, lang, art)
    return a.eid if a else None


def home(con, message: str = "") -> bytes:
    acts = con.execute("""
        SELECT a.*, v.lang, COUNT(v.id) AS n, MAX(v.date_applicability) AS last
        FROM acts a JOIN versions v ON v.act_uri = a.uri
        GROUP BY a.uri, v.lang ORDER BY a.sr_number, v.lang""").fetchall()
    items = "".join(
        f"""<li><div class="row"><a href="/atto?{_q(uri=r['uri'], lingua=r['lang'])}">{escape(_act_label(r))}</a>
        <span class="muted small">{LANG_NAMES.get(r['lang'], r['lang'])} · {r['n']} versioni · ultima {r['last']}</span></div></li>"""
        for r in acts
    )
    langs = "".join(f'<option value="{k}">{v}</option>' for k, v in LANG_NAMES.items())
    return _page("Archivio", f"""
<h1>Archivio delle norme</h1>
<p class="muted">Leggi federali importate da Fedlex, con tutte le versioni e le loro differenze.</p>
{message}
<div class="card"><form method="post" action="/importa">
<input name="atto" placeholder="Legge o articolo, es. 220 art. 958f" required autofocus style="flex:1;min-width:260px">
<select name="lingua">{langs}</select><button>Apri</button></form>
<p class="muted small" style="margin:10px 0 0">Una legge si indica con il suo numero RS: 235.1 (protezione dei dati), 220 (Codice delle obbligazioni), 210 (Codice civile), 101 (Costituzione).
Aggiungi l'articolo per aprirlo direttamente: 235.1 art. 6. Se la legge non è ancora in archivio viene importata da Fedlex.</p></div>
<h2>In archivio</h2>
<div class="card">{f'<ul class="list">{items}</ul>' if items else vuoto_html("Ancora nessun atto. Importane uno qui sopra.")}</div>""")


def act_page(con, uri: str, lang: str) -> bytes:
    act = store.find_act(con, uri)
    if act is None:
        return _page("Non trovato", non_trovato_html("Atto non presente in archivio.", '<a href="/">Torna all\'archivio</a>'))
    dates = store.list_dates(con, uri, lang)
    if not dates:
        return _page(act["title"] or uri, f"""<h1>{escape(act['title'] or uri)}</h1>
<div class="card">Nessuna versione in {LANG_NAMES.get(lang, lang)} in archivio. Prova a importarla di nuovo dalla
<a href="/">pagina iniziale</a>.</div>""")
    latest = store.in_force_date(dates)
    articles = store.load_articles(con, uri, lang, latest)

    versions = []
    for i, d in enumerate(reversed(dates)):
        idx = len(dates) - 1 - i
        link = (f'<a class="small" href="/differenze?{_q(uri=uri, lingua=lang, da=dates[idx - 1], a=d)}">'
                f'cosa cambia rispetto al {dates[idx - 1]}</a>') if idx > 0 else '<span class="muted small">prima versione in archivio</span>'
        marca = logo_svg(13) if d == latest else logo_anim("outline", 13)
        versions.append(f'<li><div class="row"><span class="in-vigore">{marca}In vigore dal {d}</span>{link}</div></li>')

    toc, last_path = [], None
    for a in articles:
        p = " › ".join(a.path)
        if p != last_path:
            toc.append(f'<div class="path">{escape(p)}</div>' if p else "")
            last_path = p
        toc.append(f'<div><a href="/articolo?{_q(uri=uri, lingua=lang, eid=a.eid)}">{escape(a.num)}</a> '
                   f'<span class="muted">{escape(a.heading)}</span></div>')

    other = [r[0] for r in con.execute("SELECT DISTINCT lang FROM versions WHERE act_uri=? AND lang<>?", (uri, lang))]
    other_links = " ".join(f'<a class="small" href="/atto?{_q(uri=uri, lingua=l)}">{LANG_NAMES.get(l, l)}</a>' for l in other)

    return _page(act["title"] or uri, f"""
<p class="muted small">{f"RS {escape(act['sr_number'])} · " if act['sr_number'] else ""}{LANG_NAMES.get(lang, lang)} {other_links}</p>
<h1>{escape(act['title'] or uri)}</h1>
<p class="muted small"><a href="{escape(uri.replace('fedlex.data.admin.ch', 'www.fedlex.admin.ch'))}/{lang}">Testo ufficiale su Fedlex</a></p>
<form method="get" action="/vai" style="margin:20px 0 0"><input type="hidden" name="uri" value="{escape(uri)}">
<input type="hidden" name="lingua" value="{lang}"><input name="art" placeholder="Vai all'articolo, es. 6" required>
<button>Vai</button></form>
<h2>Versioni</h2><div class="card"><ul class="list">{''.join(versions)}</ul></div>
<h2>Articoli ({len(articles)}) nella versione del {latest}</h2><div class="card">{''.join(toc)}</div>""")


def diff_page(con, uri: str, lang: str, d_old: str, d_new: str) -> bytes:
    act = store.find_act(con, uri)
    changes = diff.compare(store.load_articles(con, uri, lang, d_old), store.load_articles(con, uri, lang, d_new))
    labels = {"modificato": ("mod", "Modificato"), "aggiunto": ("add", "Nuovo"), "abrogato": ("rep", "Abrogato")}
    cards = []
    for c in changes:
        cls, label = labels[c.kind]
        if c.kind == "modificato":
            body = diff.word_diff_html(c.old, c.new) if c.old != c.new else '<span class="muted">Cambia solo la rubrica.</span>'
        elif c.kind == "aggiunto":
            body = f"<ins>{escape(c.new)}</ins>"
        else:
            body = f"<del>{escape(c.old)}</del>" if c.old else '<span class="muted">Articolo tolto dal testo.</span>'
        cards.append(f"""<div class="card"><div class="row"><div><span class="tag {cls}">{label}</span>
<a href="/articolo?{_q(uri=uri, lingua=lang, eid=c.eid)}"><strong>{escape(c.num)}</strong></a> {escape(c.heading)}</div></div>
<p class="text" style="margin:10px 0 0">{body}</p></div>""")
    counts = {k: sum(1 for c in changes if c.kind == k) for k in labels}
    words = {"modificato": ("modificato", "modificati"), "aggiunto": ("nuovo", "nuovi"), "abrogato": ("abrogato", "abrogati")}
    summary = ", ".join(f"{n} {words[k][n != 1]}" for k, n in counts.items() if n)
    return _page("Differenze", f"""
<p class="small"><a href="/atto?{_q(uri=uri, lingua=lang)}">{escape(act['title'] or uri)}</a></p>
<h1>Dal {d_old} al {d_new}</h1>
<p class="muted">{len(changes)} {"articolo cambiato" if len(changes) == 1 else "articoli cambiati"}{': ' + summary if summary else ''}.</p>
<p class="legend"><del>parole tolte</del> &nbsp; <ins>parole aggiunte</ins></p>
{''.join(cards) or '<div class="card muted">Nessuna differenza nel testo degli articoli.</div>'}""")


def article_page(con, uri: str, lang: str, eid: str) -> bytes:
    act = store.find_act(con, uri)
    rows = con.execute("""
        SELECT v.date_applicability AS d, a.* FROM versions v
        LEFT JOIN articles a ON a.version_id = v.id AND a.eid = ?
        WHERE v.act_uri = ? AND v.lang = ? ORDER BY v.date_applicability""", (eid, uri, lang)).fetchall()
    present = [r for r in rows if r["eid"]]
    if not present:
        return _page("Non trovato", non_trovato_html("Articolo non trovato."))
    cur = present[-1]

    hist, prev_hash = [], None
    for r in rows:
        h = r["text_hash"]
        if h is None:
            state, changed = "non presente", prev_hash is not None
        elif prev_hash is None:
            state, changed = "compare nel testo", True
        elif h != prev_hash:
            state, changed = "modificato", True
        else:
            state, changed = "invariato", False
        prev_hash = h
        hist.append(f'<li class="{"changed" if changed else ""}"><strong>{r["d"]}</strong> '
                    f'<span class="muted">{state}</span></li>')

    notes = json.loads(cur["notes"] or "[]")
    notes_html = ("<h2>Note</h2><div class=\"card small muted\">" +
                  "".join(f"<div>{escape(n)}</div>" for n in notes) + "</div>") if notes else ""
    path = " › ".join(json.loads(cur["path"] or "[]"))
    # per la copia con la fonte: riferimento e pubblicazione ufficiale
    sr = act["sr_number"] if "sr_number" in act.keys() else ""
    fonte = f"{cur['num']} {act['title'] or ''}" + (f" (RS {sr})" if sr else "")
    ufficiale = uri.replace("fedlex.data.admin.ch", "www.fedlex.admin.ch") + f"/{lang}#{eid}"
    cambi = [i for i in range(1, len(rows)) if rows[i]["text_hash"] and rows[i - 1]["text_hash"]
             and rows[i]["text_hash"] != rows[i - 1]["text_hash"]]
    azione = ({"tipo": "versioni", "etichetta": "Confronta con la versione precedente",
               "url": "/differenze?" + _q(uri=uri, lingua=lang, da=rows[cambi[-1] - 1]["d"], a=rows[cambi[-1]]["d"])}
              if cambi else None)
    return _page(f"{cur['num']} {act['title']}", f"""
<p class="small"><a href="/atto?{_q(uri=uri, lingua=lang)}">{escape(act['title'] or uri)}</a></p>
<p class="muted small">{escape(path)}</p>
<h1>{escape(cur['num'])} {escape(cur['heading'] or '')}</h1>
<p class="muted small in-vigore">{logo_anim("flip", 16)}Versione in vigore dal {cur['d']}</p>
<div class="card" data-fonte="{escape(fonte)}" data-fonte-url="{escape(ufficiale)}"><p class="text" style="margin:0">{escape(cur['text'])}</p></div>
{notes_html}
<h2>Storia dell'articolo</h2><div class="card"><ul class="timeline">{''.join(hist)}</ul></div>""", azione=azione)


def _render_answer(con, text: str, lang: str, ext: dict | None = None) -> str:
    """Testo della risposta in HTML: ogni citazione diventa un link. Articoli RS: verificati sull'archivio.
    Sentenze, oggetti parlamentari, consultazioni, leggi cantonali: link alla fonte ufficiale letta in questa risposta."""
    ext = ext or {}
    out, pos = [], 0
    spans = [(c.span, "rs", c) for c in agent.find_citations(text)] + \
            [(c.span, "other", c) for c in agent.find_other_citations(text)]
    spans.sort(key=lambda t: t[0][0])
    for (a, b), kind, c in spans:
        if a < pos:
            continue
        out.append(escape(text[pos:a]))
        if kind == "other":
            label = c.label + (f", {c.date}" if c.date else "")
            url = ext.get(c.label) or ext.get(c.label.replace("DTF ", "TF "))
            if url:
                out.append(f'<a class="cite" href="{escape(url)}" target="_blank" rel="noopener">{escape(label)}</a>')
            else:
                out.append(f'<span class="cite tag">{escape(label)}</span>')
            pos = b
            continue
        act = store.find_act(con, c.sr)
        chips = []
        for art, para in c.articles:
            label = escape(f"RS {c.sr} art. {art}" + (f" {para}" if para else "") + (f", {c.date}" if c.date else ""))
            found, flang = None, lang
            if act:
                langs = [lang] + [l for (l,) in con.execute("SELECT DISTINCT lang FROM versions WHERE act_uri=?", (act["uri"],)) if l != lang]
                for l in langs:
                    found = store.find_article(con, act["uri"], l, art, c.date)
                    if found:
                        flang = l
                        break
            if found:
                dati = (f' data-nn-uri="{escape(act["uri"])}" data-nn-eid="{escape(found.eid)}" data-nn-lingua="{flang}"'
                        + (f' data-nn-data="{escape(c.date)}"' if c.date else "")
                        + (f' data-nn-parte="{escape(para)}"' if para else ""))
                chips.append(f'<a class="cite" href="/articolo?{_q(uri=act["uri"], lingua=flang, eid=found.eid)}"{dati}>{label}</a>')
            else:
                # citazione che non corrisponde a nessun articolo in archivio: la segnaliamo
                chips.append(f'<span class="cite tag rep" title="Non trovato in archivio">{label} (non verificato)</span>')
        out.append(" ".join(chips))
        pos = b
    out.append(escape(text[pos:]))
    html = "".join(out)
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    return re.sub(r"(?m)^(#{1,3})\s+(.+)$", r"<strong>\2</strong>", html)


def chiedi_page(con, question: str = "", answer: "agent.Answer | None" = None,
                history: list | None = None, error: str = "", lang: str = "it") -> bytes:
    history = history or []
    try:
        client = MODEL_FACTORY()
        status = ""
        provider_note = getattr(client, "label", "")
        if getattr(client, "european", True) is False:
            status = (f'<div class="card small">Fornitore AI: <strong>{escape(provider_note)}</strong>. '
                      "Le domande vengono elaborate negli Stati Uniti: non inserire dati personali di clienti. "
                      "Per tornare a Infomaniak imposta NN_PROVIDER=infomaniak nel file .env.</div>")
    except ai.AIConfigError as e:
        provider_note = ""
        status = errore_html(str(e))
    n_acts = con.execute("SELECT COUNT(DISTINCT act_uri) FROM versions").fetchone()[0]
    convo = []
    for i in range(0, len(history) - 1, 2):
        convo.append(f'<div class="card"><p class="q">{escape(history[i]["content"])}</p>'
                     f'<div class="answer">{_render_answer(con, history[i + 1]["content"], lang)}</div></div>')
    result = ""
    if answer is not None:
        kinds = {"tf": "Tribunale federale", "parlamento": "Parlamento", "consultazione": "Consultazione",
                 "cantone": "Diritto cantonale", "ru": "Raccolta ufficiale"}
        sources = "".join(
            (f'<li><a href="/articolo?{_q(uri=s.act_uri, lingua=s.lang, eid=s.eid)}">RS {escape(s.sr)} {escape(s.num)}</a> '
             f'<span class="muted">{escape(s.heading)} · versione del {s.date}</span></li>') if s.kind == "rs" else
            (f'<li><span class="tag">{kinds.get(s.kind, s.kind)}</span><a href="{escape(s.url)}" target="_blank" rel="noopener">'
             f'{escape(s.label)}</a> <span class="muted">{escape(s.heading)}</span></li>')
            for s in answer.sources)
        ext = {s.label: s.url for s in answer.sources if s.kind != "rs" and s.url}
        steps = "".join(f'<li>{escape(st["strumento"] or "")} <span class="muted">{escape(json.dumps(st["argomenti"], ensure_ascii=False))}</span></li>'
                        for st in answer.steps)
        result = f"""<div class="card"><p class="q">{escape(question)}</p>
<div class="answer">{_render_answer(con, answer.text, lang, ext)}</div>
{f'<h2 style="margin-top:20px">Fonti consultate</h2><ul class="list small">{sources}</ul>' if sources else ''}
{f'<details><summary>Ricerche eseguite ({len(answer.steps)})</summary><ul class="small">{steps}</ul></details>' if steps else ''}
</div>"""
        history = history + [{"role": "user", "content": question}, {"role": "assistant", "content": answer.text}]
    err = errore_html(error) if error else ""
    hidden = escape(json.dumps(history[-8:], ensure_ascii=False))
    langs = "".join(f'<option value="{k}"{" selected" if k == lang else ""}>{v}</option>' for k, v in LANG_NAMES.items())
    return _page("Chiedi", f"""
<h1>Chiedi all'archivio</h1>
<p class="muted">Ricerca in fonti ufficiali: diritto federale (Fedlex), consultazioni, Parlamento, Tribunale federale, Canton Ticino.
In archivio locale: {n_acts} {"legge" if n_acts == 1 else "leggi"}; le altre vengono importate quando servono.
{escape(provider_note) + "." if provider_note else ""}</p>
{status}{''.join(convo)}{result}{err}
<form class="pl" method="post" action="/chiedi" style="display:block">
<input type="hidden" name="storia" value="{hidden}">
<textarea name="domanda" placeholder="Es. Per quanto tempo devo conservare le fatture della mia ditta?" required autofocus>{escape(question) if answer is None else ""}</textarea>
<div style="display:flex;gap:8px;margin-top:8px;align-items:center"><select name="lingua">{langs}</select>
<button>{"Continua" if history else "Chiedi"}</button>{attesa_html("cerco nelle fonti ufficiali...", "scan", 22)}
{'<a class="small" href="/chiedi" style="margin-left:auto">Nuova conversazione</a>' if history else ''}</div>
</form>{ATTESA_JS}
<p class="muted small" style="margin-top:16px">Informazione generale, non consulenza legale. Le domande vengono inviate al fornitore AI indicato in alto.</p>""")


# ---------------------------------------------------------------------------
# Pipeline (passi 0-3): domanda, riformulazione da confermare, domande generate
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def log_message(self, fmt, *args):  # niente rumore in console
        pass

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if serve_static(self, url.path):
            return
        con = store.connect(cli.DB)
        try:
            lang = q.get("lingua", "it")
            if url.path == "/":
                self._send(home(con))
            elif url.path == "/atto":
                self._send(act_page(con, q["uri"], lang))
            elif url.path == "/differenze":
                self._send(diff_page(con, q["uri"], lang, q["da"], q["a"]))
            elif url.path == "/chiedi":
                self._send(chiedi_page(con, question=q.get("domanda", "")[:600]))   # «Cerca in Nuova-Norma» dal menu
            elif url.path == "/vai":
                eid = find_article(con, q["uri"], lang, _art_key(q.get("art", "")))
                if eid:
                    return self._redirect("/articolo?" + _q(uri=q["uri"], lingua=lang, eid=eid))
                self._send(_page("Non trovato", f'''<div class="card error">{logo_anim("shake", 24)}<div>Articolo {escape(q.get("art", ""))} non trovato
nella versione più recente. <a href="/atto?{_q(uri=q["uri"], lingua=lang)}">Torna all'indice</a></div>'''), 404)
            elif url.path == "/articolo":
                self._send(article_page(con, q["uri"], lang, q["eid"]))
            else:
                self._send(_page("Non trovato", non_trovato_html("Pagina non trovata.", '<a href="/">Torna all\'archivio</a>')), 404)
        except Exception as e:  # pagina d'errore leggibile invece di una connessione chiusa
            self._send(_page("Errore", errore_html(str(e))), 500)
        finally:
            con.close()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(length).decode()).items()}
        if self.path == "/chiedi":
            return self._chiedi(form)
        if self.path != "/importa":
            return self._send(_page("Non trovato", ""), 404)
        text, lang = form.get("atto", "").strip(), form.get("lingua", "it")
        if lang not in fedlex.LANGUAGES:
            lang = "it"
        sr, art = parse_ref(text)
        con = store.connect(cli.DB)
        log: list[str] = []
        try:
            if sr is None and art is None and not text.startswith("http"):
                return self._send(home(con, _notice(
                    f"Non riconosco «{escape(text)}». Scrivi il numero RS della legge, ad esempio 220, "
                    "oppure legge e articolo, ad esempio 220 art. 958f.")))
            if sr is None and art:
                return self._send(home(con, self._article_everywhere(con, art)))

            ref = text if text.startswith("http") else sr
            act = store.find_act(con, ref)
            if act and art and store.list_dates(con, act["uri"], lang):
                uri = act["uri"]  # gia in archivio: nessuna chiamata a Fedlex
            else:
                uri = cli.importa(con, ref, lang, log=log.append)
            if art:
                eid = find_article(con, uri, lang, art)
                if eid:
                    return self._redirect("/articolo?" + _q(uri=uri, lingua=lang, eid=eid))
                return self._send(home(con, _notice(
                    f"La legge è in archivio, ma l'articolo {escape(art)} non c'è nella versione più recente. "
                    f'<a href="/atto?{_q(uri=uri, lingua=lang)}">Apri l\'indice</a>')))
            self._redirect("/atto?" + _q(uri=uri, lingua=lang))
        except Exception as e:
            msg = (f'<div class="card error">{logo_anim("shake", 24)}<div><strong>Importazione non riuscita.</strong> {escape(str(e))}'
                   f'<pre class="log">{escape(chr(10).join(log))}</pre></div>')
            self._send(home(con, msg))
        finally:
            con.close()

    def _chiedi(self, form: dict) -> None:
        question = form.get("domanda", "").strip()
        lang = form.get("lingua", "it") if form.get("lingua") in fedlex.LANGUAGES else "it"
        try:
            history = json.loads(form.get("storia") or "[]")
            history = [h for h in history if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str)]
        except (json.JSONDecodeError, AttributeError):
            history = []
        con = store.connect(cli.DB)
        try:
            model = MODEL_FACTORY()
            answer = agent.ask(model, con, question, lang=lang, history=history)
            self._send(chiedi_page(con, question, answer, history, lang=lang))
        except Exception as e:
            self._send(chiedi_page(con, history=history, error=str(e), lang=lang))
        finally:
            con.close()

    def _article_everywhere(self, con, art: str) -> str:
        """Articolo senza legge: lo cerca in tutti gli atti gia in archivio."""
        hits = []
        for row in con.execute("SELECT DISTINCT a.uri, a.sr_number, a.title, v.lang FROM acts a "
                               "JOIN versions v ON v.act_uri = a.uri"):
            eid = find_article(con, row["uri"], row["lang"], art)
            if eid:
                hits.append(f'<li><a href="/articolo?{_q(uri=row["uri"], lingua=row["lang"], eid=eid)}">'
                            f'Art. {escape(art)} · {escape(_act_label(row))}</a> '
                            f'<span class="muted small">{LANG_NAMES.get(row["lang"], row["lang"])}</span></li>')
        intro = (f"Per aprire l'articolo {escape(art)} serve anche la legge, ad esempio "
                 f"<strong>220 art. {escape(art)}</strong> per il Codice delle obbligazioni.")
        if hits:
            return _notice(intro + " Nell'archivio c'è in:" + f'<ul class="list">{"".join(hits)}</ul>')
        return _notice(intro)


def _notice(html: str) -> str:
    return f'<div class="card">{html}</div>'


class Server(ThreadingHTTPServer):
    # Su Windows SO_REUSEADDR permette a due processi di occupare la stessa porta:
    # risponderebbe il sito vecchio. Senza, un secondo avvio fallisce con un errore chiaro.
    allow_reuse_address = os.name != "nt"
    daemon_threads = True


def serve(port: int = 8765, open_browser: bool = True) -> None:
    try:
        server = Server(("127.0.0.1", port), Handler)
    except OSError:
        raise SystemExit(
            f"La porta {port} e gia occupata: probabilmente Nuova-Norma e gia aperta in un'altra finestra.\n"
            "Chiudi quella finestra (o premi Ctrl+C li) e riprova."
        )
    url = f"http://127.0.0.1:{port}/"
    print(f"Nuova-Norma {__version__} e aperta su {url}  (Ctrl+C per chiudere)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nChiuso.")
    finally:
        server.server_close()
