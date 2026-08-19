#!/usr/bin/env python3
"""
Stage 1+2+3 of the archive pipeline: extract catalog pages, OCR plate
metadata and part numbers, populate fiat.db.

Usage:
    python3 pipeline/ocr_catalog.py \
        --pdf archive/raw/x19/Fiat_X19_Factory_parts_catalog.pdf \
        --catalog-title "Fiat X1/9 Factory parts catalog (8-1974)" \
        --vehicle x19 --out archive/derived/factory_catalog --db fiat.db

Idempotent: re-running skips pages whose images already exist and
re-OCRs only missing plates. All OCR output lands with verified=0 —
nothing is trusted until a human pass confirms it.
"""
import argparse, csv, io, os, re, sqlite3, subprocess, sys
from pathlib import Path

DPI = 300

# Fiat "Gruppo" prefixes → friendly category names (best-effort; the
# plate header text is the authoritative title, this is just navigation).
GRUPPO = {
    "10": ("engine", "Engine"),
    "17": ("fuel", "Fuel / Exhaust"),
    "21": ("clutch", "Clutch"),
    "25": ("gearbox", "Gearbox / Differential"),
    "27": ("cooling", "Cooling"),
    "33": ("brakes", "Brakes"),
    "38": ("controls", "Pedals / Controls"),
    "41": ("steering", "Steering"),
    "44": ("suspension", "Suspension"),
    "50": ("body-fittings", "Body fittings / Heating"),
    "55": ("electrical", "Electrical"),
    "63": ("fuel-tank", "Fuel tank"),
    "68": ("tools", "Tools"),
    "70": ("body", "Body"),
}

def sh(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)

def tsv_words(png, psm=11, whitelist=None, lang="eng"):
    cfg = f"--psm {psm}"
    if whitelist:
        cfg += f" -c tessedit_char_whitelist={whitelist}"
    r = subprocess.run(["tesseract", str(png), "stdout", "-l", lang, "tsv"] + cfg.split(),
                       capture_output=True, text=True)
    rows = list(csv.reader(io.StringIO(r.stdout), delimiter="\t"))
    out = []
    for row in rows[1:]:
        if len(row) < 12 or not row[11].strip():
            continue
        try:
            conf = float(row[10])
            x, y, w, h = map(int, row[6:10])
        except ValueError:
            continue
        out.append({"text": row[11].strip(), "conf": conf, "x": x, "y": y, "w": w, "h": h})
    return out

def crop(png_path, box, out_path):
    from PIL import Image
    im = Image.open(png_path)
    W, H = im.size
    l, t, r, b = box
    im.crop((int(l*W), int(t*H), int(r*W), int(b*H))).save(out_path)
    return (W, H)

def ocr_plate_number(png, tmp):
    """Bottom-right corner box holds the plate (tavola) number."""
    crop(png, (0.80, 0.88, 1.0, 1.0), tmp)
    words = tsv_words(tmp, psm=6, whitelist="0123456789/-")
    cands = [w["text"] for w in words if re.fullmatch(r"\d{4,5}(/\d)?", w["text"])]
    date = next((w["text"] for w in words if re.fullmatch(r"\d{1,2}-\d{4}", w["text"])), None)
    return (cands[-1] if cands else None), date

def ocr_header(png, tmp):
    """Top strip: 'SGR. NNNNN  TITLE ...' in Italian."""
    crop(png, (0.0, 0.0, 1.0, 0.10), tmp)
    r = subprocess.run(["tesseract", str(tmp), "stdout", "-l", "ita+eng", "--psm", "6"],
                       capture_output=True, text=True)
    text = r.stdout
    m = re.search(r"SGR\W*\s*([\d/]+)\s+(.+)", text)
    if m:
        title = m.group(2).split("\n")[0].strip()
        title = re.sub(r"\s{2,}.*$", "", title)
        title = re.sub(r"^[\d/\s]+", "", title)          # stray sheet digits
        return m.group(1).rstrip("/"), title[:120] or None
    # fallback: longest mostly-uppercase line in the header strip
    best = ""
    for ln in text.splitlines():
        ln = ln.strip()
        letters = re.sub(r"[^A-Za-z]", "", ln)
        if len(letters) > 8 and letters.upper() == letters and len(ln) > len(best):
            best = ln
    return None, (best[:120] or None)

