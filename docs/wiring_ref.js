/* ============================================================
   Fiat wiring reference data — hand-maintained, NOT generated.
   Ported from the 2026-08 interactive-wiring prototype.

   conf: "v" verified against a documented source
         "t" typical / conventional for the platform, UNCONFIRMED
         "u" unknown

   This file holds only knowledge that is true of the paper —
   colour codes, fuse-panel lore, circuit descriptions. Anything
   with coordinates (traced wires, component boxes) is generated
   from fiat.db into docs/wiringdata/<slug>.js instead.
   ============================================================ */

window.WIRE_COLOURS = {
  N: { it: "Nero",      en: "Black",       hex: "#1b1b1f", ink: "#fff" },
  B: { it: "Bianco",    en: "White",       hex: "#f2f2f0", ink: "#000" },
  R: { it: "Rosso",     en: "Red",         hex: "#d5232c", ink: "#fff" },
  V: { it: "Verde",     en: "Green",       hex: "#1f9d55", ink: "#fff" },
  G: { it: "Giallo",    en: "Yellow",      hex: "#e8c520", ink: "#000" },
  M: { it: "Marrone",   en: "Brown",       hex: "#7a4a22", ink: "#fff" },
  A: { it: "Azzurro",   en: "Light blue",  hex: "#5bb7e8", ink: "#000" },
  C: { it: "Arancione", en: "Orange",      hex: "#ef7d1a", ink: "#000" },
  H: { it: "Grigio",    en: "Grey",        hex: "#9aa0a6", ink: "#000" },
  S: { it: "Rosa",      en: "Pink",        hex: "#f09ab2", ink: "#000" },
  L: { it: "Blu",       en: "Blue (dark)", hex: "#2a49b8", ink: "#fff" },
  Z: { it: "Viola",     en: "Violet",      hex: "#8b46c4", ink: "#fff" }
};

window.WIRE_GOTCHAS = [
  "B is BIANCO = WHITE, not black. N is NERO = BLACK. This trips up nearly everyone reading a Fiat diagram for the first time.",
  "A (azzurro, light blue) and L (blu, dark blue) are different wires. On a faded scan they look identical — read the letter, not the ink.",
  "Two-letter codes are base colour first, tracer second. RV = red wire with green stripes.",
  "Fuses on a Series 1 are lettered A–N, not numbered. J and K are skipped: they aren't Italian letters.",
  "Any numbered 1–12 fuse chart you find online is for the 1984+ Bertone ATC blade panel and does not apply to a Series 1 car."
];

window.WIRE_KNOWN_COLOURS = [
  { circuit: "Headlight beam feeds", code: "NH", desc: "Black with grey tracer", conf: "v" },
  { circuit: "Headlight beam feeds", code: "NV", desc: "Black with green tracer", conf: "v" },
  { circuit: "Main switched feed at ignition switch", code: "M", desc: "Large brown — the 'brown wire'", conf: "v" },
  { circuit: "Earths throughout", code: "N", desc: "Black", conf: "t" }
];

/* Series 1 (1974–1982) lettered fuse panel. Applies to the 1974/1978/1979/1981
   diagrams; the Bertone car uses a numbered blade panel instead. */
window.WIRE_FUSES = [
  { id: "A", amps: "?", feeds: "Unconfirmed — read from your factory diagram", conf: "u",
    note: "The factory manual has a dedicated 'Fuse A blows repeatedly' section, so A carries a fault-prone circuit." },
  { id: "B", amps: "?", feeds: "Unconfirmed", conf: "u",
    note: "'Fuse B blows repeatedly' section exists in the factory manual." },
  { id: "C", amps: "?", feeds: "HIGH BEAM circuit (one side)", conf: "v",
    note: "Factory manual: 'Fuse C blows when high beams are turned on.'" },
  { id: "D", amps: "?", feeds: "HIGH BEAM circuit", conf: "v",
    note: "Factory manual pairs D and F: 'Fuse D/F blows when high beams are turned on.'" },
  { id: "E", amps: "?", feeds: "Unconfirmed — existence itself uncertain", conf: "u",
    note: "E has no dedicated troubleshooting section in the factory manual index; the panel may be 11 or 12 way." },
  { id: "F", amps: "?", feeds: "HIGH BEAM circuit", conf: "v", note: "Paired with D in the factory manual." },
  { id: "G", amps: "?", feeds: "Unconfirmed", conf: "u", note: "'Fuse G blows repeatedly' section exists." },
  { id: "H", amps: "?", feeds: "Unconfirmed", conf: "u", note: "'Fuse H blows repeatedly' section exists." },
  { id: "I", amps: "?", feeds: "Unconfirmed", conf: "u", note: "'Fuse I blows repeatedly' section exists." },
  { id: "L", amps: "?", feeds: "Unconfirmed", conf: "u",
    note: "'Fuse L blows repeatedly' section exists. (J and K are skipped — not Italian letters.)" },
  { id: "M", amps: "?", feeds: "Unconfirmed", conf: "u",
    note: "Paired with N in the factory manual: 'Fuse M/N blows repeatedly.'" },
  { id: "N", amps: "?", feeds: "Unconfirmed", conf: "u", note: "Paired with M in the factory manual." }
];

window.WIRE_FUSE_NOTES = [
  "Series 1 cars use OLD CYLINDRICAL CERAMIC ('barrel' / torpedo) fuses, not blades.",
  "Barrel fuses build surface corrosion on the end caps and stop making contact — a very common cause of a dead circuit with an apparently intact fuse. Twist each one in its clips before condemning anything else.",
  "Do NOT use a numbered 1–12 fuse chart found online. Those charts are for the 1984+ Bertone ATC blade panel — a completely different fuse box.",
  "The letters run A B C D E F G H I L M N. J and K are skipped because they are not letters in the Italian alphabet."
];
