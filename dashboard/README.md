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

## Inhalte (Module)

- **Übersicht** — Live-Kennzahlen: Positionen gesamt, Volltextquote (K1+K2)/N, K1–K5/V, Ø Quellendichte pro Gruppe; Charts (Donut K-Verteilung, Balken Quellendichte je Gruppe, Relevanzverteilung).
- **Verzeichnis** — wissenschaftliches Verzeichnis (ID G/Nr., Titel, Quelle, K-Stufe, Relevanz, Vermerk). Mit Server: Suche direkt in der QV-Datenbank (SQLite, FTS5 falls verfügbar, sonst LIKE), Filter K/Rel., pro Zeile **Heben**-Button (K-Hebung nach K1/K2 mit Beleg-Pflicht), **Änderungslog** und **JSON-Export**. Ohne Server (file://): lokaler Filter auf `data/sample-data.js`.
- **Ablage** — Live-Browser für die Research-Ablage (Mistral Library): Suche, Dokumentliste, Vorschau (erste 4000 Zeichen). Nur mit Server + API-Key in der Umgebung; sonst Hinweis „lokal“.
- **Glossar** — K1–K5, V, W1/W2/W4, VT-Quote, G/Nr., A/B/C/P, Sammelposition.
- **Kommunikation** — zentrale Eingabemaske; Nachrichten werden lokal in `data/outbox.jsonl` protokolliert (Postausgang).

## Daten

`data/project.json` enthält Beispieldaten (Auszug, Stand 12.11.2026: 378 Positionen, K1 179 / K2 111 / K3 78 / K4 1 / K5 4 / V 5, Gruppen-Enden 38/80/143/57/18/20/22, VT-Quote 76,7 % = 290/378).

Für echte Live-Daten `data/project.json` durch den Export des Quellenverzeichnisses ersetzen (Format siehe Datei) und `data/sample-data.js` neu generieren:

```bash
python3 -c "import json;d=json.load(open('data/project.json',encoding='utf-8'));open('data/sample-data.js','w',encoding='utf-8').write('window.DASHBOARD_DATA = '+json.dumps(d,ensure_ascii=False,indent=2)+';\n')"
```

## Optionaler Live-Modus (Ablage)

`GET /api/live` listet die neuesten Dokumente der Research-Ablage plus die QV-Standzeile aus dem Apparat, **nur wenn** `mistralai` installiert ist und `MISTRAL_API_KEY` (oder `PROJECT_MISTRAL_API_KEY`) in der Umgebung gesetzt ist. Der Key wird nie fest im Code hinterlegt. Ohne Key bleibt das Dashboard rein lokal (Badge „lokal“).

## QV-Datenbank, K-Hebung, Export (Server-Modus)

Beim Start legt `serve.py` `data/qv.db` an (SQLite; FTS5-Volltexttabelle `pos_fts` falls verfügbar, sonst LIKE-Fallback) und befüllt sie aus `data/project.json` (`verzeichnis`). K-Hebungen werden in `qv.db` **und** zurück in `data/project.json` geschrieben (Write-Through inkl. `kstand` und Vermerk).

- `GET /api/qv?q=&k=&rel=&limit=` — Suche/Filter über alle Positionen (debounced aus der UI)
- `POST /api/qv/hebung` — `{"id","neu_k":"K1|K2","beleg","datum":"JJJJ-MM-TT"}`; nur K1/K2 erlaubt, Beleg ist Pflicht, Datum darf nicht in der Zukunft liegen; jeder Vorgang landet in der Tabelle `aenderungen`
- `GET /api/qv/aenderungen` — Änderungslog (neueste zuerst, max 200)
- `GET /api/qv/export` — kompletter QV als JSON-Download (inkl. DB-Stand + Änderungslog)

`data/qv.db` und `data/outbox.jsonl` sind via `.gitignore` vom Repo ausgeschlossen.

## Ablage-Browser (live)

- `GET /api/ablage?q=` — Dokumentliste der Research-Ablage (Library-ID fest im Code), optional mit Suchbegriff
- `GET /api/ablage/doc?id=` — Text-Vorschau (erste 4000 Zeichen) eines Dokuments

Beide antworten ohne Key mit `{"live": false, "grund": ...}`.

## API-Übersicht

`GET /api/stats` · `/api/verzeichnis` · `/api/glossar` · `/api/messages` · `/api/live` · `/api/ablage` · `/api/ablage/doc` · `/api/qv` · `/api/qv/aenderungen` · `/api/qv/export` — sowie `POST /api/message` · `POST /api/qv/hebung`.

## Versand an den produktiven Agenten

Das Deployment `grammatik-statt-stil-research` (Branch `vibe/forschungsagent-b21b74`) wird über die Mistral-Plattform betrieben. Nachrichten vom Dashboard werden lokal im Postausgang (`data/outbox.jsonl`) gehalten; der Versand an den Agenten erfolgt über die MCP-/Studio-Schnittstelle (`execute_workflow` bzw. Signale `submit_command` / `send_message` / `start_turn`) mit dem eigenen Workspace-Key.

## Zugriff vom iPhone / anderen Geräten (gleiches WLAN)

Standardmäßig bindet der Server nur an `127.0.0.1` — dann ist nur der lokale Rechner dran. Für Zugriff aus dem Heimnetz:

```bash
python3 serve.py --host 0.0.0.0 --port 8765
```

IP des Mac ablesen (Systemeinstellungen → WLAN → Details), z. B. `192.168.1.23`; am iPhone im **gleichen WLAN** Safari öffnen: `http://192.168.1.23:8765/`. macOS-Firewall ggf. freigeben. Achtung: dann ist das Dashboard im LAN ohne Auth sichtbar — nur in vertrauenswürdigen Netzen nutzen, nie öffentlich ins Internet exponieren (kein Tunnel/Port-Forwarding).

**Offline ohne Server:** Ordner `dashboard/` aufs iPhone kopieren (AirDrop/iCloud) und `index.html` direkt in Safari öffnen — Fallback-Daten aus `data/sample-data.js`, Postausgang deaktiviert.

Das Dashboard ist bewusst **nicht** Teil des Workflow-Deployments (`grammatik-statt-stil-research` serviert den Agenten, nicht das Dashboard).
