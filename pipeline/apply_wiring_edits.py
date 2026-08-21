#!/usr/bin/env python3
"""
Apply an editor export into fiat.db.

    python3 pipeline/apply_wiring_edits.py --db fiat.db \
        --edits wiring_edits-wd-1978-aus-s18.json

The editor exports a SNAPSHOT of one sheet, not a patch: everything it knows
about that sheet, every time. So applying is a replace, scoped to that one
sheet. That makes the operation idempotent and makes "what does the database
think this sheet contains" answerable by looking at one file — which matters
more here than merge cleverness, because this is a single-editor workflow.

Nothing outside the named sheet is touched. Derived wires are left alone;
run pipeline/derive_wires.py afterwards to rebuild them from the new ends.
"""
import argparse, json, sqlite3
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="fiat.db")
    ap.add_argument("--edits", required=True, nargs="+",
                    help="one or more editor export files")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = sqlite3.connect(args.db, timeout=120)
    db.row_factory = sqlite3.Row

    for path in args.edits:
        payload = json.loads(Path(path).read_text())
        slug, sheet_no = payload["diagram"], int(payload["sheet"])
        row = db.execute("""SELECT sh.id FROM wd_sheet sh
                            JOIN wiring_diagram w ON w.id=sh.diagram_id
                            WHERE w.slug=? AND sh.sheet_no=?""",
                         (slug, sheet_no)).fetchone()
        if not row:
            print(f"!! {path}: no sheet {sheet_no} on {slug} — skipped")
            continue
        sid = row[0]

        comps = payload.get("components", [])
        ends = payload.get("wire_ends", [])

        # An unnumbered component is a box someone drew and never labelled.
        # Storing it would collide on (sheet_id, code) and tells us nothing.
        keep_comps = [c for c in comps if (c.get("code") or "").strip()]
        keep_ends = [e for e in ends if (e.get("term") or "").strip()]
        dropped_c, dropped_e = len(comps) - len(keep_comps), len(ends) - len(keep_ends)

        before_c = db.execute("SELECT COUNT(*) FROM wd_component WHERE sheet_id=?",
                              (sid,)).fetchone()[0]
        before_e = db.execute("SELECT COUNT(*) FROM wd_wire_end WHERE sheet_id=?",
                              (sid,)).fetchone()[0]

        print(f"{path}\n  {slug} sheet {sheet_no}: "
              f"components {before_c} -> {len(keep_comps)}, "
              f"wire ends {before_e} -> {len(keep_ends)}")
        if dropped_c or dropped_e:
            print(f"  dropped {dropped_c} unnumbered component(s), "
                  f"{dropped_e} terminal(s) with no index")

        # the reciprocity check, reported before anything is written
        ptr = {e["term"].strip(): (e.get("to") or "").strip() for e in keep_ends}
        ok = sum(1 for t, o in ptr.items() if o and ptr.get(o) == t)
        print(f"  reciprocity: {ok} of {len(ptr)} terminals point at a terminal "
              f"that points back")

        if args.dry_run:
            continue

        db.execute("DELETE FROM wd_component WHERE sheet_id=?", (sid,))
        db.execute("DELETE FROM wd_wire_end WHERE sheet_id=?", (sid,))
        for c in keep_comps:
            db.execute("""INSERT INTO wd_component
                          (sheet_id,code,name,name_en,x,y,w,h,location_on_car,
                           terminals,part_no,notes,conf,verified)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (sid, c["code"].strip(), c.get("name"), c.get("en"),
                        c.get("x"), c.get("y"), c.get("w"), c.get("h"),
                        c.get("loc"),
                        json.dumps(c["pins"]) if c.get("pins") else None,
                        c.get("pn"), c.get("notes"),
                        c.get("conf") or "unknown", int(c.get("v") or 0)))
        for e in keep_ends:
            db.execute("""INSERT INTO wd_wire_end
                          (sheet_id,terminal_no,to_terminal,colour_code,
                           component_code,pin,circuit_ids,x,y,src,conf,verified,notes)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (sid, e["term"].strip(), (e.get("to") or "").strip() or None,
                        (e.get("col") or "").strip() or None,
                        (e.get("comp") or "").strip() or None,
                        (e.get("pin") or "").strip() or None,
                        ",".join(sorted({c.strip() for c in (e.get("circuits") or [])
                                         if c.strip()})) or None,
                        e.get("x"), e.get("y"),
                        e.get("src") or "manual", e.get("conf") or "unknown",
                        int(e.get("v") or 0), e.get("notes")))
        db.commit()
        print("  applied")

    if args.dry_run:
        print("\ndry run — nothing written")
    else:
        print("\nnow run: python3 pipeline/derive_wires.py --db fiat.db")


if __name__ == "__main__":
    main()
