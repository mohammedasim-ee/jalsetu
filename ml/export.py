"""Export scikit-learn models to plain JSON so the server can run inference without scikit-learn
(keeps the Vercel function small). ml/tests check that JSON inference equals scikit-learn output."""
from __future__ import annotations


def _tree(t) -> dict:
    tr = t.tree_
    return {"left": tr.children_left.tolist(), "right": tr.children_right.tolist(), "feature": tr.feature.tolist(),
            "threshold": [float(x) for x in tr.threshold], "value": [v[0] for v in tr.value.tolist()],
            "n_node_samples": tr.n_node_samples.tolist()}


def logistic(model, scaler, feats) -> dict:
    return {"type": "logistic_regression", "features": feats, "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
            "coef": model.coef_[0].tolist(), "intercept": float(model.intercept_[0])}


def classifier(name, model, scaler, feats, clim, meta) -> dict:
    out = {"name": name, "task": "Will the Jun–Sep monsoon end deficient (≤ −20% of normal)? Predicted at end of July.",
           "features": feats, "climatology_mm": clim, "threshold": 0.5, **meta}
    if name == "logistic_regression":
        out["model"] = logistic(model, scaler, feats)
    else:
        out["model"] = {"type": "random_forest_classifier", "features": feats,
                        "trees": [_tree(e) for e in model.estimators_]}
    return out


def forecaster(name, rf, lin, feats, clim, meta) -> dict:
    out = {"name": name, "task": "Next-month rainfall (mm), South Interior Karnataka", "features": feats,
           "climatology_mm": clim, **meta,
           "linear": {"coef": lin.coef_.tolist(), "intercept": float(lin.intercept_), "uses": feats[:4]}}
    if rf is not None:
        out["random_forest"] = {"trees": [_tree(e) for e in rf.estimators_]}
    return out


def isolation_forest(iso, feats, clim, std, meta) -> dict:
    return {"name": "isolation_forest", "features": feats, "climatology_mm": clim, "std_mm": std, **meta,
            "max_samples": int(iso.max_samples_), "offset": float(iso.offset_),
            "trees": [{**_tree(e), "features_used": fs.tolist()} for e, fs in zip(iso.estimators_, iso.estimators_features_)]}
