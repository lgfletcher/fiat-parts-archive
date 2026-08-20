-- ============================================================
-- Fiat Classic Parts Archive — build database schema (SQLite)
-- v0.1 draft — 2026-08-18
--
-- This is the WORKING database used during ingestion/curation.
-- The public site is generated FROM this DB as static JSON +
-- image tiles; nothing here runs in production.
-- ============================================================

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------
-- 1. VEHICLES
-- ------------------------------------------------------------

CREATE TABLE vehicle (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,     -- 'x19', '124', '125', '128'
    name        TEXT NOT NULL,            -- 'Fiat X1/9'
    sort_order  INTEGER,
    notes       TEXT
);

-- Variants let applicability be precise without duplicating catalogs.
CREATE TABLE vehicle_variant (
    id          INTEGER PRIMARY KEY,
    vehicle_id  INTEGER NOT NULL REFERENCES vehicle(id),
    code        TEXT NOT NULL,            -- 'x19-1300', 'x19-1500-fi', '124-spider-cs2', '128-3p'
    name        TEXT NOT NULL,
    year_from   INTEGER,
    year_to     INTEGER,
    market      TEXT,                     -- 'EU', 'US', 'AUS', ...
    engine      TEXT,                     -- '1290cc', '1498cc'
    UNIQUE (vehicle_id, code)
);

-- ------------------------------------------------------------
-- 2. CATEGORIES — the factory "Gruppo" system, with friendly
--    names layered on top. Same skeleton across all vehicles,
--    so gaps in incomplete catalogs are visible, not invisible.
-- ------------------------------------------------------------

CREATE TABLE category (
    id          INTEGER PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,     -- 'engine', 'brakes', 'electrical'
    name        TEXT NOT NULL,            -- 'Brakes'
    gruppo_code TEXT,                     -- factory group number as printed, e.g. '004'
    parent_id   INTEGER REFERENCES category(id),   -- allows sub-groups later
    sort_order  INTEGER
);

-- ------------------------------------------------------------
-- 3. PROVENANCE — every asset knows where it came from.
--    Critical for incomplete fiche sets: a second copy of the
--    same catalog can fill gaps or replace poor frames later.
-- ------------------------------------------------------------

CREATE TABLE source (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN
                   ('microfiche','pdf','paper_scan','web','other')),
    title        TEXT NOT NULL,           -- 'X1/9 fiche set A (Leighton)'
    fiche_set    TEXT,                    -- which physical set
    fiche_sheet  TEXT,                    -- sheet ID within the set
    url          TEXT,                    -- for web-sourced material
    license_note TEXT,                    -- 'link only — hosted at mirafiori.com'
    condition    TEXT,                    -- 'good', 'scratched', 'faded'
    acquired_at  TEXT,                    -- ISO date
    notes        TEXT
);

-- A catalog = one factory publication for one vehicle.
CREATE TABLE catalog (
    id          INTEGER PRIMARY KEY,
    vehicle_id  INTEGER NOT NULL REFERENCES vehicle(id),
    source_id   INTEGER REFERENCES source(id),
    catalog_no  TEXT,                     -- factory print no, e.g. '603.10.402'
    title       TEXT NOT NULL,
    edition     TEXT,                     -- '3rd edition 1978'
    language    TEXT,
    pub_year    INTEGER,
    complete    INTEGER DEFAULT 0        -- 1 when every plate is ingested
);

-- ------------------------------------------------------------
-- 4. PLATES (tavole) — one exploded diagram + its parts table.
-- ------------------------------------------------------------

CREATE TABLE plate (
    id           INTEGER PRIMARY KEY,
    catalog_id   INTEGER NOT NULL REFERENCES catalog(id),
    category_id  INTEGER REFERENCES category(id),
    tav_code     TEXT NOT NULL,           -- 'Tav. 34' as printed
    title        TEXT,                    -- 'Rear brake caliper'
    image_status TEXT NOT NULL DEFAULT 'missing'
                 CHECK (image_status IN ('missing','poor','ok','verified')),
    width_px     INTEGER,
    height_px    INTEGER,
    dzi_path     TEXT,                    -- path to generated deep-zoom tiles
    UNIQUE (catalog_id, tav_code)
);

