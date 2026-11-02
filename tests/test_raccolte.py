"""Archivio comune delle fonti documentali e lettori: test senza rete, con pagine d'esempio."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nn import agent, documenti, raccolte, sources, store
from nn.documenti import Item


def db():
    tmp = tempfile.mkdtemp()
    con = store.connect(Path(tmp) / "t.sqlite")
    documenti.ensure(con)
    return con, Path(tmp) / "raw"


class TestDate(unittest.TestCase):
    def test_parse_date(self):
        self.assertEqual(documenti.parse_date("1° gennaio 2026"), "2026-01-01")
        self.assertEqual(documenti.parse_date("valida dal 01.04.2011"), "2011-04-01")
        self.assertEqual(documenti.parse_date("1er janvier 2025"), "2025-01-01")
        self.assertEqual(documenti.parse_date("Stand 1. Januar 2024"), "2024-01-01")
        self.assertEqual(documenti.parse_date("nulla"), "")

    def test_declared_date(self):
        self.assertEqual(documenti.declared_date("3.01 Promemoria\nStato al 1° gennaio 2026\nRendite"), "2026-01-01")
        self.assertEqual(documenti.declared_date("Kreisschreiben\nGültig ab 1. Januar 2027"), "2027-01-01")
        self.assertEqual(documenti.declared_date("nessuna data qui"), "")


class TestArchivio(unittest.TestCase):
    def test_versioni_impronta_e_spariti(self):
        con, raw = db()
        it = Item("ufas", "6930", "PC · Direttive (DPC)", "direttiva", "https://sozialversicherungen.admin.ch/it/d/6930/download",
                  meta={"sigla": "DPC"})
        documenti.save_item(con, it)
        r1 = documenti.save_version(con, it, b"<html><body><p>Stato al 1 gennaio 2025</p><p>Cifra 1 reddito</p></body></html>", raw)
        r2 = documenti.save_version(con, it, b"<html><body><p>Stato al 1 gennaio 2025</p><p>Cifra 1 reddito</p></body></html>", raw)
        self.assertTrue(r1["nuova"])
        self.assertFalse(r2["nuova"])          # stessa impronta: nessuna versione nuova
        self.assertEqual(r1["valid_from"], "2025-01-01")
        r3 = documenti.save_version(con, it, b"<html><body><p>Stato al 1 gennaio 2026</p><p>Cifra 1 reddito netto</p></body></html>", raw)
        self.assertTrue(r3["nuova"])
        self.assertEqual(len(documenti.history(con, "ufas", "6930")), 2)
        self.assertEqual(documenti.latest(con, "ufas", "6930")["valid_from"], "2026-01-01")
        self.assertTrue((raw / f"{r1['sha256']}.html").exists())
        # ricerca: solo l'ultima versione e indicizzata
        res = documenti.search(con, "reddito netto")
        self.assertEqual([r["key"] for r in res], ["6930"])
        # per sigla
        self.assertEqual(documenti.find(con, "ufas", "dpc")["key"], "6930")
        # sparito dall'elenco
        self.assertEqual(documenti.mark_gone(con, "ufas", set()), 1)
        self.assertTrue(documenti.search(con, "reddito")[0]["non_piu_pubblicato"])

    def test_html_text_senza_menu(self):
        t = documenti.html_text("<html><nav>Menu Home</nav><main>" + "<p>Art. 1 Testo</p>" * 60 + "</main><footer>Contatti</footer></html>")
        self.assertIn("Art. 1 Testo", t)
        self.assertNotIn("Menu", t)
        self.assertNotIn("Contatti", t)


PAGINA_CARTELLA = """
<html><body><main><h1>Prestazioni complementari: direttive</h1>
<table>
<tr><td>318.682 i</td><td><a href="/it/d/6930">Direttive concernenti le prestazioni complementari all'AVS e all'AI (DPC)</a></td>
<td>valida dal 01.04.2011; stato 1 gennaio 2026</td><td><a href="/it/d/6930/download">PDF</a></td></tr>
<tr><td>318.682.01 i</td><td><a href="/it/d/7001">Circolare sulle spese di malattia (CSM)</a></td>
<td>valida dal 01.01.2024</td><td><a href="/it/d/7001/download?version=3">PDF</a></td></tr>
</table></main></body></html>"""

PAGINA_DETTAGLIO = """<html><body><main><h1>Direttive concernenti le prestazioni complementari (DPC)</h1>
<p>Numero: 318.682 i</p><p>valida dal 01.04.2011; stato 1 gennaio 2026</p>
<table><tr><td>Versione 12</td><td>stato 1 gennaio 2025</td></tr></table>
""" + "<p>testo</p>" * 120 + "</main></body></html>"


class TestUFAS(unittest.TestCase):
    def test_cartella_e_dettaglio(self):
        l = raccolte.UFAS()
        items = {i.key: i for i in l.leggi_cartella(PAGINA_CARTELLA, "PC", "direttive", 5638)}
        self.assertEqual(set(items), {"6930", "7001"})
        it = items["6930"]
        self.assertIn("DPC", it.title)
        self.assertTrue(it.title.startswith("PC · "))
        self.assertEqual(it.url, "https://sozialversicherungen.admin.ch/it/d/6930/download")
        l.dettaglio(PAGINA_DETTAGLIO, it)
        self.assertEqual(it.meta["numero"], "318.682")
        self.assertEqual(it.meta["sigla"], "DPC")
        self.assertEqual(it.valid_from, "2026-01-01")      # lo stato attuale, non quello della versione 12
        self.assertEqual(it.meta["valida_dal"], "2011-04-01")

    def test_ripiego_lingua(self):
        l = raccolte.UFAS()
        it = Item("ufas", "8000", "AVS · KSRA", "direttiva", "x", page_url="https://sozialversicherungen.admin.ch/it/d/8000")
        pagina = "<main>Per questo documento non è stata trovata alcuna versione valida nella lingua selezionata (italiano)</main>"

        def fake(url, **kw):
            self.assertNotIn("/it/d/8000/download", url)
            return b"%PDF-1.7 ..." if "/fr/" in url else b"<html>no</html>"
        with mock.patch.object(sources, "fetch_text", return_value=pagina), mock.patch.object(sources, "fetch", side_effect=fake):
            raw, ctype = l.scarica(it)
        self.assertEqual(it.meta["lingua_testo"], "fr")
        self.assertIn("francese", it.meta["nota_lingua"])


PAGINA_INDICE = """<html><body><a href="/it/Opuscoli/Prestazioni-dellAVS">Prestazioni dell'AVS</a>
<a href="/it/Opuscoli/Prestazioni-dellAI">Prestazioni dell'AI</a><a href="https://example.com/x">fuori</a></body></html>"""
PAGINA_AVS = """<html><body><table>
<tr><td>3.01</td><td><a href="/p/3.01.i">Rendite di vecchiaia e assegni per grandi invalidi dell'AVS</a></td><td>Stato 01.01.2026</td></tr>
<tr><td>3.02</td><td>Rendite per superstiti</td><td>01.01.2026</td><td><a href="https://www.ahv-iv.ch/p/3.02.i">PDF</a></td></tr>
</table></body></html>"""


