"""Official rules used by JalSetu. Every rule here comes from a published source.

- IS 10500:2012 drinking water limits (Bureau of Indian Standards)
- BWSSB rainwater harvesting rules (site size thresholds, storage formula, penalties)
- Distance-based matching of treated-water supply and demand
"""
from __future__ import annotations

import math

# Approximate locality centres (lat, lng), used only to measure distance between areas.
AREAS: dict[str, tuple[float, float]] = {
    "Banashankari": (12.9255, 77.5468), "Basavanagudi": (12.9422, 77.5738),
    "Bellandur": (12.9260, 77.6762), "Bommanahalli": (12.9030, 77.6240),
    "BTM Layout": (12.9166, 77.6101), "Electronic City": (12.8452, 77.6602),
    "Hebbal": (13.0358, 77.5970), "Hennur": (13.0350, 77.6400),
    "HSR Layout": (12.9116, 77.6389), "Indiranagar": (12.9784, 77.6408),
    "Jayanagar": (12.9250, 77.5938), "JP Nagar": (12.9063, 77.5857),
    "Kengeri": (12.9080, 77.4820), "Koramangala": (12.9352, 77.6245),
    "KR Puram": (13.0070, 77.6960), "Mahadevapura": (12.9916, 77.6926),
    "Malleshwaram": (13.0031, 77.5643), "Marathahalli": (12.9569, 77.7011),
    "Peenya": (13.0280, 77.5190), "Rajajinagar": (12.9910, 77.5550),
    "RR Nagar": (12.9274, 77.5155), "Sarjapur Road": (12.9100, 77.6850),
    "Shivajinagar": (12.9857, 77.6057), "Varthur": (12.9380, 77.7410),
    "Vijayanagar": (12.9719, 77.5360), "Whitefield": (12.9698, 77.7500),
    "Yelahanka": (13.1007, 77.5963), "Yeshwanthpur": (13.0280, 77.5400),
}

REPORT_TYPES = {
    "dry": "Borewell dry",
    "low": "Yield dropped",
    "sewage": "Sewage inflow",
    "tanker": "Tanker price",
    "quality": "Bad water",
}
TANKER_SIZES = (6000, 8000, 12000)