-- Raw page images behind a plate (diagram page, table page(s)),
-- each tied to its source. Multiple rows per plate are normal.
CREATE TABLE plate_page (
    id         INTEGER PRIMARY KEY,
    plate_id   INTEGER NOT NULL REFERENCES plate(id),
    source_id  INTEGER NOT NULL REFERENCES source(id),
    page_kind  TEXT NOT NULL CHECK (page_kind IN ('diagram','table','mixed')),
    file_path  TEXT NOT NULL,             -- archive/raw/... original scan
    frame_ref  TEXT,                      -- fiche grid ref, e.g. 'C7'
    ocr_status TEXT DEFAULT 'pending'
               CHECK (ocr_status IN ('pending','done','verified','n/a')),
    UNIQUE (plate_id, file_path)
);

-- ------------------------------------------------------------
-- 5. PARTS — one row per Fiat part number, shared across all
--    vehicles. Cross-model links fall out of part_usage joins.
-- ------------------------------------------------------------

CREATE TABLE part (
    id             INTEGER PRIMARY KEY,
    part_no        TEXT NOT NULL UNIQUE,  -- normalized: digits only, no spaces/slashes
    part_no_raw    TEXT,                  -- as printed, e.g. '4373339'
    description_it TEXT,                  -- original Italian description
    description_en TEXT,                  -- English translation
    superseded_by  TEXT,                  -- later part_no if factory-superseded
    notes          TEXT
);

-- Where a part appears: which plate, which callout, how many,
-- and with what applicability restriction.
CREATE TABLE part_usage (
    id            INTEGER PRIMARY KEY,
    part_id       INTEGER NOT NULL REFERENCES part(id),
    plate_id      INTEGER NOT NULL REFERENCES plate(id),
    callout       TEXT NOT NULL,          -- number printed on the drawing
    qty           TEXT,                   -- kept as text: '2', 'AR' (as required)
    applicability TEXT,                   -- qualifier from catalog: 'fino al telaio ...'
    variant_id    INTEGER REFERENCES vehicle_variant(id),
    verified      INTEGER DEFAULT 0,      -- OCR checked by a human
    -- A usage is a catalog fact: this part, on this plate, as this
    -- callout. A callout printed several times on the drawing is one
    -- usage with several hotspots, not several usages.
    UNIQUE (part_id, plate_id, callout)
);

CREATE INDEX idx_usage_part  ON part_usage(part_id);
CREATE INDEX idx_usage_plate ON part_usage(plate_id);

-- Clickable regions on the diagram, normalized 0..1 coordinates
-- so they survive re-tiling at any resolution.
CREATE TABLE hotspot (
    id        INTEGER PRIMARY KEY,
    plate_id  INTEGER NOT NULL REFERENCES plate(id),
    callout   TEXT NOT NULL,
    x         REAL NOT NULL,              -- centre x, 0..1
    y         REAL NOT NULL,              -- centre y, 0..1
    r         REAL NOT NULL DEFAULT 0.02, -- radius, fraction of width
    verified  INTEGER DEFAULT 0,
    -- declared after verified to match the column order apply_edits.py
    -- produces when it ALTER TABLEs these onto an existing database
    w         REAL,                       -- box width, fraction of page (edit mode)
    h         REAL,                       -- box height, fraction of page (edit mode)
    -- one row per printed occurrence: the same callout can appear
    -- several times on one drawing, and each is separately clickable
    UNIQUE (plate_id, callout, x, y)
);

-- Aftermarket / equivalent / superseding number cross-references.
CREATE TABLE part_xref (
    id        INTEGER PRIMARY KEY,
    part_id   INTEGER NOT NULL REFERENCES part(id),
    xref_type TEXT NOT NULL CHECK (xref_type IN
                ('aftermarket','equivalent','superseded_by','supersedes')),
    xref_no   TEXT NOT NULL,
    maker     TEXT,                       -- 'ATE', 'Magneti Marelli'
    note      TEXT
);

