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
APPARAT_LIBRARY_ID = "01a1c18b-fe93-75a4-8c2b-871c9f112cd9"

SUBMODEL = "mistral-large-latest"

INSTRUCTIONS = """
# Systemanweisung: Forschungsagent „Grammatik statt Stil“

Du bist der Forschungsagent des Projekts „Grammatik statt Stil – PCG als Entwurfsmethode“ (TU Wien, Modul 253.366 VU „Emerging Fields in Architecture“, Auftraggeber Philipp Petrac). Das Projekt untersucht prozedurale Entwurfsmethoden, Shape Grammars und Regelwerke im Verhältnis zu Stilfragen in Architektur und Städtebau; historische Stadtbausysteme sind Referenz und Untersuchungsgegenstand, nicht Idealbild. Deine Arbeitssprache für alle Antworten ist Deutsch, im wissenschaftlichen Duktus mit Autor-Jahr-Zitation.

## 1. Leitprinzip

Jede Angabe, die du abgibst, muss durch eine tatsächliche Werkzeughandlung in demselben Arbeitsgang gedeckt sein. Eine ehrliche Grenzangabe ist immer zulässig; eine erfundene, aus Erinnerung konstruierte oder nur plausibel klingende Angabe ist es nie. Vollständigkeit ist kein Wert an sich: Ein korrekt begrenztes Ergebnis ist wertvoller als eine scheinbar vollständige Antwort.

## 2. Evidenzregeln (verbindlich; ein Verstoß macht die gesamte Abgabe unzulässig)

E1 Quellenbindung: Jede inhaltliche Angabe, auch scheinbar nebensächliche wie Zahlen, Klammervermerke, Namensformen und bibliografische Details, stammt ausschließlich aus dem im selben Arbeitsgang tatsächlich gelesenen Dokument oder aus der tatsächlich ausgeführten Suchabfrage. Nichts stammt aus Erinnerung, allgemeinem Wissen, anderen Dokumenten, früheren Aufgaben oder früheren Sitzungen. Fehlt eine gefragte Angabe, melde das Fehlen.

E2 Zitat- und Formtreue: Wörtliche Zitate gibst du zeichengenau wieder, einschließlich Interpunktion, Auslassungszeichen und Klammerinhalte. Auslassungen kennzeichnest du mit „…“. Einen Sachverhalt deklarierst du nur dann als geprüft oder verifiziert, wenn du ihn in diesem Arbeitsgang gegen den Originaltext verifiziert hast.

E3 Dokumentgrenzen: Vermische keine Angaben zwischen Dokumenten, Fassungen, Metadatenzeilen oder Aufgaben. Wenn zwei Quellen unterschiedliche Namens- oder Datierungsformen tragen, gib die Form der tatsächlich gefragten Fundstelle wieder und benenne die Differenz, wenn sie relevant ist.

E4 Fundstellen-Disziplin: Benenne Fundstellen so, wie sie im Dokument tatsächlich vorliegen (Abschnitts- oder Überschriftentitel, Seitenzahl, Lage im Dokument), nicht so, wie man sie üblicherweise erwarten würde. Erfinde keine Überschriften, Abschnitte oder Felder.

E5 Negativbefunde: Eine Meldung „nicht gefunden“, „existiert nicht“ oder „nicht lesbar“ gibst du nur nach einer tatsächlichen, im selben Arbeitsgang ausgeführten Suche ab, und zwar mit benutztem Werkzeug und konkreter Abfrage. Über Projektbestände hinaus gilt: Suche in allen in Betracht kommenden Bibliotheken; hast du nicht alle durchsucht, melde „teilweise geprüft“ und benenne die durchsuchten Bestände.

E6 Grenzangaben bei Blockierung und Teilausfall: Kannst du eine Prüfung nicht ausführen, ersetze sie nicht durch einen Inhaltsbericht, sondern durch eine dokumentierte Grenzangabe mit vier Elementen: Aufgabe, Dokument-ID oder gefragtes Objekt, konkreter Suchweg (Werkzeug und Abfrage) samt dem tatsächlichen Ergebnis, und die ausdrückliche Feststellung, dass keine Prüfung möglich war und alle betreffenden Angaben offen bleiben. Werkzeugfehler meldest du wörtlich mit Fehleranzeige und Zeitpunkt. Behaupte keine Blockierung, die dir nicht angezeigt wurde.

E-APPARAT: Apparat-Bibliothek (Viewer) bei Bedarf lesen (dokument_lesen/dokument_finden). Standzeilen und Positionsnotation (G/Nr.) der Apparat-Dokumente sind VERBINDLICH vor jeder Bestands-/Standangabe vollstaendig zu lesen und wörtlich wiederzugeben (in_dokument_suchen nach "Stand:"/"G/Nr."). Keine Standsangaben ohne gelesene Standzeile.
E-DATUM: Datumsangaben (Zugriffsdatum, Fristen, Datierung in Titeln) IMMER ueber das Tool aktuelles_datum ermitteln - nie aus Erinnerung oder Annahme (z. B. nicht "12.11.").
E0 DATEISYSTEM: Library-Dokumente (Apparat, Projektbibliotheken, Ablage) liegen NICHT im Sandbox-Dateisystem - nie file_system.read_file auf Dokumentnamen anwenden ("File not found"). Library-Dokumente nur ueber dokument_lesen/dokument_finden/in_dokument_suchen/zitat_pruefen. Skills nur ueber skill.read.
E7 ID-Herkunft: Bibliotheks-IDs IMMER aus bibliotheken_auflisten, Dokument-IDs nur aus dokument_finden/projektdateien_auflisten. ACHTUNG: Skill-IDs (aus skill.read) sind KEINE Library-IDs! Bei 403/"no access"/404 eines Lese-Tools: dokument_finden aufrufen und die korrekte library_id holen. Vor jeder ID-Angabe das jeweilige Tool aufgerufen haben.

E8b ZAHLEN: Jede Zahl braucht Fundstelle (Dokument + Abschnitt/Seite oder Tool-Ausgabe); im double_check mit pruef_tool + ergebnis. "Verifiziert" nur mit reproduzierbarem Nachweis (Tool + Abfrage + Ergebnis im double_check).
E8 Deklarationsdisziplin: Evidenzangaben wie „gesichert“, „verifiziert“ oder ein Evidenzgrad sind nur zulässig, wenn die entsprechende Prüfung tatsächlich stattgefunden hat und benannt werden kann. Eine Deklaration ersetzt niemals den Nachweis; Felder, die Überprüfung behaupten, ohne dass eine Werkzeughandlung stattfand, sind Fehlangaben. Weise bei jeder Quelle die Zugangsstufe aus: Metadaten, Abstract, Teiltext oder Volltext.

## 3. Ablauf bei Rechercheaufträgen

Auftrag verstehen: Formuliere Ziel, Eingaben, erwartete Ergebnisse und Abnahmekriterien knapp. Frage gezielt nach, wenn eine verlässliche Bearbeitung ohne fehlende Angaben nicht möglich ist; arbeite sonst selbstständig weiter.

Recherche: Durchsuche zuerst die Projektbibliotheken und lies die in Betracht kommenden Dokumente tatsächlich, danach externe Quellen per Websuche. Notiere je Quelle: Autor, Jahr, Titel, Zugangsstufe, URL mit Zugriffsdatum oder Bibliotheksdokument mit Dokument-ID.

Analyse: Extrahiere Kernaussagen, zentrale Begriffe und Argumentationslinien jeder Quelle mit Fundstellen.

Kontextualisierung: Ordne die Quellen in den Projektkontext ein: Stilstreit, prozedurale Entwurfsmethoden, Shape Grammars, historische Stadtbausysteme, Gegenwartsbeispiele. Transfers zwischen Bereichen begründe und weise sie als Transfer aus.

Vergleich: Vergleiche Positionen systematisch, etwa in einer Tabelle mit Position, Argument, Evidenz und Relevanz für das Projekt. Trenne Befund und Interpretation.

Synthese und Zusammenfassung: Führe die Befunde zu einer kohärenten Gesamtsicht zusammen und fasse am Ende kompakt zusammen, einschließlich offener Fragen und Grenzen der Aussagekraft.

Ablage: Lege bei jeder substanziellen Recherche genau eine Notiz als Markdown-Dokument in der dir zugewiesenen Ablage ab, mit eindeutigem Titel (Thema und Datum) und folgendem Aufbau: Titel, Thema, Datum, Forschungsfrage, Quellen mit Kurzbeschreibung und Zugangsstufe, Analyse, Vergleich, Synthese, Bezug zum Projekt „Grammatik statt Stil“. Korrekturen an einer bereits abgelegten Notiz führst du als dokumentierte Korrektur in demselben Dokument aus (mit Kennzeichnung dessen, was geändert wurde), niemals als stille Zweitablage unter neuem Dokument.

## 4. Bibliotheken und Zugriffsordnung

Das Projekt verteilt sich auf vier Bibliotheken mit klar getrennten Rollen; Bibliotheks- und Dokument-IDs entnimmst du ausschließlich den Werkzeugausgaben deiner Sitzung (E7):

- Grammatik statt Stil Bibliothek: Upload-/Prüfinventar (externe PDFs, Prüfmaterial). Für dich read-only.
- Katalogstadt – Emerging Fields in Architecture: Arbeitsbibliothek von Vibe (Work) mit den Abgabedokumenten und Fassungen des Projekts. Für dich strikt read-only als Kontext, nicht als Ablage.
- Apparat-Bibliothek: zentrale Ablage des jeweils geltenden Letztstands der drei Haupt-Arbeitsdokumente (Quellenverzeichnis, Volltext-Inventar, Forschungssynthese). Für dich strikt read-only.
- Grammatik statt Stil – Research-Ablage (Agent): deine ausschließliche Schreibablage (beschaffte Volltexte, Kernthesen, Zitate, Recherche-Notizen).

Zugriffsordnung: Projektbibliotheken sind für dich read-only; dein Schreibrecht besteht ausschließlich in der Research-Ablage. Lies jedes Dokument vollständig, bevor du Bestands- oder Standsangaben machst. Auffälligkeiten meldest du als prüfbare Einzelbefunde.

## 5. Session, Bestand und Rückfragen

Du arbeitest in einer dauerhaften Konversation. Beziehe dich bei Folgefragen auf früher Besprochenes und auf abgelegte Notizen, aber nur, nachdem du den aktuellen Bestand tatsächlich gelesen hast; Behauptungen über Bestände und Stände stammen aus Werkzeugausgaben, nicht aus dem Gedächtnis der Konversation. Lies vor jeder Änderung an einem abgelegten Dokument dessen aktuellen Stand.

## 6. Hook-Transparenz

Ist ein Prüfhook in deiner Sitzung aktiv, ordnest du zu Beginn jeder Abgabe eine Transparenzmeldung (maximal fünf Sätze) an, die ausschließlich die tatsächlich implementierten Prüfungen benennt: Benenne keine Prüfung, die nicht existiert, und lasse keine bestehende aus. Führe wörtliche Zitate als solche durch die Zitatprüfung, statt sie als paraphrasierte Aussagen mit Evidenzgrad an der Prüfung vorbeizuführen.

## 7. Sprache und Zitation

Schreibe wissenschaftliches Deutsch in VOLLEN, ausformulierten Sätzen — keine Stichwortketten, keine Klammer-Telegramme. Erkläre kurz, was du gerade tust bzw. getan hast (z. B. „Ich lese jetzt Dokument X …“), halte dich präzise und kompakt: nicht unnötig lange Texte, aber vollständig begründet. Definiere fachspezifische Begriffe bei erster Verwendung. Zitiere nach dem Autor-Jahr-System mit nachvollziehbarem Literaturverzeichnis, URLs und Zugriffsdatum. Halte verbindliche Längen- und Formatvorgaben ein.


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

SESSION-START-REGEL (bei jeder neuen Session zuerst ausfuehren): ablage_durchsuchen mit allgemeinen Stichworten wie "Projektstand", "offene Punkte", "Anweisung", "letzter Stand" aufrufen (parallel dazu bibliotheken_auflisten, aktuelles_datum, projektdateien_auflisten) und den bisherigen Stand in die Antwort einbeziehen. Session-Verlauf ist fluechtig (Redeploys terminieren alte Sessions) - die Research-Ablage ist das dauerhafte Gedaechtnis.

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
- TOOL-LIBRARY-ZUORDNUNG (verbindlich): projektquellen_suchen = NUR Grammatik-statt-Stil-Bibliothek (01a1843c-...) + Katalogstadt (01a182d2-...); ablage_durchsuchen = NUR Research-Ablage (01a1b7a7-...); projektdateien_auflisten = ALLE vier Libraries (2 Projekt-Libraries + Research-Ablage + Apparat-Bibliothek); zitat_pruefen/text_content = exakter Volltext fuer Zitate aus JEDER Library.

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
    arbeitsupdate: str = Field(default="", description="PFLICHT nach jeder Arbeitsrunde: Klartext-Update in vollen Saetzen, was in diesem Turn recherchiert/gelesen/abgelegt wurde (plain text, keine Stichpunkte).")


async def _resolve_library(client, library_id: str, document_id: str) -> str:
    """Wenn library_id leer/unbekannt: Dokument ueber alle 4 Libraries aufloesen (dokument_finden-Logik)."""
    if library_id:
        return library_id
    for lib in (APPARAT_LIBRARY_ID, PROJECT_LIBRARY_ID, CATALOG_LIBRARY_ID, NOTES_LIBRARY_ID):
        try:
            await client.beta.libraries.documents.get_async(library_id=lib, document_id=document_id)
            return lib
        except Exception:
            continue
    return library_id


@agents.tool
async def web_recherche(
    query: Annotated[str, Field(description="Präzise Such-/Recherchefrage.")] = "",
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
    query: Annotated[str, Field(description="Frage oder Suchbegriff in den Projekt-Dokumenten.")] = "",
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
    query: Annotated[str, Field(description="Wonach in den Research-Notizen gesucht werden soll.")] = "",
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
        ("apparat_bibliothek", APPARAT_LIBRARY_ID),
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
    titel: Annotated[str, Field(description="Titel der Notiz (kurz, eindeutig).")] = "",
    thema: Annotated[str, Field(description="Thema/Stichwort.")] = "",
    markdown: Annotated[str, Field(description="Vollständiger Notiztext als Markdown.")] = "",
) -> dict:
    """Legt eine Research-Notiz systematisch in der Ablage-Library „Grammatik statt Stil – Research-Ablage (Agent)“ ab und gibt die Dokument-ID zurück."""
    if not titel or not markdown:
        return {"fehler": "titel/markdown fehlen - beide aus der Aufgabe entnehmen, nie leer lassen."}
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
    document_id: Annotated[str, Field(description="Dokument-ID.")],
    zitat: Annotated[str, Field(description="Das angebliche wörtliche Zitat, das geprueft werden soll.")] = "",
    library_id: Annotated[str, Field(description="Optional: Library-ID aus bibliotheken_auflisten. Wenn leer, automatische Aufloesung ueber alle 4 Libraries.")] = "",
) -> dict:
    """PFLICHT vor jedem wörtlichen Zitat: prueft per Substring-Suche im exakten Dokument-Volltext (text_content), ob das Zitat dort vorkommt. Ergebnis: found True/False + Fundstelle. NIEMALS ein Zitat als wörtlich ausgeben ohne found=True."""
    client = _client()
    library_id = await _resolve_library(client, library_id, document_id)
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
    document_id: Annotated[str, Field(description="Dokument-ID.")] = "",
    library_id: Annotated[str, Field(description="Optional: Library-ID. Wenn leer, automatische Aufloesung ueber alle 4 Libraries.")] = "",
) -> dict:
    """Liefert den EXAKTEN Volltext eines Library-Dokuments (text_content). NIE client.*-Tools aufrufen (die gehoeren zum Vibe-Chat); nur dieses Server-Tool. IDs nur aus projektdateien_auflisten/dokument_finden. Pflicht bei Aufgaben mit wörtlichen Zitaten, IDs oder genauen Zahlen - niemals ueber RAG raten."""
    if not document_id:
        return {"fehler": "document_id fehlt - nur echte Dokument-IDs aus Tool-Ausgaben (projektdateien_auflisten/dokument_finden), nie raten."}
    client = _client()
    library_id = await _resolve_library(client, library_id, document_id)
    content = await client.beta.libraries.documents.text_content_async(library_id=library_id, document_id=document_id)
    text = getattr(content, "text", None) or str(content)
    # Verlauf klein halten: Volltext kappen (in_dokument_suchen/zitat_pruefen liefern gezielte Ausschnitte)
    volltext = text[:6000] + (" ... [gekürzt, Gesamtlänge %d Zeichen - für Details in_dokument_suchen/zitat_pruefen nutzen]" % len(text) if len(text) > 6000 else "")
    return {"document_id": document_id, "library_id": library_id, "laenge": len(text), "volltext": volltext}


@agents.tool
async def web_zitat_pruefen(
    zitat: Annotated[str, Field(description="Das angebliche wörtliche Zitat.")],
    url: Annotated[str, Field(description="URL der Quelle, aus der zitiert werden soll.")] = "",
) -> dict:
    """PFLICHT vor jedem wörtlichen Zitat aus einer WEBQUELLE. v2: liefert bei Treffer Kontext (+-250 Zeichen um die Fundstelle), normalisiert HTML-Entities/Quotes/Whitespace, erkennt PDFs und nutzt dann OCR (mistral-ocr-4-1). found=True erforderlich."""
    import re, html, httpx
    if not url or not zitat:
        return {"fehler": "url und zitat fehlen - beide aus Tool-Ausgaben/Quelle entnehmen."}
    def norm(s):
        s = html.unescape(s)
        s = s.replace("\u201e", '"').replace("\u201c", '"').replace("\u2018", "'").replace("\u2019", "'").replace("\u2013", "-").replace("\u2014", "-").replace("\u00a0", " ")
        return re.sub(r"\s+", " ", s).strip().lower()
    try:
        async with httpx.AsyncClient(timeout=40, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as hc:
            resp = await hc.get(url)
            ctype = resp.headers.get("content-type", "")
            if "pdf" in ctype.lower() or url.lower().endswith(".pdf"):
                client = _client()
                ocr = await client.ocr.process_async(model="mistral-ocr-4-1", document={"type": "document_url", "document_url": url})
                text = "\n".join(getattr(p, "markdown", "") or "" for p in (getattr(ocr, "pages", []) or []))
            else:
                text = resp.text
    except Exception as e:
        return {"found": False, "url": url, "fehler": f"Seite nicht abrufbar: {e}"}
    nt, nz = norm(text), norm(zitat)
    found_norm = nz in nt
    found_exact = zitat in text
    out = {"found": found_norm, "found_exact_inkl_leerzeichen": found_exact, "url": url, "http_status": resp.status_code, "pdf_via_ocr": "pdf" in ctype.lower()}
    if found_norm:
        i = nt.find(nz)
        out["kontext"] = text[max(0, i-250): i+len(zitat)+250].replace("\n", " ")
        out["fundstelle_hint"] = "Treffer nach Normierung (Entities/Whitespace bereinigt)"
    elif found_exact:
        i = text.find(zitat)
        out["kontext"] = text[max(0, i-250): i+len(zitat)+250].replace("\n", " ")
    else:
        out["diagnose"] = "Zitat weder exakt noch normiert gefunden; Seite gekuerzt auf %d Zeichen geprueft." % len(text)
    return out


@agents.tool
async def doi_pruefen(
    doi: Annotated[str, Field(description="DOI, z. B. 10.1016/j.autcon.2008.09.006.")] = "",
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
    document_id: Annotated[str, Field(description="Dokument-ID.")],
    begriff: Annotated[str, Field(description="Suchbegriff (Substring, case-insensitive).")] = "",
    library_id: Annotated[str, Field(description="Optional: Library-ID. Wenn leer, automatische Aufloesung.")] = "",
) -> dict:
    """Grep-aehnliche Suche im exakten Volltext eines Library-Dokuments. Liefert alle Treffer mit Kontext. Deterministisch - nutze das statt RAG fuer exakte Nachweise."""
    if not begriff or not document_id:
        return {"fehler": "begriff und document_id fehlen - beide aus der Aufgabe/Tool-Ausgabe entnehmen."}
    client = _client()
    library_id = await _resolve_library(client, library_id, document_id)
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


@agents.tool
async def bibliotheken_auflisten() -> dict:
    """Liefert ALLE Bibliotheken des Workspace mit kanonischen IDs und Namen (aus der API, nicht aus Erinnerung). VOR jeder Angabe einer Bibliotheks-ID dieses Tool aufrufen und die ID daraus kopieren (E7)."""
    client = _client()
    res = await client.beta.libraries.list_async()
    items = res.data if hasattr(res, "data") else res
    return {"bibliotheken": [{"id": l.id, "name": l.name} for l in items]}


@agents.tool
async def dokument_finden(
    document_id: Annotated[str, Field(description="Dokument-ID (UUID) - wird automatisch ueber ALLE Libraries aufgeloest.")] = "",
) -> dict:
    """Loest eine Dokument-ID automatisch ueber alle 4 Libraries auf (Apparat, Grammatik-statt-Stil, Katalogstadt, Research-Ablage) und liefert die korrekte library_id + Name. IMMER vor dokument_lesen/zitat_pruefen mit einer Dokument-ID verwenden (E7/E3)."""
    if not document_id:
        return {"fehler": "document_id fehlt - nur echte Dokument-IDs aus Tool-Ausgaben verwenden (dokument_finden/projektdateien_auflisten), nie raten."}
    client = _client()
    libs = [APPARAT_LIBRARY_ID, PROJECT_LIBRARY_ID, CATALOG_LIBRARY_ID, NOTES_LIBRARY_ID]
    for lib in libs:
        try:
            doc = await client.beta.libraries.documents.get_async(library_id=lib, document_id=document_id)
            return {"document_id": document_id, "library_id": lib, "name": doc.name, "status": doc.processing_status}
        except Exception:
            continue
    return {"document_id": document_id, "library_id": None, "gefunden": False}


@agents.tool
async def aktuelles_datum() -> dict:
    """Liefert das aktuelle Datum/Uhrzeit (UTC) aus der Worker-Systemuhr. PFLICHT vor jeder Datumsangabe (Zugriffsdatum, Fristen, Titel mit Datum): niemals ein Datum aus Erinnerung oder Annahme verwenden."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return {"utc": now.isoformat(), "datum": now.date().isoformat(), "uhrzeit": now.strftime("%H:%M:%S")}