class TestPromemoria(unittest.TestCase):
    def test_categorie_e_righe(self):
        l = raccolte.Promemoria()
        cats = l.categorie(PAGINA_INDICE)
        self.assertEqual(len(cats), 2)
        items = {i.key: i for i in l.leggi_categoria(PAGINA_AVS, cats[0])}
        self.assertEqual(set(items), {"3.01", "3.02"})
        self.assertIn("Rendite di vecchiaia", items["3.01"].title)
        self.assertIn("superstiti", items["3.02"].title)
        self.assertEqual(items["3.01"].url, "https://www.ahv-iv.ch/p/3.01.i")
        self.assertEqual(items["3.01"].valid_from, "")   # la data si prende dal PDF


class FintoLettore(raccolte.Lettore):
    source = "promemoria"

    def __init__(self, docs):
        self.docs = docs

    def elenca(self, log=lambda *_: None):
        return [Item("promemoria", k, f"Promemoria {k}", "promemoria", f"https://www.ahv-iv.ch/p/{k}.i") for k in self.docs]

    def scarica(self, item):
        return self.docs[item.key], "text/html"


class TestAggiorna(unittest.TestCase):
    def test_aggiorna_e_strumenti_agente(self):
        con, raw = db()
        docs = {"3.01": "<html><body><p>Stato al 1° gennaio 2026</p><p>La rendita minima di vecchiaia ammonta a ...</p></body></html>".encode(),
                "3.02": "<html><body><p>Stato al 1° gennaio 2026</p><p>Rendite per vedove e orfani</p></body></html>".encode()}
        with mock.patch.object(sources, "robots_ok", return_value=True):
            es = raccolte.aggiorna(con, FintoLettore(docs), raw, log=lambda *_: None)
            self.assertEqual((es.elencati, es.nuove_versioni), (2, 2))
            es = raccolte.aggiorna(con, FintoLettore(docs), raw, log=lambda *_: None)   # letti da poco: non si riscaricano
            self.assertEqual(es.saltati, 2)
            del docs["3.02"]
            es = raccolte.aggiorna(con, FintoLettore(docs), raw, rileggi_dopo_giorni=0, log=lambda *_: None)
            self.assertEqual((es.invariati, es.spariti), (1, 1))

        a = agent.Archive(con)
        fonti = {f["fonte"]: f for f in a.elenca_fonti()}
        self.assertEqual(fonti["promemoria"]["livello"], "informativo")
        self.assertEqual(fonti["ufas"]["livello"], "prassi")
        res = a.fonti_cerca("rendita minima vecchiaia")
        self.assertEqual(res[0]["key"], "3.01")
        self.assertEqual(res[0]["livello"], "informativo")
        d = a.documento_leggi("promemoria", "3.01", cerca="rendita minima")
        self.assertEqual(d["cita_come"], "[Promemoria 3.01, 2026-01-01]")
        self.assertTrue(d["passaggi"])
        self.assertIn("divulgativa", d["significato_livello"])
        # la citazione si riconosce e corrisponde alla fonte aperta
        cits = agent.find_other_citations("La rendita minima ... [Promemoria 3.01, 2026-01-01]")
        self.assertEqual(cits[0].label, "Promemoria 3.01")
        self.assertIn("Promemoria 3.01", {s.label for s in a.sources.values()})
        # documento sparito: avviso
        d2 = a.documento_leggi("promemoria", "3.02")
        self.assertTrue(d2["non_piu_pubblicato"])
        self.assertIn("avviso", d2)
        with self.assertRaises(LookupError):
            a.documento_leggi("inesistente", "x")
        self.assertIn("nota", a.fonti_cerca("qualcosa", fonte="ufas")[0])

    def test_robots_esclude(self):
        con, raw = db()
        with mock.patch.object(sources, "robots_ok", return_value=False):
            es = raccolte.aggiorna(con, FintoLettore({"1.01": b"x"}), raw, log=lambda *_: None)
        self.assertEqual((es.nuove_versioni, es.saltati), (0, 1))
        self.assertIn("robots", es.note[0])