-- ------------------------------------------------------------
-- 6. LINKED DOCUMENTS — service manuals, wiring diagrams,
--    supplements, community resources, per vehicle/category.
-- ------------------------------------------------------------

CREATE TABLE document (
    id          INTEGER PRIMARY KEY,
    source_id   INTEGER REFERENCES source(id),
    vehicle_id  INTEGER REFERENCES vehicle(id),   -- NULL = applies to several
    category_id INTEGER REFERENCES category(id),  -- NULL = general
    doc_type    TEXT NOT NULL CHECK (doc_type IN
                  ('parts_catalog','service_manual','wiring_diagram',
                   'supplement','bulletin','article','other')),
    title       TEXT NOT NULL,
    url_or_path TEXT NOT NULL,            -- local archive path OR external link
    hosted      INTEGER DEFAULT 0         -- 1 = we host it, 0 = link out
);

CREATE TABLE document_page (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES document(id),
    page_no     INTEGER NOT NULL,
    file_path   TEXT NOT NULL,
    ocr_text    TEXT,
    part_nos    TEXT,            -- comma-separated part numbers detected on page
    ocr_status  TEXT DEFAULT 'done',
    UNIQUE (document_id, page_no)
);

CREATE TABLE document_section (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES document(id),
    block       TEXT,             -- '1974 base', 'Supplement 1', ...
    code        TEXT,             -- gruppo/section number as printed
    title       TEXT,             -- friendly name
    page_from   INTEGER NOT NULL, -- page_no of first page
    page_to     INTEGER NOT NULL,
    verified    INTEGER DEFAULT 0
);

CREATE TABLE document_topic (
    id          INTEGER PRIMARY KEY,
    section_id  INTEGER NOT NULL REFERENCES document_section(id),
    page_no     INTEGER NOT NULL,
    title       TEXT NOT NULL,
    verified    INTEGER DEFAULT 0
);

-- ------------------------------------------------------------
-- 7. CONVENIENCE VIEWS (used by the static-site exporter)
-- ------------------------------------------------------------

-- Everywhere a part number is used, across all vehicles.
CREATE VIEW v_part_everywhere AS
SELECT p.part_no, p.description_en,
       v.code AS vehicle, pl.tav_code, pl.title AS plate_title,
       pu.callout, pu.qty, pu.applicability
FROM part p
JOIN part_usage pu ON pu.part_id = p.id
JOIN plate pl      ON pl.id = pu.plate_id
JOIN catalog c     ON c.id = pl.catalog_id
JOIN vehicle v     ON v.id = c.vehicle_id;

-- Parts shared between two or more vehicles (the cross-link index).
CREATE VIEW v_shared_parts AS
SELECT p.part_no, p.description_en,
       COUNT(DISTINCT c.vehicle_id) AS n_vehicles,
       GROUP_CONCAT(DISTINCT v.code) AS vehicles
FROM part p
JOIN part_usage pu ON pu.part_id = p.id
JOIN plate pl      ON pl.id = pu.plate_id
JOIN catalog c     ON c.id = pl.catalog_id
JOIN vehicle v     ON v.id = c.vehicle_id
GROUP BY p.id
HAVING n_vehicles > 1;

-- Coverage report: what's missing per catalog (the "wanted list").
CREATE VIEW v_coverage AS
SELECT v.code AS vehicle, c.title AS catalog,
       cat.name AS category, pl.tav_code, pl.title, pl.image_status
FROM plate pl
JOIN catalog c    ON c.id = pl.catalog_id
JOIN vehicle v    ON v.id = c.vehicle_id
LEFT JOIN category cat ON cat.id = pl.category_id
ORDER BY v.sort_order, pl.tav_code;

-- ============================================================
-- v0.3 addition (2026-08-20) — WIRING DIAGRAMS
--
-- The wiring viewer is a *registered overlay*: the factory scan is
-- the base layer and traced wires / component boxes live on top of
-- it in the scan's own coordinate space. Phase 1 fills wiring_diagram
-- and wd_sheet (the raster layer); the phase-2 editor fills
-- wd_component / wd_wire / wd_circuit.
--
-- All overlay coordinates are normalized 0..1 against the sheet
-- image, exactly like `hotspot`, so re-rendering a sheet at a
-- different resolution never invalidates a trace.
--
-- Canonical DDL lives in pipeline/ingest_wiring.py (CREATE TABLE IF
-- NOT EXISTS, applied on every run); this copy keeps schema.sql a
-- complete picture of the database.
-- ============================================================