@agents.tool
async def pdf_ocr(
    url: Annotated[str, Field(description="Exakte URL eines PDFs (aus Tool-Ausgabe/Quelle, nie geraten).")],
) -> dict:
    """Laedt ein Web-PDF per mistral-ocr-4 (OCR) und liefert Markdown-Text. Zuvor url_status_pruefen: Sperre (403) != 404. Ergebnis gekappt; Details via in_dokument_suchen nach Ablage."""
    import httpx
    if not url:
        return {"fehler": "url fehlt - nur exakte URLs aus Tool-Ausgaben verwenden."}
    client = _client()
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as hc:
            head = await hc.head(url)
            if head.status_code in (403, 429):
                return {"url": url, "fehler": "gesperrt (HTTP %d) - keine Umgehung; Grenzangabe nach E6." % head.status_code}
            if head.status_code == 404:
                return {"url": url, "fehler": "404 - nicht gefunden."}
        resp = await client.ocr.process_async(model="mistral-ocr-4-1", document={"type": "document_url", "document_url": url})
        pages = getattr(resp, "pages", []) or []
        text = "\n\n".join(getattr(p, "markdown", "") or "" for p in pages)
        return {"url": url, "seiten": len(pages), "laenge": len(text), "text": text[:8000] + (" ... [gekürzt]" if len(text) > 8000 else "")}
    except Exception as e:
        return {"url": url, "fehler": str(e)[:300]}


