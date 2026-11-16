#!/usr/bin/env python3
"""Lokaler Server fuer das Research-Dashboard (nur stdlib, nur Loopback).

Start:  python3 serve.py [--port 8765]
        -> http://127.0.0.1:8765/

APIs:
  GET  /api/stats       aggregierte Kennzahlen aus data/project.json
  GET  /api/verzeichnis Verzeichniszeilen
  GET  /api/glossar     Glossar
  GET  /api/messages    lokaler Postausgang (data/outbox.jsonl)
  POST /api/message     {"text": "..."} -> an outbox.jsonl anhaengen
  GET  /api/live        optional live: letzte Doks der Research-Ablage
                        (nur wenn mistralai importierbar UND MISTRAL_API_KEY/
                        PROJECT_MISTRAL_API_KEY in der Umgebung gesetzt)

Kein Schreibzugriff nach außen; der Server bindet nur an 127.0.0.1.
"""
import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
NOTES_LIBRARY_ID = "01a1b7a7-d3b3-7603-9601-7efb317d38ee"  # Research-Ablage (Agent)
APPARAT_LIBRARY_ID = "01a1c18b-fe93-75a4-8c2b-871c9f112cd9"  # Apparat-Bibliothek

import re as _re


def parse_qv_standzeile(text):
    """Parst die Standzeile des Apparat_Quellenverzeichnis.md (K-Stand, Positionen, Quote)."""
    out = {"stand": None, "positionen": None, "k": None, "vermerke": None, "erschliessung": None}
    m = _re.search(r"Stand:\s*([^\n]+)", text)
    if m:
        out["stand"] = m.group(1).strip()[:200]
    m = _re.search(r"(\d+)\s*Verzeichnispositionen", text)
    if m:
        out["positionen"] = int(m.group(1))
    m = _re.search(r"K1\s+(\d+),\s*K2\s+(\d+),\s*K3\s+(\d+),\s*K4\s+(\d+),\s*K5\s+(\d+)", text)
    if m:
        out["k"] = {"K1": int(m.group(1)), "K2": int(m.group(2)), "K3": int(m.group(3)), "K4": int(m.group(4)), "K5": int(m.group(5))}
    m = _re.search(r"Vermerke\s+(\d+)", text)
    if m:
        out["vermerke"] = int(m.group(1))
    m = _re.search(r"Erschlie\S*ungsquote.{0,40}?(\d+)\s*/\s*(\d+)", text, _re.DOTALL)
    if m:
        out["erschliessung"] = {"zaehler": m.group(1) + "/" + m.group(2)}
    return out


def load_project():
    with open(DATA / "project.json", encoding="utf-8") as f:
        return json.load(f)


def load_outbox():
    p = DATA / "outbox.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def live_info():
    """Optional live: neueste Ablage-Doks + QV-Standzeile aus dem Apparat (Key nur aus Env)."""
    key = os.environ.get("PROJECT_MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY")
    if not key:
        return {"live": False, "grund": "kein API-Key in Umgebung (MISTRAL_API_KEY/PROJECT_MISTRAL_API_KEY)"}
    try:
        from mistralai.workflows.client import get_mistral_client  # optional

        client = get_mistral_client(api_key=key)

        async def _go():
            listing = await client.beta.libraries.documents.list_async(library_id=NOTES_LIBRARY_ID, page_size=8)
            ablage = [{"name": d.name, "status": getattr(d, "processing_status", None)} for d in (listing.data or [])]
            qv = None
            try:
                ql = await client.beta.libraries.documents.list_async(library_id=APPARAT_LIBRARY_ID, search="Quellenverzeichnis", page_size=5)
                qvdoc = next((d for d in (ql.data or []) if "Quellenverzeichnis" in (d.name or "")), None)
                if qvdoc is not None:
                    content = await client.beta.libraries.documents.text_content_async(library_id=APPARAT_LIBRARY_ID, document_id=qvdoc.id)
                    text = getattr(content, "text", None) or str(content)
                    qv = parse_qv_standzeile(text[:6000])
            except Exception:
                qv = None
            return ablage, qv

        import asyncio

        docs, qv = asyncio.run(_go())
        return {"live": True, "anzahl": len(docs), "zeitstempel": time.strftime("%H:%M:%S"), "doks": docs, "qv": qv}
    except Exception as e:  # kein SDK / kein Netz / kein Key -> lokal bleiben
        return {"live": False, "grund": f"{type(e).__name__}: {e}"[:200]}


class Handler(BaseHTTPRequestHandler):
    server_version = "ResearchDashboard/1.0"

    def log_message(self, fmt, *args):  # leises Logging
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        try:
            body = path.read_bytes()
        except OSError:
            self._json({"fehler": "not found"}, 404)
            return
        ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".json": "application/json; charset=utf-8", ".md": "text/markdown; charset=utf-8"}.get(path.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            return self._file(BASE / "index.html")
        if self.path.startswith("/data/"):
            rel = self.path[len("/data/"):]
            if ".." in rel:
                return self._json({"fehler": "bad path"}, 400)
            return self._file(DATA / rel)
        if self.path == "/api/stats":
            d = load_project()
            k = d["kstand"]["K"]
            n = d["kstand"]["positionen"]
            g = d["kstand"]["gruppen_enden"]
            return self._json({
                "meta": d["meta"], "kstand": d["kstand"],
                "vt_quote": round((k["K1"] + k["K2"]) / n * 100, 1),
                "gruppen": {"enden": g, "avg": round(n / len(g), 1)},
            })
        if self.path == "/api/verzeichnis":
            return self._json(load_project()["verzeichnis"])
        if self.path == "/api/glossar":
            return self._json(load_project()["glossar"])
        if self.path == "/api/messages":
            return self._json(load_outbox())
        if self.path == "/api/live":
            return self._json(live_info())
        return self._json({"fehler": "not found"}, 404)

    def do_POST(self):
        if self.path == "/api/message":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                text = str(payload.get("text", "")).strip()
                if not text:
                    return self._json({"fehler": "text fehlt"}, 400)
                entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "text": text}
                with open(DATA / "outbox.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                return self._json(entry)
            except Exception as e:
                return self._json({"fehler": str(e)[:200]}, 400)
        return self._json({"fehler": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Dashboard: http://{args.host}:{args.port}/  (nur Loopback, Ctrl+C beendet)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
