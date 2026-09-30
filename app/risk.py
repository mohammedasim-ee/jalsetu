"""water-risk-engine: explainable, configurable water-risk score and early-warning rules.

Steps: gather indicators -> validate -> normalise each to 0–100 -> weight -> total -> classify -> explain.
The pure functions (normalise, score, warnings) take plain inputs so they can be unit-tested.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from typing import Optional

from . import data_store as ds
from . import db

log = logging.getLogger("jalsetu")


class RiskInputError(ValueError):
    pass


def normalise(value: float, low: float, high: float) -> float:
    """Linear 0–100 between the 'low' (0 risk) and 'high' (100 risk) anchors; works for rising or falling scales."""
    if value is None or not math.isfinite(value):
        raise RiskInputError("indicator value missing")
    if high == low:
        raise RiskInputError("anchors must differ")
    return round(max(0.0, min(100.0, (value - low) / (high - low) * 100)), 1)


def level_for(score: float, levels: list[dict]) -> str:
    lvl = levels[0]["level"]
    for x in sorted(levels, key=lambda l: l["min"]):
        if score >= x["min"]:
            lvl = x["level"]
    return lvl


def validate_inputs(inp: dict) -> None:
    bounds = {"rainfall": (-100, 500), "groundwater": (0, 1000), "reservoir": (0, 100), "demand": (0, 100), "quality": (0, 100), "community": (0, 100000)}
    for k, (lo, hi) in bounds.items():
        v = inp.get(k, {}).get("value")
        if v is None or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
            raise RiskInputError(f"{k}: value {v!r} outside {lo}..{hi}")


def score(inp: dict, cfg: dict) -> dict:
    """inp: {component: {"value": float, "as_of": str, "source": str, "status": str, ...}}"""
    validate_inputs(inp)
    comps = []
    total = 0.0
    for key, c in cfg["components"].items():
        i = inp[key]
        n = normalise(i["value"], c["low"], c["high"])
        pts = round(n * c["weight"], 1)
        total += n * c["weight"]
        age = ds.days_old(i["as_of"]) if i.get("as_of") else None
        comps.append({"key": key, "indicator": c["indicator"], "value": i["value"], "unit": i.get("unit", ""),
                      "normalised": n, "weight": c["weight"], "points": pts, "why_anchor": c["why"],
                      "anchors": {"zero_risk_at": c["low"], "full_risk_at": c["high"]},
                      "as_of": i.get("as_of"), "days_old": age, "stale": age is not None and age > cfg["stale_after_days"].get(key, 365),
                      "source": i.get("source"), "url": i.get("url"), "status": i.get("status"), "note": i.get("note")})
    total = round(total, 1)
    comps.sort(key=lambda x: -x["points"])
    return {"score": total, "level": level_for(total, cfg["levels"]), "components": comps, "config_version": cfg["version"],
            "formula": "score = Σ weight × normalised(indicator); normalised = clamp((value − zero_risk_at) / (full_risk_at − zero_risk_at) × 100, 0, 100)"}


def explain(result: dict) -> list[str]:
    out = [f"Water risk is {result['score']:.0f}/100 ({result['level']})."]
    for c in result["components"]:
        if c["points"] >= 1:
            out.append(f"{c['indicator']}: {c['value']}{c['unit']} → {c['normalised']:.0f}/100 × weight {c['weight']} = +{c['points']} points.")
    stale = [c["indicator"] for c in result["components"] if c["stale"]]
    if stale:
        out.append("Data older than its freshness limit: " + "; ".join(stale) + ". Update data/raw/official_indicators.json.")
    zero = [c["indicator"] for c in result["components"] if c["points"] < 1]
    if zero:
        out.append("Adding little or nothing: " + "; ".join(zero) + ".")
    return out


# ------------------------------------------------------------------ gather real inputs
def verified_reports_30d() -> int:
    try:
        r = db.one("SELECT COUNT(*) AS n FROM reports WHERE status IN ('VERIFIED','RESOLVED') AND created_at >= ? AND is_demo=0",
                   (time.time() - 30 * 86400,))
        return int(r["n"]) if r else 0
    except Exception as e:
        log.warning("verified_reports_count_failed %s", e)
        return 0


def gather_inputs() -> dict:
    ind = ds.indicators()
    rain = ind["rainfall_current_season"]
    urban = rain["districts"][0]
    total = [r for r in ds.reservoir_readings() if r["id"] == "cauvery_total"]
    res = total[-1]
    gw = ind["groundwater"]["official_assessment"]
    dsu = ind["demand_supply"]
    lq = ind["lake_quality_summary"]
    quality_index = round((lq["share_not_a_to_c"] + lq["share_class_e_avg"]) / 2 * 100, 1)
    return {
        "rainfall": {"value": urban["departure_pct"], "unit": "%", "as_of": rain["as_of"], "source": rain["source"], "url": rain["url"],
                     "status": rain["status"], "note": f"{urban['name']}: {urban['actual_mm']} mm vs normal {urban['normal_mm']} mm, {rain['period']}"},
        "groundwater": {"value": gw["stage_of_extraction_pct"], "unit": "%", "as_of": gw["as_of"], "source": gw["source"], "url": gw["url"],
                        "status": gw["status"], "note": gw["assessment"]},
        "reservoir": {"value": res["pct_full"], "unit": "%", "as_of": res["date"], "source": res["source"], "url": res["url"],
                      "status": res["status"], "note": f"{res.get('storage_tmc')} of {res.get('capacity_tmc')} TMC"},
        "demand": {"value": round(dsu["gap_share"] * 100, 1), "unit": "%", "as_of": dsu["supply_as_of"], "source": f"{dsu['demand_source']}; {dsu['supply_source']}",
                   "url": dsu["supply_url"], "status": dsu["status"], "note": f"Demand {dsu['demand_mld']} MLD ({dsu['demand_as_of']}) vs supply {dsu['supply_mld']} MLD ({dsu['supply_as_of']}). {dsu['note']}"},
        "quality": {"value": quality_index, "unit": "", "as_of": lq["as_of"], "source": lq["source"], "url": lq["url"], "status": lq["status"],
                    "note": f"{lq['lakes_class_a_to_c']} of {lq['lakes_monitored']} lakes in class A–C; about {round(lq['share_class_e_avg'] * 100)}% in class E ({lq['period']})"},
        "community": {"value": verified_reports_30d(), "unit": " reports", "as_of": time.strftime("%Y-%m-%d"), "source": "JalSetu database (admin-verified reports)",
                      "url": None, "status": "live", "note": "Counts VERIFIED and RESOLVED reports from the last 30 days"},
    }


def inputs_hash(inp: dict, cfg: dict) -> str:
    key = {k: v["value"] for k, v in inp.items()} | {"_cfg": cfg["version"]}
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def current(record: bool = True) -> dict:
    cfg = ds.risk_config()
    inp = gather_inputs()
    res = score(inp, cfg)
    res["computed_at"] = time.time()
    res["inputs_hash"] = inputs_hash(inp, cfg)
    res["explanation"] = explain(res)
    if record:
        try:
            last = db.one("SELECT inputs_hash FROM risk_scores ORDER BY computed_at DESC LIMIT 1")
            if not last or last["inputs_hash"] != res["inputs_hash"]:
                db.run("INSERT INTO risk_scores(computed_at,score,level,components,inputs_hash,config_version) VALUES(?,?,?,?,?,?)",
                       (res["computed_at"], res["score"], res["level"],
                        json.dumps([{k: c[k] for k in ("key", "value", "normalised", "points")} for c in res["components"]]),
                        res["inputs_hash"], cfg["version"]))
        except Exception as e:   # the score is still returned; only the history snapshot is skipped
            log.warning("risk_snapshot_failed %s", e)
    return res


def history(limit: int = 200) -> list[dict]:
    return [{"computed_at": r["computed_at"], "score": r["score"], "level": r["level"], "components": json.loads(r["components"]),
             "config_version": r["config_version"]}
            for r in db.rows("SELECT * FROM risk_scores ORDER BY computed_at DESC LIMIT ?", (limit,))]


# ------------------------------------------------------------------ early-warning rules
ACTIONS = {
    "rain": ["Build or clean rooftop rainwater harvesting before the northeast monsoon (Oct–Dec).",
             "Reduce non-essential use of piped drinking water (car washing, garden sprinklers)."],
    "reservoir": ["Plan for possible supply cuts: store only what the household needs, fix leaks."],
    "groundwater": ["Recharge borewells with recharge pits and rainwater; avoid new deep borewells.",
                    "Use treated STP water for construction and gardening instead of borewell water."],
    "combined": ["Borewell- and tanker-dependent areas: arrange treated-water reuse and tanker contracts early.",
                 "Apartment associations: meter borewell use and set a monthly limit."],
    "quality": ["Test borewell or lake-adjacent water at an NABL-accredited lab before drinking; use the Quality tab to read the results."],
    "community": ["Ward office/BWSSB: inspect the reported locations; residents: add photos to help verification."],
}


def evaluate_warnings(inp: dict, readings_by_res: dict, hotspots: list[dict], rules: dict) -> list[dict]:
    """Pure rule engine. Returns warnings with level, trigger, indicator, timestamp and actions."""
    now = time.time()
    out = []

    def add(rule_id, level, title, trigger, indicator, actions, as_of=None):
        out.append({"rule_id": rule_id, "level": level, "title": title, "trigger": trigger, "indicator": indicator,
                    "data_as_of": as_of, "generated_at": now, "actions": actions})

    rain = inp["rainfall"]["value"]
    if rain <= rules["rain_warning_pct"]:
        add("RAIN_DEFICIT", "WARNING", "Monsoon rainfall far below normal",
            f"Rainfall departure {rain}% ≤ {rules['rain_warning_pct']}%", "rainfall", ACTIONS["rain"], inp["rainfall"]["as_of"])
    elif rain <= rules["rain_watch_pct"]:
        add("RAIN_DEFICIT", "WATCH", "Monsoon rainfall below normal",
            f"Rainfall departure {rain}% ≤ {rules['rain_watch_pct']}%", "rainfall", ACTIONS["rain"], inp["rainfall"]["as_of"])

    tot = readings_by_res.get("cauvery_total", [])
    if tot:
        cur = tot[-1]["pct_full"]
        declining = len(tot) >= 2 and tot[-1]["pct_full"] is not None and tot[-2]["pct_full"] is not None and tot[-1]["pct_full"] < tot[-2]["pct_full"]
        trend_txt = "declining since previous reading" if declining else ("trend unavailable (one reading)" if len(tot) < 2 else "not declining")
        if cur is not None and cur < rules["reservoir_watch_pct"]:
            add("RESERVOIR_LOW", "WARNING" if declining else "WATCH", "Cauvery reservoirs below half full",
                f"Storage {cur}% < {rules['reservoir_watch_pct']}%; {trend_txt}", "reservoir", ACTIONS["reservoir"], tot[-1]["date"])
        elif declining and rain <= rules["rain_watch_pct"]:
            add("RESERVOIR_FALLING_DRY_SEASON", "WATCH", "Reservoir storage falling while rain is short",
                f"Storage {cur}% and {trend_txt}; rain {rain}%", "reservoir", ACTIONS["reservoir"], tot[-1]["date"])

    gw = inp["groundwater"]["value"]
    if gw > rules["groundwater_overexploited_pct"]:
        add("GROUNDWATER_OVEREXPLOITED", "WARNING", "Groundwater over-exploited",
            f"Stage of extraction {gw}% > {rules['groundwater_overexploited_pct']}% (CGWB 'over-exploited')", "groundwater",
            ACTIONS["groundwater"], inp["groundwater"]["as_of"])
        if rain <= rules["rain_watch_pct"]:
            add("BOREWELL_STRESS", "ALERT", "Water stress rising in borewell-dependent areas",
                f"Rain {rain}% below normal AND groundwater extraction {gw}%: little recharge on top of over-pumping",
                "rainfall + groundwater", ACTIONS["combined"], inp["rainfall"]["as_of"])

    if inp["quality"]["value"] >= 50:
        add("LAKE_QUALITY", "WATCH", "Lake water quality poor",
            f"Lake quality index {inp['quality']['value']} ≥ 50", "quality", ACTIONS["quality"], inp["quality"]["as_of"])

    for h in hotspots:
        if h["reports"] >= rules["community_hotspot_reports"]:
            add(f"HOTSPOT_{h['area']}", "WATCH", f"Many verified reports in {h['area']}",
                f"{h['reports']} verified reports in 30 days ≥ {rules['community_hotspot_reports']}", "community", ACTIONS["community"])
    order = {"ALERT": 0, "WARNING": 1, "WATCH": 2}
    return sorted(out, key=lambda w: order[w["level"]])


def verified_hotspots() -> list[dict]:
    try:
        return db.rows("SELECT area, COUNT(*) AS reports FROM reports WHERE status IN ('VERIFIED','RESOLVED') AND created_at>=? "
                       "AND is_demo=0 GROUP BY area ORDER BY reports DESC", (time.time() - 30 * 86400,))
    except Exception as e:
        log.warning("hotspots_failed %s", e)
        return []


def current_warnings(record: bool = True) -> list[dict]:
    cfg = ds.risk_config()
    ws = evaluate_warnings(gather_inputs(), ds.latest_by_reservoir(), verified_hotspots(), cfg["warning_rules"])
    if record:
        try:
            now = time.time()
            active = {(r["rule_id"], r["level"]): r["id"] for r in db.rows("SELECT id, rule_id, level FROM warnings WHERE active=1")}
            keep = set()
            for w in ws:
                k = (w["rule_id"], w["level"])
                if k in active:
                    db.run("UPDATE warnings SET last_seen=? WHERE id=?", (now, active[k]))
                else:
                    db.run("INSERT INTO warnings(rule_id,level,title,detail,first_seen,last_seen,active) VALUES(?,?,?,?,?,?,1)",
                           (w["rule_id"], w["level"], w["title"], w["trigger"], now, now))
                keep.add(k)
            for k, wid in active.items():
                if k not in keep:
                    db.run("UPDATE warnings SET active=0 WHERE id=?", (wid,))
            first = {(r["rule_id"], r["level"]): r["first_seen"] for r in db.rows("SELECT rule_id, level, first_seen FROM warnings WHERE active=1")}
            for w in ws:
                w["first_seen"] = first.get((w["rule_id"], w["level"]))
        except Exception as e:   # warnings are still returned; only persistence is skipped
            log.warning("warning_persist_failed %s", e)
    return ws


def component(key: str, res: Optional[dict] = None) -> Optional[dict]:
    res = res or current(record=False)
    return next((c for c in res["components"] if c["key"] == key), None)
