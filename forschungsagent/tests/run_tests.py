"""Offline-Tests fuer den Forschungsagenten (Hook-Logik, Caches, HTTP-Retry, statische Checks).

Run: uv run python tests/run_tests.py  (aus forschungsagent/)
Keine Netzwerk- oder API-Calls.
"""
import asyncio
import json
import os
import re
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
        # RCA R5: nur parsebare Answer-Bloecke zaehlen; einzelner Block ok, kumulativ 2 -> Retry, 3 -> Reject
        b1 = '```json\n{"zusammenfassung": "A"}\n```'
        b2 = '```json\n{"zusammenfassung": "B"}\n```'
        r0 = self._post(b1)
        self.assertIsNone(r0)  # einzelner Answer-Block ist ok
        self.assertEqual(self.hook.turn_fences, 1)
        r1 = self._post(b2)
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
            "belegte_aussagen": [{"aussage": "a%d" % i, "quelle": "q", "evidenzgrad": "wahrscheinlich"} for i in range(2)],
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

    def test_schema_schlank_notiz_id(self):
        # F4: Protokoll-Listen raus aus output_type, dafuer notiz_id
        self.assertIn("notiz_id: str", self.src)
        self.assertNotIn("verifizierungsquote: float", self.src)
        self.assertNotIn("belegte_aussagen: list[BelegteAussage]", self.src)
        self.assertNotIn("quellen: list[SourceRecord]", self.src)
        self.assertNotIn("double_check: list[DoubleCheck]", self.src)
        self.assertNotIn("verbatim_zitate: list[VerbatimZitat]", self.src)
        self.assertIn("notiz_id nicht aus research_note_ablegen Tool-Ausgabe", self.src)

    def test_provenance_header(self):
        self.assertIn("Erstellt mit: Forschungsagent grammatik-statt-stil-research", self.src)

    def test_self_eval_in_background_check(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "background_check.py"), encoding="utf-8") as _f:
            bc = _f.read()
        self.assertIn("SELF_EVAL_TASK", bc)
        self.assertIn("_task_for_today()", bc)
        self.assertIn("selbst-eval-", bc)

    def test_background_check_uses_startprompt_v4(self):
        # Automatisierung schickt den Start-Prompt v4 (Variante A) als User-Message
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "background_check.py"), encoding="utf-8") as _f:
            bc = _f.read()
        self.assertIn('Session-Start für den Forschungsagenten "Grammatik statt Stil"', bc)
        self.assertIn("SESSION-START-REGEL (schlank)", bc)
        self.assertIn('projektdateien_auflisten(library="research_ablage_agent", search="00-projektstand")', bc)
        self.assertIn("Umfangsarbeit (Bulk-Screening)", bc)
        self.assertIn("GESAMTES JSON max. 3000 Zeichen", bc)
        self.assertIn("notiz_id", bc)
        self.assertIn("2x taeglich, 06:00 und 17:00 Europe/Vienna", bc)

    def test_workflow_vienna_gate_2x_taeglich(self):
        wf = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".github", "workflows", "agent-daily-check.yml")
        with open(wf, encoding="utf-8") as _f:
            y = _f.read()
        self.assertIn('cron: "0 * * * *"', y)
        self.assertIn("TZ=Europe/Vienna", y)
        self.assertIn('"$H" = "06"', y)
        self.assertIn('"$H" = "17"', y)
        self.assertIn("steps.gate.outputs.run == 'yes'", y)
        self.assertNotIn("0 6,11,16,21", y)  # alte 4x-taeglich-Automatisierung ersetzt

    def test_background_check_retry_mit_frischer_session(self):
        # Cron-Fix: bei invalid_command/HarnessCommandRejectedError einmal Retry mit NEUER Session
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "background_check.py"), encoding="utf-8") as _f:
            bc = _f.read()
        self.assertIn("def _run_once(agent)", bc)
        self.assertGreaterEqual(bc.count("agent.start_session()"), 1)
        self.assertIn("for attempt in (1, 2):", bc)
        self.assertIn("invalid_command", bc)
        self.assertIn("HarnessCommandRejectedError", bc)
        self.assertIn("await asyncio.sleep(5)", bc)

    def test_aktualisieren_deletes_predecessor(self):
        self.assertIn("delete_async(library_id=NOTES_LIBRARY_ID, document_id=document_id)", self.src)

    def test_lizenzfeld_present(self):
        self.assertIn("license_access: lizenz/zugang/abgerufen_am", self.src)  # R6: konsolidierter Ablage-Block
        self.assertNotIn("KI-Nutzung: mit KI-Assistenz", self.src)


class SessionStartRegelTests(unittest.TestCase):
    def test_session_start_regel_robust(self):
        with open(main.__file__, encoding="utf-8") as _f:
            s = _f.read()
        # O1/O2/O4: schlanker Start ueber serverseitig gefiltertes Listing (statt Volllisting + RAG-Pflichtcall)
        self.assertIn('projektdateien_auflisten(library="research_ablage_agent", search="00-projektstand")', s)
        self.assertIn("FALLBACK", s)  # ablage_durchsuchen nur noch als Fallback
        self.assertIn("NIEMALS eine ID raten", s)
        self.assertIn("NICHT blind ein neues Projektstand-Dokument anlegen", s)
        self.assertIn("GENAU EINES", s)


