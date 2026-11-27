# Research-Dashboard als Mistral Studio App (`research-hub`)

Das Research-Dashboard (`dashboard/`, PWA + `serve.py` mit allen `/api/*`-Endpunkten) laesst sich als
**Mistral App in Mistral Studio** betreiben. Studio uebernimmt dann **Hosting, Authentifizierung und
Zugriffskontrolle** (Gateway vor dem Modul) - das ersetzt das bisherige 0-EUR-Setup mit eigener VM,
Cloudflare Access/Tunnel und nginx/certbot (`deploy-vm/`, `cloudflare/`).

## Architektur

```
Browser ──> Studio-Gateway (Sign-in, Access Control) ──> Modul "api" (0.0.0.0:8080)
                                                        └─> dashboard/serve.py
                                                            ├─ statisch: index.html, sw.js, icons/, data/
                                                            └─ /api/*: Stats, QV (SQLite), Ablage/Bibliothek,
                                                               Agent-Tab (Managed Agent), Auth-Endpunkte
```

- Ein Modul genuegt: `serve.py` serviert Frontend **und** API auf einem Port; Route `/` -> Modul `api`
  (`mistral.json`).
- `apps/api/main.py` startet `serve.py` mit `--host 0.0.0.0 --port $PORT` und setzt
  `DASHBOARD_TRUST_GATEWAY_AUTH=1`. Dadurch verzichtet `serve.py` auf die fail-closed-Pruefung fuer
  exponierte Hosts - **nur hinter dem authentifizierten Studio-Gateway zulaessig** (lokal/ohne
  Gateway bleibt fail-closed aktiv, Default-Verhalten unveraendert).
- `MISTRAL_API_KEY` kommt als **Secret** in Studio (Secrets-Tab der App, Modul `api`) - die CLI laedt
  `.env` nie hoch. Damit werden die Live-Endpunkte aktiv (Ablage, Bibliothek, Agent-Tab via
  `grammatik-statt-stil-research`).
- **Kein zusaetzliches Dashboard-Passwort in der App**: `serve.py` ignoriert `DASHBOARD_PASSWORD` im App-Modus (`DASHBOARD_TRUST_GATEWAY_AUTH=1`) — Auth liegt am Gateway. Ein versehentlich gesetztes `DASHBOARD_PASSWORD`-Secret (App-Secrets oder Secrets Manager) hat daher keine Wirkung; bitte trotzdem dort entfernen.

## Voraussetzung

- Organization-Plan mit **Apps** und **Pay-as-you-go** (Free sowie Pro/Team ohne PAYG duerfen keine Apps
  anlegen), oder Enterprise. Siehe [Plan limits](https://docs.mistral.ai/studio/apps/overview).
- Mistral CLI, GitHub-Verbindung (Mistral GitHub App auf diesem Repo), sauberer Working Tree.

## Setup

```bash
curl -fsSL https://mistral.ai/cli/install.sh | bash
mistral login
cd <repo-root>       # App-Root ist das Repo-Root: das kanonische Manifest liegt in mistral.json (Root)
# MISTRAL_API_KEY in .env eintragen (gitignored) fuer lokalen Betrieb
mistral dev          # lokaler Stack inkl. Gateway, z. B. http://research-hub.apps.localhost:8080
```

Das Manifest `mistral.json` am **Repo-Root** folgt dem kanonischen Schema (schemaVersion 2, kind
`app`, `modules` als Array - validiert mit `mistral apps modules`); Modul-Quelle
(`studio-app/apps/api/`) und Dockerfile bleiben als Drop-in erhalten. Build-Kontext des Moduls ist
das Repo-Root (`build.context: "."`), damit das Dockerfile `dashboard/` kopieren kann.

## Deploy

```bash
git add -A && git commit -m "feat(studio-app): Research-Dashboard als Studio-App" && git push
mistral deploy       # aus dem Repo-Root: baut den gepushten Commit, legt Module an, druckt die App-URL
# Alternative ohne Git/Push (experimental): mistral deploy --from-disk  (uploaded das App-Verzeichnis)
```

- Erster Deploy schreibt das Deployment-Binding in `mistral.json` (mit committen/pushen).
- Secrets in Studio setzen: `MISTRAL_API_KEY` (Modul `api`), optional `DASHBOARD_PASSWORD`,
  `DASHBOARD_ALLOWED_HOSTS` (oeffentlicher Host der App, falls der Host-Guard greift).
- App veroeffentlichen: `mistral apps publish` (Publish to Vibe) - die URL funktioniert auch ohne Publish.

## Hinweise / Grenzen

- **Persistenz:** `serve.py` schreibt `data/qv.db`, `outbox.jsonl`, Snapshots ins Container-Dateisystem
  (ephemer in Mistral Cloud). Seed-Daten (`data/project.json`) sind im Repo committed und werden beim
  Start geseedet. K-Hebungen/Notizen ueberleben ein Redeploy nicht - als naechster Schritt laesst sich die
  QV-SQLite auf die **Postgres-Capability** der App migrieren (`mistral apps capability add postgres`).
- **PWA/iPhone:** Manifest + Service Worker werden mit ausgeliefert; "Zum Home-Bildschirm" funktioniert
  auf der App-URL (HTTPS). Der reine Offline-/`file://`-Modus ist in der gehosteten App nicht relevant.
- **Sicherheit:** Gateway-Auth ist der aeussere Schutz; `serve.py` haelt seine Härtung (CSP,
  nosniff, Cookie/CSRF bei Passwort-Modus, Whitelist statischer Endungen). Ohne `DASHBOARD_PASSWORD`
  schuetzt allein das Gateway - Modul nie oeffentlich ohne Gateway exponieren
  (`DASHBOARD_TRUST_GATEWAY_AUTH` nur in der Studio-App setzen).
- Lokaler Betrieb ohne Studio bleibt unveraendert: `cd dashboard && python3 serve.py` (Loopback-only,
  fail-closed). Smoke-Test: `python3 dashboard/tools/smoke_test.py --base http://127.0.0.1:8765`.

## Dateien

- `mistral.json` - App-Manifest (Module, Routes)
- `apps/api/main.py` - Modul-Runner: startet `dashboard/serve.py` auf `0.0.0.0:$PORT`
- `apps/api/Dockerfile` - Image (Build-Kontext: Repo-Root)
- `apps/api/requirements.txt` - `mistralai-agents[sessions-client]==1.1.0` (gleicher Pin wie `forschungsagent/`)
- `.env.example` - lokale Env fuer `mistral dev` (nie committen)
