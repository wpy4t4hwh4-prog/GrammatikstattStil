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
        self.assertEqual(self.hook.rep_streak, 1)
        res2 = self._post(wellig)
        self.assertIsNotNone(res2)  # zweite Welle -> Reject
        self.assertTrue(self.hook.turn_rejected)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
