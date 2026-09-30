"""Read APIs: water data with provenance, risk, warnings, forecasts, ML, GIS, calculators."""
from __future__ import annotations

import json
import time
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from . import data_store as ds
from . import db, ml_runtime, risk, rules
from .common import jlog, log, rate_limit

router = APIRouter(prefix="/api")


def prov(obj: dict, keys=("source", "url", "as_of", "period", "status", "retrieved")) -> dict:
    return {k: obj.get(k) for k in keys if obj.get(k) is not None}


# ------------------------------------------------------------------ risk + warnings
@router.get("/risk/current")
def risk_current():
    r = risk.current()
    return {k: r[k] for k in ("score", "level", "components", "computed_at", "config_version", "formula", "explanation")}


@router.get("/risk/explanation")
def risk_explanation():
    r = risk.current(record=False)
    cfg = ds.risk_config()
    return {"score": r["score"], "level": r["level"], "explanation": r["explanation"], "formula": r["formula"],
            "levels": cfg["levels"], "weights": {k: v["weight"] for k, v in cfg["components"].items()},
            "components": r["components"], "methodology": "docs/water-risk-methodology.md"}


@router.get("/risk/history")
def risk_history(limit: int = Query(200, ge=1, le=1000)):
    h = risk.history(limit)
    return {"count": len(h), "history": h,
            "note": "A snapshot is stored whenever an input value or the configuration changes. History starts at the first computation after deployment."}


@router.get("/warnings")
def warnings():
    ws = risk.current_warnings()
    return {"count": len(ws), "warnings": ws,
            "note": "Rule-based early warnings computed from the official indicators and verified reports. These are JalSetu planning signals, not official government warnings."}


# ------------------------------------------------------------------ rainfall
@router.get("/rainfall")
def rainfall():
    a = ds.processed("rainfall_analysis.json")
    cur = ds.indicators()["rainfall_current_season"]
    seasons = a["seasons"]
    return {"current_season": {**prov(cur), "districts": cur["districts"]},
            "historical": {"subdivision": a["subdivision"], "years": a["years"], "baseline": a["baseline"], "source": a["source"],
                           "annual_mean_mm": a["annual_mean_mm"], "jjas_mean_mm": a["jjas_mean_mm"], "ond_mean_mm": a["ond_mean_mm"],
                           "climatology": a["climatology"], "trend_annual": a["trend_annual"], "trend_jjas": a["trend_jjas"],
                           "mann_kendall_annual": a["mann_kendall_annual"], "mann_kendall_jjas": a["mann_kendall_jjas"],
                           "jjas_category_counts": a["jjas_category_counts"],
                           "last_10_seasons": seasons[-10:],
                           "driest_seasons": sorted(seasons, key=lambda s: s["jjas_departure_pct"])[:5],
                           "wettest_seasons": sorted(seasons, key=lambda s: -s["jjas_departure_pct"])[:5]},
            "formula": {"anomaly_mm": "observed − expected (1901–2015 mean for that month or season)",
                        "anomaly_pct": "(observed − expected) ÷ expected × 100"}}


@router.get("/rainfall/history")
def rainfall_history(start: int = Query(1901, ge=1901, le=2015), end: int = Query(2015, ge=1901, le=2015),
                     monthly: bool = False):
    if start > end:
        raise HTTPException(422, "start must be before end")
    a = ds.processed("rainfall_analysis.json")
    out = {"seasons": [s for s in a["seasons"] if start <= s["year"] <= end], "source": a["source"]}
    if monthly:
        out["monthly"] = [m for m in ds.monthly_rainfall() if start <= m["year"] <= end]
    return out


# ------------------------------------------------------------------ reservoirs
def _reservoir_summary(rid: str, readings: list[dict]) -> dict:
    last = readings[-1]
    prev = readings[-2] if len(readings) > 1 else None
    trend = None
    if prev and last["pct_full"] is not None and prev["pct_full"] is not None:
        trend = {"change_pct_points": round(last["pct_full"] - prev["pct_full"], 1), "since": prev["date"]}
    return {"id": rid, "reservoir": last["reservoir"], "latest": last, "readings": len(readings), "trend": trend,
            "trend_note": None if trend else "Only one reading so far; trend appears after the next reading is added."}


@router.get("/reservoirs")
def reservoirs():
    by = ds.latest_by_reservoir()
    res = risk.component("reservoir")
    return {"reservoirs": [_reservoir_summary(k, v) for k, v in by.items()], "risk_contribution": res,
            "ingestion": "Admins add new readings through POST /api/admin/reservoir-readings (source and URL required)."}


@router.get("/reservoirs/history")
def reservoirs_history():
    return {"readings": ds.reservoir_readings()}


@router.get("/reservoirs/{rid}")
def reservoir(rid: str):
    by = ds.latest_by_reservoir()
    if rid not in by:
        raise HTTPException(404, "Unknown reservoir.")
    return {**_reservoir_summary(rid, by[rid]), "history": by[rid]}


