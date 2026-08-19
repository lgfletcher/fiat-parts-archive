#!/usr/bin/env python3
"""
Apply an edits.json (exported from the site's Edit mode) to fiat.db,
and physically rotate any flagged page images.

    python3 pipeline/apply_edits.py edits.json fiat.db archive/derived/factory_catalog/pages

Then re-export the site:
    python3 pipeline/export_site.py --db fiat.db --pages archive/derived/factory_catalog/pages --out docs

Rules:
- 'b<i>' ids refer to the i-th OCR hotspot of that plate (creation order).
- 'n...' ids are new, human-added boxes (verified by definition).
- Edits carry verified=1 where the human ticked the box; a changed part
  number implies verified=1.
- Rotation: image file rotated in place (a .orig copy is kept), hotspot
  coordinates transformed to match, plate width/height swapped for 90/270.
"""
import json, sqlite3, sys
from pathlib import Path
from PIL import Image

def ensure_columns(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info(hotspot)")]
    if "w" not in cols:
        db.execute("ALTER TABLE hotspot ADD COLUMN w REAL")
    if "h" not in cols:
        db.execute("ALTER TABLE hotspot ADD COLUMN h REAL")

def rot_coords(x, y, deg):
    if deg == 90:   return (1 - y, x)
    if deg == 180:  return (1 - x, 1 - y)
    if deg == 270:  return (y, 1 - x)
    return (x, y)

def main():
    edits_file, db_file, pages_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    data = json.load(open(edits_file))
    edits = data.get("edits", data)
    db = sqlite3.connect(db_file); db.row_factory = sqlite3.Row
    ensure_columns(db)

    n_upd = n_add = n_del = n_rot = 0
    for tav, e in edits.items():
        pl = db.execute("SELECT * FROM plate WHERE tav_code=?", (tav,)).fetchone()
        if not pl:
            print(f"!! plate {tav} not in DB — skipped"); continue
        pid = pl["id"]
        base = db.execute(
            "SELECT id, callout FROM hotspot WHERE plate_id=? ORDER BY id", (pid,)).fetchall()

        for hid, ov in (e.get("hs") or {}).items():
            if hid.startswith("b"):
                idx = int(hid[1:])
                if idx >= len(base):
                    print(f"!! {tav} {hid}: no such base hotspot — skipped"); continue
                hrow = base[idx]
                if ov.get("del"):
                    db.execute("DELETE FROM hotspot WHERE id=?", (hrow["id"],))
                    db.execute("""DELETE FROM part_usage WHERE plate_id=? AND callout=?""",
                               (pid, hrow["callout"]))
                    n_del += 1
                    continue
                pn = (ov.get("pn") or hrow["callout"]).strip()
                verified = 1 if (ov.get("verified") or pn != hrow["callout"]) else 0
                db.execute("INSERT OR IGNORE INTO part(part_no,part_no_raw) VALUES(?,?)", (pn, pn))
                ptid = db.execute("SELECT id FROM part WHERE part_no=?", (pn,)).fetchone()[0]
                db.execute("""UPDATE hotspot SET callout=?,
                              x=COALESCE(?,x), y=COALESCE(?,y), w=?, h=?, verified=?
                              WHERE id=?""",
                           (pn, ov.get("x"), ov.get("y"), ov.get("w"), ov.get("h"),
                            verified, hrow["id"]))
                db.execute("""UPDATE part_usage SET part_id=?, callout=?, verified=?
                              WHERE plate_id=? AND callout=?""",
                           (ptid, pn, verified, pid, hrow["callout"]))
                n_upd += 1
            else:  # new box
                if ov.get("del"):
                    continue
                pn = (ov.get("pn") or "").strip()
                if not pn:
                    print(f"!! {tav} {hid}: added box with empty part number — skipped"); continue
                db.execute("INSERT OR IGNORE INTO part(part_no,part_no_raw) VALUES(?,?)", (pn, pn))
                ptid = db.execute("SELECT id FROM part WHERE part_no=?", (pn,)).fetchone()[0]
                db.execute("""INSERT OR IGNORE INTO hotspot(plate_id,callout,x,y,r,w,h,verified)
                              VALUES(?,?,?,?,?,?,?,1)""",
                           (pid, pn, ov["x"], ov["y"], ov.get("w", .04), ov.get("w"), ov.get("h")))
                db.execute("""INSERT INTO part_usage(part_id,plate_id,callout,verified)
                              VALUES(?,?,?,1)""", (ptid, pid, pn))
                n_add += 1

        deg = int(e.get("rotate") or 0) % 360
        if deg:
            img_path = Path(pages_dir) / Path(pl["dzi_path"]).name
            if img_path.exists():
                orig = img_path.with_suffix(img_path.suffix + ".orig")
                if not orig.exists():
                    img_path.rename(orig)
                    Image.open(orig).rotate(-deg, expand=True).save(img_path)
                for hrow in db.execute("SELECT id,x,y FROM hotspot WHERE plate_id=?", (pid,)).fetchall():
                    nx, ny = rot_coords(hrow["x"], hrow["y"], deg)
                    db.execute("UPDATE hotspot SET x=?,y=? WHERE id=?", (nx, ny, hrow["id"]))
                if deg in (90, 270):
                    db.execute("UPDATE plate SET width_px=?, height_px=? WHERE id=?",
                               (pl["height_px"], pl["width_px"], pid))
                n_rot += 1
            else:
                print(f"!! {tav}: page image not found for rotation — skipped")

    db.commit()
    print(f"applied: {n_upd} updated, {n_add} added, {n_del} deleted, {n_rot} rotated")
    print("now re-export: python3 pipeline/export_site.py --db", db_file,
          "--pages", pages_dir, "--out docs")

if __name__ == "__main__":
    main()
