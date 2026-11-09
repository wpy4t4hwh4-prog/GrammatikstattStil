import os
from typing import Annotated

from mistralai import agents
from mistralai.vibe_agents.sdk.authoring import hooks as _authoring_hooks
from mistralai.client.models import File
from mistralai.workflows.client import get_mistral_client
from pydantic import BaseModel, Field

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

Regeln (ANTI-HALLUZINATION, strikt einzuhalten):
- NIEMALS etwas erfinden: keine Tool-Ergebnisse, Dokumentnamen, Dokument-IDs, Zitate, URLs, Zahlen, Zustaende. Jede faktische Aussage muss auf einem tatsaechlich ausgefuehrten Tool-Call oder einer zitierten Quelle beruhen.
- Dokumentlisten/Metadaten IMMER mit dem Tool projektdateien_auflisten ermitteln - niemals aus dem Gedaechtnis oder der Projektbeschreibung raten.
- Wenn ein Tool einen Fehler liefert oder ein Fakt nicht belegt ist: sage ausdruecklich "Das kann ich nicht belegen" bzw. "Das Tool hat einen Fehler gemeldet" - nie eine plausible Erklaerung erfinden.
- Rufe Tools tatsaechlich aus, bevor du antwortest. Eine Antwort ohne Tool-Call ist nur zulaessig, wenn die Frage rein aus dem Gespraechskontext beantwortbar ist.
- Zitiere Tool-Ergebnisse wörtlich, wenn du IDs/Status nennst.
- VERPFLICHTENDE ARBEITSWEISE FUER WORTLICHE ZITATE: Bevor du einen Text als wörtliches Zitat ausgibst, MUSST du zitat_pruefen aufrufen und found=True erhalten. Ohne found=True darfst du NICHTS als wörtlich zitieren - dann paraphrasieren und als Paraphrase kennzeichnen oder in offene_punkte aufnehmen.
- Zitate aus PDFs/Dokumenten immer gegen den exakten Volltext (text_content) prüfen, nie gegen RAG-Zusammenfassungen oder das Gedaechtnis.
- Wörtliche Zitate landen im Feld verbatim_zitate (mit quelle + geprueft_mit), nie inline als erfundenes Zitat.
- "Wörtlich" heisst ZEICHEN-EXAKT inklusive Leerzeichen und Zeilenumbrueche (found_exact_inkl_leerzeichen=True). Ist nur found=True (normalisiert) aber nicht exakt, darfst du das Zitat NICHT wörtlich wiedergeben - dann paraphrasieren und als Paraphrase kennzeichnen.
- QUELLENHIERARCHIE: Primaerquellen (Original-PDF, Verlag, DOI) bevorzugen; ResearchGate/Sekundaerquellen nur mit Kennzeichnung primaerquelle=false.
- TRIANGULATION: Wichtige Fakten brauchen mind. 2 unabhaengige Quellen -> evidenzgrad=gesichert; sonst wahrscheinlich/umstritten. Bei widerspruechlichen Quellen aktiv nach Gegenpositionen suchen und vermerken.
- RECHERCHE-PROTOKOLL: In jeder substantiellen research_note_ablegen-Notiz ALLE Suchbegriffe, URLs, Zugriffsdaten und verworfene Quellen festhalten (reproduzierbar wie ein Laborbuch). Notiz-Titel immer mit Datum; bestehende Notizen nie ueberschreiben.
- LESBARKEITS-REGEL: Bevor du "nicht lesbar"/"nicht gefunden" meldest, MUSST du dokument_lesen (bzw. zitat_pruefen) aufgerufen haben und das Tool-Ergebnis (inkl. Fehlermeldung) in double_check zitieren. Pauschale Negativmeldungen ohne dokumentierten Tool-Call sind unzulaessig.
- ID-REGEL: Bibliotheks-IDs, Dokument-IDs, DOIs, PIIs NUR aus Tool-Ergebnissen kopieren - niemals eintippen oder aus dem Gedaechtnis. Vor Ausgabe in double_check eintragen. Bei DOI/PII zusaetzlich gegen doi.org/Verlag verifizieren (web_zitat_pruefen), Transpositionen sind typische Fehler.
- BOUNDARIES: Schreiben NUR in die Research-Ablage (research_note_ablegen); Projekt-Libraries sind fuer den Agenten LESEN-only (dokument_lesen/zitat_pruefen/in_dokument_suchen). DOIs/PIIs vor Ausgabe mit doi_pruefen/url_status_pruefen verifizieren; Sperre (403) != 404.
- NEGATIVBEFUND-REGEL (verbindlich): Eine Aussage wie "X existiert nicht" oder "keine Treffer" darf NUR als gesichert ausgegeben werden, wenn ALLE drei Libraries durchsucht wurden: projektdateien_auflisten (alle 3 Libraries) + projektquellen_suchen (Projekt-Libraries) + ablage_durchsuchen (Research-Ablage) + ggf. web_recherche. Sonst muss der Negativbefund als wahrscheinlich/offene_punkte deklariert werden mit Angabe, welche Libraries geprueft wurden.
- DOUBLE-CHECK (PFLICHT vor jeder Antwort): Jede wörtliche Angabe, jede Zahl, jede ID MUSS mit zitat_pruefen / web_zitat_pruefen / dokument_lesen gegen die Quelle verifiziert und im Feld double_check mit Tool-Ergebnis eingetragen werden. Nicht verifizierbare Angaben duerfen nicht als Fakt ausgegeben werden - nur als offene_punkte.
- ARITHMETIK: Zahlen immer gegen die Quelle pruefen und auf interne Konsistenz (z. B. Teilsummen) kontrollieren; bei Widerspruch -> offene_punkte, nie runden/erfinden.
- ABLAGE: Bei Ablage-Anforderungen entweder Datei mit research_note_ablegen sichern oder ausdruecklich "nicht abgelegt" melden - keine konditionalen Angaben.
- TOOL-LIBRARY-ZUORDNUNG (verbindlich): projektquellen_suchen = NUR Grammatik-statt-Stil-Bibliothek (01a1843c-...) + Katalogstadt (01a182d2-...); ablage_durchsuchen = NUR Research-Ablage (01a1b7a7-...); projektdateien_auflisten = ALLE drei Libraries (Projekt-Libraries + Research-Ablage); zitat_pruefen/text_content = exakter Volltext fuer Zitate aus JEDER Library.

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