# ------------------------------------------------------------------ groundwater
@router.get("/groundwater")
def groundwater():
    g = ds.indicators()["groundwater"]
    oa = g["official_assessment"]
    stage = oa["stage_of_extraction_pct"]
    cat = "safe" if stage <= 70 else "semi-critical" if stage <= 90 else "critical" if stage <= 100 else "over-exploited"
    comp = risk.component("groundwater")
    return {"official": {**oa, "category": cat, "data_type": "REAL (official assessment)"},
            "modelled": {**g["city_water_balance"], "data_type": "ESTIMATED / MODELLED",
                         "extraction_pressure": f"About {g['city_water_balance']['extraction_ratio']}× more pumped than naturally recharged"},
            "observed": {**g["borewells_dried"], "data_type": "REAL (reported count)"},
            "stress_score": comp,
            "trend": {"available": False, "note": "No time series of groundwater levels is public for Bengaluru wards. CGWB observation-well data would be needed."}}


# ------------------------------------------------------------------ lakes + GIS
@router.get("/lakes")
def lakes():
    obs = {}
    try:
        for r in db.rows("SELECT lake_id, COUNT(*) AS n, MAX(date) AS last FROM lake_observations GROUP BY lake_id"):
            obs[r["lake_id"]] = {"observations": r["n"], "last": r["last"]}
    except Exception as e:
        log.warning("lake_observations_failed %s", e)
    lq = ds.indicators()["lake_quality_summary"]
    return {"lakes": [{**l, "observations": obs.get(l["id"], {"observations": 0, "last": None})} for l in ds.processed("lakes.json")],
            "city_summary": lq}


@router.get("/lakes/{lake_id}")
def lake(lake_id: str):
    l = next((x for x in ds.processed("lakes.json") if x["id"] == lake_id), None)
    if not l:
        raise HTTPException(404, "Unknown lake.")
    return {**l, "observations": db.rows("SELECT date, parameter, value, class, source, url FROM lake_observations WHERE lake_id=? ORDER BY date", (lake_id,))}


@router.get("/gis/wards")
def wards(response: Response):
    response.headers["Cache-Control"] = "public, max-age=86400"
    return ds.processed("wards.geojson")


@router.get("/gis/layers")
def gis_layers():
    return {"wards": {"count": len(ds.processed("wards.geojson")["features"]), "source": "BBMP 243 wards (2022 delimitation), KSRSAC KGIS via DataMeet",
                      "url": "https://github.com/datameet/Municipal_Spatial_Data/tree/master/Bangalore", "license": "CC BY-SA 2.5 India"},
            "lakes": {"count": len(ds.processed("lakes.json")), "source": "Wikipedia articles (one per lake)"},
            "localities": ds.processed("localities.json"),
            "ward_risk": {"available": False, "note": "No official ward-level rainfall, groundwater or supply data is available, so JalSetu does not colour wards by risk. Community reports are shown per ward instead."}}


# ------------------------------------------------------------------ water quality
class WaterIn(BaseModel):
    values: dict[str, Optional[float]] = Field(default_factory=dict)


@router.get("/water-quality")
def water_quality_limits():
    return {"standard": "IS 10500:2012 (Bureau of Indian Standards), drinking water specification", "doc": "docs/water-quality-standards.md",
            "limits": [{"key": k, "label": v[0], "unit": v[1], "acceptable": v[2], "permissible": v[3], "kind": v[4]} for k, v in rules.IS10500.items()]}


@router.post("/water-quality/check")
def water_quality_check(body: WaterIn):
    return rules.check_water({k: v for k, v in body.values.items() if v is not None})


# ------------------------------------------------------------------ rainwater harvesting
class RwhIn(BaseModel):
    length_ft: float = Field(ge=0, le=5000)
    width_ft: float = Field(ge=0, le=5000)
    built: Literal["new", "old"] = "new"
    roof_sqm: float = Field(0, ge=0, le=100000)
    paved_sqm: float = Field(0, ge=0, le=100000)
    monthly_bill_rs: float = Field(0, ge=0, le=10000000)
    runoff_coefficient: float = Field(rules.RUNOFF, ge=0.05, le=1)
    collection_efficiency: float = Field(1.0, ge=0.05, le=1)
    rainfall_series: Literal["bengaluru_estimate", "imd_sik_1901_2015"] = "bengaluru_estimate"
    annual_rain_mm: Optional[float] = Field(None, ge=0, le=6000)


@router.post("/rwh")
def rwh(body: RwhIn):
    return rules.rwh_plan(body.length_ft, body.width_ft, body.built, body.roof_sqm, body.paved_sqm, body.monthly_bill_rs,
                          body.runoff_coefficient, body.collection_efficiency, body.rainfall_series, body.annual_rain_mm)


# ------------------------------------------------------------------ forecast + ML
def _log_prediction(model: dict, inputs, output) -> None:
    try:
        db.run("INSERT INTO model_predictions(model,version,inputs,output,created_at) VALUES(?,?,?,?,?)",
               (model["name"], model["version"], json.dumps(inputs), json.dumps(output), time.time()))
    except Exception as e:   # the prediction is still returned to the user
        log.warning("prediction_log_failed %s", e)


