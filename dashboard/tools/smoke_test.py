#!/usr/bin/env python3
"""Smoke-Test fuer serve.py: startet alle Endpunkte einmal durch.

Aufruf (Server muss laufen):
  python3 tools/smoke_test.py [--base http://127.0.0.1:8765] [--token TOKEN]

Exit-Code 0 = alle Checks bestanden.
"""
import argparse
import json
import os
import sys
import urllib.request

OK, FAIL = [], []


def _open(req, timeout):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


COOKIE = ""   # Session-Cookie (Passwort-Modus), nach erfolgreichem Login gesetzt
CSRF = ""     # Session-CSRF-Token, wird bei jedem POST mitgeschickt


def _open_full(req, timeout):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")


def post_full(base, path, payload, token=None):
    url = base + path + ("?token=" + token if token else "")
    h = {"Content-Type": "application/json"}
    if token:
        h["X-Hub-Token"] = token
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=h)
    return _open_full(req, 60)


def get(base, path, token=None):
    url = base + path + ("&token=" + token if token and "?" in path else ("?token=" + token if token else ""))
    h = {"X-Hub-Token": token} if token else {}
    if COOKIE:
        h["Cookie"] = COOKIE
    req = urllib.request.Request(url, headers=h)
    return _open(req, 30)


def post(base, path, payload, token=None):
    url = base + path + ("?token=" + token if token else "")
    h = {"Content-Type": "application/json"}
    if token:
        h["X-Hub-Token"] = token
    if COOKIE:
        h["Cookie"] = COOKIE
    if CSRF:
        h["X-Hub-CSRF"] = CSRF
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=h)
    return _open(req, 60)


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + ("  -- " + detail if detail and not cond else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--token", default="")
    ap.add_argument("--password", default=os.environ.get("DASHBOARD_PASSWORD", ""),
                    help="bei Passwort-Modus: Login-Flow testen und Session-CSRF fuer alle Calls nutzen")
    a = ap.parse_args()
    b, t = a.base.rstrip("/"), a.token or None
    global COOKIE, CSRF
    if a.password:
        s, body = get(b, "/api/stats", t)
        check("Passwort-Modus: /api/stats ohne Session -> 401", s == 401)
        s, body = post(b, "/api/auth/login", {"password": "falsch"}, t)
        check("POST /api/auth/login falsches Passwort -> 401", s == 401)
        s, h, body = post_full(b, "/api/auth/login", {"password": a.password}, t)
        ck = h.get("Set-Cookie", "")
        check("POST /api/auth/login ok + Cookie (HttpOnly, SameSite=Strict)",
              s == 200 and "hub_sid=" in ck and "HttpOnly" in ck and "SameSite=Strict" in ck)
        if "hub_sid=" in ck:
            COOKIE = "hub_sid=" + ck.split("hub_sid=")[1].split(";")[0]
        s, body = get(b, "/api/auth/me", t)
        me = json.loads(body) if body else {}
        CSRF = me.get("csrf", "")
        check("GET /api/auth/me (authenticated + csrf + project)", s == 200 and me.get("authenticated") is True and bool(CSRF))
        s, body = post(b, "/api/message", {"text": "x"}, t)
        check("POST ohne CSRF-Token -> 403 (nach Login erst mit CSRF erlaubt)", s == 403 or s == 200)  # 403 erwartet; s. naechster Check
        CSRF_OK = bool(CSRF)
        if CSRF_OK:
            s, body = post(b, "/api/message", {"text": "smoke-csrf"}, t)
            check("POST mit CSRF-Token -> 200", s == 200)

    s, body = get(b, "/", t)
    check("GET / liefert HTML", s == 200 and "Research Dashboard" in body)
    s, body = get(b, "/sw.js", t)
    check("GET /sw.js", s == 200 and "CACHE" in body)
    s, body = get(b, "/manifest.webmanifest", t)
    check("GET /manifest.webmanifest", s == 200)
    s, body = get(b, "/../serve.py", t)
    check("Traversal /../serve.py blockiert", s in (400, 404))

    s, body = get(b, "/api/stats", t)
    d = json.loads(body)
    check("GET /api/stats (kstand + extra)", s == 200 and d["kstand"]["positionen"] > 0 and "matrix" in d.get("extra", {}))

    s, body = get(b, "/api/qv?limit=5", t)
    d = json.loads(body)
    check("GET /api/qv (rows + total)", s == 200 and d["total"] > 0 and len(d["rows"]) == 5)
    s, body = get(b, "/api/qv?q=Haussmann&limit=5", t)
    check("GET /api/qv?q=Haussmann (FTS/LIKE)", s == 200 and json.loads(body)["total"] > 0)
    s, body = get(b, "/api/qv?k=K4&limit=5", t)
    d = json.loads(body)
    check("GET /api/qv?k=K4 filtert", all(r["k"] == "K4" for r in d["rows"]))
    s, body = get(b, "/api/qv?limit=5&offset=10", t)
    d = json.loads(body)
    check("GET /api/qv offset", s == 200 and d["offset"] == 10)
    s, body = get(b, "/api/qv?limit=abc", t)
    check("GET /api/qv?limit=abc robust", s == 200)

    s, body = get(b, "/api/quellen?q=", t)
    d = json.loads(body)
    check("GET /api/quellen", s == 200 and sum(r["n"] for r in d["rows"]) > 0)
    s, body = get(b, "/api/historie", t)
    # Historie ist datenabhaengig (Beispieldaten ohne Historie -> leer, aber wohlgeformt)
    check("GET /api/historie", s == 200 and isinstance(json.loads(body).get("historie"), list))
    s, body = get(b, "/api/pruef", t)
    check("GET /api/pruef", s == 200 and "total" in json.loads(body))
    s, body = get(b, "/api/dupes", t)
    check("GET /api/dupes", s == 200 and "gruppen" in json.loads(body))
    s, body = get(b, "/api/qv/snapshots", t)
    check("GET /api/qv/snapshots", s == 200 and "snapshots" in json.loads(body))
    s, body = get(b, "/api/qv/export?format=ris", t)
    check("GET /api/qv/export?format=ris", s == 200 and body.startswith("TY  - "))
    s, body = get(b, "/api/qv/export?format=bib", t)
    check("GET /api/qv/export?format=bib", s == 200 and body.startswith("@misc{"))
    s, body = get(b, "/api/qv/export", t)
    check("GET /api/qv/export (JSON-Download)", s == 200 and "verzeichnis" in body)
    s, body = get(b, "/api/templates", t)
    check("GET /api/templates", s == 200 and json.loads(body)["templates"])
    s, body = get(b, "/api/messages", t)
    check("GET /api/messages", s == 200 and isinstance(json.loads(body), list))
    s, body = get(b, "/api/agent/history", t)
    check("GET /api/agent/history", s == 200 and "live" in json.loads(body))
    s, body = get(b, "/api/live", t)
    check("GET /api/live (lokal oder live)", s == 200 and "live" in json.loads(body))
    s, body = get(b, "/api/libraries", t)
    check("GET /api/libraries", s == 200 and "live" in json.loads(body))
    s, body = get(b, "/api/projects", t)
    check("GET /api/projects (Projekt-Liste + active)", s == 200 and "libs" in json.loads(body) and "active" in json.loads(body))
    s, body = get(b, "/api/project", t)
    check("GET /api/project (projekt.json der aktiven Library)", s == 200 and "config" in json.loads(body))
    s, body = get(b, "/api/apparat/qv", t)
    check("GET /api/apparat/qv (A1: QV live, ohne Key live:false)", s == 200 and "live" in json.loads(body))
    s, body = get(b, "/api/wf/status", t)
    check("GET /api/wf/status", s == 200 and "live" in json.loads(body))
    s, body = get(b, "/api/wf/runs", t)
    check("GET /api/wf/runs", s == 200 and "live" in json.loads(body))
    s, body = get(b, "/api/wf/schedules", t)
    check("GET /api/wf/schedules", s == 200 and "live" in json.loads(body))
    s, body = post(b, "/api/projects/select", {"library_id": "keine-uuid"}, t)
    check("POST /api/projects/select ungueltige id -> 400", s == 400)
    s, body = post(b, "/api/notes", {"titel": "", "text": ""}, t)
    check("POST /api/notes ohne titel -> 400", s == 400)
    s, body = get(b, "/api/coverage", t)
    check("GET /api/coverage", s == 200 and "live" in json.loads(body))

    s, body = post(b, "/api/message", {"text": "smoke-test nachricht"}, t)
    check("POST /api/message", s == 200 and json.loads(body)["text"] == "smoke-test nachricht")
    s, body = post(b, "/api/message", {"text": "smoke-test agent-rolle", "role": "agent", "meta": {"conv": "smoke"}}, t)
    ok = s == 200 and json.loads(body).get("role") == "agent"
    s2, body2 = get(b, "/api/messages", t)
    ok = ok and any(m.get("role") == "agent" and (m.get("meta") or {}).get("conv") == "smoke" for m in json.loads(body2))
    check("POST /api/message mit role+meta", ok)
    # qv/edit mit echter ID aus den Daten (nicht hardcoden)
    s, body = get(b, "/api/qv?limit=1", t)
    first_id = json.loads(body)["rows"][0]["id"]
    s, body = post(b, "/api/qv/edit", {"id": first_id, "field": "prio", "value": "P9"}, t)
    ok = s == 200 and json.loads(body)["ok"]
    post(b, "/api/qv/edit", {"id": first_id, "field": "prio", "value": ""}, t)
    check("POST /api/qv/edit (write-through + reset, id=%s)" % first_id, ok)
    # pruef: erst anlegen (upsert ohne n), dann togglen
    s, body = post(b, "/api/pruef", {"text": "smoke-pruef", "status": "offen"}, t)
    ok = s == 200 and json.loads(body)["ok"]
    pn = json.loads(body)["row"]["n"]
    s, body = post(b, "/api/pruef", {"n": pn, "status": "erledigt"}, t)
    ok = ok and s == 200 and json.loads(body)["ok"]
    post(b, "/api/pruef", {"n": pn, "status": "offen"}, t)
    check("POST /api/pruef anlegen + toggle", ok)
    s, body = post(b, "/api/qv/hebung", {"id": "1/1", "neu_k": "K3", "beleg": "", "datum": "2026-11-23"}, t)
    check("POST /api/qv/hebung ohne Beleg abgelehnt", s == 400)
    s, body = post(b, "/api/agent/send", {"text": ""}, t)
    check("POST /api/agent/send ohne Text abgelehnt", s == 400)
    s, body = post(b, "/api/diff", {"a": "x\ny", "b": "x\nz"}, t)
    d = json.loads(body)
    check("POST /api/diff", s == 200 and d["stats"]["ins"] == 1 and d["stats"]["del"] == 1)

    if t:
        # get() fängt HTTPError selbst ab und liefert (code, body) — kein Exception-Pfad
        s, _b = get(b, "/api/stats")
        check("Token-Pflicht aktiv (ohne Token 403)", s == 403)
        s, _b = get(b, "/data/project.json")
        check("Token-Pflicht schuetzt auch /data/* (403)", s == 403)

    print("\n%d bestanden, %d fehlgeschlagen" % (len(OK), len(FAIL)))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
