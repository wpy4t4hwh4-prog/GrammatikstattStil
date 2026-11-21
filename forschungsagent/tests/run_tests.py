"""Offline-Tests fuer den Forschungsagenten (Hook-Logik, Caches, HTTP-Retry, statische Checks).

Run: uv run python tests/run_tests.py  (aus forschungsagent/)
Keine Netzwerk- oder API-Calls.
"""
import asyncio
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


def _reply(text="", tool_calls=None):
    return types.SimpleNamespace(text=text, tool_calls=tool_calls)


class HookLoopTests(unittest.TestCase):
    def setUp(self):
        self.hook = main.QuoteAuditHook()
        asyncio.run(self.hook.pre_agent_turn(None, None))

    def _post(self, text="", tool_calls=None):
        return asyncio.run(self.hook.post_llm_call(None, _reply(text, tool_calls)))

    def test_floskel_burst_rejected(self):
        res = self._post("Fertig. Ende. Done. Stop.")
        self.assertIsNotNone(res)
        self.assertTrue(self.hook.turn_rejected)

    def test_ok_halt_not_counted(self):
        self.assertIsNone(self._post("OK, alles erledigt."))
        self.assertIsNone(self._post("Halt, das reicht."))

    def test_single_ende_not_rejected(self):
        self.assertIsNone(self._post("Ende."))

    def test_cumulative_floskel_rejected(self):
        self.assertIsNone(self._post("Ende."))
        self.assertIsNone(self._post("Fertig."))
        res = self._post("Done.")
        self.assertIsNotNone(res)
        self.assertTrue(self.hook.turn_rejected)

    def test_tool_calls_reset_streak(self):
        self._post("Ende.")
        self._post("Fertig.")
        self.assertIsNone(self._post("weiter gehts", tool_calls=["x"]))
        self.assertEqual(self.hook.no_tool_streak, 0)
        self.assertEqual(self.hook.deg_total, 0)

    def test_iteration_soft_warning_once(self):
        self.hook.llm_calls = 14
        res = self._post("mehr recherche", tool_calls=["web_recherche"])
        self.assertIsNotNone(res)
        self.assertTrue(self.hook.wrap_warned)
        res2 = self._post("noch mehr", tool_calls=["web_recherche"])
        self.assertIsNone(res2)

    def test_json_qa_unverified_quote_retries(self):
        import json
        payload = json.dumps({"zusammenfassung": "x", "verbatim_zitate": [{"text": "erfundenes zitat", "quelle": "q", "geprueft_mit": "nix"}]})
        res = self._post(payload)
        self.assertIsNotNone(res)
        self.assertEqual(self.hook.retries, 1)

    def test_duplicate_aussagen_in_json_retried(self):
        import json
        payload = json.dumps({
            "zusammenfassung": "x",
            "belegte_aussagen": [
                {"aussage": "Gleiche Aussage", "quelle": "q1", "evidenzgrad": "wahrscheinlich"},
                {"aussage": "gleiche aussage", "quelle": "q2", "evidenzgrad": "wahrscheinlich"},
            ],
            "double_check": [],
            "verifizierungsquote": 0.0,
        })
        res = self._post(payload)
        self.assertIsNotNone(res)
        self.assertIn("doppelte", str(getattr(res, "message", res)))

    def test_very_long_answer_retry_then_reject(self):
        lang = "x" * 30001
        r1 = self._post(lang)
        self.assertIsNotNone(r1)  # zu lang -> Retry
        r2 = self._post(lang)
        self.assertIsNotNone(r2)  # weiterhin zu lang -> Reject
        self.assertTrue(self.hook.turn_rejected)

    def test_tool_call_dedup_retry_then_reject(self):
        req = types.SimpleNamespace(tool_name="in_dokument_suchen", arguments={"document_id": "x", "begriff": "y"})
        r1 = asyncio.run(self.hook.pre_tool_call(None, req))
        r2 = asyncio.run(self.hook.pre_tool_call(None, req))
        self.assertIsNone(r1); self.assertIsNone(r2)
        r3 = asyncio.run(self.hook.pre_tool_call(None, req))
        self.assertIsNotNone(r3)  # 3x identisch -> Retry
        r4 = asyncio.run(self.hook.pre_tool_call(None, req))
        self.assertIsNotNone(r4)  # weiterhin identisch -> Reject
        self.assertTrue(self.hook.turn_rejected)

    def test_hard_watchdog_at_17(self):
        self.hook.llm_calls = 16
        res = self._post("weiter", tool_calls=["web_recherche"])
        self.assertIsNotNone(res)
        self.assertTrue(self.hook.turn_rejected)

    def test_no_progress_retry_then_reject(self):
        res = types.SimpleNamespace(tool_name="ablage_durchsuchen", tool_result=types.SimpleNamespace(content=[types.SimpleNamespace(text="gleiches ergebnis")]))
        for _ in range(4):
            asyncio.run(self.hook.post_tool_call(None, res))
        self.assertGreaterEqual(self.hook.res_streak, 4)
        r1 = self._post("nochmal gleiche suche")
        self.assertIsNotNone(r1)  # Retry
        r2 = self._post("immer noch gleich")
        self.assertIsNotNone(r2)  # Reject
        self.assertTrue(self.hook.turn_rejected)

    def test_wellen_loop_retry_then_reject(self):
        wellig = '```json\n{"zusammenfassung": "A", "belegte_aussagen": []}\n```\nZwischenfazit.\n```json\n{"zusammenfassung": "B"}\n```'
        res1 = self._post(wellig)
        self.assertIsNotNone(res1)  # erster Welle -> Retry
        self.assertEqual(self.hook.wave_streak, 1)
        res2 = self._post(wellig)
        self.assertIsNotNone(res2)  # zweite Welle -> Reject
        self.assertTrue(self.hook.turn_rejected)

    def test_wellen_kumulativ_ueber_turn(self):
        # zwei EINZELNE text-only Antworten mit je einem json-Block -> kumulativ Welle
        b1 = '```json\n{"zusammenfassung": "A"}\n```'
        b2 = '```json\n{"zusammenfassung": "B"}\n```'
        r1 = self._post(b1)
        self.assertIsNotNone(r1)  # kumulativ 2 -> Retry
        self.assertEqual(self.hook.wave_streak, 1)
        r2 = self._post(b2)
        self.assertIsNotNone(r2)  # weiterhin kumulativ -> Reject
        self.assertTrue(self.hook.turn_rejected)

    def test_typo_quotes_retry_then_reject(self):
        bad = '{\u201ezusammenfassung\u201c: \u201eWelle mit deutschen Anfuehrungszeichen\u201c}'
        r1 = self._post(bad)
        self.assertIsNotNone(r1)  # Retry mit ASCII-Hinweis
        self.assertEqual(self.hook.typo_streak, 1)
        r2 = self._post(bad)
        self.assertIsNotNone(r2)  # Reject
        self.assertTrue(self.hook.turn_rejected)

    def test_typo_quotes_in_plain_text_ok(self):
        # gewoehnlicher deutscher Text mit \u201e \u201c ist KEIN JSON-versuch -> kein typo-retry
        self.assertIsNone(self._post("Das Ergebnis ist \u201eeindeutig\u201c belegt."))

    def test_ablage_pflicht_text_only_retry_then_reject(self):
        res = types.SimpleNamespace(tool_name="web_recherche", tool_result=types.SimpleNamespace(content=[types.SimpleNamespace(text="treffer")]))
        asyncio.run(self.hook.post_tool_call(None, res))
        r1 = self._post("recherche abgeschlossen")
        self.assertIsNotNone(r1)  # Retry: Notiz fehlt
        self.assertTrue(self.hook.abl_warned)
        r2 = self._post("immer noch keine notiz")
        self.assertIsNotNone(r2)  # Reject
        self.assertTrue(self.hook.turn_rejected)

    def test_ablage_erfuellt_kein_retry(self):
        for name in ("web_recherche", "research_note_ablegen"):
            res = types.SimpleNamespace(tool_name=name, tool_result=types.SimpleNamespace(content=[types.SimpleNamespace(text="ok")]))
            asyncio.run(self.hook.post_tool_call(None, res))
        self.assertIsNone(self._post("alles protokolliert"))

    def test_keine_recherche_keine_ablage_pflicht(self):
        # reine Chat-Antwort ohne Recherche-Tools -> kein Ablage-Retry
        self.assertIsNone(self._post("allgemeine erlaeuterung ohne werkzeug"))

    def test_instructions_formatregeln_present(self):
        with open(main.__file__, encoding="utf-8") as _f:
            s = _f.read()
        self.assertIn("ABSCHLUSS-ANTWORT-FORMAT", s)
        self.assertIn("ASCII-Double-Quotes", s)
        self.assertIn("ABLAGE-PFLICHT", s)

    def test_single_answer_block_not_flagged(self):
        import json
        payload = json.dumps({"zusammenfassung": "ok", "belegte_aussagen": [], "double_check": [], "verifizierungsquote": 1.0})
        self.assertIsNone(self._post(payload))

    def test_verifizierungsquote_low_retries(self):
        import json
        payload = json.dumps({
            "zusammenfassung": "x",
            "belegte_aussagen": [{"aussage": "a%d" % i, "quelle": "q", "evidenzgrad": "wahrscheinlich"} for i in range(4)],
            "double_check": [{"angabe": "a0", "pruef_tool": "dokument_lesen", "ergebnis": "ok"}],
            "verifizierungsquote": 0.25,
        })
        res = self._post(payload)
        self.assertIsNotNone(res)
        self.assertIn("Verifizierungsquote", str(getattr(res, "message", res)))

    def test_rejected_turn_skips_summary_guard(self):
        with open(main.__file__, encoding="utf-8") as _f:
            src = _f.read()
        self.assertIn("self.turn_rejected or len(set(self.tools_called)) < 2", src)


