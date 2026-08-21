#!/usr/bin/env python3
"""
Propose wire-end candidates on a wiring sheet by OCR, for the editor to review.

    python3 pipeline/propose_wire_ends.py --db fiat.db \
        --sheets archive/derived/wiring --diagram wd-1978-aus --sheet 18

VERDICT, MEASURED: not currently worth using on this sheet.
--------------------------------------------------------
The sheet prints each stub as three things on one line — colour code, the index
of the far end, and this terminal's own index. All three have to be read
correctly for a proposal to be usable, and on the pilot sheet tesseract manages
that for 39 of roughly 350 stubs, of which about 6% survive the reciprocity
check. Reviewing 39 mostly-wrong candidates costs more than typing 39 correct
ones.

This was worth measuring, and the measurement is the deliverable: it says the
transcription is a human job on this sheet, and that effort is better spent on
the editor than on the OCR. The script is kept because it is cheap to re-run if
a better scan turns up, and because a future sheet with cleaner printing may
score very differently — the same pipeline will answer that in two minutes.

Earlier revisions of this script scored better only because they were solving a
misreading of the document: they treated the middle number as a wire ID that
appears twice. It is not. It is a pointer to another terminal, and requiring the
pointer AND the terminal AND the colour off one line is the real bar.

Output is a proposal file, never a write to fiat.db. The editor loads it, marks
every candidate unconfirmed and dashed, and a human accepts each one.
"""
import argparse, csv, json, re, subprocess, sqlite3, tempfile
from pathlib import Path

from PIL import Image
Image.MAX_IMAGE_PIXELS = None

# Fiat colour codes: one or two letters from the legend on the sheet itself.
LETTERS = set("NBRVGMACHSLZ")
TILE = 1600          # px; tesseract slows down badly on a 6106 px page
OVERLAP = 120        # px; a token straddling a tile edge is caught by its neighbour