class TestRedirect(unittest.TestCase):
    def test_reindirizzamento_fuori_elenco_rifiutato(self):
        h = sources._SoloDominiAmmessi()
        req = mock.Mock(full_url="https://www.ahv-iv.ch/p/3.01.i")
        with self.assertRaises(sources.SourceNotAllowed):
            h.redirect_request(req, None, 302, "Found", {}, "https://tracker.example.com/x.pdf")


class TestTicinoArchiviato(unittest.TestCase):
    def test_cantone_leggi_usa_archivio(self):
        con, raw = db()
        from nn import cantoni
        cantoni._ensure(con)
        url = "https://m3.ti.ch/CAN/RLeggi/public/index.php/raccolta-leggi/legge/num/95"
        con.execute("INSERT INTO cantonal_acts VALUES ('TI','95','161.100','Legge sulla pubblicazione degli atti ufficiali',?,NULL,'2026-10-31')", (url,))
        items = raccolte.TicinoRL(con).elenca()
        self.assertEqual(items[0].key, "161.100")
        self.assertIn("legge-piatta", items[0].url)
        documenti.save_item(con, items[0])
        pagina = "<html><body><div>Menu</div><h1>Legge sulla pubblicazione degli atti ufficiali</h1><p>Art. 1 Scopo</p></body></html>"
        txt = raccolte.TicinoRL(con).testo(pagina.encode(), "", items[0])
        documenti.save_version(con, items[0], pagina.encode(), raw, text=txt)
        with mock.patch.object(cantoni, "text", side_effect=AssertionError("non deve andare in rete")):
            d = agent.Archive(con).cantone_leggi(url)
        self.assertTrue(d["testo"].startswith("Legge sulla pubblicazione"))
        self.assertEqual(d["numero"], "161.100")
        self.assertIn("archiviato_il", d)


