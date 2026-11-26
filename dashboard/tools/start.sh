#!/bin/sh
# Startet das Research-Dashboard mit Live-Modus.
# API-Key kommt aus dem macOS-Schlüsselbund (Service "mistral-api-key", Account $USER)
# oder aus der Umgebung (MISTRAL_API_KEY / PROJECT_MISTRAL_API_KEY).
# Ohne Key startet das Dashboard im rein lokalen Modus (Badge "lokal").
#
# Aufruf:  tools/start.sh [--port 9000] [--host 0.0.0.0]
# Key im Schlüsselbund ablegen (einmalig):
#   security add-generic-password -U -a "$USER" -s mistral-api-key -l "Mistral API Key (Vibe)" -w "<key>"

set -e
cd "$(dirname "$0")/.."

VENV_PY="/Users/philipp/GrammatikstattStil/forschungsagent/.venv/bin/python"
PY="${VENV_PY}"
if [ ! -x "$PY" ]; then
    PY="python3"  # Fallback: lokaler Modus (ohne mistralai kein Live-Zugriff)
fi

if [ -z "$MISTRAL_API_KEY" ] && [ -z "$PROJECT_MISTRAL_API_KEY" ]; then
    KEY="$(security find-generic-password -s mistral-api-key -a "${USER:-philipp}" -w 2>/dev/null || true)"
    if [ -n "$KEY" ]; then
        export MISTRAL_API_KEY="$KEY"
        echo "API-Key aus Schlüsselbund geladen (Live-Modus an)."
    else
        echo "Kein API-Key gefunden — Dashboard startet im lokalen Modus."
    fi
fi

exec "$PY" serve.py --port "${PORT:-8765}" "$@"
