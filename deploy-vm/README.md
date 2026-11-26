# Live-Dashboard ohne Daten bei GitHub (Architektur A)

Ziel: die Dashboard-Daten (QV, Ablage, Libraries) liegen **nicht** im Git-Repo/GitHub,
sondern werden nach Anmeldung live per API aus den Mistral-Libraries geholt.

## Architektur

```
Browser ──HTTPS──> nginx (:443) ──> serve.py (127.0.0.1:8765, systemd)
                                          │  PROJECT_MISTRAL_API_KEY nur in /etc/research-hub.env
                                          ▼
                                    Mistral Libraries API (Ablage, Apparat, ...)
```

- GitHub/Pages enthält nur statischen Code + `sample-data.js` (Fallback). `dashboard/data/project.json`
  (echter Snapshot) ist gitignored und wird nicht gepusht.
- Schutz der Seite (Edge): **Cloudflare Access** (E-Mail-OTP, gratis ≤ 50 Nutzer) empfohlen —
  Alternativen: Cloudflare-Worker-Gate (`cloudflare/worker-gate.js`) oder nginx basic auth.
  **Zusätzlich immer App-seitig in serve.py:** Session-Auth (`DASHBOARD_PASSWORD` -> Cookie
  HttpOnly/SameSite=Strict/Secure + CSRF auf POSTs, Rate-Limit+Lockout, Host-Guard via
  `DASHBOARD_ALLOWED_HOSTS`, fail-closed bei non-loopback ohne Token/Passwort).
- Komplette Schritt-für-Schritt-Anleitung inkl. OCI Always-Free (2 OCPU/12 GB seit 06/2026),
  DuckDNS, Cloudflare-Tunnel, Keepalive: **`deploy-vm/RUNBOOK.md`**.
- Projekte: Library = Projekt; Header-Picker wählt die aktive Library serverseitig pro Session
  (`/api/projects`, `/api/projects/select|create`); Agent-Tab (`/api/wf/*`, `/api/apparat/qv` A1,
  `/api/notes` Write-Through) — Details in `dashboard/README.md`.

## Host (gratis, immer an)

Oracle Cloud **Always-Free ARM**: seit 15.06.2026 **2 OCPU / 12 GB gesamt** (1.500 OCPU-h + 9.000 GB-h/Monat)
— für serve.py (stdlib) völlig ausreichend. 200 GB Block Storage + 10 TB Egress inklusive.
Setup: `sudo bash deploy-vm/setup.sh dashboard.deinedomain.at`
(DNS-A-Record auf VM-IP, Ports 80/443 offen — oder Cloudflare Tunnel ohne offene Ports;
Key + Passwort in `/etc/research-hub.env` eintragen, siehe RUNBOOK.md).

## Hinweis zur History

Ein bereits gepushter Snapshot (`data/project.json` auf Branch `vibe/forschungsdashboard-18c80e`)
bleibt in der public Repo-History lesbar. Wirklich "gar nicht bei GitHub" erfordert privates Repo
(kostet) oder dass solche Daten nie gepusht werden.
