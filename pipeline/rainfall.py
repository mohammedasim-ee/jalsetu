"""Rainfall stage: validate, clean and engineer features from IMD sub-divisional monthly rainfall.

Input:  data/raw/imd_subdivision_monthly_rainfall_1901_2017.csv (IMD via data.gov.in)
Output: rainfall_monthly.csv, rainfall_analysis.json
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
SUBDIVISION = "SOUTH INTERIOR KARNATAKA"   # IMD sub-division that contains Bengaluru
SUM_TOLERANCE_MM = 1.0                     # published ANNUAL may differ from the month sum by rounding


def _num(v: str):
    v = (v or "").strip()
    if v in ("", "NA", "NaN", "nan"):
        return None
    return float(v)


def load_and_validate(path: Path, subdivision: str = SUBDIVISION) -> tuple[list[dict], dict]:
    """Returns clean rows for one sub-division and a validation report. Rows that fail are dropped, not repaired."""
    report: dict[str, Any] = {"file": path.name, "subdivision": subdivision, "rows_read": 0, "rows_kept": 0,
              "missing_values": 0, "negative_values": 0, "annual_sum_mismatch": 0, "duplicate_years": 0,
              "missing_years": [], "issues": []}
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        need = {"SUBDIVISION", "YEAR", "ANNUAL", *MONTHS}
        missing_cols = need - set(reader.fieldnames or [])
        if missing_cols:
            raise ValueError(f"Rainfall file is missing columns: {sorted(missing_cols)}")
        for r in reader:
            if r["SUBDIVISION"].strip().upper() != subdivision:
                continue
            report["rows_read"] += 1
            year = int(r["YEAR"])
            vals = [_num(r[m]) for m in MONTHS]
            annual = _num(r["ANNUAL"])
            if year in seen:
                report["duplicate_years"] += 1
                report["issues"].append(f"{year}: duplicate year dropped")
                continue
            if any(v is None for v in vals):
                report["missing_values"] += sum(v is None for v in vals)
                report["issues"].append(f"{year}: missing monthly value, row dropped")
                continue
            if any(v < 0 for v in vals):
                report["negative_values"] += 1
                report["issues"].append(f"{year}: negative rainfall, row dropped")
                continue
            if annual is not None and abs(sum(vals) - annual) > SUM_TOLERANCE_MM:
                report["annual_sum_mismatch"] += 1
                report["issues"].append(f"{year}: months sum to {sum(vals):.1f} but ANNUAL is {annual}; months kept")
            seen.add(year)
            rows.append({"year": year, "months": vals})
    rows.sort(key=lambda x: x["year"])
    if rows:
        full = set(range(rows[0]["year"], rows[-1]["year"] + 1))
        report["missing_years"] = sorted(full - seen)
    report["rows_kept"] = len(rows)
    report["years"] = [rows[0]["year"], rows[-1]["year"]] if rows else None
    return rows, report


# ------------------------------------------------------------------ statistics (stdlib only)
def mean(xs):
    return sum(xs) / len(xs)


def std(xs):
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def linear_trend(xs: list[float], ys: list[float]) -> dict:
    if len(xs) < 2:
        raise ValueError("A trend needs at least two years.")
    """Ordinary least squares slope with a 95% confidence interval (normal approximation, n > 30)."""
    n = len(xs)
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    intercept = my - slope * mx
    resid = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    if n < 3:          # a line through two points has no residual error to estimate
        return {"slope_per_year": slope, "slope_per_decade": slope * 10, "ci95_per_decade": [None, None],
                "intercept": intercept, "significant_95": False}
    se = math.sqrt(sum(e * e for e in resid) / (n - 2) / sxx)
    return {"slope_per_year": slope, "slope_per_decade": slope * 10, "ci95_per_decade": [(slope - 1.96 * se) * 10, (slope + 1.96 * se) * 10],
            "intercept": intercept, "significant_95": abs(slope) > 1.96 * se}


def mann_kendall(ys: list[float]) -> dict:
    """Mann-Kendall trend test (no ties correction needed for continuous rainfall). Two-sided p-value."""
    n = len(ys)
    s = sum((1 if ys[j] > ys[i] else -1 if ys[j] < ys[i] else 0) for i in range(n - 1) for j in range(i + 1, n))
    var = n * (n - 1) * (2 * n + 5) / 18
    z = (s - 1) / math.sqrt(var) if s > 0 else (s + 1) / math.sqrt(var) if s < 0 else 0.0
    p = math.erfc(abs(z) / math.sqrt(2))
    return {"S": s, "Z": round(z, 3), "p_value": round(p, 4), "trend": "increasing" if z > 0 and p < 0.05 else "decreasing" if z < 0 and p < 0.05 else "no significant trend"}


def moving_average(xs: list[float], window: int) -> list:
    return [None if i + 1 < window else sum(xs[i + 1 - window:i + 1]) / window for i in range(len(xs))]


def imd_category(dep_pct: float) -> str:
    """IMD rainfall categories by departure from normal."""
    if dep_pct >= 60:
        return "Large excess"
    if dep_pct >= 20:
        return "Excess"
    if dep_pct > -20:
        return "Normal"
    if dep_pct > -60:
        return "Deficient"
    if dep_pct > -100:
        return "Large deficient"
    return "No rain"


def build_features(rows: list[dict]) -> tuple[list[dict], dict]:
    years = [r["year"] for r in rows]
    clim = []
    for m in range(12):
        col = [r["months"][m] for r in rows]
        clim.append({"month": MONTHS[m], "mean_mm": mean(col), "std_mm": std(col), "median_mm": sorted(col)[len(col) // 2],
                     "min_mm": min(col), "max_mm": max(col)})
    monthly = []
    for r in rows:
        for m, v in enumerate(r["months"]):
            c = clim[m]
            monthly.append({"year": r["year"], "month": m + 1, "rain_mm": v,
                            "anomaly_mm": round(v - c["mean_mm"], 2),
                            "anomaly_pct": round((v - c["mean_mm"]) / c["mean_mm"] * 100, 1) if c["mean_mm"] > 0 else None,
                            "z": round((v - c["mean_mm"]) / c["std_mm"], 3) if c["std_mm"] > 0 else 0.0})
    annual = [sum(r["months"]) for r in rows]
    jjas = [sum(r["months"][5:9]) for r in rows]
    ond = [sum(r["months"][9:12]) for r in rows]
    a_mean, j_mean, o_mean = mean(annual), mean(jjas), mean(ond)
    seasons = []
    for i, r in enumerate(rows):
        dep = (jjas[i] - j_mean) / j_mean * 100
        seasons.append({"year": r["year"], "annual_mm": round(annual[i], 1), "jjas_mm": round(jjas[i], 1), "ond_mm": round(ond[i], 1),
                        "jjas_departure_pct": round(dep, 1), "annual_departure_pct": round((annual[i] - a_mean) / a_mean * 100, 1),
                        "jjas_category": imd_category(dep)})
    ma_annual = moving_average(annual, 10)
    ma_jjas = moving_average(jjas, 10)
    for i, s in enumerate(seasons):
        s["annual_ma10_mm"] = round(ma_annual[i], 1) if ma_annual[i] is not None else None
        s["jjas_ma10_mm"] = round(ma_jjas[i], 1) if ma_jjas[i] is not None else None
    counts: dict[str, int] = {}
    for s in seasons:
        counts[s["jjas_category"]] = counts.get(s["jjas_category"], 0) + 1
    analysis = {
        "subdivision": "South Interior Karnataka (IMD sub-division that contains Bengaluru)",
        "years": [years[0], years[-1]],
        "baseline": f"{years[0]}–{years[-1]} mean (all years in the dataset)",
        "climatology": [{k: (round(v, 1) if isinstance(v, float) else v) for k, v in c.items()} for c in clim],
        "annual_mean_mm": round(a_mean, 1), "jjas_mean_mm": round(j_mean, 1), "ond_mean_mm": round(o_mean, 1),
        "trend_annual": {k: (round(v, 2) if isinstance(v, float) else [round(x, 2) if x is not None else None for x in v] if isinstance(v, list) else v)
                         for k, v in linear_trend(years, annual).items()},
        "trend_jjas": {k: (round(v, 2) if isinstance(v, float) else [round(x, 2) if x is not None else None for x in v] if isinstance(v, list) else v)
                       for k, v in linear_trend(years, jjas).items()},
        "mann_kendall_annual": mann_kendall(annual),
        "mann_kendall_jjas": mann_kendall(jjas),
        "jjas_category_counts": counts,
        "seasons": seasons,
    }
    return monthly, analysis


def write_monthly_csv(monthly: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(monthly[0].keys()))
        w.writeheader()
        w.writerows(monthly)
