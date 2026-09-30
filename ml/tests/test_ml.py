"""ML tests: preprocessing, artifact integrity, and that pure-Python inference equals scikit-learn."""
import json
import math
from pathlib import Path

import pytest

from app import ml_runtime as R
from ml import features as F

ART = Path(__file__).resolve().parent.parent / "artifacts"


def test_load_years_complete_and_valid():
    years = F.load_years()
    assert min(years) == 1901 and max(years) == 2017 and len(years) == 117
    assert all(len(v) == 12 and min(v) >= 0 for v in years.values())


def test_climatology_uses_only_given_years():
    years = {2000: [10.0] * 12, 2001: [30.0] * 12}
    assert F.climatology(years, [2000]) == [10.0] * 12
    assert F.climatology(years, [2000, 2001]) == [20.0] * 12


def test_season_features_and_label():
    clim = [10.0] * 12
    rain = [10, 10, 5, 5, 5, 5, 5, 10, 10, 10, 10, 10]
    f = F.season_features(rain, clim, prev=[10] * 12)
    assert f["jun_dep_pct"] == -50 and f["jul_dep_pct"] == -50 and f["jun_jul_dep_pct"] == -50
    assert f["premonsoon_dep_pct"] == -50 and f["prev_ond_dep_pct"] == 0
    assert F.season_label(rain, clim) == 1                   # Jun–Sep = 30 vs 40 normal = −25%
    assert F.season_label([10] * 12, clim) == 0


def test_bad_monthly_row_rejected(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("year,month,rain_mm\n2000,13,5\n")
    with pytest.raises(ValueError):
        F.load_years(p)


def test_artifacts_present_with_metadata():
    for name in ("season_classifier.json", "monthly_forecaster.json", "anomaly_detector.json", "metrics.json"):
        a = json.loads((ART / name).read_text())
        assert a["version"] and a["trained_at"] and len(a["data_sha256"]) == 64
    m = json.loads((ART / "metrics.json").read_text())
    assert m["data_sha256"] == json.loads((ART / "season_classifier.json").read_text())["data_sha256"]


def test_metrics_are_internally_consistent():
    m = json.loads((ART / "metrics.json").read_text())
    for name, r in m["classification"]["cv_results"].items():
        cm = r["confusion_matrix"]
        n = cm["tn"] + cm["fp"] + cm["fn"] + cm["tp"]
        assert n == r["n"]
        assert math.isclose(r["accuracy"], (cm["tn"] + cm["tp"]) / n, abs_tol=0.001)
    fc = m["forecasting"]
    assert fc["selected"] == min(fc["results"], key=lambda k: fc["results"][k]["mae"])


sk = pytest.importorskip("sklearn")
joblib = pytest.importorskip("joblib")
np = pytest.importorskip("numpy")


def _rows():
    years = F.load_years()
    use = [y for y in years if y - 1 in years]
    clim = F.climatology(years, use)
    X, _ = F.classification_rows(years, clim, use)
    return X


def test_classifier_json_matches_sklearn():
    obj = joblib.load(ART / "season_classifier.joblib")
    X = _rows()
    model, sc = obj["classifier"], obj["scaler"]
    ref = model.predict_proba(sc.transform(np.array(X)) if sc is not None else np.array(X))[:, 1]
    for x, r in zip(X, ref):
        assert abs(R.predict_season(x)["probability_deficient"] - r) < 1e-3


def test_explanation_adds_up_to_prediction():
    for x in _rows()[:20]:
        out = R.predict_season(x)
        e = out["explanation"]
        total = e["base_value"] + sum(c["contribution"] for c in e["contributions"])
        assert abs(total - out["probability_deficient"]) < 0.01


def test_isolation_forest_json_matches_sklearn():
    iso = joblib.load(ART / "anomaly_detector.joblib")
    years = F.load_years()
    use = list(years)
    clim = F.climatology(years, use)
    X, _ = F.anomaly_rows(F.monthly_series(years), clim, F.monthly_std(years, use, clim))
    ref = iso.decision_function(np.array(X[:300]))
    for x, r in zip(X[:300], ref):
        assert abs(R.anomaly_score(x) - r) < 1e-9


def test_forecast_uses_selected_model():
    m = json.loads((ART / "metrics.json").read_text())
    out = R.forecast_month(7)
    assert out["model"]["name"] == m["forecasting"]["selected"]
    assert out["forecast_mm"] > 0