@agents.tool
async def pdf_in_ablage_speichern(
    url: Annotated[str, Field(description="Exakte PDF-URL (aus Tool-Ausgabe).")],
    titel: Annotated[str, Field(description="Dateiname/Titel fuer die Ablage, z. B. Autor_Jahr_Titel.pdf")] = "",
) -> dict:
    """Laedt ein Web-PDF herunter und speichert es als Dokument in der Research-Ablage (serverseitig verarbeitet, danach per dokument_lesen/in_dokument_suchen/zitat_pruefen nutzbar). Legitime Wege only (E6)."""
    import httpx
    if not url:
        return {"fehler": "url fehlt."}
    client = _client()
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as hc:
            resp = await hc.get(url)
            if resp.status_code in (403, 429):
                return {"url": url, "fehler": "gesperrt (HTTP %d) - keine Umgehung; Grenzangabe E6." % resp.status_code}
            if resp.status_code != 200:
                return {"url": url, "fehler": "HTTP %d" % resp.status_code}
            name = titel or url.split("/")[-1].split("?")[0] or "dokument.pdf"
            if not name.lower().endswith(".pdf"):
                name += ".pdf"
            doc = await client.beta.libraries.documents.upload_async(library_id=NOTES_LIBRARY_ID, file={"file_name": name, "content": resp.content})
            return {"url": url, "document_id": doc.id, "name": doc.name, "library_id": NOTES_LIBRARY_ID, "status": doc.processing_status}
    except Exception as e:
        return {"url": url, "fehler": str(e)[:300]}



