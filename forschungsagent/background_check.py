"""Automatischer Arbeitsauftrag des Forschungsagenten (4x taeglich via GitHub Actions).

Startet eine frische Session und fuehrt den priorisierten Arbeitsauftrag aus.
Trigger: .github/workflows/agent-daily-check.yml (Cron 4x/Tag) oder manuell.
"""
import asyncio
import os
import sys

from mistralai import agents

TASK = """Arbeitsauftrag (alle übrigen Regeln gelten aus der Systemanweisung: E1-E8, Ablage-Template, Double-Check, Hook-Regeln):

1. Priorität: Prüfe zuerst per ablage_durchsuchen, ob eine unbeantwortete Anweisung in der Research-Ablage liegt (Vorrang). Sonst: Standzeile + Beschaffungsliste (Volltext-Inventar) + offene Prüfaufgaben (Quellenverzeichnis) lesen und DIE EINE Aufgabe mit dem höchsten strategischen Ertrag für den Apparat wählen (K4/K5-Hebung, Beschaffungsliste, Nachbeschaffung). Wahl + Begründung + Abnahmekriterien in 3-4 Sätzen. Genau diese eine Aufgabe bearbeiten.
2. Reihenfolge: Apparat-Bibliothek -> Projekt-Libraries -> Research-Ablage -> Web. Je Quelle: bibliografische Identität, Fassung, Zugangsstufe, Zugriffsdatum, G/Nr.
3. Volltextbeschaffung nur auf legitimen Wegen; keine Kosten ohne Philipps Freigabe; keine Sperrumgehung; bei Scheitern dokumentierte Grenzangabe (E6).
4. Ablage: genau eine Notiz je Recherche (research-note-template v3); Korrekturen via research_note_aktualisieren im selben Dokument.
5. Abgabe: Hook-Transparenzmeldung; dann kompakte Zusammenfassung: gewählte Priorität + Begründung, geprüfte Quellen, begründete K-Vorschläge (keine eigene Nummernvergabe), offene Punkte/Grenzen, Empfehlung für die nächste Runde."""


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


async def main() -> int:
    if not os.getenv("MISTRAL_API_KEY"):
        print("MISTRAL_API_KEY fehlt", file=sys.stderr)
        return 2
    agent = agents.Agent.load_from(agent_name="grammatik-statt-stil-research")
    session = await agent.start_session()
    print("SESSION:", session.id)
    turn = await session.run(_task_for_today())
    out = str(getattr(turn, "output", None) or turn)
    if "Failed" in out:
        print("TURN FAILED:", out[:500], file=sys.stderr)
        return 1
    print(out[:1000])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
