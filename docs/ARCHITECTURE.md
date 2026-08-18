# Fiat Classic Parts Archive — Architecture & Schema (v0.1 draft)

*2026-08-18 — for review before any data is ingested.*

## The big picture

```
 physical fiche / PDFs                 BUILD SIDE (private)                PUBLISH SIDE (public)
┌─────────────────────┐    scan     ┌──────────────────────┐   export   ┌──────────────────────┐
│ ~50 fiche sheets    │ ──────────► │ archive/raw/          │ ─────────► │ static site           │
│ community PDFs      │             │  original images,     │            │  - deep-zoom tiles     │
│ existing manuals    │             │  untouched, with      │            │  - JSON indexes        │
└─────────────────────┘             │  provenance metadata  │            │  - viewer (HTML/JS)    │
                                    │ fiat.db (SQLite)      │            │ hosted on GitHub Pages │
                                    │  the schema below     │            │ / Cloudflare Pages     │
                                    └──────────────────────┘            └──────────────────────┘
```

Three principles:

1. **Raw scans are immutable.** Every frame/page goes into `archive/raw/` exactly as scanned and is never edited in place. Cleaned/derived images are generated from them. When a better copy of a plate turns up later, it's added as a new `source` and swapped in — nothing else moves.
2. **The database is the single source of truth; the website is a build artifact.** No server, no production database. The whole site regenerates from `fiat.db` + the image archive with one script. Anyone can mirror the output folder; it can't rot.
3. **Structure comes from the factory.** Categories are Fiat's own *Gruppo* system with friendly names on top; plates keep their printed *Tav.* numbers; parts are keyed by factory part number. Incomplete fiche sets then show up as *visible gaps in a known structure* (which becomes the community "wanted list") rather than silent holes.

## Entity map

```
vehicle ─┬─ vehicle_variant          (X1/9 1300 vs 1500, markets, years)
         └─ catalog ── plate ─┬─ plate_page ── source   (provenance per scan)
                              ├─ hotspot               (clickable callouts, 0..1 coords)
                              └─ part_usage ── part ── part_xref
category (factory Gruppo tree) ── plate
document ── source               (manuals, wiring diagrams, links per vehicle/category)
```

Key design calls, and why:

- **`part` is global, not per-vehicle.** One row per Fiat part number. Cross-model links ("this bearing is also on the 128, Tav. 22") are *derived* from `part_usage` joins — never manually maintained. The `v_shared_parts` view materializes this for the site.
- **`part_usage` carries applicability.** Fiat catalogs qualify rows with variant/chassis restrictions ("fino al telaio…", US-only, etc.). Kept as structured `variant_id` where possible plus the original free text, so we never lose what the catalog actually said.
- **Hotspots use normalized 0–1 coordinates** so they survive re-scanning a plate at higher resolution without re-clicking anything.
- **`qty` is text**, because catalogs say things like "AR" (as required) — forcing integers would corrupt real data.
- **Every `plate_page` points at a `source`.** Two fiche sets + one PDF covering the same catalog is the normal case, not an edge case. `image_status` per plate ('missing' / 'poor' / 'ok' / 'verified') drives the coverage report.
- **`document.hosted` flag** separates what we host (our own scans) from what we link out to (community-hosted PDFs), which keeps the copyright posture deliberate.
- **OCR is never trusted.** `part_usage.verified` and `plate_page.ocr_status` track the human-check pass; the site can badge unverified data.

## Publish-side output (generated, not hand-written)

```
site/
  index.html                     viewer app
  data/
    vehicles.json                models, variants, category tree
    x19/catalog.json             plates per category, coverage status
    x19/plates/034.json          parts table + hotspots for one plate
    search-index.json            part_no + description → plate refs
  tiles/
    x19/034/{z}/{x}_{y}.jpg      deep-zoom tiles (DZI/IIIF layout, OpenSeadragon)
  docs/                          hosted PDFs (own scans only)
```

Static JSON + tiles means free hosting (GitHub Pages / Cloudflare Pages), trivially mirrorable, and no maintenance burden. If community contribution workflows are wanted later (submitting corrections, hotspot fixes), Supabase can be added *beside* this as an intake queue that feeds the build DB — the published site stays static either way.

## Pipeline stages (each a small repeatable script)

1. `ingest` — register raw scans with provenance (source, fiche sheet, frame ref)
2. `prep` — invert (fiche negatives), deskew, crop frames, contrast — derived files only
3. `ocr` — parts tables → draft `part` / `part_usage` rows (Italian + numeric tuned)
4. `verify` — human review UI: side-by-side scan vs extracted rows, tick to confirm
5. `hotspot` — click callouts on the diagram → `hotspot` rows (semi-automated later)
6. `build` — export JSON, generate tiles, emit static site
7. `deploy` — push to hosting

## Open questions (flagged for later, not blockers)

- Exact category list: draft uses ~10 friendly groups mapped to factory Gruppo codes; final mapping comes from the real catalogs' group index pages.
- Hotspot effort policy: full hotspots for popular groups, deep-zoom + side-by-side table for the long tail (decide per real cost after first plates).
- Whether 850 / other models ever join — schema already handles it (just new `vehicle` rows).