class TestIFPDT(unittest.TestCase):
    def test_sitemap_e_pdf(self):
        l = raccolte.IFPDT()
        xml = """<urlset><url><loc>https://www.edoeb.admin.ch/it/faq-protezione-dei-dati</loc></url>
        <url><loc>https://www.edoeb.admin.ch/de/faq-datenschutz</loc></url><url><loc>https://www.edoeb.admin.ch/it/</loc></url></urlset>"""
        self.assertEqual(len(l.sitemap_urls(xml)), 3)
        page = """<a href="/dam/it/sd-web/eVhrh8wY3QcR/TOM_IT.pdf">Guida sulle misure tecniche e organizzative</a>
        <a href="/dam/de/sd-web/abc/Verfuegung_2024.pdf">Decisione 2024</a><a href="https://example.com/x.pdf">x</a>"""
        items = {i.key: i for i in l.pdf_da_pagina(page, "https://www.edoeb.admin.ch/it/documentazione-protezione-dei-dati", "guida")}
        self.assertEqual(set(items), {"pdf:TOM_IT", "pdf:Verfuegung_2024"})
        self.assertEqual(items["pdf:TOM_IT"].title, "Guida sulle misure tecniche e organizzative")
        self.assertEqual(items["pdf:Verfuegung_2024"].meta["lingua_testo"], "de")


class TestFINMA(unittest.TestCase):
    def test_archivio_e_versione_piu_recente(self):
        l = raccolte.FINMA()
        page = """<a href="/it/~/media/finma/dokumente/rundschreiben-archiv/2008/rs-08-01/rs-08-01-letzte-aenderung-20090101.pdf?sc_lang=it">Circ. 2008/1 Fonte</a>
        <a href="/it/~/media/finma/dokumente/rundschreiben-archiv/2008/rs-08-01/rs-08-01-letzte-aenderung-20130101.pdf?sc_lang=it&hash=AB">PDF</a>
        <a href="/it/~/media/finma/dokumente/dokumentencenter/myfinma/rundschreiben/finma-rs-2025-02-20241122.pdf">Circ. 2025/2 Rischi climatici</a>"""
        items = {i.key: i for i in l.leggi_pagina(page, "https://www.finma.ch/it/documentazione/archiv/rundschreiben/archiv-2008/", True)}
        self.assertEqual(set(items), {"2008/01", "2025/02"})
        self.assertEqual(items["2008/01"].meta["data_file"], "2013-01-01")
        self.assertNotIn("hash=", items["2008/01"].url)
        self.assertTrue(items["2025/02"].title.startswith("Archivio · Circ. 2025/2"))


CSV_UST = """\ufeffvorlage_id,urnengang_datum,kanton_nummer,kanton_name,stimmberechtigte,stimmende,stimmen_ja,stimmen_nein,ja_prozent,vorlage_titel_i
6800,2024-03-03,1,Zürich,900000,500000,300000,190000,61.2,Iniziativa popolare per una 13a mensilita AVS
6800,2024-03-03,21,Ticino,220000,110000,70000,38000,64.8,Iniziativa popolare per una 13a mensilita AVS
6800,2024-03-03,16,Appenzell I.Rh.,12000,6000,2000,3800,34.5,Iniziativa popolare per una 13a mensilita AVS
6810,2024-03-03,1,Zürich,900000,500000,120000,370000,24.5,Iniziativa sulle rendite
"""


class TestVotazioni(unittest.TestCase):
    def test_aggregazione(self):
        l = raccolte.Votazioni()
        items = {i.key: i for i in l.analizza(CSV_UST)}
        self.assertEqual(set(items), {"6800", "6810"})
        self.assertEqual(items["6800"].valid_from, "2024-03-03")
        self.assertIn("13a mensilita AVS", items["6800"].title)
        t = l._testi["6800"]
        self.assertIn("si 372'000 · no 231'800", t)
        self.assertIn("Maggioranza dei votanti: si", t)
        self.assertIn("2 su 23", t)            # ZH + TI favorevoli, AI (semicantone) contrario
        self.assertIn("del 3.3.2024", t)
        self.assertIn("Ticino: si 70'000", t)
        self.assertNotIn("accettat", t)        # il tipo di oggetto non e nel file: nessun verdetto inventato
        self.assertIn("Maggioranza dei votanti: no", l._testi["6810"])

    def test_colonne_mancanti(self):
        with self.assertRaises(RuntimeError):
            raccolte.Votazioni().analizza("a,b\n1,2\n")


