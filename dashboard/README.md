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
- **Quellen** — Quellendatenbank: Positionen gruppiert nach Quelle/Fundstelle mit Anzahl, K-Verteilung (Balken) und Positions-IDs; Suche + JSON-Export. Server: Aggregation in SQLite (`/api/quellen`), offline: lokal aus `data/project.json`.
- **Ablage** — Live-Browser für die Research-Ablage (Mistral Library): Suche, Dokumentliste, Vorschau (erste 4000 Zeichen). Nur mit Server + API-Key in der Umgebung; sonst Hinweis „lokal“.
- **Bibliothek** — Live-Übersicht **aller** Libraries des Workspace mit Dokumentzahl, Drill-down Library → Dokumente (Suche) → Vorschau (`/api/libraries`, `/api/library/docs`, `/api/library/doc`).
- **Text** — Textproduktion/Review/Export: Templates aus `data/templates.json` rendern (`{{key}}`-Platzhalter, Kontext aus QV-Position + Zusatzfeldern; `POST /api/render`), Ergebnis kopieren / als `.md` laden / drucken (`@media print`), zeilenweiser Diff A-vs-B (`POST /api/diff`, difflib serverseitig, LCS-Fallback offline).
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

`GET /api/stats` (inkl. `extra`: Jahresdekaden, Quellentypen, Gruppe×K-Matrix) · `/api/verzeichnis` · `/api/glossar` · `/api/historie` (K-Stand-Verlauf aus den Standzeilen) · `/api/messages` · `/api/live` · `/api/ablage` · `/api/ablage/doc` (mit `offset` seitenweise) · `/api/libraries` · `/api/library/docs` · `/api/library/doc` (mit `offset`) · `/api/qv` (mit `q/k/rel/limit/offset`) · `/api/qv/aenderungen` · `/api/qv/export` (JSON-Download; `?format=ris|bib` für RIS/BibTeX) · `/api/qv/snapshots` · `/api/qv/diff?a=&b=` (Snapshot-Vergleich: hinzu/entfernt/geändert) · `/api/dupes` · `/api/pruef` · `/api/coverage` (Zitations-Coverage gegen das Essay in der Projekt-Bibliothek) · `/api/quellen` · `/api/templates` — sowie `POST /api/message` · `POST /api/qv/hebung` · `POST /api/qv/edit` (Titel/Quelle/Vermerk/Rel/Prio, Write-Through) · `POST /api/pruef` · `POST /api/import` (Re-Import aus der Apparat-Bibliothek, legt Snapshot an) · `POST /api/render` · `POST /api/diff` · `POST /api/agent/send` (live an den Forschungsagenten, s. u.)

Optionen: `--token <t>` (schützt `/api/*` und `/data/*` via `?token=` oder Header `X-Hub-Token`; Env `DASHBOARD_TOKEN`), `--log` (Access-Log nach `data/hub.log`). Live-Endpunkte (`/api/live`, `/api/ablage*`, `/api/libraries`, `/api/library/*`, `/api/coverage`) werden 20–300 s gecacht und bei Fehler einmal mit Backoff wiederholt. Der Server spricht HTTP/1.1 (Keep-Alive), beantwortet `HEAD`, und serviert statisch nur eine Whitelist an Dateiendungen (`.html .js .css .json .md .webmanifest .png .svg .ico .db .map`, keine Dotfiles) — Quellcode unter `dashboard/` bleibt 404. Alle Antworten tragen `X-Content-Type-Options: nosniff` und `Cache-Control: no-store`. POST-Fehler werden mit Traceback in `data/debug-trace.log` protokolliert.

## Tabs

Übersicht (Stats mit Count-up, K-Donut, Gruppen-Balken, **Erschließungsquote im Verlauf**, **Gruppe×K-Heatmap**, Relevanz-Donut, Coverage-Karte — Klick auf Segmente/Zellen/Legende filtert das Verzeichnis) · Verzeichnis (Suche/FTS, Filter K/Rel./Gruppe/Prio/nur-zitierte/Duplikate, **Sortieren per Klick auf Spaltenkopf**, Inline-Edit per Doppelklick, K-Hebung, RIS/BibTeX/JSON-Export, QV-aktualisieren-Button) · Quellen · **Prüfaufgaben** (aus dem QV-Abschnitt „Offene Prüfaufgaben“, Status offen/erledigt serverseitig persistiert) · Ablage (live, Neu-Badges, seitenweise Vorschau) · Bibliothek · Text · Glossar · Kommunikation.

## Dashboard in die Library ablegen (Zugriff für Online-Agent-Sessions)

`tools/upload_dashboard.py` (venv-Python mit `mistralai`, Key aus Env/Schlüsselbund) lädt das **komplette Dashboard** in die Library **„Hub-Uebergabe (Dashboard Handoff)"** — alle Text/Code-Dateien, Icons, `data/project.json`, `data/qv-export.json` (vollständige DB inkl. Änderungslog), `data/agent-conv.json` (aktuelle Session-ID) und ein generiertes `index.md` als Datei-Map. Idempotent über das Namenspräfix `dashboard-<YYYY-MM-DD>-`. Online-Sessions des Agents können die Library danach durchsuchen. Nicht hochgeladen: `qv.db` (binär), `snapshots/`, `__pycache__`.

