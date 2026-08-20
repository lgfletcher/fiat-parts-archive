#!/usr/bin/env python3
"""
Derive wd_wire rows by pairing wire ends that share a wire number.

    python3 pipeline/derive_wires.py --db fiat.db
    python3 pipeline/derive_wires.py --db fiat.db --diagram wd-1978-aus --sheet 18

On the 1978 Australian master sheet every wire number is printed at both ends
of its wire, so connectivity does not have to be traced — it falls out of the
transcription. Two ends with the same number are one wire.

Anything that is NOT exactly two ends is reported rather than guessed at:

  one end    an end was missed, or a digit was misread into a number that
             doesn't exist elsewhere
  3+ ends    a digit was misread INTO an existing number, so a real wire has
             acquired a phantom third end

Both are transcription errors, not data. This script never invents a wire from
them, and it prints them so the next editing session has a worklist.

Confidence is inherited honestly: a derived wire is 'verified' only when both
its ends are, 'unknown' when either end is, 'typical' otherwise. A colour
mismatch between the two ends downgrades to 'unknown' and is reported — the two
printings of one wire should agree, and when they don't, one of them was
misread.

Only derived wires are rewritten. A hand-traced polyline lives in the same
table, so wires carrying a `path` are preserved: their endpoints get refreshed
from the ends, their geometry is left alone.
"""
import argparse, sqlite3
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="fiat.db")
    ap.add_argument("--diagram", help="limit to one diagram slug")
    ap.add_argument("--sheet", type=int, help="limit to one sheet number")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    db = sqlite3.connect(args.db, timeout=120)
    db.row_factory = sqlite3.Row

    q = """SELECT sh.id, sh.sheet_no, w.slug
           FROM wd_sheet sh JOIN wiring_diagram w ON w.id=sh.diagram_id
           WHERE EXISTS (SELECT 1 FROM wd_wire_end e WHERE e.sheet_id=sh.id)"""
    params = []
    if args.diagram:
        q += " AND w.slug=?"; params.append(args.diagram)
    if args.sheet:
        q += " AND sh.sheet_no=?"; params.append(args.sheet)
    sheets = db.execute(q + " ORDER BY w.sort_order, sh.sheet_no", params).fetchall()

    if not sheets:
        print("no sheets have wire ends yet — nothing to derive")
        return

    grand = defaultdict(int)
    for sh in sheets:
        ends = db.execute("""SELECT wire_no,colour_code,component_code,pin,
                                    circuit_ids,conf,verified
                             FROM wd_wire_end WHERE sheet_id=? ORDER BY wire_no,y""",
                          (sh["id"],)).fetchall()
        by_no = defaultdict(list)
        for e in ends:
            by_no[e["wire_no"].strip()].append(e)

        # keep hand-traced geometry, drop previously derived wires
        traced = db.execute("""SELECT label,path FROM wd_wire
                               WHERE sheet_id=? AND path IS NOT NULL AND path!=''""",
                            (sh["id"],)).fetchall()
        traced_by_label = {t["label"]: t["path"] for t in traced}
        db.execute("DELETE FROM wd_wire WHERE sheet_id=?", (sh["id"],))

        made, singles, over, clash = 0, [], [], []
        for no, group in sorted(by_no.items()):
            if len(group) == 1:
                singles.append(no); continue
            if len(group) > 2:
                over.append((no, len(group))); continue
            a, b = group
            ca = (a["colour_code"] or "").strip().upper()
            cb = (b["colour_code"] or "").strip().upper()
            colour, mismatch = ca or cb, bool(ca and cb and ca != cb)
            if mismatch:
                clash.append((no, ca, cb))

            if a["verified"] and b["verified"] and not mismatch:
                conf = "verified"
            elif mismatch or "unknown" in (a["conf"], b["conf"]):
                conf = "unknown"
            else:
                conf = "typical"

            # a wire belongs to every circuit either of its ends was tagged with
            circuits = sorted({c for e in group
                               for c in (e["circuit_ids"] or "").split(",") if c})
            db.execute("""INSERT INTO wd_wire
                          (sheet_id,label,colour_code,gauge,from_component,from_pin,
                           to_component,to_pin,path,circuit_ids,conf,verified,notes)
                          VALUES(?,?,?,NULL,?,?,?,?,?,?,?,?,?)""",
                       (sh["id"], no, colour or None,
                        a["component_code"], a["pin"],
                        b["component_code"], b["pin"],
                        traced_by_label.get(no),
                        ",".join(circuits) or None,
                        conf, 1 if conf == "verified" else 0,
                        "colour codes disagree between the two ends" if mismatch else None))
            made += 1

        db.commit()
        grand["wires"] += made
        grand["singles"] += len(singles)
        grand["over"] += len(over)
        grand["clash"] += len(clash)

        if args.quiet and not (singles or over or clash):
            continue
        print(f"\n{sh['slug']} sheet {sh['sheet_no']}: "
              f"{len(ends)} ends -> {made} wires")
        if singles:
            print(f"  {len(singles)} number(s) with only one end: "
                  f"{', '.join(singles[:20])}{' …' if len(singles) > 20 else ''}")
        if over:
            print(f"  {len(over)} number(s) with 3+ ends: "
                  + ", ".join(f"{n} ({c})" for n, c in over[:20]))
        if clash:
            print(f"  {len(clash)} colour disagreement(s): "
                  + ", ".join(f"{n}: {a} vs {b}" for n, a, b in clash[:15]))

    print(f"\nTOTAL: {grand['wires']} wires derived; "
          f"{grand['singles']} unpaired, {grand['over']} over-paired, "
          f"{grand['clash']} colour clashes to resolve")


if __name__ == "__main__":
    main()