def ocr_tokens(img, psm="11"):
    """[(text, cx, cy, conf)] in image pixel coordinates."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.png"
        img.save(p)
        subprocess.run(["tesseract", str(p), str(Path(td) / "out"), "--psm", psm, "tsv"],
                       capture_output=True, check=True)
        rows = list(csv.DictReader(open(Path(td) / "out.tsv"),
                                   delimiter="\t", quoting=csv.QUOTE_NONE))
    out = []
    for r in rows:
        t = (r.get("text") or "").strip()
        if not t:
            continue
        try:
            l, tp, w, h, c = (int(r["left"]), int(r["top"]), int(r["width"]),
                              int(r["height"]), float(r["conf"]))
        except (ValueError, KeyError):
            continue
        out.append((t, l + w / 2, tp + h / 2, c))
    return out


def scan(img, psm="11"):
    """OCR the whole sheet in overlapping tiles, de-duplicated by position."""
    seen, toks = set(), []
    for y in range(0, img.height, TILE - OVERLAP):
        for x in range(0, img.width, TILE - OVERLAP):
            box = (x, y, min(x + TILE, img.width), min(y + TILE, img.height))
            if box[2] - box[0] < 60 or box[3] - box[1] < 60:
                continue
            for t, cx, cy, conf in ocr_tokens(img.crop(box), psm):
                gx, gy = cx + x, cy + y
                key = (t, round(gx / 12), round(gy / 12))
                if key in seen:
                    continue
                seen.add(key)
                toks.append({"t": t, "x": gx, "y": gy, "conf": conf})
    return toks


def classify(toks):
    numbers, codes = [], []
    for tk in toks:
        t = tk["t"]
        if re.fullmatch(r"\d{1,3}", t):
            numbers.append(tk)
        elif re.fullmatch(r"[A-Z]{1,2}", t) and set(t) <= LETTERS:
            codes.append(tk)
    return numbers, codes


def rows_of(toks, tol=13):
    """Group tokens into printed rows. The stubs are set on tight baselines
    about 26 px apart, so half that is a safe tolerance."""
    out = []
    for t in sorted(toks, key=lambda k: k["y"]):
        for r in out:
            if abs(r[0]["y"] - t["y"]) <= tol:
                r.append(t); break
        else:
            out.append([t])
    return [sorted(r, key=lambda k: k["x"]) for r in out]


def read_stubs(toks):
    """Read '<colour> <to_terminal> <terminal_no>' triples off each printed row.

    The sheet prints a stub as colour, then the index of the far end, then this
    terminal's own index. Left-hand blocks read in that order; the right-hand
    blocks are mirrored, so the row is read from whichever side the colour code
    sits on. Only rows that yield a colour and two numbers are proposed — a
    partial read is worse than no read, because it costs review time and
    supplies nothing the reciprocity check can use.
    """
    stubs = []
    for row in rows_of(toks):
        codes = [t for t in row if re.fullmatch(r"[A-Z]{1,2}", t["t"]) and set(t["t"]) <= LETTERS]
        nums = [t for t in row if re.fullmatch(r"\d{1,3}", t["t"])]
        if len(codes) != 1 or len(nums) < 2:
            continue
        c = codes[0]
        right = [n for n in nums if n["x"] > c["x"]]
        left = [n for n in nums if n["x"] < c["x"]]
        if len(right) >= 2:                 # left-hand block: colour, far, own
            far, own = right[0], right[1]
        elif len(left) >= 2:                # mirrored block: own, far, colour
            own, far = left[0], left[1]
        else:
            continue
        stubs.append({"terminal_no": own["t"], "to_terminal": far["t"],
                      "colour": c["t"],
                      "x": own["x"], "y": own["y"],
                      "conf_ocr": round(min(own["conf"], far["conf"], c["conf"]), 1)})
    return stubs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="fiat.db")
    ap.add_argument("--sheets", default="archive/derived/wiring")
    ap.add_argument("--diagram", default="wd-1978-aus")
    ap.add_argument("--sheet", type=int, default=18)
    ap.add_argument("--out", default="archive/derived/wiring/proposals")
    ap.add_argument("--psm", default="11")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    row = db.execute("""SELECT sh.file_path, sh.width_px, sh.height_px
                        FROM wd_sheet sh JOIN wiring_diagram w ON w.id=sh.diagram_id
                        WHERE w.slug=? AND sh.sheet_no=?""",
                     (args.diagram, args.sheet)).fetchone()
    if not row:
        raise SystemExit(f"no sheet {args.sheet} on {args.diagram}")

    img = Image.open(Path(args.sheets) / row["file_path"]).convert("L")
    W, H = img.size
    print(f"scanning {args.diagram} sheet {args.sheet} — {W} x {H}")

    toks = scan(img, args.psm)
    numbers, codes = classify(toks)
    print(f"  {len(toks)} tokens -> {len(numbers)} numbers, {len(codes)} colour codes")

    stubs = read_stubs(toks)
    print(f"  {len(stubs)} rows read as a complete <colour, far end, this terminal> triple")

    # the sheet's own integrity rule, applied to the OCR: does each pointer
    # point at a terminal that points back?
    by_t = {}
    dups = 0
    for st in stubs:
        if st["terminal_no"] in by_t:
            dups += 1
        else:
            by_t[st["terminal_no"]] = st
    good = [t for t, st in by_t.items()
            if by_t.get(st["to_terminal"], {}).get("to_terminal") == t]
    print(f"  distinct terminals: {len(by_t)}"
          + (f" ({dups} duplicate index/indices)" if dups else ""))
    print(f"    reciprocated round trips: {len(good)} "
          f"({100*len(good)/max(1,len(by_t)):.0f}%)")
    print("    a low figure here is expected and is the honest result — these are")
    print("    review candidates, and the editor shows every one as unconfirmed.")

    if args.report_only:
        return

    ends = []
    for st in stubs:
        ends.append({
            "terminal_no": st["terminal_no"], "to_terminal": st["to_terminal"],
            "colour": st["colour"],
            "x": round(st["x"] / W, 6), "y": round(st["y"] / H, 6),
            "conf_ocr": st["conf_ocr"],
            "reciprocated": st["terminal_no"] in good,
        })
    ends.sort(key=lambda e: (int(e["terminal_no"]) if e["terminal_no"].isdigit() else 0))
    print(f"  {len(ends)} proposed terminals")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    dst = outdir / f"{args.diagram}-s{args.sheet:02d}.json"
    dst.write_text(json.dumps({
        "diagram": args.diagram, "sheet": args.sheet,
        "image_w": W, "image_h": H,
        "psm": args.psm,
        "stats": {"tokens": len(toks), "numbers": len(numbers), "codes": len(codes),
                  "stubs": len(stubs), "terminals": len(by_t),
                  "reciprocated": len(good), "duplicates": dups},
        "ends": ends,
    }, indent=1))
    print(f"  -> {dst}")


if __name__ == "__main__":
    main()
