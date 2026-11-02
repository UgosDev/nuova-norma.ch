"""Riga di comando di Nuova-Norma.

Esempi:
  py -m nn importa 235.1            # scarica tutte le versioni XML della nLPD in italiano
  py -m nn importa 235.1 --lingua de
  py -m nn versioni 235.1
  py -m nn differenze 235.1         # confronta le ultime due versioni
  py -m nn differenze 235.1 --da 2023-09-01 --a 2024-01-01
  py -m nn articolo 235.1 art_6
"""

from __future__ import annotations

import argparse
import json
import re
import os
import sys
from pathlib import Path

from . import akn, diff, fedlex, store

DATA = Path(__file__).resolve().parent.parent / "data"
# NN_DB / NN_RAW: un archivio diverso da quello predefinito (prove, copie di lavoro)
DB = Path(os.environ["NN_DB"]) if os.environ.get("NN_DB") else DATA / "nuova-norma.sqlite"
RAW = Path(os.environ["NN_RAW"]) if os.environ.get("NN_RAW") else DATA / "raw"
_open = []


def _db():
    con = store.connect(DB)
    _open.append(con)
    return con


def _act(con, ref: str):
    row = store.find_act(con, ref)
    if row is None:
        sys.exit(f"Atto {ref} non ancora importato. Esegui prima: py -m nn importa {ref}")
    return row


def importa(con, ref: str, lang: str, log=print, rebuild: bool = True) -> str:
    """Importa da Fedlex tutte le versioni XML di un atto. Restituisce l'URI dell'atto."""
    if ref.startswith("http"):
        uri, sr, title = ref, "", ""
    else:
        info = fedlex.resolve_sr(ref)
        uri, sr, title = info["ca"], ref, info["title"]
        if len(info["candidates"]) > 1:
            log(f"Il numero RS {ref} corrisponde a {len(info['candidates'])} atti; scelto quello in vigore piu recente:")
            for c in info["candidates"]:
                mark = "->" if c["ca"] == uri else "  "
                log(f"  {mark} {c.get('entry', '')[:10] or '?':10}  {c['ca']}  {c.get('title', '')[:70]}")
    log(f"Atto: {title or uri}")
    log(f"URI:  {uri}")
    in_force = True
    if not ref.startswith("http"):
        import datetime
        end = info.get("end", "")[:10]
        in_force = (not info.get("status", "").endswith("/enforcement-status/3")
                    and not (end and end <= datetime.date.today().isoformat()))
    store.upsert_act(con, uri, sr, title, in_force=in_force)
    if not in_force:
        log("Attenzione: questo atto risulta abrogato. Resta consultabile come storia, ma non entra nella ricerca.")
    con.commit()

    all_files = fedlex.list_versions(uri, lang)
    versions = fedlex.xml_versions(all_files)
    if not versions:
        formats = sorted({f.fmt.rsplit('/', 1)[-1] for f in all_files})
        raise LookupError(f"Nessun file XML trovato. Formati disponibili: {', '.join(formats) or 'nessuno'}")
    log(f"Versioni XML disponibili ({lang}): {len(versions)}")

    new = 0
    for v in versions:
        if store.has_version(con, uri, lang, v.date_applicability):
            continue
        path, sha = fedlex.download(v.url, RAW)
        act = akn.parse(path)
        store.save_version(con, uri, lang, v.date_applicability, v.url, sha, act)
        new += 1
        log(f"  {v.date_applicability}  {len(act.articles):4d} articoli  {sha[:12]}")
    store.mark_checked(con, uri)
    con.commit()
    log(f"Fatto: {new} nuove versioni, {len(versions) - new} gia presenti.")
    if new and rebuild:
        store.rebuild_search(con, uri)
    return uri


def cmd_importa(args) -> None:
    try:
        importa(_db(), args.atto, args.lingua)
    except LookupError as e:
        sys.exit(str(e))


def _importa_elenco(con, elenco: list[tuple[str, str]], lang: str) -> None:
    """Importa piu atti di seguito; un atto che non si trova o non ha XML non ferma gli altri."""
    import time
    ok, falliti = 0, []
    t0 = time.monotonic()
    for n, (rs, nome) in enumerate(elenco, 1):
        print(f"\n[{n}/{len(elenco)}] RS {rs} {nome}")
        try:
            importa(con, rs, lang, log=lambda m: print("  " + m), rebuild=False)
            ok += 1
        except Exception as e:  # rete o atto non trovato: si annota e si continua
            falliti.append((rs, nome, f"{type(e).__name__}: {str(e)[:160]}"))
            print(f"  NON IMPORTATO: {type(e).__name__}: {str(e)[:160]}")
    n_art = store.rebuild_search(con)
    print(f"\nImportati {ok} atti su {len(elenco)} in {time.monotonic() - t0:.0f} s. Indice di ricerca: {n_art} articoli.")
    if falliti:
        print("Non importati (da controllare):")
        for rs, nome, err in falliti:
            print(f"  RS {rs:<14} {nome:<14} {err}")


def cmd_importa_pacchetto(args) -> None:
    from .pacchetti import PACCHETTI
    if args.nome not in PACCHETTI:
        sys.exit("Pacchetti disponibili:\n" + "\n".join(f"  {k:<22} {v['descrizione']}" for k, v in PACCHETTI.items()))
    pk = PACCHETTI[args.nome]
    print(f"Pacchetto {args.nome}: {pk['descrizione']} ({len(pk['atti'])} atti)")
    _importa_elenco(_db(), pk["atti"], args.lingua)


