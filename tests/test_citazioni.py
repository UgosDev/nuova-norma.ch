"""Riferimenti leggibili: divisione dell'articolo, parte citata, vigenza e route /nn/citazione (senza rete)."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nn import citazioni, cli, store, web
from nn.akn import ActText, Article

URI = "https://fedlex.data.admin.ch/eli/cc/27/317_321_377"
T336C = ("1 Dopo il tempo di prova, il datore di lavoro non può disdire il rapporto di lavoro:\n"
         "a. allorquando il lavoratore presta servizio obbligatorio;\n"
         "b. allorquando il lavoratore è impedito di lavorare a causa di malattia o infortunio non imputabili a sua colpa;\n"
         "c bis. prima del termine del congedo di maternità prolungato;\n"
         "2 La disdetta data durante uno dei periodi stabiliti nel capoverso 1 è nulla.\n"
         "3 Se per la cessazione vale un giorno fisso, questo è protratto.")


def _db(tmp: str, testi: dict[str, str]) -> Path:
    """Archivio con il CO in tre versioni: date -> testo dell'art. 336c (None = articolo assente)."""
    path = Path(tmp) / "db.sqlite"
    con = store.connect(path)
    store.upsert_act(con, URI, "220", "Codice delle obbligazioni")
    for d, t in testi.items():
        arts = [Article("art_335_c", "Art. 335 c", "", "1 Il rapporto di lavoro può essere disdetto per la fine di un mese.",
                        ["Contratto di lavoro", "Termini di disdetta"])]
        if t is not None:
            arts.append(Article("art_336_c", "Art. 336 c", "", t,
                                ["Contratto di lavoro", "Protezione dalla disdetta", "Disdetta in tempo inopportuno"]))
        store.save_version(con, URI, "it", d, f"https://x/{d}.xml", "x", ActText("CO", "CO", arts))
    con.close()
    return path


class TestDividi(unittest.TestCase):
    def test_capoversi_e_lettere(self):
        r = citazioni.dividi(T336C)
        self.assertEqual([x["sigla"] for x in r], ["1", "a.", "b.", "c bis.", "2", "3"])
        self.assertEqual([x["livello"] for x in r], [0, 1, 1, 1, 0, 0])
        self.assertEqual(r[3]["lett"], "cbis")
        self.assertEqual(r[2]["cpv"], "1")
        self.assertTrue(r[0]["testo"].startswith("Dopo il tempo di prova"))

    def test_numeri_dentro_una_lettera(self):
        r = citazioni.dividi("1 Sono puniti i privati che:\na. violano gli obblighi;\nb. omettono:\n1. di informare,\n2. di fornire.")
        self.assertEqual([x["livello"] for x in r], [0, 1, 1, 2, 2])
        self.assertEqual(r[4]["lett"], "b")

    def test_articolo_senza_capoversi(self):
        r = citazioni.dividi("La presente legge ha lo scopo di proteggere la personalità.")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["sigla"], "")


class TestSegna(unittest.TestCase):
    def test_per_parte(self):
        r = citazioni.segna(citazioni.dividi(T336C), parte="cpv. 1 lett. b")
        self.assertEqual([x["sigla"] for x in r if x["citata"]], ["b."])
        self.assertTrue(r[0]["contesto"])   # l'attacco del capoverso accompagna la lettera
        r = citazioni.segna(citazioni.dividi(T336C), parte="cpv. 2")
        self.assertEqual([x["sigla"] for x in r if x["citata"]], ["2"])
        self.assertEqual(citazioni.parse_parte("Abs. 3 Bst. a"), ("3", "a"))

    def test_per_passaggi_letti(self):
        passo = ("b. allorquando il lavoratore è impedito di lavorare a causa di malattia o infortunio non imputabili "
                 "a sua colpa;\n2 La disdetta data durante uno dei periodi stabiliti nel capoverso 1 è nulla.")
        r = citazioni.segna(citazioni.dividi(T336C), passi=[passo])
        self.assertEqual([x["sigla"] for x in r if x["citata"]], ["b.", "2"])

    def test_passaggio_troncato(self):
        r = citazioni.segna(citazioni.dividi(T336C), passi=["Art. 336c 3 Se per la cessazione vale un giorno fisso, questo"])
        self.assertEqual([x["sigla"] for x in r if x["citata"]], ["3"])

    def test_cita(self):
        self.assertEqual(citazioni.parse_cita("[RS 220 art. 336c, 2026-10-01]"), ("220", "336c", "2026-10-01"))
        self.assertEqual(citazioni.parse_cita("[RS 235.1 art. 6]"), ("235.1", "6", ""))
        self.assertIsNone(citazioni.parse_cita("[TF 4A_631/2014, 2015-11-25]"))