class _FakeDoc:
    def __init__(self, name, id):
        self.name = name
        self.id = id
        self.extension = "md"
        self.processing_status = "ok"


class SessionStartOptTests(unittest.TestCase):
    """O1/O2/O4: projektdateien_auflisten/bibliotheken_auflisten mit library=/search=-Filter."""

    def setUp(self):
        self._old_client = main._client
        self.calls = []
        docs = {
            main.NOTES_LIBRARY_ID: [_FakeDoc("00-projektstand.md", "id-stand"), _FakeDoc("andere-notiz.md", "id-x")],
            main.PROJECT_LIBRARY_ID: [_FakeDoc("projekt-doc.md", "id-p")],
        }
        calls = self.calls

        class Docs:
            async def list_async(self, **kw):
                calls.append(("docs", kw))
                data = docs.get(kw.get("library_id"), [])
                if kw.get("search"):
                    data = [d for d in data if kw["search"].lower() in (d.name or "").lower()]
                return types.SimpleNamespace(data=data)

        class Libs:
            documents = Docs()

            async def list_async(self, **kw):
                calls.append(("libs", kw))
                return types.SimpleNamespace(data=[types.SimpleNamespace(id=main.NOTES_LIBRARY_ID, name="Research-Ablage")])

        class Beta:
            libraries = Libs()

        class C:
            beta = Beta()

        main._client = lambda: C()

    def tearDown(self):
        main._client = self._old_client

    def test_signaturen_haben_filter(self):
        import inspect
        sig = inspect.signature(main.projektdateien_auflisten.input_model)
        self.assertIn("library", sig.parameters)
        self.assertIn("search", sig.parameters)
        sig2 = inspect.signature(main.bibliotheken_auflisten.input_model)
        self.assertIn("search", sig2.parameters)

    def test_gefiltertes_listing_nur_eine_library_und_search_weitergereicht(self):
        f = main.projektdateien_auflisten
        res = asyncio.run(f.handler(args=f.input_model(library="research_ablage_agent", search="00-projektstand")))
        self.assertEqual(list(res.keys()), ["research_ablage_agent"])
        self.assertEqual([d["name"] for d in res["research_ablage_agent"]], ["00-projektstand.md"])
        doc_calls = [kw for kind, kw in self.calls if kind == "docs"]
        self.assertEqual(len(doc_calls), 1)
        self.assertEqual(doc_calls[0]["library_id"], main.NOTES_LIBRARY_ID)
        self.assertEqual(doc_calls[0].get("search"), "00-projektstand")

    def test_default_listet_alle_vier_libraries_ohne_search(self):
        f = main.projektdateien_auflisten
        res = asyncio.run(f.handler(args=f.input_model()))
        self.assertEqual(set(res.keys()), {
            "grammatik_statt_stil_bibliothek", "katalogstadt_emerging_fields",
            "research_ablage_agent", "apparat_bibliothek",
        })
        doc_calls = [kw for kind, kw in self.calls if kind == "docs"]
        self.assertEqual(len(doc_calls), 4)
        self.assertTrue(all("search" not in kw for kw in doc_calls))

    def test_unbekannte_library_gibt_fehler_dict(self):
        f = main.projektdateien_auflisten
        res = asyncio.run(f.handler(args=f.input_model(library="quatsch")))
        self.assertIn("fehler", res)
        self.assertEqual([c for c in self.calls if c[0] == "docs"], [])

    def test_bibliotheken_auflisten_search_weitergereicht(self):
        b = main.bibliotheken_auflisten
        res = asyncio.run(b.handler(args=b.input_model(search="Ablage")))
        self.assertEqual(res["bibliotheken"][0]["id"], main.NOTES_LIBRARY_ID)
        lib_calls = [kw for kind, kw in self.calls if kind == "libs"]
        self.assertEqual(lib_calls[-1].get("search"), "Ablage")

    def test_kein_neues_tool_dunguard_count_bleibt_19(self):
        with open(main.__file__, encoding="utf-8") as _f:
            s = _f.read()
        self.assertEqual(s.count("@_tool_guard\n@agents.tool"), 19)


