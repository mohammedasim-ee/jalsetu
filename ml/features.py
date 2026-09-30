"""Preprocessing and feature engineering for JalSetu's rainfall models.

All baselines (monthly climatology) are computed from TRAINING years only and passed in,
so evaluation never sees the test period's statistics (no leakage).
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MONTHLY_CSV = ROOT / "data" / "processed" / "rainfall_monthly.csv"

CLS_FEATURES = ["jun_dep_pct", "jul_dep_pct", "jun_jul_dep_pct", "premonsoon_dep_pct", "prev_ond_dep_pct"]
CLS_LABELS = {"jun_dep_pct": "June departure", "jul_dep_pct": "July departure",
              "jun_jul_dep_pct": "June–July combined departure", "premonsoon_dep_pct": "Pre-monsoon (Mar–May) departure",
              "prev_ond_dep_pct": "Previous year's Oct–Dec departure"}
DEFICIENT_THRESHOLD = -20.0      # IMD: season departure of −20% or worse = deficient


def load_years(path: Path = MONTHLY_CSV) -> dict[int, list[float]]:
    """{year: [12 monthly totals in mm]} from the processed pipeline output."""
    years: dict[int, list[float]] = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            y, m, v = int(r["year"]), int(r["month"]), float(r["rain_mm"])
            if not (1 <= m <= 12) or v < 0:
                raise ValueError(f"bad monthly row {r}")
            years.setdefault(y, [0.0] * 12)[m - 1] = v
    bad = [y for y, v in years.items() if len(v) != 12]
    if bad:
        raise ValueError(f"incomplete years {bad}")
    return dict(sorted(years.items()))


def climatology(years: dict[int, list[float]], use: list[int]) -> list[float]:
    return [sum(years[y][m] for y in use) / len(use) for m in range(12)]


def _dep(actual: float, normal: float) -> float:
    return (actual - normal) / normal * 100 if normal > 0 else 0.0


def season_features(rain: list[float], clim: list[float], prev: list[float] | None) -> dict:
    """Features known by 31 July of a year. `rain` is that year's 12 months (only Mar–Jul are used)."""
    r = rain
    f = {
        "jun_dep_pct": _dep(r[5], clim[5]),
        "jul_dep_pct": _dep(r[6], clim[6]),
        "jun_jul_dep_pct": _dep(r[5] + r[6], clim[5] + clim[6]),
        "premonsoon_dep_pct": _dep(r[2] + r[3] + r[4], clim[2] + clim[3] + clim[4]),
        "prev_ond_dep_pct": _dep(sum(prev[9:12]), sum(clim[9:12])) if prev is not None else 0.0,
    }
    return f


def season_label(rain: list[float], clim: list[float]) -> int:
    return int(_dep(sum(rain[5:9]), sum(clim[5:9])) <= DEFICIENT_THRESHOLD)


def classification_rows(years: dict[int, list[float]], clim: list[float], use: list[int]) -> tuple[list[list[float]], list[int]]:
    X, y = [], []
    for yr in use:
        if yr - 1 not in years:
            continue
        f = season_features(years[yr], clim, years[yr - 1])
        X.append([f[k] for k in CLS_FEATURES])
        y.append(season_label(years[yr], clim))
    return X, y


# ------------------------------------------------------------------ monthly forecasting
FC_FEATURES = ["anom_lag1", "anom_lag2", "anom_lag3", "anom_same_month_last_year", "clim_target", "month_sin", "month_cos"]


def monthly_series(years: dict[int, list[float]]) -> list[tuple[int, int, float]]:
    return [(y, m + 1, v) for y, vals in years.items() for m, v in enumerate(vals)]


def forecast_rows(series: list[tuple[int, int, float]], clim: list[float], start_index: int = 12):
    """Predict month t from months t-1..t-3 and t-12. Returns X, y, keys (year, month) and climatology baseline."""
    import math
    X, y, keys, base = [], [], [], []
    for t in range(max(start_index, 12), len(series)):
        yr, mo, v = series[t]
        a = [series[t - k][2] - clim[series[t - k][1] - 1] for k in (1, 2, 3, 12)]
        X.append(a + [clim[mo - 1], math.sin(2 * math.pi * mo / 12), math.cos(2 * math.pi * mo / 12)])
        y.append(v)
        keys.append((yr, mo))
        base.append(clim[mo - 1])
    return X, y, keys, base


# ------------------------------------------------------------------ anomaly detection
AN_FEATURES = ["z_month", "z_3month", "ratio_to_normal"]


def anomaly_rows(series, clim, std):
    import math
    X, keys = [], []
    for t in range(2, len(series)):
        yr, mo, v = series[t]
        z = (v - clim[mo - 1]) / std[mo - 1] if std[mo - 1] > 0 else 0.0
        z3 = sum((series[t - k][2] - clim[series[t - k][1] - 1]) / std[series[t - k][1] - 1] for k in range(3)) / math.sqrt(3)
        X.append([z, z3, math.log1p(v) - math.log1p(clim[mo - 1])])
        keys.append((yr, mo, v))
    return X, keys


def monthly_std(years, use, clim):
    import math
    return [math.sqrt(sum((years[y][m] - clim[m]) ** 2 for y in use) / (len(use) - 1)) for m in range(12)]
