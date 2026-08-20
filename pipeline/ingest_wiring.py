#!/usr/bin/env python3
"""
Ingest wiring diagrams as a raster layer (phase 1 of the wiring viewer).

    python3 pipeline/ingest_wiring.py --all --out archive/derived/wiring --db fiat.db
    python3 pipeline/ingest_wiring.py --slug wd-1978-aus --out archive/derived/wiring

Each wiring PDF becomes one `wiring_diagram` with N `wd_sheet` rows. Sheets are
rendered at (or near) the resolution of the image actually embedded in the PDF:

  * master sheets  -- the big fold-out schematics you will trace on in phase 2/3 --
    are rendered at full native resolution, no cap;
  * ordinary pages (legends, component tables, sub-diagrams) are capped at
    --cap px on the long edge, which is plenty for reading.

A sheet counts as "master" when its embedded image is >= 4000 px on the long
edge -- bigger than any bound page scanned at 300 DPI, i.e. a fold-out.

The overlay tables (wd_component / wd_wire / wd_circuit) are created here but
left empty; phase 2's editor fills them. Coordinates in those tables are
normalized 0..1 against the sheet image, so re-rendering a sheet at a different
resolution never invalidates a trace.

Idempotent: existing sheet images are reused unless --force.
"""
import argparse, json, re, shutil, sqlite3, subprocess, sys, tempfile
from pathlib import Path

from PIL import Image
Image.MAX_IMAGE_PIXELS = None

# ---------------------------------------------------------------- manifest
# Everything below came from the x19.com.au library (see archive/sources.yaml);
# CREDIT is surfaced on every wiring page of the site.
CREDIT = "Scan courtesy of x19.com.au"

DIAGRAMS = [
    dict(slug="wd-1974", file="Fiat_X19_1974_wiring.pdf",
         title="Wiring diagram — 1974",
         year_from=1974, year_to=1974, market="EU/US",
         variant_note="Early 1300 carb", sort_order=10),
    dict(slug="wd-1978-aus", file="Fiat_X19_1978_Australian_X19Aust_Wiring_Diagram.pdf",
         title="Wiring diagram — 1978 Australian (RHD)",
         year_from=1978, year_to=1978, market="AUS",
         variant_note="Serie Speciale 1300 carb, RHD — the pilot sheet for the "
                      "traced overlay",
         pilot=1, sort_order=20),
    dict(slug="wd-1979-aus", file="Fiat-X19_wiring_diagram_australian_1979.pdf",
         title="Wiring diagram — 1979 Australian",
         year_from=1979, year_to=1979, market="AUS", sort_order=30),
    dict(slug="wd-1981", file="Fiat-X19_wiring_diagram_1981.pdf",
         title="Wiring diagram — 1981",
         year_from=1981, year_to=1981, market="US", sort_order=40),
    dict(slug="wd-bertone", file="Bertone_wiring_diagram.PDF",
         title="Wiring diagram — Bertone (1982 on)",
         year_from=1982, year_to=1988, market="EU/US", sort_order=50),
]

