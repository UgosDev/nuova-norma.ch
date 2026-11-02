"""Test senza rete delle fonti ufficiali: le risposte HTTP sono simulate nel formato delle API reali."""

import json
import tempfile
import unittest
import urllib.parse
from unittest import mock

from nn import agent, cantoni, fedlex, giurisprudenza, parlamento, sources, store
from tests.test_agent import make_db


def sparql_json(rows):
    return json.dumps({"results": {"bindings": [
        {k: {"type": "literal", "value": v} for k, v in r.items()} for r in rows]}}).encode()


class TestAllowlist(unittest.TestCase):
    def test_refuses_unknown_domain(self):
        with self.assertRaises(sources.SourceNotAllowed):
            sources.fetch("https://example.com/x")
        with self.assertRaises(sources.SourceNotAllowed):
            sources.fetch("https://www.google.com/search?q=legge")
        sources.assert_allowed("https://fedlex.data.admin.ch/sparqlendpoint")
        sources.assert_allowed("https://ws.parlament.ch/odata.svc/Business")


class TestFedlex(unittest.TestCase):
    def test_search_titles_and_future(self):
        calls = []

        def fake_fetch(url, data=None, headers=None, timeout=60, retries=3):
            q = urllib.parse.parse_qs(data.decode())["query"][0]
            calls.append(q)
            if "jolux:Consultation" in q:
                return sparql_json([{"c": "x", "eventId": "2026/12", "title": "Revisione LPD", "end": "2026-12-31",
                                     "status": "https://fedlex.data.admin.ch/vocabulary/consultation-status/2"}])
            if "CONTAINS(LCASE(STR(?title))" in q and "ConsolidationAbstract" in q:
                self.assertIn('"protezione"', q)
                self.assertIn('"dati"', q)
                return sparql_json([{"ca": "https://fedlex.data.admin.ch/eli/cc/2022/491", "title": "Legge federale sulla protezione dei dati"},  # stessa legge, riga senza numero RS
                                    {"ca": "https://fedlex.data.admin.ch/eli/cc/1998/1", "title": "Convenzione sulla protezione dei dati",
                                     "sr": "0.235.1", "status": "https://fedlex.data.admin.ch/vocabulary/enforcement-status/0"},
                                    {"ca": "https://fedlex.data.admin.ch/eli/cc/2017/2", "title": "Ordinanza sulla protezione dei dati personali del personale federale",
                                     "sr": "172.220.111.4", "status": "https://fedlex.data.admin.ch/vocabulary/enforcement-status/0"},
                                    {"ca": "https://fedlex.data.admin.ch/eli/cc/2022/491", "title": "Legge federale sulla protezione dei dati",
                                     "titleShort": "LPD", "sr": "235.1",
                                     "status": "https://fedlex.data.admin.ch/vocabulary/enforcement-status/0"}])
            if "dateEntryInForce" in q:
                return sparql_json([{"ca": "https://fedlex.data.admin.ch/eli/cc/2026/1", "title": "Nuova legge", "sr": "999.9", "entry": "2027-01-01"}])
            if "publicationDate" in q:
                return sparql_json([{"act": "https://fedlex.data.admin.ch/eli/oc/2026/100", "title": "Modifica OPDa", "pubDate": "2026-10-20"}])
            return sparql_json([])

        with mock.patch.object(sources, "fetch", fake_fetch):
            r = fedlex.search_titles("protezione dei dati")
            self.assertEqual([x["rs"] for x in r], ["235.1", "172.220.111.4", "0.235.1"])  # legge (righe unite, col numero RS), ordinanza, trattato
            self.assertEqual(r[0]["stato"], "in vigore")
            self.assertTrue(r[0]["url"].startswith("https://www.fedlex.admin.ch/eli/cc/2022/491"))
            self.assertEqual(fedlex.upcoming_entries()[0]["entrata_in_vigore"], "2027-01-01")
            c = fedlex.consultations("LPD")
            self.assertEqual((c[0]["id"], c[0]["stato"]), ("2026/12", "in corso"))
            self.assertEqual(fedlex.recent_publications()[0]["raccolta"], "RU")

    def test_escape(self):
        self.assertEqual(fedlex.sparql_escape('a"b'), 'a\\"b')


