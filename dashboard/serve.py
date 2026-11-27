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
  POST /api/auth/login       {"password"} -> Session-Cookie (HttpOnly, SameSite=Strict, CSRF-Token); nur wenn --password/DASHBOARD_PASSWORD gesetzt
  GET  /api/auth/me          {authenticated, csrf, project, password_mode, token_mode}
  POST /api/auth/logout      Session loeschen (Cookie ablaufen lassen)
  GET  /api/projects         Libraries des Workspace = Projekte; {libs, active, live}
  POST /api/projects/select  {"library_id"} -> aktives Projekt der Session (serverseitig gehalten)
  POST /api/projects/create  {"name"} -> neue Library anlegen + Seed (00-projektstand.md, projekt.json)
  GET  /api/project          projekt.json der aktiven Library (agenten: [{name,deployment,workflow}], cron, apparat_library?)
  GET  /api/apparat/qv       A1: komplettes QV LIVE aus der Apparat-Library (Standzeile + paged Text; ?lib= Override, ?offset=&limit=)
  GET  /api/wf/status?deployment=   Deployment-Status (ready, Worker, Revision)
  GET  /api/wf/runs?deployment=&limit=   neueste Workflow-Runs
  GET  /api/wf/runs/{id}/logs?limit=&cursor=   Execution-Logs (gepaget)
  POST /api/wf/run           {"deployment","workflow","input"} -> Workflow starten (kostet Modelllauf)
  GET  /api/wf/schedules     Cron-Plaene
  POST /api/notes            {"titel","text"} -> Write-Through: Notiz (Markdown) in die aktive Projekt-Library

Kein Schreibzugriff nach außen; Default bindet der Server nur an 127.0.0.1. Statisch serviert: /, index.html, sw.js, manifest.webmanifest, icons/, data/ (PWA: Manifest + Service Worker + Icons).
"""
import argparse
import datetime
import hashlib
import hmac
import json
import os
import re as _re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
HUB_TOKEN = None   # via --token; schuetzt /api/* und /data/* (Query ?token= oder Header X-Hub-Token)
HUB_PASSWORD_HASH = None  # sha256("hub-v1:"+password) via --password/DASHBOARD_PASSWORD; Klartext wird nie gehalten/geloggt
ALLOWED_HOSTS = set()     # zusaetzliche erlaubte Host-Header (DNS-Rebinding-Guard) via --allowed-hosts/DASHBOARD_ALLOWED_HOSTS
TRUST_GATEWAY = os.environ.get("DASHBOARD_TRUST_GATEWAY_AUTH", "") == "1"  # Studio-App (studio-app/): Auth liegt am Studio-Gateway vor dem Modul
LOG_ACCESS = False  # via --log: Access-Log nach data/hub.log
_SESSIONS = {}            # sid -> {"created","last","csrf","project"} (In-Memory; Neustart = Logout)
_SESSION_TTL = 12 * 3600  # 12 h
_SESSION_LOCK = threading.Lock()
_LOGIN_FAILS = {}         # ip -> [timestamps]; >=5 Fehlversuche in 300 s -> 900 s Lockout (429)


def _access_log(line):
    # Secrets im Query-String (?token=...) duerfen nie ins Log landen
    line = _re.sub(r"([?&])token=[^&\s\"']+", r"\1token=[REDACTED]", line, flags=_re.IGNORECASE)
    line = _re.sub(r"([?&])password=[^&\s\"']+", r"\1password=[REDACTED]", line, flags=_re.IGNORECASE)
    if LOG_ACCESS:
        try:
            with open(DATA / "hub.log", "a", encoding="utf-8") as f:
                f.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), line))
        except OSError:
            pass
DATA = BASE / "data"
DB = DATA / "qv.db"
# statisch servierte Dateiendungen (alles andere unter BASE bleibt 404 — kein Quellcode-Leak)
STATIC_SUFFIXES = {".html", ".js", ".css", ".json", ".md", ".webmanifest", ".png", ".svg", ".ico", ".db", ".map"}
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


SCHEMA_VERSION = 3

POS_DDL = """CREATE TABLE pos(
  id TEXT PRIMARY KEY, titel TEXT, quelle TEXT, k TEXT, rel TEXT, vermerk TEXT, updated TEXT,
  prio TEXT DEFAULT '', jahr INTEGER, typ TEXT DEFAULT '', added TEXT DEFAULT '')"""


def _read_added(con):
    """added-Zeitstempel der aktuellen pos-Tabelle retten (vor DROP/RESEED aufrufen);
    None, wenn die Spalte noch nicht existiert (Migration von Schema < 3)."""
    try:
        return {r["id"]: r["added"] for r in con.execute("SELECT id, added FROM pos").fetchall()}
    except sqlite3.OperationalError:
        return None


def _seed(con, d, fts, old_added=None):
    # old_added: Map id->added der vorherigen Tabelle (None = frisches Schema -> nichts ist "neu")
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    con.execute("DELETE FROM pos")
    if fts:
        try:
            con.execute("DELETE FROM pos_fts")
        except sqlite3.OperationalError:
            pass
    for r in d["verzeichnis"]:
        added = (old_added.get(r["id"], now) if old_added is not None else "")
        con.execute("INSERT OR REPLACE INTO pos VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (r["id"], r["titel"], r["quelle"], r["k"], r.get("rel", ""), r.get("vermerk", ""),
                     r.get("updated") or time.strftime("%Y-%m-%d"),
                     r.get("prio", ""), r.get("jahr"), r.get("typ", ""), added))
        if fts:
            con.execute("INSERT INTO pos_fts(id, titel, quelle, vermerk, k, rel) VALUES (?,?,?,?,?,?)",
                        (r["id"], r["titel"], r["quelle"], r.get("vermerk", ""), r["k"], r.get("rel", "")))
    pc = con.execute("SELECT COUNT(*) c FROM pruef").fetchone()["c"]
    if pc == 0:
        for p in d.get("pruefaufgaben", []):
            con.execute("INSERT OR REPLACE INTO pruef(n, text, prio, status, ts) VALUES (?,?,?,?,?)",
                        (p["n"], p["text"], p.get("prio", ""),
                         "erledigt" if p.get("erledigt") else "offen", time.strftime("%Y-%m-%d")))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('kstand', ?)", (json.dumps(d["kstand"], ensure_ascii=False),))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('meta', ?)", (json.dumps(d["meta"], ensure_ascii=False),))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('project_mtime', ?)",
                (str(os.path.getmtime(DATA / "project.json")),))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    con.commit()


def init_db():
    fresh = not DB.exists()
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS aenderungen(
      ts TEXT, pos_id TEXT, alt_k TEXT, neu_k TEXT, beleg TEXT, datum TEXT);
    CREATE TABLE IF NOT EXISTS pruef(
      n INTEGER PRIMARY KEY, text TEXT, prio TEXT DEFAULT '', status TEXT DEFAULT 'offen', ts TEXT DEFAULT '');
    """)
    con.execute(POS_DDL.replace("CREATE TABLE pos", "CREATE TABLE IF NOT EXISTS pos"))
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS pos_fts USING fts5(id UNINDEXED, titel, quelle, vermerk, k UNINDEXED, rel UNINDEXED)")
        fts = True
    except sqlite3.OperationalError:
        fts = False
    ver = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    count = con.execute("SELECT COUNT(*) c FROM pos").fetchone()["c"]
    if fresh or count == 0 or ver is None or int(ver["value"]) < SCHEMA_VERSION:
        old_added = _read_added(con)  # vor dem DROP retten
        con.execute("DROP TABLE IF EXISTS pos")
        if fts:
            con.execute("DROP TABLE IF EXISTS pos_fts")
        con.execute(POS_DDL)
        if fts:
            con.execute("CREATE VIRTUAL TABLE pos_fts USING fts5(id UNINDEXED, titel, quelle, vermerk, k UNINDEXED, rel UNINDEXED)")
        _seed(con, load_project(), fts, old_added)
    con.close()
    return fts


def ensure_fresh():
    """QV-DB neu seeden, sobald data/project.json geaendert wurde (z. B. Re-Import
    ueber tools/import_apparat.py) oder das Schema gewechselt hat — kein Neustart noetig."""
    try:
        mt = str(os.path.getmtime(DATA / "project.json"))
    except OSError:
        return
    con = db()
    try:
        row = con.execute("SELECT value FROM meta WHERE key='project_mtime'").fetchone()
        ver = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is None or row["value"] != mt or ver is None or int(ver["value"]) < SCHEMA_VERSION:
            fts = True
            try:
                con.execute("SELECT 1 FROM pos_fts LIMIT 1")
            except sqlite3.OperationalError:
                fts = False
            old_added = _read_added(con)  # vor dem DROP retten
            con.execute("DROP TABLE IF EXISTS pos")
            if fts:
                con.execute("DROP TABLE IF EXISTS pos_fts")
            con.execute(POS_DDL)
            if fts:
                con.execute("CREATE VIRTUAL TABLE pos_fts USING fts5(id UNINDEXED, titel, quelle, vermerk, k UNINDEXED, rel UNINDEXED)")
            _seed(con, load_project(), fts, old_added)
    finally:
        con.close()


def _fts_query(q):
    """FTS5-MATCH-Ausdruck: Tokens als Praefix-Treffer (\"paris\"* matcht auch \"Pariser\")."""
    toks = [t for t in _re.split(r"[^\w\-/]+", q, flags=_re.UNICODE) if t]
    return " ".join('"%s"*' % t.replace('"', '""') for t in toks)