def cmd_importa_catalogo(args) -> None:
    """Tutta la Raccolta sistematica in vigore (o un settore): riprende da dove si era fermato."""
    con = _db()
    cat = fedlex.catalog(args.lingua, args.prefisso or "", include_treaties=args.trattati)
    gia = {r[0] for r in con.execute("SELECT uri FROM acts")}
    da_fare = [c for c in cat if args.aggiorna or c["uri"] not in gia]
    print(f"Atti in vigore nel catalogo{' (RS ' + args.prefisso + '...)' if args.prefisso else ''}: {len(cat)}; "
          f"gia in archivio: {len(cat) - len(da_fare)}; da importare: {len(da_fare)}")
    if args.limite:
        da_fare = da_fare[:args.limite]
    if args.solo_elenco:
        for c in da_fare:
            print(f"  RS {c['rs']:<16} {c['titolo'][:90]}")
        return
    _importa_elenco(con, [(c["rs"], "") for c in da_fare], args.lingua)


def _raw_dir():
    return RAW


def cmd_aggiorna_raccolte(args) -> None:
    from . import documenti, raccolte
    con = _db()
    documenti.ensure(con)
    nomi = args.fonti or list(raccolte.LETTORI)
    ignote = [n for n in nomi if n not in raccolte.LETTORI]
    if ignote:
        sys.exit(f"Fonti sconosciute: {', '.join(ignote)}. Disponibili: {', '.join(raccolte.LETTORI)}")
    esiti = []
    for nome in nomi:
        lettore = raccolte.LETTORI[nome](con)
        print(f"\n== {nome}: {lettore.descrizione}")
        try:
            es = raccolte.aggiorna(con, lettore, _raw_dir(), limite=args.limite,
                                   rileggi_dopo_giorni=0 if args.forza else args.giorni, solo=args.solo or ())
        except Exception as e:
            print(f"  FONTE NON LETTA: {type(e).__name__}: {str(e)[:200]}")
            continue
        esiti.append(es)
        print("  " + es.riga())
    print("\nRiepilogo:")
    for es in esiti:
        print("  " + es.riga())


def cmd_esporta_vettori(args) -> None:
    from . import vettori
    con = _db()
    dest = Path(args.file) if args.file else DB.parent / "vettori" / "da-calcolare.jsonl"
    n = vettori.esporta(con, dest, lang=args.lingua)
    print(f"{n} articoli da calcolare in {dest}")
    if n:
        print("Carica il file nel notebook colab/vettori.ipynb, poi: py -m nn importa-vettori vettori.npz")


def cmd_calcola_vettori(args) -> None:
    from . import vettori
    con = _db()
    if args.da_capo:
        vettori.azzera(con)
    r = vettori.calcola(con, batch=args.batch, lang=args.lingua)
    print(f"Calcolati {r['importati']} vettori. Totale in archivio: {r['totale']}.")


def cmd_copia_sicurezza(args) -> None:
    """Copia l'archivio (in modo coerente anche con il sito aperto), i file originali e i vettori in una cartella,
    per esempio su un disco esterno. I file gia copiati e uguali non si ricopiano."""
    import shutil
    import sqlite3
    import time
    dest = Path(args.cartella)
    dest.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    con = _db()
    copia = dest / DB.name
    tmp = copia.with_suffix(".tmp")
    out = sqlite3.connect(tmp)
    con.backup(out)   # copia coerente: SQLite la fa a blocchi, anche mentre altri leggono o scrivono
    out.close()
    tmp.replace(copia)
    print(f"Archivio: {copia} ({copia.stat().st_size // 1_000_000} MB)")
    for nome in ("raw", "vettori"):
        src = DB.parent / nome
        if not src.exists():
            continue
        nuovi = 0
        for f in src.rglob("*"):
            if not f.is_file():
                continue
            g = dest / nome / f.relative_to(src)
            if g.exists() and g.stat().st_size == f.stat().st_size and g.stat().st_mtime >= f.stat().st_mtime:
                continue
            g.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, g)
            nuovi += 1
        print(f"{nome}: {nuovi} file copiati o aggiornati")
    print(f"Fatto in {time.time() - t0:.0f} s.")


def cmd_verifica_vettori(args) -> None:
    """Mostra da dove vengono i vettori e, per Infomaniak, quali modelli di embedding offre il tuo prodotto."""
    import time
    from . import vettori
    print(f"Fonte dei vettori: {vettori.fonte()}   modello: {vettori.modello_attivo()}")
    if vettori.fonte() == "infomaniak" or args.infomaniak:
        from . import embedding_infomaniak as emb
        try:
            elenco = emb.modelli()
        except Exception as e:
            print(f"Elenco dei modelli non disponibile: {type(e).__name__}: {str(e)[:200]}")
            print("Controlla INFOMANIAK_API_TOKEN (token con accesso ad AI Tools) e INFOMANIAK_PRODUCT_ID nel .env.")
            return
        emb_modelli = [m for m in elenco if "embed" in str(m["tipo"]).lower()]
        print("Modelli di embedding su Infomaniak:" if emb_modelli else "Nessun modello di embedding nell'elenco.")
        for m in emb_modelli:
            print(f"  {m['nome']}")
        nome = args.modello or vettori.modello_attivo()
        if vettori.fonte() != "infomaniak" and not args.modello:
            nome = vettori.PREDEFINITI["infomaniak"]
        try:
            enc = emb.Infomaniak(nome)
            t0 = time.time()
            v = enc.encode(["Il datore di lavoro puo disdire durante la malattia?"], domanda=True)
            print(f"Prova con {nome}: dimensione {v.shape[1]}, {(time.time() - t0) * 1000:.0f} ms")
        except Exception as e:
            print(f"Prova con {nome} non riuscita: {str(e)[:300]}")
            print("Diagnosi:")
            for riga in emb.diagnosi():
                print("  " + riga)
    else:
        enc = vettori.codificatore()
        print("Modello locale: " + ("pronto, dispositivo " + vettori.dispositivo() if enc is not None else "non disponibile"))


