#!/usr/bin/env python3
"""
Propose wire-end candidates on a wiring sheet by OCR, for the editor to review.

    python3 pipeline/propose_wire_ends.py --db fiat.db \
        --sheets archive/derived/wiring --diagram wd-1978-aus --sheet 18 \
        --out archive/derived/wiring/proposals

The 1978 Australian master sheet is a numbered-wire cross-reference: every wire
stub carries a Fiat colour code and a wire number, and the same number appears
at both ends of the wire. That last property is the whole point of this script —
it is a free correctness check. A number OCR'd correctly at both ends pairs up;
a misread digit almost always lands on a number that appears once, or three
times. So we do not need OCR to be right, we need it to be right *often*, and
the pairing statistics tell us how often without anyone checking by hand.

Output is a proposal file, never a write to fiat.db. The editor loads it, shows
paired candidates as pre-filled and unpaired ones as flagged, and a human
accepts. Nothing here is trusted.
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


def pair_colour(num, codes, max_dx=420, max_dy=14):
    """A wire number sits at the end of a stub; its colour code is the nearest
    token on the same printed line. Vertical tolerance is tight on purpose —
    the rows are ~26 px apart and grabbing the row above is worse than
    grabbing nothing."""
    best, bestd = None, 1e9
    for c in codes:
        dy = abs(c["y"] - num["y"])
        dx = abs(c["x"] - num["x"])
        if dy <= max_dy and dx <= max_dx and dx < bestd:
            best, bestd = c, dx
    return best


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

    # the free correctness check
    counts = {}
    for n in numbers:
        counts[n["t"]] = counts.get(n["t"], 0) + 1
    paired = sorted(k for k, v in counts.items() if v == 2)
    singles = sorted(k for k, v in counts.items() if v == 1)
    over = sorted(k for k, v in counts.items() if v > 2)
    tot = len(counts)
    print(f"  distinct numbers: {tot}")
    print(f"    appear exactly twice (pair cleanly): {len(paired)}"
          f"  ({100*len(paired)/max(1,tot):.0f}%)")
    print(f"    appear once  (likely a missed or misread end): {len(singles)}")
    print(f"    appear 3+    (likely a misread of another number): {len(over)}")
    if over:
        print(f"      {', '.join(f'{k}x{counts[k]}' for k in over[:15])}")

    if args.report_only:
        return

    ends = []
    for n in numbers:
        c = pair_colour(n, codes)
        ends.append({
            "wire_no": n["t"],
            "colour": c["t"] if c else None,
            "x": round(n["x"] / W, 6), "y": round(n["y"] / H, 6),
            "conf_ocr": round(n["conf"], 1),
            "pairs": counts[n["t"]] == 2,
        })
    ends.sort(key=lambda e: (e["wire_no"], e["y"]))
    with_colour = sum(1 for e in ends if e["colour"])
    print(f"  {len(ends)} proposed ends, {with_colour} with a colour code attached")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    dst = outdir / f"{args.diagram}-s{args.sheet:02d}.json"
    dst.write_text(json.dumps({
        "diagram": args.diagram, "sheet": args.sheet,
        "image_w": W, "image_h": H,
        "psm": args.psm,
        "stats": {"tokens": len(toks), "numbers": len(numbers), "codes": len(codes),
                  "distinct": tot, "paired": len(paired),
                  "singles": len(singles), "over": len(over)},
        "ends": ends,
    }, indent=1))
    print(f"  -> {dst}")


if __name__ == "__main__":
    main()
