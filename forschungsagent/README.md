# Forschungsagent „Grammatik statt Stil"

Mistral Agents SDK agent (`mistralai-agents`) for the TU Wien project
**„Grammatik statt Stil"** (Philipp Petrac, Emerging Fields in Architecture, 253.366 VU).

Tools: `web_recherche` (Web, mit Quellen), `projektquellen_suchen` (RAG über die beiden
Projekt-Libraries), `ablage_durchsuchen` (eigene Research-Notizen), `projektdateien_auflisten`,
`research_note_ablegen` (systematische Ablage als Markdown in der Library
„Grammatik statt Stil – Research-Ablage (Agent)"). Conversation-Memory über durable Sessions.

## Deploy (Mistral-managed)
git add forschungsagent && git commit -m "Add grammatik-statt-stil-research agent" && git push -u origin vibe/forschungsagent-b21b74

## Runde 2 + Subagenten (Arm B) - 2026-11-20
- Subagenten: Root auf `mistral-large-4-0`, `screener` auf `mistral-small-2603` (read-only Umfangsarbeit/Bulk:
  Existenz/Metadaten/Lizenz pro Kandidatenquelle, kein Ablage-Write), `verifier` auf `mistral-large-4-0`
  (Claim-Verifikation). Cap: `SubagentPolicy(concurrent_child_turn_limit=10, max_depth=2)`.
- Sandbox: Default `MistralSandbox` (Deployment + Subagenten brauchen sie; `cloud_user`-Rolle noetig,
  sonst Startup-Fehler `subagents_with_unborrowable_sandbox`). Lokal/Tests: `AGENT_SANDBOX=bashkit`.
- Hook (QuoteAuditHook): Session-Scoping (SDK haelt Felder pro Session; `session_id`-Guard),
  pro-Claim double_check + Backstop Verifizierungsquote >= 0.8, Lizenz-/Zugangs-Sidecar
  (`ResearchAnswer.quellen[].license_access`) Pflicht bei Volltext, URL-Existenz-Check: Status
  wird in `post_tool_call` rein aus Tool-Ergebnissen (url_status_pruefen/doi_pruefen) eingesammelt
  (kein I/O/keine Decision dort - Temporal-Replay-sicher), Durchsetzung (Retry/Reject) in
  `post_llm_call`: zitierte URL/DOI ohne Check oder mit 404 -> Problem; 403/429 = gesperrt (403 != 404).
  Subagenten-Hooks ohne Ablage-Pflicht/Summary.
- Skills: gepinnt via `PINNED_SKILLS` (id, version), Fallback `all_registry_skills()`.
- Tests: `uv run python tests/run_tests.py` (75/75 OK).

## RCA Textwurst/F1-F5 - 2026-11-24 (ab main nach PR #10/#11)
- F1: DOUBLE-CHECK-Regel entschaerft den Konflikt - vollstaendiger Nachweis liegt in der Ablage-Notiz; JSON nur Kern-Checks (max. 3 double_check, ergebnis max. 200 Z.).
- F2: Schema-Descriptions sagen "max. 5 / Kern-Eintraege" statt "Alle .../PFLICHT" (Schema ist zweiter Instruktionskanal, arXiv:2608.08254).
- F3: Caps schaerfer: JSON gesamt <= 3000 Z., offene_punkte <= 5, double_check.ergebnis <= 200 / gesamt <= 1500; zusammenfassung 500 / arbeitsupdate 800 bleiben.
- F4: ResearchAnswer verschlankt auf zusammenfassung + arbeitsupdate + offene_punkte + notiz_id; belegte_aussagen/double_check/quellen/verbatim_zitate/deutungen/verifizierungsquote entfernt. Hook: notiz_id-Herkunft (muss aus research_note_ablegen Tool-Output stammen), URL-Check auf Textfeldern bleibt, Ablage-Pflicht bleibt; Feld-basierte QA (Zitate/Lizenz) liegt in der Ablage-Notiz.
- F5: Plattformseitig Instanzgroesse erhoehen (OOM exit 137 -> invalid_command) - Console/Koyeb, nicht per API.
- Begriff: "Masse(-Arbeit)" ersetzt durch "Umfangsarbeit (Bulk)" in main.py/README.
- RCA-Dok: `rca-textwurst-abschlussantwort-2026-11-24.md` (Ablage).

## Session-Start-Optimierung (O1/O2/O4) - 2026-11-22
- `projektdateien_auflisten(library=..., search=...)`: optionale Filter; `search` wird serverseitig
  an `documents.list_async(search=...)` durchgereicht (kein LLM-Call, spart Paginierung/Kontext).
  `bibliotheken_auflisten(search=...)` ebenso.
- `SESSION-START-REGEL` schlank: Start = `bibliotheken_auflisten` + `aktuelles_datum` +
  `projektdateien_auflisten(library="research_ablage_agent", search="00-projektstand")` -> ID ->
  `dokument_lesen` (EIN Volltext-Dokument, gekappt). `ablage_durchsuchen` nur noch als FALLBACK.
  Inhaltlich liest die Session weiterhin nur `00-projektstand.md` (wird von `post_agent_turn`
  automatisch nach jedem Turn aktualisiert); Sicherheitsregeln (nie IDs raten, nie blind anlegen,
  GENAU EINES als Erstbefuellung) unveraendert.
- Tests: 86/86 OK (`SessionStartOptTests`).
