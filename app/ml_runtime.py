"""Pure-Python inference for the exported models (no scikit-learn or numpy needed at runtime).

- Season classifier: random forest (or logistic regression) -> probability that Jun–Sep ends deficient.
  Local explanation = path contributions (Saabas / "treeinterpreter" method):
  probability = bias + sum(feature contributions), exactly, for tree ensembles.
- Monthly forecaster: the model selected in evaluation (climatology won; see MODEL_REPORT.md).
- Anomaly detector: isolation forest score, identical to scikit-learn's decision_function.
"""
from __future__ import annotations

import json
import math
from functools import cache
from pathlib import Path

ART = Path(__file__).resolve().parent.parent / "ml" / "artifacts"
EULER = 0.5772156649015329


@cache
def load(name: str) -> dict:
    return json.loads((ART / name).read_text())


def available() -> bool:
    return all((ART / f).exists() for f in ("season_classifier.json", "monthly_forecaster.json", "anomaly_detector.json", "metrics.json"))


# ------------------------------------------------------------------ trees
def _p1(value) -> float:
    s = sum(value)
    return value[1] / s if s else 0.0


def _tree_path(t: dict, x: list[float]) -> list[int]:
    n, path = 0, [0]
    while t["left"][n] != -1:
        n = t["left"][n] if x[t["feature"][n]] <= t["threshold"][n] else t["right"][n]
        path.append(n)
    return path


def forest_proba_and_contrib(trees: list[dict], x: list[float], n_feat: int):
    bias, prob = 0.0, 0.0
    contrib = [0.0] * n_feat
    for t in trees:
        path = _tree_path(t, x)
        vals = [_p1(t["value"][n]) for n in path]
        bias += vals[0]
        prob += vals[-1]
        for a, v0, v1 in zip(path, vals, vals[1:]):
            contrib[t["feature"][a]] += v1 - v0
    k = len(trees)
    return prob / k, bias / k, [c / k for c in contrib]


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def logistic_proba_and_contrib(m: dict, x: list[float]):
    zs = [(v - mu) / s for v, mu, s in zip(x, m["mean"], m["scale"])]
    terms = [c * z for c, z in zip(m["coef"], zs)]
    return _sigmoid(m["intercept"] + sum(terms)), m["intercept"], terms


# ------------------------------------------------------------------ season classifier
def features_from_departures(jun: float, jul: float, jun_jul: float | None, premonsoon: float, prev_ond: float) -> list[float]:
    art = load("season_classifier.json")
    c = art["climatology_mm"]
    if jun_jul is None:   # combine June and July departures weighted by their normals
        jun_jul = (jun * c[5] + jul * c[6]) / (c[5] + c[6])
    return [jun, jul, jun_jul, premonsoon, prev_ond]


def predict_season(x: list[float]) -> dict:
    art = load("season_classifier.json")
    m = art["model"]
    if m["type"] == "random_forest_classifier":
        p, bias, contrib = forest_proba_and_contrib(m["trees"], x, len(art["features"]))
        method = "Path contributions (Saabas): probability = base rate + sum of contributions"
    else:
        p, bias, contrib = logistic_proba_and_contrib(m, x)
        method = "Coefficient × standardised value (log-odds contributions)"
    rule = x[art["features"].index("jun_jul_dep_pct")] <= -20
    labels = art.get("labels", {})
    order = sorted(range(len(contrib)), key=lambda i: -abs(contrib[i]))
    return {"probability_deficient": round(p, 3), "predicted_deficient": p >= art["threshold"], "threshold": art["threshold"],
            "rule_baseline_deficient": rule,
            "explanation": {"method": method, "base_value": round(bias, 3),
                            "contributions": [{"feature": art["features"][i], "label": labels.get(art["features"][i], art["features"][i]),
                                               "value": round(x[i], 1), "contribution": round(contrib[i], 4)} for i in order]},
            "model": {"name": art["name"], "version": art["version"], "trained_at": art["trained_at"], "data_sha256": art["data_sha256"][:12]}}


# ------------------------------------------------------------------ forecaster
def forecast_month(month: int, recent_anomalies: list[float] | None = None) -> dict:
    art = load("monthly_forecaster.json")
    clim = art["climatology_mm"][month - 1]
    out = {"month": month, "model": {"name": art["name"], "version": art["version"], "trained_at": art["trained_at"]}}
    if art["name"] == "climatology" or not recent_anomalies:
        out["forecast_mm"] = round(clim, 1)
        out["method"] = "Long-term monthly mean. In evaluation no model beat this baseline (see MODEL_REPORT.md)."
    else:
        lin = art["linear"]
        out["forecast_mm"] = round(max(0.0, clim + lin["intercept"] + sum(c * a for c, a in zip(lin["coef"], recent_anomalies))), 1)
        out["method"] = "Climatology plus linear anomaly persistence"
    return out


# ------------------------------------------------------------------ isolation forest
def _c(n: float) -> float:
    if n <= 1:
        return 0.0
    if n == 2:
        return 1.0
    return 2.0 * (math.log(n - 1.0) + EULER) - 2.0 * (n - 1.0) / n


def anomaly_score(x: list[float]) -> float:
    """scikit-learn IsolationForest.decision_function: negative = anomalous."""
    art = load("anomaly_detector.json")
    depth = 0.0
    for t in art["trees"]:
        xs = [x[i] for i in t["features_used"]]
        path = _tree_path(t, xs)
        depth += len(path) - 1 + _c(t["n_node_samples"][path[-1]])
    score = -(2 ** (-depth / (len(art["trees"]) * _c(art["max_samples"]))))
    return score - art["offset"]


def month_features(month: int, rain_mm: float, prev2: list[tuple[int, float]]) -> list[float]:
    """Features for one month given the two previous (month, rain) pairs, using the training climatology."""
    art = load("anomaly_detector.json")
    clim, std = art["climatology_mm"], art["std_mm"]
    z = (rain_mm - clim[month - 1]) / std[month - 1]
    zs = [z] + [(v - clim[m - 1]) / std[m - 1] for m, v in prev2]
    return [z, sum(zs) / math.sqrt(3), math.log1p(rain_mm) - math.log1p(clim[month - 1])]


def check_month(month: int, rain_mm: float, prev2: list[tuple[int, float]]) -> dict:
    x = month_features(month, rain_mm, prev2)
    s = anomaly_score(x)
    art = load("anomaly_detector.json")
    return {"anomalous": s < 0, "score": round(s, 4), "z": round(x[0], 2), "normal_mm": round(art["climatology_mm"][month - 1], 1),
            "model": {"name": art["name"], "version": art["version"], "trained_at": art["trained_at"]}}
