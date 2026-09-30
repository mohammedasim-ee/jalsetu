"""Indicators stage: validate hand-entered official figures and derive normalised indicators."""
from __future__ import annotations

REQUIRED_PROVENANCE = ("source", "url", "retrieved", "status")
STATUSES = {"live", "historical", "modelled", "demonstration", "simulated", "manually uploaded", "unavailable", "planned integration"}


class IndicatorError(ValueError):
    pass


def _check_prov(obj: dict, where: str, issues: list):
    for k in REQUIRED_PROVENANCE:
        if not obj.get(k):
            issues.append(f"{where}: missing '{k}'")
    if obj.get("status") and obj["status"] not in STATUSES:
        issues.append(f"{where}: unknown status '{obj['status']}'")
    if obj.get("url") and not str(obj["url"]).startswith("https://"):
        issues.append(f"{where}: url must be https")


def _pos(v, where, issues, hi=None):
    if v is None:
        return
    if not isinstance(v, (int, float)) or v < 0 or (hi is not None and v > hi):
        issues.append(f"{where}: value {v!r} out of range")


def process(raw: dict) -> tuple[dict, dict]:
    issues: list[str] = []
    rain = raw["rainfall_current_season"]
    _check_prov(rain, "rainfall_current_season", issues)
    districts = []
    for d in rain["districts"]:
        _pos(d["actual_mm"], f"rain {d['name']} actual", issues)
        _pos(d["normal_mm"], f"rain {d['name']} normal", issues)
        if not d["normal_mm"]:
            issues.append(f"rain {d['name']}: normal must be > 0")
            continue
        anomaly = d["actual_mm"] - d["normal_mm"]
        districts.append({**d, "anomaly_mm": round(anomaly, 1), "departure_pct": round(anomaly / d["normal_mm"] * 100, 1)})

    readings = []
    for i, r in enumerate(raw["reservoir_readings"]):
        _check_prov(r, f"reservoir_readings[{i}]", issues)
        _pos(r.get("storage_tmc"), f"reservoir {r['id']} storage", issues)
        _pos(r.get("capacity_tmc"), f"reservoir {r['id']} capacity", issues)
        _pos(r.get("pct_full"), f"reservoir {r['id']} pct", issues, 100)
        pct = r.get("pct_full")
        if pct is None and r.get("storage_tmc") is not None and r.get("capacity_tmc"):
            if r["storage_tmc"] > r["capacity_tmc"]:
                issues.append(f"reservoir {r['id']}: storage above capacity")
            pct = round(r["storage_tmc"] / r["capacity_tmc"] * 100, 1)
        readings.append({**r, "pct_full": pct, "pct_derived": r.get("pct_full") is None and pct is not None})

    gw = raw["groundwater"]
    for k in ("official_assessment", "city_water_balance", "borewells_dried"):
        _check_prov(gw[k], f"groundwater.{k}", issues)
    bal = gw["city_water_balance"]
    _pos(bal["pumped_mld"], "groundwater pumped", issues)
    if not bal["recharge_mld"]:
        issues.append("groundwater recharge must be > 0")
    groundwater = {
        "official_assessment": gw["official_assessment"],
        "city_water_balance": {**bal, "extraction_ratio": round(bal["pumped_mld"] / bal["recharge_mld"], 2)},
        "borewells_dried": {**gw["borewells_dried"], "share": round(gw["borewells_dried"]["dried"] / gw["borewells_dried"]["total"], 3)},
    }

    ds = raw["demand_supply"]
    for k in ("demand_source", "demand_url", "supply_source", "supply_url"):
        if not ds.get(k):
            issues.append(f"demand_supply: missing {k}")
    gap = (ds["demand_mld"] - ds["supply_mld"]) / ds["demand_mld"]
    demand = {**ds, "gap_mld": ds["demand_mld"] - ds["supply_mld"], "gap_share": round(gap, 3)}

    lq = raw["lake_quality_summary"]
    _check_prov(lq, "lake_quality_summary", issues)
    if lq["lakes_class_a_to_c"] > lq["lakes_monitored"]:
        issues.append("lake_quality_summary: class A–C count above lakes monitored")
    lakes = {**lq, "share_not_a_to_c": round(1 - lq["lakes_class_a_to_c"] / lq["lakes_monitored"], 3)}

    for k in ("sewage", "treated_water_price"):
        _check_prov(raw[k], k, issues)

    if issues:
        raise IndicatorError("Official indicators failed validation:\n- " + "\n- ".join(issues))
    out = {"rainfall_current_season": {**rain, "districts": districts}, "reservoir_readings": readings,
           "groundwater": groundwater, "demand_supply": demand, "lake_quality_summary": lakes,
           "sewage": raw["sewage"], "treated_water_price": raw["treated_water_price"]}
    return out, {"checks_passed": True, "reservoir_readings": len(readings), "districts": len(districts)}