class TestCAVPP(unittest.TestCase):
    def test_pdf_piu_recente_e_lingua(self):
        l = raccolte.CAVPP()
        page = """<h1>D – 01/2017 Requisiti per i periti</h1>
        <a href="/dam/it/sd-web/PBnzPl8rgC4Q/D-01_2017_CAV%20PP_Prima%20versione_24.10.2017.pdf">Prima versione</a>
        <a href="/dam/it/sd-web/xyz123456789/D-01_2017_CHS%20PP_Version%20r%C3%A9vis%C3%A9e_17.09.2026.pdf">Versione revisionata (disponibile in francese)</a>"""
        url, data, lingua = l.pdf_piu_recente(page, "https://www.oak-bv.admin.ch/it/direttive-d-01-2017")
        self.assertEqual(data, "2026-09-17")
        self.assertEqual(lingua, "fr")
        self.assertIn("xyz123456789", url)

    def test_elenco_da_sitemap(self):
        l = raccolte.CAVPP()
        sitemap = """<urlset><url><loc>https://www.oak-bv.admin.ch/it/direttive-d-01-2026</loc></url>
        <url><loc>https://www.oak-bv.admin.ch/it/comunicazioni-c-03-2025</loc></url><url><loc>https://www.oak-bv.admin.ch/it/pubblicazioni</loc></url></urlset>"""
        pagina = """<h1>Titolo</h1><a href="/dam/it/sd-web/abcdefabcdef/X_Prima%20versione_22.04.2026.pdf">PDF</a>"""

        def fake(url, **kw):
            return sitemap if url.endswith("it.xml") else pagina
        with mock.patch.object(sources, "fetch_text", side_effect=fake):
            items = {i.key: i for i in l.elenca()}
        self.assertEqual(set(items), {"D-01/2026", "C-03/2025"})
        self.assertEqual(items["D-01/2026"].kind, "direttiva")
        self.assertEqual(items["D-01/2026"].valid_from, "2026-04-22")
        self.assertNotIn("lingua_testo", items["D-01/2026"].meta)


class TestUFASTedesco(unittest.TestCase):
    def test_link_tedesco_segna_manca_italiano(self):
        page = """<a href="/de/d/20963">Mitteilungen über die berufliche Vorsorge Nr. 168</a>"""
        it = raccolte.UFAS().leggi_cartella(page, "PP", "Bollettino", 5578)[0]
        self.assertTrue(it.meta["manca_italiano"])
        self.assertIn("Nr. 168", it.title)


class TestSitoConfederazione(unittest.TestCase):
    def test_chiave_stabile(self):
        self.assertEqual(raccolte.chiave_da_file("D-01_2017_CAV%20PP_Prima%20versione_24.10.2017.pdf"),
                         raccolte.chiave_da_file("D-01_2017_CAV PP_Versione revisionata_17.09.2026.pdf"))
        self.assertEqual(raccolte.chiave_da_file("rs-08-01-20130101.pdf"), "rs-08-01")

    def test_documenti_e_sottopagine(self):
        class Sito(raccolte.SitoConfederazione):
            source = "prova"
            BASE = "https://www.esempio.admin.ch"
            SEZIONI = {"/it/guide": "guida"}
        l = Sito()
        page = """<a href="/dam/it/sd-web/AAA/Guida_rumore_01.01.2024.pdf">Guida sul rumore</a>
        <a href="/dam/it/sd-web/BBB/Guida_rumore_01.07.2026.pdf">Guida sul rumore (aggiornata)</a>
        <a href="/dam/de/sd-web/CCC/Merkblatt.pdf">Promemoria</a><a href="https://altro.ch/x.pdf">fuori</a>
        <a href="/it/guide/ambiente">Ambiente</a><a href="/it/altro">no</a>"""
        items = {i.key: i for i in l.documenti_pagina(page, "https://www.esempio.admin.ch/it/guide", "guida")}
        self.assertEqual(set(items), {"Guida_rumore", "Merkblatt"})
        self.assertEqual(items["Guida_rumore"].valid_from, "2026-07-01")
        self.assertIn("aggiornata", items["Guida_rumore"].title)
        self.assertEqual(items["Merkblatt"].meta["lingua_testo"], "de")
        self.assertEqual(l.sottopagine(page, "https://www.esempio.admin.ch/it/guide"), ["https://www.esempio.admin.ch/it/guide/ambiente"])