## Daten-Import

`tools/import_apparat.py` liest `Apparat_Quellenverzeichnis.md` + `Apparat_Volltext-Inventar.md` aus der Apparat-Bibliothek und schreibt `data/project.json` (Positionen mit K/Rel/Prio/Jahr/Typ, Prüfaufgaben, Historie) + `data/sample-data.js`. Re-Import im laufenden Betrieb: Button „QV aktualisieren“ im Verzeichnis-Tab (`POST /api/import`, legt vorher `data/snapshots/project-<ts>.json` an; `GET /api/qv/snapshots` + `GET /api/qv/diff` zeigen die Änderung zwischen zwei Ständen). Die QV-DB seedet bei mtime-/Schema-Wechsel automatisch neu.

Smoke-Test: `python3 tools/smoke_test.py` (29 Checks gegen den laufenden Server).

Die QV-SQLite (`data/qv.db`) wird bei jedem `/api/qv*`-Aufruf gegen die mtime von `data/project.json` geprüft und bei Änderung (z. B. Re-Import via `tools/import_apparat.py`) automatisch neu geseedet — kein Server-Neustart nötig.

## Direkt an den Forschungsagenten senden

`POST /api/agent/send` `{"text": "..."}` schickt die Nachricht asynchron an den Managed Agent `grammatik-statt-stil-research` (chat.mistral.ai/managed-agents, Name via Env `FORSCHUNG_AGENT_NAME` änderbar) über die Agents-v2-Sessions-API (`POST /v2/agents/sessions` + `/sessions/{id}/commands`; Control-Plane via Env `FORSCHUNG_AGENTS_BASE` änderbar). Antwort: sofort `{"live": true, "queued": true, "command_id": ..., "session_id": ...}`; die Antwort selbst pollt das Dashboard per `GET /api/agent/pending?command_id=...&wait=25` (Events aus `/sessions/{id}/events/history` bis `turn_terminated`). Mit `{"sync": true, "wait": 180}` bleibt der Aufruf blockierend (CLI/curl). Die Session-ID bleibt in `data/agent-conv.json` (gitignored) gespeichert — Folgemessages gehen an dieselbe Session. `GET /api/agent/history` liest den Session-Verlauf, `POST /api/agent/reset` löscht die Session-ID (nächste Nachricht startet eine neue Session). Ohne API-Key: `{"live": false, "grund": ...}` — das Dashboard bleibt dann lokal.

## Versand an den produktiven Agenten

Das Deployment `grammatik-statt-stil-research` (Branch `vibe/forschungsagent-b21b74`, siehe `forschungsagent/` im Repo) wird als Managed Agent auf der Mistral-Plattform betrieben (chat.mistral.ai/managed-agents/grammatik-statt-stil-research). Das Dashboard spricht ihn direkt über die Sessions-API an (s. o.); zusätzlich kann der Versand über die MCP-/Studio-Schnittstelle erfolgen.

## Zugriff vom iPhone / anderen Geräten (gleiches WLAN)

Standardmäßig bindet der Server nur an `127.0.0.1` — dann ist nur der lokale Rechner dran. Für Zugriff aus dem Heimnetz:

```bash
python3 serve.py --host 0.0.0.0 --port 8765
```

IP des Mac ablesen (Systemeinstellungen → WLAN → Details), z. B. `192.168.1.23`; am iPhone im **gleichen WLAN** Safari öffnen: `http://192.168.1.23:8765/`. macOS-Firewall ggf. freigeben. Achtung: dann ist das Dashboard im LAN ohne Auth sichtbar — nur in vertrauenswürdigen Netzen nutzen, nie öffentlich ins Internet exponieren (kein Tunnel/Port-Forwarding).

**Offline ohne Server:** Ordner `dashboard/` aufs iPhone kopieren (AirDrop/iCloud) und `index.html` direkt in Safari öffnen — Fallback-Daten aus `data/sample-data.js`, Postausgang deaktiviert.

## PWA („Zum Home-Bildschirm“ / Standalone-App)

`manifest.webmanifest` + `sw.js` + Icons (`icons/`, erzeugt mit `python3 tools/make_icons.py`, reines stdlib) sind enthalten. Safari/iOS: „Zum Home-Bildschirm“ — die App läuft dann standalone mit Icon. Service Worker: statische Assets cache-first, `/api/*` und `/data/*` network-first (Offline-Fallback: gecachte Antwort bzw. `{"live": false, "grund": "offline"}`; Schreibzugriffe POST offline → 503, nie ein fingiertes OK); nur bei http(s) aktiv, nicht bei file://. `data/sample-data.js` wird erst bei Bedarf nachgeladen (Fallback, wenn `data/project.json` nicht erreichbar ist) und liegt für den Offline-Fallback im Precache. Tastatur: **⌘/Strg+1–8** wechselt den Tab, **/** fokussiert die Suche des aktiven Tabs.

Das Dashboard ist bewusst **nicht** Teil des Workflow-Deployments (`grammatik-statt-stil-research` serviert den Agenten, nicht das Dashboard).