def _client():
    """Mistral client: explicit workspace API key (user identity) wins over the worker SA token."""
    key = os.environ.get("PROJECT_MISTRAL_API_KEY")
    if key:
        return get_mistral_client(api_key=key)
    return get_mistral_client(run_as="auto")


class BelegteAussage(BaseModel):
    aussage: str = Field(description="Faktische Aussage, die ausschliesslich auf einem Tool-Ergebnis oder einer Quelle beruht.")
    quelle: str = Field(description="Konkrete Quelle: Dokumentname/ID oder Titel + URL. Nie leer, nie erfunden.")
    evidenzgrad: str = Field(description=" Einer von: gesichert (mind. 2 unabhaengige Quellen oder Primaerquelle), wahrscheinlich (1 Quelle), umstritten (gegenteilige Quellen), unbelegt (nicht verifiziert -> nur offene_punkte).")
    primaerquelle: bool = Field(default=False, description="True, wenn die Quelle das Original/Primaerdokument ist (Verlag/DOI), nicht ResearchGate/Zweitquelle.")


class VerbatimZitat(BaseModel):
    text: str = Field(description="WORTLICHES Zitat - ausschliesslich Copy-Paste aus einem Tool-Ergebnis (zitat_pruefen/text_content), niemals aus dem Gedaechtnis.")
    quelle: str = Field(description="Dokumentname + Dokument-ID oder Titel + URL.")
    geprueft_mit: str = Field(description="Name des Tools, mit dem das Zitat verifiziert wurde (z. B. zitat_pruefen).")

class DoubleCheck(BaseModel):
    angabe: str = Field(description="Die gepruefte Angabe (Zitat, Zahl, ID).")
    pruef_tool: str = Field(description="Tool, mit dem geprueft wurde (zitat_pruefen / web_zitat_pruefen / dokument_lesen).")
    ergebnis: str = Field(description="found=True/False bzw. exakter Befund - wörtlich aus dem Tool-Ergebnis.")


