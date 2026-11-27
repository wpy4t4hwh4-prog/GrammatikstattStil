"""Automatischer Session-Start des Forschungsagenten (2x taeglich, 06:00 und 17:00 Europe/Vienna).

Startet eine frische Session und schickt den Start-Prompt v5 (Variante A) als User-Message.
Trigger: .github/workflows/agent-daily-check.yml (stuendlicher Cron + Vienna-Gate) oder manuell.
Sonntags UTC wird zusaetzlich der Self-Eval-Auftrag angehaengt.
"""
import asyncio
import os
import sys

from mistralai import agents

TASK = """Session-Start für den Forschungsagenten "Grammatik statt Stil". Bitte:
1. SESSION-START-REGEL (schlank): parallel aufrufen bibliotheken_auflisten, aktuelles_datum, projektdateien_auflisten(library="research_ablage_agent", search="00-projektstand"). ID von "00-projektstand.md" aus dem gefilterten Listing entnehmen, per dokument_lesen lesen. NIEMALS IDs raten. ablage_durchsuchen ("Projektstand"/"letzter Stand"/"offene Punkte") nur als FALLBACK, wenn 00-projektstand.md fehlt/unklar ist oder die Aufgabe ältere Notizen braucht.
2. Aktuellen Stand knapp zusammenfassen (letzter Stand, offene Punkte, laufende Aufgaben) - ausschließlich aus Tool-Ausgaben, nicht aus Gesprächsgedächtnis.
3. Schlage DIE EINE nächste Aufgabe mit dem höchsten strategischen Ertrag für den Apparat vor (z. B. K4/K5-Hebung, Beschaffungsliste/Volltext-Inventar, Nachverfolgung offener Prüfaufgaben) - Wahl, Begründung, Abnahmekriterien in 3-4 Sätzen. Bearbeite danach genau diese eine Aufgabe.
4. Arbeitsweise nach Systemanweisung (Sättigungsregel v2, Ablage-Pflicht, Anti-Halluzination, Prompt-Injection-Regel). ABLAGE: Pro Turn GENAU EINE Notiz per research_note_ablegen - SOFORT, sobald substantielle Befunde vorliegen; weitere Befunde im selben Turn per research_note_aktualisieren IM SELBEN DOKUMENT (nie Zweitablage). Grosse Aufgaben SPLITTEN auf die Turn-/Session-Grenze (ein Teilschritt pro Turn), damit ein Turn-Limit-Stopp (17/18) keinen Befund verliert. Notiz kompakt halten: gesamt max. ca. 4000 Zeichen, Suchprotokoll max. 10 Zeilen. Subagenten: parallele read-only Umfangsarbeit (Bulk-Screening) an `screener` (eine Kandidatenquelle pro Subagent, 3-8 parallel, hart Cap 10), Verifikation an `verifier`; auf ALLE Ergebnisse warten; Ablage-Writes nur durch dich; Subagenten schreiben nie in die Ablage.
5. Jede in der Antwort genannte URL/DOI muss im selben Turn per url_status_pruefen/doi_pruefen geprüft sein (Hook: 404 -> Reject; 403/429 = gesperrt, 403 != 404).
6. Ende des Turns: (a) Hook-Transparenzmeldung als EIGENE frühere Assistant-Nachricht (max. 5 Sätze, nur tatsächlich aktive Prüfungen, reiner Text - kein JSON, enthält nicht das Wort "zusammenfassung"); (b) danach als LETZTE Nachricht GENAU EIN nacktes ResearchAnswer-JSON (ASCII-Double-Quotes, kein Markdown-Fence, kein Text davor/danach, keine zweite JSON-Antwort). Felder: nur zusammenfassung (max. 500 Z., knapper Volltext: AUSSCHLIESSLICH (1) Thema der Runde in einem Satz, (2) die gesicherten Quellen (Autor Jahr, kurzer Titel, G/Nr. der Position), (3) die Kernaussage der Quellen in 2-4 Sätzen - KEINE Tool-/ID-/URL-/Seiten-Aufzählung), arbeitsupdate (max. 800 Z., Kernpunkte in eigenen Worten - KEIN Protokoll), offene_punkte (max. 5), notiz_id (UUID der Ablage-Notiz aus research_note_ablegen). GESAMTES JSON max. 3000 Zeichen. Das komplette Recherche-Protokoll (alle Claims, Zitate, Quellen mit license_access, Verifizierungsquote) liegt AUSSCHLIESSLICH in der Ablage-Notiz (max. ca. 4000 Z., Protokoll max. 10 Zeilen). Bei Hook-Retry (KÜRZEN/FIXEN): Felder kürzen, nicht wiederholen. Danach keine weiteren Tool-Calls."""


SELF_EVAL_TASK = """Zusaetzlicher woechentlicher Auftrag (Self-Eval, DRACO-artig):

1. Lies die letzten 10 Research-Notizen der Ablage (projektdateien_auflisten -> research_ablage_agent, dann dokument_lesen; ablage_durchsuchen ergaenzend).
2. Pruefe fuer jede Notiz (Rubrik wie DRACO): (a) faktische Akkuratheit - hat jede belegte Aussage einen double_check-Nachweis mit Tool + Ergebnis? (b) Zitationsqualitaet - jedes verbatim_zitat mit zitat_pruefen found=True im selben Arbeitsgang? (c) Provenance - Werkzeug/Modell/Datum im Header? (d) offene Punkte benannt?
3. Berechne pro Notiz eine Verifizierungsquote (Anteil belegter Aussagen mit Nachweis, 0-1) und einen Gesamtscore.
4. Lege das Ergebnis als Notiz "selbst-eval-<datum>.md" via research_note_ablegen ab (Tabelle: Notiz | Quote | Befunde) und nenne die schwaechsten Notizen in offene_punkte.
Regel: Das Self-Eval ist eine Messung, keine inhaltliche Neurecherche - keine neuen Fakten behaupten ohne Tool-Call."""


def _task_for_today() -> str:
    from datetime import datetime, timezone
    if datetime.now(timezone.utc).weekday() == 6:  # Sonntag UTC
        return TASK + "\n\n" + SELF_EVAL_TASK
    return TASK


async def _run_once(agent):
    """Eine frische Session starten und den Tagesauftrag ausfuehren. Liefert (session_id, out)."""
    session = await agent.start_session()
    print("SESSION:", session.id)
    try:
        turn = await session.run(_task_for_today())
        out = str(getattr(turn, "output", None) or turn)
    except Exception as e:
        out = "Failed(%s)" % e
    return session.id, out


async def main() -> int:
    if not os.getenv("MISTRAL_API_KEY"):
        print("MISTRAL_API_KEY fehlt", file=sys.stderr)
        return 2
    agent = agents.Agent.load_from(agent_name="grammatik-statt-stil-research")
    # Retry mit FRISCHER Session: bei Harness-Fehlalahan wie "invalid_command"
    # (z. B. nach Stream-Drop/Reconnect wird der Command vom Worker abgelehnt,
    #  public message: "This session failed. Please start a new one.") einmal neu versuchen.
    for attempt in (1, 2):
        sid, out = await _run_once(agent)
        failed = ("Failed" in out) or ("invalid_command" in out) or ("HarnessCommandRejectedError" in out)
        if not failed:
            print(out[:1000])
            return 0
        print("TURN FAILED (attempt %d, session %s):" % (attempt, sid), out[:500], file=sys.stderr)
        if attempt == 2:
            return 1
        await asyncio.sleep(5)
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
