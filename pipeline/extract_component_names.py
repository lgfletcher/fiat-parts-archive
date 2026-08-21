#!/usr/bin/env python3
"""
Extract the component legend ("1. Front turn signal lamps ...") from the pages
that accompany a wiring sheet, so the editor can name a callout for you.

    python3 pipeline/extract_component_names.py --db fiat.db \
        --sheets archive/derived/wiring --diagram wd-1978-aus \
        --legend-sheets 19 20 21 --for-sheet 18

On the 1978 Australian diagram the master sheet numbers its components 1..88 and
pages 19-21 list what those numbers mean. Those pages are clean typewriting, not
a scanned schematic, so unlike the wire numbers they OCR very well — which makes
this worth automating where the wire ends were not.

Output is a legend file the editor loads to auto-fill the English name when you
type a callout number. It is still a proposal: it fills a blank field and never
overwrites something you typed, and `--apply` (which writes names into existing
wd_component rows) leaves any row whose name is already set alone.

Sanity is reported, not assumed: the run prints how many numbers were found,
which are missing from the run, and any suspiciously short or duplicated names.
"""
import argparse, json, re, subprocess, sqlite3, tempfile
from pathlib import Path

from PIL import Image
Image.MAX_IMAGE_PIXELS = None

# Permissive on the separator and on leading scanner junk: the typewriter's
# full stop OCRs as ")", "+", "," or ":" often enough to matter.
ENTRY = re.compile(r"^\W{0,6}(?:\d{1,3}\s+)??(\d{1,3})\s*[.)+,:;«»\-]\s+(.{2,})$")


def ocr(img, psm="6"):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "p.png"
        img.save(p)
        r = subprocess.run(["tesseract", str(p), "stdout", "--psm", psm, "-l", "eng"],
                           capture_output=True, text=True, timeout=300)
    return r.stdout


def tidy(s):
    s = re.sub(r"\s+", " ", s).strip(" .;:_,-")
    s = s.replace("|", "l")
    return s


def strip_lead_junk(s):
    """Drop a leading token that is the misread number, not part of the name.

    Every real entry starts with a capital ("Front", "Relay", "Fog"), so a short
    lowercase first token is the wreckage of the number: "die" for 1., "ae" for
    3., "iis" for 11., a stray "l" for a full stop.
    """
    parts = s.strip().split(None, 1)
    if len(parts) == 2 and len(parts[0]) <= 4 and not parts[0][:1].isupper():
        return parts[1].strip()
    return s.strip()


def orphan_kind(text):
    """Is an unnumbered line a new entry whose number was misread, or the
    wrapped tail of the entry above it?

    Entries are typed sentences and always begin with a capital; wrapped tails
    begin with a lowercase word ("relay") or with the continuation of a
    parenthetical ("45/40 W)"). Classifying this BEFORE recovering numbers is
    what stops a wrapped tail being counted as a missing entry, which is how
    entry 3 previously got swallowed into entry 2.
    """
    stripped = strip_lead_junk(text)
    if not stripped:
        return "skip"
    return "entry" if stripped[:1].isupper() else "cont"