@router.get("/forecast")
def forecast(month: int = Query(..., ge=1, le=12)):
    out = ml_runtime.forecast_month(month)
    m = ml_runtime.load("metrics.json")["forecasting"]
    out["evaluation"] = {"test_period": m["split"]["test"], "results": m["results"], "selected": m["selected"]}
    out["region"] = "South Interior Karnataka (IMD sub-division)"
    out["generated_at"] = time.time()
    return out


@router.get("/forecast/backtest")
def forecast_backtest(start: int = Query(2011, ge=1996, le=2015)):
    rows = [r for r in json.loads((ml_runtime.ART / "forecast_backtest.json").read_text()) if r["year"] >= start]
    return {"rows": rows, "note": "Out-of-sample: models were trained on 1902–1995 only."}


class SeasonIn(BaseModel):
    jun_dep_pct: float = Field(ge=-100, le=500)
    jul_dep_pct: float = Field(ge=-100, le=500)
    premonsoon_dep_pct: float = Field(0, ge=-100, le=1000)
    prev_ond_dep_pct: float = Field(0, ge=-100, le=1000)


@router.post("/ml/predict")
def ml_predict(body: SeasonIn, request: Request):
    rate_limit(request, "ml", 120)
    x = ml_runtime.features_from_departures(body.jun_dep_pct, body.jul_dep_pct, None, body.premonsoon_dep_pct, body.prev_ond_dep_pct)
    out = ml_runtime.predict_season(x)
    out["generated_at"] = time.time()
    out["task"] = ml_runtime.load("season_classifier.json")["task"]
    out["region"] = "South Interior Karnataka (IMD sub-division); departures are relative to the 1901–2015 monthly mean"
    _log_prediction(out["model"], body.model_dump(), {"p": out["probability_deficient"]})
    jlog("ml_predict", model=out["model"]["name"], p=out["probability_deficient"])
    return out


class AnomalyIn(BaseModel):
    month: int = Field(ge=1, le=12)
    rain_mm: float = Field(ge=0, le=5000)
    prev_month_mm: float = Field(ge=0, le=5000)
    prev2_month_mm: float = Field(ge=0, le=5000)


@router.post("/ml/anomaly")
def ml_anomaly(body: AnomalyIn):
    m1 = (body.month - 2) % 12 + 1
    m2 = (body.month - 3) % 12 + 1
    out = ml_runtime.check_month(body.month, body.rain_mm, [(m1, body.prev_month_mm), (m2, body.prev2_month_mm)])
    out["generated_at"] = time.time()
    _log_prediction(out["model"], body.model_dump(), {"score": out["score"]})
    return out


@router.get("/ml/models")
def ml_models():
    m = ml_runtime.load("metrics.json")
    return {"version": m["version"], "trained_at": m["trained_at"], "data": m["data"], "data_sha256": m["data_sha256"],
            "classification": m["classification"], "forecasting": m["forecasting"],
            "anomaly": {"agreement": m["anomaly"]["agreement"], "flagged": m["anomaly"]["flagged"][:25]},
            "docs": ["MODEL_REPORT.md", "ML_MODEL_CARD.md"]}


# ------------------------------------------------------------------ overview (one call for the dashboard)
@router.get("/overview")
def overview():
    ind = ds.indicators()
    r = risk.current()
    return {"risk": {k: r[k] for k in ("score", "level", "components", "computed_at", "explanation", "config_version")},
            "warnings": risk.current_warnings(),
            "indicators": ind,
            "rainfall_context": {k: ds.processed("rainfall_analysis.json")[k] for k in ("annual_mean_mm", "jjas_mean_mm", "trend_jjas", "mann_kendall_jjas")},
            "data_manifest": {"generated_at": ds.manifest()["generated_at"], "pipeline_version": ds.manifest()["pipeline_version"]}}


@router.get("/signals")
def signals_v1():
    """v1 compatibility: rain, reservoirs and groundwater in the old shape."""
    ind = ds.indicators()
    rain = ind["rainfall_current_season"]
    tot = next(r for r in ind["reservoir_readings"] if r["id"] == "cauvery_total")
    return {"rain": {**prov(rain), "districts": [{**d, "departure_pct": round(d["departure_pct"])} for d in rain["districts"]]},
            "reservoirs": {"as_of": tot["date"], "gross_tmc": tot["storage_tmc"], "capacity_tmc": tot["capacity_tmc"], "pct": tot["pct_full"],
                           "dams": [{"name": r["reservoir"], "pct": r["pct_full"]} for r in ind["reservoir_readings"] if r["id"] != "cauvery_total"],
                           "source": tot["source"], "url": tot["url"]},
            "groundwater": {**ind["groundwater"]["city_water_balance"], "pumped_vs_recharge": round(ind["groundwater"]["city_water_balance"]["extraction_ratio"], 1)}}
