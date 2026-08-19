#!/usr/bin/env python3
"""
Build document_section rows from OCR'd page headers, and repair the
category (Gruppo) map.

    python3 pipeline/build_sections.py fiat.db

Detection logic (works for factory service manuals whose pages print
"Section No. NN"):
- Fill-forward the section number across pages (headers appear on
  right-hand pages only).
- A drop back to a lower section number starts a new block (the base
  manual, then each model-year supplement).
- Uppercase heading lines become 'topics' (page-level bookmarks) inside
  each section — unverified, fixable via edit mode later.
Re-runnable: wipes and rebuilds document_section each time.
"""
import re, sqlite3, sys

GRUPPO = {
    "00": ("general", "General information"),
    "10": ("engine", "Engine"),
    "17": ("fuel", "Fuel / Exhaust"),
    "18": ("clutch", "Clutch"),
    "21": ("gearbox", "Gearbox / Differential"),
    "25": ("exhaust-emission", "Emission control"),
    "27": ("driveshafts", "Driveshafts"),
    "30": ("heating", "Heating / Ventilation"),
    "33": ("brakes", "Brakes"),
    "38": ("controls", "Pedals / Controls"),
    "41": ("steering", "Steering"),
    "44": ("suspension", "Suspension"),
    "50": ("body-fittings", "Body fittings"),
    "55": ("electrical", "Electrical"),
    "63": ("fuel-tank", "Fuel tank"),
    "68": ("tools", "Tools"),
    "70": ("body", "Body"),
    "71": ("body-fittings2", "Body fittings / Trim"),
    "90": ("aux-controls", "Auxiliary controls"),
    "95": ("ignition", "Ignition"),
    "99": ("lighting", "Lighting / Signalling"),
}

DDL = """
CREATE TABLE IF NOT EXISTS document_section (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES document(id),
    block       TEXT,             -- '1974 base', 'Supplement 1', ...
    code        TEXT,             -- gruppo/section number as printed
    title       TEXT,             -- friendly name
    page_from   INTEGER NOT NULL, -- page_no of first page
    page_to     INTEGER NOT NULL,
    verified    INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS document_topic (
    id          INTEGER PRIMARY KEY,
    section_id  INTEGER NOT NULL REFERENCES document_section(id),
    page_no     INTEGER NOT NULL,
    title       TEXT NOT NULL,
    verified    INTEGER DEFAULT 0
);
"""

HEAD_RE = re.compile(r"Section\s*N[o0]\.?\s*(\d{2})")
YEAR_RE = re.compile(r"\b(19[78]\d)\b")

def topic_ok(ln):
    ln = ln.strip()
    if not (9 < len(ln) < 42): return False
    if not re.fullmatch(r"[A-Z][A-Z /\-]+[A-Z]", ln): return False
    words = ln.split()
    if len(words) < 2: return False
    if any(len(w) == 1 for w in words): return False
    bad = {"SERVICE", "MANUAL", "PAGE", "SECTION", "FIAT"}
    if set(words) & bad: return False
    return True

