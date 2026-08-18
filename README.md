# Fiat Classic Parts Archive

Source archive + build pipeline for an interactive parts & documentation
platform covering the Fiat X1/9, 124, 125 and 128.

- `docs/ARCHITECTURE.md` — how the whole system works (read this first)
- `schema/schema.sql` — the build database (SQLite) DDL
- `archive/raw/` — **original scans & PDFs, never edited in place**, organized per vehicle
- `archive/derived/` — generated: cleaned images, OCR output, tiles (never hand-edited)
- `archive/sources.yaml` — provenance register: where every file came from
- `pipeline/` — ingest / prep / OCR / tile / build scripts (added as they're written)
- `site/` — static site output; `site/prototype.html` is the current UI prototype

## Adding documents

1. Drop the file into `archive/raw/<vehicle>/` (use `misc/` if it spans models).
   Keep the original filename; do not "clean up" names of source files.
2. Add an entry to `archive/sources.yaml` (template inside — a filename,
   where it came from, and its condition is enough).
3. Commit and push. Claude pulls from this repo each session and takes it
   from there (registration in the DB, page extraction, OCR, tiling).

### File size rules

- Under 100 MB per file: plain git, nothing special needed.
- Over 100 MB: GitHub refuses the push. Options, in order of preference:
  split the PDF into parts (`part1`, `part2` — the pipeline rejoins them),
  or enable Git LFS just for that file (`git lfs track "archive/raw/**/bigfile.pdf"`).
  Big files will ultimately live in object storage (R2) — see ARCHITECTURE.md.

## Ground rules

- Files in `archive/raw/` are immutable once committed. Better copy of the
  same document? Add it alongside with a `-b` suffix and note it in
  `sources.yaml`; the database decides which copy each plate uses.
- `archive/derived/` and `site/` are build products — regenerated, not edited.