class CacheTests(unittest.TestCase):
    def test_tool_cache_cap(self):
        main._TOOL_CACHE.clear()
        for i in range(2500):
            main._cache_set("k%d" % i, i)
        self.assertLessEqual(len(main._TOOL_CACHE), 2000)

    def test_text_cache_budget_eviction(self):
        main._TEXT_CACHE.clear()
        main._text_cache_set("a", "x" * 100)
        main._text_cache_set("b", "y" * (main._TEXT_CACHE_MAX_CHARS))
        main._text_cache_set("c", "z" * 10)
        total = sum(len(v) for v in main._TEXT_CACHE.values())
        self.assertLessEqual(total, main._TEXT_CACHE_MAX_CHARS + 10)
        self.assertIn("c", main._TEXT_CACHE)

    def test_text_cache_invalidate(self):
        main._TEXT_CACHE.clear()
        main._text_cache_set("lib:doc", "text")
        main._text_cache_invalidate("lib", "doc")
        self.assertNotIn("lib:doc", main._TEXT_CACHE)


class HttpRetryTests(unittest.TestCase):
    def test_retry_then_raise(self):
        import httpx
        calls = {"n": 0}
        real_sleep = asyncio.sleep

        async def _nosleep(_):
            return None

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def request(self, *a, **kw):
                calls["n"] += 1
                raise httpx.ConnectError("boom")

        orig_client = httpx.AsyncClient
        orig_sleep = asyncio.sleep
        httpx.AsyncClient = FakeClient
        asyncio.sleep = _nosleep
        try:
            with self.assertRaises(httpx.ConnectError):
                asyncio.run(main._http_fetch("https://example.invalid/", max_retries=2))
            self.assertEqual(calls["n"], 3)
        finally:
            httpx.AsyncClient = orig_client
            asyncio.sleep = orig_sleep


class StaticSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(main.__file__, encoding="utf-8") as _f:
            cls.src = _f.read()

    def test_submodel_pinned(self):
        self.assertIn('SUBMODEL = "mistral-large-4-0"', self.src)
        self.assertNotIn("mistral-large-latest", self.src)

    def test_prompt_injection_rule_present(self):
        self.assertIn("PROMPT-INJECTION-REGEL", self.src)

    def test_aktualisieren_tool_registered(self):
        self.assertIn('"research_note_aktualisieren"', self.src)
        self.assertIn("async def research_note_aktualisieren", self.src)
        self.assertIn("research_note_aktualisieren,\n        webseite_lesen,", self.src)

    def test_pagination_in_auflisten(self):
        self.assertIn("page=_page", self.src)

    def test_ocr_size_limit(self):
        self.assertIn("50_000_000", self.src)

    def test_projektstand_upsert(self):
        self.assertIn('00-projektstand.md', self.src)
        self.assertIn("_upsert_document", self.src)

    def test_hook_logging(self):
        self.assertIn('logger = logging.getLogger("forschungsagent")', self.src)
        self.assertIn('logger.warning("hook reject")', self.src)

    def test_json_import_module_level(self):
        self.assertIn("import json as _json", self.src.split("\n")[:5])

    def test_eigene_ablage_regel_present(self):
        self.assertIn("EIGENE-ABLAGE-REGEL", self.src)
        self.assertIn("NIEMALS Primaerquelle", self.src)

    def test_naechster_block_regeln_present(self):
        self.assertIn("SAETTIGUNGS-REGEL v2", self.src)
        self.assertIn("zaehlen NICHT", self.src)
        self.assertIn("DATENSCHUTZ/ROBOTS", self.src)
        self.assertIn("Getty AAT", self.src)

    def test_verifizierungsquote_feld_und_hook_check(self):
        self.assertIn("verifizierungsquote: float", self.src)
        self.assertIn("Verifizierungsquote zu niedrig", self.src)

    def test_provenance_header(self):
        self.assertIn("Erstellt mit: Forschungsagent grammatik-statt-stil-research", self.src)

    def test_self_eval_in_background_check(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "background_check.py"), encoding="utf-8") as _f:
            bc = _f.read()
        self.assertIn("SELF_EVAL_TASK", bc)
        self.assertIn("_task_for_today()", bc)
        self.assertIn("selbst-eval-", bc)

    def test_aktualisieren_deletes_predecessor(self):
        self.assertIn("delete_async(library_id=NOTES_LIBRARY_ID, document_id=document_id)", self.src)

    def test_lizenzfeld_present(self):
        self.assertIn("Lizenz-/Zugangsweg-Feld", self.src)
        self.assertNotIn("KI-Nutzung: mit KI-Assistenz", self.src)