class TestScheda(unittest.TestCase):
    def test_vigenza_e_modifica_in_arrivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = store.connect(_db(tmp, {"2021-01-01": "1 Vecchio testo.", "2024-01-01": T336C,
                                          "2026-10-01": T336C, "2027-07-01": T336C + "\n4 Nuovo capoverso."}))
            s = citazioni.scheda(con, cita="[RS 220 art. 336c, 2026-10-01]", parte="cpv. 1 lett. b", oggi="2026-11-02")
            con.close()
        self.assertEqual(s["eid"], "art_336_c")
        self.assertEqual(s["versione"], "2026-10-01")
        self.assertEqual(s["vigore_dal"], "2024-01-01")
        self.assertEqual(s["futura"], "2027-07-01")
        self.assertEqual(s["cambiato_il"], "")
        self.assertEqual(s["versioni"], 3)
        self.assertTrue(s["parte_trovata"])
        self.assertTrue(s["estratto"].startswith("b. allorquando"))
        self.assertEqual(s["originale"], "https://www.fedlex.admin.ch/eli/cc/27/317_321_377/it#art_336_c")
        self.assertIn("eid=art_336_c", s["nn"])

    def test_citazione_di_una_versione_superata(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = store.connect(_db(tmp, {"2021-01-01": "1 Vecchio testo.", "2024-01-01": T336C}))
            s = citazioni.scheda(con, cita="[RS 220 art. 336c, 2022-05-01]", oggi="2026-11-02")
            con.close()
        self.assertEqual(s["versione"], "2021-01-01")
        self.assertEqual(s["cambiato_il"], "2024-01-01")
        self.assertFalse(s["parte_trovata"])
        self.assertEqual(s["estratto"], "1 Vecchio testo.")

    def test_impronta_diversa_e_abrogato(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = store.connect(_db(tmp, {"2024-01-01": T336C, "2025-01-01": None}))
            s = citazioni.scheda(con, cita="[RS 220 art. 336c, 2024-06-01]", impronta="abc", oggi="2026-11-02")
            uguale = citazioni.scheda(con, cita="[RS 220 art. 336c, 2024-06-01]", oggi="2026-11-02",
                                      impronta=citazioni.impronta_testo(T336C))
            assente = citazioni.scheda(con, cita="[RS 220 art. 999]")
            altra = citazioni.scheda(con, cita="[RS 999 art. 1]")
            con.close()
        self.assertEqual(s["abrogato_il"], "2025-01-01")
        self.assertTrue(s["diversa"])
        self.assertFalse(uguale["diversa"])
        self.assertIsNone(assente)
        self.assertIsNone(altra)

    def test_per_uri_ed_eid(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = store.connect(_db(tmp, {"2024-01-01": T336C}))
            s = citazioni.scheda(con, uri=URI, eid="art_335_c", lingua="it")
            con.close()
        self.assertEqual(s["num"], "Art. 335 c")


class _Finto:
    """Il minimo di BaseHTTPRequestHandler che serve a serve_static."""
    def __init__(self, path):
        self.path, self.wfile, self.stato, self.intestazioni = path, io.BytesIO(), None, {}

    def send_response(self, s):
        self.stato = s

    def send_header(self, k, v):
        self.intestazioni[k] = v

    def end_headers(self):
        pass


class TestRoute(unittest.TestCase):
    def test_json_e_script(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(cli, "DB", _db(tmp, {"2024-01-01": T336C})):
            h = _Finto("/nn/citazione?cita=%5BRS%20220%20art.%20336c%2C%202024-01-01%5D&parte=cpv.%202")
            self.assertTrue(web.serve_static(h, "/nn/citazione"))
            self.assertEqual(h.stato, 200)
            d = json.loads(h.wfile.getvalue())
            self.assertEqual([r["sigla"] for r in d["righe"] if r["citata"]], ["2"])
            h = _Finto("/nn/citazione?cita=%5BRS%20220%20art.%20999%5D")
            web.serve_static(h, "/nn/citazione")
            self.assertEqual(h.stato, 404)
        h = _Finto("/nn/citazioni.js")
        self.assertTrue(web.serve_static(h, "/nn/citazioni.js"))
        self.assertIn(b"NNCitazioni", h.wfile.getvalue())

    def test_riferimenti_della_risposta_portano_i_dati(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = store.connect(_db(tmp, {"2024-01-01": T336C}))
            html = web._render_answer(con, "Vedi [RS 220 art. 336c, 2024-01-01].", "it")
            pagina = web._page("Prova", "x").decode()
            con.close()
        self.assertIn('data-nn-eid="art_336_c"', html)
        self.assertIn('data-nn-uri="' + URI + '"', html)
        self.assertIn("/nn/citazioni.js", pagina)
        self.assertIn(".nn-bolla", web.CSS)


if __name__ == "__main__":
    unittest.main()