def cmd_ricostruisci_indice(args) -> None:
    import time
    con = _db()
    t0 = time.time()
    n = store.rebuild_search(con)
    print(f"Indice di ricerca: {n} articoli in {time.time() - t0:.0f} s.")


def cmd_candidati(args) -> None:
    import time
    from . import preparata, vettori
    con = _db()
    t0 = time.time()
    pronti = vettori.scalda(con)
    print(f"Vettori: {'si' if pronti else 'no, solo testo'} (avvio {time.time() - t0:.1f} s)")
    for domanda in args.domande:
        t0 = time.time()
        righe = preparata.candidati(con, domanda, lang=args.lingua, k=args.quanti)
        print(f"\n{domanda}  ({(time.time() - t0) * 1000:.0f} ms)")
        for r in righe:
            print(f"  RS {r['rs']:<10} art. {r['articolo']:<8} {'+'.join(r['da']):<14} {(r['rubrica'] or '')[:60]}")


def cmd_importa_vettori(args) -> None:
    from . import vettori
    con = _db()
    r = vettori.importa(con, Path(args.file))
    print(f"Importati {r['importati']} vettori, scartati {r['scartati']} (testo cambiato o gia presenti). "
          f"Totale in archivio: {r['totale']}.")
    print("Ricerca per vettori: " + ("pronta" if vettori.codificatore() is not None else
          "manca il modello in locale per le domande (py -m pip install sentence-transformers); "
          "intanto resta la ricerca testuale"))


def cmd_stato_raccolte(args) -> None:
    from . import documenti, raccolte, sources
    con = _db()
    documenti.ensure(con)
    conti = {r["source"]: r for r in documenti.stats(con)}
    print(f"{'fonte':<18} {'livello':<14} {'documenti':>9} {'versioni':>8} {'spariti':>7}  ultimo controllo")
    for nome in raccolte.LETTORI:
        f = sources.SOURCES.get(nome)
        c = conti.get(nome)
        print(f"{nome:<18} {(f.livello_effettivo if f else ''):<14} {(c['documenti'] if c else 0):>9} "
              f"{(c['versioni'] if c else 0):>8} {(c['non_piu_pubblicati'] if c else 0):>7}  {(c['ultimo_controllo'] if c else 'mai')}")


def cmd_verifica_raccolte(args) -> None:
    """Prova ogni lettore senza toccare l'archivio: quanti documenti elenca e se il primo si legge."""
    import sqlite3 as _sq
    import tempfile
    from . import documenti, raccolte, sources
    con = _db()
    nomi = args.fonti or list(raccolte.LETTORI)
    for nome in nomi:
        lettore = raccolte.LETTORI[nome](con)
        try:
            items = lettore.elenca()
        except Exception as e:
            print(f"ERRORE  {nome:<16} elenco non letto: {type(e).__name__}: {str(e)[:200]}")
            continue
        if not items:
            print(f"VUOTO   {nome:<16} nessun documento riconosciuto: il sito potrebbe essere cambiato")
            continue
        it = items[0]
        try:
            raw, ctype = lettore.scarica(it)
            testo = lettore.testo(raw, ctype, it)
            if testo is None:
                testo, _ = documenti.extract(raw, ctype)
            data = it.valid_from or documenti.declared_date(testo)
            print(f"OK      {nome:<16} {len(items)} documenti; primo: {it.key} «{it.title[:50]}» "
                  f"{len(testo)} caratteri, data {data or 'non trovata'}; inizio: {testo[:90]!r}")
        except Exception as e:
            print(f"PARZIALE {nome:<15} {len(items)} documenti elencati, ma il primo ({it.key}) non si legge: "
                  f"{type(e).__name__}: {str(e)[:160]}")
        if not sources.robots_ok(it.url):
            print(f"        {nome}: il robots.txt del sito esclude questi documenti; aggiorna-raccolte li saltera")
    if not args.fonti:
        print("\nFonti studiate ma non ancora collegate (robots.txt):")
        for nome, url in raccolte.DA_VALUTARE.items():
            st = sources.robots_stato(url)
            print(f"  {'permesso ' if st else 'ESCLUSO  ' if st is False else 'non letto'} {nome}")


