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
- Subagenten: Root auf `mistral-large-4-0`, `screener` auf `mistral-small-2603` (read-only Masse:
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
