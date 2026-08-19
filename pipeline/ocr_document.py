#!/usr/bin/env python3
"""
Ingest a manual/reference PDF as a page-viewable, text-searchable document.

    python3 pipeline/ocr_document.py \
        --pdf "archive/raw/x19/Fiat_X19_Service_Manual_1974_to_1978_USA.pdf" \
        --slug sm-74-78-usa --title "Service Manual 1974-1978 (USA)" \
        --doc-type service_manual --vehicle x19 \
        --out archive/derived/documents --db fiat.db

Per page: 150 DPI JPEG (for the viewer) + OCR text (for search) + detected
part numbers (for cross-links to the parts catalog). Idempotent; resumes
where it left off. Creates document_page table on first use (schema v0.2).
"""
import argparse, re, sqlite3, subprocess
from pathlib import Path

DPI = 150

DDL = """
CREATE TABLE IF NOT EXISTS document_page (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES document(id),
    page_no     INTEGER NOT NULL,
    file_path   TEXT NOT NULL,
    ocr_text    TEXT,
    part_nos    TEXT,            -- comma-separated part numbers detected on page
    ocr_status  TEXT DEFAULT 'done',
    UNIQUE (document_id, page_no)
);
"""

def sh(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--doc-type", default="service_manual")
    ap.add_argument("--vehicle", default="x19")
    ap.add_argument("--out", required=True)
    ap.add_argument("--db", default="fiat.db")
    ap.add_argument("--first", type=int, default=1)
    ap.add_argument("--last", type=int, default=0)
    args = ap.parse_args()

    out = Path(args.out) / args.slug
    out.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(args.db)
    db.executescript(DDL)

    vid = db.execute("SELECT id FROM vehicle WHERE code=?", (args.vehicle,)).fetchone()[0]
    db.execute("""INSERT OR IGNORE INTO source(kind,title) VALUES('pdf',?)""",
               (Path(args.pdf).name,))
    sid = db.execute("SELECT id FROM source WHERE title=?", (Path(args.pdf).name,)).fetchone()[0]
    row = db.execute("SELECT id FROM document WHERE url_or_path=?", (args.slug,)).fetchone()
    if row:
        did = row[0]
    else:
        db.execute("""INSERT INTO document(source_id,vehicle_id,doc_type,title,url_or_path,hosted)
                      VALUES(?,?,?,?,?,1)""",
                   (sid, vid, args.doc_type, args.title, args.slug))
        did = db.execute("SELECT id FROM document WHERE url_or_path=?", (args.slug,)).fetchone()[0]

    info = sh(["pdfinfo", args.pdf]).stdout
    npages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
    last = args.last or npages

    known_parts = {r[0] for r in db.execute("SELECT part_no FROM part")}
    n_done = 0
    for p in range(args.first, last + 1):
        jpg = out / f"p{p:03d}.jpg"
        have = db.execute("SELECT 1 FROM document_page WHERE document_id=? AND page_no=?",
                          (did, p)).fetchone()
        if have and jpg.exists():
            continue
        if not jpg.exists():
            sh(["pdftoppm", "-jpeg", "-r", str(DPI), "-jpegopt", "quality=72",
                "-f", str(p), "-l", str(p), args.pdf, str(out / "tmp")])
            produced = list(out.glob("tmp-*.jpg"))
            produced[0].rename(jpg)
        r = subprocess.run(["tesseract", str(jpg), "stdout", "-l", "eng", "--psm", "3"],
                           capture_output=True, text=True)
        text = r.stdout.strip()
        # part numbers mentioned on the page — only ones the catalog knows,
        # plus clear 7-digit candidates (avoids matching torque figures etc.)
        cands = set(re.findall(r"\b\d{7}\b", text))
        mentions = sorted(cands & known_parts | {c for c in cands if c.startswith(('4','5','1'))})
        db.execute("""INSERT OR REPLACE INTO document_page
                      (document_id,page_no,file_path,ocr_text,part_nos,ocr_status)
                      VALUES(?,?,?,?,?,'done')""",
                   (did, p, f"{args.slug}/p{p:03d}.jpg", text, ",".join(mentions)))
        n_done += 1
        if n_done % 10 == 0:
            db.commit()
            print(f"page {p}/{last}", flush=True)
    db.commit()
    total = db.execute("SELECT COUNT(*) FROM document_page WHERE document_id=?", (did,)).fetchone()[0]
    print(f"DONE document {args.slug}: {total} pages in DB")

if __name__ == "__main__":
    main()
