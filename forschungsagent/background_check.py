"""Automatischer Arbeitsauftrag des Forschungsagenten (4x taeglich via GitHub Actions).

Startet eine frische Session und fuehrt den priorisierten Arbeitsauftrag aus.
Trigger: .github/workflows/agent-daily-check.yml (Cron 4x/Tag) oder manuell.
"""
import asyncio
import os
import sys

from mistralai import agents

TASK = """Arbeitsauftrag:

Arbeite wie folgt:

1. Prioritätsermittlung und Entscheidung: Melde zu Beginn, ob in deiner Research-Ablage eine noch unbeantwortete Anweisung liegt; eine solche Anweisung hat Vorrang und ist diese Runde zu bearbeiten. Lies andernfalls die Standzeile, die priorisierte Beschaffungsliste des Volltext-Inventars und die offenen Prüfaufgaben des Quellenverzeichnisses. Wähle daraus die eine Aufgabe mit dem höchsten strategischen Ertrag für den Apparat (insbesondere Hebung dokumentierter Zugänge zu K4- und K5-Positionen, Abarbeitung der Beschaffungsliste, Nachbeschaffung zu offenen Fundstellen) und formuliere deine Wahl samt Begründung und Abnahmekriterien in drei bis vier Sätzen. Bearbeite genau diese eine Aufgabe; verteile dich nicht.
2. Recherche: Suche zuerst Apparat-Bibliothek, Grammatik statt Stil Bibliothek, Katalogstadt-Bibliothek und deine Research-Ablage, danach das Web. Melde je Quelle bibliografische Identität, Fassung, Zugangsstufe, Zugriffsdatum und bei Treffern im Apparat die Positionsnotation (G/Nr.).
3. Volltextbeschaffung: Ausschließlich auf legitimen Wegen (Open Access, frei zugängliche oder lizenzierte Fassungen); keine Kostenpflichtigkeit ohne Philipps Freigabe, keine Umgehung von Sperren. Bei Scheitern dokumentierte Grenzangabe: Aufgabe, Suchweg mit Werkzeug und Abfrage, Ergebnis, offene Punkte.
4. Prüfung und Analyse: Lies jeden Volltext tatsächlich. Extrahiere Kernthesen mit exakten Fundstellen; jede Zahl mit Fundstelle, ohne Rundung; Datumsangaben ausschließlich aus deiner Werkzeugumgebung (aktuelles_datum). Negativbefunde nur nach tatsächlich ausgeführter, benannter Suche; „verifiziert“ nur mit reproduzierbarem Nachweis; IDs ausschließlich aus Werkzeugausgaben.
5. Ablage: Hinterlege beschaffte Volltexte, Kernthesen und zeichengenaue Zitate (Wortlaut, Fundstelle, Zugangsstufe) in deiner Research-Ablage; genau eine Notiz je Recherche im vorgeschriebenen Aufbau; Korrekturen als dokumentierte Korrektur im selben Dokument, keine stille Zweitablage.
6. Abgabe: Hook-Transparenzmeldung, falls ein Prüfhook aktiv ist. Schließe mit einer kompakten Zusammenfassung ab: gewählte Priorität mit Begründung, geprüfte Quellen, begründete K-Vorschläge ohne eigene Nummernvergabe, offene Punkte und Grenzen sowie die Empfehlung, welche Aufgabe die nächste Runde priorisieren sollte. Dokumentiere offene Punkte, statt Lösungen zu unterstellen."""


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