class AblageInkrementellTests(unittest.TestCase):
    """Optionen 1+2: inkrementelle Ablage + Splitten grosser Aufgaben (Turn-Limit-sicher)."""

    def test_ablage_pflicht_inkrementell_und_split(self):
        with open(main.__file__, encoding="utf-8") as _f:
            s = _f.read()
        self.assertIn("INKREMENTELL ABLEGEN", s)
        self.assertIn("SOFORT ab, sobald substantielle Befunde vorliegen", s)
        self.assertIn("GENAU EINE Notiz", s)                                  # R3: eine Notiz pro Turn
        self.assertIn("research_note_aktualisieren IM SELBEN Dokument", s)     # R3: Updates im selben Dokument
        self.assertIn("Grosse Aufgaben SPLITTEN auf die Turn-/Session-Grenze", s)  # R3: Splitten auf Turn-Grenze
        self.assertIn("Turn-Limit-Stopp (Hook-Reject ab Iteration 17/18)", s)
        self.assertIn("max. 10 Zeilen", s)                                     # R2: kompaktes Protokoll
        self.assertIn("max. ca. 4000 Zeichen", s)                              # R2: Notiz-Laenge gedeckelt
        self.assertIn("ABLAGE & PROTOKOLL (verbindlich)", s)                   # R6: konsolidierter Block
        self.assertNotIn("Laborbuch", s)                                       # R6: Laborbuch-Formulierung entfernt
        self.assertNotIn("eine Notiz pro Position/Abschnitt", s)               # R6: alte Schritt-5-Doppelung entfernt

    def test_iterationslimit_hook_bleibt_17_18(self):
        with open(main.__file__, encoding="utf-8") as _f:
            s = _f.read()
        self.assertIn("self.llm_calls >= 17", s)
        self.assertIn("Iterationslimit (17/18) erreicht", s)

    def test_kurze_kernzusammenfassung_caps_500_800(self):
        with open(main.__file__, encoding="utf-8") as _f:
            s = _f.read()
        # Hook-Caps hart auf 500/800 heruntergesetzt
        self.assertIn('zusammenfassung zu lang (>500 Zeichen)', s)
        self.assertIn('arbeitsupdate zu lang (>800 Zeichen)', s)
        self.assertIn('len(str(data.get("zusammenfassung", ""))) > 500', s)
        self.assertIn('len(str(data.get("arbeitsupdate", ""))) > 800', s)
        # Regeltext: eigene Kernzusammenfassung, KEIN Tool-/Quellen-Protokoll in der Antwort
        self.assertIn("zusammenfassung max. 500 Zeichen, arbeitsupdate max. 800 Zeichen", s)
        self.assertIn("KEINE Aufzaehlung von Tool-Calls, Quellen-IDs, DOIs, URLs", s)


class AntwortKurzCapsTests(unittest.TestCase):
    """Anti-Endlos: GESAMTES JSON max 6000 Zeichen + Listen-Caps (Hook-QA)."""

    def setUp(self):
        self._old = main._SDK_RETRY_BASE
        main._SDK_RETRY_BASE = 0.0
        self.hook = main.QuoteAuditHook()
        asyncio.run(self.hook.pre_agent_turn(None, None))

    def tearDown(self):
        main._SDK_RETRY_BASE = self._old

    def _post(self, payload):
        return asyncio.run(self.hook.post_llm_call(None, _reply(json.dumps(payload), None)))

    def test_gesamtlaenge_json_cap_6000(self):
        payload = {"zusammenfassung": "ok", "arbeitsupdate": "ok", "belegte_aussagen": [], "double_check": [],
                   "verifizierungsquote": 1.0, "offene_punkte": ["z" * 700] * 10}
        res = self._post(payload)
        self.assertIsNotNone(res)
        self.assertIn("gesamte JSON-Antwort zu lang", str(getattr(res, "message", res)))

    def test_listen_caps(self):
        payload = {"zusammenfassung": "ok", "arbeitsupdate": "ok",
                   "offene_punkte": ["p"] * 6, "notiz_id": ""}
        res = self._post(payload)
        self.assertIsNotNone(res)
        self.assertIn("offene_punkte hat 6 Eintraege (max 5)", str(getattr(res, "message", res)))

    def test_kurze_antwort_mit_begrenzten_listen_ok(self):
        payload = {"zusammenfassung": "ok", "arbeitsupdate": "ok", "belegte_aussagen": [], "double_check": [],
                   "verifizierungsquote": 1.0, "offene_punkte": ["p1", "p2"], "quellen": [], "deutungen": [], "verbatim_zitate": []}
        self.assertIsNone(self._post(payload))

    def test_statische_caps_im_quelltext(self):
        with open(main.__file__, encoding="utf-8") as _f:
            s = _f.read()
        self.assertIn("len(text) > 3000", s)
        self.assertIn('(("offene_punkte", 5),)', s)
        self.assertIn("GESAMTES JSON max. 3000 Zeichen", s)
        self.assertIn("ergebnis\", \"\"))) > 200", s)
        self.assertIn("_dc_ges > 1500", s)


