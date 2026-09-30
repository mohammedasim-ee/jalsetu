"""Data pipeline: validation catches bad rows, features are correct, output is reproducible."""
import json
from pathlib import Path

import pytest

from pipeline import gis, indicators, rainfall, run_pipeline

ROOT = Path(__file__).resolve().parent.parent


def _csv(tmp_path, rows):
    head = "SUBDIVISION,YEAR," + ",".join(rainfall.MONTHS) + ",ANNUAL\n"
    p = tmp_path / "r.csv"
    p.write_text(head + "".join(rows))
    return p


def test_validation_drops_bad_rows(tmp_path):
    ok = "SOUTH INTERIOR KARNATAKA,2000," + ",".join(["10"] * 12) + ",120\n"
    miss = "SOUTH INTERIOR KARNATAKA,2001," + ",".join(["NA"] + ["10"] * 11) + ",110\n"
    neg = "SOUTH INTERIOR KARNATAKA,2002," + ",".join(["-1"] + ["10"] * 11) + ",109\n"
    dup = ok
    mism = "SOUTH INTERIOR KARNATAKA,2004," + ",".join(["10"] * 12) + ",500\n"
    other = "KERALA,2000," + ",".join(["10"] * 12) + ",120\n"
    rows, rep = rainfall.load_and_validate(_csv(tmp_path, [ok, miss, neg, dup, mism, other]))
    assert [r["year"] for r in rows] == [2000, 2004]
    assert rep["missing_values"] == 1 and rep["negative_values"] == 1 and rep["duplicate_years"] == 1
    assert rep["annual_sum_mismatch"] == 1 and rep["missing_years"] == [2001, 2002, 2003]


def test_missing_column_is_an_error(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("SUBDIVISION,YEAR,JAN\n")
    with pytest.raises(ValueError):
        rainfall.load_and_validate(p)


def test_statistics():
    assert rainfall.moving_average([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    t = rainfall.linear_trend([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
    assert t["slope_per_year"] == pytest.approx(2) and t["slope_per_decade"] == pytest.approx(20)
    assert rainfall.mann_kendall(list(range(40)))["trend"] == "increasing"
    assert rainfall.mann_kendall([5, 1, 4, 2, 3, 3, 2, 4, 1, 5])["trend"] == "no significant trend"
    assert [rainfall.imd_category(x) for x in (65, 25, 0, -25, -70, -100)] == ["Large excess", "Excess", "Normal", "Deficient", "Large deficient", "No rain"]


def test_anomaly_definition():
    rows = [{"year": 2000, "months": [10.0] * 12}, {"year": 2001, "months": [30.0] * 12}]
    monthly, a = rainfall.build_features(rows)
    first = monthly[0]
    assert first["anomaly_mm"] == -10 and first["anomaly_pct"] == -50
    assert a["seasons"][0]["jjas_departure_pct"] == -50 and a["seasons"][0]["jjas_category"] == "Deficient"


def test_gis_point_in_polygon_and_simplify():
    sq = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    f = {"geometry": {"type": "Polygon", "coordinates": [sq]}}
    assert gis.point_in_feature(0.5, 0.5, f) and not gis.point_in_feature(1.5, 0.5, f)
    line = [(0, 0), (1, 0.0001), (2, 0), (3, 0)]
    assert gis.rdp(line, 0.01) == [(0, 0), (3, 0)]


def test_indicator_validation_rejects_missing_source():
    raw = json.loads((ROOT / "data/raw/official_indicators.json").read_text())
    raw["rainfall_current_season"]["url"] = ""
    with pytest.raises(indicators.IndicatorError):
        indicators.process(raw)
    raw = json.loads((ROOT / "data/raw/official_indicators.json").read_text())
    raw["reservoir_readings"][1]["pct_full"] = 140
    with pytest.raises(indicators.IndicatorError):
        indicators.process(raw)


def test_pipeline_is_reproducible():
    before = json.loads((ROOT / "data/processed/manifest.json").read_text())["outputs"]
    res = run_pipeline.main()
    assert res["manifest"]["outputs"] == before            # same raw data -> byte-identical outputs
    v = res["validation"]
    assert v["rainfall"]["rows_kept"] == 115 and v["wards"]["features_kept"] == 243 and v["lakes"]["rows_kept"] == 7
    assert 700 < v["wards"]["total_area_km2"] < 720        # BBMP is ~712 km²
