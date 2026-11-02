"""Velocita senza perdere capacita: WAL, memoria delle fonti dal vivo, leggi dall'archivio, indice per atto."""

import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from nn import agent, akn, cache_rete, cli, fedlex, giurisprudenza, store
from tests.test_agent import URI, make_db
from tests.test_nn import V1

URI2 = "https://fedlex.data.admin.ch/eli/cc/1999/999"


class TestWal(unittest.TestCase):
    def test_archivio_su_file_in_wal(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = store.connect(Path(tmp) / "db.sqlite")
            modo = con.execute("PRAGMA journal_mode").fetchone()[0].lower()
            con.close()
            # dove il file system non lo permette SQLite resta nel modo precedente: e accettato
            self.assertIn(modo, ("wal", "delete"))

    def test_wal_disattivabile(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"NN_WAL": "0"}):
            con = store.connect(Path(tmp) / "db.sqlite")
            self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0].lower(), "delete")
            con.close()


class TestCacheRete(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = store.connect(Path(self.tmp.name) / "db.sqlite")

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_seconda_volta_dalla_memoria(self):
        fn = mock.Mock(return_value=[{"numero": "4A_1/2020"}])
        a = cache_rete.ricorda(self.con, "tf", 7, fn, "disdetta", "it")
        b = cache_rete.ricorda(self.con, "tf", 7, fn, "disdetta", "it")
        self.assertEqual(a, b)
        self.assertEqual(fn.call_count, 1)
        cache_rete.ricorda(self.con, "tf", 7, fn, "disdetta", "de")   # argomenti diversi: nuova chiamata
        self.assertEqual(fn.call_count, 2)

    def test_vuoti_ed_errori_non_si_conservano(self):
        vuota = mock.Mock(return_value=[])
        cache_rete.ricorda(self.con, "tf", 7, vuota, "x")
        cache_rete.ricorda(self.con, "tf", 7, vuota, "x")
        self.assertEqual(vuota.call_count, 2)
        rotta = mock.Mock(side_effect=OSError("rete"))
        for _ in range(2):
            with self.assertRaises(OSError):
                cache_rete.ricorda(self.con, "tf", 7, rotta, "y")
        self.assertEqual(rotta.call_count, 2)

    def test_scadenza(self):
        fn = mock.Mock(return_value={"testo": "t"})
        cache_rete.ricorda(self.con, "tf", 1, fn, "z")
        self.con.execute("UPDATE cache_rete SET salvato = ?", (time.time() - 2 * 86400,))
        self.con.commit()
        cache_rete.ricorda(self.con, "tf", 1, fn, "z")
        self.assertEqual(fn.call_count, 2)

    def test_disattivabile(self):
        fn = mock.Mock(return_value={"a": 1})
        with mock.patch.dict(os.environ, {"NN_CACHE_RETE": "0"}):
            cache_rete.ricorda(self.con, "tf", 7, fn, "w")
            cache_rete.ricorda(self.con, "tf", 7, fn, "w")
        self.assertEqual(fn.call_count, 2)

    def test_non_chiude_la_transazione_di_chi_chiama(self):
        self.con.execute("INSERT INTO acts(uri, sr_number, title) VALUES ('u', '1', 't')")
        cache_rete.ricorda(self.con, "tf", 7, mock.Mock(return_value={"a": 1}), "v")
        self.assertTrue(self.con.in_transaction)
        self.con.rollback()
        self.assertIsNone(store.find_act(self.con, "u"))

    def test_sentenza_dalla_memoria_resta_citabile(self):
        arch = agent.Archive(self.con)
        testo = {"url": "https://www.bger.ch/x", "testo": "considerando"}
        with mock.patch.object(giurisprudenza, "decision_text", return_value=testo) as dal_vivo:
            arch.giurisprudenza_leggi("aza://01-02-2020-4A_1-2020")
            arch2 = agent.Archive(self.con)
            d = arch2.giurisprudenza_leggi("aza://01-02-2020-4A_1-2020")
        self.assertEqual(dal_vivo.call_count, 1)
        self.assertIn("cita_come", d)
        self.assertTrue(arch2.sources)   # la seconda squadra registra comunque la fonte che ha aperto


class TestLeggiDallArchivio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = make_db(self.tmp.name)
        self.arch = agent.Archive(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_legge_controllata_di_recente_niente_rete(self):
        store.mark_checked(self.con, URI)
        self.con.commit()
        with mock.patch.object(cli, "importa", side_effect=AssertionError("rete")) as imp:
            r = self.arch.importa_legge("RS 235.1")
        imp.assert_not_called()
        self.assertTrue(r["da_archivio"])
        self.assertEqual(r["versioni"], ["2023-09-01", "2024-03-01"])

    def test_legge_mai_controllata_va_su_fedlex(self):
        with mock.patch.object(cli, "importa", return_value=URI) as imp:
            r = self.arch.importa_legge("235.1")
        imp.assert_called_once()
        self.assertNotIn("da_archivio", r)

    def test_legge_vecchia_va_su_fedlex(self):
        self.con.execute("UPDATE acts SET checked_at = '2020-01-01T00:00:00+00:00'")
        self.con.commit()
        with mock.patch.object(cli, "importa", return_value=URI) as imp:
            self.arch.importa_legge("235.1")
        imp.assert_called_once()

    def test_titoli_locali_con_catalogo_completo(self):
        with mock.patch.object(agent, "SOGLIA_CATALOGO", 1), \
                mock.patch.object(fedlex, "search_titles", side_effect=AssertionError("rete")) as viva:
            r = self.arch.cerca_legge("protezione dati")
        viva.assert_not_called()
        self.assertEqual(r[0]["rs"], "235.1")

    def test_catalogo_incompleto_unisce_archivio_e_fedlex(self):
        altra = {"rs": "235.11", "titolo": "Ordinanza sulla protezione dei dati", "uri": "u2", "url": "x"}
        doppia = {"rs": "235.1", "titolo": "Legge federale sulla protezione dei dati", "uri": URI, "url": "x"}
        with mock.patch.object(fedlex, "search_titles", return_value=[doppia, altra]) as viva:
            r = self.arch.cerca_legge("protezione dati")
            self.arch.cerca_legge("protezione dati")
        self.assertEqual(viva.call_count, 1)   # la seconda volta dalla memoria
        self.assertEqual([x["rs"] for x in r], ["235.1", "235.11"])


class TestIndicePerAtto(unittest.TestCase):
    def test_ricostruisce_solo_l_atto_importato(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            prima = con.execute("SELECT COUNT(*) FROM search WHERE act_uri = ?", (URI,)).fetchone()[0]
            store.upsert_act(con, URI2, "999", "Legge di prova")
            store.save_version(con, URI2, "it", "2020-01-01", "https://x/3", "c" * 64, akn.parse(V1))
            store.rebuild_search(con, URI2)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM search WHERE act_uri = ?", (URI,)).fetchone()[0], prima)
            self.assertGreater(con.execute("SELECT COUNT(*) FROM search WHERE act_uri = ?", (URI2,)).fetchone()[0], 0)
            # stessa RS a un nuovo atto: il vecchio diventa abrogato ed esce dalla ricerca
            store.upsert_act(con, "https://nuovo", "235.1", "Nuova legge")
            store.rebuild_search(con, "https://nuovo")
            self.assertEqual(con.execute("SELECT COUNT(*) FROM search WHERE act_uri = ?", (URI,)).fetchone()[0], 0)
            con.close()


if __name__ == "__main__":
    unittest.main()
