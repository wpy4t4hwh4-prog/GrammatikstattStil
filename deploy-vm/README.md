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
- Schutz der Seite: Cloudflare-Worker-Gate (`cloudflare/worker-gate.js`) vor die Domain legen
  ODER nginx Basic-Auth (htpasswd). Beides gratis.
- `serve.py` hat CORS-Header (`CORS_ORIGIN` in Env, default `*`) + `do_OPTIONS`, damit optional auch
  eine statische Shell von GitHub Pages die Live-API auf der VM rufen kann (`window.API_BASE` in index.html).

## Host (gratis, immer an)

Oracle Cloud **Always-Free ARM**: 2 VMs (je 1 OCPU/6 GB oder 4 OCPU/24 GB gesamt) dauerhaft gratis.
Alternativ jeder Always-Free-VPS. Setup: `sudo bash deploy-vm/setup.sh dashboard.deinedomain.at`
(DNS-A-Record auf VM-IP, Ports 80/443 offen; Key in `/etc/research-hub.env` eintragen).

## Hinweis zur History

Ein bereits gepushter Snapshot (`data/project.json` auf Branch `vibe/forschungsdashboard-18c80e`)
bleibt in der public Repo-History lesbar. Wirklich "gar nicht bei GitHub" erfordert privates Repo
(kostet) oder dass solche Daten nie gepusht werden.