def qv_search(q, k, rel, limit=200, offset=0):
    con = db()
    k, rel = (k or ""), (rel or "")
    off = max(0, int(offset))
    try:
        if q and _fts_query(q):
            sql = ("SELECT p.* FROM pos_fts f JOIN pos p ON p.id = f.id "
                   "WHERE pos_fts MATCH ? AND (? = '' OR p.k = ?) AND (? = '' OR p.rel = ?) "
                   "ORDER BY rank LIMIT ? OFFSET ?")
            rows = con.execute(sql, (_fts_query(q), k, k, rel, rel, limit, off)).fetchall()
        else:
            like = "%" + (q or "") + "%"
            rows = con.execute("SELECT * FROM pos WHERE (titel LIKE ? OR quelle LIKE ? OR vermerk LIKE ? OR id LIKE ?) "
                               "AND (? = '' OR k = ?) AND (? = '' OR rel = ?) ORDER BY id LIMIT ? OFFSET ?",
                               (like, like, like, like, k, k, rel, rel, limit, off)).fetchall()
    except sqlite3.OperationalError:
        like = "%" + (q or "") + "%"
        rows = con.execute("SELECT * FROM pos WHERE (titel LIKE ? OR quelle LIKE ? OR vermerk LIKE ? OR id LIKE ?) "
                           "AND (? = '' OR k = ?) AND (? = '' OR rel = ?) ORDER BY id LIMIT ? OFFSET ?",
                           (like, like, like, like, k, k, rel, rel, limit, off)).fetchall()
    out = [dict(r) for r in rows]
    total = con.execute("SELECT COUNT(*) c FROM pos").fetchone()["c"]
    con.close()
    return {"rows": out, "total": total, "offset": off}


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
            "SUM(CASE WHEN k='K5' THEN 1 ELSE 0 END) K5, GROUP_CONCAT(id, ', ') ids, MAX(added) added "
            "FROM pos ")
    if q:
        rows = con.execute(base + "WHERE quelle LIKE ? GROUP BY quelle ORDER BY n DESC, quelle LIMIT 1000",
                           ("%" + q + "%",)).fetchall()
    else:
        rows = con.execute(base + "GROUP BY quelle ORDER BY n DESC, quelle LIMIT 1000").fetchall()
    cutoff = (time.time() - 2 * 24 * 3600)
    cutoff_s = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(cutoff))
    out = []
    for r in rows:
        d = dict(r)
        d["neu"] = bool(d.get("added") and d["added"] >= cutoff_s)
        out.append(d)
    con.close()
    return {"rows": out, "total": len(out)}


# ---------- Export (RIS / BibTeX / JSON), Duplikate, Prüfaufgaben, Edit, Snapshots ----------

def _all_rows():
    con = db()
    rows = [dict(r) for r in con.execute("SELECT * FROM pos ORDER BY id").fetchall()]
    con.close()
    return rows


def to_ris(rows):
    out = []
    for r in rows:
        typ = {"Fachaufsatz": "JOUR", "Online": "ELEC"}.get(r.get("typ"), "BOOK")
        out.append("\n".join([
            "TY  - " + typ,
            "ID  - " + r["id"],
            "TI  - " + (r["titel"] or "").replace("\n", " "),
            "T2  - " + (r["quelle"] or "").replace("\n", " "),
            "PY  - " + (str(r.get("jahr")) if r.get("jahr") else ""),
            "KW  - K=" + (r.get("k") or ""),
            "KW  - Rel=" + (r.get("rel") or ""),
            "KW  - Prio=" + (r.get("prio") or "-"),
            "N1  - " + ((r.get("vermerk") or "")[:300].replace("\n", " ")),
            "ER  - ",
        ]))
    return "\n".join(out) + "\n"


def to_bib(rows):
    def esc(s):
        return (s or "").replace("\\", "\\textbackslash{}").replace("{", "\\{").replace("}", "\\}")
    out = []
    for r in rows:
        key = "qv" + (r["id"] or "x").replace("/", "_")
        out.append("@misc{%s,\n  title = {%s},\n  howpublished = {%s},\n  year = {%s},\n"
                   "  note = {QV-ID %s; K %s; Rel. %s; Prio %s},\n}"
                   % (key, esc(r["titel"]), esc(r["quelle"]),
                      r.get("jahr") or "o.J.", r["id"], r.get("k") or "", r.get("rel") or "", r.get("prio") or "-"))
    return "\n\n".join(out) + "\n"


def qv_dupes():
    def norm(s, n=80):
        return _re.sub(r"[^a-z0-9]+", "", (s or "").lower())[:n]
    groups = {}
    for r in _all_rows():
        keys = []
        t = norm(r["titel"])
        if t:
            keys.append("t:" + t)
        q = (r["quelle"] or "").strip()
        if _re.match(r"^(https?://|DOI )", q, _re.I):
            keys.append("q:" + norm(q, 120))
        for key in keys:
            groups.setdefault(key, []).append({"id": r["id"], "titel": r["titel"], "quelle": r["quelle"], "k": r.get("k", "")})
    # nur Gruppen, die wirklich >1 distincte IDs haben
    seen, out = set(), []
    for v in groups.values():
        ids = tuple(sorted(x["id"] for x in v))
        if len(v) > 1 and ids not in seen:
            seen.add(ids)
            out.append({"n": len(v), "rows": v})
    out.sort(key=lambda g: -g["n"])
    return {"gruppen": out, "anzahl": len(out)}


def pruef_list():
    con = db()
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM pruef ORDER BY (status='erledigt'), prio, n").fetchall()]
    con.close()
    return {"rows": rows, "total": len(rows)}


def pruef_upsert(payload):
    n = payload.get("n")
    text = str(payload.get("text", "")).strip()
    prio = str(payload.get("prio", "")).strip()[:4]
    status = str(payload.get("status", "")).strip()
    con = db()
    if n is None:
        if not text:
            con.close()
            return {"fehler": "text fehlt"}, 400
        mx = con.execute("SELECT COALESCE(MAX(n),0) m FROM pruef").fetchone()["m"]
        n = mx + 1
        con.execute("INSERT INTO pruef(n, text, prio, status, ts) VALUES (?,?,?,?,?)",
                    (n, text[:4000], prio, status or "offen", time.strftime("%Y-%m-%d")))
    else:
        n = int(n)
        row = con.execute("SELECT * FROM pruef WHERE n=?", (n,)).fetchone()
        if row is None:
            con.close()
            return {"fehler": "nicht gefunden"}, 404
        if text:
            con.execute("UPDATE pruef SET text=? WHERE n=?", (text[:4000], n))
        if prio:
            con.execute("UPDATE pruef SET prio=? WHERE n=?", (prio, n))
        if status in ("offen", "erledigt"):
            con.execute("UPDATE pruef SET status=? WHERE n=?", (status, n))
    con.commit()
    row = con.execute("SELECT * FROM pruef WHERE n=?", (n,)).fetchone()
    con.close()
    return {"ok": True, "row": dict(row)}, 200


EDIT_FIELDS = {"titel": 5000, "quelle": 5000, "vermerk": 100000, "rel": 4, "prio": 4}


def qv_edit(payload):
    pid = str(payload.get("id", "")).strip()
    field = str(payload.get("field", "")).strip()
    value = str(payload.get("value", ""))
    if field not in EDIT_FIELDS:
        return {"fehler": "feld nicht editierbar"}, 400
    if not pid or len(value) > EDIT_FIELDS[field]:
        return {"fehler": "ungueltig"}, 400
    con = db()
    row = con.execute("SELECT * FROM pos WHERE id=?", (pid,)).fetchone()
    if row is None:
        con.close()
        return {"fehler": "id unbekannt"}, 404
    con.execute("UPDATE pos SET %s=? WHERE id=?" % field, (value, pid))
    if field in ("titel", "quelle", "vermerk"):
        try:
            con.execute("UPDATE pos_fts SET %s=? WHERE id=?" % field, (value, pid))
        except sqlite3.OperationalError:
            pass
    con.commit()
    row = con.execute("SELECT * FROM pos WHERE id=?", (pid,)).fetchone()
    con.close()
    # write-through nach project.json
    d = load_project()
    for r in d["verzeichnis"]:
        if r["id"] == pid:
            r[field] = value
            r["updated"] = time.strftime("%Y-%m-%d")
    save_project(d)
    return {"ok": True, "row": dict(row)}, 200


SNAP_DIR = DATA / "snapshots"


def snapshot_project(max_keep=30):
    SNAP_DIR.mkdir(exist_ok=True)
    name = "project-%s.json" % time.strftime("%Y%m%d-%H%M%S")
    (SNAP_DIR / name).write_text((DATA / "project.json").read_text(encoding="utf-8"), encoding="utf-8")
    snaps = sorted(SNAP_DIR.glob("project-*.json"))
    for old in snaps[:-max_keep]:  # nur die neuesten 30 Snapshots behalten
        try:
            old.unlink()
        except OSError:
            pass
    return name


def list_snapshots():
    if not SNAP_DIR.exists():
        return {"snapshots": []}
    return {"snapshots": sorted(p.name for p in SNAP_DIR.glob("project-*.json"))}