def cmd_rielabora(args) -> None:
    """Rilegge i file originali gia scaricati (data/raw) con il parser attuale. Nessun accesso a Fedlex."""
    con = _db()
    rows = con.execute("SELECT id, act_uri, lang, date_applicability, sha256 FROM versions ORDER BY act_uri, lang, date_applicability").fetchall()
    done = missing = 0
    for r in rows:
        path = RAW / f"{r['sha256']}.xml"
        if not path.exists():
            missing += 1
            print(f"  manca il file originale per {r['act_uri']} {r['lang']} {r['date_applicability']}")
            continue
        store.replace_articles(con, r["id"], akn.parse(path))
        done += 1
    con.commit()
    n = store.rebuild_search(con)
    print(f"Rielaborate {done} versioni ({missing} senza file originale). Indice di ricerca: {n} articoli.")


def cmd_verifica_fonti(args) -> None:
    """Una chiamata leggera per ogni fonte ufficiale: dice cosa risponde davvero. Nessuna chiave necessaria."""
    from . import cantoni, giurisprudenza, parlamento, sources

    def run(name, fn):
        import time
        t0 = time.monotonic()
        try:
            out = fn()
            print(f"OK      {name}  ({time.monotonic() - t0:.1f} s)  {out}")
        except Exception as e:
            print(f"ERRORE  {name}  {type(e).__name__}: {str(e)[:200]}")

    print("Domini ammessi:", ", ".join(sorted(sources.ALLOWED_HOSTS)))
    print("Certificati TLS:", "di sistema (truststore)" if "truststore" in __import__("sys").modules
          else "certifi" if sources._SSL else "lista di Python (se una fonte da errore di certificato: py -m pip install truststore)", "\n")
    run("Fedlex: ricerca titoli", lambda: f"{len(r := fedlex.search_titles('protezione dei dati'))} risultati; primo: {r[0]['rs'] if r else '-'} {r[0]['titolo'][:50] if r else ''}")
    run("Fedlex: entrate in vigore future", lambda: f"{len(r := fedlex.upcoming_entries(180))} atti; primo: {r[0]['entrata_in_vigore'] if r else '-'} {r[0]['titolo'][:50] if r else ''}")
    run("Fedlex: pubblicazioni RU/FF 30 gg", lambda: f"{len(r := fedlex.recent_publications(30))} pubblicazioni; prima: {r[0]['raccolta'] if r else '-'} {r[0]['pubblicato'] if r else ''} {r[0]['titolo'][:40] if r else ''}")
    run("Fedlex: consultazioni aperte", lambda: f"{len(r := fedlex.consultations())} aperte; prima: {r[0]['termine'] if r else '-'} {r[0]['titolo'][:50] if r else ''}")
    run("Parlamento: oggetti", lambda: f"{len(r := parlamento.search_business('protezione dei dati'))} oggetti; primo: {r[0]['numero'] if r else '-'} {r[0]['titolo'][:50] if r else ''}")
    run("Parlamento: votazioni", lambda: f"{len(r := parlamento.votes('dati'))} votazioni; prima: {r[0]['data'] if r else '-'} {(r[0]['oggetto'] or '')[:50] if r else ''}")
    run("Tribunale federale: tutte le sentenze", lambda: f"{len(r := giurisprudenza.search('protezione dei dati', limit=5))} riconosciute; prima: {r[0]['numero'] if r else '-'} {r[0]['data'] if r else ''}")
    def tf_text():
        r = giurisprudenza.search("protezione dei dati", limit=3)
        d = giurisprudenza.decision_text(r[0]["docid"])
        return f"{r[0]['numero']}: {len(d['testo'])} caratteri{' (troncato)' if d['troncato'] else ''}; inizio: {d['testo'][:110]!r}"
    run("Tribunale federale: testo di una sentenza", tf_text)
    run("Tribunale federale: DTF", lambda: f"{len(r := giurisprudenza.search('protezione dei dati', collection='dtf', limit=5))} riconosciute; prima: {r[0]['numero'] if r else '-'}")
    def parl_detail():
        keys = ("testo", "testo_mozione", "risposta_consiglio_federale", "situazione_iniziale", "descrizione", "procedura")
        for n, b in enumerate(parlamento.search_business("protezione dei dati", limit=8)[:5], 1):
            d = parlamento.business_detail(b["id"])
            campi = [k for k in keys if d.get(k)]
            if campi:
                return f"{d['numero']} ({n}o provato): testi letti: {', '.join(campi)}"
        return "nessun testo nei primi 5 oggetti: i nomi dei campi vanno rivisti"
    run("Parlamento: dettaglio di un oggetto", parl_detail)
    from . import opencaselaw

    def ocl():
        r = opencaselaw.cerca("disdetta locazione", cantone="TI", limite=3)
        if not r["risultati"]:
            return "nessun risultato per una ricerca di prova"
        d = opencaselaw.sentenza(r["risultati"][0]["id"])
        campi = ", ".join(sorted(k for k in d["grezzo"] if isinstance(d["grezzo"], dict)))[:200]
        return (f"{r['totale']} sentenze; prima: {d['id']} {d['data']}, testo {len(d['testo'])} caratteri"
                + ("" if d["testo"] else f"  ATTENZIONE testo vuoto, campi: {campi}"))
    run("OpenCaseLaw: sentenze ticinesi", ocl)
    con = _db()
    n = cantoni.count(con)
    print(f"{'OK     ' if n else 'VUOTO  '} Ticino: indice locale  {n} atti" + ("" if n else "  -> esegui: py -m nn indicizza-ticino"))
    if n:
        run("Ticino: testo di un atto", lambda: f"{len((t := cantoni.text(con, cantoni.search(con, 'pubblicazioni ufficiali')[0]['url']))['testo'])} caratteri; inizio: {t['testo'][:140]!r}")
    run("Ticino: pagina iniziale RL", lambda: f"{len(sources.fetch_text(cantoni.TICINO_HOME))} caratteri letti")


