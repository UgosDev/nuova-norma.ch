import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nn import agent, akn, formati, giurisprudenza, store
from nn.formati import (Affermazione, Collegamento, Domanda, Dossier, Lacuna, Passaggio, Registro,
                        calcola_punteggio, controlla_affermazione, controlla_collegamento, controlla_domanda,
                        controlla_dossier, fascia, vista)
from tests.test_agent import URI, V2, make_db

OGGI = "2026-10-31"


def registro_con_fonti():
    reg = Registro(OGGI)
    vig = reg.registra(tipo="articolo", citazione="[RS 220 art. 266c, 2026-10-01]", testo="testo vigente",
                       vigenza="2026-10-01", aperta_da="passo4:d1")
    fut = reg.registra(tipo="articolo", citazione="[RS 220 art. 336c, 2027-07-01]", testo="testo futuro",
                       vigenza="2027-07-01", aperta_da="passo4:d2")
    con_futura = reg.registra(tipo="articolo", citazione="[RS 220 art. 336c, 2026-10-01]", testo="testo",
                              vigenza="2026-10-01", versione_futura="2027-07-01", aperta_da="passo4:d2")
    ti = reg.registra(tipo="legge_cantonale", citazione="[RL-TI 161.100]", testo="legge", aperta_da="passo4:d3")
    return reg, vig, fut, con_futura, ti


def affermazione(**kw):
    base = dict(id="a1", testo="La disdetta della locazione di un'abitazione richiede tre mesi di preavviso.",
                tipo="norma", istituto="locazione di abitazione", ordinamento="CH", data_riferimento=OGGI, fonti=["f1"])
    base.update(kw)
    return Affermazione(**base)


class TestPunteggio(unittest.TestCase):
    def test_punteggio_e_fasce(self):
        tutto_si = {k: "si" for k in formati.CRITERI}
        self.assertEqual(calcola_punteggio(tutto_si), 100)
        self.assertEqual(calcola_punteggio({}), 0)
        self.assertEqual(calcola_punteggio({"pertinenza": "in_parte", "utilita": "si"}), 40)
        self.assertEqual([fascia(p) for p in (0, 29, 30, 49, 50, 100)],
                         ["scartata", "scartata", "marchiata", "marchiata", "accettata", "accettata"])
        # sbarramento: utilita "no" non passa mai come accettata
        quasi = {"pertinenza": "in_parte", "utilita": "no", "perimetro": "si", "non_presuppone": "si", "non_duplica": "si"}
        self.assertEqual(calcola_punteggio(quasi), 49)   # sarebbe 60
        self.assertEqual(fascia(calcola_punteggio(quasi)), "marchiata")
        self.assertEqual(fascia(calcola_punteggio(dict(quasi, pertinenza="no"))), "scartata")
        with self.assertRaises(ValueError):
            calcola_punteggio({"pertinenza": "forse"})
        with self.assertRaises(ValueError):
            calcola_punteggio({"simpatia": "si"})

    def test_domanda_valutata_dal_codice(self):
        d = Domanda("d1", "Quale preavviso vale per la locazione di un'abitazione?", asse="che cosa")
        d.valuta({"pertinenza": "si", "utilita": "in_parte"})
        self.assertEqual((d.punteggio, d.fascia, d.marchiata), (43, "marchiata", True))
        self.assertTrue(controlla_domanda(d).ok)
        d.fascia = "accettata"  # un modello non puo cambiare la fascia: il codice se ne accorge
        self.assertFalse(controlla_domanda(d).ok)

    def test_controlli_domanda(self):
        self.assertIn("non e una domanda", controlla_domanda(Domanda("d1", "Verifica l'art. 266c")).errori[0])
        d = Domanda("d2", "Chi?", squadre=["federale", "giurisprudenza", "cantone"])
        self.assertTrue(any("piu di 2 squadre" in e for e in controlla_domanda(d).errori))
        d = Domanda("d3", "Chi?", squadre=["notai"])
        self.assertTrue(any("squadra sconosciuta" in e for e in controlla_domanda(d).errori))
        d = Domanda("d4", "Chi?", squadre=["federale"])
        d.valuta({})
        self.assertTrue(any("scartata non va assegnata" in e for e in controlla_domanda(d).errori))


class TestVista(unittest.TestCase):
    def test_campi_nascosti(self):
        d = Domanda("d1", "Chi?", origine="avvocato")
        for passo in range(1, 11):
            self.assertNotIn("origine", vista(d, passo))  # l'avvocato del diavolo non si riconosce mai
        a = affermazione(domanda="d1", marchio=True)
        self.assertIn("domanda", vista(a, 5))
        self.assertNotIn("marchio", vista(a, 5))
        for passo in (6, 7):
            v = vista(a, passo)
            self.assertNotIn("domanda", v)
            self.assertNotIn("marchio", v)
        self.assertIn("marchio", vista(a, 8))  # la ricomposizione deve mostrare l'incertezza