class LoopFixB3Tests(unittest.TestCase):
    """B3-Optionen (a),(b),(d),(e): Transparency-Klarstellung, Tool-Result-Caps, Retry-Feedback top3, qa-stats-Logging."""

    def setUp(self):
        with open(main.__file__, encoding="utf-8") as _f:
            self.src = _f.read()

    def test_a_transparency_klarstellung(self):
        self.assertIn("EIGENE fruehere Assistant-Nachricht im selben Turn", self.src)
        self.assertIn("die LETZTE Nachricht des Turns ist AUSSCHLIESSLICH das nackte JSON", self.src)

    def test_b_tool_result_caps(self):
        self.assertIn("Default 8000, max 12000", self.src)          # webseite_lesen
        self.assertIn("min(max(max_zeichen, 500), 12000)", self.src)
        self.assertIn("text[:8000]", self.src)                        # pdf_ocr
        self.assertIn("pdf_in_ablage_speichern + in_dokument_suchen", self.src)

    def test_d_retry_feedback_top3(self):
        self.assertIn('" | ".join(problems[:3])', self.src)
        self.assertIn('(+%d weitere)', self.src)

    def test_e_qa_stats_logging(self):
        self.assertIn('logger.info("qa-stats llm_calls=%d text_len=%d', self.src)

    def test_iterationslimit_bleibt_18(self):
        self.assertIn("max_iterations=18", self.src)  # Option (c): 18 halten, keine Aenderung




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
        payload = json.dumps({"zusammenfassung": "ok", "arbeitsupdate": "x" * 801, "belegte_aussagen": [], "double_check": [], "verifizierungsquote": 1.0})
        res = self._post(payload)
        self.assertIsNotNone(res)
        self.assertIn("zu lang", str(getattr(res, "message", res)))

    def test_zusammenfassung_zu_lang_retry(self):
        import json
        payload = json.dumps({"zusammenfassung": "x" * 501, "arbeitsupdate": "kurz", "belegte_aussagen": [], "double_check": [], "verifizierungsquote": 1.0})
        res = self._post(payload)
        self.assertIsNotNone(res)

    def test_kurze_antwort_ok(self):
        import json
        payload = json.dumps({"zusammenfassung": "x" * 500, "arbeitsupdate": "y" * 800, "belegte_aussagen": [], "double_check": [], "verifizierungsquote": 1.0})
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
                {"aussage": "Die Wiener Ringstrasse wurde 1865 eroeffnet", "quelle": "q", "evidenzgrad": "wahrscheinlich"},
            ],
            "double_check": [],
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

    def test_doublecheck_ergebnis_zu_lang_wird_flagged(self):
        # Protokoll-Kurzregel: nur Kurzergebnis in der Antwort, Langprotokoll -> Ablage-Notiz
        import json
        asyncio.run(self.hook.post_tool_call(None, self._tool_res("research_note_ablegen", "ok")))
        payload = json.dumps({
            "zusammenfassung": "x",
            "belegte_aussagen": [{"aussage": "a", "quelle": "q", "evidenzgrad": "wahrscheinlich"}],
            "double_check": [{"angabe": "a", "pruef_tool": "web_zitat_pruefen", "ergebnis": "protokoll " * 100}],
            "verifizierungsquote": 1.0,
        })
        r = self._post(payload)
        self.assertIsNotNone(r)
        self.assertIn("zu lang", str(getattr(r, "message", r)))

    def test_client_timeout_300(self):
        with open(main.__file__, encoding="utf-8") as _f:
            s = _f.read()
        self.assertIn("timeout=300", s)

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
        self.assertIn("VOLLSTAENDIGE Nachweis", s)  # F1: Nachweis in der Ablage-Notiz
        self.assertIn("license_access: lizenz/zugang/abgerufen_am", s)
        self.assertIn("Hook-Durchsetzung", s)
        self.assertIn("Umfangsarbeit (Bulk-Screening", s)  # Begriff statt "Masse"
        self.assertNotIn("Masse-Arbeit", s)
        self.assertNotIn("Masse ", s)

