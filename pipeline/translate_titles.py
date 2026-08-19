#!/usr/bin/env python3
"""
Add English plate titles (title_en) alongside the OCR'd Italian ones.

    python3 pipeline/translate_titles.py fiat.db

Dictionary-based: factory plate captions are formulaic, so a curated
phrase table covers them. Unknown phrases are left NULL (Italian shown
alone until a human or a later pass fills them). Re-runnable.
"""
import re, sqlite3, sys

PHRASES = {
    "MOTORE": "Engine (complete)",
    "SOSPENSIONI GRUPPO MOTOPROPULSORE": "Engine & powertrain mountings",
    "BASAMENTO E TESTA CILINDRI": "Crankcase & cylinder head",
    "COPPA E COPERCHI BASAMENTO": "Sump & crankcase covers",
    "DISTRIBUZIONE": "Valve timing / camshaft drive",
    "COMANDI VARI": "Miscellaneous controls",
    "POMPA ALIMENTAZIONE E TUBAZIONI": "Fuel pump & pipes",
    "FILTRO ARIA": "Air filter",
    "CARBURATORE": "Carburettor",
    "COMANDI ACCELERATORE E CARBURATORE": "Accelerator & carburettor controls",
    "TUBAZIONE DI SCARICO": "Exhaust system",
    "LUBRIFICAZIONE": "Lubrication",
    "RADIATORE": "Radiator",
    "POMPA ACQUA E TUBAZIONI": "Water pump & pipes",
    "COMANDO DISINNESTO FRIZIONE": "Clutch release control",
    "COMANDO IDRAULICO DISINNESTO FRIZIONE": "Hydraulic clutch release control",
    "CILINDRO COMANDO DISINNESTO": "Clutch slave cylinder",
    "CAMBIO E DIFFERENZIALE SCATOLA E COPERCHI": "Gearbox & differential — casing & covers",
    "COMANDI ESTERNI CAMBIO DI VELOCITA": "External gearchange linkage",
    "SEMIALBERI DIFFERENZIALE": "Driveshafts",
    "RISCALDAMENTO E VENTILAZIONE": "Heating & ventilation",
    "COMANDO IDRAULICO FRENI": "Hydraulic brake system",
    "CILINDRO MAESTRO": "Brake master cylinder",
    "PINZA ANTERIORE DESTRA": "Front brake caliper, right",
    "PINZA ANTERIORE SINISTRA": "Front brake caliper, left",
    "FRENI RUOTE POSTERIORI": "Rear wheel brakes",
    "PINZA POSTERIORE DESTRA": "Rear brake caliper, right",
    "PINZA POSTERIORE SINISTRA": "Rear brake caliper, left",
    "COMANDO A MANO FRENI": "Handbrake control",
    "COMANDO STERZO": "Steering linkage",
    "SCATOLA STERZO": "Steering rack",
    "SOSPENSIONE ANTERIORE": "Front suspension",
    "SOSPENSIONE POSTERIORE": "Rear suspension",
    "RISCALDATORE": "Heater unit",
    "MOTORINO DI AVVIAMENTO": "Starter motor",
    "GENERAZIONE DI CORRENTE": "Alternator & charging",
    "PROIETTORE": "Headlamp",
    "FANALE POSTERIORE": "Rear lamp cluster",
    "FANALE ANTERIORE": "Front lamp / indicator",
    "SEGNALAZIONI DI FUNZIONAMENTO": "Instruments & warning indicators",
    "SEGNALAZIONE DI AVVISO E DI MANOVRA": "Warning & indicator signals",
    "ACCESSORI VARI": "Miscellaneous electrical accessories",
    "ATTREZZI": "Toolkit",
    "COMANDI RISCALDAMENTO E VENTILAZIONE": "Heating & ventilation controls",
    "LAVACRISTALLO": "Windscreen washer",
    "DISTRIBUTORE DI ACCENSIONE": "Ignition distributor",
    "ILLUMINAZIONE ESTERNA ED INTERNA": "Exterior & interior lighting",
}

def clean(it):
    t = it.upper()
    t = re.sub(r"\d{5,}", " ", t)          # drop embedded assembly numbers
    t = re.sub(r"[|.,;:]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s*\(([A-Z]+)\)$", "", t)  # trailing maker "(WEBER)" handled below
    return t

def maker(it):
    m = re.search(r"\(([A-Za-z]+)\)", it)
    return f" ({m.group(1).title()})" if m else ""

def assy(it):
    m = re.search(r"(\d{6,})", it)
    return f" — assy {m.group(1)}" if m else ""

def main():
    db = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else "fiat.db")
    cols = [r[1] for r in db.execute("PRAGMA table_info(plate)")]
    if "title_en" not in cols:
        db.execute("ALTER TABLE plate ADD COLUMN title_en TEXT")
    n = 0
    for pid, it in db.execute("SELECT id,title FROM plate WHERE title IS NOT NULL").fetchall():
        en = PHRASES.get(clean(it))
        if en:
            db.execute("UPDATE plate SET title_en=? WHERE id=?", (en + maker(it) + assy(it), pid))
            n += 1
    db.commit()
    total = db.execute("SELECT COUNT(*) FROM plate WHERE title IS NOT NULL").fetchone()[0]
    print(f"translated {n}/{total} titled plates")

if __name__ == "__main__":
    main()
