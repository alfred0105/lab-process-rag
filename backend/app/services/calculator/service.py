from dataclasses import dataclass

CONC = {"M": 1.0, "mol/L": 1.0, "mM": 1e-3, "uM": 1e-6, "µM": 1e-6}
VOL = {"L": 1.0, "mL": 1e-3, "uL": 1e-6, "µL": 1e-6}
MASS = {"g": 1.0, "mg": 1e-3, "kg": 1e3}

def amount(concentration: float, concentration_unit: str, volume: float, volume_unit: str):
    c = concentration * CONC[concentration_unit]; v = volume * VOL[volume_unit]
    return {"formula": "n = C * V", "substitution": f"{c:g} mol/L * {v:g} L", "result": c*v, "unit": "mol"}

def mass_from_concentration(concentration: float, concentration_unit: str, volume: float, volume_unit: str, molar_mass: float, molar_mass_unit: str = "g/mol"):
    n = amount(concentration, concentration_unit, volume, volume_unit)["result"]
    g = n*molar_mass
    return {"formula": "m = C * V * M", "substitution": f"{n:g} mol * {molar_mass:g} g/mol", "result": g, "unit": "g"}

def dilution(c1: float, v1: float, c2: float | None = None, v2: float | None = None):
    if c2 is None and v2 is None: raise ValueError("Provide c2 or v2")
    if c2 is None:
        c2 = c1*v1/v2
        return {"formula":"C1 * V1 = C2 * V2", "solved_for":"C2", "result":c2}
    if v2 is None:
        v2 = c1*v1/c2
        return {"formula":"C1 * V1 = C2 * V2", "solved_for":"V2", "result":v2}
    return {"formula":"C1 * V1 = C2 * V2", "result":c1*v1, "check":c2*v2}

def ratio(a: float, b: float, basis: str = "molar"):
    if b == 0: raise ValueError("denominator must be non-zero")
    return {"formula": f"{basis} ratio = A / B", "result": a/b, "unit": f"{basis} ratio"}