def _load_snapshot(name):
    name = os.path.basename(name)
    if not name.startswith("project-") or not name.endswith(".json"):
        return None
    p = SNAP_DIR / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def qv_diff(a, b):
    da, db_ = _load_snapshot(a), _load_snapshot(b)
    if da is None or db_ is None:
        return {"fehler": "snapshot nicht gefunden"}, 404
    A = {r["id"]: r for r in da.get("verzeichnis", [])}
    B = {r["id"]: r for r in db_.get("verzeichnis", [])}
    added = sorted(set(B) - set(A))
    removed = sorted(set(A) - set(B))
    changed = []
    for pid in sorted(set(A) & set(B)):
        diffs = {}
        for f in ("k", "rel", "prio"):
            if (A[pid].get(f) or "") != (B[pid].get(f) or ""):
                diffs[f] = [A[pid].get(f) or "", B[pid].get(f) or ""]
        if diffs:
            changed.append({"id": pid, "titel": (B[pid].get("titel") or "")[:80], "diffs": diffs})
    return {"a": a, "b": b,
            "kstand_a": da.get("kstand"), "kstand_b": db_.get("kstand"),
            "hinzu": added, "entfernt": removed, "geaendert": changed}, 200


def run_import(auto=False):
    """tools/import_apparat.py live ausfuehren (Key aus Server-Env); Snapshot vorher anlegen.
    auto=True (Dashboard-Start): Ueberspringen, wenn der letzte Import < 300 s zurueckliegt."""
    con = db()
    try:
        row = con.execute("SELECT value FROM meta WHERE key='last_import'").fetchone()
        if auto and row:
            try:
                age = time.time() - float(row["value"])
            except (TypeError, ValueError):
                age = 10**9
            if age < 300:
                n = con.execute("SELECT COUNT(*) c FROM pos").fetchone()["c"]
                con.close()
                try:
                    mt = str(os.path.getmtime(DATA / "project.json"))
                except OSError:
                    mt = ""
                return {"ok": True, "skipped": True,
                        "grund": "letzter Import vor %d s" % int(age), "positionen": n, "mtime": mt}, 200
        con.execute("INSERT OR REPLACE INTO meta VALUES ('last_import', ?)", (str(time.time()),))
        con.commit()
    finally:
        con.close()
    name = snapshot_project()
    script = BASE / "tools" / "import_apparat.py"
    try:
        p = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=180)
        ensure_fresh()  # project.json hat sich geaendert -> DB sofort neu seeden
        con = db()
        n = con.execute("SELECT COUNT(*) c FROM pos").fetchone()["c"]
        con.close()
        try:
            mt = str(os.path.getmtime(DATA / "project.json"))
        except OSError:
            mt = ""
        return {"ok": p.returncode == 0, "rc": p.returncode, "snapshot": name, "positionen": n, "mtime": mt,
                "log": (p.stdout + p.stderr)[-3000:]}, 200 if p.returncode == 0 else 500
    except Exception as e:
        return {"ok": False, "fehler": "%s: %s" % (type(e).__name__, e)[:200], "snapshot": name}, 500