class SessionStartRegelTests(unittest.TestCase):
    def test_session_start_regel_robust(self):
        with open(main.__file__, encoding="utf-8") as _f:
            s = _f.read()
        self.assertIn("dokument_finden mit dem Namen", s)
        self.assertIn("NIEMALS eine ID raten", s)
        self.assertIn("NICHT blind ein neues Projektstand-Dokument anlegen", s)
        self.assertIn("GENAU EINES", s)




class SdkRetryTests(unittest.TestCase):
    def setUp(self):
        self._old = main._SDK_RETRY_BASE
        main._SDK_RETRY_BASE = 0.0

    def tearDown(self):
        main._SDK_RETRY_BASE = self._old

    @staticmethod
    def _sdk_err(sc):
        class FakeSDKError(Exception):
            pass
        e = FakeSDKError("API error occurred: Status %d" % sc)
        e.status_code = sc
        return e

    def test_retry_eventual_success(self):
        calls = {"n": 0}
        async def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise self._sdk_err(520)
            return "ok"
        res = asyncio.run(main._sdk_retry(flaky))
        self.assertEqual(res, "ok")
        self.assertEqual(calls["n"], 3)

    def test_retry_gives_up_after_4(self):
        calls = {"n": 0}
        async def always520():
            calls["n"] += 1
            raise self._sdk_err(520)
        with self.assertRaises(Exception):
            asyncio.run(main._sdk_retry(always520))
        self.assertEqual(calls["n"], 4)

    def test_non_retryable_raises_immediately(self):
        calls = {"n": 0}
        async def bad400():
            calls["n"] += 1
            raise self._sdk_err(400)
        with self.assertRaises(Exception):
            asyncio.run(main._sdk_retry(bad400))
        self.assertEqual(calls["n"], 1)

    def test_timeout_retryable(self):
        ReadTimeout = type("ReadTimeout", (Exception,), {})
        self.assertTrue(main._is_retryable_sdk_error(ReadTimeout("t")))
        self.assertTrue(main._is_retryable_sdk_error(self._sdk_err(429)))
        self.assertFalse(main._is_retryable_sdk_error(self._sdk_err(400)))
        self.assertFalse(main._is_retryable_sdk_error(ValueError("x")))

    def test_client_wrap_wraps_async_calls(self):
        class FakeDocs:
            async def list_async(self, **kw):
                return "listed"
        class FakeBeta:
            documents = FakeDocs()
        class FakeClient:
            beta = FakeBeta()
        w = main._ClientWrap(FakeClient())
        res = asyncio.run(w.beta.documents.list_async(library_id="x"))
        self.assertEqual(res, "listed")