DDL = """
CREATE TABLE IF NOT EXISTS wiring_diagram (
    id           INTEGER PRIMARY KEY,
    slug         TEXT NOT NULL UNIQUE,
    vehicle_id   INTEGER REFERENCES vehicle(id),
    source_id    INTEGER REFERENCES source(id),
    title        TEXT NOT NULL,
    year_from    INTEGER,
    year_to      INTEGER,
    market       TEXT,
    variant_note TEXT,
    credit       TEXT,
    pilot        INTEGER DEFAULT 0,   -- 1 = the sheet the overlay work targets
    sort_order   INTEGER,
    notes        TEXT
);

-- One page of a wiring PDF. 'master' sheets are the fold-out schematics.
CREATE TABLE IF NOT EXISTS wd_sheet (
    id         INTEGER PRIMARY KEY,
    diagram_id INTEGER NOT NULL REFERENCES wiring_diagram(id),
    sheet_no   INTEGER NOT NULL,          -- page order within the diagram
    kind       TEXT NOT NULL DEFAULT 'page'
               CHECK (kind IN ('master','page')),
    label      TEXT,
    file_path  TEXT NOT NULL,             -- relative to the wiring image root
    width_px   INTEGER,
    height_px  INTEGER,
    native_w   INTEGER,                   -- embedded image size in the PDF
    native_h   INTEGER,
    ocr_text   TEXT,
    UNIQUE (diagram_id, sheet_no)
);

-- ---- overlay layer (populated by the phase-2 editor; empty for now) -------
CREATE TABLE IF NOT EXISTS wd_circuit (
    id         INTEGER PRIMARY KEY,
    diagram_id INTEGER REFERENCES wiring_diagram(id),
    code       TEXT NOT NULL,
    name       TEXT,
    grp        TEXT,
    descr      TEXT,
    symptoms   TEXT,
    tests      TEXT,
    colour     TEXT,
    conf       TEXT DEFAULT 'unknown'
               CHECK (conf IN ('verified','typical','unknown')),
    UNIQUE (diagram_id, code)
);

CREATE TABLE IF NOT EXISTS wd_component (
    id        INTEGER PRIMARY KEY,
    sheet_id  INTEGER NOT NULL REFERENCES wd_sheet(id),
    code      TEXT NOT NULL,              -- factory legend number
    name      TEXT,
    name_en   TEXT,
    x REAL, y REAL, w REAL, h REAL,       -- normalized 0..1 box on the sheet
    location_on_car TEXT,
    terminals TEXT,
    part_no   TEXT,
    notes     TEXT,
    conf      TEXT DEFAULT 'unknown'
              CHECK (conf IN ('verified','typical','unknown')),
    verified  INTEGER DEFAULT 0,
    UNIQUE (sheet_id, code)
);

CREATE TABLE IF NOT EXISTS wd_wire (
    id          INTEGER PRIMARY KEY,
    sheet_id    INTEGER NOT NULL REFERENCES wd_sheet(id),
    label       TEXT,
    colour_code TEXT,                     -- Fiat letters, e.g. 'RN', 'V'
    gauge       TEXT,
    from_component TEXT, from_pin TEXT,
    to_component   TEXT, to_pin   TEXT,
    path        TEXT,                     -- JSON [[ [x,y], ... ], ...] normalized
    circuit_ids TEXT,                     -- comma-separated wd_circuit.code
    conf        TEXT DEFAULT 'unknown'
                CHECK (conf IN ('verified','typical','unknown')),
    verified    INTEGER DEFAULT 0,
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS idx_wd_sheet_diagram ON wd_sheet(diagram_id);
CREATE INDEX IF NOT EXISTS idx_wd_comp_sheet    ON wd_component(sheet_id);
CREATE INDEX IF NOT EXISTS idx_wd_wire_sheet    ON wd_wire(sheet_id);
"""


