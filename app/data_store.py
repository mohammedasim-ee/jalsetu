"""Read-only access to the processed data produced by pipeline/run_pipeline.py, plus DB-held readings."""
from __future__ import annotations

import csv
import json
import logging
import time
from datetime import date
from functools import cache
from pathlib import Path

from . import db

log = logging.getLogger("jalsetu")

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
CONFIG = ROOT / "config"


@cache
def processed(name: str):
    p = PROC / name
    if not p.exists():
        raise RuntimeError(f"Missing {p.name}. Run: python pipeline/run_pipeline.py")
    return json.loads(p.read_text())


@cache
def monthly_rainfall() -> list[dict]:
    with open(PROC / "rainfall_monthly.csv", newline="") as f:
        return [{k: (float(v) if k not in ("year", "month") else int(v)) if v != "" else None for k, v in r.items()}
                for r in csv.DictReader(f)]


@cache
def risk_config() -> dict:
    cfg = json.loads((CONFIG / "risk_config.json").read_text())
    total = sum(c["weight"] for c in cfg["components"].values())
    if abs(total - 1) > 1e-6:
        raise RuntimeError(f"Risk weights must sum to 1 (got {total})")
    return cfg


def indicators() -> dict:
    return processed("indicators.json")


def days_old(as_of: str, today: date | None = None) -> int | None:
    """Age in days of an as_of value like '2026-09-28', '2026-08' or '2024' (uses the period's last day)."""
    today = today or date.today()
    try:
        parts = [int(x) for x in str(as_of).split("-")]
    except ValueError:
        return None
    if len(parts) == 1:
        d = date(parts[0], 12, 31)
    elif len(parts) == 2:
        import calendar
        d = date(parts[0], parts[1], calendar.monthrange(parts[0], parts[1])[1])
    else:
        d = date(*parts[:3])
    return max(0, (today - d).days)


def reservoir_readings() -> list[dict]:
    """File readings (pipeline) plus readings added by admins (DB). Sorted by reservoir, date."""
    out = [{**r, "origin": "pipeline"} for r in indicators()["reservoir_readings"]]
    try:
        for r in db.rows("SELECT * FROM reservoir_readings ORDER BY date"):
            pct = r["pct_full"]
            if pct is None and r["storage_tmc"] is not None and r["capacity_tmc"]:
                pct = round(r["storage_tmc"] / r["capacity_tmc"] * 100, 1)
            out.append({"id": r["reservoir_id"], "reservoir": r["reservoir"], "date": r["date"], "storage_tmc": r["storage_tmc"],
                        "capacity_tmc": r["capacity_tmc"], "pct_full": pct, "inflow_cusecs": r["inflow_cusecs"],
                        "outflow_cusecs": r["outflow_cusecs"], "status": r["status"], "source": r["source"], "url": r["url"],
                        "origin": "admin upload"})
    except Exception as e:   # DB unavailable: fall back to the pipeline readings only
        log.warning("reservoir_readings_db_failed %s", e)
    seen, uniq = set(), []
    for r in sorted(out, key=lambda r: (r["id"], r["date"], r["origin"] != "admin upload")):
        k = (r["id"], r["date"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq


def latest_by_reservoir() -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    for r in reservoir_readings():
        by.setdefault(r["id"], []).append(r)
    return by


def manifest() -> dict:
    return processed("manifest.json")


def now() -> float:
    return time.time()