class TestRobots(unittest.TestCase):
    def setUp(self):
        sources._robots.clear()

    def test_stati(self):
        with mock.patch.object(sources, "_leggi_robots", return_value=["User-agent: *", "Disallow: /cgi-bin/"]):
            self.assertFalse(sources.robots_stato("https://www.sentenze.ti.ch/cgi-bin/x"))
            self.assertTrue(sources.robots_stato("https://www.sentenze.ti.ch/altro"))
        sources._robots.clear()
        with mock.patch.object(sources, "_leggi_robots", return_value=None):
            self.assertIsNone(sources.robots_stato("https://www.esempio.ch/x"))
            self.assertTrue(sources.robots_ok("https://www.esempio.ch/x"))
        sources._robots.clear()
        with mock.patch.object(sources, "_leggi_robots", return_value=[]):
            self.assertTrue(sources.robots_stato("https://www.esempio2.ch/x"))


class TestSECO(unittest.TestCase):
    def test_pagina(self):
        page = """<a href="https://www.arbeit.swiss/api/media/fileservice/sdweb-docs-prod-arbeitswiss-files/files/2026/07/02/3eb1.pdf">Prassi LADI ID valida dal 1.7.2026</a>
        <a href="https://www.arbeit.swiss/api/media/fileservice/sdweb-docs-prod-arbeitswiss-files/files/2026/09/15/37d9.pdf">Prassi LADI ILR valida dal 1.7.2026 (PDF, 2 MB)</a>
        <a href="https://www.arbeit.swiss/api/media/fileservice/x/files/2026/01/01/aaaa.pdf">PDF</a>"""
        items = {i.key: i for i in raccolte.SECOLADI().leggi_pagina(page, raccolte.SECOLADI.PAGINA)}
        self.assertEqual(set(items), {"Prassi LADI ID", "Prassi LADI ILR"})
        self.assertEqual(items["Prassi LADI ID"].valid_from, "2026-07-01")


class TestOmbudsman(unittest.TestCase):
    def test_json(self):
        posts = [{"id": 1041, "slug": "viaggio-cancellazione-viaggio", "date": "2021-08-25T10:00:00", "link": "https://ombudsman-assicurazione.ch/viaggio-cancellazione-viaggio/",
                  "title": {"rendered": "Viaggio: cancellazione"}, "content": {"rendered": "<p>La signora X aveva stipulato...</p>"}}]
        media = [{"source_url": "https://versicherungsombudsman.ch/wp-content/uploads/2026/05/OM-Jahresbericht_2025.pdf", "date": "2026-05-02T00:00:00",
                  "title": {"rendered": "OM-Jahresbericht 2025"}},
                 {"source_url": "https://versicherungsombudsman.ch/wp-content/uploads/2025/04/Riassunto-rapporto-annuale-2024.pdf", "date": "2025-04-01", "title": {"rendered": "Riassunto"}}]
        l = raccolte.Ombudsman()
        items = {i.key: i for i in l.da_json(posts, media)}
        self.assertIn("caso:viaggio-cancellazione-viaggio", items)
        self.assertIn("La signora X", l._testi["caso:viaggio-cancellazione-viaggio"])
        self.assertEqual(items["pdf:OM-Jahresbericht_2025"].meta["lingua_testo"], "de")
        self.assertNotIn("lingua_testo", items["pdf:Riassunto-rapporto-annuale-2024"].meta)
        self.assertEqual(sources.SOURCES["ombudsman"].livello_effettivo, "privato")


