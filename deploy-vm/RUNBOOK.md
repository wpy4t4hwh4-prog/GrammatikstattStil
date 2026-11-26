# RUNBOOK — Research Hub produktiv auf Always-Free-VM (0 € laufend)

Ziel: Dashboard produktiv unter `https://dashboard.<domain>` — iPhone als Home-Screen-App,
Mac als PWA/localhost — Daten liegen **nur** in der Mistral-Cloud, Seite bestmöglich geschützt.
Kosten: 0 €/Monat (abgesehen von optionaler eigener Domain ~10 €/Jahr; gratis: DuckDNS-Subdomain).

## 0. Architektur (Kurzfassung)

```
iPhone/Mac ──HTTPS──> [Edge-Auth: Cloudflare Access (empfohlen) | worker-gate.js | nginx basic auth]
                     │  nur 80/443 offen (ufw) — oder gar keine Ports bei Cloudflare Tunnel
                     ▼
        nginx :443 (certbot)  oder  cloudflared-Tunnel ──> 127.0.0.1:8765
                     ▼
        serve.py (systemd, fail-closed)
          ├─ Session-Auth: DASHBOARD_PASSWORD -> Cookie (HttpOnly, SameSite=Strict, Secure via X-Forwarded-Proto) + CSRF (X-Hub-CSRF) auf allen POSTs
          ├─ Host-Guard: DASHBOARD_ALLOWED_HOSTS (DNS-Rebinding)
          ├─ Login-Rate-Limit: >=5 Fehlversuche/5 min -> 900 s Lockout (429)
          └─ Mistral-Key NUR in /etc/research-hub.env (chmod 600) — serverseitige Calls in die Libraries/Workflows
                     ▼
        Mistral Cloud: Libraries (= Projekte, ACL viewer/editor) + Workflows (Agenten)
```

Datenmodell: **Library = Single Source of Truth.** Dashboard schreibt Notizen per Write-Through
(`POST /api/notes` -> `documents.upload` in die aktive Projekt-Library), liest live
(`/api/live`, `/api/ablage*`, `/api/apparat/qv` A1, `/api/wf/*`). Agenten-Worker schreiben in
dieselbe Ablage -> Dashboard pollt (30 s) -> Konvergenz auf allen Geräten.

## 1. OCI Always-Free VM anlegen (~15 Min)

1. Account: cloud.oracle.com -> "Always Free" signup (Kreditkarte zur Verifikation, wird nicht belastet).
2. Home-Region wählen, die Ampere A1 unterstützt (z. B. Europe Frankfurt / UK London — 3 ADs bevorzugt).
3. Compute -> Instances -> Create: Image **Ubuntu 24.04 (aarch64)**, Shape `VM.Standard.A1.Flex`.
   - **Limits seit 15.06.2026: 2 OCPU / 12 GB gesamt** (1.500 OCPU-h + 9.000 GB-h/Monat) — für serve.py (stdlib) mehr als genug.
   - Boot-Volume 50–200 GB (200 GB Always-Free gesamt), SSH-Key hinterlegen.
4. Networking -> Security List: Ingress **TCP 80 + 443** von 0.0.0.0/0 (bei Cloudflare Tunnel stattdessen nur 22 von deiner Admin-IP).
5. Notieren: Public IP (für DNS) oder reservierte IP.

## 2. DNS — gratis Subdomain (0 €) oder eigene Domain

- **Gratis:** DuckDNS (duckdns.org) -> `research-hub.duckdns.org`, A-Record auf die VM-IP (DDNS-Updater auf der VM: `cron */5` curl duckdns.org/update).
- **Oder:** eigene Domain (~10 €/Jahr) -> DNS-A-Record auf VM-IP.
- Notiere die Domain als `DOMAIN`.

## 3. Domain in Cloudflare (gratis) — empfohlen für Edge-Auth

1. cloudflare.com -> Add site -> `DOMAIN` (oder Subdomain) -> Free Plan.
2. Nameserver beim Registrar auf die Cloudflare-NS umstellen (warten, bis aktiv).
3. **Edge-Auth (primär):** Zero Trust (dash.cloudflare.com -> Zero Trust -> Access -> Applications -> Add):
   - Application: `dashboard.DOMAIN`, Policy: **Allow** `Emails` = deine Adresse (oder Everyone + OTP); Identity: Email OTP (gratis).
   - Ergebnis: Login per E-Mail-OTP (2FA-ähnlich) vor ALLEM. Workers/Workers-Requests zählen nicht gegen das Workers-Limit (100k/Tag Free reichen eh).
4. **Tunnel (optional, spart offene Ports):** Zero Trust -> Networks -> Tunnels -> Create `cloudflared`:
   `cloudflared tunnel --url http://127.0.0.1:8765` lokal testen; produktiv: Tunnel mit Public Hostname `dashboard.DOMAIN` -> Service `http://127.0.0.1:8765`. Dann ufw: nur 22 (Admin-IP).
   - Ohne Tunnel: Ports 80/443 offen + certbot (Schritt 5a), mit Tunnel: direkt HTTPS von Cloudflare (kein certbot nötig).

## 4. VM einrichten