class ResearchAnswer(BaseModel):
    zusammenfassung: str = Field(description="Praegnanate Zusammenfassung der Antwort.")
    belegte_aussagen: list[BelegteAussage] = Field(default_factory=list, description="Alle faktischen Aussagen mit Pflichtquelle.")
    deutungen: list[str] = Field(default_factory=list, description="Eigene Einordnungen, klar als Deutung markiert.")
    offene_punkte: list[str] = Field(default_factory=list, description="Ungeklaerte Fragen / nicht belegbare Punkte.")
    verbatim_zitate: list[VerbatimZitat] = Field(default_factory=list, description="Alle wörtlichen Zitate, jeweils per zitat_pruefen verifiziert. Leer lassen, wenn keins verifiziert ist.")
    double_check: list[DoubleCheck] = Field(default_factory=list, description="PFLICHT: jede wörtliche Angabe und jede Zahl/ID, jeweils mit Tool-Ergebnis verifiziert.")


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
    client = _client()
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
    client = _client()
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
    client = _client()
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
    client = _client()
    result: dict[str, list[dict]] = {}
    for label, library_id in (
        ("grammatik_statt_stil_bibliothek", PROJECT_LIBRARY_ID),
        ("katalogstadt_emerging_fields", CATALOG_LIBRARY_ID),
        ("research_ablage_agent", NOTES_LIBRARY_ID),
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
    client = _client()
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


@agents.tool
async def zitat_pruefen(
    library_id: Annotated[str, Field(description="ID der Library, z. B. 01a1843c-f463-71db-a3fe-ae8b3814f155 (Grammatik statt Stil) oder 01a182d2-0a6f-762d-9fc3-a4150e53e3be (Katalogstadt).")],
    document_id: Annotated[str, Field(description="Dokument-ID in dieser Library.")],
    zitat: Annotated[str, Field(description="Das angebliche wörtliche Zitat, das geprueft werden soll.")],
) -> dict:
    """PFLICHT vor jedem wörtlichen Zitat: prueft per Substring-Suche im exakten Dokument-Volltext (text_content), ob das Zitat dort vorkommt. Ergebnis: found True/False + Fundstelle. NIEMALS ein Zitat als wörtlich ausgeben ohne found=True."""
    client = _client()
    content = await client.beta.libraries.documents.text_content_async(library_id=library_id, document_id=document_id)
    text = getattr(content, "text", None) or str(content)
    import re
    norm = lambda s: re.sub(r"\s+", " ", s).strip()
    found_norm = norm(zitat) in norm(text)
    found_exact = zitat in text
    idx = norm(text).find(norm(zitat))
    kontext = norm(text)[max(0, idx-120): idx+len(norm(zitat))+120] if found_norm else None
    return {"found": found_norm, "found_exact_inkl_leerzeichen": found_exact, "zitat": zitat, "kontext": kontext}


@agents.tool
async def dokument_lesen(
    library_id: Annotated[str, Field(description="Library-ID.")],
    document_id: Annotated[str, Field(description="Dokument-ID.")],
) -> dict:
    """Liefert den EXAKTEN Volltext eines Library-Dokuments (text_content). Pflicht bei Aufgaben mit wörtlichen Zitaten, IDs oder genauen Zahlen - niemals ueber RAG raten."""
    client = _client()
    content = await client.beta.libraries.documents.text_content_async(library_id=library_id, document_id=document_id)
    text = getattr(content, "text", None) or str(content)
    return {"document_id": document_id, "laenge": len(text), "volltext": text}


@agents.tool
async def web_zitat_pruefen(
    url: Annotated[str, Field(description="URL der Quelle, aus der zitiert werden soll.")],
    zitat: Annotated[str, Field(description="Das angebliche wörtliche Zitat.")],
) -> dict:
    """PFLICHT vor jedem wörtlichen Zitat aus einer WEBQUELLE: laedt die Seite und prueft per Substring-Suche, ob das Zitat dort vorkommt. found=True erforderlich, sonst nicht als wörtlich ausgeben."""
    import re
    import httpx
    norm = lambda s: re.sub(r"\s+", " ", s).strip()
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as hc:
            resp = await hc.get(url)
            text = resp.text
    except Exception as e:
        return {"found": False, "fehler": f"Seite nicht abrufbar: {e}"}
    found_norm = norm(zitat) in norm(text)
    found_exact = zitat in text
    return {"found": found_norm, "found_exact_inkl_leerzeichen": found_exact, "url": url, "http_status": resp.status_code}


import re as _re
import json as _json


def _norm(s: str) -> str:
    return _re.sub(r"\s+", " ", s).strip()


class QuoteAuditHook(agents.Hook):
    """Sichert Zitate UND Negativbefunde ab. Pro Turn (State wird in pre_agent_turn zurueckgesetzt):
    - sammelt verifizierte Zitate (zitat_pruefen/web_zitat_pruefen found=True) und alle Tool-Calls
    - post_agent_turn: unverifizierte verbatim_zitate ODER Negativbefund ("nicht gefunden"/"nicht lesbar"/
      "nicht existiert") ohne Such-Tool-Call im selben Turn -> Retry mit Feedback (max 2), dann Reject."""

    verified: list[dict] = Field(default_factory=list)
    tools_called: list[str] = Field(default_factory=list)
    retries: int = 0

    async def pre_agent_turn(self, ctx, request):
        self.verified = []
        self.tools_called = []
        self.tool_texts = []
        self.retries = 0
        return None

    tool_texts: list[str] = Field(default_factory=list)

    async def post_tool_call(self, ctx, result):
        name = getattr(result, "tool_name", "")
        self.tools_called = self.tools_called + [name]
        tr = getattr(result, "tool_result", None)
        txt = ""
        content = getattr(tr, "content", None) or []
        for b in content:
            txt += getattr(b, "text", "") or ""
        if not txt:
            txt = str(tr)
        self.tool_texts = self.tool_texts + [txt[:20000]]
        if name in ("zitat_pruefen", "web_zitat_pruefen"):
            tr = getattr(result, "tool_result", None)
            txt = ""
            content = getattr(tr, "content", None) or []
            for b in content:
                txt += getattr(b, "text", "") or ""
            if not txt:
                txt = str(tr)
            try:
                data = _json.loads(txt)
            except Exception:
                data = {}
            if isinstance(data, dict) and data.get("found") is True:
                self.verified = self.verified + [{
                    "text": _norm(str(data.get("zitat", ""))),
                    "quelle": _norm(str(data.get("quelle", data.get("url", "")))),
                }]
        return None

    async def post_llm_call(self, ctx, result):
        if getattr(result, "tool_calls", None):
            return None
        text = getattr(result, "text", "") or ""
        try:
            data = _json.loads(text)
        except Exception:
            data = None
        if not isinstance(data, dict):
            return None
        problems = []
        quotes = data.get("verbatim_zitate") or []
        for q in quotes:
            qt = _norm(str(q.get("text", "")))
            if qt and not any(qt == v["text"] for v in self.verified):
                problems.append("unverifiziertes Zitat: " + qt[:100])
        search_tools = {"dokument_lesen", "zitat_pruefen", "web_zitat_pruefen", "ablage_durchsuchen", "projektquellen_suchen", "projektdateien_auflisten", "web_recherche"}
        all_text = _norm(str(data.get("zusammenfassung", "")) + " " + str(data.get("offene_punkte", "")) + " " + str(data.get("belegte_aussagen", "")))
        neg_words = ["nicht gefunden", "nicht lesbar", "nicht existiert", "nicht auffindbar", "keine treffer"]
        # nur bei echtem Dokument-/Quellenbezug pruefen (UUID, URL, DOI, "Dokument"), nicht bei reinen Chat-Antworten
        has_source_ref = bool(_re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|https?://|doi:|dokument", all_text.lower()))
        if has_source_ref and any(w in all_text.lower() for w in neg_words) and not (set(self.tools_called) & search_tools):
            problems.append("Negativbefund ohne Such-Tool-Call im selben Turn")
        ids_in_answer = set(_re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", all_text))
        tool_blob = _norm(" ".join(self.tool_texts))
        if has_source_ref and any(w in all_text.lower() for w in neg_words):
            for i in ids_in_answer:
                if _norm(i) in tool_blob:
                    problems.append("Widerspruch: ID " + i + " im Tool-Ergebnis vorhanden, aber als nicht gefunden gemeldet")
        # 4. "gesichert" mit konkreter Quellenangabe (UUID/URL/DOI) ohne Such-Tool-Call ist unzulaessig
        for a in data.get("belegte_aussagen") or []:
            if isinstance(a, dict) and "gesichert" in str(a.get("evidenzgrad", "")).lower():
                q = str(a.get("quelle", "")).lower()
                if _re.search(r"[0-9a-f]{8}-[0-9a-f]{4}|https?://|doi:", q) and not (set(self.tools_called) & search_tools):
                    problems.append("evidenzgrad=gesichert mit Quelle ohne Such-Tool-Call im selben Turn: " + str(a.get("aussage", ""))[:100])
        if not problems:
            return None
        feedback = ("VERBOTEN: " + " | ".join(problems) +
                    ". Regeln: wörtliche Zitate nur mit zitat_pruefen/web_zitat_pruefen found=True in DIESEM Turn; "
                    "Negativbefunde nur nach dokument_lesen/ablage_durchsuchen/projektquellen_suchen/projektdateien_auflisten-Call mit dokumentiertem Ergebnis in double_check.")
        if self.retries < 2:
            self.retries = self.retries + 1
            return agents.retry(feedback)
        return agents.reject("Turn abgelehnt: " + feedback)



@agents.tool
async def doi_pruefen(
    doi: Annotated[str, Field(description="DOI, z. B. 10.1016/j.autcon.2008.09.006. Muss aus einer Tool-Quelle stammen, nie getippt.")],
) -> dict:
    """PFLICHT vor jeder DOI-Angabe: loest den DOI ueber doi.org auf und liefert Titel/Autoren/Jahr. Falsch transkribierte DOIs (z. B. vertauschte Ziffern) werden so erkannt."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, headers={"Accept": "application/vnd.citationstyles.csl+json", "User-Agent": "Mozilla/5.0"}) as hc:
            r = await hc.get(f"https://doi.org/{_norm(doi)}", headers={"Accept": "application/vnd.citationstyles.csl+json"})
            if r.status_code in (200, 302, 303):
                if r.status_code == 200:
                    meta = r.json()
                    return {"doi": doi, "existiert": True, "titel": meta.get("title"), "autoren": [f"{a.get('family','')} {a.get('given','')}" for a in meta.get("author", [])], "jahr": (meta.get("issued", {}).get("date-parts", [[None]])[0][0])}
                loc = r.headers.get("location", "")
                return {"doi": doi, "existiert": True, "redirect": loc, "titel": None}
            return {"doi": doi, "existiert": False, "http_status": r.status_code}
    except Exception as e:
        return {"doi": doi, "existiert": None, "fehler": str(e)}


@agents.tool
async def url_status_pruefen(
    url: Annotated[str, Field(description="URL, deren Erreichbarkeit geprueft wird.")],
) -> dict:
    """Prueft HTTP-Status einer URL. UNTERSCHEIDET Sperre (403/Cloudflare) von echtem 404 - Sperre heisst 'nicht pruefbar', nie 'nicht gefunden'."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as hc:
            r = await hc.get(url)
            blocked = r.status_code in (403, 429) or "cloudflare" in r.text[:2000].lower()
            return {"url": url, "http_status": r.status_code, "gesperrt": blocked, "pruefbar": not blocked}
    except Exception as e:
        return {"url": url, "http_status": None, "gesperrt": None, "pruefbar": False, "fehler": str(e)}


@agents.tool
async def in_dokument_suchen(
    library_id: Annotated[str, Field(description="Library-ID.")],
    document_id: Annotated[str, Field(description="Dokument-ID.")],
    begriff: Annotated[str, Field(description="Suchbegriff (Substring, case-insensitive).")],
) -> dict:
    """Grep-aehnliche Suche im exakten Volltext eines Library-Dokuments. Liefert alle Treffer mit Kontext. Deterministisch - nutze das statt RAG fuer exakte Nachweise."""
    client = _client()
    content = await client.beta.libraries.documents.text_content_async(library_id=library_id, document_id=document_id)
    text = getattr(content, "text", None) or str(content)
    import re as _re2
    hits = []
    for m in _re2.finditer(_re2.escape(begriff), text, _re2.IGNORECASE):
        s = max(0, m.start()-100)
        hits.append(text[s:m.end()+100].replace("\n", " "))
        if len(hits) >= 20:
            break
    return {"document_id": document_id, "begriff": begriff, "anzahl": len(hits), "treffer": hits}


agent = agents.Agent(
    model="mistral-large-latest",
    temperature=0.0,
    tool_errors="show",
    hooks=[QuoteAuditHook()],
    skills=[agents.all_registry_skills()],
    environment=agents.BashkitSandbox(),
    output_type=ResearchAnswer,
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
        zitat_pruefen,
        dokument_lesen,
        web_zitat_pruefen,
        doi_pruefen,
        url_status_pruefen,
        in_dokument_suchen,
        research_note_ablegen,
    ],
    max_iterations=40,
)
