#!/usr/bin/env python3
"""
Post-OCR cleanup + verification queue.

- Nulls junk titles (the applicability line "VALE PER TUTTI..." is not a title).
- Emits verify_queue.csv: one row per plate with counts and flags, ordered
  by how much human attention it needs (worst first).
"""
import csv, sqlite3, sys

db = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else "fiat.db")
db.row_factory = sqlite3.Row

db.execute("UPDATE plate SET title=NULL WHERE title LIKE 'VALE PER%' OR length(title)<6")
db.commit()

# Counted as correlated subqueries, not joins: one callout can own
# several hotspots, and joining both tables at once would multiply the
# low-confidence tally by the number of times the callout was printed.
rows = db.execute("""
  SELECT pl.tav_code, pl.title, pp.file_path,
         (SELECT COUNT(*) FROM hotspot h
           WHERE h.plate_id = pl.id) AS n_hotspots,
         (SELECT COUNT(*) FROM part_usage pu
           WHERE pu.plate_id = pl.id
             AND pu.applicability LIKE 'ocr_conf=%'
             AND CAST(substr(pu.applicability,10) AS REAL) < 55) AS n_lowconf,
         CASE WHEN pl.tav_code LIKE 'p0%' THEN 1 ELSE 0 END AS tav_missing,
         CASE WHEN pl.title IS NULL THEN 1 ELSE 0 END AS title_missing
  FROM plate pl
  JOIN plate_page pp ON pp.plate_id = pl.id
  GROUP BY pl.id
  ORDER BY tav_missing DESC, (n_hotspots=0) DESC, n_lowconf DESC
""").fetchall()

with open("verify_queue.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["tav", "title", "page", "hotspots", "low_conf", "tav_missing", "title_missing", "action"])
    for r in rows:
        action = []
        if r["tav_missing"]: action.append("read tavola no. from corner")
        if r["title_missing"]: action.append("type title from header")
        if r["n_hotspots"] == 0: action.append("check: really no numbers?")
        if (r["n_lowconf"] or 0) > 0: action.append(f"check {r['n_lowconf']} low-conf numbers")
        w.writerow([r["tav_code"], r["title"], r["file_path"], r["n_hotspots"],
                    r["n_lowconf"] or 0, r["tav_missing"], r["title_missing"],
                    "; ".join(action) or "spot-check only"])

tot = db.execute("SELECT COUNT(*) FROM plate").fetchone()[0]
need = sum(1 for r in rows if r["tav_missing"] or r["title_missing"] or r["n_hotspots"] == 0)
print(f"verify_queue.csv written: {tot} plates, {need} need metadata attention")
