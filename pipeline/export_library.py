#!/usr/bin/env python3
"""
Generate docs/library.html — the document library page listing every file
in archive/raw/, grouped by vehicle and type, linking to the files on GitHub.

    python3 pipeline/export_library.py --repo lgfletcher/fiat-parts-archive --out docs/library.html

Runs off the working tree, so re-run it whenever files are added.
"""
import argparse, html, re
from pathlib import Path

VEHICLE_NAMES = {"x19": "Fiat X1/9", "124": "Fiat 124", "125": "Fiat 125",
                 "128": "Fiat 128", "misc": "Multi-model / other"}

def classify(name):
    n = name.lower()
    if n.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")) or "colour" in n or "color" in n or "paint" in n or "chip" in n:
        return "Paint & colour charts"
    if "parts" in n and ("catalog" in n or "list" in n): return "Parts catalogues"
    if "wiring" in n or "electrical" in n: return "Wiring & electrical"
    if "owner" in n or "ownes" in n: return "Owner's manuals"
    if "service" in n or "data_and_characteristics" in n: return "Service manuals"
    if "timing" in n: return "Engine guides"
    return "Other documents"

def human(nbytes):
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024: return f"{nbytes:.0f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)          # owner/name
    ap.add_argument("--branch", default="main")
    ap.add_argument("--raw", default="archive/raw")
    ap.add_argument("--out", default="docs/library.html")
    ap.add_argument("--db", default=None,
                    help="optional fiat.db — adds 'open in viewer' links for ingested docs")
    args = ap.parse_args()

    viewers = {}   # filename -> doc.html slug
    wirings = {}   # filename -> wiring.html slug
    if args.db:
        import sqlite3
        db = sqlite3.connect(args.db)
        try:
            for fn, slug in db.execute("""
                SELECT s.title, d.url_or_path FROM document d
                JOIN source s ON s.id=d.source_id
                WHERE d.hosted=1 AND EXISTS
                  (SELECT 1 FROM document_page dp WHERE dp.document_id=d.id)"""):
                viewers[fn] = slug
        except sqlite3.OperationalError:
            pass
        try:
            for fn, slug in db.execute("""
                SELECT s.title, wd.slug FROM wiring_diagram wd
                JOIN source s ON s.id=wd.source_id
                WHERE EXISTS (SELECT 1 FROM wd_sheet sh WHERE sh.diagram_id=wd.id)"""):
                wirings[fn] = slug
        except sqlite3.OperationalError:
            pass

    groups = {}   # vehicle -> category -> [(name, size, url)]
    for f in sorted(Path(args.raw).rglob("*")):
        if not f.is_file() or f.name.startswith((".", "._")) or f.suffix.lower() == ".md":
            continue
        veh = f.relative_to(args.raw).parts[0]
        url = (f"https://github.com/{args.repo}/raw/{args.branch}/"
               + str(f).replace(" ", "%20"))
        groups.setdefault(veh, {}).setdefault(classify(f.name), []).append(
            (f.name, f.stat().st_size, url))

    rows = []
    for veh in ("x19", "124", "125", "128", "misc"):
        if veh not in groups: continue
        rows.append(f'<h2>{VEHICLE_NAMES.get(veh, veh)}</h2>')
        for cat in sorted(groups[veh]):
            rows.append(f'<h3>{cat}</h3><ul>')
            for name, size, url in groups[veh][cat]:
                pretty = html.escape(re.sub(r"[_]+", " ", name))
                if name in wirings:
                    view = (f' <a class="vw" href="wiring.html?d={wirings[name]}">'
                            f'▶ open in wiring viewer</a>')
                elif name in viewers:
                    view = f' <a class="vw" href="doc.html?d={viewers[name]}">▶ open in viewer</a>'
                else:
                    view = ''
                rows.append(f'<li><span><a href="{url}">{pretty}</a>{view}</span>'
                            f'<span class="sz">{human(size)}</span></li>')
            rows.append('</ul>')
    listing = "\n".join(rows) or "<p>No documents yet.</p>"

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Document Library — Fiat Classic Parts Archive</title>
<style>
 :root{{--bg:#1c1f26;--panel:#252932;--line:#3a4150;--txt:#e8e6df;--dim:#9aa0ac;--accent:#e8b84b;--accent2:#7fb4d8}}
 body{{font-family:"Avenir Next","Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--txt);margin:0}}
 header{{display:flex;align-items:center;gap:14px;padding:12px 22px;background:var(--panel);border-bottom:1px solid var(--line)}}
 header h1{{font-size:15px;letter-spacing:.04em}}
 header a{{color:var(--accent);text-decoration:none;font-size:13px;border:1px solid var(--line);border-radius:6px;padding:5px 12px}}
 main{{max-width:860px;margin:0 auto;padding:26px 22px 60px}}
 h2{{color:var(--accent);font-size:17px;margin:26px 0 4px;border-bottom:1px solid var(--line);padding-bottom:6px}}
 h3{{color:var(--dim);font-size:12px;letter-spacing:.1em;text-transform:uppercase;margin:16px 0 4px}}
 ul{{list-style:none;padding:0;margin:0}}
 li{{display:flex;justify-content:space-between;gap:14px;padding:7px 4px;border-bottom:1px solid #2c313c;font-size:14px}}
 li a{{color:var(--accent2);text-decoration:none}}
 li a:hover{{text-decoration:underline}}
 .sz{{color:var(--dim);font-size:12px;white-space:nowrap}}
 .vw{{color:#1c1f26!important;background:var(--accent);border-radius:4px;padding:1px 8px;font-size:11.5px;margin-left:8px;white-space:nowrap}}
 .note{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 16px;font-size:13px;color:var(--dim);margin-top:8px}}
</style></head><body>
<header><h1>FIAT CLASSIC PARTS ARCHIVE — DOCUMENT LIBRARY</h1>
<a href="index.html">← Parts catalog viewer</a>
<a href="wiring.html">⚡ Wiring diagrams</a>
<a href="paint.html">🎨 Paint codes &amp; colour charts</a></header>
<main>
<div class="note">Original scans preserved as-is. Files download directly from this project's GitHub repository.
Interactive (zoom + part search) versions are being added to the
<a href="index.html" style="color:var(--accent2)">viewer</a> one document at a time.</div>
{listing}
</main></body></html>"""
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(page)
    n = sum(len(v) for g in groups.values() for v in g.values())
    print(f"library.html: {n} documents listed → {args.out}")

if __name__ == "__main__":
    main()