```bash
ssh ubuntu@<vm-ip>
# Repo + Setup (als root):
sudo bash -c 'git clone https://github.com/wpy4t4hwh4-prog/GrammatikstattStil.git /tmp/gs && sudo bash /tmp/gs/deploy-vm/setup.sh dashboard.DOMAIN'
# oder manuell Schritt für Schritt, siehe setup.sh
```

`setup.sh` macht: Pakete (nginx, ufw, git, python3), Clone nach `/opt/research-hub`, Env-Datei
`/etc/research-hub.env` (chmod 600), systemd-Unit, nginx-Site, certbot, ufw 80/443, Keepalive-Cron.

**Danach `/etc/research-hub.env` befüllen (sudo nano):**
```
PROJECT_MISTRAL_API_KEY=sk-...        # La Plateforme (console.mistral.ai) -> API Keys
DASHBOARD_PASSWORD=<starkes passwort> # Login der Web-App
DASHBOARD_ALLOWED_HOSTS=dashboard.DOMAIN
#PROJECT_LIBRARY_ID=01a1b7a7-...      # Default-Projekt (sonst erste Library)
#APPARAT_LIBRARY_ID=01a1c18b-...      # Apparat-Library (Default: hartkodiert)
```
`chmod 600 /etc/research-hub.env`, dann `sudo systemctl restart research-hub`.

## 5. TLS

- **Mit Cloudflare:** HTTPS automatisch (Full strict empfohlen), kein certbot nötig.
- **Ohne Cloudflare:** `sudo certbot --nginx -d dashboard.DOMAIN` (setup.sh versucht es bereits).

## 6. Verifizieren

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://dashboard.DOMAIN/                 # 200 (nach Access-Login) oder 401/302
curl -s https://dashboard.DOMAIN/api/stats | head -c 120                          # {"fehler":"nicht angemeldet"...} = 401 -> korrekt
# lokal auf der VM:
curl -s http://127.0.0.1:8765/api/auth/me                                          # password_mode:true, authenticated:false
# Login-Test:
curl -si -X POST https://dashboard.DOMAIN/api/auth/login -H 'Content-Type: application/json' \
     -d '{"password":"..."}' | grep -i 'set-cookie'                              # hub_sid=...; HttpOnly; SameSite=Strict; Secure
# Smoke gegen Produktiv:
python3 tools/smoke_test.py --base https://dashboard.DOMAIN --password '...'
```

## 7. Geräte verbinden

- **iPhone:** Safari -> `https://dashboard.DOMAIN` -> Teilen -> "Zum Home-Bildschirm" -> App starten, Login (Cookie bleibt 12 h; Secure via HTTPS). Tabs inkl. Agent über Shortcuts/Deep-Links `?tab=agent`.
- **Mac zuhause:** lokal `cd dashboard && DASHBOARD_PASSWORD=... python3 serve.py` -> `http://127.0.0.1:8765` (localhost = Secure Context -> PWA installierbar in Chrome/Edge) — oder dieselbe produktive URL.
- **Projekt anlegen/wechseln:** Header-Picker "Projekt" -> Library-Liste live; "＋ Neu" legt Library + Seed (`00-projektstand.md`, `projekt.json` mit Agent-Deployment + Cron) an.

## 8. Betrieb & Sicherheit (Checkliste)

- [ ] `DASHBOARD_PASSWORD` stark (>= 20 Zeichen), nur in `/etc/research-hub.env` (chmod 600)
- [ ] `DASHBOARD_ALLOWED_HOSTS` = produktive Domain (Host-Guard gegen DNS-Rebinding)
- [ ] ufw: nur 80/443 (bzw. nur 22 bei Tunnel); serve.py läuft auf 127.0.0.1 (fail-closed ohne Token/Passwort bei non-loopback: exit 2)
- [ ] systemd-Härtung aktiv (ProtectSystem=strict, ReadWritePaths=data, NoNewPrivileges — siehe research-hub.service)
- [ ] Keepalive-Cron aktiv (`/etc/cron.d/research-hub-keepalive`) — OCI stoppt idle Always-Free-VMs
- [ ] `unattended-upgrades` aktiv: `sudo apt-get install -y unattended-upgrades`
- [ ] Access-Log optional: `DASHBOARD_TOKEN` nicht nötig; `--log` schreibt `data/hub.log` (token/password redacted) — `data/` ist gitignored
- [ ] Backups: keine nötig — SSOT ist die Mistral-Cloud; VM neu aufsetzbar via setup.sh (IaC)
- [ ] Rotation: bei Verdacht Passwort in `/etc/research-hub.env` ändern + `systemctl restart research-hub`; Mistral-Key bei Leak in console.mistral.ai rotieren; GitHub-PATs bei github.com/settings/tokens rotieren
- [ ] GitHub Pages bleibt Demo-Shell (Code + Beispieldaten, `/api/*` -> 404) — dort nie anmelden

## 9. Alternativen (falls Cloudflare nicht gewünscht)

- **worker-gate.js** (`cloudflare/worker-gate.js`): Passwort-Cookie-Gate als Worker-Route vor der Domain — Setup siehe `cloudflare/README.md` (bereits getestet, 15/15).
- **nginx basic auth:** `htpasswd -c /etc/nginx/.htpasswd philipp`, in der Site `auth_basic` einkommentieren (Snippet in setup.sh-Kommentar).
- Beide schützen die Seite; die **App-Auth (Session+CSRF) läuft immer zusätzlich** in serve.py.
