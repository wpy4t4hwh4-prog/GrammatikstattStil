#!/usr/bin/env python3
"""Lokaler Server fuer Research-Dashboard / Hub (nur stdlib, Default nur Loopback).

Start:  python3 serve.py [--port 8765] [--host 127.0.0.1]
        -> http://127.0.0.1:8765/   (Default nur Loopback; --host 0.0.0.0 nur im vertrauenswuerdigen LAN)

APIs:
  GET  /api/stats            aggregierte Kennzahlen aus data/project.json
  GET  /api/verzeichnis     Verzeichniszeilen (Fallback, wenn kein /api/qv)
  GET  /api/glossar          Glossar
  GET  /api/messages         lokaler Postausgang (data/outbox.jsonl)
  POST /api/message          {"text": "..."} -> an outbox.jsonl anhaengen
  GET  /api/live             optional live: neueste Ablage-Doks + QV-Standzeile aus dem Apparat
  GET  /api/ablage?q=        optional live: Suche in der Research-Ablage (Library)
  GET  /api/ablage/doc?id=   optional live: Text-Ausschnitt (4000 Zeichen) eines Ablage-Dokuments
  GET  /api/qv?q=&k=&rel=&limit=   QV-Suche (SQLite, FTS5 falls verfuegbar, sonst LIKE)
  POST /api/qv/hebung        {"id","neu_k"(K1|K2),"beleg","datum"} -> K-Hebung mit Beleg-Pflicht + Log
  GET  /api/qv/aenderungen   Aenderungslog (K-Hebungen)
  GET  /api/qv/export        QV als JSON (Download)
  GET  /api/quellen?q=       Quellendatenbank: gruppiert nach Quelle (Pos., K-Verteilung, IDs)
  GET  /api/libraries        optional live: alle Libraries (ID, Name, Dok-Zahl)
  GET  /api/library/docs?lib=&q=   optional live: Dokumente einer Library
  GET  /api/library/doc?lib=&id=   optional live: Text-Ausschnitt (4000 Zeichen) aus beliebiger Library
  GET  /api/templates        Text-Vorlagen (data/templates.json)
  POST /api/render           {"template","context"} -> gerenderter Text ({{key}}-Ersetzung)
  POST /api/diff             {"a","b"} -> zeilenweiser Diff als JSON

Kein Schreibzugriff nach außen; Default bindet der Server nur an 127.0.0.1. Statisch serviert: /, index.html, sw.js, manifest.webmanifest, icons/, data/ (PWA: Manifest + Service Worker + Icons).
"""
import argparse
import datetime
import json
import os
import re as _re
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DB = DATA / "qv.db"
NOTES_LIBRARY_ID = "01a1b7a7-d3b3-7603-9601-7efb317d38ee"  # Research-Ablage (Agent)
APPARAT_LIBRARY_ID = "01a1c18b-fe93-75a4-8c2b-871c9f112cd9"  # Apparat-Bibliothek


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