def main():
    db = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else "fiat.db")
    db.executescript(DDL)

    # ---- repair category map & re-link plates by tav prefix ----------
    # neutralize slugs first so renames can't collide (e.g. 'clutch'
    # moving from gruppo 21 to gruppo 18)
    db.execute("UPDATE category SET slug='g'||gruppo_code WHERE gruppo_code IS NOT NULL")
    for code, (slug, name) in GRUPPO.items():
        db.execute("""INSERT INTO category(slug,name,gruppo_code)
                      SELECT ?,?,? WHERE NOT EXISTS
                        (SELECT 1 FROM category WHERE gruppo_code=?)""",
                   (slug, name, code, code))
        db.execute("UPDATE category SET slug=?, name=? WHERE gruppo_code=?",
                   (slug, name, code))
    db.execute("""UPDATE plate SET category_id=
                    (SELECT id FROM category WHERE gruppo_code=substr(plate.tav_code,1,2))
                  WHERE EXISTS
                    (SELECT 1 FROM category WHERE gruppo_code=substr(plate.tav_code,1,2))""")

    # ---- section detection per document -----------------------------
    for (did, title) in db.execute("SELECT id,title FROM document").fetchall():
        pages = db.execute("""SELECT page_no, ocr_text FROM document_page
                              WHERE document_id=? ORDER BY page_no""", (did,)).fetchall()
        if not pages:
            continue
        db.execute("""DELETE FROM document_topic WHERE section_id IN
                      (SELECT id FROM document_section WHERE document_id=?)""", (did,))
        db.execute("DELETE FROM document_section WHERE document_id=?", (did,))

        seq = []           # (page_no, sec or None, year or None, text, banner)
        banner_count = {}
        for pno, txt in pages:
            lines = (txt or "").split("\n")
            head = "\n".join(lines[:4])
            m = HEAD_RE.search(head)
            y = YEAR_RE.search(head)
            first = next((l.strip() for l in lines if l.strip()), "")
            banner = first if (len(first) > 12 and first.isupper()
                               and re.fullmatch(r"[A-Z][A-Z /\-]+", first)) else None
            if banner and not m:
                banner_count[banner] = banner_count.get(banner, 0) + 1
            seq.append((pno, m.group(1) if m else None,
                        y.group(1) if y else None, txt or "", banner))
        # banners on 8+ pages = an appendix document bound into the manual
        appendix = {b for b, n in banner_count.items() if n >= 8}

        # fill-forward sections; detect block restarts (section value drops)
        cur_block, last_sec = 1, None
        filled = []
        for pno, sec, year, txt, banner in seq:
            if banner in appendix:
                last_sec = "APX:" + banner     # sticky: appendix continues
                filled.append((pno, last_sec, cur_block, year, txt))
                continue
            if sec is not None:
                if (isinstance(last_sec, str) and last_sec.isdigit()
                        and int(sec) < int(last_sec) - 5):
                    cur_block += 1          # supplement starts
                last_sec = sec
            filled.append((pno, last_sec, cur_block, year, txt))

        # block labels: first year seen inside the block
        block_year = {}
        for pno, sec, blk, year, txt in filled:
            if year and blk not in block_year:
                block_year[blk] = year
        def blabel(blk):
            y = block_year.get(blk)
            return (f"{y} base manual" if blk == 1 else
                    f"Supplement {blk-1}" + (f" ({y})" if y else ""))

        # collapse to (block, sec) runs
        runs = []
        for pno, sec, blk, year, txt in filled:
            key = (blk, sec)
            if runs and runs[-1][0] == key:
                runs[-1][2] = pno
            else:
                runs.append([key, pno, pno])
        n_sec = n_top = 0
        for (blk, sec), p_from, p_to in runs:
            if sec is None:
                continue
            if sec.startswith("APX:"):
                code, name, blockname = "", sec[4:].title(), "Appendix"
            else:
                code, name, blockname = sec, GRUPPO.get(sec, (None, f"Section {sec}"))[1], blabel(blk)
            db.execute("""INSERT INTO document_section
                          (document_id,block,code,title,page_from,page_to)
                          VALUES(?,?,?,?,?,?)""",
                       (did, blockname, code, name, p_from, p_to))
            sid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            n_sec += 1
            seen_topics = set()
            for pno, s2, b2, year, txt in filled:
                if b2 == blk and s2 == sec and p_from <= pno <= p_to:
                    for ln in txt.split("\n")[:6]:
                        if (topic_ok(ln) and ln.strip().title() != name
                                and ln.strip().title() not in seen_topics):
                            seen_topics.add(ln.strip().title())
                            db.execute("""INSERT INTO document_topic(section_id,page_no,title)
                                          VALUES(?,?,?)""", (sid, pno, ln.strip().title()))
                            n_top += 1
                            break
        print(f"{title}: {n_sec} sections, {n_top} topics")
    db.commit()

if __name__ == "__main__":
    main()