def parse(text):
    """Numbered entries, with wrapped continuations folded in and misread
    numbers recovered from the sequence.

    The failure mode on these pages is never the name — it is the number:
    "1." reads as "die", "3." as "ae", "11." as "iis". The list is strictly
    sequential, so a new-entry line sitting between entries n and n+2 can only
    be n+1. That is a fact about the document, not a guess, and it is applied
    only when the gap and the number of new-entry orphans agree exactly.
    """
    rows = []                        # (line_no, number|None, text, kind)
    for i, raw in enumerate(text.splitlines()):
        if not raw.strip():
            continue
        m = ENTRY.match(raw.rstrip())
        if m and 1 <= int(m.group(1)) <= 200:
            rows.append((i, int(m.group(1)), tidy(strip_lead_junk(m.group(2))), None))
        else:
            t = raw.rstrip()
            rows.append((i, None, t, orphan_kind(t)))

    numbered = [r for r in rows if r[1] is not None]
    if not numbered:
        return {}
    out = {n: t for _, n, t, _ in numbered}
    claimed = set()

    # recover misread numbers from the gaps, new-entry orphans only
    for a, b in zip(numbered, numbered[1:]):
        gap = b[1] - a[1]
        if gap <= 1:
            continue
        orphans = [r for r in rows
                   if a[0] < r[0] < b[0] and r[1] is None and r[3] == "entry"]
        if len(orphans) == gap - 1:                 # counts agree — safe
            for k, r in zip(range(a[1] + 1, b[1]), orphans):
                out[k] = tidy(strip_lead_junk(r[2]))
                claimed.add(r[0])

    # a new-entry orphan before the first numbered line is the entry before it
    first = numbered[0]
    if first[1] > 1:
        pre = [r for r in rows
               if r[0] < first[0] and r[1] is None and r[3] == "entry"]
        if pre:
            out.setdefault(first[1] - 1, tidy(strip_lead_junk(pre[-1][2])))
            claimed.add(pre[-1][0])

    # fold wrapped tails into whichever entry they belong under
    owner_at = {}
    cur = None
    for ln, num, txt, kind in rows:
        if num is not None:
            cur = num
        elif ln in claimed:
            # a recovered entry: work out which number it took
            cur = next((k for k, v in out.items()
                        if v == tidy(strip_lead_junk(txt))), cur)
        owner_at[ln] = cur
    for ln, num, txt, kind in rows:
        if num is not None or kind != "cont" or ln in claimed:
            continue
        owner = owner_at.get(ln)
        if owner in out:
            out[owner] = tidy(out[owner] + " " + txt.strip(" .,"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="fiat.db")
    ap.add_argument("--sheets", default="archive/derived/wiring")
    ap.add_argument("--diagram", default="wd-1978-aus")
    ap.add_argument("--legend-sheets", type=int, nargs="+", default=[19, 20, 21],
                    help="sheet numbers holding the numbered legend")
    ap.add_argument("--for-sheet", type=int, default=18,
                    help="the master sheet these numbers label")
    ap.add_argument("--out", default="archive/derived/wiring/legend")
    ap.add_argument("--psm", default="6")
    ap.add_argument("--extra-psm", nargs="*", default=["4"],
                    help="further segmentation modes to merge in (recall, not accuracy)")
    ap.add_argument("--apply", action="store_true",
                    help="also write names into existing wd_component rows that "
                         "have no name yet (never overwrites)")
    args = ap.parse_args()

    db = sqlite3.connect(args.db, timeout=120)
    db.row_factory = sqlite3.Row

    entries, per_sheet = {}, {}
    for n in args.legend_sheets:
        row = db.execute("""SELECT sh.file_path FROM wd_sheet sh
                            JOIN wiring_diagram w ON w.id=sh.diagram_id
                            WHERE w.slug=? AND sh.sheet_no=?""",
                         (args.diagram, n)).fetchone()
        if not row:
            print(f"!! no sheet {n} on {args.diagram} — skipped")
            continue
        img = Image.open(Path(args.sheets) / row["file_path"]).convert("L")
        # Different segmentation modes drop different lines, so run more than
        # one and merge: a number missing from every pass is genuinely missing,
        # which is worth knowing, and a number found by one pass is recovered.
        found = {}
        for mode in dict.fromkeys([args.psm] + args.extra_psm):
            for k, v in parse(ocr(img, mode)).items():
                if k not in found or len(v) > len(found[k]) + 2:
                    found[k] = v
        per_sheet[n] = sorted(found)
        for k, v in found.items():
            entries.setdefault(k, v)      # first sheet to define a number wins
        print(f"  sheet {n}: {len(found)} entries "
              f"({min(found) if found else '-'}–{max(found) if found else '-'})")

    if not entries:
        raise SystemExit("no legend entries found — check --legend-sheets and --psm")

    lo, hi = min(entries), max(entries)
    missing = [i for i in range(lo, hi + 1) if i not in entries]
    short = sorted(k for k, v in entries.items() if len(v) < 4)
    # a lone 2-4 letter token that is not a real word is usually OCR debris
    # sitting in the middle of an otherwise good name ("Instrument panel Abe
    # ballast resistors"). Flag rather than silently "fix".
    OKSHORT = {"and", "or", "for", "the", "w/b", "led", "fan", "low", "oil",
               "air", "off", "on", "of", "to", "a", "up", "rh", "lh", "ac",
               "hi", "no", "in", "id", "am", "fm"}
    suspect = sorted(k for k, v in entries.items()
                     if any(re.fullmatch(r"[A-Za-z]{2,4}", t) and t.lower() not in OKSHORT
                            and not t[:1].isupper() is False and t.lower() not in
                            {w.lower() for w in v.split()[:1]}
                            for t in v.split()[1:])
                     and not any(c.isdigit() for c in v))
    dupes = {}
    for k, v in entries.items():
        dupes.setdefault(v.lower(), []).append(k)
    repeated = {v: ks for v, ks in dupes.items() if len(ks) > 1}

    print(f"\n{len(entries)} components, numbered {lo}–{hi}")
    if missing:
        print(f"  MISSING from the run: {', '.join(map(str, missing))}")
    if short:
        print(f"  suspiciously short (check by eye): {', '.join(map(str, short))}")
    if suspect:
        print(f"  {len(suspect)} name(s) may carry OCR debris — worth an eye:")
        for k in suspect[:10]:
            print(f"    {k}: {entries[k]}")
    if repeated:
        print(f"  {len(repeated)} name(s) used for more than one number "
              f"(often correct — paired lamps etc.):")
        for v, ks in list(repeated.items())[:8]:
            print(f"    {ks} -> {v}")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    dst = outdir / f"{args.diagram}-s{args.for_sheet:02d}.json"
    dst.write_text(json.dumps({
        "diagram": args.diagram, "sheet": args.for_sheet,
        "legend_sheets": args.legend_sheets,
        "count": len(entries), "range": [lo, hi], "missing": missing,
        "suspect": suspect,
        "names": {str(k): entries[k] for k in sorted(entries)},
    }, indent=1))
    print(f"\n-> {dst}")

    if args.apply:
        row = db.execute("""SELECT sh.id FROM wd_sheet sh
                            JOIN wiring_diagram w ON w.id=sh.diagram_id
                            WHERE w.slug=? AND sh.sheet_no=?""",
                         (args.diagram, args.for_sheet)).fetchone()
        if not row:
            raise SystemExit(f"no sheet {args.for_sheet} to apply to")
        n = 0
        for code, name in entries.items():
            n += db.execute("""UPDATE wd_component SET name_en=?
                               WHERE sheet_id=? AND code=?
                                 AND (name_en IS NULL OR name_en='')""",
                            (name, row[0], str(code))).rowcount
        db.commit()
        print(f"named {n} existing component row(s); rows with a name were left alone")


if __name__ == "__main__":
    main()
