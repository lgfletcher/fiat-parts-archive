#!/usr/bin/env python3
"""
Tidy run-together section titles from folder-derived ingestion
("Generalinformation 02" → "General Information 02").

    python3 pipeline/tidy_section_titles.py fiat.db

Greedy longest-match splitter over a technical vocabulary; words not in
the vocabulary are left intact. Re-runnable and safe: only rewrites a
title when every fragment resolves, so it never mangles unknown text.
"""
import re, sqlite3, sys

VOCAB = sorted({
    "general","information","cover","and","contents","engine","assembly",
    "crankcase","crankshaft","camshaft","drive","pistons","valves","auxiliary",
    "drives","fuel","tank","pump","carburator","carburetor","accelerator",
    "linkage","injection","exhaust","lubrication","radiator","water","tools",
    "clutch","transmission","brakes","steering","suspension","accessories",
    "air","conditioning","electrical","body","heater","heating","ventilation",
    "wiring","diagram","ignition","cooling","service","manual","index",
}, key=len, reverse=True)

def split_word(w):
    """Greedy longest-match split of a lowercase run-together word."""
    out, rest = [], w.lower()
    while rest:
        for v in VOCAB:
            if rest.startswith(v):
                out.append(v)
                rest = rest[len(v):]
                break
        else:
            return None            # unknown fragment — refuse to guess
    return out

def tidy(title):
    parts = []
    changed = False
    for tok in title.split():
        if tok.isalpha() and len(tok) > 10:
            sp = split_word(tok)
            if sp and len(sp) > 1:
                parts.extend(s.title() for s in sp)
                changed = True
                continue
        parts.append(tok)
    return (" ".join(parts), changed)

def main():
    db = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else "fiat.db")
    n = 0
    for tbl, col in (("document_section", "title"), ("document_topic", "title")):
        try:
            rows = db.execute(f"SELECT id,{col} FROM {tbl}").fetchall()
        except sqlite3.OperationalError:
            continue
        for rid, t in rows:
            if not t:
                continue
            new, changed = tidy(t)
            if changed:
                db.execute(f"UPDATE {tbl} SET {col}=? WHERE id=?", (new, rid))
                n += 1
    db.commit()
    print(f"tidied {n} titles")

if __name__ == "__main__":
    main()