class TestParlamento(unittest.TestCase):
    def test_search_and_detail(self):
        seen = {}

        def fake_json(url, **kw):
            seen["url"] = url
            if "Business(ID=" in url:
                return {"d": {"ID": 1, "BusinessShortNumber": "23.4567", "Title": "Mozione X", "BusinessStatusText": "Liquidato",
                              "SubmittedText": "<p>Testo &amp; motivazione</p>", "SubmissionDate": "/Date(1700000000000)/"}}
            return {"d": {"results": [{"ID": 1, "BusinessShortNumber": "23.4567", "Title": "Mozione X",
                                       "SubmissionDate": "/Date(1700000000000)/", "BusinessStatusText": "Depositato"}]}}

        with mock.patch.object(sources, "fetch_json", fake_json):
            r = parlamento.search_business("protezione dati", status="Depositato")
            q = urllib.parse.unquote_plus(seen["url"])
            self.assertIn("Language eq 'IT'", q)
            self.assertIn("substringof('protezione',Title)", q)
            self.assertIn("BusinessStatusText eq 'Depositato'", q)
            self.assertEqual(r[0]["depositato_il"], "2023-11-14")
            d = parlamento.business_detail(1)
            self.assertEqual(d["testo"], "Testo & motivazione")


class TestGiurisprudenza(unittest.TestCase):
    PAGE = """<html><body><div class="ranklist_content">
    <a href="index.php?highlight_docid=aza%3A%2F%2F12-03-2024-4A_123-2023&lang=it&type=show_document">4A_123/2023</a>
    12.03.2024 Protezione dei dati, risarcimento ... </div>
    <a href="index.php?highlight_docid=atf://145-III-225&lang=it&type=show_document">145 III 225</a>
    <a href="index.php?highlight_docid=atf://142-III-263:it&lang=it&type=show_document">142 III 263</a></body></html>"""

    def test_parse_and_urls(self):
        r = giurisprudenza.parse_results(self.PAGE, "aza", "it", 10)
        self.assertEqual([(x["tipo"], x["numero"], x["data"]) for x in r],
                         [("TF", "4A_123/2023", "2024-03-12"), ("DTF", "145 III 225", ""), ("DTF", "142 III 263", "")])
        self.assertTrue(r[2]["docid"].endswith(":it"))  # il docid resta intero: serve per aprire la pagina
        self.assertIn("highlight_docid=aza%3A%2F%2F12-03-2024-4A_123-2023", r[0]["url"])
        url = giurisprudenza._search_url("clir", "dati", "it")
        self.assertIn("top_subcollection_clir=all", url)
        self.assertTrue(url.startswith("https://www.bger.ch/ext/eurospider/live/it/php/clir/"))

    def test_decision_text(self):
        page = "<html><head><title>x</title></head><body><div id=\"content\">Tribunale federale Fatti: A. La ricorrente... Diritto: 1. ...</div></body></html>"
        with mock.patch.object(sources, "fetch_text", lambda url, **kw: page):
            d = giurisprudenza.decision_text("aza://12-03-2024-4A_123-2023")
            self.assertTrue(d["testo"].startswith("Fatti: A. La ricorrente"))


