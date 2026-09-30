"""Core API tests: health, data endpoints with provenance, calculators, reports workflow, validation, safety."""
import pytest

from app import main, rules
from tests.conftest import jpeg


def test_health_site_and_docs(c):
    h = c.get("/api/health").json()
    assert h["ok"] is True and h["ai"] is False and h["schema_version"] == 2
    assert h["data_mode"].startswith("official data") and h["models"]["version"]
    assert c.get("/").status_code == 200 and "JalSetu" in c.get("/").text
    assert c.get("/docs").status_code == 200
    r = c.get("/api")
    assert r.status_code == 200 and "/api/risk/current" in r.text and "/api/admin/reports/{rid}" in r.text


def test_security_headers_and_request_id(c):
    r = c.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert len(r.headers["x-request-id"]) >= 8


def test_v1_signals_still_served(c):
    s = c.get("/api/signals").json()
    assert s["rain"]["districts"][0]["departure_pct"] == -48 and s["reservoirs"]["pct"] == 63.7
    assert s["groundwater"]["pumped_vs_recharge"] == 9.3


# ---------------------------------------------------------------- data endpoints carry provenance
@pytest.mark.parametrize("path", ["/api/rainfall", "/api/reservoirs", "/api/groundwater", "/api/lakes", "/api/risk/current"])
def test_every_data_endpoint_has_sources(c, path):
    txt = c.get(path).text
    assert "source" in txt and "https://" in txt


def test_rainfall_analysis(c):
    r = c.get("/api/rainfall").json()
    h = r["historical"]
    assert h["years"] == [1901, 2015] and len(h["climatology"]) == 12
    assert r["current_season"]["districts"][0]["departure_pct"] == -48.4
    assert r["current_season"]["districts"][0]["anomaly_mm"] == -213.9
    assert h["mann_kendall_jjas"]["p_value"] < 0.05
    hist = c.get("/api/rainfall/history?start=2010&end=2015&monthly=true").json()
    assert [s["year"] for s in hist["seasons"]] == list(range(2010, 2016)) and len(hist["monthly"]) == 72
    assert c.get("/api/rainfall/history?start=2015&end=2010").status_code == 422


def test_reservoirs_and_single_reading_trend_note(c):
    r = c.get("/api/reservoirs").json()
    tot = next(x for x in r["reservoirs"] if x["id"] == "cauvery_total")
    assert tot["latest"]["pct_full"] == 63.7 and tot["latest"]["date"] == "2026-09-05"
    assert r["risk_contribution"]["key"] == "reservoir"
    assert c.get("/api/reservoirs/krs").json()["latest"]["pct_full"] == 59.35
    assert c.get("/api/reservoirs/nope").status_code == 404


def test_groundwater_separates_real_and_modelled(c):
    g = c.get("/api/groundwater").json()
    assert g["official"]["stage_of_extraction_pct"] == 186.7 and g["official"]["category"] == "over-exploited"
    assert g["modelled"]["data_type"].startswith("ESTIMATED") and g["modelled"]["extraction_ratio"] == 9.27
    assert g["trend"]["available"] is False


def test_lakes_and_gis(c):
    lakes = c.get("/api/lakes").json()["lakes"]
    assert len(lakes) == 7 and all(l["url"].startswith("https://en.wikipedia.org/") for l in lakes)
    bell = c.get("/api/lakes/bellandur").json()
    assert bell["ward"]["name"] == "Bellanduru" and bell["observations"] == []
    w = c.get("/api/gis/wards")
    assert w.headers["cache-control"].startswith("public") and len(w.json()["features"]) == 243
    assert c.get("/api/gis/layers").json()["ward_risk"]["available"] is False


# ---------------------------------------------------------------- water quality (IS 10500) — v1 cases kept
@pytest.mark.parametrize("values,verdict", [
    ({"pH": 7.2, "tds": 450, "tc": 0}, "safe"),
    ({"pH": 7.0, "tds": 1200}, "only_if_no_other_source"),
    ({"no3": 60}, "unsafe"),
    ({"tc": 3}, "unsafe"),
    ({"pH": 9}, "unsafe"),
    ({"tds": -5}, "no_values"),
    ({}, "no_values"),
])
def test_water_check(c, values, verdict):
    assert c.post("/api/water-quality/check", json={"values": values}).json()["verdict"] == verdict


def test_water_check_invalid_and_bacteria(c):
    r = c.post("/api/water-quality/check", json={"values": {"pH": 15, "tds": 300, "ec": 1}}).json()
    assert "pH" in r["invalid"] and r["bacteria_found"] is True and r["verdict"] == "unsafe"


def test_all_18_parameters_boundaries():
    for key, (_, _, acc, perm, kind) in rules.IS10500.items():
        if kind == "range":
            assert rules.judge(key, acc[0]) == "ok" and rules.judge(key, acc[1]) == "ok" and rules.judge(key, acc[1] + 0.01) == "unsafe"
        elif kind == "zero":
            assert rules.judge(key, 0) == "ok" and rules.judge(key, 0.1) == "unsafe"
        else:
            assert rules.judge(key, acc) == "ok"
            if perm is None:
                assert rules.judge(key, acc * 1.01) == "unsafe"
            else:
                assert rules.judge(key, acc * 1.01) == "high" and rules.judge(key, perm) == "high" and rules.judge(key, perm * 1.01) == "unsafe"
    assert len(rules.IS10500) == 18
    assert c_get_limits_count() == 18


