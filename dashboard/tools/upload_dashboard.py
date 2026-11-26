#!/usr/bin/env python3
"""Laedt das komplette Dashboard in die Mistral-Library "Hub-Uebergabe (Dashboard Handoff)",
damit Online-Agent-Sessions (Managed Agent grammatik-statt-stil-research) darauf zugreifen
und die Library durchsuchen koennen.

Aufruf:  tools/upload_dashboard.py            (Key aus Env oder macOS-Schluesselbund)
Ziel-Library per Env DASHBOARD_HUB_LIBRARY_ID aenderbar.

Idempotent: Dokumente mit dem Namenspraefix des heutigen Datums werden vor dem Upload geloescht.
Nicht hochgeladen: qv.db (Binaerdatei; stattdessen qv-export.json aus /api/qv/export),
snapshots/ (7 MB Historie), __pycache__, .gitignore.
"""
import asyncio
import json
import os
import re as _re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
HUB_LIBRARY_ID = os.environ.get("DASHBOARD_HUB_LIBRARY_ID", "01a1e97d-793f-77fc-aa91-d8baf800d561")
DATE = time.strftime("%Y-%m-%d")
PREFIX = "dashboard-%s-" % DATE

FILES = [
    ("README.md", "readme.md"),
    ("serve.py", "serve.py"),
    ("index.html", "index.html"),
    ("sw.js", "sw.js"),
    ("manifest.webmanifest", "manifest.webmanifest"),
    ("tools/start.sh", "start.sh"),
    ("tools/import_apparat.py", "tools-import_apparat.py"),
    ("tools/smoke_test.py", "tools-smoke_test.py"),
    ("tools/make_icons.py", "tools-make_icons.py"),
    ("tools/upload_dashboard.py", "tools-upload_dashboard.py"),
    ("data/project.json", "data-project.json"),
    ("data/templates.json", "data-templates.json"),
    ("data/outbox.jsonl", "data-outbox.jsonl"),
    ("data/agent-conv.json", "data-agent-conv.json"),
    ("data/sample-data.js", "data-sample-data.js"),
    ("icons/icon-192.png", "icon-192.png"),
    ("icons/icon-512.png", "icon-512.png"),
    ("icons/icon-512-maskable.png", "icon-512-maskable.png"),
    ("icons/icon-180.png", "icon-180.png"),
]


def _key():
    k = os.environ.get("PROJECT_MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY")
    if k:
        return k
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", "mistral-api-key",
                            "-a", os.environ.get("USER", "philipp"), "-w"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    sys.exit("kein API-Key (Env MISTRAL_API_KEY oder Schluesselbund mistral-api-key)")


def _qv_export():
    """Vollstaendiger QV-Export inkl. DB-Zeilen + Aenderungslog vom lokalen Server."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/qv/export", timeout=15) as r:
            return r.read()
    except Exception:
        # Server nicht lokal erreichbar -> aus project.json + qv.db selbst bauen
        import sqlite3
        d = json.loads((DATA / "project.json").read_text(encoding="utf-8"))
        con = sqlite3.connect(DATA / "qv.db")
        con.row_factory = sqlite3.Row
        d["verzeichnis_db"] = [dict(r) for r in con.execute("SELECT * FROM pos ORDER BY id")]
        d["aenderungen"] = [dict(r) for r in con.execute(
            "SELECT * FROM aenderungen ORDER BY ts DESC LIMIT 200")]
        con.close()
        return json.dumps(d, ensure_ascii=False, indent=2).encode("utf-8")


def _index_doc():
    conv = {}
    try:
        conv = json.loads((DATA / "agent-conv.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        meta = json.loads((DATA / "project.json").read_text(encoding="utf-8"))["meta"]
        stand = meta.get("stand", "?")
    except Exception:
        stand = "?"
    return f"""# Dashboard Uebergabe — komplettes Research-Dashboard (Stand {DATE})

 Zweck: Online-Sessions des Managed Agents **grammatik-statt-stil-research** koennen diese
 Library durchsuchen und so vollstaendigen Zugriff auf Code, Daten und Doku des Dashboards haben.

## Was das Dashboard ist
 Lokaler Research-Hub fuer das TU-Wien-Projekt „{stand}“.
 Start: `cd dashboard && ./tools/start.sh` -> http://127.0.0.1:8765/ (Default nur Loopback;
 optional `--host 0.0.0.0 --token <t>`). Nur Python-stdlib serverseitig; API-Key kommt aus
 Env/Schluesselbund, nie aus dem Repo.

## Datei-Map (alle mit Praefix `{PREFIX}` in dieser Library)
- `readme.md` — Doku: Start, API-UEbersicht, Tabs, Import, PWA
- `serve.py` — kompletter Server (HTTP/1.1, Whitelist fuer statische Dateien, SQLite+FTS5 QV,
  Agent-v2-Control-Plane-Client, Live-Library-Zugriffe, TTL-Cache)