class TestTicino(unittest.TestCase):
    HOME = """<a href="/CAN/RLeggi/public/index.php/raccolta-leggi/libro/n/1">1 STATO</a>
              <a href="https://m3.ti.ch/CAN/RLeggi/public/index.php/raccolta-leggi/legge/num/58">161.100 Legge sulle pubblicazioni ufficiali</a>"""
    CAT = """<a href="https://m3.ti.ch/CAN/RLeggi/public/index.php/raccolta-leggi/legge-piatta/num/58">Legge sulle pubblicazioni ufficiali</a>
             <a href="https://m3.ti.ch/CAN/RLeggi/public/index.php/raccolta-leggi/legge/num/6724">161.110 - Regolamento sulle pubblicazioni ufficiali</a>
             <a href="https://m3.ti.ch/CAN/RLeggi/public/index.php/raccolta-leggi/legge-piatta/num/6724">Regolamento sulle pubblicazioni ufficiali</a>
             <a href="https://www.google.com/x">fuori</a>"""

    def test_check_gaps(self):
        import urllib.error
        SHELL = "<html><body><h1>CAN - Raccolta delle leggi del Cantone Ticino</h1><p>Repubblica e Cantone Ticino</p></body></html>"
        ACT = "<html><body><h1>CAN - Raccolta</h1><h2>Legge X</h2><p>Art. 1 Scopo</p></body></html>"
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            cantoni._ensure(con)
            for n in (1, 2, 5):
                con.execute("INSERT INTO cantonal_acts(canton, act_key, number, title, url, pdf_url, discovered_at) "
                            "VALUES ('TI', ?, ?, 'x', 'u', NULL, 'now')", (str(n), f"1.{n}"))
            con.commit()
            pages = {1: ACT, 2: ACT, 5: ACT, 3: SHELL, 999999: SHELL}  # 3 = numero inesistente: risponde col guscio

            def fake(url, **kw):
                n = int(url.rsplit("/", 1)[1])
                if n == 4:
                    raise urllib.error.HTTPError(url, 404, "nf", {}, None)
                return pages[n]

            with mock.patch.object(sources, "fetch_text", fake):
                res = cantoni.check_gaps(con, sample=10)
            self.assertTrue(res["controllo_affidabile"])
            self.assertEqual(res["riepilogo"], {"inesistente (pagina vuota del sito)": 1, "HTTP 404": 1})
            self.assertEqual(res["esistenti"], [])
            pages[3] = "<html><body><h1>Pagina di tutt'altro tipo</h1>" + "<p>contenuto lungo senza articoli numerati</p>" * 6 + "</body></html>"
            with mock.patch.object(sources, "fetch_text", fake):
                res = cantoni.check_gaps(con, sample=10)
            self.assertEqual([d["id"] for d in res["dubbi"]], [3])  # ne guscio ne atto: va segnalato, non ignorato
            self.assertEqual(res["esistenti"], [])
            pages[3] = ("<html><body>DATA ULTIMO BU CON MODIFICHE 30.10.2026 > 3 L'atto normativo cercato non è contenuto nella "
                        "Raccolta delle leggi. PROSSIME VARIAZIONI chiudi - NUOVO chiudi - 561.100 NUOVO (BU 2026, 212) "
                        "Variazione in vigore dal 01.01.2027 MESSAGGI</body></html>")
            with mock.patch.object(sources, "fetch_text", fake):
                res = cantoni.check_gaps(con, sample=10)
            self.assertEqual(res["in_arrivo"], [{"id": 3, "numero": "561.100", "dal": "01.01.2027"}])
            self.assertEqual((res["dubbi"], res["esistenti"]), ([], []))
            pages[3] = ACT  # ora il numero 3 e un atto vero: l'indice e incompleto
            with mock.patch.object(sources, "fetch_text", fake):
                res = cantoni.check_gaps(con, sample=10)
            self.assertEqual(res["esistenti"], [3])
            # se il controllo e l'atto noto non si distinguono, il metodo lo dichiara
            pages.update({1: SHELL, 2: SHELL, 5: SHELL})
            with mock.patch.object(sources, "fetch_text", fake):
                self.assertFalse(cantoni.check_gaps(con, sample=10)["controllo_affidabile"])
            con.close()

    def test_commenti_html_e_inizio_testo(self):
        page = (b"<html><body><!--[if lt IE 9]><p>vecchio</p><![endif]--><div>CAN - Raccolta --> </div>"
                b"<p>161.100</p><p>\xef\xbb\xbf</p><p>: DL che autorizza la pubblicazione di una Raccolta - 1956</p>"
                b"<p>Legge</p><p>sulle pubblicazioni ufficiali</p><p>Art. 1 Testo</p></body></html>")
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            cantoni._ensure(con)
            con.execute("INSERT INTO cantonal_acts(canton, act_key, number, title, url, pdf_url, discovered_at) "
                        "VALUES ('TI', '58', '161.100', 'Legge sulle pubblicazioni ufficiali (LPU)', 'https://m3.ti.ch/x/58', NULL, 'now')")
            con.commit()
            with mock.patch.object(sources, "fetch", lambda url, **kw: page):
                t = cantoni.text(con, "https://m3.ti.ch/x/58")
            self.assertNotIn("-->", t["testo"])
            self.assertNotIn("vecchio", t["testo"])
            self.assertNotIn("\ufeff", t["testo"])
            self.assertNotIn(" )", t["testo"])
            self.assertTrue(t["testo"].startswith("Legge\nsulle pubblicazioni ufficiali"))  # titolo spezzato su due righe
            con.close()

    def test_page_text(self):
        page = "<html><body><nav>Menu</nav><p>Intestazione</p><p>DATA ULTIMO BU 30.10.2026 > 885 Numerazione precedente</p><p>Legge nuova</p></body></html>"
        with mock.patch.object(sources, "fetch_text", lambda url, **kw: page):
            t = cantoni.page_text(885)
        self.assertTrue(t.startswith("DATA ULTIMO BU"))
        self.assertIn("Legge nuova", t)

    def test_migrazione_tabella_vecchia(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            con.execute("CREATE TABLE cantonal_acts (canton TEXT, number TEXT, title TEXT, url TEXT, pdf_url TEXT, discovered_at TEXT)")
            con.commit()
            self.assertEqual(cantoni.count(con), 0)
            self.assertIn("act_key", {r[1] for r in con.execute("PRAGMA table_info(cantonal_acts)")})
            con.close()

    def test_discover_search_text(self):
        pages = {cantoni.TICINO_HOME: self.HOME,
                 "https://m3.ti.ch/CAN/RLeggi/public/index.php/raccolta-leggi/libro/n/1": self.CAT}
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            with mock.patch.object(sources, "fetch_text", lambda url, **kw: pages.get(url, "")):
                res = cantoni.discover(con, max_pages=10)
            self.assertEqual(res["atti_trovati"], 2)  # 4 link, 2 atti: deduplicati per numero interno
            self.assertIn("/CAN/RLeggi/public/index.php/raccolta-leggi/legge-piatta/num/N", res["schemi_url"])
            hit = cantoni.search(con, "161.100")[0]
            self.assertEqual(hit["titolo"], "Legge sulle pubblicazioni ufficiali")
            self.assertIn("legge-piatta/num/58", hit["url"])  # preferita la versione piatta, ma col numero RL
            self.assertEqual(cantoni.search(con, "regolamento pubblicazioni")[0]["numero"], "161.110")
            page = b"<html><head><style>x{}</style></head><body><nav>Menu</nav><div>Regolamento sulle pubblicazioni ufficiali</div><p>Art. 1</p><p>Testo</p></body></html>"
            with mock.patch.object(sources, "fetch", lambda url, **kw: page):
                t = cantoni.text(con, cantoni.search(con, "161.110")[0]["url"])
            self.assertEqual(t["testo"], "Regolamento sulle pubblicazioni ufficiali\nArt. 1\nTesto")
            con.close()


class TestAgentSources(unittest.TestCase):
    def test_tools_route_and_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            arc = agent.Archive(con)
            with mock.patch.object(parlamento, "search_business", lambda *a, **k: [
                    {"id": 1, "numero": "23.4567", "titolo": "Mozione X", "url": "https://www.parlament.ch/x"}]):
                out = json.loads(arc.call("parlamento_cerca", {"parole": "dati"}))
            self.assertEqual(out[0]["numero"], "23.4567")
            self.assertEqual(list(arc.sources.values())[0].label, "Curia Vista 23.4567")
            # errore di rete: il modello riceve un messaggio, non un'eccezione
            with mock.patch.object(parlamento, "votes", side_effect=OSError("timeout")):
                out = json.loads(arc.call("parlamento_voti", {"parole": "dati"}))
            self.assertIn("non raggiungibile", out["errore"])
            # ticino vuoto: suggerimento invece di risultato vuoto
            out = json.loads(arc.call("cantone_cerca", {"query": "scuola"}))
            self.assertIn("indicizza-ticino", out[0]["nota"])
            con.close()

    def test_cita_come_and_canton_normalization(self):
        from nn import cantoni
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            cantoni._ensure(con)
            con.execute("INSERT INTO cantonal_acts(canton, act_key, number, title, url, pdf_url, discovered_at) "
                        "VALUES ('TI', '58', '161.100', 'Legge sulle pubblicazioni ufficiali (LPU)', 'https://m3.ti.ch/x/58', NULL, 'now')")
            con.commit()
            arc = agent.Archive(con)
            for canton in ("Ticino", "ti", "TI", None):  # il modello puo scrivere il cantone in vari modi
                out = json.loads(arc.call("cantone_cerca", {"query": "pubblicazioni ufficiali", **({"cantone": canton} if canton else {})}))
                self.assertEqual(out[0]["cita_come"], "[RL-TI 161.100]", canton)
            self.assertIn("solo il Canton Ticino", json.loads(arc.call("cantone_cerca", {"query": "x", "cantone": "ZH"}))[0]["nota"])
            # ricerca senza risultati: il modello riceve un suggerimento, non una lista vuota
            self.assertIn("Riprova", json.loads(arc.call("cantone_cerca", {"query": "inesistente parola"}))[0]["nota"])

            with mock.patch.object(giurisprudenza, "search", lambda *a, **k: [
                    {"tipo": "TF", "numero": "4A_123/2023", "data": "2024-03-12", "url": "https://www.bger.ch/x", "docid": "aza://12-03-2024-4A_123-2023"}]):
                out = json.loads(arc.call("giurisprudenza_cerca", {"query": "dati"}))
            self.assertEqual(out[0]["cita_come"], "[TF 4A_123/2023, 2024-03-12]")
            with mock.patch.object(fedlex, "upcoming_entries", lambda *a, **k: [
                    {"rs": "741.62", "titolo": "Regolamento, del Fondo", "entrata_in_vigore": "2026-11-01", "url": "https://www.fedlex.admin.ch/eli/cc/2026/1/it"}]):
                out = json.loads(arc.call("modifiche_in_arrivo", {}))
            cita = out["nuovi_atti_in_entrata_in_vigore"][0]["cita_come"]
            self.assertEqual(cita, "[Fedlex 741.62, 2026-11-01]")
            cit = agent.find_other_citations(f"Entra in vigore {cita}")[0]
            self.assertEqual((cit.label, cit.date), ("Fedlex 741.62", "2026-11-01"))
            self.assertIn(cit.label, {s.label for s in arc.sources.values()})  # la fonte e registrata: il link si risolve
            self.assertEqual(giurisprudenza.describe_docid("atf://142-III-263:it"), ("DTF", "142 III 263", ""))
            self.assertEqual(giurisprudenza.describe_docid("aza://12-03-2024-4A_123-2023"), ("TF", "4A_123/2023", "2024-03-12"))
            con.close()

    def test_canton_article_citations_resolve_to_the_act(self):
        got = [c.label for c in agent.find_other_citations(
            "[RL-TI 161.100 art. 2] e [RL-TI 161.100 art. 10; RPU art. 4] e [RL-TI 161.110]")]
        self.assertEqual(got, ["RL-TI 161.100"] * 2 + ["RL-TI 161.110"])

    def test_other_citations(self):
        cs = agent.find_other_citations("x [TF 4A_123/2023, 2024-03-12] y [DTF 145 III 225] z [Curia Vista 23.4567] [RL-TI 161.100]")
        self.assertEqual([c.label for c in cs], ["TF 4A_123/2023", "DTF 145 III 225", "Curia Vista 23.4567", "RL-TI 161.100"])
        self.assertEqual(cs[0].date, "2024-03-12")

    def test_abrogated_act_excluded_from_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            old = "https://fedlex.data.admin.ch/eli/cc/1993/1945"
            store.upsert_act(con, old, "235.1", "LPD 1992", in_force=False)
            from nn import akn
            from tests.test_nn import V1
            store.save_version(con, old, "it", "1993-07-01", "https://x/old", "c" * 64, akn.parse(V1))
            store.rebuild_search(con)
            hits = store.search(con, "organi federali")
            self.assertTrue(all(h["act_uri"] != old for h in hits))
            # l'atto in vigore vince sul numero RS
            self.assertEqual(store.find_act(con, "235.1")["uri"], "https://fedlex.data.admin.ch/eli/cc/2022/491")
            out = agent.Archive(con).leggi_articolo("235.1", "2")
            self.assertNotIn("AVVISO", out)
            con.close()


if __name__ == "__main__":
    unittest.main()
