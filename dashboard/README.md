# Research-Dashboard „Grammatik statt Stil“ (lokal)

Minimalistisches, lokales Dashboard für das Projekt „Grammatik statt Stil – PCG als Entwurfsmethode“.
Keine Build-Schritte, keine externen Abhängigkeiten (nur Python-Standardbibliothek + Browser).

## Start

```bash
cd dashboard
python3 serve.py            # http://127.0.0.1:8765/
# optional: python3 serve.py --port 9000
```

Aufruf im Browser: **http://127.0.0.1:8765/** — der Server bindet nur an `127.0.0.1` (Loopback, kein externer Zugriff).

Ohne Server genügt auch das direkte Öffnen von `index.html` (file://) — dann dienen die Fallback-Daten aus `data/sample-data.js` und der Postausgang ist deaktiviert.

## Inhalte

- **Übersicht** — Live-Kennzahlen: Positionen gesamt, Volltextquote (K1+K2)/N, K1–K5/V, Ø Quellendichte pro Gruppe; Charts (Donut K-Verteilung, Balken Quellendichte je Gruppe, Relevanzverteilung).
- **Verzeichnis** — durchsuchbares/filterbares wissenschaftliches Verzeichnis (ID G/Nr., Titel, Quelle, K-Stufe, Relevanz, Vermerk).
- **Glossar** — K1–K5, V, W1/W2/W4, VT-Quote, G/Nr., A/B/C/P, Sammelposition.
- **Kommunikation** — zentrale Eingabemaske; Nachrichten werden lokal in `data/outbox.jsonl` protokolliert (Postausgang).

## Daten

`data/project.json` enthält Beispieldaten (Auszug, Stand 12.11.2026: 378 Positionen, K1 179 / K2 111 / K3 78 / K4 1 / K5 4 / V 5, Gruppen-Enden 38/80/143/57/18/20/22, VT-Quote 76,7 % = 290/378).

Für echte Live-Daten `data/project.json` durch den Export des Quellenverzeichnisses ersetzen (Format siehe Datei) und `data/sample-data.js` neu generieren:

```bash
python3 -c "import json;d=json.load(open('data/project.json',encoding='utf-8'));open('data/sample-data.js','w',encoding='utf-8').write('window.DASHBOARD_DATA = '+json.dumps(d,ensure_ascii=False,indent=2)+';\n')"
```

## Optionaler Live-Modus (Ablage)

`GET /api/live` listet die neuesten Dokumente der Research-Ablage, **nur wenn** `mistralai` installiert ist und `MISTRAL_API_KEY` (oder `PROJECT_MISTRAL_API_KEY`) in der Umgebung gesetzt ist. Der Key wird nie fest im Code hinterlegt. Ohne Key bleibt das Dashboard rein lokal (Badge „lokal“).

## Versand an den produktiven Agenten

Das Deployment `grammatik-statt-stil-research` (Branch `vibe/forschungsagent-b21b74`) wird über die Mistral-Plattform betrieben. Nachrichten vom Dashboard werden lokal im Postausgang (`data/outbox.jsonl`) gehalten; der Versand an den Agenten erfolgt über die MCP-/Studio-Schnittstelle (`execute_workflow` bzw. Signale `submit_command` / `send_message` / `start_turn`) mit dem eigenen Workspace-Key.