class ToolGuardAndLaengenTests(unittest.TestCase):
    def setUp(self):
        self._old = main._SDK_RETRY_BASE
        main._SDK_RETRY_BASE = 0.0
        self.hook = main.QuoteAuditHook()
        asyncio.run(self.hook.pre_agent_turn(None, None))

    def tearDown(self):
        main._SDK_RETRY_BASE = self._old

    @staticmethod
    def _sdk_err(sc, body="{}"):
        class FakeSDKError(Exception):
            pass
        e = FakeSDKError("API error occurred: Status %d" % sc)
        e.status_code = sc
        e.body = body
        return e

    def test_tool_guard_returns_dict_on_520(self):
        async def t():
            raise self._sdk_err(520)
        w = main._tool_guard(t)
        res = asyncio.run(w())
        self.assertIsInstance(res, dict)
        self.assertIn("fehler", res)
        self.assertEqual(res["http_status"], 520)
        self.assertTrue(res["retryable"])

    def test_tool_guard_400_open_not_supported_hint(self):
        async def t():
            raise self._sdk_err(400, '{"detail":"Open not supported for this filetype."}')
        w = main._tool_guard(t)
        res = asyncio.run(w())
        self.assertIn("pdf_ocr", res["fehler"])
        self.assertFalse(res["retryable"])

    def test_tool_guard_passes_result(self):
        async def t():
            return {"ok": True}
        res = asyncio.run(main._tool_guard(t)())
        self.assertEqual(res, {"ok": True})

    def _post(self, text="", tool_calls=None):
        return asyncio.run(self.hook.post_llm_call(None, _reply(text, tool_calls)))

    def test_arbeitsupdate_zu_lang_retry(self):
        import json
        payload = json.dumps({"zusammenfassung": "ok", "arbeitsupdate": "x" * 2501, "belegte_aussagen": [], "double_check": [], "verifizierungsquote": 1.0})
        res = self._post(payload)
        self.assertIsNotNone(res)
        self.assertIn("zu lang", str(getattr(res, "message", res)))

    def test_zusammenfassung_zu_lang_retry(self):
        import json
        payload = json.dumps({"zusammenfassung": "x" * 1501, "arbeitsupdate": "kurz", "belegte_aussagen": [], "double_check": [], "verifizierungsquote": 1.0})
        res = self._post(payload)
        self.assertIsNotNone(res)

    def test_kurze_antwort_ok(self):
        import json
        payload = json.dumps({"zusammenfassung": "x" * 1500, "arbeitsupdate": "y" * 2500, "belegte_aussagen": [], "double_check": [], "verifizierungsquote": 1.0})
        self.assertIsNone(self._post(payload))

    def test_alle_tools_guarded(self):
        with open(main.__file__, encoding="utf-8") as _f:
            s = _f.read()
        self.assertEqual(s.count("@_tool_guard\n@agents.tool"), 19)




class MkdirRegelTests(unittest.TestCase):
    def test_mkdir_regel_in_instructions(self):
        with open(main.__file__, encoding="utf-8") as _f:
            s = _f.read()
        self.assertIn("mkdir -p", s)
        self.assertIn("/tmp/ext", s)


class UrlGuardTests(unittest.TestCase):
    """SSRF-Schutz (Deep-Review): _assert_public_url blockiert interne/private Ziele."""

    def test_blocks_internal_and_private(self):
        for u in (
            "http://127.0.0.1/", "http://localhost/x", "http://0.0.0.0/",
            "http://169.254.169.254/latest/meta-data", "http://10.1.2.3/",
            "http://172.16.0.9/", "http://192.168.0.1/", "http://[::1]/",
            "http://metadata.google.internal/", "http://foo.internal/",
            "file:///etc/passwd", "ftp://example.com/x", "gopher://127.0.0.1/",
        ):
            with self.assertRaises(ValueError, msg=u):
                main._assert_public_url(u)

    def test_allows_public_urls(self):
        for u in ("https://export.arxiv.org/api/query?search_query=all:x",
                  "https://doi.org/10.1000/xyz123", "http://93.184.216.34/"):
            main._assert_public_url(u)  # darf nicht werfen

    def test_http_fetch_guards_before_network(self):
        with self.assertRaises(ValueError):
            asyncio.run(main._http_fetch("http://169.254.169.254/latest/meta-data", max_retries=0))
        with self.assertRaises(ValueError):
            asyncio.run(main._http_fetch("file:///etc/passwd", max_retries=0))