class RcaAblageLoopTests(unittest.TestCase):
    """RCA 2026-11-25 (Dokument 48b8aba1): Endlos-Loop der Abschlussantwort - R1-R8."""

    def setUp(self):
        self.hook = main.QuoteAuditHook()
        asyncio.run(self.hook.pre_agent_turn(None, None))

    def _post(self, text="", tool_calls=None):
        return asyncio.run(self.hook.post_llm_call(None, _reply(text, tool_calls)))

    def test_deg_woerter_in_langem_forschungstext_kein_reject(self):
        # R4: 'abgeschlossen/beendet/...' in normaler langer Antwort ist KEIN degenerativer Loop
        lang = ("Die Kollation der Zahllesart ist abgeschlossen; die Pruefung wurde beendet. " * 8) + "x" * 100
        self.assertGreater(len(lang), 300)
        res = self._post(lang)
        self.assertIsNone(res)
        self.assertFalse(self.hook.turn_rejected)

    def test_deg_kurztext_weiterhin_reject(self):
        res = self._post("Fertig. Ende. Done. Stop.")
        self.assertIsNotNone(res)
        self.assertTrue(self.hook.turn_rejected)

    def test_prosa_erwaehnung_zusammenfassung_zaehlt_nicht(self):
        # R5: blosse Prosa-Erwaehnung des Feldnamens (kein parsebares JSON) ist kein Answer-Block
        res = self._post('Im JSON heisst das Feld "zusammenfassung" und bleibt kurz.')
        self.assertIsNone(res)
        self.assertEqual(self.hook.turn_fences, 0)

    def test_ein_parsebarer_answer_block_pro_turn_ok(self):
        import json
        b1 = '```json\n' + json.dumps({"zusammenfassung": "A"}) + '\n```'
        self.assertIsNone(self._post(b1))
        self.assertEqual(self.hook.turn_fences, 1)

    def test_zwei_answer_bloecke_welle_retry(self):
        import json
        b = '```json\n' + json.dumps({"zusammenfassung": "A"}) + '\n```'
        self.assertIsNone(self._post(b))
        r = self._post(b)
        self.assertIsNotNone(r)  # kumulativ 2 -> Retry
        self.assertEqual(self.hook.wave_streak, 1)

    def test_schema_arbeitsupdate_schlank(self):
        # R1: Feldbeschreibung verlangt kein Protokoll mehr in der Antwort
        with open(main.__file__, encoding="utf-8") as _f:
            s = _f.read()
        self.assertNotIn("was in diesem Turn recherchiert/gelesen/abgelegt wurde", s)
        self.assertIn("KEIN Tool-/Quellen-Protokoll", s)

    def test_reject_reason_wird_geloggt(self):
        # R8: _reject loggt den Grund; alter Test-String bleibt erhalten
        with open(main.__file__, encoding="utf-8") as _f:
            s = _f.read()
        self.assertIn('logger.warning("hook reject")', s)
        self.assertIn("def _reject(self, reason: str, msg: str):", s)
        self.assertIn("reject_reason=", s)

    def test_retry_feedback_mit_limits(self):
        # R7: praezises, kurzes Retry-Feedback mit harten Limits
        with open(main.__file__, encoding="utf-8") as _f:
            s = _f.read()
        self.assertIn("FIXEN:", s)
        self.assertIn("zusammenfassung <=500 Z.", s)
        self.assertIn("arbeitsupdate <=800 Z.", s)
        self.assertIn("JSON gesamt <=3000 Z.", s)

    def test_background_check_eine_notiz_pro_turn(self):
        import os
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "background_check.py"), encoding="utf-8") as _f:
            bc = _f.read()
        self.assertIn("Pro Turn GENAU EINE Notiz", bc)


class StartPromptV5Tests(unittest.TestCase):
    """Start-Prompt v5 (RCA 48b8aba1, R1-R8): background_check.TASK ist byte-gleich Variante A des v5-Dokuments."""

    def _bc(self):
        import os
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "background_check.py"), encoding="utf-8") as _f:
            return _f.read()

    def test_task_ist_v5_variante_a(self):
        bc = self._bc()
        for needle in ["Start-Prompt v5", "Pro Turn GENAU EINE Notiz",
                       "research_note_aktualisieren IM SELBEN DOKUMENT", "Turn-/Session-Grenze",
                       "max. ca. 4000 Zeichen", "max. 10 Zeilen", "KÜRZEN/FIXEN"]:
            self.assertIn(needle, bc)
        self.assertNotIn("pro Position/Teilschritt eigene Notiz", bc)  # alte v4-Formulierung entfernt
        self.assertNotIn("Start-Prompt v4", bc)

    def test_task_keep_teststrings(self):
        # bestehende Assertions von test_background_check_uses_startprompt_v4 bleiben gueltig
        bc = self._bc()
        for needle in ['Session-Start für den Forschungsagenten "Grammatik statt Stil"',
                       "SESSION-START-REGEL (schlank)",
                       'projektdateien_auflisten(library="research_ablage_agent", search="00-projektstand")',
                       "Umfangsarbeit (Bulk-Screening)", "GESAMTES JSON max. 3000 Zeichen",
                       "notiz_id", "2x taeglich, 06:00 und 17:00 Europe/Vienna"]:
            self.assertIn(needle, bc)