def cmd_indicizza_ticino(args) -> None:
    from . import cantoni
    con = _db()
    print("Esploro la Raccolta delle leggi del Canton Ticino (puo richiedere qualche minuto)...")
    res = cantoni.discover(con, max_pages=args.pagine, log=print)
    print(f"\nPagine lette: {res['pagine_lette']}  Atti indicizzati: {res['atti_trovati']}")
    print("Schemi di URL incontrati (per capire la struttura del sito):")
    for shape, n in res["schemi_url"].items():
        print(f"  {n:4d}  {shape}")
    if res["atti_trovati"] == 0:
        print("Nessun atto riconosciuto: incolla questo elenco di schemi, serve per adattare il lettore al sito.")


def cmd_verifica_ticino(args) -> None:
    from . import cantoni
    con = _db()
    print("Controllo la completezza dell'indice ticinese sui numeri interni mancanti...")
    res = cantoni.check_gaps(con, sample=args.campione, log=print)
    if "errore" in res:
        sys.exit(res["errore"])
    print(f"\nIn indice: {res['in_indice']}  Numero massimo: {res['massimo_id']}  Numeri mancanti: {res['mancanti']}")
    print("Esito:", res["riepilogo"])
    if res.get("in_arrivo"):
        print("\nAtti nuovi non ancora in vigore (non fanno parte degli atti in vigore):")
        for u in res["in_arrivo"]:
            print(f"  RL {u['numero']}  in vigore dal {u['dal']}  (id interno {u['id']})")
    print()
    if not res["controllo_affidabile"]:
        print("Il controllo non e affidabile: l'atto noto o la pagina di controllo non si distinguono. Incolla questo output.")
    elif res["esistenti"]:
        print(f"L'indice e INCOMPLETO: {len(res['esistenti'])} numeri mancanti sono atti veri (id {res['esistenti']}).")
    elif res["dubbi"]:
        print(f"{len(res['dubbi'])} numeri non si lasciano classificare:")
        for d in res["dubbi"]:
            print(f"  id {d['id']}: {d['inizio']}\n       {cantoni.BASE_ACT}{d['id']}")
        print("Incolla questo output: finche non sono chiariti, l'indice non e dimostrato completo.")
    else:
        verb = "completo" if res["mancanti"] <= args.campione else "completo sul campione"
        print(f"Nessun atto in vigore tra i numeri mancanti controllati: l'indice risulta {verb}.")


def cmd_ticino_pagina(args) -> None:
    from . import cantoni
    for n in args.id:
        print(f"===== id {n}  {cantoni.BASE_ACT}{n}")
        print(cantoni.page_text(n))
        print()


def _citation_check(answer) -> dict:
    """Controlla le citazioni: ogni articolo citato deve essere stato LETTO con leggi_articolo in questa ricerca
    (altrimenti il modello cita a memoria); ogni altra citazione deve corrispondere a una fonte consultata."""
    from . import agent
    read = {(s.sr, store.art_key(s.num)) for s in answer.sources if s.kind == "rs"}
    read |= {tuple(x[3:].split(" art. ", 1)) for x in getattr(answer, "absent", [])}  # cercati e inesistenti
    labels = {s.label for s in answer.sources if s.kind != "rs"}
    ok, bad = 0, []
    for c in agent.find_citations(answer.text):
        for art, _ in c.articles:
            if (c.sr, art) in read:
                ok += 1
            else:
                bad.append(f"RS {c.sr} art. {art}")
    for c in agent.find_other_citations(answer.text):
        if c.label in labels or c.label.replace("DTF ", "TF ") in labels:
            ok += 1
        else:
            bad.append(c.label)
    return {"lette": ok, "non_lette": len(bad), "elenco": bad}


