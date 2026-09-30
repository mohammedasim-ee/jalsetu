"""Train, validate and export JalSetu's models.

    pip install -r requirements-ml.txt
    python ml/train.py

Writes ml/artifacts/*.json (used by the server, pure-Python inference), *.joblib (scikit-learn objects for
reproducibility) and ml/artifacts/metrics.json (every number quoted in MODEL_REPORT.md).
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest, RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ml import export  # noqa: E402
from ml import features as F  # noqa: E402

ART = ROOT / "ml" / "artifacts"
SEED = 42
VERSION = "2.0.0"


def cls_metrics(y, pred, prob=None) -> dict:
    y, pred = np.asarray(y), np.asarray(pred)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    m = {"n": int(len(y)), "positives": int(y.sum()), "accuracy": accuracy_score(y, pred),
         "precision": precision_score(y, pred, zero_division=0), "recall": recall_score(y, pred, zero_division=0),
         "f1": f1_score(y, pred, zero_division=0), "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}}
    if prob is not None and len(set(y.tolist())) > 1:
        m["roc_auc"] = roc_auc_score(y, prob)
        m["brier"] = brier_score_loss(y, prob)
    return {k: (round(float(v), 3) if isinstance(v, (float, np.floating)) else v) for k, v in m.items()}


def reg_metrics(y, pred, base=None) -> dict:
    y, pred = np.asarray(y), np.asarray(pred)
    m = {"n": int(len(y)), "mae": mean_absolute_error(y, pred), "rmse": math.sqrt(mean_squared_error(y, pred)), "r2": r2_score(y, pred)}
    if base is not None:
        mae_b = mean_absolute_error(y, base)
        m["skill_vs_climatology_mae"] = 1 - m["mae"] / mae_b
    return {k: (round(float(v), 3) if not isinstance(v, int) else v) for k, v in m.items()}


# ------------------------------------------------------------------ A. deficient-monsoon early warning (classification)
def make_cls_models():
    return {
        "logistic_regression": lambda: ("scaled", LogisticRegression(class_weight="balanced", C=1.0, max_iter=2000)),
        "random_forest": lambda: ("raw", RandomForestClassifier(n_estimators=300, max_depth=3, min_samples_leaf=3,
                                                                class_weight="balanced", random_state=SEED)),
    }


def classification(years):
    all_years = [y for y in years if y - 1 in years]
    folds = [(s, min(s + 9, 2015)) for s in range(1931, 2016, 10)]   # 9 folds, expanding training window (>= 29 training years)
    preds = {k: {"y": [], "pred": [], "prob": []} for k in ["majority_class", "rule_jun_jul_le_-20", *make_cls_models()]}
    fold_log = []
    for lo, hi in folds:
        train = [y for y in all_years if y < lo]
        test = [y for y in all_years if lo <= y <= hi]
        clim = F.climatology(years, train)
        Xtr, ytr = F.classification_rows(years, clim, train)
        Xte, yte = F.classification_rows(years, clim, test)
        Xtr, Xte = np.array(Xtr), np.array(Xte)
        fold_log.append({"train": [train[0], train[-1]], "test": [lo, hi], "test_positives": int(sum(yte))})
        maj = int(round(np.mean(ytr)))
        preds["majority_class"]["y"] += yte; preds["majority_class"]["pred"] += [maj] * len(yte); preds["majority_class"]["prob"] += [float(np.mean(ytr))] * len(yte)
        jj = F.CLS_FEATURES.index("jun_jul_dep_pct")
        rule = [int(x[jj] <= F.DEFICIENT_THRESHOLD) for x in Xte]
        preds["rule_jun_jul_le_-20"]["y"] += yte; preds["rule_jun_jul_le_-20"]["pred"] += rule; preds["rule_jun_jul_le_-20"]["prob"] += [float(r) for r in rule]
        for name, mk in make_cls_models().items():
            mode, model = mk()
            sc = StandardScaler().fit(Xtr) if mode == "scaled" else None
            model.fit(sc.transform(Xtr) if sc else Xtr, ytr)
            p = model.predict_proba(sc.transform(Xte) if sc else Xte)[:, 1]
            preds[name]["y"] += yte; preds[name]["prob"] += p.tolist(); preds[name]["pred"] += (p >= 0.5).astype(int).tolist()
    results = {k: cls_metrics(v["y"], v["pred"], v["prob"] if k not in ("rule_jun_jul_le_-20",) else None) for k, v in preds.items()}
    candidates = [k for k in make_cls_models()]
    best = max(candidates, key=lambda k: (results[k]["f1"], results[k].get("roc_auc", 0)))

    # final model on all years
    clim = F.climatology(years, all_years)
    X, y = F.classification_rows(years, clim, all_years)
    X = np.array(X)
    mode, model = make_cls_models()[best]()
    sc = StandardScaler().fit(X) if mode == "scaled" else None
    model.fit(sc.transform(X) if sc else X, y)
    lr_mode, lr = make_cls_models()["logistic_regression"]()
    lr_sc = StandardScaler().fit(X)
    lr.fit(lr_sc.transform(X), y)
    rf_mode, rf = make_cls_models()["random_forest"]()
    rf.fit(X, y)
    coef = dict(zip(F.CLS_FEATURES, [round(float(c), 4) for c in lr.coef_[0]]))
    rf_imp = dict(zip(F.CLS_FEATURES, [round(float(c), 4) for c in rf.feature_importances_]))
    rule = results["rule_jun_jul_le_-20"]
    note = ("The selected model does not beat the one-line rule (June–July departure ≤ −20%) on F1; its extra value is a "
            "probability that ranks risk (ROC AUC).") if results[best]["f1"] <= rule["f1"] else "The selected model beats the one-line rule on F1."
    return {"folds": fold_log, "cv_results": results, "selected": best, "selection_note": note, "final_model": model, "final_scaler": sc,
            "climatology_all_years": clim, "n_train": len(y), "positives_train": int(sum(y)),
            "logistic_coefficients_standardised": coef, "rf_feature_importance": rf_imp,
            "logistic_model": lr, "logistic_scaler": lr_sc}


# ------------------------------------------------------------------ B. next-month rainfall forecast (regression)
def forecasting(years):
    series = F.monthly_series(years)
    split_year = 1996
    train_years = [y for y in years if y < split_year]
    clim = F.climatology(years, train_years)
    X, y, keys, base = F.forecast_rows(series, clim)
    X, y, base = np.array(X), np.array(y), np.array(base)
    tr = np.array([k[0] < split_year for k in keys])
    te = ~tr
    # seasonal naive: same month last year
    snaive = np.array([years[k[0] - 1][k[1] - 1] for k in keys])
    lin = LinearRegression().fit(X[tr][:, :4], y[tr] - base[tr])        # anomaly persistence model
    lin_pred = np.clip(base + lin.predict(X[:, :4]), 0, None)
    rf = RandomForestRegressor(n_estimators=200, max_depth=6, min_samples_leaf=5, random_state=SEED).fit(X[tr], y[tr])
    rf_pred = np.clip(rf.predict(X), 0, None)
    res = {
        "climatology": reg_metrics(y[te], base[te], base[te]),
        "seasonal_naive": reg_metrics(y[te], snaive[te], base[te]),
        "linear_anomaly_persistence": reg_metrics(y[te], lin_pred[te], base[te]),
        "random_forest": reg_metrics(y[te], rf_pred[te], base[te]),
    }
    best = min(res, key=lambda k: res[k]["mae"])
    test_rows = [{"year": k[0], "month": k[1], "actual": round(float(a), 1), "climatology": round(float(b), 1),
                  "random_forest": round(float(r), 1), "linear": round(float(l), 1)}
                 for k, a, b, r, l, t in zip(keys, y, base, rf_pred, lin_pred, te) if t]
    return {"split": {"train": [min(train_years) + 1, split_year - 1], "test": [split_year, max(years)]}, "results": res,
            "selected": best, "rf": rf, "linear": lin, "climatology_train": clim, "backtest": test_rows,
            "rf_feature_importance": dict(zip(F.FC_FEATURES, [round(float(v), 4) for v in rf.feature_importances_]))}


# ------------------------------------------------------------------ C. anomaly detection (unsupervised)
def anomalies(years):
    use = list(years)
    clim = F.climatology(years, use)
    std = F.monthly_std(years, use, clim)
    series = F.monthly_series(years)
    X, keys = F.anomaly_rows(series, clim, std)
    X = np.array(X)
    iso = IsolationForest(n_estimators=100, max_samples=256, contamination=0.02, random_state=SEED).fit(X)
    score = iso.decision_function(X)
    flag = iso.predict(X) == -1
    rule = np.abs(X[:, 0]) >= 3
    agree = {"isolation_forest_flags": int(flag.sum()), "rule_abs_z_ge_3_flags": int(rule.sum()),
             "both": int((flag & rule).sum()),
             "share_of_rule_flags_also_flagged_by_model": round(float((flag & rule).sum() / max(rule.sum(), 1)), 3),
             "share_of_model_flags_that_meet_rule": round(float((flag & rule).sum() / max(flag.sum(), 1)), 3)}
    top = sorted([{"year": k[0], "month": k[1], "rain_mm": round(k[2], 1), "normal_mm": round(clim[k[1] - 1], 1),
                   "z": round(float(x[0]), 2), "score": round(float(s), 4)}
                  for k, x, s, fl in zip(keys, X, score, flag) if fl], key=lambda r: r["score"])
    return {"model": iso, "climatology": clim, "std": std, "agreement": agree, "flagged": top}


def data_hash() -> str:
    return hashlib.sha256(F.MONTHLY_CSV.read_bytes()).hexdigest()


def main():
    np.random.seed(SEED)
    ART.mkdir(parents=True, exist_ok=True)
    years = F.load_years()
    t0 = time.time()
    c = classification(years)
    f = forecasting(years)
    a = anomalies(years)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    meta = {"version": VERSION, "trained_at": stamp, "data_sha256": data_hash(),
            "data": "IMD South Interior Karnataka monthly rainfall 1901–2015 (data/processed/rainfall_monthly.csv)"}

    # exports used by the server (pure Python)
    cls_art = export.classifier(c["selected"], c["final_model"], c["final_scaler"], F.CLS_FEATURES, c["climatology_all_years"], meta)
    cls_art["labels"] = F.CLS_LABELS
    cls_art["explainer"] = export.logistic(c["logistic_model"], c["logistic_scaler"], F.CLS_FEATURES)
    (ART / "season_classifier.json").write_text(json.dumps(cls_art))
    fc_model = f["rf"] if f["selected"] == "random_forest" else None
    fc_art = export.forecaster(f["selected"], fc_model, f["linear"], F.FC_FEATURES, f["climatology_train"], meta)
    (ART / "monthly_forecaster.json").write_text(json.dumps(fc_art))
    (ART / "anomaly_detector.json").write_text(json.dumps(export.isolation_forest(a["model"], F.AN_FEATURES, a["climatology"], a["std"], meta)))
    joblib.dump({"classifier": c["final_model"], "scaler": c["final_scaler"], "logistic": c["logistic_model"],
                 "logistic_scaler": c["logistic_scaler"]}, ART / "season_classifier.joblib")
    joblib.dump({"rf": f["rf"], "linear": f["linear"]}, ART / "monthly_forecaster.joblib")
    joblib.dump(a["model"], ART / "anomaly_detector.joblib")

    metrics = {**meta, "duration_s": round(time.time() - t0, 1),
               "classification": {k: v for k, v in c.items() if k not in ("final_model", "final_scaler", "logistic_model", "logistic_scaler", "climatology_all_years")},
               "forecasting": {k: v for k, v in f.items() if k not in ("rf", "linear", "climatology_train", "backtest")},
               "anomaly": {"agreement": a["agreement"], "flagged": a["flagged"]}}
    (ART / "metrics.json").write_text(json.dumps(metrics, indent=1))
    (ART / "forecast_backtest.json").write_text(json.dumps(f["backtest"]))
    print(json.dumps({"classification": {k: {m: v.get(m) for m in ("f1", "precision", "recall", "accuracy", "roc_auc")}
                                         for k, v in c["cv_results"].items()}, "selected_cls": c["selected"],
                      "forecast": f["results"], "selected_fc": f["selected"], "anomaly": a["agreement"]}, indent=1))
    return metrics


if __name__ == "__main__":
    main()
