#!/usr/bin/env python3
"""Mistral-Studio-App "research-hub" - Modul "api": startet das Research-Dashboard (dashboard/serve.py).

Studio stellt Hosting, Authentifizierung und Zugriffskontrolle ueber das Gateway vor dieses Modul.
Der Runner bindet daher 0.0.0.0:$PORT und setzt DASHBOARD_TRUST_GATEWAY_AUTH=1, damit serve.py die
fail-closed-Pruefung fuer exponierte Hosts aussetzt. Ohne Gateway-Auth niemals so betreiben!

Env:
  PORT                    Listener-Port (Default 8080)
  DASHBOARD_DIR           Pfad zum dashboard/-Verzeichnis (Default <repo>/dashboard; im Container /app/dashboard)
  DASHBOARD_PASSWORD      wirkungslos im App-Modus: serve.py ignoriert es bei DASHBOARD_TRUST_GATEWAY_AUTH=1 (Auth liegt am Gateway; kein zweites Passwort im App-Pfad)
  DASHBOARD_TOKEN         optional: zusaetzlicher Token (Back-Compat)
  DASHBOARD_ALLOWED_HOSTS optional: zusaetzliche Host-Header (DNS-Rebinding-Guard)
  MISTRAL_API_KEY         Secret in Studio: Live-Endpunkte (Ablage, Bibliothek, Agent-Tab)
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# DASHBOARD_DIR lazy aufloesen: im Container liegt main.py unter /app/main.py (Dockerfile setzt
# DASHBOARD_DIR=/app/dashboard als ENV), im Repo unter studio-app/apps/api/main.py (parents[3] =
# Repo-Root). Die Default-Auswertung darf nicht eager passieren (IndexError bei /app/main.py).
_env_dir = os.environ.get("DASHBOARD_DIR")
if _env_dir:
    DASHBOARD_DIR = Path(_env_dir).resolve()
elif len(HERE.parents) > 3:
    DASHBOARD_DIR = (HERE.parents[3] / "dashboard").resolve()
else:
    DASHBOARD_DIR = (HERE.parent / "dashboard").resolve()
PORT = os.environ.get("PORT", "8080")


def main():
    serve_py = DASHBOARD_DIR / "serve.py"
    if not serve_py.is_file():
        print("FEHLER: serve.py nicht gefunden unter %s (DASHBOARD_DIR setzen)" % serve_py, file=sys.stderr)
        sys.exit(2)
    env = dict(os.environ)
    env["DASHBOARD_TRUST_GATEWAY_AUTH"] = "1"
    argv = [sys.executable, str(serve_py), "--host", "0.0.0.0", "--port", PORT]
    print("research-hub (Studio-App): starte %s auf 0.0.0.0:%s (Auth am Studio-Gateway)" % (serve_py, PORT), flush=True)
    os.execve(sys.executable, argv, env)


if __name__ == "__main__":
    main()
