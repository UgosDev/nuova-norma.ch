"""Test senza rete: XML Akoma Ntoso di esempio con la stessa struttura dei file Fedlex."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from nn import akn, cli, diff, fedlex, store, web

NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"


def make_xml(art2_text: str, with_art3: bool, art1_note: str) -> bytes:
    art3 = (
        '<article eId="art_3"><num><b>Art. 3</b></num><heading>Nuovo</heading>'
        '<paragraph eId="art_3/para_1"><content><p>Testo del nuovo articolo.</p></content></paragraph></article>'
        if with_art3 else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<akomaNtoso xmlns="{NS}"><act name="LPD">
<preface><p><docTitle>Legge federale sulla protezione dei dati</docTitle>
<shortTitle>(LPD)</shortTitle></p></preface>
<body>
<chapter eId="chp_1"><num>Capitolo 1:</num><heading>Disposizioni generali</heading>
 <article eId="art_1"><num><b>Art. 1</b></num><heading>Scopo</heading>
  <paragraph eId="art_1/para_1"><content><p>La presente legge ha lo scopo di proteggere
   la personalità.<authorialNote marker="1"><p>{art1_note}</p></authorialNote></p></content></paragraph>
 </article>
 <article eId="art_2"><num><b>Art. 2</b></num><heading>Campo d'applicazione</heading>
  <paragraph eId="art_2/para_1"><num>1</num><content><p>{art2_text}</p></content></paragraph>
  <paragraph eId="art_2/para_2"><num>2</num><content><p>Non si applica:</p>
   <blockList><item><num>a.</num><p>ai trattamenti personali;</p></item>
   <item><num>b.</num><p>alle Camere federali.</p></item></blockList></content></paragraph>
 </article>
 {art3}
</chapter>
</body></act></akomaNtoso>""".encode()


V1 = make_xml("La legge si applica ai privati.", False, "RU 2022 491")
V2 = make_xml("La legge si applica ai privati e agli organi federali.", True, "RU 2023 100")


class TestParse(unittest.TestCase):
    def test_structure(self):
        act = akn.parse(V1)
        self.assertEqual(act.title, "Legge federale sulla protezione dei dati")
        self.assertEqual([a.eid for a in act.articles], ["art_1", "art_2"])
        a1, a2 = act.articles
        self.assertEqual(a1.num, "Art. 1")
        self.assertEqual(a1.heading, "Scopo")
        self.assertEqual(a1.path, ["Capitolo 1: Disposizioni generali"])
        self.assertIn("proteggere la personalità.", a1.text)
        self.assertNotIn("RU 2022", a1.text)  # le note restano fuori dal testo
        self.assertEqual(a1.notes, ["RU 2022 491"])
        self.assertIn("\na. ai trattamenti personali;\nb.", a2.text)  # una voce per riga
        self.assertNotIn("proteggere\n", a1.text)  # gli a capo del file XML non contano
        self.assertTrue(a2.text.startswith("1 La legge si applica"))

    def test_spazi_punteggiatura(self):
        # Fedlex mette i termini definiti in corsivo: "<i>dati personali</i> : tutte le informazioni"
        self.assertEqual(akn.normalize("a. dati personali : tutte ( FF 2023 84 ; RU 2024 )"),
                         "a. dati personali: tutte (FF 2023 84; RU 2024)")


class TestDiff(unittest.TestCase):
    def test_compare(self):
        changes = diff.compare(akn.parse(V1).articles, akn.parse(V2).articles)
        kinds = {c.eid: c.kind for c in changes}
        # art_1 cambia solo nella nota: non deve risultare modificato
        self.assertEqual(kinds, {"art_2": "modificato", "art_3": "aggiunto"})
        wd = next(c for c in changes if c.eid == "art_2").word_diff()
        self.assertIn("{+e agli organi federali+}", wd)

    def test_repeal(self):
        old = [akn.Article("art_9", "Art. 9", "X", "Testo in vigore.")]
        new = [akn.Article("art_9", "Art. 9", "X", "Abrogato")]
        self.assertEqual(diff.compare(old, new)[0].kind, "abrogato")
        self.assertEqual(diff.compare(old, [])[0].kind, "abrogato")


