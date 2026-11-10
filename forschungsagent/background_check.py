"""Täglicher Hintergrund-Check des Forschungsagenten.

Startet eine frische Session, lädt den Apparat-Stand (Apparat-Bibliothek),
prüft Standzeilen/Positionsnotation und legt eine Notiz in der Research-Ablage ab.

Ausführung: MISTRAL_API_KEY muss als Env/Secret gesetzt sein.
Trigger-Optionen: GitHub Actions (siehe .github/workflows/agent-daily-check.yml), lokaler Cron, externes Monitoring.
"""
import asyncio
import os
import sys

from mistralai import agents

TASK = (
    "Täglicher Hintergrund-Check (Apparat-Stand): "
    "1) aktuelles_datum abrufen. "
    "2) bibliotheken_auflisten + projektdateien_auflisten aufrufen. "
    "3) Alle drei Apparat-Dokumente (Quellenverzeichnis, Volltext-Inventar, Forschungssynthese) "
    "mit dokument_finden/dokument_lesen lesen; Standzeilen und letzte Positionsnummer (G/Nr.) notieren. "
    "4) Kurz prüfen, ob K4/K5-Blocker oder neue Positionen erkennbar sind (in_dokument_suchen nach 'K4'/'K5'/'Stand:'). "
    "5) Ergebnis als Notiz mit research_note_ablegen in der Research-Ablage ablegen "
    "(Titel: 'Täglicher Apparat-Check YYYY-MM-DD'). "
    "6) arbeitsupdate ausfüllen."
)


async def main() -> int:
    if not os.getenv("MISTRAL_API_KEY"):
        print("MISTRAL_API_KEY fehlt", file=sys.stderr)
        return 2
    agent = agents.Agent.load_from(agent_name="grammatik-statt-stil-research")
    session = await agent.start_session()
    print("SESSION:", session.id)
    turn = await session.run(TASK)
    out = str(getattr(turn, "output", None) or turn)
    if "Failed" in out:
        print("TURN FAILED:", out[:500], file=sys.stderr)
        return 1
    print(out[:1000])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