def cmd_valuta(args) -> None:
    """Esegue un elenco di domande e produce un rapporto di confronto in data/valutazioni/."""
    from . import agent, ai
    import datetime
    import time
    path = Path(args.file) if args.file else DATA.parent / "domande-prova.txt"
    if not path.exists():
        sys.exit(f"File delle domande non trovato: {path}")
    questions = [l.strip() for l in path.read_text("utf-8-sig").splitlines() if l.strip() and not l.lstrip().startswith("#")]
    try:
        model = ai.make_client()
    except ai.AIConfigError as e:
        sys.exit(str(e))
    con = _db()
    print(f"[{model.label} · {model.model}]  {len(questions)} domande da {path.name}\n", file=sys.stderr)
    rows = []
    for i, q in enumerate(questions, 1):
        t0 = time.monotonic()
        ans, err = None, ""
        try:
            ans = agent.ask(model, con, q, lang=args.lingua)
        except (ai.AIConfigError, RuntimeError, OSError) as e:
            err = str(e)
        dt = time.monotonic() - t0
        chk = _citation_check(ans) if ans else {"lette": 0, "non_lette": 0, "elenco": []}
        tools = [st["strumento"] for st in ans.steps] if ans else []
        rows.append({"q": q, "ans": ans, "err": err, "dt": dt, "chk": chk, "tools": tools})
        flag = "ERRORE" if err else (f"{chk['non_lette']} citazioni NON lette" if chk["non_lette"] else "citazioni ok")
        print(f"[{i:2d}/{len(questions)}] {dt:5.1f} s  {len(tools):2d} strumenti  {chk['lette']} lette  {flag}  {q[:60]}", file=sys.stderr, flush=True)

    out_dir = DATA / "valutazioni"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    out = out_dir / f"{stamp}.md"
    total_lette = sum(r["chk"]["lette"] for r in rows)
    total_non = sum(r["chk"]["non_lette"] for r in rows)
    lines = [f"# Banco di prova {stamp}", "", f"Modello: {model.model} ({model.label}). Domande: {len(questions)}. "
             f"Tempo medio: {sum(r['dt'] for r in rows) / max(len(rows), 1):.1f} s.", "",
             f"Citazioni di articoli letti in questa ricerca: **{total_lette}**. Citazioni NON lette (fatte a memoria): **{total_non}**.", "",
             "| # | Domanda | Tempo | Strumenti | Citazioni lette | Non lette |", "| --- | --- | --- | --- | --- | --- |"]
    for i, r in enumerate(rows, 1):
        lines.append(f"| {i} | {r['q']} | {r['dt']:.0f} s | {len(r['tools'])} | {r['chk']['lette']} | {r['chk']['non_lette'] or '-'} |")
    for i, r in enumerate(rows, 1):
        lines += ["", f"## {i}. {r['q']}", ""]
        if r["err"]:
            lines.append(f"ERRORE: {r['err']}")
            continue
        lines += [r["ans"].text, ""]
        if r["chk"]["elenco"]:
            lines += ["**Citazioni non verificate:** " + ", ".join(r["chk"]["elenco"]), ""]
        lines.append("**Fonti consultate:** " + (", ".join(
            (f"RS {s.sr} {s.num}" if s.kind == "rs" else s.label) for s in r["ans"].sources) or "nessuna"))
        lines.append("**Strumenti:** " + (", ".join(r["tools"]) or "nessuno"))
        lines += ["", "**Ricerche eseguite:**"] + [f"- {st['strumento']} {json.dumps(st['argomenti'], ensure_ascii=False)}" for st in r["ans"].steps]
        lines += ["", "### Risposta dello strumento di confronto (incolla qui)", "", "", "### Giudizio (corretta / parziale / sbagliata, citazioni giuste?)", ""]
    out.write_text("\n".join(lines), "utf-8")
    print(f"\nCitazioni lette: {total_lette}  non lette: {total_non}\nRapporto salvato in: {out}")


def cmd_rapporto(args) -> None:
    """Come chiedi, ma salva la risposta e le fonti in data/rapporti/<data>-<titolo>.md"""
    from . import agent, ai
    import datetime
    try:
        model = ai.make_client()
    except ai.AIConfigError as e:
        sys.exit(str(e))
    question = args.domanda + "\n\nProduci un rapporto di ricerca completo e strutturato in sezioni."
    print(f"[{model.label} · {model.model}]", file=sys.stderr)
    try:
        answer = agent.ask(model, _db(), question, lang=args.lingua,
                           on_step=lambda e, i: print(f"  {e} {i}", file=sys.stderr, flush=True))
    except (ai.AIConfigError, RuntimeError, OSError) as e:
        sys.exit(f"Errore: {e}")
    out_dir = DATA / "rapporti"
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", args.domanda.lower())[:60].strip("-")
    path = out_dir / f"{datetime.date.today().isoformat()}-{slug}.md"
    lines = [f"# {args.domanda}", "", f"Data: {datetime.date.today().isoformat()} · Modello: {model.model} ({model.label})", "",
             answer.text, "", "## Fonti consultate", ""]
    for s in answer.sources:
        lines.append(f"- RS {s.sr} {s.num} {s.heading} (versione del {s.date})" if s.kind == "rs"
                     else f"- {s.label} {s.heading} {s.url}".rstrip())
    lines += ["", "## Ricerche eseguite", ""] + [f"- {st['strumento']} {json.dumps(st['argomenti'], ensure_ascii=False)}" for st in answer.steps]
    path.write_text("\n".join(lines), "utf-8")
    print(answer.text)
    print(f"\nRapporto salvato in: {path}")


def cmd_versioni(args) -> None:
    con = _db()
    act = _act(con, args.atto)
    print(act["title"])
    for d in store.list_dates(con, act["uri"], args.lingua):
        n = len(store.load_articles(con, act["uri"], args.lingua, d))
        print(f"  {d}  {n} articoli")


def cmd_differenze(args) -> None:
    con = _db()
    act = _act(con, args.atto)
    dates = store.list_dates(con, act["uri"], args.lingua)
    if len(dates) < 2 and not (args.da and args.a):
        sys.exit("Servono almeno due versioni in archivio.")
    d_old = args.da or dates[-2]
    d_new = args.a or dates[-1]
    changes = diff.compare(
        store.load_articles(con, act["uri"], args.lingua, d_old),
        store.load_articles(con, act["uri"], args.lingua, d_new),
    )
    print(f"{act['title']}\nDal {d_old} al {d_new}: {len(changes)} articoli cambiati\n")
    for c in changes:
        label = f"{c.num} {c.heading}".strip()
        print(f"[{c.kind.upper()}] {label}")
        if c.kind == "modificato":
            body = c.word_diff() if c.old != c.new else "(cambia solo la rubrica)"
            print(f"  {body}\n")
        elif c.kind == "aggiunto":
            print(f"  {c.new}\n")
        else:
            print()