def sh(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def page_sizes_pt(pdf):
    """{page_no: (width_pt, height_pt)} as rendered (rotation applied)."""
    out = sh(["pdfinfo", "-f", "1", "-l", "100000", pdf]).stdout
    sizes = {}
    for m in re.finditer(r"Page\s+(\d+)\s+size:\s+([\d.]+)\s+x\s+([\d.]+)", out):
        sizes[int(m.group(1))] = (float(m.group(2)), float(m.group(3)))
    for m in re.finditer(r"Page\s+(\d+)\s+rot:\s+(\d+)", out):
        p, rot = int(m.group(1)), int(m.group(2))
        if rot in (90, 270) and p in sizes:
            sizes[p] = (sizes[p][1], sizes[p][0])
    return sizes


def native_sizes(pdf):
    """{page_no: (w,h)} of the largest embedded image on each page."""
    try:
        out = sh(["pdfimages", "-list", pdf]).stdout
    except subprocess.CalledProcessError:
        return {}
    best = {}
    for line in out.splitlines()[2:]:
        f = line.split()
        if len(f) < 5 or f[2] not in ("image", "smask"):
            continue
        if f[2] == "smask":
            continue
        try:
            p, w, h = int(f[0]), int(f[3]), int(f[4])
        except ValueError:
            continue
        if w * h > best.get(p, (0, 0))[0] * best.get(p, (0, 0))[1]:
            best[p] = (w, h)
    return best


def is_master(nw, nh):
    """A fold-out schematic, as opposed to an ordinary bound page.

    Deliberately just a size test: a plain A4/letter page scanned at 300 DPI
    tops out around 3500 px, so >= 4000 px on the long edge means the original
    was physically bigger than a page -- i.e. a fold-out. (Aspect ratio is no
    help here: A4 is already 1.41 : 1.)
    """
    return max(nw, nh) >= 4000


def render_page(pdf, page, dpi, tmpdir):
    stem = Path(tmpdir) / "pg"
    sh(["pdftoppm", "-png", "-r", f"{dpi:.2f}", "-f", str(page), "-l", str(page),
        pdf, str(stem)])
    produced = sorted(Path(tmpdir).glob("pg-*.png"))
    if not produced:
        raise RuntimeError(f"pdftoppm produced nothing for page {page}")
    return produced[0]


def ocr(png_path, tmpdir):
    """OCR from a modest downscale — full-res fold-outs are slow and no better."""
    try:
        im = Image.open(png_path)
        if max(im.size) > 2000:
            sc = 2000 / max(im.size)
            im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))),
                           Image.LANCZOS)
        small = Path(tmpdir) / "ocr.png"
        im.convert("L").save(small)
        r = subprocess.run(["tesseract", str(small), "stdout", "-l", "eng", "--psm", "3"],
                           capture_output=True, text=True, timeout=180)
        return r.stdout.strip()
    except Exception as e:                                   # noqa: BLE001
        print(f"    ocr skipped: {e}")
        return ""