class TestRegistro(unittest.TestCase):
    def test_registra_e_riapre(self):
        reg = Registro(OGGI)
        a = reg.registra(tipo="articolo", citazione="[RS 235.1 art. 24, 2025-07-07]", testo="abc",
                         vigenza="2025-07-07", aperta_da="passo4:d1")
        b = reg.registra(tipo="articolo", citazione="[RS 235.1 art. 24, 2025-07-07]", testo="abc",
                         vigenza="2025-07-07", aperta_da="passo6:a3")
        self.assertIs(a, b)
        self.assertEqual(len(reg), 1)
        self.assertEqual(a.aperta_da, ["passo4:d1", "passo6:a3"])
        self.assertEqual(len(a.impronta), 64)
        self.assertIs(reg.per_citazione("[RS 235.1 art. 24, 2025-07-07]"), a)
        with self.assertRaises(ValueError):
            reg.registra(tipo="blog", citazione="x")

    def test_salva_e_carica(self):
        reg, *_ = registro_con_fonti()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            reg.salva(path)
            copia = Registro.carica(path)
        self.assertEqual(copia.oggi, OGGI)
        self.assertEqual([v.citazione for v in copia.voci.values()], [v.citazione for v in reg.voci.values()])
        self.assertEqual(copia.registra(tipo="legge_cantonale", citazione="[RL-TI 161.100]").id, "f4")  # riconosciuta


class TestCancelloAffermazioni(unittest.TestCase):
    def setUp(self):
        self.reg, self.vig, self.fut, self.con_futura, self.ti = registro_con_fonti()

    def test_affermazione_valida(self):
        c = controlla_affermazione(affermazione(), self.reg)
        self.assertTrue(c.ok, c.errori)

    def test_campi_obbligatori(self):
        c = controlla_affermazione(affermazione(istituto="", ordinamento="Svizzera", fonti=[]), self.reg)
        self.assertEqual(len(c.errori), 3)
        lacuna = Affermazione("a9", "Nessuna fonte di dottrina disponibile.", "lacuna", data_riferimento=OGGI)
        self.assertTrue(controlla_affermazione(lacuna, self.reg).ok)
        self.assertFalse(controlla_affermazione(affermazione(tipo="opinione"), self.reg).ok)

    def test_fonte_non_aperta(self):
        c = controlla_affermazione(affermazione(fonti=["f99"]), self.reg)
        self.assertIn("citata senza essere stata aperta", c.errori[0])

    def test_versione_futura_non_e_vigente(self):
        c = controlla_affermazione(affermazione(fonti=[self.fut.id]), self.reg)
        self.assertTrue(any("non ancora in vigore" in e for e in c.errori))
        c = controlla_affermazione(affermazione(fonti=[self.con_futura.id]), self.reg)
        self.assertTrue(c.ok)
        self.assertTrue(any("versione futura dal 2027-07-01" in a for a in c.avvisi))
        self.assertFalse(controlla_affermazione(affermazione(data_riferimento="2027-07-01"), self.reg).ok)

    def test_modifica_in_arrivo(self):
        ok = affermazione(tipo="modifica_in_arrivo", data_riferimento="2027-07-01", fonti=[self.con_futura.id])
        self.assertTrue(controlla_affermazione(ok, self.reg).ok)
        no = affermazione(tipo="modifica_in_arrivo", fonti=[self.vig.id])
        self.assertTrue(any("senza una fonte con data futura" in e for e in controlla_affermazione(no, self.reg).errori))

    def test_legge_cantonale_senza_data(self):
        c = controlla_affermazione(affermazione(ordinamento="TI", istituto="pubblicazioni ufficiali", fonti=[self.ti.id]), self.reg)
        self.assertTrue(c.ok)
        self.assertTrue(any("non verificabile" in a for a in c.avvisi))

    def test_contestata(self):
        a = affermazione(esito="contestata")
        self.assertTrue(any("senza lettura alternativa" in e for e in controlla_affermazione(a, self.reg).errori))
        a.alternativa = {"testo": "Il preavviso e di sei mesi.", "fonti": ["f99"]}
        self.assertTrue(any("alternativa f99" in e for e in controlla_affermazione(a, self.reg).errori))
        a.alternativa["fonti"] = [self.vig.id]
        self.assertTrue(controlla_affermazione(a, self.reg).ok)
        self.assertFalse(controlla_affermazione(affermazione(esito="forse"), self.reg).ok)
        self.assertFalse(controlla_affermazione(affermazione(sezione="varie"), self.reg).ok)


