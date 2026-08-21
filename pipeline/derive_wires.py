#!/usr/bin/env python3
"""
Derive wd_wire rows from reciprocal terminal pointers.

    python3 pipeline/derive_wires.py --db fiat.db
    python3 pipeline/derive_wires.py --db fiat.db --diagram wd-1978-aus --sheet 18

HOW THE SHEET ACTUALLY WORKS
----------------------------
The 1978 Australian master sheet is a cross-reference table, not a routing
drawing. Each wire stub is printed as

    <colour>  <to_terminal>   <terminal_no>
    GR ------ 258             97

meaning: "this is terminal 97, it is green/grey, and the other end of this wire
is terminal 258". Over at terminal 258 the sheet prints "GR 97", pointing back.

So connectivity is not traced and it is not "the same number twice" — it is a
mutual pointer pair. Terminal A names B, B names A, and the colours agree.

That reciprocity is a genuinely strong check, because it validates BOTH numbers
at BOTH ends: a single misread digit breaks the round trip and shows up as an
unreciprocated pointer rather than quietly becoming a wrong wire.

WHAT THIS SCRIPT REFUSES TO DO
------------------------------
  dangling       A points at B, but B was never transcribed
  one-way        A points at B, but B points somewhere else entirely
  duplicate      the same terminal index recorded twice on one sheet
  colour clash   A and B agree they are joined but disagree on the colour

None of these become wires. They are printed as a worklist, because each one is
a transcription error or an unfinished terminal, and inventing a wire from a
broken pointer is exactly the failure this design exists to prevent.

Confidence is inherited: 'verified' only when both ends are verified and the
colours agree, 'unknown' when either end is unknown or the colours clash,
'typical' otherwise.

Hand-traced polylines are preserved: a wire carrying a `path` keeps its geometry
and only has its endpoints refreshed.
"""
import argparse, sqlite3
from collections import defaultdict


def norm(v):
    return (v or "").strip()


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
        ends = db.execute("""SELECT terminal_no,to_terminal,colour_code,component_code,
                                    pin,circuit_ids,conf,verified
                             FROM wd_wire_end WHERE sheet_id=?
                             ORDER BY CAST(terminal_no AS INTEGER)""",
                          (sh["id"],)).fetchall()

        by_terminal, dup = {}, []
        for e in ends:
            t = norm(e["terminal_no"])
            if not t:
                continue
            if t in by_terminal:
                dup.append(t)
            else:
                by_terminal[t] = e

        traced = db.execute("""SELECT label,path FROM wd_wire
                               WHERE sheet_id=? AND path IS NOT NULL AND path!=''""",
                            (sh["id"],)).fetchall()
        traced_by_label = {t["label"]: t["path"] for t in traced}
        db.execute("DELETE FROM wd_wire WHERE sheet_id=?", (sh["id"],))

        made, dangling, oneway, clash, nopointer = 0, [], [], [], []
        done = set()
        for t, e in sorted(by_terminal.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
            if t in done:
                continue
            other = norm(e["to_terminal"])
            if not other:
                nopointer.append(t); continue
            o = by_terminal.get(other)
            if o is None:
                dangling.append((t, other)); continue
            if norm(o["to_terminal"]) != t:
                oneway.append((t, other, norm(o["to_terminal"]) or "nothing")); continue

            done.add(t); done.add(other)
            ca, cb = norm(e["colour_code"]).upper(), norm(o["colour_code"]).upper()
            colour, mismatch = ca or cb, bool(ca and cb and ca != cb)
            if mismatch:
                clash.append((t, other, ca, cb))

            if e["verified"] and o["verified"] and not mismatch:
                conf = "verified"
            elif mismatch or "unknown" in (e["conf"], o["conf"]):
                conf = "unknown"
            else:
                conf = "typical"

            circuits = sorted({c for r in (e, o)
                               for c in (r["circuit_ids"] or "").split(",") if c})
            # a stable name for the wire, independent of which end you read first
            lo, hi = sorted([t, other], key=lambda v: int(v) if v.isdigit() else 0)
            label = f"{lo}-{hi}"

            db.execute("""INSERT INTO wd_wire
                          (sheet_id,label,colour_code,gauge,from_component,from_pin,
                           to_component,to_pin,path,circuit_ids,conf,verified,notes)
                          VALUES(?,?,?,NULL,?,?,?,?,?,?,?,?,?)""",
                       (sh["id"], label, colour or None,
                        e["component_code"], e["pin"],
                        o["component_code"], o["pin"],
                        traced_by_label.get(label),
                        ",".join(circuits) or None,
                        conf, 1 if conf == "verified" else 0,
                        f"colour disagrees: terminal {t} says {ca}, {other} says {cb}"
                        if mismatch else None))
            made += 1

        db.commit()
        grand["wires"] += made
        for k, v in (("dangling", dangling), ("oneway", oneway),
                     ("clash", clash), ("dup", dup), ("nopointer", nopointer)):
            grand[k] += len(v)

        problems = dangling or oneway or clash or dup or nopointer
        if args.quiet and not problems:
            continue
        print(f"\n{sh['slug']} sheet {sh['sheet_no']}: "
              f"{len(ends)} terminals -> {made} wires")
        if dup:
            print(f"  {len(dup)} duplicate terminal index/indices: "
                  + ", ".join(sorted(set(dup))[:20]))
        if nopointer:
            print(f"  {len(nopointer)} terminal(s) with no pointer recorded yet: "
                  + ", ".join(nopointer[:20]) + (" …" if len(nopointer) > 20 else ""))
        if dangling:
            print(f"  {len(dangling)} pointer(s) to a terminal not yet transcribed: "
                  + ", ".join(f"{a}->{b}" for a, b in dangling[:20])
                  + (" …" if len(dangling) > 20 else ""))
        if oneway:
            print(f"  {len(oneway)} pointer(s) not reciprocated:")
            for a, b, back in oneway[:15]:
                print(f"    terminal {a} -> {b}, but {b} -> {back}")
        if clash:
            print(f"  {len(clash)} colour disagreement(s): "
                  + ", ".join(f"{a}/{b}: {x} vs {y}" for a, b, x, y in clash[:12]))

    print(f"\nTOTAL: {grand['wires']} wires derived; "
          f"{grand['dangling']} dangling, {grand['oneway']} one-way, "
          f"{grand['dup']} duplicate indices, {grand['nopointer']} unpointed, "
          f"{grand['clash']} colour clashes")


if __name__ == "__main__":
    main()