class TestAFCSEMSECO(unittest.TestCase):
    def test_chiavi(self):
        a = raccolte.AFC()
        self.assertEqual(a.chiave("dbst-ks-2020-1-050a-d-it.pdf", ""), "n. 50a")
        self.assertEqual(a.chiave("dbst-ks-2025-1-032a-dvs-it.pdf", ""), "n. 32a")
        self.assertEqual(a.chiave("mwst-kg-zeitliche-wirkung-it.pdf", ""), "mwst-kg-zeitliche-wirkung")
        self.assertEqual(raccolte.SEM().chiave("weisungen-aig-i.pdf", ""), "weisungen-aig")
        s = raccolte.SECOLavoro()
        self.assertEqual(s.chiave("ArG-Artikel-02-SECO-AB-2025-IT.pdf", ""), s.chiave("ArG-Artikel-02-SECO-AB-2026-IT.pdf", ""))

    def test_sem_due_livelli(self):
        l = raccolte.SEM()
        base = l.BASE + "/sem/it/home/publiservice/weisungen-kreisschreiben.html"
        pagine = {
            base: '<a href="/sem/it/home/publiservice/weisungen-kreisschreiben/auslaenderbereich.html">LStrI</a>',
            l.BASE + "/sem/it/home/publiservice/weisungen-kreisschreiben/auslaenderbereich.html":
                '<a href="/sem/it/home/publiservice/weisungen-kreisschreiben/auslaenderbereich/familiennachzug.html">Cap. 6</a>'
                '<a href="/dam/sem/it/data/rechtsgrundlagen/weisungen/auslaender/weisungen-aig.pdf.download.pdf/weisungen-aig-i.pdf">Istruzioni LStrI</a>',
            l.BASE + "/sem/it/home/publiservice/weisungen-kreisschreiben/auslaenderbereich/familiennachzug.html":
                '<a href="/dam/sem/it/data/rechtsgrundlagen/weisungen/auslaender/weisungen-aig-k6.pdf.download.pdf/weisungen-aig-k6-i.pdf">Cap. 6</a>',
        }
        with mock.patch.object(sources, "fetch_text", side_effect=lambda u, **k: pagine[u]):
            keys = {i.key for i in l.elenca()}
        self.assertEqual(keys, {"weisungen-aig", "weisungen-aig-k6"})


class TestAltriUffici(unittest.TestCase):
    def test_chiavi(self):
        self.assertEqual(raccolte.UFCOM().chiave("sr_784.101.113-1.9_veröffentlichung.pdf", ""), "RS 784.101.113/1.9")
        self.assertEqual(raccolte.COMCO().chiave("RPW 2025_4a.pdf", ""), "DPC 2025/4a")
        self.assertEqual(raccolte.COMCO().chiave("rpw_2025_1.pdf", ""), "DPC 2025/1")
        self.assertEqual(raccolte.UFAM().chiave("UV-2656 Vollzugshilfe Geruchsempfehlung_IT.pdf", ""), "UV-2656")
        self.assertEqual(raccolte.Swissmedic().chiave("ZL000_00_021d_WL Angaben auf Packmittel.pdf", ""), "ZL000_00_021_WL")
        self.assertIn("/it/decisioni-2024-2025", raccolte.ComCom().SEZIONI)

    def test_decisione_e_lingua(self):
        con, raw = db()
        l = raccolte.COMCO()
        it = l.documenti_pagina('<a href="/dam/it/sd-web/yrsVr-XH7yzi/blocking_patent_decision_du_7_octobre_2024.pdf">Decisione</a>',
                                "https://www.weko.admin.ch/it/decisioni", "decisione")[0]
        self.assertEqual(it.meta["livello"], "decisione")
        documenti.save_item(con, it)
        documenti.save_version(con, it, b"<html><p>Decisione sul brevetto di blocco</p></html>", raw)
        a = agent.Archive(con)
        self.assertEqual(a.fonti_cerca("brevetto blocco")[0]["livello"], "decisione")
        d = a.documento_leggi("comco", it.key)
        self.assertEqual(d["livello"], "decisione")
        sm = raccolte.Swissmedic().documenti_pagina(
            '<a href="/dam/swissmedic/de/dokumente/zulassung/zl000_00_021d_wl.pdf.download.pdf/ZL000_00_021d_WL%20Angaben.pdf">Guida</a>',
            "https://www.swissmedic.ch/swissmedic/it/home/services/documents/x.html", "guida")[0]
        self.assertEqual(sm.meta["lingua_testo"], "de")