class ExactQuoteTests(unittest.TestCase):
    """Deep-Review (wissenschaftliche Integritaet): verbatim_zitate brauchen found_exact."""

    def setUp(self):
        self.hook = main.QuoteAuditHook()
        asyncio.run(self.hook.pre_agent_turn(None, None))

    def _tool_result(self, name, payload):
        import json as _j
        tr = types.SimpleNamespace(content=[types.SimpleNamespace(text=_j.dumps(payload))])
        return types.SimpleNamespace(tool_name=name, tool_result=tr)

    def _answer_json(self, quote_text):
        import json as _j
        return _j.dumps({
            "zusammenfassung": "kurze Zusammenfassung", "arbeitsupdate": "kurz",
            "belegte_aussagen": [], "deutungen": [], "offene_punkte": [],
            "verbatim_zitate": [{"text": quote_text, "quelle": "Dokument X", "geprueft_mit": "zitat_pruefen"}],
            "double_check": [], "verifizierungsquote": 0.0,
        })

    def test_exact_quote_accepted(self):
        asyncio.run(self.hook.post_tool_call(None, self._tool_result("research_note_ablegen", {"document_id": "11111111-2222-3333-4444-555555555555"})))
        asyncio.run(self.hook.post_tool_call(None, self._tool_result("zitat_pruefen", {"found": True, "found_exact_inkl_leerzeichen": True, "zitat": "Hallo Welt"})))
        res = asyncio.run(self.hook.post_llm_call(None, _reply(self._answer_json("Hallo Welt"))))
        self.assertIsNone(res)

    def test_normalized_only_quote_flagged(self):
        asyncio.run(self.hook.post_tool_call(None, self._tool_result("research_note_ablegen", {"document_id": "11111111-2222-3333-4444-555555555555"})))
        asyncio.run(self.hook.post_tool_call(None, self._tool_result("zitat_pruefen", {"found": True, "found_exact_inkl_leerzeichen": False, "zitat": "Hallo  Welt"})))
        res = asyncio.run(self.hook.post_llm_call(None, _reply(self._answer_json("Hallo  Welt"))))
        self.assertIsNotNone(res)  # Retry wegen nicht zeichen-exakt

    def test_unverified_quote_still_flagged(self):
        asyncio.run(self.hook.post_tool_call(None, self._tool_result("research_note_ablegen", {"document_id": "11111111-2222-3333-4444-555555555555"})))
        res = asyncio.run(self.hook.post_llm_call(None, _reply(self._answer_json("nicht geprueft"))))
        self.assertIsNotNone(res)