def pronounceable(word):
    """Reject OCR mush without a dictionary: real words have vowels, and don't
    run four consonants together."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if len(w) < 4:
        return True
    if not re.search(r"[aeiouy]", w):
        return False
    return not re.search(r"[bcdfghjklmnpqrstvwxz]{4}", w)


def plausible_title(line):
    """Is this OCR line a real heading, or scanner noise?

    Wiring sheets OCR badly, and a bad label ("Fe Ee", "B/ E/ Ay 9") is worse
    than no label at all. So: strict. Every token must be a clean word or a
    small number, and at least one token has to be a proper word — junk OCR
    almost never produces one.
    """
    s = re.sub(r"[^A-Za-z0-9 /&.,'-]", " ", line or "")
    s = re.sub(r"\s{2,}", " ", s).strip(" .,-")
    if not (6 <= len(s) <= 46):
        return None
    tokens = s.split()
    if not tokens or len(tokens) > 7:
        return None
    words = []
    for t in tokens:
        t = t.strip(".,:;'")
        if not t or re.fullmatch(r"\d{1,4}", t) or re.fullmatch(r"[-&.]+", t):
            continue                                  # numbering, bullets, dashes
        if not re.fullmatch(r"[A-Za-z][A-Za-z'&/-]*", t):
            return None
        if "/" in t and any(len(seg) < 4 for seg in t.split("/") if seg):
            return None                               # "Wht/Blk" — a colour code, not a title
        if not pronounceable(t):
            return None                               # "Dpnynnnnabh" — OCR mush
        words.append(t)
    if not words:
        return None
    longest = max(len(w) for w in words)
    if len(words) == 1:
        w = words[0]
        # A lone word has no context to vouch for it, so demand that it at least
        # looks pronounceable: "Capacities" yes, OCR mush like "Oyanfwn" no.
        if longest < 7 or "/" in s:
            return None
        return s.title()
    return s.title() if longest >= 5 else None


def renumber_masters(db, diagram_id):
    """'Main schematic' × 5 is useless in a list — number them 1 of 5, 2 of 5…"""
    rows = db.execute("""SELECT id, sheet_no FROM wd_sheet
                         WHERE diagram_id=? AND kind='master' ORDER BY sheet_no""",
                      (diagram_id,)).fetchall()
    if len(rows) < 2:
        return
    for i, (sid, no) in enumerate(rows, 1):
        db.execute("UPDATE wd_sheet SET label=? WHERE id=?",
                   (f"Main schematic {i} of {len(rows)} (p.{no})", sid))


def label_for(kind, sheet_no, text):
    if kind == "master":
        base = "Main schematic"
    else:
        base = None
        for line in (text or "").splitlines()[:40]:
            base = plausible_title(line)
            if base:
                break
        base = base or "Sheet"
    return f"{base} (p.{sheet_no})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="fiat.db")
    ap.add_argument("--raw", default="archive/raw/x19")
    ap.add_argument("--out", default="archive/derived/wiring")
    ap.add_argument("--vehicle", default="x19")
    ap.add_argument("--slug", action="append",
                    help="ingest only these diagram slugs (repeatable)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--cap", type=int, default=2400,
                    help="long-edge px cap for non-master sheets")
    ap.add_argument("--format", choices=["webp", "jpg"], default="webp")
    ap.add_argument("--quality", type=int, default=85)
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--relabel", action="store_true",
                    help="recompute sheet labels from stored OCR text and exit "
                         "(no rendering — for tuning the heading heuristic)")
    args = ap.parse_args()

    if not args.all and not args.slug:
        ap.error("pass --all or one or more --slug")
    wanted = [d for d in DIAGRAMS if args.all or d["slug"] in (args.slug or [])]
    if not wanted:
        ap.error("no matching diagram slugs")

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(args.db, timeout=120)
    db.executescript(DDL)
    vid = db.execute("SELECT id FROM vehicle WHERE code=?", (args.vehicle,)).fetchone()[0]

    if args.relabel:
        n = 0
        for sid, dslug, sheet_no, kind, text, old in db.execute(
                """SELECT sh.id, wd.slug, sh.sheet_no, sh.kind, sh.ocr_text, sh.label
                   FROM wd_sheet sh JOIN wiring_diagram wd ON wd.id=sh.diagram_id
                   ORDER BY wd.sort_order, sh.sheet_no""").fetchall():
            if not any(args.all or dslug == s for s in (args.slug or [dslug])):
                continue
            if kind == "master":
                continue                       # renumber_masters owns these labels
            new = label_for(kind, sheet_no, text)
            if new != old:
                db.execute("UPDATE wd_sheet SET label=? WHERE id=?", (new, sid))
                print(f"  {dslug} p{sheet_no:02d}: {old!r} -> {new!r}")
                n += 1
        for (did,) in db.execute("SELECT id FROM wiring_diagram").fetchall():
            renumber_masters(db, did)
        db.commit()
        print(f"relabelled {n} sheets")
        return

    for d in wanted:
        pdf = Path(args.raw) / d["file"]
        if not pdf.exists():
            print(f"!! missing {pdf} — skipped")
            continue
        print(f"\n== {d['slug']}: {pdf.name}")

        row = db.execute("SELECT id FROM source WHERE title=?", (d["file"],)).fetchone()
        if row:
            sid = row[0]
        else:
            db.execute("INSERT INTO source(kind,title,notes) VALUES('pdf',?,?)",
                       (d["file"], CREDIT))
            sid = db.execute("SELECT id FROM source WHERE title=?", (d["file"],)).fetchone()[0]

        db.execute("""INSERT INTO wiring_diagram
                        (slug,vehicle_id,source_id,title,year_from,year_to,market,
                         variant_note,credit,pilot,sort_order)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?)
                      ON CONFLICT(slug) DO UPDATE SET
                        title=excluded.title, year_from=excluded.year_from,
                        year_to=excluded.year_to, market=excluded.market,
                        variant_note=excluded.variant_note, credit=excluded.credit,
                        pilot=excluded.pilot, sort_order=excluded.sort_order""",
                   (d["slug"], vid, sid, d["title"], d.get("year_from"), d.get("year_to"),
                    d.get("market"), d.get("variant_note"), CREDIT,
                    d.get("pilot", 0), d.get("sort_order", 99)))
        did = db.execute("SELECT id FROM wiring_diagram WHERE slug=?", (d["slug"],)).fetchone()[0]

        sheet_dir = out_root / d["slug"]
        sheet_dir.mkdir(parents=True, exist_ok=True)
        pts = page_sizes_pt(str(pdf))
        natives = native_sizes(str(pdf))
        npages = max(pts) if pts else 0

        for p in range(1, npages + 1):
            pt_w, pt_h = pts[p]
            nw, nh = natives.get(p, (int(pt_w / 72 * 300), int(pt_h / 72 * 300)))
            master = is_master(nw, nh)
            long_native = max(nw, nh)
            target_long = long_native if master else min(long_native, args.cap)
            # render dpi that lands the page on target_long px
            dpi = 72.0 * target_long / max(pt_w, pt_h)
            dpi = max(40.0, min(dpi, 1200.0))

            name = f"s{p:02d}.{args.format}"
            dst = sheet_dir / name
            existing = db.execute(
                "SELECT id, ocr_text FROM wd_sheet WHERE diagram_id=? AND sheet_no=?",
                (did, p)).fetchone()
            if dst.exists() and existing and not args.force:
                print(f"  p{p:02d} ok (cached)")
                continue

            with tempfile.TemporaryDirectory() as td:
                png = render_page(str(pdf), p, dpi, td)
                im = Image.open(png)
                # line art: greyscale unless the scan is genuinely colour
                im = im.convert("RGB")
                raw = im.resize((80, 80)).tobytes()
                trip = [raw[i:i + 3] for i in range(0, len(raw), 3)]
                colourful = sum(1 for t in trip if max(t) - min(t) > 28) / len(trip) > 0.02
                if not colourful:
                    im = im.convert("L")
                if args.format == "webp":
                    im.save(dst, "WEBP", quality=args.quality, method=5)
                else:
                    im.save(dst, "JPEG", quality=args.quality, optimize=True,
                            progressive=True)
                text = "" if args.no_ocr else ocr(png, td)

            w, h = Image.open(dst).size
            kind = "master" if master else "page"
            db.execute("""INSERT INTO wd_sheet
                            (diagram_id,sheet_no,kind,label,file_path,
                             width_px,height_px,native_w,native_h,ocr_text)
                          VALUES(?,?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(diagram_id,sheet_no) DO UPDATE SET
                            kind=excluded.kind, label=excluded.label,
                            file_path=excluded.file_path, width_px=excluded.width_px,
                            height_px=excluded.height_px, native_w=excluded.native_w,
                            native_h=excluded.native_h, ocr_text=excluded.ocr_text""",
                       (did, p, kind, label_for(kind, p, text),
                        f"{d['slug']}/{name}", w, h, nw, nh, text))
            db.commit()
            kb = dst.stat().st_size / 1024
            print(f"  p{p:02d} {kind:<6} {w}x{h} ({nw}x{nh} native) "
                  f"{kb:,.0f} KB  {'colour' if colourful else 'grey'}")

        renumber_masters(db, did)
        db.commit()
        n = db.execute("SELECT COUNT(*) FROM wd_sheet WHERE diagram_id=?", (did,)).fetchone()[0]
        nm = db.execute("SELECT COUNT(*) FROM wd_sheet WHERE diagram_id=? AND kind='master'",
                        (did,)).fetchone()[0]
        print(f"  -> {n} sheets ({nm} master)")

    db.commit()
    total = db.execute("SELECT COUNT(*) FROM wd_sheet").fetchone()[0]
    print(f"\nDONE: {total} wiring sheets in DB")


if __name__ == "__main__":
    main()