def stats_extra():
    con = db()
    jahre = {}
    for r in con.execute("SELECT jahr, COUNT(*) c FROM pos WHERE jahr IS NOT NULL GROUP BY jahr").fetchall():
        decade = (r["jahr"] // 10) * 10
        jahre[decade] = jahre.get(decade, 0) + r["c"]
    typen = {r["typ"]: r["c"] for r in con.execute("SELECT typ, COUNT(*) c FROM pos GROUP BY typ").fetchall()}
    matrix = {}
    for r in con.execute("SELECT substr(id, 1, instr(id, '/') - 1) g, k, COUNT(*) c FROM pos GROUP BY g, k").fetchall():
        matrix.setdefault(str(r["g"]), {})[r["k"]] = r["c"]
    con.close()
    return {"jahre": [{"dekade": d, "n": n} for d, n in sorted(jahre.items())],
            "typen": typen, "matrix": matrix}


ESSAY_LIBRARY_ID = "01a1843c-f463-71db-a3fe-ae8b3814f155"  # Grammatik statt Stil Bibliothek


def coverage():
    """Zitations-Coverage: welche QV-Positionen kommen im Essay-Text vor?"""
    try:
        client, err = _client()
        if client is None:
            return {"live": False, "grund": err}
        import asyncio

        async def _go():
            l = await client.beta.libraries.documents.list_async(library_id=ESSAY_LIBRARY_ID, search="Essay", page_size=10)
            doc = next((d for d in (l.data or []) if "Essay" in (d.name or "")), None)
            if doc is None:
                l2 = await client.beta.libraries.documents.list_async(library_id=ESSAY_LIBRARY_ID, page_size=50)
                doc = next((d for d in (l2.data or []) if "Essay" in (d.name or "")), None)
            if doc is None:
                return None, "kein Essay-Dokument in der Projekt-Bibliothek gefunden"
            c = await client.beta.libraries.documents.text_content_async(library_id=ESSAY_LIBRARY_ID, document_id=doc.id)
            return (getattr(c, "text", None) or str(c)), doc.name

        text, docname = asyncio.run(_go())
        if text is None:
            return {"live": False, "grund": docname}
        norm = _re.sub(r"[^a-z0-9]+", "", (text or "").lower())
        rows = _all_rows()
        cited = []
        per_g = {}
        for r in rows:
            g = r["id"].split("/")[0]
            hit = r["id"] in (text or "")
            if not hit:
                frag = _re.sub(r"[^a-z0-9]+", "", (r["titel"] or "").lower())[:30]
                hit = bool(frag) and frag in norm
            per_g.setdefault(g, {"cited": 0, "total": 0})
            per_g[g]["total"] += 1
            if hit:
                cited.append(r["id"])
                per_g[g]["cited"] += 1
        return {"live": True, "essay": docname, "cited": cited, "total": len(rows),
                "pct": round(len(cited) / len(rows) * 100, 1) if rows else 0, "proGruppe": per_g}
    except Exception as e:
        return {"live": False, "grund": "%s: %s" % (type(e).__name__, e)[:200]}


AGENT_NAME = os.environ.get("FORSCHUNG_AGENT_NAME", "grammatik-statt-stil-research")
CONV_FILE = DATA / "agent-conv.json"
AGENTS_BASE = os.environ.get("FORSCHUNG_AGENTS_BASE", "https://api.mistral.ai/v2/agents")


def _api_key():
    return os.environ.get("PROJECT_MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY")


def _v2(method, path, body=None, timeout=60):
    """Stdlib-HTTP gegen das Agents-v2-Control-Plane (Managed Agents / Sessions)."""
    import urllib.request
    key = _api_key()
    if not key:
        raise RuntimeError("kein API-Key in Umgebung (MISTRAL_API_KEY/PROJECT_MISTRAL_API_KEY)")
    req = urllib.request.Request(
        AGENTS_BASE + path, method=method,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw or b"null")


def _conv_state():
    if CONV_FILE.exists():
        try:
            return json.loads(CONV_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _new_session():
    """Legt eine frische Managed-Agent-Session an und speichert sie in data/agent-conv.json."""
    import uuid
    r = _v2("POST", "/sessions", {
        "idempotency_key": str(uuid.uuid4()),
        "agent_name": AGENT_NAME,
        "session_protocol": "session_v1",
    }, timeout=30)
    sid = (r.get("agent_session") or {}).get("agent_session_id") or r.get("agent_session_id")
    if not sid:
        raise RuntimeError("Session-Antwort ohne agent_session_id: %s" % str(r)[:200])
    CONV_FILE.write_text(json.dumps({"agent": AGENT_NAME, "session_id": sid, "conversation_id": sid},
                                    ensure_ascii=False), encoding="utf-8")
    return sid


def _ensure_session():
    """Session-ID des Managed Agents; persistent in data/agent-conv.json.
    Legt bei Bedarf eine neue Session an (agent_name lt. FORSCHUNG_AGENT_NAME)."""
    st = _conv_state()
    sid = st.get("session_id")
    if sid:
        try:
            _v2("GET", "/sessions/" + sid, timeout=20)
            return sid
        except Exception:
            pass  # Session serverseitig nicht mehr vorhanden -> neu anlegen
    return _new_session()


def _events_all(sid, max_pages=4):
    """Event-History seitenweise (nextCursor), bis zu max_pages*500 Events."""
    evs, cursor = [], None
    for _ in range(max_pages):
        path = "/sessions/%s/events/history?limit=500" % sid
        if cursor:
            path += "&cursor=" + cursor
        h = _v2("GET", path, timeout=30)
        evs.extend((h or {}).get("events") or [])
        cursor = (h or {}).get("nextCursor") or (h or {}).get("next_cursor")
        if not cursor:
            break
    return evs


def _session_preview(sid):
    """Fallback: letzter Nachrichten-Preview-Eintrag der Session aus der Session-Liste."""
    try:
        r = _v2("GET", "/sessions?limit=200", timeout=20)
        for it in (r or {}).get("items") or []:
            if it.get("agent_session_id") == sid:
                return it.get("preview") or ""
    except Exception:
        pass
    return ""


def _entry_text(entry):
    parts = []
    for c in (entry.get("content") or []):
        if isinstance(c, dict) and c.get("type") == "text":
            parts.append(c.get("text", ""))
    return "\n".join(parts)


def _running_turn(sid):
    """ID des aktuell laufenden Turns einer Session (aus den Events), sonst None."""
    turn_id = None
    for ev in _events_all(sid, 2):
        p = ((ev or {}).get("event") or {}).get("payload") or {}
        if p.get("type") == "turn_started":
            turn_id = (p.get("turn") or {}).get("id") or turn_id
        elif p.get("type") == "turn_terminated":
            if ((p.get("turn") or {}).get("id")) == turn_id:
                turn_id = None
    return turn_id


def agent_stop(sid):
    """Stoppt den laufenden Turn (interrupt_session); ohne laufenden Turn: Session
    terminieren (cancel_session)."""
    import uuid
    if not sid:
        return {"ok": False, "fehler": "session_id fehlt"}, 400
    tid = None
    try:
        tid = _running_turn(sid)
    except Exception:
        pass
    if tid:
        _v2("POST", "/sessions/%s/commands" % sid, {
            "type": "interrupt_session", "command_id": str(uuid.uuid4()),
            "source": "agents_sdk", "reason": "stop requested from dashboard",
            "expected_turn_id": tid,
        }, timeout=30)
        return {"ok": True, "aktion": "turn_interrupt", "turn_id": tid}, 200
    _v2("POST", "/sessions/%s/commands" % sid, {
        "type": "cancel_session", "command_id": str(uuid.uuid4()),
        "source": "agents_sdk", "reason": "cancel requested from dashboard",
    }, timeout=30)
    return {"ok": True, "aktion": "session_cancelled"}, 200


def agent_archive(sid, archived=True):
    """Session archivieren ( DELETE ist 405 ) bzw. wiederherstellen."""
    if not sid:
        return {"ok": False, "fehler": "session_id fehlt"}, 400
    _v2("POST", "/sessions/%s/archive" % sid, {"archived": bool(archived)}, timeout=30)
    _CACHE.pop("agent_sessions", None)
    return {"ok": True, "archived": bool(archived)}, 200


def agent_sessions():
    """Alle Sessions des Managed Agents (v2 Control Plane), neueste zuerst."""
    try:
        if not _api_key():
            return {"live": False, "grund": "kein API-Key in Umgebung (MISTRAL_API_KEY/PROJECT_MISTRAL_API_KEY)"}
        items, nxt = [], None
        for _ in range(5):
            path = "/sessions?limit=200&include_archived=true"
            if nxt:
                path += "&cursor=" + nxt
            h = _v2("GET", path, timeout=30)
            items.extend((h or {}).get("items") or [])
            nxt = (h or {}).get("next")
            if not nxt:
                break
        out = []
        for it in items:
            if (it.get("agent_name") or "") != AGENT_NAME:
                continue
            out.append({
                "id": it.get("agent_session_id"),
                "title": it.get("generated_title") or it.get("title") or "",
                "status": it.get("status") or "",
                "archived": bool(it.get("archived_at")),
                "app": it.get("application_name") or "",
                "created": str(it.get("created_at") or ""),
                "updated": str(it.get("updated_at") or ""),
            })
        out.sort(key=lambda s: (not s.get("archived"), s.get("updated") or s.get("created") or ""), reverse=True)
        return {"live": True, "agent": AGENT_NAME, "sessions": out[:100]}
    except Exception as e:
        return {"live": False, "grund": "%s: %s" % (type(e).__name__, str(e))[:200]}


def agent_history(sid=None):
    """Vollstaendiger Verlauf einer Managed-Agent-Session (default: gespeicherte in
    data/agent-conv.json; sid per ?session_id= waehlbar):
    Nachrichten (user/assistant) plus Trace-Eintraege (reasoning, tool_call, tool_result, notice),
    chronologisch sortiert; Streaming-Partialtexte werden auf die laengste Fassung kollabiert."""
    try:
        if not _api_key():
            return {"live": False, "grund": "kein API-Key in Umgebung (MISTRAL_API_KEY/PROJECT_MISTRAL_API_KEY)"}
        sid = sid or _conv_state().get("session_id")
        if not sid:
            return {"live": True, "agent": AGENT_NAME, "session_id": None, "conversation_id": None, "messages": []}
        best, order = {}, []
        for ev in _events_all(sid, 3):
            p = ((ev or {}).get("event") or {}).get("payload") or {}
            if p.get("type") not in ("history_entry_added", "history_entry_completed"):
                continue
            e = p.get("entry") or {}
            t = e.get("type")
            eid = e.get("id") or ""
            created = e.get("createdAt") or 0
            idx = e.get("index") or 0
            if t == "message" and e.get("role") in ("user", "assistant"):
                txt = _entry_text(e)
                if not txt:
                    continue
                item = {"role": e.get("role"), "text": txt[:4000]}
            elif t == "reasoning":
                txt = e.get("text") or ""
                if not txt:
                    continue
                item = {"role": "trace", "kind": "reasoning", "text": txt[:4000]}
            elif t == "tool_call":
                args = e.get("arguments")
                item = {"role": "trace", "kind": "tool_call", "name": e.get("name") or "",
                        "args": args if isinstance(args, (dict, list)) else {}, "text": ""}
            elif t == "tool_result":
                res = e.get("result")
                if res is None:
                    res = e.get("content")
                txt = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False)
                item = {"role": "trace", "kind": "tool_result", "name": e.get("name") or "",
                        "text": (txt or "")[:4000]}
            elif t == "notice":
                item = {"role": "trace", "kind": "notice", "text": (e.get("message") or "")[:1000]}
            else:
                continue
            if eid in best:
                if len(item.get("text") or "") > len(best[eid][2].get("text") or ""):
                    best[eid] = (created, idx, item)
            else:
                best[eid] = (created, idx, item)
                order.append(eid)
        msgs = []
        for eid in order:
            created, idx, item = best[eid]
            item = dict(item)
            item["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(created / 1000.0)) if created else ""
            msgs.append((created, idx, item))
        msgs.sort(key=lambda x: (x[0], x[1]))
        return {"live": True, "agent": AGENT_NAME, "session_id": sid, "conversation_id": sid,
                "messages": [m[2] for m in msgs]}
    except Exception as e:
        return {"live": False, "grund": "%s: %s" % (type(e).__name__, str(e))[:200]}


_PENDING = {}  # command_id -> {"session_id": sid, "text": text, "ts": ...}


def _submit(sid, text):
    """Schickt eine User-Nachricht an die Session (Agents-v2-API), ohne auf Antwort zu warten.
    503/429 ("outcome unknown"/busy) werden mit derselben command_id idempotent retried."""
    import uuid
    import urllib.error
    cmd = str(uuid.uuid4())
    body = {
        "type": "message", "command_id": cmd, "source": "agents_sdk",
        "message": {"role": "user", "parts": [{"type": "text", "text": text}]},
    }
    last_err = None
    for attempt in range(3):
        try:
            _v2("POST", "/sessions/%s/commands" % sid, body, timeout=30)
            return cmd
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = str((json.loads(e.read() or b"{}")).get("detail") or "")[:160]
            except Exception:
                pass
            last_err = "HTTP %s: %s" % (e.code, detail)
            if e.code in (429, 502, 503, 504):
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(last_err)
    raise RuntimeError("submit fehlgeschlagen: %s" % last_err)


def _collect(sid, cmd, wait):
    """Pollt die Session-Events bis turn_terminated des Commands oder wait Sekunden.
    Rueckgabe: (done, antwort, outcome). Streaming-Partialtexte werden auf die laengste Fassung kollabiert."""
    deadline = time.time() + max(0, min(int(wait), 600))
    last, outcome = "", None
    while True:
        try:
            evs = _events_all(sid)
        except Exception:
            evs = []
        best, out_texts, done = {}, [], False
        for ev in evs:
            p = ((ev or {}).get("event") or {}).get("payload") or {}
            if p.get("type") in ("history_entry_added", "history_entry_completed"):
                e = p.get("entry") or {}
                if e.get("type") == "message" and e.get("role") == "assistant":
                    tid = e.get("turnId")
                    if tid and tid != cmd:
                        continue  # nur der eigene Turn
                    t = _entry_text(e)
                    if t:
                        k = e.get("id") or tid
                        if k not in best or len(t) > len(best[k]):
                            best[k] = t
            elif p.get("type") == "turn_terminated":
                turn = p.get("turn") or {}
                if turn.get("id") == cmd:
                    outcome = (turn.get("termination") or {}).get("outcome")
                    for c in ((turn.get("termination") or {}).get("output") or []):
                        if isinstance(c, dict) and c.get("type") == "text":
                            out_texts.append(c.get("text", ""))
                    done = True
        texts = list(best.values()) + out_texts
        if texts:
            last = "\n".join(out_texts) if out_texts else max(texts, key=len)
        if done or time.time() >= deadline:
            return done, (last[-8000:] if last else ""), outcome
        time.sleep(3)


def agent_submit(text):
    """Schickt eine Nachricht an den Managed Agent, wartet aber nicht auf die Antwort.
    Der Command wird in _PENDING registriert; Antwort per GET /api/agent/pending abholbar."""
    if not _api_key():
        return {"live": False, "grund": "kein API-Key in Umgebung (MISTRAL_API_KEY/PROJECT_MISTRAL_API_KEY)"}, 200
    sid = _ensure_session()
    try:
        cmd = _submit(sid, text)
    except RuntimeError:
        # Session beschaeftigt/wedged -> frische Session anlegen und dort submittten
        sid = _new_session()
        cmd = _submit(sid, text)
    _PENDING[cmd] = {"session_id": sid, "text": text, "ts": time.time()}
    return {"live": True, "queued": True, "agent": AGENT_NAME, "session_id": sid,
            "conversation_id": sid, "command_id": cmd}, 200


def agent_pending(cmd, wait=25):
    """GET /api/agent/pending?command_id=...&wait=25 — Antwort-Status eines submitteten Commands."""
    now = time.time()
    for k in [k for k, v in _PENDING.items() if now - v.get("ts", 0) > 3600]:
        _PENDING.pop(k, None)  # nie abgeholte Commands nach 1 h verwerfen
    st = _PENDING.get(cmd)
    if not st:
        return {"live": True, "done": False, "lost": True, "antwort": ""}
    done, antwort, outcome = _collect(st["session_id"], cmd, wait)
    if done:
        _PENDING.pop(cmd, None)
        if not antwort:
            antwort = _session_preview(st["session_id"])  # Fallback: letzter Session-Preview
    return {"live": True, "done": done, "agent": AGENT_NAME, "session_id": st["session_id"],
            "conversation_id": st["session_id"], "antwort": antwort, "outcome": outcome}


def agent_send(text, wait=180, sync=False):
    """POST /api/agent/send — default asynchron (queued; Antwort via /api/agent/pending).
    Mit {"sync": true} blockierend bis wait Sekunden (Kompatibilitaet/CLI)."""
    try:
        if not sync:
            return agent_submit(text)
        if not _api_key():
            return {"live": False, "grund": "kein API-Key in Umgebung (MISTRAL_API_KEY/PROJECT_MISTRAL_API_KEY)"}, 200
        sid = _ensure_session()
        cmd = _submit(sid, text)
        done, antwort, outcome = _collect(sid, cmd, wait)
        if done and not antwort:
            antwort = _session_preview(sid)
        return {"live": True, "agent": AGENT_NAME, "session_id": sid, "conversation_id": sid,
                "antwort": antwort or "(noch keine Antwort nach %ds)" % int(wait), "timeout": not done,
                "outcome": outcome}, 200
    except Exception as e:
        return {"live": False, "grund": "%s: %s" % (type(e).__name__, str(e))[:200]}, 200


# ---------- TTL-Cache + Retry fuer Live-Endpunkte ----------

_CACHE = {}


def cached(key, ttl, fn):
    now = time.time()
    if len(_CACHE) > 400:  # Keys enthalten teils User-Querystrings -> Deckel gegen unbegrenztes Wachstum
        _CACHE.clear()
    if key in _CACHE and now - _CACHE[key][0] < ttl:
        return _CACHE[key][1]
    last = None
    for attempt in (1, 2):
        try:
            r = fn()
            _CACHE[key] = (now, r)
            return r
        except Exception as e:
            last = e
            time.sleep(0.8)
    raise last


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


def live_info(notes_lib=NOTES_LIBRARY_ID, apparat_lib=APPARAT_LIBRARY_ID):
    """Optional live: neueste Ablage-Doks + QV-Standzeile aus dem Apparat (Key nur aus Env)."""
    try:
        client, err = _client()
        if client is None:
            return {"live": False, "grund": err}

        async def _go():
            listing = await client.beta.libraries.documents.list_async(library_id=notes_lib, page_size=8)
            ablage = [{"name": d.name, "status": getattr(d, "processing_status", None)} for d in (listing.data or [])]
            qv = None
            try:
                ql = await client.beta.libraries.documents.list_async(library_id=apparat_lib, search="Quellenverzeichnis", page_size=5)
                qvdoc = next((d for d in (ql.data or []) if "Quellenverzeichnis" in (d.name or "")), None)
                if qvdoc is not None:
                    content = await client.beta.libraries.documents.text_content_async(library_id=apparat_lib, document_id=qvdoc.id)
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


def projects_list_live():
    r = libraries_live()
    r = dict(r)
    r["password_mode"] = bool(HUB_PASSWORD_HASH)
    return r


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
            return [{"id": d.id, "name": d.name, "status": getattr(d, "processing_status", None),
                     "created": str(getattr(d, "created_at", "") or "")} for d in (l.data or [])]

        return {"live": True, "lib": lib_id, "docs": asyncio.run(_go())}
    except Exception as e:
        return {"live": False, "grund": f"{type(e).__name__}: {e}"[:200], "docs": []}


def library_doc_text(lib_id, doc_id, offset=0, limit=4000):
    """Dokument-Text seitenweise (offset/limit) — kein Abschneiden mehr im UI."""
    try:
        client, err = _client()
        if client is None:
            return {"live": False, "grund": err}
        import asyncio

        async def _go():
            c = await client.beta.libraries.documents.text_content_async(library_id=lib_id, document_id=doc_id)
            t = getattr(c, "text", None) or str(c)
            off = max(0, int(offset))
            return {"text": t[off:off + limit], "total": len(t), "offset": off,
                    "has_more": off + limit < len(t)}

        r = {"live": True, "lib": lib_id, "id": doc_id}
        r.update(asyncio.run(_go()))
        return r
    except Exception as e:
        return {"live": False, "grund": f"{type(e).__name__}: {e}"[:200]}


def ablage_search(q, lib_id=NOTES_LIBRARY_ID):
    return library_docs(lib_id, q)


def ablage_doc(doc_id, offset=0, lib_id=NOTES_LIBRARY_ID):
    return library_doc_text(lib_id, doc_id, offset)


# ---------- Session-Auth (Passwort-Modus), Projekte, Agent-Workflows, Write-Through ----------

def _pass_hash(pw):
    return hashlib.sha256(("hub-v1:" + pw).encode("utf-8")).hexdigest()


def _is_loopback_host(h):
    return h in ("localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1")


def _login_locked(ip):
    now = time.time()
    with _SESSION_LOCK:
        fails = [t for t in _LOGIN_FAILS.get(ip, []) if now - t < 300]
        _LOGIN_FAILS[ip] = fails
        return len(fails) >= 5


def _note_login_fail(ip):
    with _SESSION_LOCK:
        _LOGIN_FAILS.setdefault(ip, []).append(time.time())


def _sweep_sessions():
    now = time.time()
    for sid in [s for s, v in _SESSIONS.items() if now - v["last"] > _SESSION_TTL]:
        _SESSIONS.pop(sid, None)


def _new_session(project=None):
    sid = secrets.token_urlsafe(32)
    with _SESSION_LOCK:
        _sweep_sessions()
        _SESSIONS[sid] = {"created": time.time(), "last": time.time(),
                          "csrf": secrets.token_urlsafe(24), "project": project}
    return sid


def _default_config(lib_id):
    return {"projekt": lib_id,
            "agenten": [{"name": "grammatik-statt-stil-research",
                         "deployment": "grammatik-statt-stil-research",
                         "workflow": "grammatik-statt-stil-research"}]}


def project_config(lib_id):
    """projekt.json aus der Library lesen (Cache liegt beim Aufrufer)."""
    try:
        client, err = _client()
        if client is None:
            return {"live": False, "grund": err, "config": _default_config(lib_id)}
        import asyncio

        async def _go():
            l = await client.beta.libraries.documents.list_async(library_id=lib_id, search="projekt.json", page_size=10)
            doc = next((d for d in (l.data or []) if (d.name or "").endswith("projekt.json")), None)
            if doc is None:
                return {"live": True, "config": _default_config(lib_id), "doc": None}
            c = await client.beta.libraries.documents.text_content_async(library_id=lib_id, document_id=doc.id)
            t = getattr(c, "text", None) or str(c)
            try:
                cfg = json.loads(t)
            except Exception:
                cfg = _default_config(lib_id)
            if not isinstance(cfg, dict):
                cfg = _default_config(lib_id)
            cfg.setdefault("projekt", lib_id)
            return {"live": True, "config": cfg, "doc": {"id": doc.id, "name": doc.name}}

        return asyncio.run(_go())
    except Exception as e:
        return {"live": False, "grund": f"{type(e).__name__}: {e}"[:200], "config": _default_config(lib_id)}


def project_create(name):
    """Neues Projekt = neue Mistral-Library + Seed-Dokumente (00-projektstand.md, projekt.json)."""
    client, err = _client()
    if client is None:
        return {"live": False, "grund": err}, 503
    if not name or len(name) > 120 or not _re.match(r"^[\w \-.,()äöüÄÖÜß&/]+$", name):
        return {"fehler": "ungueltiger Projektname (max 120 Zeichen)"}, 400
    import asyncio

    async def _go():
        from mistralai.client.models.file import File
        lib = await client.beta.libraries.create_async(
            name=name, description="Research-Hub Projekt — angelegt via Dashboard am " + time.strftime("%Y-%m-%d"))
        cfg = {"projekt": name, "angelegt": time.strftime("%Y-%m-%d"),
               "agenten": [{"name": "grammatik-statt-stil-research",
                            "deployment": "grammatik-statt-stil-research",
                            "workflow": "grammatik-statt-stil-research"}],
               "cron": "06:00,17:00 Europe/Vienna"}
        seed = [
            ("00-projektstand.md", "# Projektstand — " + name + "\n\nAngelegt am " + time.strftime("%Y-%m-%d") +
             " via Research Hub.\n\n- Agenten-Deployments, Cron etc.: siehe `projekt.json` in dieser Library.\n- Apparat-/Ablage-Dokumente werden hier abgelegt.\n"),
            ("projekt.json", json.dumps(cfg, ensure_ascii=False, indent=2)),
        ]
        docs = []
        for fn, content in seed:
            d = await client.beta.libraries.documents.upload_async(
                library_id=lib.id,
                file=File(file_name=fn, content=content.encode("utf-8"),
                          content_type="text/markdown" if fn.endswith(".md") else "application/json"))
            docs.append({"id": d.id, "name": d.name})
        return {"live": True, "id": lib.id, "name": lib.name, "seed": docs}

    try:
        return asyncio.run(_go()), 200
    except Exception as e:
        return {"live": False, "grund": f"{type(e).__name__}: {e}"[:200]}, 502


def apparat_qv(lib_id, offset=0, limit=8000):
    """A1: komplettes QV LIVE aus der Apparat-Library — Standzeile geparst + Text seitenweise."""
    try:
        client, err = _client()
        if client is None:
            return {"live": False, "grund": err}
        import asyncio

        async def _go():
            ql = await client.beta.libraries.documents.list_async(library_id=lib_id, search="Quellenverzeichnis", page_size=10)
            doc = next((d for d in (ql.data or []) if "Quellenverzeichnis" in (d.name or "")), None)
            if doc is None:
                return {"live": False, "grund": "kein 'Quellenverzeichnis'-Dokument in Library " + lib_id[:8]}
            c = await client.beta.libraries.documents.text_content_async(library_id=lib_id, document_id=doc.id)
            t = getattr(c, "text", None) or str(c)
            off = max(0, int(offset))
            return {"live": True, "lib": lib_id, "doc": {"id": doc.id, "name": doc.name},
                    "stand": parse_qv_standzeile(t[:6000]),
                    "text": t[off:off + limit], "total": len(t), "offset": off,
                    "has_more": off + limit < len(t)}

        return asyncio.run(_go())
    except Exception as e:
        return {"live": False, "grund": f"{type(e).__name__}: {e}"[:200]}


def wf_status(deployment):
    try:
        client, err = _client()
        if client is None:
            return {"live": False, "grund": err}
        import asyncio

        async def _go():
            d = await client.workflows.deployments.get_deployment_async(name=deployment)
            return {"live": True, "deployment": deployment,
                    "ready": getattr(d, "ready", None), "status": getattr(d, "status", None),
                    "deployed_revision": getattr(d, "deployed_revision", None),
                    "active_worker_count": getattr(d, "active_worker_count", None)}

        return asyncio.run(_go())
    except Exception as e:
        return {"live": False, "grund": f"{type(e).__name__}: {e}"[:200]}


def wf_runs(deployment, limit=20):
    try:
        client, err = _client()
        if client is None:
            return {"live": False, "grund": err}
        import asyncio

        async def _go():
            res = await client.workflows.runs.list_runs_async(deployment_name=deployment, page_size=limit,
                                                              sort_by="start_time", order="desc")
            runs = []
            for r in (getattr(res, "data", None) or []):
                runs.append({"id": getattr(r, "id", None) or getattr(r, "run_id", None),
                             "status": getattr(r, "status", None),
                             "start": str(getattr(r, "start_time", "") or ""),
                             "end": str(getattr(r, "end_time", "") or ""),
                             "workflow": getattr(r, "workflow_identifier", None)})
            return {"live": True, "deployment": deployment, "runs": runs}

        return asyncio.run(_go())
    except Exception as e:
        return {"live": False, "grund": f"{type(e).__name__}: {e}"[:200]}


def wf_run_logs(execution_id, limit=100, cursor=None):
    try:
        client, err = _client()
        if client is None:
            return {"live": False, "grund": err}
        import asyncio

        async def _go():
            kw = {"execution_id": execution_id, "limit": limit}
            if cursor:
                kw["cursor"] = cursor
            res = await client.workflows.executions.get_workflow_execution_logs_async(**kw)
            entries = []
            for e in (getattr(res, "data", None) or []):
                msg = getattr(e, "message", None)
                if msg is None:
                    msg = getattr(e, "content", None)
                entries.append({"ts": str(getattr(e, "timestamp", "") or ""),
                                "level": str(getattr(e, "level", "") or ""),
                                "message": str(msg or "")[:2000]})
            return {"live": True, "execution_id": execution_id, "entries": entries,
                    "next_cursor": getattr(res, "next_cursor", None) or getattr(res, "cursor", None)}

        return asyncio.run(_go())
    except Exception as e:
        return {"live": False, "grund": f"{type(e).__name__}: {e}"[:200]}


def wf_run(deployment, workflow, inp):
    try:
        client, err = _client()
        if client is None:
            return {"live": False, "grund": err}, 503
        import asyncio

        async def _go():
            r = await client.workflows.execute_workflow_async(
                workflow_identifier=workflow or deployment,
                deployment_name=deployment,
                input=inp if isinstance(inp, (dict, list)) else {"task": str(inp or "")})
            return {"live": True, "execution_id": getattr(r, "execution_id", None) or getattr(r, "id", None),
                    "status": getattr(r, "status", None), "deployment": deployment}

        return asyncio.run(_go()), 200
    except Exception as e:
        return {"live": False, "grund": f"{type(e).__name__}: {e}"[:200]}, 502


def wf_schedules():
    try:
        client, err = _client()
        if client is None:
            return {"live": False, "grund": err}
        import asyncio

        async def _go():
            res = await client.workflows.schedules.get_schedules_async()
            out = []
            for s in (getattr(res, "data", None) or []):
                out.append({"id": getattr(s, "id", None),
                            "name": getattr(s, "name", None) or getattr(s, "workflow_name", None),
                            "cron": getattr(s, "cron", None) or getattr(s, "cron_expression", None),
                            "status": getattr(s, "status", None),
                            "next_run": str(getattr(s, "next_run", "") or "")})
            return {"live": True, "schedules": out}

        return asyncio.run(_go())
    except Exception as e:
        return {"live": False, "grund": f"{type(e).__name__}: {e}"[:200]}


def note_write(lib_id, titel, text):
    """Write-Through: Markdown-Notiz in die aktive Projekt-Library (research_note_ablegen-Aequivalent)."""
    # Validierung VOR dem Client-Check: 400er muessen auch ohne API-Key sauber kommen
    titel = (titel or "").strip()
    if not titel or len(titel) > 200:
        return {"fehler": "titel fehlt/zu lang (max 200)"}, 400
    if not text or len(text) > 200000:
        return {"fehler": "text fehlt/zu lang (max 200 KB)"}, 400
    if not _re.match(r"^[0-9a-f\-]{36}$", lib_id or ""):
        return {"fehler": "ungueltige library_id"}, 400
    client, err = _client()
    if client is None:
        return {"live": False, "grund": err}, 503
    import asyncio

    async def _go():
        from mistralai.client.models.file import File
        fn = time.strftime("%Y-%m-%d") + "-" + _re.sub(r"[^\w\-]+", "-", titel.lower())[:60] + ".md"
        d = await client.beta.libraries.documents.upload_async(
            library_id=lib_id, file=File(file_name=fn, content=text.encode("utf-8"), content_type="text/markdown"))
        return {"ok": True, "live": True, "lib": lib_id, "id": d.id, "name": d.name}

    try:
        r = asyncio.run(_go())
    except Exception as e:
        return {"live": False, "grund": f"{type(e).__name__}: {e}"[:200]}, 502
    # Live-Caches der betroffenen Library invalidieren
    for k in [k for k in _CACHE if k.startswith(("ablage", "libdocs:" + lib_id, "libdoc:" + lib_id))]:
        _CACHE.pop(k, None)
    return r, 200




# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "ResearchHub/1.0"
    protocol_version = "HTTP/1.1"  # Keep-Alive (alle Antworten setzen Content-Length)

    def do_HEAD(self):
        self._head_only = True
        self.do_GET()
        self._head_only = False

    def log_message(self, fmt, *args):
        _access_log((fmt % args) if args else fmt)

    def _json(self, obj, status=200, download_name=None, extra_headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._sec()
        if extra_headers:
            for _k, _v in extra_headers:
                self.send_header(_k, _v)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        if download_name:
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % download_name)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not getattr(self, "_head_only", False):
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
        self._sec()
        self.send_header("Content-Type", ctype)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)

    def _download(self, text, name, ctype):
        body = text.encode("utf-8")
        self.send_response(200)
        self._sec()
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % name)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)

    def _sec(self):
        # Haertung: kein Framing, keine Referrer, keine Device-APIs.
        # CSP bewusst ohne default-src/script-src: die App ist self-contained mit einem
        # Inline-Skript (wuerde sonst geblockt); frame-ancestors/base-uri/form-action greifen trotzdem.
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    def _check_token(self, u, qs):
        # DNS-Rebinding-Guard: bei exponiertem Server (Token oder Passwort gesetzt) Host-Header pruefen
        if HUB_TOKEN or HUB_PASSWORD_HASH:
            host = (self.headers.get("Host") or "").split(":")[0].lower()
            if host and not _is_loopback_host(host) and host not in ALLOWED_HOSTS:
                self._json({"fehler": "bad host"}, 400)
                return False
        if u.path.startswith("/api/auth/"):
            return True  # login/logout/me ohne Session erreichbar (login hat eigenes Rate-Limit)
        if u.path.startswith(("/api/", "/data/")):
            tok = qs.get("token", [""])[0] or self.headers.get("X-Hub-Token", "")
            if HUB_TOKEN and hmac.compare_digest(tok.encode("utf-8"), HUB_TOKEN.encode("utf-8")):
                return True  # Token-Pfad (Back-Compat) bleibt immer zulaessig
            if HUB_PASSWORD_HASH:
                if self._session():
                    return True
                self._json({"fehler": "nicht angemeldet", "auth": True}, 401)
                return False
            if HUB_TOKEN:
                self._json({"fehler": "token fehlt/ungueltig"}, 403)
                return False
        return True

    def _session(self):
        ck = self.headers.get("Cookie", "")
        m = _re.search(r"(?:^|;\s*)hub_sid=([A-Za-z0-9_\-]{16,})", ck)
        if not m:
            return None
        sid = m.group(1)
        with _SESSION_LOCK:
            _sweep_sessions()
            s = _SESSIONS.get(sid)
            if s:
                s["last"] = time.time()
        return (sid, s) if s else None

    def _cookie(self, sid, max_age):
        # Secure nur hinter TLS-Terminierung (nginx setzt X-Forwarded-Proto); localhost bleibt http
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto", "") == "https" else ""
        return "hub_sid=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d%s" % (sid, max_age, secure)

    def _client_ip(self):
        xff = self.headers.get("X-Forwarded-For", "")
        return xff.split(",")[0].strip() if xff else (self.client_address[0] if self.client_address else "")

    def _active_lib(self):
        sess = self._session()
        if sess and sess[1].get("project"):
            return sess[1]["project"]
        return os.environ.get("PROJECT_LIBRARY_ID") or NOTES_LIBRARY_ID

    def _active_apparat_lib(self, qs):
        lib = qs.get("lib", [""])[0].strip()
        if lib:
            return lib
        try:
            cfg = cached("projcfg:" + self._active_lib(), 30, lambda: project_config(self._active_lib()))
            al = (cfg.get("config") or {}).get("apparat_library")
        except Exception:
            al = None
        return al or os.environ.get("APPARAT_LIBRARY_ID") or APPARAT_LIBRARY_ID

    def _default_deployment(self):
        try:
            cfg = cached("projcfg:" + self._active_lib(), 30, lambda: project_config(self._active_lib()))
            agents = (cfg.get("config") or {}).get("agenten") or []
            if agents and isinstance(agents, list):
                return agents[0].get("deployment") or "grammatik-statt-stil-research"
        except Exception:
            pass
        return "grammatik-statt-stil-research"

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if not self._check_token(u, qs):
            return
        if u.path in ("/", "/index.html"):
            return self._file(BASE / "index.html")
        if u.path.startswith("/data/"):
            rel = u.path[len("/data/"):]
            if ".." in rel:
                return self._json({"fehler": "bad path"}, 400)
            return self._file(DATA / rel)
        rel = u.path.lstrip("/")
        if rel and ".." not in rel and not any(p.startswith(".") for p in rel.split("/")):
            cand = (BASE / rel).resolve()
            if (str(cand).startswith(str(BASE) + os.sep) and cand.is_file()
                    and cand.suffix.lower() in STATIC_SUFFIXES):
                return self._file(cand)
        if u.path.startswith(("/api/qv", "/api/quellen", "/api/pruef", "/api/stats")):
            ensure_fresh()  # project.json geaendert / Schema gewechselt? -> DB neu seeden
        if u.path == "/api/stats":
            d = load_project()
            k = d["kstand"]["K"]
            n = d["kstand"]["positionen"]
            g = d["kstand"]["gruppen_enden"]
            return self._json({
                "meta": d["meta"], "kstand": d["kstand"],
                "vt_quote": round((k["K1"] + k["K2"]) / n * 100, 1),
                "gruppen": {"enden": g, "avg": round(n / len(g), 1)},
                "extra": stats_extra(),
            })
        if u.path == "/api/meta":
            # Aenderungs-Erkennung fuer das Dashboard: project.json-Mtime + DB-Stand + letzter Import
            try:
                mt = str(os.path.getmtime(DATA / "project.json"))
            except OSError:
                mt = ""
            con = db()
            try:
                n = con.execute("SELECT COUNT(*) c FROM pos").fetchone()["c"]
                li = con.execute("SELECT value FROM meta WHERE key='last_import'").fetchone()
                sv = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            finally:
                con.close()
            return self._json({"project_mtime": mt, "pos_count": n,
                               "last_import": (li["value"] if li else None),
                               "schema_version": (sv["value"] if sv else None)})
        if u.path == "/api/verzeichnis":
            return self._json(load_project()["verzeichnis"])
        if u.path == "/api/glossar":
            return self._json(load_project()["glossar"])
        if u.path == "/api/historie":
            return self._json({"historie": load_project().get("historie", [])})
        if u.path == "/api/messages":
            return self._json(load_outbox())
        if u.path == "/api/auth/me":
            sess = self._session()
            return self._json({"authenticated": bool(sess),
                               "password_mode": bool(HUB_PASSWORD_HASH),
                               "token_mode": bool(HUB_TOKEN),
                               "csrf": sess[1]["csrf"] if sess else None,
                               "project": self._active_lib()})
        if u.path == "/api/live":
            lib = self._active_lib()
            alib = self._active_apparat_lib(qs)
            return self._json(cached("live:%s:%s" % (lib, alib), 20, lambda: live_info(lib, alib)))
        if u.path == "/api/ablage":
            q = qs.get("q", [""])[0]
            lib = self._active_lib()
            return self._json(cached("ablage:%s:%s" % (lib, q), 20, lambda: ablage_search(q, lib)))
        if u.path == "/api/ablage/doc":
            did = qs.get("id", [""])[0]
            off = _qint(qs, "offset", 0, 0, 10**7)
            lib = self._active_lib()
            return self._json(cached("ablage_doc:%s:%s:%d" % (lib, did, off), 60, lambda: ablage_doc(did, off, lib)))
        if u.path == "/api/projects":
            r = dict(cached("projects", 30, projects_list_live))
            r["active"] = self._active_lib()
            return self._json(r)
        if u.path == "/api/project":
            lib = self._active_lib()
            return self._json(cached("projcfg:" + lib, 30, lambda: project_config(lib)))
        if u.path == "/api/apparat/qv":
            alib = self._active_apparat_lib(qs)
            off = _qint(qs, "offset", 0, 0, 10**7)
            lim = _qint(qs, "limit", 8000, 1, 50000)
            return self._json(cached("apparatqv:%s:%d" % (alib, off), 60, lambda: apparat_qv(alib, off, lim)))
        if u.path == "/api/wf/status":
            dep = qs.get("deployment", [""])[0] or self._default_deployment()
            return self._json(cached("wfstatus:" + dep, 10, lambda: wf_status(dep)))
        if u.path == "/api/wf/runs":
            dep = qs.get("deployment", [""])[0] or self._default_deployment()
            return self._json(cached("wfruns:%s" % dep, 10, lambda: wf_runs(dep, _qint(qs, "limit", 20, 1, 100))))
        if u.path.startswith("/api/wf/runs/") and u.path.endswith("/logs"):
            eid = u.path[len("/api/wf/runs/"):-len("/logs")]
            cur = qs.get("cursor", [None])[0] or None
            return self._json(cached("wflogs:%s:%s" % (eid, cur or ""), 5,
                                     lambda: wf_run_logs(eid, _qint(qs, "limit", 100, 1, 500), cur)))
        if u.path == "/api/wf/schedules":
            return self._json(cached("wfsched", 60, wf_schedules))
        if u.path == "/api/qv":
            return self._json(qv_search(qs.get("q", [""])[0], qs.get("k", [""])[0], qs.get("rel", [""])[0],
                                         _qint(qs, "limit", 200), _qint(qs, "offset", 0, 0, 10**7)))
        if u.path == "/api/qv/aenderungen":
            return self._json(qv_aenderungen())
        if u.path == "/api/qv/export":
            fmt = qs.get("format", ["json"])[0]
            if fmt == "ris":
                return self._download(to_ris(_all_rows()), "quellenverzeichnis.ris", "application/x-research-info-systems")
            if fmt == "bib":
                return self._download(to_bib(_all_rows()), "quellenverzeichnis.bib", "application/x-bibtex")
            return self._json(qv_export(), download_name="qv-export-%s.json" % time.strftime("%Y%m%d"))
        if u.path == "/api/qv/snapshots":
            return self._json(list_snapshots())
        if u.path == "/api/qv/diff":
            obj, st = qv_diff(qs.get("a", [""])[0], qs.get("b", [""])[0])
            return self._json(obj, st)
        if u.path == "/api/dupes":
            return self._json(qv_dupes())
        if u.path == "/api/pruef":
            return self._json(pruef_list())
        if u.path == "/api/coverage":
            return self._json(cached("coverage", 300, coverage))
        if u.path == "/api/agent/history":
            sid = qs.get("session_id", [""])[0] or "default"
            return self._json(cached("agent_history:" + sid, 4, lambda: agent_history(None if sid == "default" else sid)))
        if u.path == "/api/agent/sessions":
            return self._json(cached("agent_sessions", 10, agent_sessions))
        if u.path == "/api/agent/pending":
            return self._json(agent_pending(qs.get("command_id", [""])[0], _qint(qs, "wait", 25, 0, 60)))
        if u.path == "/api/libraries":
            return self._json(cached("libraries", 30, libraries_live))
        if u.path == "/api/library/docs":
            lib = qs.get("lib", [""])[0]
            q = qs.get("q", [""])[0]
            return self._json(cached("libdocs:%s:%s" % (lib, q), 30, lambda: library_docs(lib, q)))
        if u.path == "/api/library/doc":
            lib = qs.get("lib", [""])[0]
            did = qs.get("id", [""])[0]
            off = _qint(qs, "offset", 0, 0, 10**7)
            return self._json(cached("libdoc:%s:%s:%d" % (lib, did, off), 60,
                                     lambda: library_doc_text(lib, did, off)))
        if u.path == "/api/quellen":
            return self._json(qv_quellen(qs.get("q", [""])[0]))
        if u.path == "/api/templates":
            return self._json(load_templates())
        return self._json({"fehler": "not found"}, 404)

    def do_POST(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if not self._check_token(u, qs):
            return
        # CSRF: im Passwort-Modus brauchen alle schreibenden /api/*-Calls den Session-CSRF-Token
        if HUB_PASSWORD_HASH and u.path.startswith("/api/") and u.path != "/api/auth/login":
            sess = self._session()
            csrf = self.headers.get("X-Hub-CSRF", "")
            if not sess or not hmac.compare_digest(csrf.encode("utf-8"), sess[1]["csrf"].encode("utf-8")):
                return self._json({"fehler": "CSRF-Token fehlt/ungueltig"}, 403)
        if u.path in ("/api/message", "/api/qv/hebung", "/api/render", "/api/diff", "/api/agent/send",
                      "/api/pruef", "/api/qv/edit", "/api/import", "/api/outbox/clear", "/api/agent/reset",
                      "/api/agent/stop", "/api/agent/archive",
                      "/api/auth/login", "/api/auth/logout", "/api/projects/select", "/api/projects/create",
                      "/api/wf/run", "/api/notes"):
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > 1000000:
                    return self._json({"fehler": "Body zu gross (max 1 MB)"}, 413)
                payload = json.loads(self.rfile.read(length) or b"{}")
                if u.path == "/api/auth/login":
                    ip = self._client_ip()
                    if _login_locked(ip):
                        return self._json({"fehler": "zu viele Fehlversuche - kurz gesperrt"}, 429)
                    if not HUB_PASSWORD_HASH:
                        return self._json({"fehler": "Passwort-Login nicht konfiguriert (nur Token-Modus aktiv)"}, 400)
                    pw = str(payload.get("password", ""))
                    # Passwort-Klartext wird nur zum Hashing genutzt und nie geloggt/gespeichert
                    if not hmac.compare_digest(_pass_hash(pw).encode("utf-8"), HUB_PASSWORD_HASH.encode("utf-8")):
                        _note_login_fail(ip)
                        return self._json({"fehler": "falsches Passwort"}, 401)
                    sid = _new_session(project=os.environ.get("PROJECT_LIBRARY_ID") or None)
                    return self._json({"ok": True, "authenticated": True},
                                      200, extra_headers=[("Set-Cookie", self._cookie(sid, _SESSION_TTL))])
                if u.path == "/api/auth/logout":
                    sess = self._session()
                    if sess:
                        with _SESSION_LOCK:
                            _SESSIONS.pop(sess[0], None)
                    return self._json({"ok": True, "authenticated": False},
                                      200, extra_headers=[("Set-Cookie", self._cookie("", 0))])
                if u.path == "/api/projects/select":
                    lib_id = str(payload.get("library_id", "")).strip()
                    if not _re.match(r"^[0-9a-f\-]{36}$", lib_id):
                        return self._json({"fehler": "ungueltige library_id"}, 400)
                    sess = self._session()
                    if not sess:
                        return self._json({"fehler": "nicht angemeldet"}, 401)
                    live = libraries_live()
                    if live.get("live") and live.get("libs") and not any(l.get("id") == lib_id for l in live["libs"]):
                        return self._json({"fehler": "Library nicht gefunden/kein Zugriff"}, 404)
                    with _SESSION_LOCK:
                        sess[1]["project"] = lib_id
                    for k in [k for k in _CACHE if k.startswith(("ablage", "apparatqv", "projcfg", "live:"))]:
                        _CACHE.pop(k, None)
                    return self._json({"ok": True, "project": lib_id})
                if u.path == "/api/projects/create":
                    obj, st = project_create(str(payload.get("name", "")).strip())
                    if st == 200:
                        _CACHE.pop("projects", None)
                    return self._json(obj, st)
                if u.path == "/api/wf/run":
                    dep = str(payload.get("deployment", "")).strip() or self._default_deployment()
                    wf = str(payload.get("workflow", "")).strip() or dep
                    obj, st = wf_run(dep, wf, payload.get("input"))
                    if st == 200:
                        _CACHE.pop("wfruns:" + dep, None)
                    return self._json(obj, st)
                if u.path == "/api/notes":
                    lib = self._active_lib()
                    obj, st = note_write(lib, str(payload.get("titel", "")), str(payload.get("text", "")))
                    return self._json(obj, st)
                if u.path == "/api/message":
                    text = str(payload.get("text", "")).strip()
                    if not text:
                        return self._json({"fehler": "text fehlt"}, 400)
                    role = str(payload.get("role", "user"))
                    if role not in ("user", "agent", "system"):
                        role = "user"
                    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
                    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "text": text, "role": role, "meta": meta}
                    with open(DATA / "outbox.jsonl", "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    return self._json(entry)
                if u.path == "/api/outbox/clear":
                    n = len(load_outbox())
                    open(DATA / "outbox.jsonl", "w", encoding="utf-8").close()
                    return self._json({"ok": True, "geleert": n})
                if u.path == "/api/agent/send":
                    text = str(payload.get("text", "")).strip()
                    if not text:
                        return self._json({"fehler": "text fehlt"}, 400)
                    try:
                        wait = int(payload.get("wait", 180))
                    except (TypeError, ValueError):
                        wait = 180
                    obj, status = agent_send(text, wait=wait, sync=bool(payload.get("sync")))
                    return self._json(obj, status)
                if u.path == "/api/agent/stop":
                    obj, status = agent_stop(str(payload.get("session_id", "")))
                    return self._json(obj, status)
                if u.path == "/api/agent/archive":
                    obj, status = agent_archive(str(payload.get("session_id", "")),
                                               archived=bool(payload.get("archived", True)))
                    return self._json(obj, status)
                if u.path == "/api/agent/reset":
                    try:
                        CONV_FILE.unlink()
                    except OSError:
                        pass
                    _CACHE.pop("agent_history", None)
                    return self._json({"ok": True, "hinweis": "Conversation-ID geloescht — naechste Nachricht startet eine neue Session"})
                if u.path == "/api/pruef":
                    obj, status = pruef_upsert(payload)
                    return self._json(obj, status)
                if u.path == "/api/qv/edit":
                    obj, status = qv_edit(payload)
                    return self._json(obj, status)
                if u.path == "/api/import":
                    obj, status = run_import(auto=bool(payload.get("auto")))
                    return self._json(obj, status)
                if u.path == "/api/render":
                    obj, status = render_template(payload)
                    return self._json(obj, status)
                if u.path == "/api/diff":
                    obj, status = diff_lines(payload)
                    return self._json(obj, status)
                obj, status = qv_heben(payload)
                return self._json(obj, status)
            except Exception as e:
                import traceback as _tb
                with open(DATA / "debug-trace.log", "a", encoding="utf-8") as _f:
                    _f.write("=== POST %s\n%s\n" % (u.path, _tb.format_exc()))
                return self._json({"fehler": str(e)[:200]}, 400)
        return self._json({"fehler": "not found"}, 404)


def main():
    global HUB_TOKEN, HUB_PASSWORD_HASH, ALLOWED_HOSTS, LOG_ACCESS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--token", default=os.environ.get("DASHBOARD_TOKEN", ""),
                    help="optional: Token schuetzt /api/* und /data/* (?token=... oder Header X-Hub-Token)")
    ap.add_argument("--log", action="store_true", help="Access-Log nach data/hub.log schreiben")
    ap.add_argument("--password", default=os.environ.get("DASHBOARD_PASSWORD", ""),
                    help="optional: Login-Passwort schuetzt /api/* via Session-Cookie (HttpOnly, SameSite=Strict) + CSRF; "
                         "Klartext bleibt im Prozess (nur sha256-Hash im Speicher), wird nie geloggt")
    ap.add_argument("--allowed-hosts", default=os.environ.get("DASHBOARD_ALLOWED_HOSTS", ""),
                    help="komma-getrennte zusaetzliche Host-Header (DNS-Rebinding-Guard), z. B. dashboard.deinedomain.at")
    args = ap.parse_args()
    HUB_TOKEN = args.token or None
    HUB_PASSWORD_HASH = _pass_hash(args.password) if args.password else None
    ALLOWED_HOSTS.update(h.strip().lower() for h in args.allowed_hosts.split(",") if h.strip())
    LOG_ACCESS = args.log
    _loopback = args.host in ("127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1")
    if not _loopback and not HUB_TOKEN and not HUB_PASSWORD_HASH and not TRUST_GATEWAY:
        print("FEHLER (fail-closed): --host %s ohne --token/DASHBOARD_TOKEN und ohne --password/DASHBOARD_PASSWORD nicht erlaubt - "
              "/api/* und /data/* waeren sonst ohne Auth im Netz sichtbar. "
              "Abhilfe: --token oder --password setzen (oder Env DASHBOARD_TOKEN/DASHBOARD_PASSWORD) oder Default 127.0.0.1 nutzen."
              % args.host, file=sys.stderr)
        sys.exit(2)
    if not _loopback and not HUB_TOKEN and not HUB_PASSWORD_HASH and TRUST_GATEWAY:
        print("HINWEIS: bind an %s ohne Token/Passwort (DASHBOARD_TRUST_GATEWAY_AUTH=1) - nur hinter authentifiziertem Gateway betreiben (Studio-App, siehe studio-app/)"
              % args.host, file=sys.stderr)
    DATA.mkdir(exist_ok=True)
    fts = init_db()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    fts_label = "ja" if fts else "nein (LIKE-Fallback)"
    tok = ("; Token via ?token=<token>" if HUB_TOKEN else "") + ("; Session-Login (Cookie+CSRF)" if HUB_PASSWORD_HASH else "")
    print(f"Research Hub: http://{args.host}:{args.port}/  (Default nur Loopback; FTS5={fts_label}{tok}; Ctrl+C beendet)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