def ocr_part_numbers(png, W, H):
    """Full-page sweep for 6-8 digit part numbers with positions."""
    words = tsv_words(png, psm=11)
    hits = []
    for w in words:
        t = w["text"].rstrip(".,;:")
        if re.fullmatch(r"\d{6,8}", t) and w["conf"] > 25:
            hits.append({
                "pn": t, "conf": round(w["conf"], 1),
                "x": round((w["x"] + w["w"]/2) / W, 4),
                "y": round((w["y"] + w["h"]/2) / H, 4),
                "w": round(w["w"]/W, 4), "h": round(w["h"]/H, 4),
            })
    # dedupe identical number at nearly identical position (psm quirks)
    seen, out = set(), []
    for h in hits:
        key = (h["pn"], round(h["x"], 2), round(h["y"], 2))
        if key not in seen:
            seen.add(key); out.append(h)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--catalog-title", required=True)
    ap.add_argument("--vehicle", default="x19")
    ap.add_argument("--out", required=True)
    ap.add_argument("--db", default="fiat.db")
    ap.add_argument("--schema", default="schema/schema.sql")
    ap.add_argument("--first", type=int, default=1)
    ap.add_argument("--last", type=int, default=0)  # 0 = all
    args = ap.parse_args()

    out = Path(args.out); (out / "pages").mkdir(parents=True, exist_ok=True)
    tmp = out / "_crop.png"

    # --- database ---------------------------------------------------
    new_db = not Path(args.db).exists()
    db = sqlite3.connect(args.db)
    if new_db:
        db.executescript(Path(args.schema).read_text())
    db.execute("INSERT OR IGNORE INTO vehicle(code,name,sort_order) VALUES('x19','Fiat X1/9',1)")
    for code, (slug, name) in GRUPPO.items():
        db.execute("INSERT OR IGNORE INTO category(slug,name,gruppo_code) VALUES(?,?,?)",
                   (slug, name, code))
    vid = db.execute("SELECT id FROM vehicle WHERE code=?", (args.vehicle,)).fetchone()[0]
    db.execute("""INSERT OR IGNORE INTO source(kind,title,url,notes)
                  VALUES('pdf',?,?,?)""",
               (Path(args.pdf).name, "x19.com.au library", "downloaded to archive/raw"))
    sid = db.execute("SELECT id FROM source WHERE title=?", (Path(args.pdf).name,)).fetchone()[0]
    db.execute("""INSERT OR IGNORE INTO catalog(vehicle_id,source_id,title) VALUES(?,?,?)""",
               (vid, sid, args.catalog_title))
    cid = db.execute("SELECT id FROM catalog WHERE title=?", (args.catalog_title,)).fetchone()[0]

    # --- page count -------------------------------------------------
    info = sh(["pdfinfo", args.pdf]).stdout
    npages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
    last = args.last or npages

    stats = {"pages": 0, "plates": 0, "numbers": 0}
    for p in range(args.first, last + 1):
        png = out / "pages" / f"p{p:03d}.png"
        if not png.exists():
            sh(["pdftoppm", "-png", "-r", str(DPI), "-f", str(p), "-l", str(p),
                args.pdf, str(out / "pages" / "tmp")])
            # pdftoppm names it tmp-NNN.png
            produced = list((out / "pages").glob("tmp-*.png"))
            produced[0].rename(png)
        from PIL import Image
        W, H = Image.open(png).size

        tav, date = ocr_plate_number(png, tmp)
        sgr, title = ocr_header(png, tmp)
        tav = tav or sgr or f"p{p:03d}"
        prefix = tav[:2]
        cat = db.execute("SELECT id FROM category WHERE gruppo_code=?", (prefix,)).fetchone()
        cat_id = cat[0] if cat else None

        # multi-sheet plates share a tavola number; keep one plate row
        # per PAGE by suffixing the sheet ("33135", then "33135·2", ...)
        base_tav, n = tav, 2
        while True:
            row = db.execute("""SELECT p.id FROM plate p JOIN plate_page pp ON pp.plate_id=p.id
                                WHERE p.catalog_id=? AND p.tav_code=? AND pp.file_path<>?""",
                             (cid, tav, f"pages/p{p:03d}.png")).fetchone()
            if row is None:
                break
            tav = f"{base_tav}·{n}"; n += 1
        db.execute("""INSERT OR IGNORE INTO plate
                      (catalog_id,category_id,tav_code,title,image_status,width_px,height_px,dzi_path)
                      VALUES(?,?,?,?,?,?,?,?)""",
                   (cid, cat_id, tav, title, "ok", W, H, f"pages/p{p:03d}.png"))
        pid = db.execute("SELECT id FROM plate WHERE catalog_id=? AND tav_code=?",
                         (cid, tav)).fetchone()[0]
        db.execute("""INSERT INTO plate_page(plate_id,source_id,page_kind,file_path,frame_ref,ocr_status)
                      VALUES(?,?,?,?,?,?)""",
                   (pid, sid, "diagram", f"pages/p{p:03d}.png", f"pdf p.{p}", "done"))

        hits = ocr_part_numbers(png, W, H)
        for h in hits:
            db.execute("INSERT OR IGNORE INTO part(part_no,part_no_raw) VALUES(?,?)",
                       (h["pn"], h["pn"]))
            pt = db.execute("SELECT id FROM part WHERE part_no=?", (h["pn"],)).fetchone()[0]
            db.execute("""INSERT INTO part_usage(part_id,plate_id,callout,qty,applicability,verified)
                          VALUES(?,?,?,?,?,0)""",
                       (pt, pid, h["pn"], None, f"ocr_conf={h['conf']}"))
            db.execute("""INSERT OR IGNORE INTO hotspot(plate_id,callout,x,y,r,verified)
                          VALUES(?,?,?,?,?,0)""",
                       (pid, h["pn"], h["x"], h["y"], max(h["w"], 0.02), ))
            stats["numbers"] += 1
        stats["pages"] += 1
        stats["plates"] += 1
        db.commit()
        print(f"p{p:03d}  tav={tav:<10} numbers={len(hits):<3} title={str(title)[:60]}", flush=True)

    print("DONE", stats)

if __name__ == "__main__":
    main()
