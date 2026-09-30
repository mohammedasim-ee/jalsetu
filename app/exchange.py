"""Treated-water exchange: ranked matching of supplier offers to buyer requests.

Hard filters (a pair is only a candidate if all pass):
  1. reuse purpose of the request is in the offer's approved reuse categories (declared by the supplier),
  2. offer treatment level >= request's minimum (secondary < tertiary),
  3. the availability windows overlap.
Score (0–1) for candidates = 0.45 × distance + 0.35 × quantity + 0.20 × availability, where
  distance     = max(0, 1 − km / 25)             (25 km ≈ across the city; transport cost grows with distance)
  quantity     = min(1, offer kL/day ÷ request kL/day)
  availability = overlapping days ÷ requested days
No regulatory quality thresholds are invented: suppliers declare approved uses and treatment level;
the buyer chooses the minimum treatment level they accept.
"""
from __future__ import annotations

import math
from datetime import date

REUSE_CATEGORIES = {
    "construction": "Construction (curing, mixing, dust control)",
    "landscaping": "Gardening and landscaping",
    "flushing": "Toilet flushing",
    "industrial": "Industrial cooling / process",
    "vehicle_washing": "Vehicle washing",
}
TREATMENT_LEVELS = {"secondary": 1, "tertiary": 2}
WEIGHTS = {"distance": 0.45, "quantity": 0.35, "availability": 0.20}
MAX_KM = 25.0


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    (la1, lo1), (la2, lo2) = a, b
    r = math.pi / 180
    h = math.sin((la2 - la1) * r / 2) ** 2 + math.cos(la1 * r) * math.cos(la2 * r) * math.sin((lo2 - lo1) * r / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _d(s: str) -> date:
    return date.fromisoformat(s)


def overlap_days(a_from: str, a_to: str, b_from: str, b_to: str) -> int:
    lo, hi = max(_d(a_from), _d(b_from)), min(_d(a_to), _d(b_to))
    return max(0, (hi - lo).days + 1)


def score_pair(offer: dict, req: dict) -> dict:
    reasons, blocked = [], []
    cats = offer["reuse_categories"] if isinstance(offer["reuse_categories"], list) else offer["reuse_categories"].split(",")
    if req["purpose"] not in cats:
        blocked.append(f"supplier has not approved use for {REUSE_CATEGORIES.get(req['purpose'], req['purpose'])}")
    if TREATMENT_LEVELS[offer["treatment_level"]] < TREATMENT_LEVELS[req["min_treatment"]]:
        blocked.append(f"treatment is {offer['treatment_level']}, buyer needs {req['min_treatment']}")
    ov = overlap_days(offer["available_from"], offer["available_to"], req["needed_from"], req["needed_to"])
    if ov == 0:
        blocked.append("availability dates do not overlap")
    km = haversine_km((offer["lat"], offer["lng"]), (req["lat"], req["lng"]))
    need_days = overlap_days(req["needed_from"], req["needed_to"], req["needed_from"], req["needed_to"])
    parts = {"distance": max(0.0, 1 - km / MAX_KM), "quantity": min(1.0, offer["qty_kl_per_day"] / req["qty_kl_per_day"]),
             "availability": ov / need_days if need_days else 0.0}
    total = sum(WEIGHTS[k] * v for k, v in parts.items())
    reasons.append(f"{km:.1f} km apart")
    reasons.append(f"covers {min(offer['qty_kl_per_day'], req['qty_kl_per_day']):g} of {req['qty_kl_per_day']:g} kL/day")
    reasons.append(f"available {ov} of {need_days} requested days")
    return {"offer_id": offer["id"], "request_id": req["id"], "eligible": not blocked, "blocked_by": blocked,
            "score": round(total, 3) if not blocked else 0.0, "parts": {k: round(v, 3) for k, v in parts.items()},
            "km": round(km, 1), "kl_per_day": min(offer["qty_kl_per_day"], req["qty_kl_per_day"]), "reasons": reasons}


def rank_offers(req: dict, offers: list[dict], fresh_rs_per_kl: float, treated_rs_per_kl: float, include_blocked: bool = False) -> list[dict]:
    out = []
    for o in offers:
        s = score_pair(o, req)
        if not s["eligible"] and not include_blocked:
            continue
        s["offer"] = {k: o[k] for k in ("id", "organization", "area", "qty_kl_per_day", "treatment_level", "available_from", "available_to")}
        s["saving_rs_per_day"] = round(s["kl_per_day"] * max(0.0, fresh_rs_per_kl - treated_rs_per_kl)) if s["eligible"] else 0
        out.append(s)
    return sorted(out, key=lambda s: (-s["eligible"], -s["score"], s["km"]))