def cmd_articolo(args) -> None:
    con = _db()
    act = _act(con, args.atto)
    dates = store.list_dates(con, act["uri"], args.lingua)
    date = args.data or store.in_force_date(dates)
    for a in store.load_articles(con, act["uri"], args.lingua, date):
        if a.eid == args.eid or a.num.replace(" ", "").lower() == args.eid.replace(" ", "").lower():
            print(f"{act['title']} (versione del {date})")
            if a.path:
                print(" > ".join(a.path))
            print(f"\n{a.num} {a.heading}\n\n{a.text}")
            for n in a.notes:
                print(f"\n  nota: {n}")
            return
    sys.exit(f"Articolo {args.eid} non trovato nella versione {date}")


def cmd_chiedi(args) -> None:
    from . import agent, ai
    try:
        model = ai.make_client()
    except ai.AIConfigError as e:
        sys.exit(str(e))
    labels = {"pensa": "Il modello ragiona", "risposta": "  risposta ricevuta in", "strumento": "  consulta l'archivio:"}

    def progress(event, info):
        print(f"{labels.get(event, event)} {info}", file=sys.stderr, flush=True)

    print(f"[{model.label} · {model.model}]", file=sys.stderr)
    try:
        answer = agent.ask(model, _db(), args.domanda, lang=args.lingua, on_step=progress)
    except (ai.AIConfigError, RuntimeError) as e:
        sys.exit(f"Errore: {e}")
    except KeyboardInterrupt:
        sys.exit("\nInterrotto.")
    except OSError as e:  # rete: timeout, connessione chiusa
        sys.exit(f"Errore di rete: {e}")
    print()
    print(answer.text)
    if answer.sources:
        print("\nFonti consultate:")
        for s in answer.sources:
            if s.kind == "rs":
                print(f"  RS {s.sr} {s.num} {s.heading} (versione del {s.date})")
            else:
                print(f"  {s.label}  {s.heading}  {s.url}")


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="nn", description="Nuova-Norma: archivio delle norme svizzere")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("atto", help="numero RS (es. 235.1) o URI Fedlex")
        sp.add_argument("--lingua", default="it", choices=sorted(fedlex.LANGUAGES))
        sp.set_defaults(fn=fn)
        return sp

    add("importa", cmd_importa, "scarica da Fedlex tutte le versioni XML di un atto")
    add("versioni", cmd_versioni, "elenca le versioni in archivio")
    d = add("differenze", cmd_differenze, "confronta due versioni articolo per articolo")
    d.add_argument("--da", help="data della versione vecchia (AAAA-MM-GG)")
    d.add_argument("--a", help="data della versione nuova (AAAA-MM-GG)")
    a = add("articolo", cmd_articolo, "mostra un articolo")
    a.add_argument("eid", help="es. art_6 oppure 'Art. 6'")
    a.add_argument("--data", help="versione (AAAA-MM-GG), predefinita l'ultima")
    q = sub.add_parser("chiedi", help="fa una domanda all'agente (modelli europei su Infomaniak)")
    q.add_argument("domanda")
    q.add_argument("--lingua", default="it", choices=sorted(fedlex.LANGUAGES))
    q.set_defaults(fn=cmd_chiedi)
    r = sub.add_parser("rielabora", help="rilegge i file gia scaricati con il parser aggiornato (senza Fedlex)")
    r.set_defaults(fn=cmd_rielabora)
    ip = sub.add_parser("importa-pacchetto", help="importa un gruppo di leggi per settore (anorma, sociali, finanza...)")
    ip.add_argument("nome", nargs="?", default="")
    ip.add_argument("--lingua", default="it", choices=sorted(fedlex.LANGUAGES))
    ip.set_defaults(fn=cmd_importa_pacchetto)
    ic = sub.add_parser("importa-catalogo", help="importa tutta la Raccolta sistematica in vigore, o un settore")
    ic.add_argument("--prefisso", help="numero RS iniziale del settore, es. 8 (sanita, lavoro, sicurezza sociale)")
    ic.add_argument("--trattati", action="store_true", help="includi i trattati internazionali (RS 0.x)")
    ic.add_argument("--limite", type=int, help="al massimo N atti in questa esecuzione")
    ic.add_argument("--aggiorna", action="store_true", help="ricontrolla anche gli atti gia in archivio (nuove versioni)")
    ic.add_argument("--solo-elenco", action="store_true", help="mostra cosa importerebbe, senza scaricare")
    ic.add_argument("--lingua", default="it", choices=sorted(fedlex.LANGUAGES))
    ic.set_defaults(fn=cmd_importa_catalogo)
    ar = sub.add_parser("aggiorna-raccolte", help="scarica e archivia le fonti documentali (direttive, circolari, sentenze...)")
    ar.add_argument("fonti", nargs="*", help="una o piu fonti; senza: tutte")
    ar.add_argument("--limite", type=int, help="al massimo N documenti scaricati per fonte")
    ar.add_argument("--giorni", type=int, default=7, help="non riscaricare cio che e stato letto da meno di N giorni")
    ar.add_argument("--forza", action="store_true", help="riscarica tutto")
    ar.add_argument("--solo", nargs="*", help="solo questi identificativi")
    ar.set_defaults(fn=cmd_aggiorna_raccolte)
    ev = sub.add_parser("esporta-vettori", help="scrive in JSONL gli articoli vigenti senza vettore (per colab/vettori.ipynb)")
    ev.add_argument("--file", help="file di destinazione (predefinito: data/vettori/da-calcolare.jsonl)")
    ev.add_argument("--lingua", choices=sorted(fedlex.LANGUAGES), help="solo questa lingua")
    ev.set_defaults(fn=cmd_esporta_vettori)
    cv = sub.add_parser("calcola-vettori", help="calcola sul PC (GPU se c'e) i vettori degli articoli che non li hanno")
    cv.add_argument("--batch", type=int, default=32, help="articoli per passata sulla GPU (meno se manca memoria)")
    cv.add_argument("--lingua", choices=sorted(fedlex.LANGUAGES), help="solo questa lingua")
    cv.add_argument("--da-capo", action="store_true", help="cancella i vettori esistenti e li ricalcola tutti")
    cv.set_defaults(fn=cmd_calcola_vettori)
    cs = sub.add_parser("copia-sicurezza", help="copia archivio, file originali e vettori in una cartella (es. disco esterno)")
    cs.add_argument("cartella")
    cs.set_defaults(fn=cmd_copia_sicurezza)
    vv = sub.add_parser("verifica-vettori", help="controlla la fonte dei vettori (locale o Infomaniak) e prova un embedding")
    vv.add_argument("--infomaniak", action="store_true", help="prova Infomaniak anche se la fonte attuale e locale")
    vv.add_argument("--modello", help="modello di embedding da provare")
    vv.set_defaults(fn=cmd_verifica_vettori)
    ri = sub.add_parser("ricostruisci-indice", help="ricostruisce l'indice di ricerca degli articoli vigenti (senza rete)")
    ri.set_defaults(fn=cmd_ricostruisci_indice)
    cd = sub.add_parser("candidati", help="mostra gli articoli che la ricerca preparata proporrebbe per una o piu domande")
    cd.add_argument("domande", nargs="+")
    cd.add_argument("--quanti", type=int, default=8)
    cd.add_argument("--lingua", default="it", choices=sorted(fedlex.LANGUAGES))
    cd.set_defaults(fn=cmd_candidati)
    iv = sub.add_parser("importa-vettori", help="aggiunge i vettori calcolati su Colab (file .npz)")
    iv.add_argument("file")
    iv.set_defaults(fn=cmd_importa_vettori)
    sr = sub.add_parser("stato-raccolte", help="documenti e versioni in archivio per ogni fonte documentale")
    sr.set_defaults(fn=cmd_stato_raccolte)
    vr = sub.add_parser("verifica-raccolte", help="prova i lettori delle fonti documentali senza modificare l'archivio")
    vr.add_argument("fonti", nargs="*")
    vr.set_defaults(fn=cmd_verifica_raccolte)
    vf = sub.add_parser("verifica-fonti", help="prova ogni fonte ufficiale e riporta cosa risponde")
    vf.set_defaults(fn=cmd_verifica_fonti)
    it = sub.add_parser("indicizza-ticino", help="esplora la Raccolta delle leggi del Canton Ticino e costruisce l'indice locale")
    it.add_argument("--pagine", type=int, default=80)
    it.set_defaults(fn=cmd_indicizza_ticino)
    vt = sub.add_parser("verifica-ticino", help="controlla se l'indice ticinese e completo (campione dei numeri mancanti)")
    vt.add_argument("--campione", type=int, default=25)
    vt.set_defaults(fn=cmd_verifica_ticino)
    va = sub.add_parser("valuta", help="esegue le domande di domande-prova.txt e produce un rapporto di confronto")
    va.add_argument("file", nargs="?", help="file con una domanda per riga (predefinito: domande-prova.txt)")
    va.add_argument("--lingua", default="it", choices=sorted(fedlex.LANGUAGES))
    va.set_defaults(fn=cmd_valuta)
    tp = sub.add_parser("ticino-pagina", help="mostra il testo della pagina di un atto ticinese (per numero interno)")
    tp.add_argument("id", type=int, nargs="+")
    tp.set_defaults(fn=cmd_ticino_pagina)
    rp = sub.add_parser("rapporto", help="ricerca ampia salvata come rapporto Markdown in data/rapporti")
    rp.add_argument("domanda")
    rp.add_argument("--lingua", default="it", choices=sorted(fedlex.LANGUAGES))
    rp.set_defaults(fn=cmd_rapporto)
    v = sub.add_parser("verifica-ai", help="controlla la configurazione AI (non mostra il token)")
    v.set_defaults(fn=lambda a: __import__("nn.ai", fromlist=["diagnose"]).diagnose())
    w = sub.add_parser("sito", help="apre l'interfaccia web locale nel browser")
    w.add_argument("--porta", type=int, default=8765)
    w.add_argument("--senza-browser", action="store_true")
    w.set_defaults(fn=lambda a: __import__("nn.web", fromlist=["serve"]).serve(a.porta, not a.senza_browser))

    args = p.parse_args(argv)
    try:
        args.fn(args)
    finally:
        while _open:
            _open.pop().close()


if __name__ == "__main__":
    main()
