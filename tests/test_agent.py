"""Test dell'agente senza rete: archivio di esempio e modello simulato."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nn import agent, ai, akn, store, web
from tests.test_nn import V1, V2

URI = "https://fedlex.data.admin.ch/eli/cc/2022/491"


def make_db(tmp: str):
    con = store.connect(Path(tmp) / "db.sqlite")
    store.upsert_act(con, URI, "235.1", "Legge federale sulla protezione dei dati")
    store.save_version(con, URI, "it", "2023-09-01", "https://x/1", "a" * 64, akn.parse(V1))
    store.save_version(con, URI, "it", "2024-03-01", "https://x/2", "b" * 64, akn.parse(V2))
    store.rebuild_search(con)
    return con


def tool_call(i, name, **args):
    return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class ScriptedModel:
    """Restituisce una sequenza prestabilita di messaggi e registra cio che riceve."""

    def __init__(self, script):
        self.script = list(script)
        self.received = []

    def chat(self, messages, tools=None):
        self.received.append(json.loads(json.dumps(messages)))
        return self.script.pop(0)


class TestArchiveTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = make_db(self.tmp.name)
        self.arc = agent.Archive(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_search_finds_by_stem(self):
        hits = self.arc.cerca_articoli("organo federale applicazione")
        self.assertEqual(hits[0]["articolo"], "Art. 2")

    def test_read_current_and_past(self):
        now = self.arc.leggi_articolo("235.1", "2")
        self.assertIn("organi federali", now["testo"])
        self.assertEqual(now["versione_in_vigore_dal"], "2024-03-01")
        past = self.arc.leggi_articolo("RS 235.1", "Art. 2", data="2023-12-31")
        self.assertNotIn("organi federali", past["testo"])
        self.assertEqual(past["versione_in_vigore_dal"], "2023-09-01")

    def test_history_and_diff(self):
        self.assertEqual([h["stato"] for h in self.arc.storia_articolo("235.1", "3")], ["non presente", "compare"])
        d = self.arc.differenze("235.1")
        self.assertEqual({c["tipo"] for c in d["articoli_cambiati"]}, {"modificato", "aggiunto"})

    def test_errors_are_returned_to_model(self):
        out = json.loads(self.arc.call("leggi_articolo", {"rs": "999", "articolo": "1"}))
        self.assertIn("non e in archivio", out["errore"])
        out = json.loads(self.arc.call("inesistente", {}))
        self.assertIn("sconosciuto", out["errore"])


class TestAgentLoop(unittest.TestCase):
    def test_tool_loop_and_citations(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            model = ScriptedModel([
                {"role": "assistant", "content": "", "tool_calls": [tool_call(1, "cerca_articoli", query="campo applicazione")]},
                {"role": "assistant", "content": "", "tool_calls": [tool_call(2, "leggi_articolo", rs="235.1", articolo="2")]},
                {"role": "assistant", "content": "La legge vale anche per gli organi federali [RS 235.1 art. 2, 2024-03-01]. "
                                                 "Vedi pure [RS 235.1 art. 99].\nInformazione generale, non consulenza legale."},
            ])
            model.script += [model.script[-1]] * agent.VERIFY_ROUNDS  # il modello insiste con un articolo mai letto
            events = []
            ans = agent.ask(model, con, "A chi si applica la LPD?", on_step=lambda e, i: events.append(e))
            self.assertEqual(events.count("strumento"), 2)
            self.assertEqual(events.count("verifica"), agent.VERIFY_ROUNDS)
            self.assertEqual(ans.unverified, ["RS 235.1 art. 99"])
            self.assertIn("NON sono state verificate", ans.text)
            self.assertEqual([s["strumento"] for s in ans.steps], ["cerca_articoli", "leggi_articolo"])
            self.assertEqual([(s.sr, s.num, s.date) for s in ans.sources], [("235.1", "Art. 2", "2024-03-01")])
            # il modello riceve i risultati degli strumenti con l'id della chiamata
            last = model.received[-1]
            self.assertEqual(last[0]["role"], "system")
            self.assertTrue(any(m["role"] == "user" and "CONTROLLO AUTOMATICO" in m["content"] for m in last))
            tool_msgs = [m for m in last if m["role"] == "tool"]
            self.assertEqual([m["tool_call_id"] for m in tool_msgs], ["c1", "c2"])
            self.assertIn("organi federali", tool_msgs[1]["content"])

            html = web._render_answer(con, ans.text, "it")
            self.assertIn('class="cite" href="/articolo?', html)
            self.assertIn("eid=art_2", html)
            self.assertIn("(non verificato)", html)  # art. 99 non esiste: segnalato
            con.close()

    def test_verification_makes_model_read_the_article(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            model = ScriptedModel([
                {"role": "assistant", "content": "Vale [RS 235.1 art. 3, 2024-03-01]."},          # citazione a memoria
                {"role": "assistant", "content": "", "tool_calls": [tool_call(1, "leggi_articolo", rs="235.1", articolo="3")]},
                {"role": "assistant", "content": "Vale, come dice il testo [RS 235.1 art. 3, 2024-03-01]."},
            ])
            ans = agent.ask(model, con, "Cosa dice l'art. 3?")
            self.assertEqual(ans.unverified, [])
            self.assertNotIn("NON sono state verificate", ans.text)
            self.assertEqual([s.num for s in ans.sources], ["Art. 3"])
            self.assertTrue(any("CONTROLLO AUTOMATICO" in str(m.get("content")) for m in model.received[1]))
            con.close()

    def test_nonexistent_article_named_to_say_so_is_not_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            model = ScriptedModel([
                {"role": "assistant", "content": "", "tool_calls": [tool_call(1, "leggi_articolo", rs="235.1", articolo="99z")]},
                {"role": "assistant", "content": "L'art. 99z non esiste [RS 235.1 art. 99z, 2024-03-01]."},
            ])
            ans = agent.ask(model, con, "Esiste l'art. 99z?")
            self.assertEqual(ans.unverified, [])
            self.assertNotIn("NON sono state verificate", ans.text)
            self.assertEqual(len(ans.absent), 1)
            con.close()

    def test_future_version_is_not_presented_as_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            store.save_version(con, URI, "it", "2999-01-01", "https://x/3", "c" * 64, akn.parse(V2))
            store.rebuild_search(con)
            arc = agent.Archive(con)
            out = json.loads(arc.call("leggi_articolo", {"rs": "235.1", "articolo": "3"}))
            self.assertEqual(out["versione_in_vigore_dal"], "2024-03-01")
            self.assertEqual(out["versione_piu_recente"], "2999-01-01")
            self.assertIn("AVVISO_VERSIONE_FUTURA", out)
            self.assertEqual({h["date"] for h in store.search(con, "articolo")}, {"2024-03-01"})
            diff = json.loads(arc.call("differenze", {"rs": "235.1"}))
            self.assertEqual((diff["da"], diff["a"]), ("2024-03-01", "2999-01-01"))
            self.assertEqual(store.in_force_date(["2023-01-01", "2999-01-01"], "2026-10-31"), "2023-01-01")
            self.assertEqual(store.in_force_date(["2999-01-01"], "2026-10-31"), "2999-01-01")
            con.close()

    def test_step_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            loop = {"role": "assistant", "content": "", "tool_calls": [tool_call(1, "elenca_leggi")]}
            ans = agent.ask(ScriptedModel([loop] * agent.MAX_STEPS), con, "?")
            self.assertIn("numero ragionevole di passaggi", ans.text)
            con.close()

    def test_web_page_with_fake_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            model = ScriptedModel([{"role": "assistant", "content": "Risposta [RS 235.1 art. 3]."}] * (1 + agent.VERIFY_ROUNDS))
            with mock.patch.object(web, "MODEL_FACTORY", lambda: model):
                ans = agent.ask(model, con, "Cosa dice l'art. 3?")
                page = web.chiedi_page(con, "Cosa dice l'art. 3?", ans).decode()
            self.assertIn("Cosa dice l&#x27;art. 3?", page)
            self.assertIn("eid=art_3", page)
            self.assertIn("Continua", page)
            con.close()


class TestCitazioni(unittest.TestCase):
    def test_formati(self):
        t = ("a [RS 235.1 art. 24 cpv. 4–5; art. 26, 2025-07-07] b [RS 235.1 art. 24 cpv. 5bis e 6, 2025-07-07] "
             "c [RS 220 art. 958f] d [vedi sopra]")
        cs = agent.find_citations(t)
        self.assertEqual([(c.sr, [a for a, _ in c.articles], c.date) for c in cs], [
            ("235.1", ["24", "26"], "2025-07-07"), ("235.1", ["24"], "2025-07-07"), ("220", ["958f"], None)])
        self.assertEqual(cs[1].articles[0][1], "cpv. 5bis e 6")

    def test_render_piu_articoli(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            html = web._render_answer(con, "x [RS 235.1 art. 2 cpv. 1; art. 3, 2024-03-01]", "it")
            self.assertEqual(html.count('class="cite" href'), 2)
            self.assertNotIn("non verificato", html)
            con.close()


class TestValuta(unittest.TestCase):
    def test_valuta_report_and_citation_check(self):
        from nn import cli
        with tempfile.TemporaryDirectory() as tmp:
            con = make_db(tmp)
            con.close()
            qfile = Path(tmp) / "q.txt"
            qfile.write_text("# commento\nA chi si applica la legge?\nChe cosa dice l'art. 99?\n", "utf-8")
            model = ScriptedModel([
                # domanda 1: legge l'art. 2 e lo cita: ok
                {"content": "", "tool_calls": [tool_call(1, "leggi_articolo", rs="235.1", articolo="2")]},
                {"content": "Anche agli organi federali [RS 235.1 art. 2, 2024-03-01]."},
                # domanda 2: cita l'art. 3 senza averlo letto (a memoria) e insiste dopo i due richiami: da segnalare
                {"content": "Dice questo [RS 235.1 art. 3, 2024-03-01]."},
                {"content": "Dice questo [RS 235.1 art. 3, 2024-03-01]."},
                {"content": "Dice questo [RS 235.1 art. 3, 2024-03-01]."},
            ])
            model.label, model.model = "Simulato", "finto"
            with mock.patch.object(cli, "DB", Path(tmp) / "db.sqlite"), mock.patch.object(cli, "DATA", Path(tmp)), \
                    mock.patch.object(ai, "make_client", lambda: model):
                cli.main(["valuta", str(qfile)])
            report = next((Path(tmp) / "valutazioni").glob("*.md")).read_text("utf-8")
            self.assertIn("Citazioni di articoli letti in questa ricerca: **1**", report)
            self.assertIn("Citazioni NON lette (fatte a memoria): **1**", report)
            self.assertIn("**Citazioni non verificate:** RS 235.1 art. 3", report)
            self.assertIn("Risposta dello strumento di confronto", report)


class TestInfomaniakClient(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.noenv = mock.patch.object(ai, "load_env", lambda path=None: None)
        self.noenv.start()

    def tearDown(self):
        self.noenv.stop()
        self.env.stop()

    def test_missing_config(self):
        with self.assertRaises(ai.AIConfigError):
            ai.InfomaniakClient()

    def test_modelli_ammessi(self):
        from unittest import mock
        ospitati = ("Qwen/Qwen3.5-397B-A17B-FP8", "moonshotai/Kimi-K2.6", "google/gemma-4-31B-it")
        europei = ("mistralai/Mistral-Small-4-119B-2603", "swiss-ai/Apertus-v1.5-70B")
        with mock.patch.dict(os.environ, {"NN_MODELLI_OSPITATI_CH": "1"}):
            for m in ospitati + europei:
                ai.InfomaniakClient(token="t", product_id="p", model=m)
        with mock.patch.dict(os.environ, {"NN_MODELLI_OSPITATI_CH": "0"}):
            for m in ospitati:
                with self.assertRaises(ai.AIConfigError):
                    ai.InfomaniakClient(token="t", product_id="p", model=m)
            for m in europei:
                ai.InfomaniakClient(token="t", product_id="p", model=m)
        with self.assertRaises(ai.AIConfigError):
            ai.InfomaniakClient(token="t", product_id="p", model="sconosciuto/x")

    def test_qwen_senza_pensiero(self):
        c = ai.InfomaniakClient(token="t", product_id="p", model="Qwen/Qwen3.5-397B-A17B-FP8") \
            if os.environ.get("NN_MODELLI_OSPITATI_CH", "1") != "0" else None
        if c:
            self.assertEqual(c.extra_body(), {"chat_template_kwargs": {"enable_thinking": False}})
        self.assertEqual(ai._senza_ragionamento("<think>bla</think>\n{\"a\": 1}"), '{"a": 1}')

    def test_request_shape(self):
        client = ai.InfomaniakClient(token="segreto", product_id="12345")
        sent = {}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=0):
            sent["url"], sent["auth"] = req.full_url, req.get_header("Authorization")
            sent["body"] = json.loads(req.data)
            return Resp(json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}]}).encode())

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            msg = client.chat([{"role": "user", "content": "ciao"}], tools=agent.TOOLS)
        self.assertEqual(msg["content"], "ok")
        self.assertEqual(sent["url"], "https://api.infomaniak.com/2/ai/12345/openai/v1/chat/completions")
        self.assertEqual(sent["auth"], "Bearer segreto")
        self.assertEqual(sent["body"]["model"], ai.DEFAULT_MODEL)
        self.assertEqual(len(sent["body"]["tools"]), len(agent.TOOLS))

    def _capture(self, client, reply=None, error=None):
        sent = {}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=0):
            sent["url"], sent["auth"] = req.full_url, req.get_header("Authorization")
            sent["body"] = json.loads(req.data) if req.data else None
            if error:
                import urllib.error
                raise urllib.error.HTTPError(req.full_url, error[0], "x", {}, io.BytesIO(error[1].encode()))
            return Resp(json.dumps(reply or {"choices": [{"message": {"content": "ok"}}]}).encode())

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            try:
                client.chat([{"role": "user", "content": "ciao"}])
            except Exception as e:
                sent["error"] = e
        return sent

    def test_provider_selection(self):
        os.environ.update({"INFOMANIAK_API_TOKEN": "t", "INFOMANIAK_PRODUCT_ID": "1", "OPENAI_API_KEY": "sk-x"})
        self.assertEqual(ai.make_client().provider, "infomaniak")
        os.environ["NN_PROVIDER"] = "openai"
        self.assertEqual(ai.make_client().provider, "openai")
        os.environ["NN_PROVIDER"] = "infomaniak=segreto-che-non-va-mostrato"
        with self.assertRaises(ai.AIConfigError) as ctx:
            ai.make_client()
        self.assertNotIn("segreto", str(ctx.exception))

    def test_openai_request_shape(self):
        os.environ["NN_MODEL"] = "mistralai/Mistral-Small-4-119B-2603"  # rimasto dal .env: va ignorato
        client = ai.OpenAIClient(token="sk-segreto")
        self.assertFalse(client.european)
        sent = self._capture(client)
        self.assertEqual(sent["url"], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(sent["auth"], "Bearer sk-segreto")
        self.assertEqual(sent["body"]["model"], ai.OPENAI_DEFAULT_MODEL)
        self.assertNotIn("temperature", sent["body"])  # i modelli GPT-5 la rifiutano
        self.assertEqual(sent["body"]["reasoning_effort"], "low")  # ragionamento breve, piu veloce

    def test_reasoning_fallback(self):
        """Se il modello non accetta reasoning_effort, si riprova senza."""
        client = ai.OpenAIClient(token="sk-x", model="gpt-5-mini")
        calls = []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=0):
            body = json.loads(req.data)
            calls.append(body)
            if "reasoning_effort" in body:
                import urllib.error
                raise urllib.error.HTTPError(req.full_url, 400, "x", {}, io.BytesIO(
                    b'{"error":{"message":"Unsupported parameter: reasoning_effort"}}'))
            return Resp(b'{"choices":[{"message":{"content":"ok"}}]}')

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            self.assertEqual(client.chat([{"role": "user", "content": "x"}])["content"], "ok")
        self.assertEqual(len(calls), 2)

    def test_error_message_has_detail_but_no_token(self):
        client = ai.InfomaniakClient(token="segreto-123", product_id="9")
        sent = self._capture(client, error=(403, '{"result":"error","error":{"code":"not_authorized","description":"Scope missing"}}'))
        msg = str(sent["error"])
        self.assertIsInstance(sent["error"], ai.AIConfigError)
        self.assertIn("not_authorized", msg)
        self.assertIn("verifica-ai", msg)
        self.assertNotIn("segreto-123", msg)

    def test_env_file(self):
        self.noenv.stop()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / ".env"
            p.write_text('# commento\nINFOMANIAK_API_TOKEN="abc"\nINFOMANIAK_PRODUCT_ID=42\n'
                         'NN_PROVIDER=infomaniak\nNN_PROVIDER=openai\n', "utf-8")
            ai.load_env(p)
        self.assertEqual(os.environ["NN_PROVIDER"], "openai")  # chiave ripetuta: vale l'ultima
        self.assertEqual(os.environ["INFOMANIAK_API_TOKEN"], "abc")
        self.assertEqual(os.environ["INFOMANIAK_PRODUCT_ID"], "42")
        self.noenv.start()


if __name__ == "__main__":
    unittest.main()