def km(a: str, b: str) -> float:
    """Great-circle distance in km between two area centres (haversine)."""
    (la1, lo1), (la2, lo2) = AREAS[a], AREAS[b]
    r = math.pi / 180
    h = (math.sin((la2 - la1) * r / 2) ** 2
         + math.cos(la1 * r) * math.cos(la2 * r) * math.sin((lo2 - lo1) * r / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(h))


def match(listings: list[dict]) -> list[dict]:
    """Greedy nearest-first matching: biggest demands first, each served from the
    closest supply with water left. Unmet demand is returned with from=None."""
    supply = [dict(s, left=s["qty"]) for s in listings if s["kind"] == "supply"]
    demand = sorted((d for d in listings if d["kind"] == "demand"), key=lambda d: -d["qty"])
    out = []
    for d in demand:
        need = d["qty"]
        options = sorted(((s, km(s["area"], d["area"])) for s in supply if s["left"] > 0), key=lambda x: x[1])
        for s, dist in options:
            if need <= 0:
                break
            q = min(need, s["left"])
            s["left"] -= q
            need -= q
            out.append({"from": s["name"], "from_area": s["area"], "to": d["name"], "to_area": d["area"],
                        "kl_per_day": q, "km": round(dist, 1), "within_5km": dist <= 5})
        if need > 0:
            out.append({"from": None, "to": d["name"], "to_area": d["area"], "kl_per_day": need})
    return out


# IS 10500:2012 — key: (label, unit, acceptable, permissible or None = no relaxation, kind)
IS10500 = {
    "pH": ("pH", "", (6.5, 8.5), None, "range"),
    "tds": ("Total dissolved solids", "mg/L", 500, 2000, "max"),
    "turb": ("Turbidity", "NTU", 1, 5, "max"),
    "hard": ("Total hardness (as CaCO3)", "mg/L", 200, 600, "max"),
    "alk": ("Total alkalinity", "mg/L", 200, 600, "max"),
    "ca": ("Calcium", "mg/L", 75, 200, "max"),
    "mg": ("Magnesium", "mg/L", 30, 100, "max"),
    "cl": ("Chloride", "mg/L", 250, 1000, "max"),
    "so4": ("Sulphate", "mg/L", 200, 400, "max"),
    "no3": ("Nitrate", "mg/L", 45, None, "max"),
    "f": ("Fluoride", "mg/L", 1.0, 1.5, "max"),
    "fe": ("Iron", "mg/L", 0.3, None, "max"),
    "mn": ("Manganese", "mg/L", 0.1, 0.3, "max"),
    "nh3": ("Ammonia", "mg/L", 0.5, None, "max"),
    "as": ("Arsenic", "mg/L", 0.01, 0.05, "max"),
    "pb": ("Lead", "mg/L", 0.01, None, "max"),
    "tc": ("Total coliform", "MPN/100 mL", 0, None, "zero"),
    "ec": ("E. coli", "MPN/100 mL", 0, None, "zero"),
}


def judge(key: str, v: float) -> str:
    _, _, acc, perm, kind = IS10500[key]
    if not math.isfinite(v) or v < 0 or (key == "pH" and v > 14):
        return "invalid"
    if kind == "range":
        return "ok" if acc[0] <= v <= acc[1] else "unsafe"
    if kind == "zero":
        return "unsafe" if v > 0 else "ok"
    if v <= acc:
        return "ok"
    if perm is not None and v <= perm:
        return "high"
    return "unsafe"


def check_water(values: dict[str, float]) -> dict:
    results, unsafe, high, invalid = [], [], [], []
    for key, v in values.items():
        if key not in IS10500 or v is None:
            continue
        status = judge(key, float(v))
        label, unit, acc, perm, kind = IS10500[key]
        results.append({"key": key, "label": label, "unit": unit, "value": v, "status": status,
                        "acceptable": acc, "permissible": perm})
        {"unsafe": unsafe, "high": high, "invalid": invalid}.get(status, []).append(label)
    if not [r for r in results if r["status"] != "invalid"]:
        verdict = "no_values"
    elif unsafe:
        verdict = "unsafe"
    elif high:
        verdict = "only_if_no_other_source"
    else:
        verdict = "safe"
    return {"verdict": verdict, "unsafe": unsafe, "above_ideal": high, "invalid": invalid,
            "bacteria_found": any(r["key"] in ("tc", "ec") and r["status"] == "unsafe" for r in results),
            "results": results, "standard": "IS 10500:2012"}


# Average monthly rainfall, Bengaluru, 1991–2021 (climate-data.org), mm
MONTHLY_RAIN_MM = [4, 7, 16, 45, 131, 126, 134, 137, 125, 147, 65, 23]
RUNOFF = 0.8  # share of roof rain captured: a common planning figure for concrete roofs


def rwh_plan(length_ft: float, width_ft: float, built: str, roof_sqm: float, paved_sqm: float,
             monthly_bill: float) -> dict:
    site = max(0.0, length_ft) * max(0.0, width_ft)
    threshold = 1200 if built == "new" else 2400  # BWSSB: 30x40 ft (2009+) / 60x40 ft (before 2009)
    mandatory = site >= threshold
    roof, paved, bill = max(0.0, roof_sqm), max(0.0, paved_sqm), max(0.0, monthly_bill)
    storage_l = roof * 20 + paved * 10  # BWSSB: 20 L per sq m roof + 10 L per sq m paved
    monthly_kl = [round(roof * mm / 1000 * RUNOFF, 2) for mm in MONTHLY_RAIN_MM]
    return {
        "site_sqft": site, "threshold_sqft": threshold, "mandatory": mandatory,
        "min_storage_litres": round(storage_l),
        "yearly_harvest_kl": round(sum(monthly_kl), 1),
        "monthly_harvest_kl": monthly_kl,
        "first_year_penalty_avoided_rs": round(bill * 0.5 * 3 + bill * 9) if mandatory else 0,
        "assumptions": "80% of roof rain captured; rainfall = 1991–2021 monthly averages",
    }
