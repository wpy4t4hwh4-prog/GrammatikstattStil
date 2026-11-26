#!/usr/bin/env python3
"""Importiert die Arbeitsdokumente aus der Apparat-Bibliothek (Mistral Library)
in dashboard/data/project.json, damit Verzeichnis- und Quellen-Tab den vollen
Bestand zeigen.

Quellen (live, Key nur aus Umgebung MISTRAL_API_KEY / PROJECT_MISTRAL_API_KEY):
  - Apparat_Quellenverzeichnis.md  -> Positionen (Gruppe/Nr., Zitat, Stufe, Vermerk)
  - Apparat_Volltext-Inventar.md   -> K-Klassifikation je Position (K1-K5 / Vermerk)

Aufruf (mit dem forschungsagent-Venv, das mistralai installiert hat):
  MISTRAL_API_KEY=... /Pfad/zum/.venv/bin/python tools/import_apparat.py

Danach qv.db loeschen und serve.py neu starten, damit die SQLite-DB neu
aufgebaut wird:
  rm data/qv.db && python3 serve.py --port 8765

Ohne Key: --from-files /tmp/apparat_qv.md /tmp/apparat_vt.md
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"

APPARAT_LIBRARY_ID = "01a1c18b-fe93-75a4-8c2b-871c9f112cd9"  # Apparat-Bibliothek
DOC_QV = "6c771308-6024-492a-94c2-195bf02238da"  # Apparat_Quellenverzeichnis.md
DOC_VT = "5ed30e1e-1a84-4ed4-b092-0e7c36b420da"  # Apparat_Volltext-Inventar.md

RE_SECTION = re.compile(r"^## (\d+)\.\s")
RE_ANY_H2 = re.compile(r"^## ")
RE_SUBGROUP = re.compile(r"^### ")
RE_STUFE = re.compile(r"^\*\*Stufe ([A-Z])\b")
RE_ENTRY = re.compile(r"^(\d{1,3})\.\s+(.+)$")
RE_STUFE_INLINE = re.compile(r"^Stufe ([A-Z])[;,.]\s*")
RE_URL = re.compile(r"URL:\s*(\S+)")
RE_GRUPPE = re.compile(r"^### Gruppe (\d+) — .*?\((\d+) Einträge\)")
RE_KLINE = re.compile(r"^- \*\*(K[1-5]|Vermerk) \((\d+)\):\*\*\s*(.*)$")
RE_NUMSEG = re.compile(r"^(?:Nr\.?\s*)?(?:\d{1,3}\s*/\s*)?(\d{1,3})(?!\.)(?:\s*[–-]\s*(\d{1,3}))?")


def mask_parens(s):
    """Klammer-Inhalte maskieren (Klammerzeichen selbst bleiben als Trenner erhalten)."""
    out, depth = [], 0
    for ch in s:
        if ch in "([":
            depth += 1
            out.append(ch)
        elif ch in ")]":
            depth = max(0, depth - 1)
            out.append(ch)
        elif depth > 0:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


RE_REF = re.compile(r"(?:Nr\.?\s*|(?:^|[;,]\s+|\)\.?\s+|und\s+))(\d{1,3})(?![\d./])(?:\s*[–-]\s*(\d{1,3}))?(?=\s|$)")


def fetch_docs():
    key = os.environ.get("PROJECT_MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY")
    if not key:
        sys.exit("kein API-Key in Umgebung (MISTRAL_API_KEY/PROJECT_MISTRAL_API_KEY) "
                 "oder --from-files nutzen")
    import asyncio
    from mistralai.workflows.client import get_mistral_client

    async def go():
        c = get_mistral_client(api_key=key)
        # Dokumente per Name aufloesen (IDs aendern sich bei Re-Uploads); Fallback: alte IDs
        docs = {}
        try:
            lst = await c.beta.libraries.documents.list_async(library_id=APPARAT_LIBRARY_ID, page_size=100)
            for d in (getattr(lst, "data", None) or []):
                nm = (getattr(d, "name", "") or "").lower()
                ca = str(getattr(d, "created_at", "") or "")
                if "quellenverzeichnis" in nm:
                    key_ = "qv"
                elif "volltext-inventar" in nm or "volltext_inventar" in nm:
                    key_ = "vt"
                else:
                    continue
                prev = docs.get(key_)
                if prev is None or ca > prev[1]:
                    docs[key_] = (d.id, ca)
        except Exception:
            pass
        out = {}
        for name, doc_id in (("qv", DOC_QV), ("vt", DOC_VT)):
            doc_id = docs.get(name, (doc_id, ""))[0]
            content = await c.beta.libraries.documents.text_content_async(
                library_id=APPARAT_LIBRARY_ID, document_id=doc_id)
            out[name] = getattr(content, "text", None) or str(content)
        return out

    return asyncio.run(go())


def parse_qv(text):
    """QV -> (rows, stand_info). rows: id, titel, quelle, rel, vermerk."""
    rows = []
    stand = {"stand": None, "positionen": None, "k": None, "vermerke": None,
             "vt_zaehler": None, "vt_quote_prozent": None, "integritaet": None}
    m = re.search(r"Stand:\s*([^\n]+)", text)
    if m:
        stand["stand"] = m.group(1).strip()[:200]
    m = re.search(r"(\d+)\s*Verzeichnispositionen|Positionsbestand unverändert (\d+)", text)
    if m:
        stand["positionen"] = int(m.group(1) or m.group(2))
    m = re.search(r"K1 (\d+), K2 (\d+), K3 (\d+), K4 (\d+), K5 (\d+), Vermerke (\d+)", text)
    if m:
        stand["k"] = {"K1": int(m.group(1)), "K2": int(m.group(2)), "K3": int(m.group(3)),
                      "K4": int(m.group(4)), "K5": int(m.group(5)), "V": int(m.group(6))}
    m = re.search(r"Erschlie\S*ungsquote (\d+)\s*/\s*(\d+), gerundet ([\d,]+) Prozent", text)
    if m:
        stand["vt_zaehler"] = "%s/%s" % (m.group(1), m.group(2))
        stand["vt_quote_prozent"] = float(m.group(3).replace(",", "."))
    m = re.search(r"Nummernintegrität ([\d/]+)", text)
    if m:
        stand["integritaet"] = [int(x) for x in m.group(1).split("/")]

    group = None
    stufe = None
    for line in text.splitlines():
        line = line.rstrip()
        m = RE_SECTION.match(line)
        if m:
            group = int(m.group(1))
            stufe = None
            continue
        if RE_ANY_H2.match(line):
            group = None
            stufe = None
            continue
        if group is None:
            continue
        if RE_SUBGROUP.match(line):
            continue
        m = RE_STUFE.match(line)
        if m:
            stufe = m.group(1)
            continue
        m = RE_ENTRY.match(line)
        if m:
            nr = int(m.group(1))
            body = m.group(2).strip()
            if " — " in body:
                citation, rest = body.split(" — ", 1)
            else:
                citation, rest = body, ""
            rel = stufe
            m2 = RE_STUFE_INLINE.match(rest)
            if m2:
                rel = m2.group(1)
                rest = rest[m2.end():]
            citation = citation.strip()
            mu = RE_URL.search(citation)
            md = re.search(r"DOI[:\s]+(\S+)", citation, re.I)
            if mu:
                quelle = mu.group(1)
            elif md:
                quelle = "DOI " + md.group(1)
            else:
                # letzter Satzteil, der wie ein Verlag/Ort/Heft aussieht (Buchstabe,
                # nicht mit Ziffer/Klammer beginnen)
                segs = [s.strip() for s in citation.split(". ") if s.strip()]
                quelle = next((s for s in reversed(segs)
                               if re.search(r"[A-Za-zÀ-ÿ]", s) and not re.match(r"^[\d(]", s)),
                              citation)
            rows.append({"id": "%d/%d" % (group, nr), "titel": citation,
                         "quelle": quelle, "k": "", "rel": rel or "",
                         "vermerk": rest.strip(), "updated": time.strftime("%Y-%m-%d")})
    return rows, stand


def parse_vt(text):
    """VT-Klassifikation -> {id: k} plus Gruppengrößen."""
    k_map = {}
    gruppen = {}
    group = None
    for line in text.splitlines():
        m = RE_GRUPPE.match(line)
        if m:
            group = int(m.group(1))
            gruppen[group] = int(m.group(2))
            continue
        if line.startswith("## ") or line.startswith("### "):
            if not RE_GRUPPE.match(line):
                group = None
            continue
        m = RE_KLINE.match(line)
        if m and group is not None:
            k = "V" if m.group(1) == "Vermerk" else m.group(1)
            body = m.group(3)
            masked = mask_parens(body)
            gsize = gruppen.get(group)
            for m2 in RE_REF.finditer(masked):
                prefix = body[max(0, m2.start() - 12):m2.start()]
                if re.search(r"Gruppe \d+,\s*$", prefix):
                    continue  # Querverweis auf eine andere Gruppe
                a = int(m2.group(1))
                b = int(m2.group(2)) if m2.group(2) else a
                for nr in range(a, b + 1):
                    if gsize and nr > gsize:
                        continue  # z. B. "Werkstattbericht Nr. 85" — keine Position
                    pid = "%d/%d" % (group, nr)
                    k_map.setdefault(pid, k)  # erste Nennung gewinnt (Historie-Verweise ignorieren)
    return k_map, gruppen


def parse_prio(vt_text):
    """Priorität 1-4 aus der Beschaffungsliste des Inventars -> {id: 'P1'..'P4'}."""
    prio = {}
    for n in (1, 2, 3, 4):
        i = vt_text.find("### Priorität %d" % n)
        if i < 0:
            continue
        j = vt_text.find("\n### ", i + 10)
        k = vt_text.find("\n## ", i + 10)
        ends = [x for x in (j, k) if x > 0]
        seg = vt_text[i:(min(ends) if ends else len(vt_text))]
        for g, nr in re.findall(r"(?<!\d)(\d)/(\d{1,3})(?!\d)", seg):
            pid = "%s/%s" % (g, nr)
            if pid not in prio:
                prio[pid] = "P%d" % n
    return prio


def parse_pruefaufgaben(qv_text):
    """Sektion '## Offene Prüfaufgaben' -> Liste {n, text, erledigt}."""
    j = qv_text.find("## Offene Prüfaufgaben")
    if j < 0:
        return []
    k = qv_text.find("\n## ", j + 10)
    sec = qv_text[j:(k if k > 0 else len(qv_text))]
    out = []
    for i, m in enumerate(re.finditer(r"^\s*(?:[-*]\s+|\d+\.\s+)([^\n]+)", sec, re.M), 1):
        t = m.group(1).strip()
        if len(t) < 20:
            continue
        out.append({"n": i, "text": t, "erledigt": bool(re.search(r"ERLEDIGT", t))})
    return out


def parse_historie(text):
    """K-Stand-Historie aus der Standzeilen-Kette im Kopf des Dokuments (älteste zuerst)."""
    head = text[:12000]
    kp = re.compile(r"K1 (\d+), K2 (\d+), K3 (\d+), K4 (\d+), K5 (\d+), Vermerke (\d+)")
    dp = re.compile(r"(\d{1,2}\. \w+ 2026)")
    hist = []
    for m in kp.finditer(head):
        back = head[max(0, m.start() - 3000):m.start()]
        dates = dp.findall(back)
        pos = re.findall(r"(?:Positionsbestand unverändert|Bestand) (\d+)", back)
        vtq = re.findall(r"Erschlie\S*ungsquote (\d+)\s*/\s*(\d+)", back)
        ksum = sum(int(m.group(i)) for i in range(1, 7))
        hist.append({
            "datum": dates[-1] if dates else "",
            "k": {"K1": int(m.group(1)), "K2": int(m.group(2)), "K3": int(m.group(3)),
                  "K4": int(m.group(4)), "K5": int(m.group(5)), "V": int(m.group(6))},
            # Positionen = Summe der K-Stände (konsistent); Regex nur als Fallback
            "positionen": ksum or (int(pos[-1]) if pos else None),
            "vt": ("%s/%s" % vtq[-1]) if vtq else None,
        })
    hist.reverse()
    return hist


def parse_meta_fields(titel):
    """Jahr + Quellentyp heuristisch aus der Zitation."""
    y = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", titel or "")
    jahr = int(y.group(1)) if y else None
    t = (titel or "").lower()
    if "doi" in t:
        typ = "Fachaufsatz"
    elif "url" in t:
        typ = "Online"
    elif re.search(r"\b(hg\.|herausgeber|hrsg\.|red\.)\b", t):
        typ = "Sammelband"
    else:
        typ = "Monografie"
    return jahr, typ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-files", nargs=2, metavar=("QV_MD", "VT_MD"),
                    help="statt Live-Download lokale Dateien parsen")
    args = ap.parse_args()

    if args.from_files:
        qv_text = Path(args.from_files[0]).read_text(encoding="utf-8")
        vt_text = Path(args.from_files[1]).read_text(encoding="utf-8")
    else:
        docs = fetch_docs()
        qv_text, vt_text = docs["qv"], docs["vt"]

    rows, stand = parse_qv(qv_text)
    k_map, gruppen = parse_vt(vt_text)
    prio = parse_prio(vt_text)
    pruef = parse_pruefaufgaben(qv_text)
    historie = parse_historie(qv_text)

    for r in rows:
        r["k"] = k_map.get(r["id"], "")
        r["prio"] = prio.get(r["id"], "")
        jahr, typ = parse_meta_fields(r["titel"])
        r["jahr"] = jahr
        r["typ"] = typ
    missing_k = [r["id"] for r in rows if not r["k"]]
    unknown_k = sorted(set(k_map) - {r["id"] for r in rows})

    # K-Stand aus den geparsten Daten gegenrechnen
    k_count = {}
    for r in rows:
        k_count[r["k"]] = k_count.get(r["k"], 0) + 1
    gruppen_enden = [len([r for r in rows if r["id"].startswith("%d/" % g)]) for g in sorted(gruppen)]

    old = json.loads((DATA / "project.json").read_text(encoding="utf-8"))
    meta = dict(old.get("meta", {}))
    meta["stand"] = (stand["stand"] or "")[:200]
    meta["quelle"] = ("Apparat_Quellenverzeichnis.md + Apparat_Volltext-Inventar.md "
                      "(Mistral Library, Live-Import %s)" % time.strftime("%Y-%m-%d"))
    meta["hinweis"] = ("Live-Import aus der Apparat-Bibliothek: %d Positionen. "
                       "Re-Import: tools/import_apparat.py (Key via Env), dann qv.db loeschen "
                       "und serve.py neu starten." % len(rows))
    kstand = {
        "positionen": stand["positionen"] or len(rows),
        "gruppen_enden": gruppen_enden,
        "K": {k: k_count.get(k, 0) for k in ("K1", "K2", "K3", "K4", "K5", "V")},
        "vt_quote_prozent": stand["vt_quote_prozent"],
        "vt_zaehler": stand["vt_zaehler"],
    }
    project = {"meta": meta, "kstand": kstand, "verzeichnis": rows,
               "glossar": old.get("glossar", []),
               "pruefaufgaben": pruef, "historie": historie}
    (DATA / "project.json").write_text(
        json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "sample-data.js").write_text(
        "window.DASHBOARD_DATA = " + json.dumps(project, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8")

    print("Positionen geparst: %d" % len(rows))
    print("Prio-Mapping: %d Positionen" % len(prio))
    print("Prüfaufgaben: %d (davon erledigt: %d)" % (len(pruef), sum(1 for p in pruef if p["erledigt"])))
    print("Historie: %d Stände" % len(historie))
    print("Gruppen-Enden: %s (Inventar: %s)" % (gruppen_enden, sorted(gruppen.items())))
    print("K-Stand geparst: %s" % k_count)
    print("K-Stand laut Standzeile: %s, Positionen %s, Erschließung %s (%s %%)" % (
        stand["k"], stand["positionen"], stand["vt_zaehler"], stand["vt_quote_prozent"]))
    if missing_k:
        print("WARNUNG: ohne K-Klasse: %s" % ", ".join(missing_k[:20]))
    if unknown_k:
        print("WARNUNG: K-Klasse ohne QV-Position: %s" % ", ".join(unknown_k[:20]))
    print("geschrieben: data/project.json, data/sample-data.js")
    print("naechster Schritt: rm data/qv.db && serve.py neu starten")


if __name__ == "__main__":
    main()