class TestCancelloDossierECollegamenti(unittest.TestCase):
    def test_dossier(self):
        reg, vig, *_ = registro_con_fonti()
        d = Dossier("d1", ["federale"], [vig.id], [Passaggio(vig.id, "tre mesi")], lacune=[])
        self.assertTrue(controlla_dossier(d, reg).ok)
        self.assertIn("lacune non dichiarate", controlla_dossier(Dossier("d1", fonti=[vig.id]), reg).errori[0])
        vuoto = controlla_dossier(Dossier("d2", lacune=[]), reg)
        self.assertTrue(any("nessuna fonte e nessuna lacuna" in e for e in vuoto.errori))
        senza_risultati = Dossier("d3", lacune=[Lacuna("nessuna sentenza trovata", "non_trovato")], stato="parziale")
        self.assertTrue(controlla_dossier(senza_risultati, reg).ok)
        errato = Dossier("d4", squadre=["a", "b", "c"], fonti=["f99"], passaggi=[Passaggio("f1", "x")],
                         lacune=[Lacuna("x", "pigrizia")], stato="boh")
        self.assertEqual(len(controlla_dossier(errato, reg).errori), 5)

    def test_collegamenti(self):
        ids = {"a1", "a2"}
        self.assertTrue(controlla_collegamento(Collegamento("a1", "a2", "eccezione_di"), ids).ok)
        self.assertEqual(len(controlla_collegamento(Collegamento("a1", "a1", "simile"), ids).errori), 2)
        self.assertFalse(controlla_collegamento(Collegamento("a1", "a9", "limita"), ids).ok)

    def test_da_dict_ignora_campi_in_piu(self):
        d = formati.da_dict(Dossier, {"domanda": "d1", "fonti": ["f1"], "commento": "extra",
                                      "passaggi": [{"fonte": "f1", "testo": "x", "voto": 3}],
                                      "lacune": [{"descrizione": "y", "motivo": "non_trovato"}]})
        self.assertIsInstance(d.passaggi[0], Passaggio)
        self.assertIsInstance(d.lacune[0], Lacuna)
        a = formati.da_dict(Affermazione, json.loads('{"id":"a1","testo":"t","tipo":"norma","fiducia":0.9}'))
        self.assertEqual(a.id, "a1")


class TestArchivioScriveNelRegistro(unittest.TestCase):
    def test_strumenti_annotano_le_fonti_aperte(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            store.save_version(con, URI, "it", "2999-01-01", "https://x/3", "c" * 64, akn.parse(V2))
            reg = Registro()
            arc = agent.Archive(con, registro=reg, chi="passo4:d1")
            json.loads(arc.call("leggi_articolo", {"rs": "235.1", "articolo": "3"}))
            arc.call("cerca_articoli", {"query": "articolo"})  # una ricerca non e un'apertura
            self.assertEqual(len(reg), 1)
            voce = next(iter(reg.voci.values()))
            self.assertEqual(voce.tipo, "articolo")
            self.assertEqual(voce.citazione, "[RS 235.1 art. 3, 2024-03-01]")
            self.assertEqual((voce.vigenza, voce.versione_futura), ("2024-03-01", "2999-01-01"))
            self.assertEqual(voce.aperta_da, ["passo4:d1"])
            self.assertTrue(voce.url.startswith("https://www.fedlex.admin.ch/"))

            arc.chi = "passo6:a1"  # lo stesso articolo riaperto da un altro passo: una sola voce
            arc.call("leggi_articolo", {"rs": "235.1", "articolo": "3"})
            self.assertEqual(len(reg), 1)
            self.assertEqual(voce.aperta_da, ["passo4:d1", "passo6:a1"])

            with mock.patch.object(giurisprudenza, "decision_text",
                                   lambda docid, lang: {"docid": docid, "url": "https://www.bger.ch/x", "testo": "sentenza"}):
                arc.call("giurisprudenza_leggi", {"docid": "aza://12-03-2024-4A_123-2023"})
            tf = reg.per_citazione("[TF 4A_123/2023, 2024-03-12]")
            self.assertIsNotNone(tf)
            self.assertEqual((tf.tipo, tf.vigenza), ("sentenza", "2024-03-12"))

            # l'agente attuale funziona anche senza registro
            self.assertIn("testo", json.loads(agent.Archive(con).call("leggi_articolo", {"rs": "235.1", "articolo": "3"})))
            con.close()


if __name__ == "__main__":
    unittest.main()