class Runde2B3Tests(unittest.TestCase):
    """Deep Review Runde 2 + Subagenten Arm B: B3-1 Session-Scoping, B3-2 pro-Claim/Backstop 0.8,
    B3-3 Lizenz-Sidecar, B3-4 URL-Check 404/403, B3-7 Skills gepinnt, B3-8 Subagenten-Konfig."""

    def setUp(self):
        self.hook = main.QuoteAuditHook()
        asyncio.run(self.hook.pre_agent_turn(None, None))

    def _post(self, text="", tool_calls=None):
        return asyncio.run(self.hook.post_llm_call(None, _reply(text, tool_calls)))

    def test_hook_session_id_gesetzt(self):
        ctx = types.SimpleNamespace(session=types.SimpleNamespace(id="sess-42"))
        h = main.QuoteAuditHook()
        asyncio.run(h.pre_agent_turn(ctx, None))
        self.assertEqual(h.session_id, "sess-42")

    def test_proclaim_doublecheck_fehlt(self):
        import json
        payload = json.dumps({
            "zusammenfassung": "x",
            "belegte_aussagen": [
                {"aussage": "Haussmann leitete die Pariser Stadterneuerung 1853-1870", "quelle": "q", "evidenzgrad": "wahrscheinlich"},
                {"aussage": "Die Wiener Ringstrasse wurde 1865 eroeffnet", "quelle": "q", "evidenzgrad": "wahrscheinlich"},
            ],
            "double_check": [{"angabe": "Haussmann leitete die Pariser Stadterneuerung 1853-1870", "pruef_tool": "dokument_lesen", "ergebnis": "ok"}],
            "verifizierungsquote": 0.5,
        })
        res = self._post(payload)
        self.assertIsNotNone(res)
        msg = str(getattr(res, "message", res))
        self.assertIn("pro-Claim", msg)
        self.assertIn("80%", msg)  # Backstop 0.8 erklaert

    def test_proclaim_ok_bei_vollstaendiger_abdeckung(self):
        import json
        a = "Haussmann leitete die Pariser Stadterneuerung 1853-1870"
        asyncio.run(self.hook.post_tool_call(None, self._tool_res("dokument_lesen", "volltext mit claim und jahr 1853")))  # Such-Tool-Call im Turn
        asyncio.run(self.hook.post_tool_call(None, self._tool_res("research_note_ablegen", "notiz abgelegt")))  # Ablage-Pflicht erfuellt
        payload = json.dumps({
            "zusammenfassung": "x",
            "belegte_aussagen": [{"aussage": a, "quelle": "q", "evidenzgrad": "wahrscheinlich"}],
            "double_check": [{"angabe": a, "pruef_tool": "dokument_lesen", "ergebnis": "ok"}],
            "verifizierungsquote": 1.0,
        })
        self.assertIsNone(self._post(payload))

    def test_license_sidecar_pflicht_volltext(self):
        import json
        payload = json.dumps({
            "zusammenfassung": "x",
            "quellen": [{"titel": "Scan X", "url": "https://example.com/x.pdf", "zugangsstufe": "Volltext", "license_access": {}}],
            "belegte_aussagen": [], "double_check": [], "verifizierungsquote": 1.0,
        })
        res = self._post(payload)
        self.assertIsNotNone(res)
        self.assertIn("Sidecar", str(getattr(res, "message", res)))

    def test_license_sidecar_ok(self):
        import json
        payload = json.dumps({
            "zusammenfassung": "x",
            "quellen": [{"titel": "Scan X", "url": "https://example.com/x.pdf", "zugangsstufe": "Volltext", "license_access": {"lizenz": "Archiv-Scan (legitim)", "zugang": "scan", "abgerufen_am": "2026-11-20"}}],
            "belegte_aussagen": [], "double_check": [], "verifizierungsquote": 1.0,
        })
        self.assertIsNone(self._post(payload))

    def _tool_res(self, name, text):
        return types.SimpleNamespace(tool_name=name, tool_result=types.SimpleNamespace(content=[types.SimpleNamespace(text=text)]))

    def test_url_check_404_wird_erfasst_und_in_post_llm_durchgesetzt(self):
        # Harness-Vertrag: post_tool_call darf nur Continue (None) liefern - keine Decision, kein I/O
        import json
        url = "https://example.com/tot"
        res = self._tool_res("url_status_pruefen", json.dumps({"url": url, "http_status": 404, "gesperrt": False, "pruefbar": True}))
        r = asyncio.run(self.hook.post_tool_call(None, res))
        self.assertIsNone(r)
        self.assertEqual(self.hook.url_checks.get(main._norm(url)), 404)
        asyncio.run(self.hook.post_tool_call(None, self._tool_res("research_note_ablegen", "ok")))
        payload = json.dumps({"zusammenfassung": "Quelle: " + url, "belegte_aussagen": [], "double_check": [], "verifizierungsquote": 1.0})
        r1 = self._post(payload)
        self.assertIsNotNone(r1)  # Retry wegen 404-URL in der Antwort
        self.assertIn("404", str(getattr(r1, "message", r1)))
        r2 = self._post(payload)
        self.assertIsNotNone(r2)  # zweites Retry (retries<2)
        r3 = self._post(payload)
        self.assertIsNotNone(r3)  # drittes Mal -> Reject
        self.assertTrue(self.hook.turn_rejected)

    def test_url_check_403_ist_kein_404(self):
        import json
        url = "https://example.com/gesperrt"
        res = self._tool_res("url_status_pruefen", json.dumps({"url": url, "http_status": 403, "gesperrt": True, "pruefbar": False}))
        r = asyncio.run(self.hook.post_tool_call(None, res))
        self.assertIsNone(r)
        self.assertIn("gesperrt", str(self.hook.url_checks.get(main._norm(url))))
        asyncio.run(self.hook.post_tool_call(None, self._tool_res("research_note_ablegen", "ok")))
        payload = json.dumps({"zusammenfassung": "Quelle gesperrt (403): " + url, "belegte_aussagen": [], "double_check": [], "verifizierungsquote": 1.0})
        self.assertIsNone(self._post(payload))  # 403 != 404 -> kein Problem

    def test_url_ohne_check_wird_flagged(self):
        import json
        asyncio.run(self.hook.post_tool_call(None, self._tool_res("research_note_ablegen", "ok")))
        payload = json.dumps({"zusammenfassung": "siehe https://example.com/ungeprueft", "belegte_aussagen": [], "double_check": [], "verifizierungsquote": 1.0})
        r = self._post(payload)
        self.assertIsNotNone(r)
        self.assertIn("Existenz-Check", str(getattr(r, "message", r)))

    def test_post_llm_call_swallows_internal_errors(self):
        # Harness-Regel: Hook darf nie werfen (sonst "Hook failed ..." und Turn-Ende)
        from unittest.mock import patch
        with patch.object(main._re, "findall", side_effect=Exception("boom")):
            r = asyncio.run(self.hook.post_llm_call(None, _reply("irgendein text")))
        self.assertIsNone(r)

    def test_huge_text_does_not_blow_up(self):
        # CPU-Deckel: riesige Modellausgabe darf den Hook (Temporal-Activity) nicht aufblasen
        import time
        t0 = time.time()
        r = self._post("x" * 40000)
        self.assertLess(time.time() - t0, 5)
        self.assertIsNotNone(r)  # Welle/Laenge -> Retry, kein Absturz

    def test_subagent_konfiguration_arm_b(self):
        names = [getattr(s, "name", "") for s in (getattr(main.agent, "subagents", None) or [])]
        self.assertIn("screener", names)
        self.assertIn("verifier", names)
        self.assertEqual(main.SCREENER_MODEL, "mistral-small-2603")
        self.assertEqual(main.VERIFIER_MODEL, "mistral-large-4-0")
        self.assertEqual(main.MAX_CONCURRENT_SUBTURNS, 10)
        pol = getattr(main.agent, "subagent_policy", None)
        self.assertIsNotNone(pol)
        self.assertEqual(pol.concurrent_child_turn_limit, 10)

    def test_subagenten_hooks_ohne_ablage_summary(self):
        for s in (main.screener_subagent, main.verifier_subagent):
            hk = (getattr(s, "hooks", None) or [None])[0]
            self.assertIsNotNone(hk)
            self.assertFalse(hk.enforce_ablage_pflicht)
            self.assertFalse(hk.write_session_summary)
            self.assertTrue(hk.check_urls)

    def test_subagenten_keine_note_tools(self):
        for s in (main.screener_subagent, main.verifier_subagent):
            tnames = {getattr(t, "tool_definition", None) and getattr(t.tool_definition, "name", "") or getattr(t, "name", "") for t in (getattr(s, "tools", None) or [])}
            self.assertNotIn("research_note_ablegen", tnames)
            self.assertNotIn("research_note_aktualisieren", tnames)

    def test_skills_gepinnt(self):
        import uuid as _uuid
        self.assertEqual(len(main.PINNED_SKILLS), 19)
        for sid, v in main.PINNED_SKILLS:
            _uuid.UUID(sid)
            self.assertGreaterEqual(v, 1)
        self.assertEqual(len(main._SKILLS), 19)

    def test_sandbox_default_mistral(self):
        self.assertEqual(main._SANDBOX_KIND, "mistral")
        self.assertEqual(type(main._AGENT_ENVIRONMENT).__name__, "MistralSandbox")

    def test_instructions_neue_bloecke(self):
        with open(main.__file__, encoding="utf-8") as _f:
            s = _f.read()
        self.assertIn("SUBAGENTEN-DELEGATION", s)
        self.assertIn("PROJEKT-/FACHKONTEXT", s)
        self.assertIn("PRO CLAIM", s)
        self.assertIn("license_access", s)
        self.assertIn("Hook-Durchsetzung", s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