- `index.html` — Frontend-Shell (sichtbarer Text; script/style werden vom Library-Extractor gestrippt)
- `index-inline.js` / `index-inline.css` — **kompletter Inline-Quelltext** des Frontends (Tabs, Charts, Komm-Tab)
- `sw.js` + `manifest.webmanifest` + `icon-*.png` — PWA (network-first /api + /data, POST offline -> 503)
- `start.sh`, `tools-*.py` — Start + Import/Smoke/Icons/Upload
- `data-project.json` — Projektdaten (meta, kstand, verzeichnis 393 Pos., glossar, pruefaufgaben, historie)
- `data-qv-export.json` — generierter Export: project.json + pos-Tabelle (qv.db) + Aenderungslog
- `data-templates.json` — Text-Vorlagen (Render-API)
- `data-outbox.jsonl` — lokaler Postausgang/Chat-Log des Dashboards
- `data-agent-conv.json` — aktuelle Agent-Session: `{json.dumps(conv, ensure_ascii=False)}`
- `data-sample-data.js` — Fallback-Daten fuer file://-Modus

## Agent-Zugriff
- Agent: `grammatik-statt-stil-research` (v2 Control Plane, Sessions unter /v2/agents/sessions)
- aktuelle Session-ID: `{conv.get('session_id', '?')}` (Verlauf via Dashboard-Komm-Tab oder /api/agent/history)
- Die Ablage des Agents liegt in Library "Grammatik statt Stil – Research-Ablage (Agent)",
  der Apparat (Quellenverzeichnis/Volltext-Inventar) in "Apparat-Bibliothek".

## API-Kurzuebersicht (serve.py)
GET /api/stats /api/meta /api/verzeichnis /api/glossar /api/historie /api/messages /api/live
/api/ablage /api/ablage/doc /api/qv (q/k/rel/limit/offset, FTS5) /api/qv/aenderungen
/api/qv/export (?format=ris|bib) /api/qv/snapshots /api/qv/diff /api/dupes /api/pruef
/api/coverage /api/quellen /api/templates /api/libraries /api/library/docs /api/library/doc
/api/agent/history /api/agent/sessions /api/agent/pending
POST /api/message /api/qv/hebung /api/qv/edit /api/pruef /api/import /api/render /api/diff
/api/agent/send /api/agent/stop /api/agent/archive /api/agent/reset /api/outbox/clear

Hinweis: Aenderungen am Dashboard bitte als neue Docs mit neuem Datum ablegen (Praefix
`dashboard-<YYYY-MM-DD>-`), alte Uebergaenge nicht loeschen.
""".encode("utf-8")


async def main_async():
    from mistralai.client.models import File
    from mistralai.workflows.client import get_mistral_client
    client = get_mistral_client(api_key=_key())

    # alte Uebergaben mit heutigem Praefix entfernen (idempotent)
    listing = await client.beta.libraries.documents.list_async(library_id=HUB_LIBRARY_ID, page_size=100)
    for d in (listing.data or []):
        if (d.name or "").startswith(PREFIX):
            try:
                await client.beta.libraries.documents.delete_async(library_id=HUB_LIBRARY_ID, document_id=d.id)
                print("entfernt:", d.name)
            except Exception as e:
                print("loeschen fehlgeschlagen:", d.name, e)

    payloads = []
    for rel, name in FILES:
        p = BASE / rel
        if p.is_file():
            payloads.append((PREFIX + name, p.read_bytes()))
        else:
            print("UEBERSPRUNGEN (fehlt):", rel)
    payloads.append((PREFIX + "qv-export.json", _qv_export()))
    payloads.append((PREFIX + "index.md", _index_doc()))
    # Inline-JS/-CSS separat als .js/.css: Der Library-Extractor liefert bei .html/.md nur
    # sichtbaren Text (script/style werden gestrippt) — .js/.css kommen komplett durch.
    html_src = (BASE / "index.html").read_text(encoding="utf-8")
    js = _re.search(r"<script>\n(.*)</script>", html_src, _re.DOTALL)
    css = _re.search(r"<style>\n(.*)</style>", html_src, _re.DOTALL)
    if js:
        payloads.append((PREFIX + "index-inline.js", js.group(1).encode("utf-8")))
    if css:
        payloads.append((PREFIX + "index-inline.css", css.group(1).encode("utf-8")))

    ok, fail = 0, 0
    for name, content in payloads:
        try:
            doc = await client.beta.libraries.documents.upload_async(
                library_id=HUB_LIBRARY_ID,
                file=File(fileName=name, content=content),
            )
            ok += 1
            print(f"hochgeladen: {name}  ({len(content)} B, {doc.processing_status}, {doc.id[:13]})")
        except Exception as e:
            fail += 1
            print(f"FEHLER: {name}: {str(e)[:200]}")
    print(f"\n== {ok} hochgeladen, {fail} Fehler — Library {HUB_LIBRARY_ID}")


if __name__ == "__main__":
    asyncio.run(main_async())