def c_get_limits_count():
    from fastapi.testclient import TestClient
    return len(TestClient(main.app).get("/api/water-quality").json()["limits"])


# ---------------------------------------------------------------- rainwater harvesting
@pytest.mark.parametrize("body,mandatory,storage", [
    ({"length_ft": 40, "width_ft": 60, "built": "old", "roof_sqm": 150, "paved_sqm": 30}, True, 3300),
    ({"length_ft": 30, "width_ft": 40, "built": "old", "roof_sqm": 100}, False, 2000),
    ({"length_ft": 30, "width_ft": 40, "built": "new", "roof_sqm": 100}, True, 2000),
    ({"length_ft": 0, "width_ft": 0, "built": "new"}, False, 0),
])
def test_rwh_rules(c, body, mandatory, storage):
    r = c.post("/api/rwh", json=body).json()
    assert r["mandatory"] is mandatory and r["min_storage_litres"] == storage and len(r["monthly_harvest_kl"]) == 12


def test_rwh_formula_units_and_fine(c):
    # 100 m² roof, 1000 mm/year, C 0.8, efficiency 0.9 -> 100 × 1000 × 0.8 × 0.9 = 72,000 L = 72 kL
    r = c.post("/api/rwh", json={"length_ft": 60, "width_ft": 40, "built": "old", "roof_sqm": 100, "runoff_coefficient": 0.8,
                                 "collection_efficiency": 0.9, "annual_rain_mm": 1000, "monthly_bill_rs": 800}).json()
    assert r["yearly_harvest_kl"] == pytest.approx(72.0, abs=0.1) and r["annual_rain_mm"] == 1000
    assert r["first_year_penalty_avoided_rs"] == 8400 and r["site_sqm"] == 223.0
    assert rules.harvest_litres(1, 1, 1, 1) == 1       # 1 mm on 1 m² = 1 litre
    imd = c.post("/api/rwh", json={"length_ft": 10, "width_ft": 10, "roof_sqm": 100, "rainfall_series": "imd_sik_1901_2015"}).json()
    assert imd["rainfall_source"]["status"] == "historical" and imd["annual_rain_mm"] == pytest.approx(1040.4, abs=0.2)
    assert c.post("/api/rwh", json={"length_ft": -1, "width_ft": 10}).status_code == 422
    assert c.post("/api/rwh", json={"length_ft": 1, "width_ft": 1, "runoff_coefficient": 1.5}).status_code == 422


# ---------------------------------------------------------------- community reports
def test_report_create_with_photo_ward_and_history(c):
    r = c.post("/api/reports", data={"category": "groundwater", "area": "Whitefield", "description": "1,000 ft borewell dry"},
               files={"photo": ("p.jpg", jpeg(), "image/jpeg")})
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["status"] == "SUBMITTED" and rep["ward"] and rep["photo_url"] and rep["ai"] is None
    ph = c.get(rep["photo_url"])
    assert ph.status_code == 200 and ph.headers["content-type"] == "image/jpeg" and len(ph.content) < 120_000
    assert c.get(f"/api/reports/{rep['id']}").json()["history"][0]["to_status"] == "SUBMITTED"
    assert any(a["area"] == "Whitefield" for a in c.get("/api/hotspots").json()["areas"])


def test_report_with_map_point(c):
    r = c.post("/api/reports", data={"category": "leakage", "lat": 12.93417, "lng": 77.66278, "description": "pipe burst"}).json()
    assert r["ward"]["name"] == "Bellanduru" and r["lat"] == 12.93417
    assert c.post("/api/reports", data={"category": "leakage", "lat": 19.07, "lng": 72.87}).status_code == 422


@pytest.mark.parametrize("data,msg", [
    ({"category": "flood", "area": "Whitefield"}, "category"),
    ({"category": "shortage", "area": "Mars"}, "area"),
    ({"category": "tanker", "area": "Whitefield", "litres": 6000}, "price"),
    ({"category": "tanker", "area": "Whitefield", "price": -5, "litres": 6000}, "price"),
    ({"category": "tanker", "area": "Whitefield", "price": 1500, "litres": 7000}, "tanker size"),
])
def test_report_validation(c, data, msg):
    r = c.post("/api/reports", data=data)
    assert r.status_code == 422 and msg in r.json()["error"]


def test_report_rejects_non_image_and_huge_file(c):
    assert c.post("/api/reports", data={"category": "shortage", "area": "Hebbal"},
                  files={"photo": ("x.jpg", b"not an image", "image/jpeg")}).status_code == 415
    assert c.post("/api/reports", data={"category": "shortage", "area": "Hebbal"},
                  files={"photo": ("x.jpg", b"0" * (9 * 1024 * 1024), "image/jpeg")}).status_code == 413


