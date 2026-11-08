from typing import Annotated

from mistralai import agents
from mistralai.client.models import File
from mistralai.workflows.client import get_mistral_client
from pydantic import Field

PROJECT_LIBRARY_ID = "01a1843c-f463-71db-a3fe-ae8b3814f155"
CATALOG_LIBRARY_ID = "01a182d2-0a6f-762d-9fc3-a4150e53e3be"
NOTES_LIBRARY_ID = "01a1b7a7-d3b3-7603-9601-7efb317d38ee"

SUBMODEL = "mistral-large-latest"

INSTRUCTIONS = """
Du bist der Forschungsagent für das Projekt „Grammatik statt Stil" von Philipp Petrac
(TU Wien, Modul Emerging Fields in Architecture, 253.366 VU, Matrikelnummer 01325817).

Projektkontext (die zentrale Datei und der Projektstand, die du dir merken sollst):
- Leitfrage: Unter welchen Bedingungen können regelbasierte prozedurale Verfahren
  (PCG, Formgrammatiken/Shape Grammars) Entwurfs- und Planungsinstrumente für
  qualitative Heterogenität in der gebauten Stadt werden — und wo liegen ihre Grenzen?
- Der Stilstreit in der Architektur (traditionell vs. modern) wird als Symptom gelesen:
  statt Stilfragen stehen prozedurale Entwurfsmethoden, historische Stadtbausysteme
  (Haussmanns Paris, Wiener Gründerzeit) und ökonomische/rechtliche Regelwerke im Fokus.
- Zentrale Projektdateien in der Library „Grammatik statt Stil Bibliothek"
  (ID 01a1843c-f463-71db-a3fe-ae8b3814f155):
  „Grammatik statt Stil – Essay (siebte Fassung).pdf" (Dokument 21aca561-c4fd-4388-bd45-e02e4c7fbe87)
  und „Entwurf Reflexionsarbeit Philipp Petrac.pdf" (Dokument 002e3c8f-5005-481e-a883-79c51083910e).
- Weitere Projekt-Dokumente (Projekt-Reports, wiss-workflow, K-Struktur-Exporte, Spezifikationen)
  liegen in der Library „Katalogstadt – Emerging Fields in Architecture"
  (ID 01a182d2-0a6f-762d-9fc3-a4150e53e3be).
- Code/Projekt-Repo: github.com/wpy4t4hwh4-prog/GrammatikstattStil.

Arbeitsweise bei jeder Anfrage:
1. Recherchieren: zuerst die Projektquellen mit projektquellen_suchen durchsuchen,
   dann gezielt extern mit web_recherche. Bereits abgelegte eigene Notizen mit
   ablage_durchsuchen einbeziehen.
2. Analysieren und kontextualisieren: Befunde auf die Leitfrage des Projekts beziehen
   und in den Architekturdiskurs (Stilstreit, prozedurale Methoden, Stadtbausysteme) einordnen.
3. Synthetisieren und vergleichen: Positionen, Quellen und Methoden gegenüberstellen
   (z. B. PCG/Grammatik vs. parametrisch vs. generativ-optimierend vs. KI), Gemeinsamkeiten
   und Widersprüche herausarbeiten.
4. Zusammenfassen: am Ende jeder substanziellen Antwort eine klare, prägnante Zusammenfassung.
5. Systematisch ablegen: substantielle Rechercheergebnisse (neue Quellenbefunde, Analysen,
   Vergleiche, Synthesen) mit research_note_ablegen als Markdown-Notiz in der Ablage-Library
   sichern, damit sie später über ablage_durchsuchen wieder auffindbar sind.

Regeln:
- Antworte auf Deutsch.
- Gib bei jeder Aussage die Quellen an (Titel + URL bei Webquellen, Dokumentname bei
  Projektquellen). Erfinde keine Quellen.
- Unterscheide klar zwischen Beleg (aus einer Quelle), Deutung (deine Einordnung) und
  eigener Synthese.
- Diese Session ist dauerhaft: Du erinnerst dich an alles, was wir in diesem Gespräch
  besprochen haben, inklusive der Projektdatei. Bei Folgefragen bezieh dich darauf,
  ohne dass der Nutzer es wiederholen muss.
- Notizen in der Ablage immer als Markdown mit den Abschnitten: Fragestellung, Quellen,
  Befunde, Analyse/Kontext, Vergleich, Synthese, Offene Punkte.
"""


def _extract_conversation(response) -> dict:
    text_parts: list[str] = []
    quellen: list[dict] = []
    for output in response.outputs or []:
        if getattr(output, "type", None) != "message.output":
            continue
        for chunk in output.content or []:
            kind = getattr(chunk, "type", None)
            if kind == "text":
                text_parts.append(chunk.text)
            elif kind == "tool_reference":
                quellen.append(
                    {
                        "titel": getattr(chunk, "title", None),
                        "url": getattr(chunk, "url", None),
                        "quelle": getattr(chunk, "source", None),
                    }
                )
    return {"antwort": "".join(text_parts).strip(), "quellen": quellen}