def save_project(d):
    with open(DATA / "project.json", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def _qint(qs, name, default, lo=1, hi=1000):
    """Query-Param robust als int (Default bei Fehler), geclampt auf [lo, hi]."""
    try:
        return max(lo, min(hi, int(qs.get(name, [str(default)])[0] or default)))
    except (ValueError, TypeError):
        return default


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


# ---------- QV-SQLite (FTS5 wenn verfuegbar) ----------

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    fresh = not DB.exists()
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS pos(
      id TEXT PRIMARY KEY, titel TEXT, quelle TEXT, k TEXT, rel TEXT, vermerk TEXT, updated TEXT);
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS aenderungen(
      ts TEXT, pos_id TEXT, alt_k TEXT, neu_k TEXT, beleg TEXT, datum TEXT);
    """)
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS pos_fts USING fts5(id UNINDEXED, titel, quelle, vermerk, k UNINDEXED, rel UNINDEXED)")
        fts = True
    except sqlite3.OperationalError:
        fts = False
    count = con.execute("SELECT COUNT(*) c FROM pos").fetchone()["c"]
    if fresh or count == 0:
        d = load_project()
        for r in d["verzeichnis"]:
            con.execute("INSERT OR REPLACE INTO pos VALUES (?,?,?,?,?,?,?)",
                        (r["id"], r["titel"], r["quelle"], r["k"], r.get("rel", ""), r.get("vermerk", ""), time.strftime("%Y-%m-%d")))
            if fts:
                con.execute("INSERT INTO pos_fts(id, titel, quelle, vermerk, k, rel) VALUES (?,?,?,?,?,?)",
                            (r["id"], r["titel"], r["quelle"], r.get("vermerk", ""), r["k"], r.get("rel", "")))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('kstand', ?)", (json.dumps(d["kstand"], ensure_ascii=False),))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('meta', ?)", (json.dumps(d["meta"], ensure_ascii=False),))
        con.commit()
    con.close()
    return fts


def _fts_query(q):
    """FTS5-MATCH-Ausdruck: Tokens als Praefix-Treffer (\"paris\"* matcht auch \"Pariser\")."""
    toks = [t for t in _re.split(r"[^\w\-/]+", q, flags=_re.UNICODE) if t]
    return " ".join('"%s"*' % t.replace('"', '""') for t in toks)


def qv_search(q, k, rel, limit=200):
    con = db()
    k, rel = (k or ""), (rel or "")
    try:
        if q and _fts_query(q):
            sql = ("SELECT p.* FROM pos_fts f JOIN pos p ON p.id = f.id "
                   "WHERE pos_fts MATCH ? AND (? = '' OR p.k = ?) AND (? = '' OR p.rel = ?) "
                   "ORDER BY rank LIMIT ?")
            rows = con.execute(sql, (_fts_query(q), k, k, rel, rel, limit)).fetchall()
        else:
            like = "%" + (q or "") + "%"
            rows = con.execute("SELECT * FROM pos WHERE (titel LIKE ? OR quelle LIKE ? OR vermerk LIKE ? OR id LIKE ?) "
                               "AND (? = '' OR k = ?) AND (? = '' OR rel = ?) ORDER BY id LIMIT ?",
                               (like, like, like, like, k, k, rel, rel, limit)).fetchall()
    except sqlite3.OperationalError:
        like = "%" + (q or "") + "%"
        rows = con.execute("SELECT * FROM pos WHERE (titel LIKE ? OR quelle LIKE ? OR vermerk LIKE ? OR id LIKE ?) "
                           "AND (? = '' OR k = ?) AND (? = '' OR rel = ?) ORDER BY id LIMIT ?",
                           (like, like, like, like, k, k, rel, rel, limit)).fetchall()
    out = [dict(r) for r in rows]
    total = con.execute("SELECT COUNT(*) c FROM pos").fetchone()["c"]
    con.close()
    return {"rows": out, "total": total}


def qv_heben(payload):
    """K-Hebung nur mit Beleg; loggt in aenderungen und schreibt project.json zurueck."""
    pid = str(payload.get("id", "")).strip()
    neu = str(payload.get("neu_k", "")).strip().upper()
    beleg = str(payload.get("beleg", "")).strip()
    datum = str(payload.get("datum", "")).strip() or time.strftime("%Y-%m-%d")
    if neu not in ("K1", "K2"):
        return {"fehler": "Hebung nur nach K1 oder K2 erlaubt (K4/K5 -> K1/K2)."}, 400
    if not beleg:
        return {"fehler": "Beleg ist Pflicht (DOI/URL/Digitalisat/Campus)."}, 400
    if not _re.match(r"^\d{4}-\d{2}-\d{2}$", datum):
        return {"fehler": "Datum muss YYYY-MM-DD sein (aus aktuelles_datum, nie raten)."}, 400
    today = time.strftime("%Y-%m-%d")
    if datum > today:
        return {"fehler": "Datum liegt in der Zukunft (heute %s)." % today}, 400
    con = db()
    row = con.execute("SELECT * FROM pos WHERE id = ?", (pid,)).fetchone()
    if not row:
        con.close()
        return {"fehler": "Position %s nicht gefunden." % pid}, 404
    alt = row["k"]
    if alt == neu:
        con.close()
        return {"fehler": "Position %s ist bereits %s." % (pid, neu)}, 400
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    con.execute("UPDATE pos SET k = ?, updated = ? WHERE id = ?", (neu, datum, pid))
    try:
        con.execute("DELETE FROM pos_fts WHERE id = ?", (pid,))
        con.execute("INSERT INTO pos_fts(id, titel, quelle, vermerk, k, rel) SELECT id, titel, quelle, vermerk, k, rel FROM pos WHERE id = ?", (pid,))
    except sqlite3.OperationalError:
        pass
    con.execute("INSERT INTO aenderungen VALUES (?,?,?,?,?,?)", (ts, pid, alt, neu, beleg, datum))
    con.commit()
    con.close()
    # write-through: project.json aktualisieren (k + kstand + vermerk)
    d = load_project()
    for r in d["verzeichnis"]:
        if r["id"] == pid:
            r["k"] = neu
            r["vermerk"] = ((r.get("vermerk") or "") + " | Hebung %s: %s -> %s (Beleg: %s)" % (datum, alt, neu, beleg)).strip(" |")
    k = d["kstand"]["K"]
    if alt in k and k[alt] > 0:
        k[alt] -= 1
    k[neu] = k.get(neu, 0) + 1
    save_project(d)
    return {"ok": True, "id": pid, "alt_k": alt, "neu_k": neu, "beleg": beleg, "datum": datum, "ts": ts}, 200


def qv_aenderungen():
    con = db()
    rows = [dict(r) for r in con.execute("SELECT * FROM aenderungen ORDER BY ts DESC LIMIT 200").fetchall()]
    con.close()
    return rows


def qv_export():
    d = load_project()
    con = db()
    d["verzeichnis_db"] = [dict(r) for r in con.execute("SELECT * FROM pos ORDER BY id").fetchall()]
    d["aenderungen"] = qv_aenderungen()
    con.close()
    return d


def qv_quellen(q):
    """Quellendatenbank: Positionen gruppiert nach Quelle mit K-Verteilung und IDs."""
    con = db()
    base = ("SELECT quelle, COUNT(*) n, "
            "SUM(CASE WHEN k='K1' THEN 1 ELSE 0 END) K1, SUM(CASE WHEN k='K2' THEN 1 ELSE 0 END) K2, "
            "SUM(CASE WHEN k='K3' THEN 1 ELSE 0 END) K3, SUM(CASE WHEN k='K4' THEN 1 ELSE 0 END) K4, "
            "SUM(CASE WHEN k='K5' THEN 1 ELSE 0 END) K5, GROUP_CONCAT(id, ', ') ids "
            "FROM pos ")
    if q:
        rows = con.execute(base + "WHERE quelle LIKE ? GROUP BY quelle ORDER BY n DESC, quelle LIMIT 300",
                           ("%" + q + "%",)).fetchall()
    else:
        rows = con.execute(base + "GROUP BY quelle ORDER BY n DESC, quelle LIMIT 300").fetchall()
    out = [dict(r) for r in rows]
    con.close()
    return {"rows": out, "total": len(out)}


def load_templates():
    p = DATA / "templates.json"
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"templates": []}


def render_template(payload):
    """Einfache {{key}}-Ersetzung aus data/templates.json; context kommt vom Client (nur Loopback)."""
    tid = str(payload.get("template", "")).strip()
    ctx = payload.get("context")
    if not isinstance(ctx, dict):
        return {"fehler": "context muss ein Objekt sein"}, 400
    tpl = next((t for t in load_templates().get("templates", []) if str(t.get("id")) == tid), None)
    if not tpl:
        return {"fehler": "Template nicht gefunden: %s" % tid}, 404

    def repl(m):
        v = ctx.get(m.group(1).strip())
        return "" if v is None else str(v)

    text = _re.sub(r"\{\{\s*([\w.]+)\s*\}\}", repl, str(tpl.get("text", "")))
    return {"ok": True, "id": tid, "text": text, "laenge": len(text)}, 200


def diff_lines(payload):
    """Zeilenweiser Diff (difflib) als JSON: Liste von {t: ''|'+'|'-', line}."""
    a = str(payload.get("a", ""))
    b = str(payload.get("b", ""))
    if len(a) > 200000 or len(b) > 200000:
        return {"fehler": "Eingabe zu gross (max 200000 Zeichen je Seite)"}, 413
    import difflib
    al, bl = a.splitlines(), b.splitlines()
    sm = difflib.SequenceMatcher(a=al, b=bl, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for line in al[i1:i2]:
                out.append({"t": "", "line": line})
            continue
        for line in al[i1:i2]:
            out.append({"t": "-", "line": line})
        for line in bl[j1:j2]:
            out.append({"t": "+", "line": line})
    return {"ok": True, "lines": out,
            "stats": {"ins": sum(1 for x in out if x["t"] == "+"), "del": sum(1 for x in out if x["t"] == "-")}}, 200


# ---------- optional live (Mistral-Library; Key nur aus Env) ----------

def _client():
    key = os.environ.get("PROJECT_MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY")
    if not key:
        return None, "kein API-Key in Umgebung (MISTRAL_API_KEY/PROJECT_MISTRAL_API_KEY)"
    from mistralai.workflows.client import get_mistral_client
    return get_mistral_client(api_key=key), None


def live_info():
    """Optional live: neueste Ablage-Doks + QV-Standzeile aus dem Apparat (Key nur aus Env)."""
    try:
        client, err = _client()
        if client is None:
            return {"live": False, "grund": err}

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
    except Exception as e:
        return {"live": False, "grund": f"{type(e).__name__}: {e}"[:200]}


def libraries_live():
    """Optional live: alle Libraries des Workspace (Fallback: die zwei bekannten)."""
    try:
        client, err = _client()
        if client is None:
            return {"live": False, "grund": err, "libs": []}
        import asyncio

        async def _go():
            libs = []
            try:
                res = await client.beta.libraries.list_async()
                for l in (getattr(res, "data", None) or []):
                    libs.append({"id": l.id, "name": l.name, "docs": getattr(l, "nb_documents", None)})
            except Exception:
                pass
            if not libs:
                libs = [{"id": NOTES_LIBRARY_ID, "name": "Grammatik statt Stil – Research-Ablage (Agent)"},
                        {"id": APPARAT_LIBRARY_ID, "name": "Apparat-Bibliothek"}]
            return libs

        return {"live": True, "libs": asyncio.run(_go())}
    except Exception as e:
        return {"live": False, "grund": f"{type(e).__name__}: {e}"[:200], "libs": []}


def library_docs(lib_id, q):
    try:
        client, err = _client()
        if client is None:
            return {"live": False, "grund": err, "docs": []}
        if not lib_id:
            return {"live": False, "grund": "lib fehlt", "docs": []}
        import asyncio

        async def _go():
            l = await client.beta.libraries.documents.list_async(library_id=lib_id, search=(q or None), page_size=50)
            return [{"id": d.id, "name": d.name, "status": getattr(d, "processing_status", None)} for d in (l.data or [])]

        return {"live": True, "lib": lib_id, "docs": asyncio.run(_go())}
    except Exception as e:
        return {"live": False, "grund": f"{type(e).__name__}: {e}"[:200], "docs": []}


def library_doc_text(lib_id, doc_id):
    try:
        client, err = _client()
        if client is None:
            return {"live": False, "grund": err}
        import asyncio

        async def _go():
            c = await client.beta.libraries.documents.text_content_async(library_id=lib_id, document_id=doc_id)
            t = getattr(c, "text", None) or str(c)
            return t[:4000] + (" … [gekürzt, Gesamtlänge %d]" % len(t) if len(t) > 4000 else "")

        return {"live": True, "lib": lib_id, "id": doc_id, "text": asyncio.run(_go())}
    except Exception as e:
        return {"live": False, "grund": f"{type(e).__name__}: {e}"[:200]}


def ablage_search(q):
    return library_docs(NOTES_LIBRARY_ID, q)


def ablage_doc(doc_id):
    return library_doc_text(NOTES_LIBRARY_ID, doc_id)


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "ResearchHub/1.0"

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, status=200, download_name=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if download_name:
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % download_name)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # CORS: statische Shell darf von anderer Origin (z. B. GitHub Pages) die Live-API rufen;
        # Origin einschraenkbar via Env CORS_ORIGIN (Default * - nur lesende GETs/POSTs ohne Credentials)
        self.send_header("Access-Control-Allow-Origin", os.environ.get("CORS_ORIGIN", "*"))
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        try:
            body = path.read_bytes()
        except OSError:
            self._json({"fehler": "not found"}, 404)
            return
        ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".json": "application/json; charset=utf-8", ".md": "text/markdown; charset=utf-8",
                 ".webmanifest": "application/manifest+json", ".png": "image/png", ".svg": "image/svg+xml",
                 ".ico": "image/x-icon", ".db": "application/octet-stream"}.get(path.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # CORS: statische Shell darf von anderer Origin (z. B. GitHub Pages) die Live-API rufen;
        # Origin einschraenkbar via Env CORS_ORIGIN (Default * - nur lesende GETs/POSTs ohne Credentials)
        self.send_header("Access-Control-Allow-Origin", os.environ.get("CORS_ORIGIN", "*"))
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            return self._file(BASE / "index.html")
        if u.path.startswith("/data/"):
            rel = u.path[len("/data/"):]
            if ".." in rel:
                return self._json({"fehler": "bad path"}, 400)
            return self._file(DATA / rel)
        rel = u.path.lstrip("/")
        if rel and ".." not in rel:
            cand = (BASE / rel).resolve()
            if str(cand).startswith(str(BASE) + os.sep) and cand.is_file():
                return self._file(cand)
        if u.path == "/api/stats":
            d = load_project()
            k = d["kstand"]["K"]
            n = d["kstand"]["positionen"]
            g = d["kstand"]["gruppen_enden"]
            return self._json({
                "meta": d["meta"], "kstand": d["kstand"],
                "vt_quote": round((k["K1"] + k["K2"]) / n * 100, 1),
                "gruppen": {"enden": g, "avg": round(n / len(g), 1)},
            })
        if u.path == "/api/verzeichnis":
            return self._json(load_project()["verzeichnis"])
        if u.path == "/api/glossar":
            return self._json(load_project()["glossar"])
        if u.path == "/api/messages":
            return self._json(load_outbox())
        if u.path == "/api/live":
            return self._json(live_info())
        if u.path == "/api/ablage":
            return self._json(ablage_search(qs.get("q", [""])[0]))
        if u.path == "/api/ablage/doc":
            return self._json(ablage_doc(qs.get("id", [""])[0]))
        if u.path == "/api/qv":
            return self._json(qv_search(qs.get("q", [""])[0], qs.get("k", [""])[0], qs.get("rel", [""])[0],
                                         _qint(qs, "limit", 200)))
        if u.path == "/api/qv/aenderungen":
            return self._json(qv_aenderungen())
        if u.path == "/api/qv/export":
            return self._json(qv_export(), download_name="qv-export-%s.json" % time.strftime("%Y%m%d"))
        if u.path == "/api/libraries":
            return self._json(libraries_live())
        if u.path == "/api/library/docs":
            return self._json(library_docs(qs.get("lib", [""])[0], qs.get("q", [""])[0]))
        if u.path == "/api/library/doc":
            return self._json(library_doc_text(qs.get("lib", [""])[0], qs.get("id", [""])[0]))
        if u.path == "/api/quellen":
            return self._json(qv_quellen(qs.get("q", [""])[0]))
        if u.path == "/api/templates":
            return self._json(load_templates())
        return self._json({"fehler": "not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", os.environ.get("CORS_ORIGIN", "*"))
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        from urllib.parse import urlparse
        u = urlparse(self.path)
        if u.path in ("/api/message", "/api/qv/hebung", "/api/render", "/api/diff"):
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > 1000000:
                    return self._json({"fehler": "Body zu gross (max 1 MB)"}, 413)
                payload = json.loads(self.rfile.read(length) or b"{}")
                if u.path == "/api/message":
                    text = str(payload.get("text", "")).strip()
                    if not text:
                        return self._json({"fehler": "text fehlt"}, 400)
                    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "text": text}
                    with open(DATA / "outbox.jsonl", "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    return self._json(entry)
                if u.path == "/api/render":
                    obj, status = render_template(payload)
                    return self._json(obj, status)
                if u.path == "/api/diff":
                    obj, status = diff_lines(payload)
                    return self._json(obj, status)
                obj, status = qv_heben(payload)
                return self._json(obj, status)
            except Exception as e:
                return self._json({"fehler": str(e)[:200]}, 400)
        return self._json({"fehler": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    DATA.mkdir(exist_ok=True)
    fts = init_db()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    fts_label = "ja" if fts else "nein (LIKE-Fallback)"
    print(f"Research Hub: http://{args.host}:{args.port}/  (Default nur Loopback; FTS5={fts_label}; Ctrl+C beendet)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