KNOWN_TOOL_NAMES = {"web_recherche", "projektquellen_suchen", "ablage_durchsuchen", "projektdateien_auflisten", "bibliotheken_auflisten", "dokument_finden", "research_note_ablegen", "zitat_pruefen", "web_zitat_pruefen", "dokument_lesen", "doi_pruefen", "url_status_pruefen", "in_dokument_suchen", "aktuelles_datum", "pdf_ocr", "pdf_in_ablage_speichern"}


class QuoteAuditHook(agents.Hook):
    """Sichert Zitate UND Negativbefunde ab. Pro Turn (State wird in pre_agent_turn zurueckgesetzt):
    - sammelt verifizierte Zitate (zitat_pruefen/web_zitat_pruefen found=True) und alle Tool-Calls
    - post_agent_turn: unverifizierte verbatim_zitate ODER Negativbefund ("nicht gefunden"/"nicht lesbar"/
      "nicht existiert") ohne Such-Tool-Call im selben Turn -> Retry mit Feedback (max 2), dann Reject."""

    verified: list[str] = Field(default_factory=list)
    tools_called: list[str] = Field(default_factory=list)
    retries: int = 0
    consec_errors: int = 0


    async def pre_agent_turn(self, ctx, request):
        self.verified = []
        self.tools_called = []
        self.tool_texts = []
        self.retries = 0
        self.consec_errors = 0
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
        # State klein halten (65536-Byte-Limit): nur UUIDs + kurzer Hash pro Tool-Ergebnis speichern
        if ("fehler" in txt.lower() or "invalid arguments" in txt.lower() or "not found" in txt.lower()) and name in KNOWN_TOOL_NAMES:
            self.consec_errors += 1
        else:
            self.consec_errors = 0
        ids = _re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", txt)
        import hashlib
        self.tool_texts = (self.tool_texts + ids + [hashlib.sha256(txt.encode()).hexdigest()[:16]])[:200]
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
                import hashlib as _hl
                h = _hl.sha256(_norm(str(data.get("zitat", ""))).encode()).hexdigest()
                self.verified = (self.verified + [h])[:100]
        return None

    async def post_llm_call(self, ctx, result):
        if getattr(result, "tool_calls", None):
            return None
        if self.consec_errors >= 3:
            return agents.retry("STOPP: 3+ aufeinanderfolgende fehlgeschlagene Tool-Calls. Pruefe die Argumente sorgfaeltig: IDs nur aus projektdateien_auflisten/bibliotheken_auflisten/dokument_finden kopieren, nie raten. Dann erst weiter.")
        text = getattr(result, "text", "") or ""
        try:
            data = _json.loads(text)
        except Exception:
            data = None
        if not isinstance(data, dict):
            return None
        problems = []
        quotes = data.get("verbatim_zitate") or []
        import hashlib as _hl2
        for q in quotes:
            qt = _norm(str(q.get("text", "")))
            if qt and _hl2.sha256(qt.encode()).hexdigest() not in self.verified:
                problems.append("unverifiziertes Zitat: " + qt[:100])
        search_tools = {"dokument_lesen", "zitat_pruefen", "web_zitat_pruefen", "ablage_durchsuchen", "projektquellen_suchen", "projektdateien_auflisten", "web_recherche", "dokument_finden", "bibliotheken_auflisten", "aktuelles_datum", "pdf_ocr", "pdf_in_ablage_speichern"}
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
        # 4. Prüfbare Claims (ID/URL/DOI/Zahl/Zitat in Aussage oder Quelle) brauchen Such-Tool-Call im selben Turn;
        #    "gesichert" generell nur mit Tool-Call. Reine Deutungen/Allgemeinwissen ohne Quelle bleiben zulaessig.
        for a in data.get("belegte_aussagen") or []:
            if not isinstance(a, dict):
                continue
            aussage = str(a.get("aussage", ""))
            quelle = str(a.get("quelle", ""))
            ev = str(a.get("evidenzgrad", "")).lower()
            is_pruefbar = bool(_re.search(r"[0-9a-f]{8}-[0-9a-f]{4}|https?://|doi:|\d{4}|[\u201e\u201c\"']", aussage + " " + quelle))
            no_tool = not (set(self.tools_called) & search_tools)
            if "gesichert" in ev and no_tool:
                problems.append("evidenzgrad=gesichert ohne Such-Tool-Call: " + aussage[:100])
            elif is_pruefbar and no_tool:
                problems.append("prüfbarer Claim (ID/URL/DOI/Zahl/Zitat) ohne Such-Tool-Call: " + aussage[:100])
        # 5. ID-Herkunft (E7): jede UUID in der Antwort muss in Tool-Ergebnissen des Turns
        # oder unter den bekannten Library-IDs vorkommen
        known_libs = {"01a1843c-f463-71db-a3fe-ae8b3814f155", "01a182d2-0a6f-762d-9fc3-a4150e53e3be", "01a1b7a7-d3b3-7603-9601-7efb317d38ee", "01a1c18b-fe93-75a4-8c2b-871c9f112cd9"}
        for i in ids_in_answer:
            if _norm(i) not in tool_blob and i not in known_libs:
                problems.append("ID nicht aus Tool-Output/Library-Konstante: " + i)
        if not problems:
            return None
        feedback = ("VERBOTEN: " + " | ".join(problems) +
                    ". Regeln: wörtliche Zitate nur mit zitat_pruefen/web_zitat_pruefen found=True in DIESEM Turn; "
                    "Negativbefunde nur nach dokument_lesen/ablage_durchsuchen/projektquellen_suchen/projektdateien_auflisten-Call mit dokumentiertem Ergebnis in double_check.")
        if self.retries < 2:
            self.retries = self.retries + 1
            return agents.retry(feedback)
        return agents.reject("Turn abgelehnt: " + feedback)



agent = agents.Agent(
    model="mistral-large-4-0",
    temperature=0.1,
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
        bibliotheken_auflisten,
        dokument_finden,
        aktuelles_datum,
        pdf_ocr,
        pdf_in_ablage_speichern,
        zitat_pruefen,
        dokument_lesen,
        web_zitat_pruefen,
        doi_pruefen,
        url_status_pruefen,
        in_dokument_suchen,
        research_note_ablegen,
    ],
    max_iterations=25,
)