@agents.tool
async def web_recherche(
    query: Annotated[str, Field(description="Präzise Such-/Recherchefrage auf Deutsch oder Englisch.")],
    kontext: Annotated[str, Field(description="Kontext aus dem Projekt, damit die Suche zielgerichtet ist.")] = "",
) -> dict:
    """Recherchiert eigenständig im Web zu einer Frage zum Projekt „Grammatik statt Stil" und liefert Befunde mit Quellen (Titel + URL)."""
    prompt = (
        "Recherchiere im Web zu folgender Frage zum Architektur-Forschungsprojekt "
        "„Grammatik statt Stil“ (prozedurale Entwurfsmethoden, Formgrammatiken, historische "
        "Stadtbausysteme, Stilstreit in der Architektur).\n\n"
        f"Frage: {query}\n"
        f"Projektkontext: {kontext or 'keiner'}\n\n"
        "Fasse die wichtigsten Befunde stichpunktartig zusammen (max. 15 Punkte), nenne "
        "dabei stets die Quelle. Liste am Ende alle verwendeten Quellen als „Titel — URL“."
    )
    client = get_mistral_client(run_as="auto")
    response = await client.beta.conversations.start_async(
        model=SUBMODEL,
        inputs=[{"role": "user", "content": prompt}],
        tools=[{"type": "web_search"}],
    )
    return _extract_conversation(response)


@agents.tool
async def projektquellen_suchen(
    query: Annotated[str, Field(description="Frage oder Suchbegriff, der in den Projekt-Dokumenten (Essay, Entwurf, Reports, Literaturliste) gesucht werden soll.")],
) -> dict:
    """Durchsucht die beiden Projekt-Libraries („Grammatik statt Stil Bibliothek" und „Katalogstadt – Emerging Fields in Architecture“) per RAG und beantwortet quellenbasiert mit Dokument-Angaben."""
    client = get_mistral_client(run_as="auto")
    response = await client.beta.conversations.start_async(
        model=SUBMODEL,
        instructions=(
            "Beantworte die Frage ausschließlich aus den Dokumenten der verbundenen Libraries. "
            "Zitiere jeden Befund mit dem Dokumentnamen (und Kapitel/Abschnitt, falls erkennbar). "
            "Wenn die Dokumente keine Antwort enthalten, sage das ausdrücklich."
        ),
        inputs=[{"role": "user", "content": query}],
        tools=[
            {
                "type": "document_library",
                "library_ids": [PROJECT_LIBRARY_ID, CATALOG_LIBRARY_ID],
            }
        ],
    )
    return _extract_conversation(response)


@agents.tool
async def ablage_durchsuchen(
    query: Annotated[str, Field(description="Wonach in den bereits vom Agenten abgelegten Research-Notizen gesucht werden soll.")],
) -> dict:
    """Durchsucht die Ablage-Library mit den bisherigen Research-Notizen des Agenten (Research-Ablage), um frühere Ergebnisse wiederzuverwenden."""
    client = get_mistral_client(run_as="auto")
    response = await client.beta.conversations.start_async(
        model=SUBMODEL,
        instructions=(
            "Beantworte die Frage aus den Research-Notizen in der verbundenen Library. "
            "Zitiere die jeweilige Notiz (Dateiname). Wenn nichts Passendes gefunden wird, sage das ausdrücklich."
        ),
        inputs=[{"role": "user", "content": query}],
        tools=[{"type": "document_library", "library_ids": [NOTES_LIBRARY_ID]}],
    )
    return _extract_conversation(response)


@agents.tool
async def projektdateien_auflisten() -> dict:
    """Listet die Dokumente der beiden Projekt-Libraries mit Namen, ID und Verarbeitungsstatus auf."""
    client = get_mistral_client(run_as="auto")
    result: dict[str, list[dict]] = {}
    for label, library_id in (
        ("grammatik_statt_stil_bibliothek", PROJECT_LIBRARY_ID),
        ("katalogstadt_emerging_fields", CATALOG_LIBRARY_ID),
    ):
        listing = await client.beta.libraries.documents.list_async(library_id=library_id, page_size=100)
        result[label] = [
            {
                "name": doc.name,
                "id": doc.id,
                "extension": doc.extension,
                "processing_status": doc.processing_status,
            }
            for doc in listing.data or []
        ]
    return result


@agents.tool
async def research_note_ablegen(
    titel: Annotated[str, Field(description="Titel der Notiz (kurz, eindeutig).")],
    thema: Annotated[str, Field(description="Thema/Stichwort, z. B. Shape Grammars Stiny, Haussmann Paris, K4-Blocker.")],
    markdown: Annotated[str, Field(description="Vollständiger Notiztext als Markdown mit den Abschnitten: Fragestellung, Quellen, Befunde, Analyse/Kontext, Vergleich, Synthese, Offene Punkte.")],
) -> dict:
    """Legt eine Research-Notiz systematisch in der Ablage-Library „Grammatik statt Stil – Research-Ablage (Agent)“ ab und gibt die Dokument-ID zurück."""
    slug = "".join(ch if ch.isalnum() else "-" for ch in titel.lower()).strip("-")
    filename = f"{slug[:80] or 'notiz'}.md"
    client = get_mistral_client(run_as="auto")
    header = f"# {titel}\n\n- Thema: {thema}\n- Ablage: Research-Agent „Grammatik statt Stil“\n\n"
    document = await client.beta.libraries.documents.upload_async(
        library_id=NOTES_LIBRARY_ID,
        file=File(fileName=filename, content=(header + markdown).encode("utf-8")),
    )
    return {
        "document_id": document.id,
        "name": document.name,
        "library_id": NOTES_LIBRARY_ID,
        "processing_status": document.processing_status,
    }


agent = agents.Agent(
    model="mistral-large-latest",
    name="grammatik-statt-stil-research",
    description=(
        "Forschungsagent für das TU-Wien-Projekt „Grammatik statt Stil“: recherchiert Quellen, "
        "analysiert, kontextualisiert, synthetisiert, fasst zusammen, vergleicht und legt "
        "Ergebnisse systematisch in der Research-Ablage ab."
    ),
    instructions=INSTRUCTIONS,
    tools=[
        web_recherche,
        projektquellen_suchen,
        ablage_durchsuchen,
        projektdateien_auflisten,
        research_note_ablegen,
    ],
    max_iterations=40,
)
