"""water-risk-engine unit tests: normalisation, weights, classification, validation, warning rules."""
import pytest

from app import data_store as ds
from app import risk

CFG = ds.risk_config()


def inputs(**over):
    base = {"rainfall": -48.4, "groundwater": 186.7, "reservoir": 63.7, "demand": 25.6, "quality": 70.0, "community": 0}
    base.update(over)
    return {k: {"value": v, "as_of": "2026-09-28", "source": "t", "url": "https://x", "status": "historical"} for k, v in base.items()}


def test_weights_sum_to_one_and_levels_ordered():
    assert sum(c["weight"] for c in CFG["components"].values()) == pytest.approx(1)
    mins = [l["min"] for l in CFG["levels"]]
    assert mins == sorted(mins)


@pytest.mark.parametrize("v,low,high,exp", [(0, 0, -60, 0), (-30, 0, -60, 50), (-60, 0, -60, 100), (-90, 0, -60, 100), (10, 0, -60, 0),
                                            (80, 80, 20, 0), (50, 80, 20, 50), (186.7, 70, 100, 100), (85, 70, 100, 50)])
def test_normalise(v, low, high, exp):
    assert risk.normalise(v, low, high) == exp


def test_normalise_rejects_bad_input():
    with pytest.raises(risk.RiskInputError):
        risk.normalise(float("nan"), 0, 1)
    with pytest.raises(risk.RiskInputError):
        risk.normalise(1, 5, 5)


def test_current_score_matches_hand_calculation():
    r = risk.score(inputs(), CFG)
    expected = 0.25 * (48.4 / 60 * 100) + 0.25 * 100 + 0.20 * ((63.7 - 80) / (20 - 80) * 100) + 0.15 * (25.6 / 40 * 100) + 0.10 * 70 + 0
    assert r["score"] == pytest.approx(expected, abs=0.15) and r["level"] == "HIGH"
    assert sum(c["points"] for c in r["components"]) == pytest.approx(r["score"], abs=0.3)
    assert r["components"][0]["key"] == "groundwater"            # sorted by contribution


@pytest.mark.parametrize("over,level", [
    (dict(rainfall=10, groundwater=60, reservoir=95, demand=0, quality=0), "LOW"),
    (dict(rainfall=-60, groundwater=200, reservoir=10, demand=50, quality=100, community=60), "CRITICAL"),
])
def test_levels(over, level):
    assert risk.score(inputs(**over), CFG)["level"] == level


def test_score_rejects_out_of_range_inputs():
    with pytest.raises(risk.RiskInputError):
        risk.score(inputs(reservoir=140), CFG)
    with pytest.raises(risk.RiskInputError):
        risk.score(inputs(rainfall=None), CFG)


def test_explanation_lists_drivers_and_stale_data():
    r = risk.score(inputs(), CFG)
    text = " ".join(risk.explain(r))
    assert "Stage of groundwater extraction" in text and "+25.0 points" in text


def _res(*pcts):
    return {"cauvery_total": [{"pct_full": p, "date": f"2026-09-0{i + 1}"} for i, p in enumerate(pcts)]}


def test_warning_rules():
    rules = CFG["warning_rules"]
    ws = risk.evaluate_warnings({k: v for k, v in inputs().items()}, _res(63.7), [], rules)
    ids = {w["rule_id"]: w["level"] for w in ws}
    assert ids["BOREWELL_STRESS"] == "ALERT" and ids["RAIN_DEFICIT"] == "WARNING" and "RESERVOIR_LOW" not in ids
    assert ws[0]["level"] == "ALERT" and all(w["actions"] and w["trigger"] for w in ws)
    low = {w["rule_id"]: w for w in risk.evaluate_warnings(inputs(), _res(55, 45), [], rules)}
    assert low["RESERVOIR_LOW"]["level"] == "WARNING" and "declining" in low["RESERVOIR_LOW"]["trigger"]
    one = {w["rule_id"]: w for w in risk.evaluate_warnings(inputs(), _res(45), [], rules)}
    assert one["RESERVOIR_LOW"]["level"] == "WATCH" and "one reading" in one["RESERVOIR_LOW"]["trigger"]
    calm = risk.evaluate_warnings(inputs(rainfall=5, groundwater=60, quality=10), _res(80), [], rules)
    assert calm == []
    hot = risk.evaluate_warnings(inputs(rainfall=5, groundwater=60, quality=10), _res(80), [{"area": "Hebbal", "reports": 6}], rules)
    assert hot[0]["rule_id"] == "HOTSPOT_Hebbal"


def test_days_old():
    from datetime import date
    assert ds.days_old("2026-09-28", date(2026, 9, 30)) == 2
    assert ds.days_old("2026-08", date(2026, 9, 30)) == 30
    assert ds.days_old("2024", date(2026, 1, 1)) == 366       # a year value counts from 31 Dec