def test_tanker_average_and_description_trimmed(c):
    c.post("/api/reports", data={"category": "tanker", "area": "Bellandur", "price": 1500, "litres": 6000, "description": "x" * 900})
    hs = c.get("/api/hotspots").json()
    assert hs["tanker"]["avg_rs_per_1000l"] == 250.0
    assert len(c.get("/api/reports?limit=1").json()["reports"][0]["description"]) == 500


def test_html_stored_as_text(c):
    r = c.post("/api/reports", data={"category": "other", "area": "Hebbal", "description": "<script>alert(1)</script>"})
    assert r.json()["description"] == "<script>alert(1)</script>"


def test_filters_validate(c):
    assert c.get("/api/reports?status=NOPE").status_code == 422
    assert c.get("/api/reports?category=nope").status_code == 422
    assert all(r["category"] == "leakage" for r in c.get("/api/reports?category=leakage").json()["reports"])


# ---------------------------------------------------------------- ML + forecast APIs
def test_ml_predict_with_explanation(c):
    r = c.post("/api/ml/predict", json={"jun_dep_pct": -45, "jul_dep_pct": -40}).json()
    assert 0 <= r["probability_deficient"] <= 1 and r["model"]["version"] and r["generated_at"]
    e = r["explanation"]
    assert abs(e["base_value"] + sum(x["contribution"] for x in e["contributions"]) - r["probability_deficient"]) < 0.01
    wet = c.post("/api/ml/predict", json={"jun_dep_pct": 40, "jul_dep_pct": 35}).json()
    assert wet["probability_deficient"] < r["probability_deficient"]
    assert c.post("/api/ml/predict", json={"jun_dep_pct": -150, "jul_dep_pct": 0}).status_code == 422


def test_forecast_and_models(c):
    f = c.get("/api/forecast?month=10").json()
    assert f["forecast_mm"] > 0 and f["evaluation"]["selected"] == f["model"]["name"]
    assert c.get("/api/forecast?month=13").status_code == 422
    assert len(c.get("/api/forecast/backtest?start=2015").json()["rows"]) == 12
    m = c.get("/api/ml/models").json()
    assert m["classification"]["cv_results"]["random_forest"]["confusion_matrix"]


def test_ml_anomaly(c):
    wet_march = c.post("/api/ml/anomaly", json={"month": 3, "rain_mm": 108.9, "prev_month_mm": 1, "prev2_month_mm": 2}).json()
    normal_july = c.post("/api/ml/anomaly", json={"month": 7, "rain_mm": 230, "prev_month_mm": 140, "prev2_month_mm": 90}).json()
    assert wet_march["anomalous"] is True and normal_july["anomalous"] is False


# ---------------------------------------------------------------- misc safety
def test_rate_limit(c, monkeypatch):
    from app import common
    monkeypatch.setattr(common, "WRITE_LIMIT", 3)
    common._hits.clear()
    codes = [c.post("/api/reports", data={"category": "shortage", "area": "Hebbal"}).status_code for _ in range(5)]
    assert codes[:3] == [201] * 3 and codes[3:] == [429, 429]
    common._hits.clear()


def test_unknown_route_and_server_error_is_json(c, monkeypatch):
    assert c.get("/api/nothing").status_code == 404
    from app import routes_data
    monkeypatch.setattr(routes_data.risk, "current", lambda **k: 1 / 0)
    from fastapi.testclient import TestClient
    r = TestClient(main.app, raise_server_exceptions=False).get("/api/risk/current")
    assert r.status_code == 500 and r.json()["ref"] and "ZeroDivision" not in r.text


def test_ai_off_gives_clear_message(c):
    r = c.post("/api/ai/lab-report", files={"photo": ("r.jpg", jpeg(400, 400), "image/jpeg")})
    assert r.status_code == 503 and "switched off" in r.json()["error"]


def test_ai_on_mocked_and_failure(c, monkeypatch):
    from app import ai
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(ai, "verify_report_photo", lambda *a: {"cls": "bad", "text": "AI: photo doesn't match · a cat"})
    rep = c.post("/api/reports", data={"category": "drainage", "area": "Varthur"}, files={"photo": ("p.jpg", jpeg(500, 500), "image/jpeg")}).json()
    assert rep["ai"]["cls"] == "bad"
    assert all(a["area"] != "Varthur" for a in c.get("/api/hotspots").json()["areas"])

    def boom(*a):
        raise RuntimeError("network down")
    monkeypatch.setattr(ai, "verify_report_photo", boom)
    r = c.post("/api/reports", data={"category": "shortage", "area": "Kengeri"}, files={"photo": ("p.jpg", jpeg(300, 300), "image/jpeg")})
    assert r.status_code == 201 and r.json()["ai"]["cls"] == "wait"


def test_every_endpoint_documented():
    from app.api_docs import DESCRIPTIONS
    spec = main.app.openapi()
    ops = {(m, p) for p, o in spec["paths"].items() for m in o}
    assert ops == set(DESCRIPTIONS)
