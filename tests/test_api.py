import io
import os
import tempfile

os.environ["JALSETU_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["ADMIN_TOKEN"] = "test-admin"
os.environ["JALSETU_WRITE_LIMIT"] = "1000"
os.environ.pop("ANTHROPIC_API_KEY", None)

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import ai, main, rules

c = TestClient(main.app)


def jpeg(w=3000, h=4000):
    b = io.BytesIO(); Image.new("RGB", (w, h), (80, 110, 130)).save(b, "JPEG"); return b.getvalue()


# ---------- meta + website
def test_health_and_site():
    r = c.get("/api/health"); assert r.status_code == 200 and r.json()["ok"] is True and r.json()["ai"] is False
    r = c.get("/"); assert r.status_code == 200 and "JalSetu" in r.text
    assert c.get("/docs").status_code == 200


def test_signals_computed_from_official_figures():
    s = c.get("/api/signals").json()
    urban = s["rain"]["districts"][0]
    assert urban["departure_pct"] == -48 and urban["level"] == "alert"
    assert s["rain"]["districts"][1]["level"] == "watch"          # -20%
    assert s["reservoirs"]["pct"] == 63.7
    assert s["groundwater"]["pumped_vs_recharge"] == 9.3
    assert s["reading"]["borewell_areas"] == "alert"
    assert s["reading"]["cauvery_piped_areas"] == "lower_near_term_risk"


# ---------- reports
def test_report_create_list_photo_and_hotspot():
    r = c.post("/api/reports", data={"type": "dry", "area": "Whitefield", "note": "1,000 ft borewell dry"},
               files={"photo": ("p.jpg", jpeg(), "image/jpeg")})
    assert r.status_code == 201, r.text
    rep = r.json(); assert rep["photo_url"] and rep["ai"] is None
    ph = c.get(rep["photo_url"]); assert ph.status_code == 200 and ph.headers["content-type"] == "image/jpeg"
    assert len(ph.content) < 120_000                                 # 12 MP photo shrunk
    assert any(x["id"] == rep["id"] for x in c.get("/api/reports").json()["reports"])
    hs = c.get("/api/hotspots").json(); assert {"area": "Whitefield", "reports": 1} in hs["areas"]


@pytest.mark.parametrize("data,msg", [
    ({"type": "flood", "area": "Whitefield"}, "Choose what happened"),
    ({"type": "dry", "area": "Mars"}, "Choose an area"),
    ({"type": "tanker", "area": "Whitefield", "litres": 6000}, "price"),
    ({"type": "tanker", "area": "Whitefield", "price": -5, "litres": 6000}, "price"),
    ({"type": "tanker", "area": "Whitefield", "price": 1500, "litres": 7000}, "tanker size"),
])
def test_report_validation(data, msg):
    r = c.post("/api/reports", data=data); assert r.status_code == 422 and msg in r.json()["error"]


def test_report_rejects_non_image_and_huge_file():
    r = c.post("/api/reports", data={"type": "dry", "area": "Hebbal"}, files={"photo": ("x.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 415
    r = c.post("/api/reports", data={"type": "dry", "area": "Hebbal"}, files={"photo": ("x.jpg", b"0" * (9 * 1024 * 1024), "image/jpeg")})
    assert r.status_code == 413


def test_tanker_average_and_note_trimmed():
    c.post("/api/reports", data={"type": "tanker", "area": "Bellandur", "price": 1500, "litres": 6000, "note": "x" * 900})
    hs = c.get("/api/hotspots").json(); assert hs["tanker"]["avg_rs_per_1000l"] == 250.0
    last = c.get("/api/reports?limit=1").json()["reports"][0]; assert len(last["note"]) == 300


def test_html_is_stored_as_text_not_interpreted():
    r = c.post("/api/reports", data={"type": "dry", "area": "Hebbal", "note": "<script>alert(1)</script>"})
    assert r.json()["note"] == "<script>alert(1)</script>"         # the page escapes it when showing


def test_delete_report_needs_moderator():
    rid = c.post("/api/reports", data={"type": "low", "area": "Hebbal"}).json()["id"]
    assert c.delete(f"/api/reports/{rid}").status_code == 403
    assert c.delete(f"/api/reports/{rid}", headers={"x-admin-token": "wrong"}).status_code == 403
    assert c.delete(f"/api/reports/{rid}", headers={"x-admin-token": "test-admin"}).status_code == 200
    assert c.delete(f"/api/reports/{rid}", headers={"x-admin-token": "test-admin"}).status_code == 404


# ---------- listings + matching
def test_listings_match_and_owner_only_delete():
    s = c.post("/api/listings", json={"kind": "supply", "area": "Marathahalli", "name": "Lakeview STP", "qty": 80}).json()
    d = c.post("/api/listings", json={"kind": "demand", "area": "Whitefield", "name": "Site A", "qty": 60}).json()
    assert s["edit_token"] and "token_hash" not in s
    m = c.get("/api/match?fresh_rs_per_kl=100").json()
    pair = [x for x in m["matches"] if x["to"] == "Site A"][0]
    assert pair["from"] == "Lakeview STP" and pair["kl_per_day"] == 60 and pair["km"] == 5.5
    assert m["saving_rs_per_day"] >= 60 * 90
    assert c.delete(f"/api/listings/{s['id']}").status_code == 403
    assert c.delete(f"/api/listings/{s['id']}", headers={"x-edit-token": d["edit_token"]}).status_code == 403
    assert c.delete(f"/api/listings/{s['id']}", headers={"x-edit-token": s["edit_token"]}).status_code == 200
    assert c.delete(f"/api/listings/{d['id']}", headers={"x-admin-token": "test-admin"}).status_code == 200


@pytest.mark.parametrize("body", [
    {"kind": "supply", "area": "Whitefield", "name": "   ", "qty": 5},
    {"kind": "supply", "area": "Whitefield", "name": "A", "qty": 0},
    {"kind": "supply", "area": "Whitefield", "name": "A", "qty": 99999},
    {"kind": "sell", "area": "Whitefield", "name": "A", "qty": 5},
    {"kind": "supply", "area": "Nowhere", "name": "A", "qty": 5},
])
def test_listing_validation(body):
    r = c.post("/api/listings", json=body); assert r.status_code == 422 and r.json()["error"]


def test_unmet_demand_reported():
    out = rules.match([{"kind": "demand", "area": "Hebbal", "name": "Big site", "qty": 50}])
    assert out == [{"from": None, "to": "Big site", "to_area": "Hebbal", "kl_per_day": 50}]


# ---------- IS 10500 + RWH rules
@pytest.mark.parametrize("values,verdict", [
    ({"pH": 7.2, "tds": 450, "tc": 0}, "safe"),
    ({"pH": 7.0, "tds": 1200}, "only_if_no_other_source"),
    ({"no3": 60}, "unsafe"),
    ({"tc": 3}, "unsafe"),
    ({"pH": 9}, "unsafe"),
    ({"tds": -5}, "no_values"),
    ({}, "no_values"),
])
def test_water_check(values, verdict):
    r = c.post("/api/quality/check", json={"values": values}).json(); assert r["verdict"] == verdict


def test_water_check_flags_invalid_and_bacteria():
    r = c.post("/api/quality/check", json={"values": {"pH": 15, "tds": 300, "ec": 1}}).json()
    assert "pH" in r["invalid"] and r["bacteria_found"] is True and r["verdict"] == "unsafe"


@pytest.mark.parametrize("body,mandatory,storage", [
    ({"length_ft": 40, "width_ft": 60, "built": "old", "roof_sqm": 150, "paved_sqm": 30}, True, 3300),
    ({"length_ft": 30, "width_ft": 40, "built": "old", "roof_sqm": 100}, False, 2000),
    ({"length_ft": 30, "width_ft": 40, "built": "new", "roof_sqm": 100}, True, 2000),
    ({"length_ft": 0, "width_ft": 0, "built": "new"}, False, 0),
])
def test_rwh(body, mandatory, storage):
    r = c.post("/api/rwh", json=body).json()
    assert r["mandatory"] is mandatory and r["min_storage_litres"] == storage
    assert len(r["monthly_harvest_kl"]) == 12


def test_rwh_rejects_negative():
    assert c.post("/api/rwh", json={"length_ft": -1, "width_ft": 10}).status_code == 422


# ---------- AI switched off / on (mocked)
def test_ai_off_gives_clear_message():
    r = c.post("/api/ai/lab-report", files={"photo": ("r.jpg", jpeg(400, 400), "image/jpeg")})
    assert r.status_code == 503 and "switched off" in r.json()["error"]


def test_ai_on_mocked(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(ai, "verify_report_photo", lambda *a: {"cls": "bad", "text": "AI: photo doesn't match · a cat"})
    monkeypatch.setattr(ai, "read_lab_report", lambda *a: {"pH": 7.1, "no3": 70.0})
    rep = c.post("/api/reports", data={"type": "sewage", "area": "Varthur"}, files={"photo": ("p.jpg", jpeg(500, 500), "image/jpeg")}).json()
    assert rep["ai"]["cls"] == "bad"
    hs = c.get("/api/hotspots").json(); assert all(a["area"] != "Varthur" for a in hs["areas"])   # rejected photo not counted
    lab = c.post("/api/ai/lab-report", files={"photo": ("r.jpg", jpeg(500, 500), "image/jpeg")}).json()
    assert lab["values"]["no3"] == 70.0 and lab["check"]["verdict"] == "unsafe"


def test_ai_failure_does_not_block_report(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    def boom(*a): raise RuntimeError("network down")
    monkeypatch.setattr(ai, "verify_report_photo", boom)
    r = c.post("/api/reports", data={"type": "dry", "area": "Kengeri"}, files={"photo": ("p.jpg", jpeg(300, 300), "image/jpeg")})
    assert r.status_code == 201 and r.json()["ai"]["cls"] == "wait"


def test_rate_limit(monkeypatch):
    monkeypatch.setattr(main, "WRITE_LIMIT", 3); main._hits.clear()
    codes = [c.post("/api/reports", data={"type": "dry", "area": "Hebbal"}).status_code for _ in range(5)]
    assert codes[:3] == [201] * 3 and codes[3:] == [429, 429]
    main._hits.clear()


def test_unknown_route_404():
    assert c.get("/api/nothing").status_code == 404


def test_offline_api_page():
    r = c.get("/api"); assert r.status_code == 200 and "/api/reports" in r.text and "/api/match" in r.text