class TestRiferimenti(unittest.TestCase):
    def test_parse_ref(self):
        self.assertEqual(web.parse_ref("Art. 958f"), (None, "958f"))
        self.assertEqual(web.parse_ref("220 art. 958f"), ("220", "958f"))
        self.assertEqual(web.parse_ref("RS 235.1"), ("235.1", None))
        self.assertEqual(web.parse_ref("ciao"), (None, None))


class TestImportOffline(unittest.TestCase):
    """Import completo con Fedlex simulato: SPARQL e download sostituiti."""

    def test_end_to_end(self):
        uri = "https://fedlex.data.admin.ch/eli/cc/2022/491"
        files = {
            "https://x/v1.xml": V1,
            "https://x/v2.xml": V2,
        }

        old = "https://fedlex.data.admin.ch/eli/cc/1993/1945_1945_1945"

        def fake_sparql(q):
            if "jolux:title ?title" in q and "LIMIT 1" in q:
                return [{"title": "Legge federale sulla protezione dei dati" if uri in q else "LPD 1992"}]
            if "historicalLegalId" in q:
                # stesso numero RS per la legge abrogata e per quella nuova
                return [{"ca": old, "status": "https://fedlex.data.admin.ch/vocabulary/enforcement-status/3",
                         "entry": "1993-07-01"},
                        {"ca": uri, "status": "https://fedlex.data.admin.ch/vocabulary/enforcement-status/0",
                         "entry": "2023-09-01"}]
            xml = "http://publications.europa.eu/resource/authority/file-type/XML"
            pdf = "http://publications.europa.eu/resource/authority/file-type/PDF"
            return [
                {"cons": uri + "/20230901", "date": "2023-09-01", "fmt": pdf, "url": "https://x/v1.pdf"},
                {"cons": uri + "/20230901", "date": "2023-09-01", "fmt": xml, "url": "https://x/v1.xml"},
                {"cons": uri + "/20240301", "date": "2024-03-01", "fmt": xml, "url": "https://x/v2.xml"},
            ]

        def fake_http(req, timeout=60, retries=3):
            return files[req.full_url]

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(cli, "DB", Path(tmp) / "db.sqlite"), \
                mock.patch.object(cli, "RAW", Path(tmp) / "raw"), \
                mock.patch.object(fedlex, "sparql", fake_sparql), \
                mock.patch.object(fedlex, "_http", fake_http):
            out = io.StringIO()
            with redirect_stdout(out):
                cli.main(["importa", "235.1"])
                cli.main(["importa", "235.1"])  # seconda volta: niente da scaricare
                cli.main(["differenze", "235.1"])
                cli.main(["articolo", "235.1", "Art. 2"])
            text = out.getvalue()
            self.assertIn("Fatto: 2 nuove versioni", text)
            self.assertIn(f"-> 2023-09-01  {uri}", text)  # scelta la nLPD, non la LPD del 1992
            self.assertIn("Fatto: 0 nuove versioni, 2 gia presenti", text)
            self.assertIn("[MODIFICATO] Art. 2", text)
            self.assertIn("[AGGIUNTO] Art. 3 Nuovo", text)
            self.assertIn("Capitolo 1: Disposizioni generali", text)
            # le pagine dell'interfaccia si generano senza errori
            con = store.connect(cli.DB)
            try:
                self.assertIn(b"Legge federale", web.home(con))
                self.assertIn(b"cosa cambia rispetto al 2023-09-01", web.act_page(con, uri, "it"))
                page = web.diff_page(con, uri, "it", "2023-09-01", "2024-03-01").decode()
                self.assertIn("<ins>e agli organi federali</ins>", page)
                self.assertIn("1 modificato, 1 nuovo", page)
                self.assertIn(b"compare nel testo", web.article_page(con, uri, "it", "art_3"))
                self.assertIn(b"Nessuna versione", web.act_page(con, uri, "de"))
                self.assertEqual(web.find_article(con, uri, "it", "2"), "art_2")
                self.assertIsNone(web.find_article(con, uri, "it", "958f"))
            finally:
                con.close()
            # rielaborazione dai file originali, senza rete
            out2 = io.StringIO()
            with redirect_stdout(out2):
                cli.main(["rielabora"])
            self.assertIn("Rielaborate 2 versioni (0 senza file originale)", out2.getvalue())
            # archivio grezzo: un file per contenuto, nome = impronta SHA-256
            self.assertEqual(len(list((Path(tmp) / "raw").glob("*.xml"))), 2)


if __name__ == "__main__":
    unittest.main()
