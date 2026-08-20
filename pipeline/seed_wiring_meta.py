#!/usr/bin/env python3
"""
Seed wd_circuit with the circuit knowledge from the 2026-08 interactive-wiring
prototype, so the phase-2 editor starts from data rather than a blank sheet.

    python3 pipeline/seed_wiring_meta.py --db fiat.db --diagram wd-1978-aus

These rows describe *circuits*, not geometry: what a circuit does, what the
symptoms of its common faults look like, and how to test it. None of it depends
on a wire having been traced yet, so it is useful on the site immediately and
becomes the circuit picker's backing data once tracing starts.

conf: verified / typical / unknown, carried through to the site badges.
Re-runnable: rows are upserted on (diagram_id, code).
"""
import argparse, sqlite3

CIRCUITS = [
    ("start", "Starting", "Power", "verified",
     "Battery → solenoid terminal 30. Turning the key to START sends 12 V out of "
     "ignition terminal 50 to the solenoid, which throws the pinion and closes the "
     "heavy contacts.",
     ["Click but no crank → solenoid, earth strap, or voltage drop on the brown wire",
      "Slow lazy crank → engine earth strap or corroded battery terminals long before it's the starter",
      "Nothing at all with lights working → ignition switch or its 4-pin connector"],
     ["Battery at rest: 12.6 V. Below 12.2 V charge it before diagnosing anything else.",
      "Crank and watch battery voltage — below 9.5 V under crank means battery or cables.",
      "Voltage drop test: probe battery − to engine block while cranking. Anything over 0.3 V is a bad earth."]),

    ("charge", "Charging", "Power", "typical",
     "Alternator B+ feeds back to the solenoid 30 stud and thence to the battery. "
     "D+ drives the dash warning lamp and, on external-regulator cars, the regulator field.",
     ["Warning lamp glows with lights + wipers + heater on → classic X1/9 voltage-drop symptom, not necessarily a failing alternator",
      "No charge at all → check the D+ warning lamp bulb; many alternators will not self-excite without it"],
     ["Engine at 2000 rpm: expect 13.8–14.4 V at the battery.",
      "If you read battery voltage only, check the D+ circuit and the warning lamp bulb.",
      "1978 sits on the internal/external regulator changeover — establish which yours has before ordering parts."]),

    ("run", "Main switched supply (the brown wire)", "Power", "verified",
     "The single most important circuit on the car. Ignition terminal 15 feeds a LARGE "
     "BROWN wire that supplies almost everything downstream. Every switch and connector "
     "in that chain drops a little voltage.",
     ["Everything is a bit weak — dim lights, slow wipers, lazy indicators, sluggish crank — all at once",
      "Symptoms get worse as more loads are switched on"],
     ["Measure at the headlight with everything running. An untouched car typically reads 10.5–11.4 V.",
      "The 'brown wire mod' runs a heavy (10 AWG) wire from battery + to the ignition feed or an auxiliary fuse block.",
      "⚠ FUSE IT. Owners have very nearly burnt cars to the ground doing this unfused. Leave the factory wiring in place; the mod supplements, it does not replace."]),

    ("head", "Headlights (hi / lo)", "Lighting", "verified",
     "Light switch → dip stalk → four beam feeds. The beam wires are black-with-grey (NH) "
     "and black-with-green (NV). Fuses C, D and F are all implicated in high-beam faults.",
     ["Dim yellow headlights → voltage drop, not bulbs",
      "One beam dead → its fuse (C / D / F) or the earth pod behind that headlight",
      "Both dead on high only → dip stalk contacts"],
     ["Best single upgrade on the car: fit 30 A relays on the bulkhead fed direct from the battery, and demote the original NH/NV wires to relay-trigger duty only.",
      "Confirm which of NH / NV is high and which is low on YOUR car before cutting — the pairing is not documented reliably."]),

    ("pods", "Pop-up headlight pods", "Lighting", "verified",
     "Electric motors, controlled through relays E2, E3 and E5. Pods raise when the "
     "lighting slider reaches the sidelight position with the ignition on, and drop when "
     "the ignition is switched off.",
     ["One pod slow or stuck → motor, or a failed diode in that leg",
      "Intermittent operation on both → heat-damaged terminals in the dash light switch",
      "Pods raise but won't drop → relay or the ignition-off signal"],
     ["Diodes in the pod circuit fail often and are hard to test with the motors in place — pull the motor to test properly.",
      "The dash light switch is the usual culprit for intermittent behaviour. A Panda switch plus four relays is the standard fix.",
      "Some relays in the E-series are unfitted on RHD cars — don't assume an empty socket is a fault."]),

    ("park", "Side, tail & plate lamps", "Lighting", "typical",
     "First position of the dash slider. On the Australian car the number plate lamps are "
     "side-mounted in black housings.",
     ["Rear lamps dim or cross-talking with the indicators → rear cluster earth"],
     ["Australian option Carello fog lamps are clear-lens only — yellow lenses failed the ADRs."]),

    ("turn", "Indicators", "Lighting", "typical",
     "Flasher can → column stalk → front, rear and side repeater lamps.",
     ["Slow or lazy flashing → corroded connectors first, then the flasher can itself",
      "Brake lights flash with the indicators → rear cluster earth failure"],
     ["Swapping to LED bulbs needs an electronic flasher or a load resistor."]),

    ("hazard", "Hazard flashers", "Lighting", "typical",
     "Unswitched feed through the dash hazard switch into the flasher, bypassing the ignition.",
     ["Hazards work but indicators don't → the fault is upstream of the flasher, in the ignition-switched supply"],
     []),

    ("stop", "Brake lights", "Lighting", "typical",
     "Pedal-actuated switch on the pedal box feeding both rear stop lamps.",
     ["Stop lamps permanently on → switch adjustment or a collapsed pedal stop",
      "No stop lamps → switch, then the rear cluster earth"],
     []),

    ("rev", "Reverse lights", "Lighting", "typical",
     "Switch on the transaxle housing, fed from a switched fuse.",
     ["Dead → the transaxle switch is exposed and corrodes; test by bridging its two terminals"],
     []),

    ("interior", "Interior lamp", "Body", "typical",
     "Unswitched feed to the lamp; the A-pillar door switches complete the earth side.",
     ["Stays on → a door switch stuck closed or a chafed earth wire in the pillar"], []),

    ("horn", "Horn", "Body", "typical",
     "Unswitched feed to the horn; the wheel-boss push switches the earth through a slip ring.",
     ["Intermittent → the steering wheel slip ring, almost always"], []),

    ("wipe", "Wipers & washer", "Body", "typical",
     "Column stalk selects speed 1 or 2 and triggers the washer pump.",
     ["Slow wipers → voltage drop through the main supply chain, not a tired motor",
      "Won't park → park switch inside the motor gearbox"], []),

    ("hvac", "Heater blower", "Body", "typical",
     "Dash switch, low speed through a resistor pack, high speed direct.",
     ["High speed only → resistor pack open circuit"], []),

    ("ignition", "Ignition (coil & distributor)", "Engine", "typical",
     "Switched supply to the coil positive; the distributor points or module switch the "
     "negative side to earth.",
     ["Cranks but no spark → coil feed, points/module, or condenser",
      "Runs then dies when hot → coil or module heat failure"],
     ["Coil + should see battery voltage with the ignition on.",
      "Check for voltage drop at the coil while cranking — this circuit is fed through the same tired brown wire."]),

    ("fuel", "Fuel pump", "Engine", "verified",
     "A carburettor 1300 Serie Speciale has a MECHANICAL pump driven off the camshaft. "
     "There is no electric fuel pump circuit to trace on a standard car.",
     ["If your car has an electric pump it is a conversion, or the car is a later fuel-injected 1500"],
     ["Where an electric pump has been added, its inline fuse holder is a known melt-down point — the Bakelite ages and fails. Relocate that circuit into a proper fuse box."]),

    ("instr", "Instruments & gauges", "Dash", "typical",
     "Fuel level sender, coolant temp sender, oil pressure switch, alternator D+ tell-tale "
     "and handbrake warning all land at the cluster.",
     ["Every gauge reads low → cluster earth", "One gauge dead → that sender or its single wire"],
     ["Test a sender by earthing its wire — the gauge should swing full scale. If it does, the gauge and wiring are fine and the sender is at fault."]),

    ("aux", "Accessories", "Dash", "typical",
     "Cigar lighter, radio, and heated rear window if fitted.", [],
     ["The lighter socket is a convenient, already-fused place to take a voltmeter reading of the switched supply."]),

    ("power", "Fuse panel distribution", "Power", "typical",
     "Main junction feeding all twelve lettered fuse positions.",
     ["Dead circuit with an intact-looking fuse → barrel fuse end-cap corrosion"],
     ["Twist every barrel fuse in its clips. Clean the clips with a fine abrasive. This alone fixes a surprising number of faults."]),

    ("ground", "Earths & grounds", "Power", "verified",
     "Front bulkhead straps, the 'ground pods' behind each headlight, the engine-to-body "
     "strap, and the rear lamp cluster earths.",
     ["Bizarre cross-talk between circuits — indicators flashing brake lights, gauges moving when lights are switched — is almost always an earth"],
     ["Voltage drop test each earth: probe from battery − to the component body with the circuit loaded. Over 0.2–0.3 V means clean it.",
      "Rebuild with new ring terminals onto bare metal, then seal with a protective compound."]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="fiat.db")
    ap.add_argument("--diagram", default="wd-1978-aus",
                    help="wiring_diagram.slug these circuits describe")
    args = ap.parse_args()

    db = sqlite3.connect(args.db, timeout=120)
    row = db.execute("SELECT id FROM wiring_diagram WHERE slug=?", (args.diagram,)).fetchone()
    if not row:
        raise SystemExit(f"no wiring_diagram with slug {args.diagram!r} — "
                         f"run ingest_wiring.py first")
    did = row[0]
    for code, name, grp, conf, desc, symptoms, tests in CIRCUITS:
        db.execute("""INSERT INTO wd_circuit(diagram_id,code,name,grp,descr,symptoms,tests,conf)
                      VALUES(?,?,?,?,?,?,?,?)
                      ON CONFLICT(diagram_id,code) DO UPDATE SET
                        name=excluded.name, grp=excluded.grp, descr=excluded.descr,
                        symptoms=excluded.symptoms, tests=excluded.tests, conf=excluded.conf""",
                   (did, code, name, grp, desc, "\n".join(symptoms), "\n".join(tests), conf))
    db.commit()
    n = db.execute("SELECT COUNT(*) FROM wd_circuit WHERE diagram_id=?", (did,)).fetchone()[0]
    print(f"seeded {n} circuits on {args.diagram}")


if __name__ == "__main__":
    main()
