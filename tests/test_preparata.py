"""Ricerca preparata e vettori, senza rete e senza modello: i vettori sono costruiti a mano."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from nn import preparata, store, vettori
from tests.test_agent import make_db

DIM = 8


def vettore(i: int) -> np.ndarray:
    v = np.zeros(DIM, dtype="float32")
    v[i] = 1.0
    return v


class TestVettori(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = make_db(self.tmp.name)
        self.dim = mock.patch.object(vettori, "DIM", DIM)
        self.dim.start()
        self.jsonl = Path(self.tmp.name) / "vettori" / "da-calcolare.jsonl"

    def tearDown(self):
        self.dim.stop()
        vettori._MATRICI.clear()
        self.con.close()
        self.tmp.cleanup()

    def _calcola(self, quali=None):
        """Fa il lavoro del notebook: un vettore 'unitario' per articolo (art. 1 -> asse 1, ecc.)."""
        righe = [json.loads(x) for x in self.jsonl.read_text(encoding="utf-8").splitlines()]
        righe = [d for d in righe if quali is None or d["e"] in quali]
        npz = Path(self.tmp.name) / "vettori.npz"
        np.savez(npz, r=np.asarray([d["r"] for d in righe], dtype="int64"),
                 e=np.asarray([d["e"] for d in righe], dtype="U"), h=np.asarray([d["h"] for d in righe], dtype="U"),
                 v=np.stack([vettore(int(d["e"].split("_")[1])) for d in righe]).astype("float16"))
        return npz

    def test_esporta_solo_gli_articoli_vigenti_senza_vettore(self):
        self.assertEqual(vettori.esporta(self.con, self.jsonl), 3)   # versione 2024: art. 1, 2, 3
        primo = json.loads(self.jsonl.read_text(encoding="utf-8").splitlines()[0])
        self.assertIn("RS 235.1", primo["t"])
        r = vettori.importa(self.con, self._calcola({"art_1", "art_2"}))
        self.assertEqual((r["importati"], r["totale"]), (2, 2))
        self.assertEqual(vettori.esporta(self.con, self.jsonl), 1)   # resta solo l'art. 3
        r = vettori.importa(self.con, self._calcola())
        self.assertEqual((r["importati"], r["totale"]), (1, 3))

    def test_cerca_per_vicinanza(self):
        vettori.esporta(self.con, self.jsonl)
        vettori.importa(self.con, self._calcola())
        trovati = vettori.cerca(self.con, "", vettore=vettore(2) + 0.1 * vettore(3))
        self.assertEqual([t["num"] for t in trovati][:2], ["Art. 2", "Art. 3"])

    def test_testo_cambiato_il_vettore_non_vale_piu(self):
        vettori.esporta(self.con, self.jsonl)
        npz = self._calcola()
        self.con.execute("UPDATE articles SET text_hash = 'cambiato' WHERE eid = 'art_2'")
        self.con.commit()
        r = vettori.importa(self.con, npz)
        self.assertEqual((r["importati"], r["scartati"]), (2, 1))
        self.assertNotIn("Art. 2", [t["num"] for t in vettori.cerca(self.con, "", vettore=vettore(2))])

    def test_dimensione_sbagliata_rifiutata(self):
        vettori.esporta(self.con, self.jsonl)
        npz = Path(self.tmp.name) / "x.npz"
        np.savez(npz, r=np.asarray([1]), e=np.asarray(["art_1"]), h=np.asarray(["x"]), v=np.zeros((1, 5), "float16"))
        with self.assertRaises(ValueError):
            vettori.importa(self.con, npz)

    def test_senza_file_niente_vettori(self):
        self.assertEqual(vettori.cerca(self.con, "qualcosa", vettore=vettore(1)), [])
        self.assertFalse(vettori.disponibile(self.con))


    def test_calcola_in_locale_a_blocchi(self):
        import sys, types
        class Finto:
            def __init__(self, *a, **k):
                self.max_seq_length = 0
            def encode(self, testi, **k):
                return np.stack([vettore(1 + i % 3) for i, _ in enumerate(testi)])
        modulo = types.SimpleNamespace(SentenceTransformer=Finto)
        with mock.patch.dict(sys.modules, {"sentence_transformers": modulo}), \
                mock.patch.object(vettori, "dispositivo", return_value="cpu"):
            r = vettori.calcola(self.con, blocco=2, log=lambda m: None)
            self.assertEqual((r["importati"], r["totale"]), (3, 3))
            self.assertEqual(vettori.calcola(self.con, log=lambda m: None)["importati"], 0)   # gia fatti
        self.assertEqual(vettori.esporta(self.con, self.jsonl), 0)

class TestCandidati(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = make_db(self.tmp.name)

    def tearDown(self):
        vettori._MATRICI.clear()
        self.con.close()
        self.tmp.cleanup()

    def test_solo_testo_senza_vettori(self):
        c = preparata.candidati(self.con, "A chi si applica la legge sugli organi federali?")
        self.assertEqual(c[0]["articolo"], "2")
        self.assertEqual(c[0]["da"], ["testo"])

    def test_le_parole_vuote_non_contano(self):
        self.assertEqual(preparata.parole_utili("Che cosa posso fare con la legge?"), "")

    def test_parole_di_tutti_i_giorni_diventano_termini_di_legge(self):
        p = preparata.parole_utili("Il mio capo puo licenziarmi?").split()
        self.assertEqual(p[:3], ["disdetta", "disdire", "datore"])
        self.assertIn("licenziarmi", p)

    def test_rubrica_dai_titoli_marginali(self):
        path = '["Titolo decimo: Del contratto di lavoro", "III. Protezione dalla disdetta", "2. Disdetta in tempo inopportuno"]'
        self.assertEqual(store.rubrica("", path), "III. Protezione dalla disdetta > 2. Disdetta in tempo inopportuno")
        self.assertEqual(store.rubrica("Scopo", path), "Scopo")

    def test_fusione_trovato_da_entrambe_sale(self):
        def finta(con, testo, lang=None, k=8):
            return [{"sr": "235.1", "lang": "it", "act_uri": r["act_uri"], "eid": r["eid"], "title": r["title"],
                     "num": r["num"], "heading": r["heading"], "excerpt": ""}
                    for r in con.execute("SELECT * FROM search WHERE eid IN ('art_3', 'art_2') ORDER BY eid DESC")]
        with mock.patch.object(vettori, "cerca", finta):
            c = preparata.candidati(self.con, "organi federali")
        self.assertEqual(c[0]["articolo"], "2")
        self.assertEqual(sorted(c[0]["da"]), ["testo", "vettori"])
        self.assertIn("3", [x["articolo"] for x in c])

    def test_un_errore_dei_vettori_non_ferma(self):
        with mock.patch.object(vettori, "cerca", side_effect=RuntimeError("rotto")):
            self.assertTrue(preparata.candidati(self.con, "organi federali"))


    def test_prima_la_legge_generale(self):
        d = "Il datore di lavoro puo licenziarmi mentre sono in malattia?"
        self.assertEqual(preparata.tipo_atto("220", "Legge federale di complemento del Codice civile", d), 2)
        self.assertEqual(preparata.tipo_atto("172.220.111.3", "Ordinanza sul personale federale", d), -3)
        self.assertEqual(preparata.tipo_atto("172.220.111.3", "Ordinanza sul personale federale",
                                             "Sono impiegato della Confederazione e sono malato"), 0)
        self.assertEqual(preparata.tipo_atto("834.1", "Legge federale sulle indennita di perdita di guadagno", d), 1)

class TestInfomaniak(unittest.TestCase):
    def test_encode_a_lotti_con_istruzione_per_le_domande(self):
        import io
        from nn import embedding_infomaniak as emb
        inviati = []

        def risposta(req, timeout=0):
            corpo = json.loads(req.data)
            inviati.append(corpo)
            dati = {"data": [{"index": i, "embedding": [3.0, 4.0]} for i in range(len(corpo["input"]))],
                    "usage": {"total_tokens": 5}}
            r = io.BytesIO(json.dumps(dati).encode())
            r.__enter__ = lambda *a: r
            r.__exit__ = lambda *a: None
            return r
        with mock.patch("urllib.request.urlopen", side_effect=risposta):
            enc = emb.Infomaniak("bge_multilingual_gemma2", token="t", product_id="1", per_richiesta=2)
            v = enc.encode(["a", "b", "c"])
            q = enc.encode(["domanda"], domanda=True)
        self.assertEqual([len(x["input"]) for x in inviati], [2, 1, 1])
        self.assertTrue(inviati[-1]["input"][0].startswith("<instruct>"))
        self.assertFalse(inviati[0]["input"][0].startswith("<instruct>"))
        self.assertAlmostEqual(float(v[0][0]), 0.6, places=5)   # normalizzato: (3,4)/5
        self.assertEqual(enc.token_usati, 15)
        self.assertEqual(q.shape, (1, 2))

    def test_senza_credenziali_errore_chiaro(self):
        from nn import embedding_infomaniak as emb
        with mock.patch.dict("os.environ", {"INFOMANIAK_API_TOKEN": "", "INFOMANIAK_PRODUCT_ID": ""}), \
                mock.patch("nn.ai.load_env"):
            with self.assertRaises(RuntimeError):
                emb.Infomaniak("bge_multilingual_gemma2")


if __name__ == "__main__":
    unittest.main()