class PwaAppTests(unittest.TestCase):
    """Dashboard als installierbare App (PWA) + Port des verfeinerten Dashboards (2026-11-26):
    Manifest vollstaendig, iOS-Meta, SW v29 App-Shell (navigate network-first, Token-Bypass),
    Deep-Links, serve.py (Token-Auth, Whitelist, Agent-Control-Plane), keine echten Daten/Secrets im Repo."""

    def _dash(self):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/../dashboard'

    def _read(self, rel):
        with open(os.path.join(self._dash(), rel), encoding='utf-8') as _f:
            return _f.read()

    def test_manifest_install_kriterien(self):
        import json
        m = json.loads(self._read('manifest.webmanifest'))
        self.assertIn('name', m) and self.assertIn('short_name', m)
        self.assertEqual(m['display'], 'standalone')
        self.assertIn('start_url', m) and self.assertIn('scope', m)
        self.assertEqual(m.get('id'), './')
        self.assertFalse(m.get('prefer_related_applications', False))
        self.assertIn('standalone', m.get('display_override', []))
        self.assertTrue(m.get('categories'), 'categories fehlen')
        sizes = {i['sizes'] for i in m['icons']}
        self.assertIn('192x192', sizes) and self.assertIn('512x512', sizes)
        self.assertTrue(any(i.get('purpose') == 'maskable' for i in m['icons']))
        self.assertTrue(m.get('shortcuts'), 'App-Shortcuts fehlen')
        tabs = set()
        for sc in m['shortcuts']:
            self.assertIn('url', sc) and self.assertIn('name', sc)
            self.assertIn('tab=', sc['url'])
            tabs.add(sc['url'].split('tab=')[1])
        self.assertEqual(tabs, {'verzeichnis', 'pruef', 'ablage', 'komm'})

    def test_index_ios_meta_und_deeplink(self):
        s = self._read('index.html')
        self.assertIn('apple-mobile-web-app-capable', s)
        self.assertIn('apple-touch-icon', s)
        self.assertIn('name="theme-color"', s)
        self.assertIn('rel="manifest"', s)
        self.assertIn('[?&]tab=', s)          # Deep-Link ?tab= aus App-Shortcuts
        self.assertIn('#tab=', s)
        self.assertIn('data-page="ablage"', s) and self.assertIn('data-page="komm"', s)
        self.assertEqual(s.count('<script'), 1)      # self-contained: genau ein Inline-Skript
        self.assertEqual(s.count('</script'), 1)
        body = s.split('<script>')[1].split('</script>')[0]
        self.assertNotIn('<script', body.lower())     # PR-#17-Regression
        nav_html = s.split('<body')[1].split('<script>')[0]
        self.assertEqual(len(re.findall(r'data-page="[a-z]+"', nav_html)), 9)

    def test_index_ios_safari_optimierung(self):
        """iPhone/Safari-Audit (Review 2026-11-26): Viewport, Safe-Area, Touch, Zoom, Standalone."""
        s = self._read('index.html')
        # Viewport: viewport-fit=cover + interactiveWidget, aber KEIN Zoom-Block (Accessibility)
        m = re.search(r'<meta name="viewport" content="([^"]*)"', s)
        self.assertIsNotNone(m)
        vp = m.group(1)
        self.assertIn('viewport-fit=cover', vp)
        self.assertIn('interactiveWidget=resizes-content', vp)   # iOS-Tastatur schrumpft Layout-Viewport
        self.assertNotRegex(vp, r'maximum-scale=1|user-scalable=no')
        # iOS-Metas
        for meta in ('apple-mobile-web-app-capable', 'mobile-web-app-capable',
                     'apple-mobile-web-app-status-bar-style', 'apple-mobile-web-app-title',
                     'format-detection'):
            self.assertIn('name="%s"' % meta, s)
        self.assertIn('content="telephone=no"', s)
        self.assertIn('rel="apple-touch-icon"', s)
        self.assertIn('name="color-scheme" content="light dark"', s)
        # Safe-Area an allen kritischen Stellen
        self.assertGreaterEqual(len(re.findall(r'env\(safe-area-inset', s)), 4)
        self.assertIn('padding-top: env(safe-area-inset-top)', s)
        # Safari-Quirks
        self.assertIn('-webkit-backdrop-filter', s)
        self.assertIn('-webkit-tap-highlight', s)
        self.assertIn('-webkit-text-size-adjust', s)
        self.assertIn("typeof d.showModal === 'function'", s)     # dialog-Fallback Safari < 15.4
        self.assertIn("'serviceWorker' in navigator", s)           # SW-Registrierung ge guarded
        self.assertIn('overscroll-behavior-y: none', s)            # kein Pull-to-Refresh-Reload im Standalone
        self.assertIn('touch-action: manipulation', s)             # kein Doppel-Tipp-Zoom
        # Coarse-Pointer (Touch): 16px-Inputs gegen iOS-Auto-Zoom, 44px-Touch-Targets
        coarse = re.search(r'@media \(pointer: coarse\) \{(.*?)\n  \}', s, re.S)
        self.assertIsNotNone(coarse)
        self.assertRegex(coarse.group(1), r'font-size:\s*16px')
        self.assertRegex(coarse.group(1), r'min-height:\s*44px')
        # dvh-Fallback ( dynamischer Viewport auf iOS )
        self.assertIn('dvh', s)
        # vh nur als Fallback, immer mit dvh-Override (iOS-Adressleisten-Problem)
        self.assertIn('100dvh', s)
        self.assertEqual(s.count('100vh'), s.count('100dvh'))
        # Sprache
        self.assertIn('<html lang="de">', s)
        # jsdom-iPhone-Render-Test liegt als Tool bereit
        self.assertTrue(os.path.exists(os.path.join(self._dash(), 'tools/iphone_render_test.js')))

    def test_komm_tab_apple_hig(self):
        """Komm-Tab Redesign (Apple HIG): iMessage-Pattern, Segmented Control, Sheet auf mobil, Gruppierung, a11y."""
        s = self._read('index.html')
        # Composer: genau ein runder Send-Button, alte Doppel-Buttons entfernt
        self.assertIn('id="sendBtn" class="sendbtn"', s)
        self.assertNotIn('sendAgentBtn', s)
        self.assertEqual(s.count('id="msgInput"'), 1)
        self.assertEqual(s.count('id="thread"'), 1)
        # Segmented Control Zielwahl + Session-Toggle
        self.assertIn('id="segLocal"', s) and self.assertIn('id="segAgent"', s)
        self.assertIn('id="btnSessToggle"', s)
        # Thread als log + aria
        self.assertIn('id="thread" role="log" aria-live="polite"', s)
        # Nachrichten-Gruppierung + Bubble-Tail + Typing
        self.assertIn('.msg + .msg.cont', s)
        self.assertIn('.msg.cont .who { display: none; }', s)
        self.assertIn('border-bottom-right-radius: 6px', s)
        self.assertIn('.typing span', s)
        # Chat fuellt Viewport (dvh mit vh-Fallback), Thread flex
        self.assertIn('calc(100dvh - var(--header-h-live', s)
        self.assertIn('#page-komm .thread { padding: 12px; gap: 8px; }', s)
        # Mobil: Session-Sheet statt Spalten-Stack
        self.assertRegex(s, r'@media \(max-width: 940px\) \{[\s\S]*?\.kommgrid\.show-sess \.session \{ display: flex; \}')
        self.assertIn('.sess-toggle { display: none; }', s)
        # Apple-exact Accent light (#007aff), dark behaelt #0a84ff
        self.assertIn('--accent: #007aff;', s)
        # Toast/Fokus safe-area + focus-visible
        self.assertIn('bottom: calc(28px + env(safe-area-inset-bottom))', s)
        self.assertIn(':focus-visible', s)
        # JS-Wiring
        self.assertIn('let destMode', s)
        self.assertIn("destMode === 'agent' ? sendAgent() : sendLocal()", s)
        self.assertIn('showStream(streamText, !!pendingCmd)', s)
        self.assertIn("classList.toggle('show-sess')", s)
        # v2 (iPhone): Bedienelemente IM Composer-Container, Chat-Head nur Titel+Count
        self.assertGreater(s.find('id="segLocal"'), s.find('class="chathead-right"'))  # seg NICHT im Header, sondern im Composer
        self.assertIn('class="composer-row"', s)
        self.assertIn('class="composer-bar"', s)
        cpos = s.find('<div class="composer">')
        self.assertGreater(s.find('id="segLocal"'), cpos)          # Segmented Control im Composer
        self.assertGreater(s.find('id="sendStatus"'), cpos)         # Status-Hinweis im Composer
        hp = s.find('class="chathead"')
        self.assertGreater(s.find('id="btnSessToggle"'), hp)           # Session-Toggle als trailing Nav-Button im Chat-Head
        self.assertLess(s.find('id="btnSessToggle"'), cpos)             # ... NICHT mehr im Composer
        # Glossar: zentrierte Spalte + mobil gestapelt
        self.assertIn('.glossar { grid-template-columns: 1fr; max-width: 760px; margin: 0 auto; }', s)
        self.assertIn('.glossar .card { flex-direction: column; align-items: flex-start; gap: 4px; }', s)
        self.assertIn('.glossar .begriff { min-width: 0; }', s)
        # Tastatur/Eventualitäten: visualViewport-Handler + Landscape-Regel + kompaktes seg
        self.assertIn('visualViewport', s)
        self.assertIn('@media (max-height: 500px) { .chat { min-height: 0; } }', s)
        self.assertIn('#page-komm .seg button { padding: 4px 10px; font-size: 11px; min-height: 28px; }', s)
        self.assertGreater(s.find('id="sendBtn"'), s.find('composer-row'))
        # Header-Höhe live gemessen (iPhone-Header wrappt auf 2 Zeilen)
        self.assertIn('--header-h-live', s)
        self.assertIn('function syncHeaderH()', s)
        self.assertIn('var(--header-h-live, var(--header-h))', s)
        # 4px-Raster mobil (Schrittgrößen)
        self.assertIn('#page-komm .card { padding: var(--sp-4); }', s)
        self.assertIn('#page-komm .thread { padding: 12px; gap: 8px; }', s)
        self.assertIn('main.wrap { padding-top: var(--sp-4);', s)
        # weiterhin self-contained: genau ein Skript-Tag
        self.assertEqual(s.count('<script'), 1)
        self.assertEqual(s.count('</script'), 1)


    def test_serve_py_security_haertung(self):
        """Security-Härtung serve.py: fail-closed Host/Token, Log-Redaction, compare_digest, Security-Header."""
        serve = self._read('serve.py')
        # fail-closed: non-loopback ohne Token -> exit 2
        self.assertIn('sys.exit(2)', serve)
        self.assertRegex(serve, r'_loopback = args\.host in \("127\.0\.0\.1"')
        self.assertIn('if not _loopback and not HUB_TOKEN:', serve)
        # Token im Access-Log redacten
        self.assertIn('token=[REDACTED]', serve)
        self.assertIn('_access_log', serve)
        # konstant-zeitlicher Vergleich
        self.assertIn('hmac.compare_digest', serve)
        # Security-Header in allen Antwort-Pfaden (_json, _file, _download rufen _sec)
        self.assertIn('def _sec(self):', serve)
        self.assertEqual(serve.count('self._sec()'), 3)
        self.assertIn('"X-Frame-Options", "DENY"', serve)
        self.assertIn('"Referrer-Policy", "no-referrer"', serve)
        self.assertIn('"Permissions-Policy", "camera=(), microphone=(), geolocation=()"', serve)
        self.assertIn("frame-ancestors 'none'; base-uri 'none'; form-action 'self'", serve)
        # CSP darf das self-contained Inline-Skript nicht blocken (kein script-src ohne unsafe-inline)
        csp = re.search(r'Content-Security-Policy", "([^"]+)"', serve).group(1)
        self.assertNotIn('script-src', csp)

    def test_sw_v30_app_shell(self):
        sw = self._read('sw.js')
        self.assertIn("const CACHE = 'research-hub-v30';", sw)
        self.assertIn('HAS_TOKEN', sw)                               # /data/* mit Token nie cachen
        self.assertIn("url.pathname.startsWith('/data/')", sw)
        self.assertIn('icon-512-maskable.png', sw)                 # maskable Icon precachen
        self.assertIn('data/templates.json', sw)
        self.assertIn("e.request.mode === 'navigate'", sw)         # App-Shell: Navigation network-first
        self.assertIn("caches.match('index.html')", sw)             # Offline-Fallback Shell
        self.assertIn("url.searchParams.has('token')", sw)          # Token-URLs nie cachen
        self.assertIn("url.pathname.startsWith('/api/')", sw)       # API network-first + GET-Cache

    def test_serve_py_refined_port(self):
        import py_compile
        serve = self._read('serve.py')
        py_compile.compile(os.path.join(self._dash(), 'serve.py'), doraise=True)
        self.assertGreater(len(serve), 60000)                       # verfeinerter Server (~64,7 KB)
        self.assertIn('STATIC_SUFFIXES', serve)
        m = re.search(r'STATIC_SUFFIXES\s*=\s*\{([^}]*)\}', serve)
        self.assertIsNotNone(m)
        self.assertNotIn('".py"', m.group(1))                       # Quellcode nicht auslieferbar
        self.assertIn('".."', serve)                                # Traversal-Guard
        self.assertIn('def _check_token', serve)
        self.assertIn('"/api/"', serve) and self.assertIn('"/data/"', serve)  # Token schuetzt API+Data
        self.assertIn('X-Hub-Token', serve)
        self.assertIn('1000000', serve)                             # Body-Cap 1 MB
        for ep in ('/api/agent/send', '/api/agent/stop', '/api/agent/archive', '/api/agent/reset',
                   '/api/agent/history', '/api/agent/sessions', '/api/agent/pending',
                   '/api/qv/snapshots', '/api/dupes', '/api/pruef', '/api/coverage',
                   '/api/import', '/api/qv/export', '/api/meta', '/api/historie'):
            self.assertIn(ep, serve)
        for t in ('tools/start.sh', 'tools/smoke_test.py', 'tools/upload_dashboard.py',
                  'tools/import_apparat.py', 'tools/make_icons.py'):
            self.assertTrue(os.path.exists(os.path.join(self._dash(), t)), t + ' fehlt')
        for t in ('tools/smoke_test.py', 'tools/upload_dashboard.py', 'tools/import_apparat.py',
                  'tools/make_icons.py'):
            py_compile.compile(os.path.join(self._dash(), t), doraise=True)

    def test_repo_keine_echten_daten_und_kein_secret(self):
        dash = self._dash()
        # .gitignore schuetzt echte Daten/Logs
        gi = self._read('.gitignore')
        for pat in ('data/qv-export.json', 'data/agent-conv.json', 'data/hub.log',
                    'data/debug-trace.log', 'data/snapshots/', 'data/*.db'):
            self.assertIn(pat, gi)
        # Daten-Dateien im Repo bleiben klein (nur Samples)
        for rel in ('data/project.json', 'data/sample-data.js', 'data/templates.json'):
            p = os.path.join(dash, rel)
            self.assertTrue(os.path.exists(p), rel)
            self.assertLess(os.path.getsize(p), 10 * 1024, rel + ' zu gross -> echte Daten im Repo?')
        # echte Daten duerfen nicht im Repo liegen
        for rel in ('data/qv-export.json', 'data/outbox.jsonl', 'data/agent-conv.json',
                    'data/qv.db', 'data/hub.log', 'data/debug-trace.log'):
            self.assertFalse(os.path.exists(os.path.join(dash, rel)), rel + ' darf nicht im Repo sein')
        # kein Secret in irgendeiner Dashboard-Textdatei
        secret_re = re.compile(r'ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|\bsk-[A-Za-z0-9]{20,}')
        for root, _dirs, files in os.walk(dash):
            if '__pycache__' in root:
                continue
            for fn in files:
                p = os.path.join(root, fn)
                if os.path.getsize(p) > 2 * 1024 * 1024:
                    continue
                with open(p, 'rb') as _f:
                    raw = _f.read()
                try:
                    txt = raw.decode('utf-8')
                except UnicodeDecodeError:
                    continue
                self.assertIsNone(secret_re.search(txt), 'Secret in ' + p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