CREATE TABLE IF NOT EXISTS wiring_diagram (
    id           INTEGER PRIMARY KEY,
    slug         TEXT NOT NULL UNIQUE,
    vehicle_id   INTEGER REFERENCES vehicle(id),
    source_id    INTEGER REFERENCES source(id),
    title        TEXT NOT NULL,
    year_from    INTEGER,
    year_to      INTEGER,
    market       TEXT,
    variant_note TEXT,
    credit       TEXT,
    pilot        INTEGER DEFAULT 0,   -- 1 = the sheet the overlay work targets
    sort_order   INTEGER,
    notes        TEXT
);

-- One page of a wiring PDF. 'master' sheets are the fold-out schematics.
CREATE TABLE IF NOT EXISTS wd_sheet (
    id         INTEGER PRIMARY KEY,
    diagram_id INTEGER NOT NULL REFERENCES wiring_diagram(id),
    sheet_no   INTEGER NOT NULL,          -- page order within the diagram
    kind       TEXT NOT NULL DEFAULT 'page'
               CHECK (kind IN ('master','page')),
    label      TEXT,
    file_path  TEXT NOT NULL,             -- relative to the wiring image root
    width_px   INTEGER,
    height_px  INTEGER,
    native_w   INTEGER,                   -- embedded image size in the PDF
    native_h   INTEGER,
    ocr_text   TEXT,
    UNIQUE (diagram_id, sheet_no)
);

-- ---- overlay layer (populated by the phase-2 editor; empty for now) -------
CREATE TABLE IF NOT EXISTS wd_circuit (
    id         INTEGER PRIMARY KEY,
    diagram_id INTEGER REFERENCES wiring_diagram(id),
    code       TEXT NOT NULL,
    name       TEXT,
    grp        TEXT,
    descr      TEXT,
    symptoms   TEXT,
    tests      TEXT,
    colour     TEXT,
    conf       TEXT DEFAULT 'unknown'
               CHECK (conf IN ('verified','typical','unknown')),
    UNIQUE (diagram_id, code)
);

CREATE TABLE IF NOT EXISTS wd_component (
    id        INTEGER PRIMARY KEY,
    sheet_id  INTEGER NOT NULL REFERENCES wd_sheet(id),
    code      TEXT NOT NULL,              -- factory legend number
    name      TEXT,
    name_en   TEXT,
    x REAL, y REAL, w REAL, h REAL,       -- normalized 0..1 box on the sheet
    location_on_car TEXT,
    terminals TEXT,
    part_no   TEXT,
    notes     TEXT,
    conf      TEXT DEFAULT 'unknown'
              CHECK (conf IN ('verified','typical','unknown')),
    verified  INTEGER DEFAULT 0,
    UNIQUE (sheet_id, code)
);

CREATE TABLE IF NOT EXISTS wd_wire (
    id          INTEGER PRIMARY KEY,
    sheet_id    INTEGER NOT NULL REFERENCES wd_sheet(id),
    label       TEXT,
    colour_code TEXT,                     -- Fiat letters, e.g. 'RN', 'V'
    gauge       TEXT,
    from_component TEXT, from_pin TEXT,
    to_component   TEXT, to_pin   TEXT,
    path        TEXT,                     -- JSON [[ [x,y], ... ], ...] normalized
    circuit_ids TEXT,                     -- comma-separated wd_circuit.code
    conf        TEXT DEFAULT 'unknown'
                CHECK (conf IN ('verified','typical','unknown')),
    verified    INTEGER DEFAULT 0,
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS idx_wd_sheet_diagram ON wd_sheet(diagram_id);
CREATE INDEX IF NOT EXISTS idx_wd_comp_sheet    ON wd_component(sheet_id);
CREATE INDEX IF NOT EXISTS idx_wd_wire_sheet    ON wd_wire(sheet_id);