class TestEURLex(unittest.TestCase):
    def test_versioni_e_articolo(self):
        from nn import eurlex
        righe = [
            {"celex": "32016R0679", "manif": "http://publications.europa.eu/resource/cellar/3e48.0013.03", "type": "xhtml",
             "item": "http://publications.europa.eu/resource/cellar/3e48.0013.03/DOC_1"},
            {"celex": "32016R0679", "manif": "http://publications.europa.eu/resource/cellar/3e48.0013.01", "type": "pdfa1a"},
            {"celex": "02016R0679-20160504", "date": "2016-05-04", "manif": "http://publications.europa.eu/resource/cellar/5f25.0002.04", "type": "xhtml"},
        ]
        with mock.patch.object(eurlex, "sparql", return_value=righe):
            vs = eurlex.versioni("32016R0679")
        self.assertEqual([v["celex"] for v in vs], ["32016R0679", "02016R0679-20160504"])
        self.assertTrue(vs[0]["url"].startswith("https://publications.europa.eu/"))
        self.assertTrue(vs[1]["url"].endswith("/DOC_1"))
        self.assertNotIn('0679"x', eurlex.query_versioni('32016R0679"x'))   # le virgolette non entrano nella query
        con, raw = db()
        it = Item("eurlex", "32016R0679", "GDPR", "atto UE", vs[-1]["url"], valid_from="2016-05-04")
        documenti.save_item(con, it)
        testo = ("Articolo 32\nSicurezza del trattamento\n1. Il titolare...\n"
                 "Articolo 33\nNotifica di una violazione dei dati personali all'autorita di controllo\n"
                 "1. In caso di violazione dei dati personali, il titolare del trattamento notifica ... senza ingiustificato ritardo\n"
                 "Articolo 34\nComunicazione all'interessato")
        documenti.save_version(con, it, testo.encode(), raw, text=testo)
        d = agent.Archive(con).documento_leggi("eurlex", "32016R0679", articolo="33")
        self.assertTrue(d["testo"].startswith("Articolo 33"))
        self.assertNotIn("Articolo 34", d["testo"])
        self.assertEqual(d["cita_come"], "[UE 32016R0679 art. 33, 2016-05-04]")
        self.assertEqual(d["livello"], "diritto_ue")
        self.assertIn("accordo", d["significato_livello"])
        self.assertEqual(agent.find_other_citations(d["cita_come"])[0].kind, "UE")


class TestOpenCaseLaw(unittest.TestCase):
    def test_cerca_leggi_archivia(self):
        from nn import opencaselaw
        risposte = {
            "/decisions?": {"total": 2, "has_more": False, "results": [
                {"decision_id": "ti_tca_52.2023.10", "court": "TI TCA", "decision_date": "2024-02-01", "language": "it",
                 "title": "Locazione: disdetta", "regeste": "Disdetta abusiva...", "canonical_url": "https://www.sentenze.ti.ch/x"}]},
            "/decisions/ti_tca_52.2023.10": {"decision_id": "ti_tca_52.2023.10", "court": "TI TCA", "decision_date": "2024-02-01",
                                              "language": "it", "title": "Locazione: disdetta", "canonical_url": "https://www.sentenze.ti.ch/x",
                                              "full_text": "Fatti ... Diritto: 2.3 La disdetta e annullabile ..."},
        }
        visti = []

        def fake(url, **kw):
            visti.append(url)
            self.assertTrue(url.startswith(opencaselaw.BASE))
            for k, v in risposte.items():
                if k in url:
                    return v
            raise AssertionError(url)
        tmp = tempfile.mkdtemp()
        con = store.connect(Path(tmp) / "t.sqlite")
        a = agent.Archive(con)
        self.assertEqual(a.raw_dir, Path(tmp) / "raw")
        with mock.patch.object(sources, "fetch_json", side_effect=fake):
            r = a.sentenze_cerca("disdetta abusiva locazione", cantone="ticino")
            self.assertIn("canton=TI", visti[0])
            self.assertEqual(r["risultati"][0]["id"], "ti_tca_52.2023.10")
            d = a.sentenza_leggi("ti_tca_52.2023.10")
        self.assertIn("annullabile", d["testo"])
        self.assertEqual(d["cita_come"], "[Sentenza ti_tca_52.2023.10, 2024-02-01]")
        self.assertEqual(agent.find_other_citations(d["cita_come"])[0].label, "Sentenza ti_tca_52.2023.10")
        self.assertIn("Sentenza ti_tca_52.2023.10", {x.label for x in a.sources.values()})
        arch = documenti.latest(con, "opencaselaw", "ti_tca_52.2023.10")
        self.assertIn("annullabile", arch["text"])
        self.assertTrue(any((Path(tmp) / "raw").iterdir()))

    def test_senza_file_niente_archivio(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        self.assertIsNone(agent.Archive(con).raw_dir)


if __name__ == "__main__":
    unittest.main()
