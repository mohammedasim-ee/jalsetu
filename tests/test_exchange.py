"""Treated-water exchange: validation, roles, ownership, ranked matching with hard filters."""
import pytest

from app import exchange

OFFER = {"organization": "Lakeview STP", "area": "Marathahalli", "qty_kl_per_day": 80, "treatment_level": "tertiary",
         "available_from": "2026-10-01", "available_to": "2027-03-31", "reuse_categories": ["construction", "landscaping"]}
REQ = {"requester": "Site A", "area": "Whitefield", "qty_kl_per_day": 60, "needed_from": "2026-10-15", "needed_to": "2026-12-15",
       "purpose": "construction", "min_treatment": "secondary"}


def test_score_pair_filters_and_parts():
    o = {**OFFER, "id": 1, "lat": 12.9569, "lng": 77.7011}
    r = {**REQ, "id": 2, "lat": 12.9698, "lng": 77.75}
    s = exchange.score_pair(o, r)
    assert s["eligible"] and s["km"] == 5.5 and s["parts"]["quantity"] == 1.0 and s["parts"]["availability"] == 1.0
    assert s["score"] == pytest.approx(0.45 * (1 - 5.5 / 25) + 0.35 + 0.20, abs=0.01)
    assert not exchange.score_pair({**o, "reuse_categories": ["flushing"]}, r)["eligible"]
    assert not exchange.score_pair({**o, "treatment_level": "secondary"}, {**r, "min_treatment": "tertiary"})["eligible"]
    blocked = exchange.score_pair({**o, "available_to": "2026-10-01"}, r)
    assert not blocked["eligible"] and "do not overlap" in blocked["blocked_by"][0]


def test_overlap_days():
    assert exchange.overlap_days("2026-10-01", "2026-10-10", "2026-10-05", "2026-10-20") == 6
    assert exchange.overlap_days("2026-10-01", "2026-10-01", "2026-10-02", "2026-10-03") == 0


def test_roles_and_validation(c, citizen, org):
    assert c.post("/api/treated-water/offers", json=OFFER).status_code == 401
    assert c.post("/api/treated-water/offers", json=OFFER, headers=citizen).status_code == 403
    for bad in ({"organization": " "}, {"qty_kl_per_day": 0}, {"reuse_categories": ["drinking"]}, {"available_to": "2026-01-01"},
                {"available_from": "tomorrow"}, {"area": "Mars"}, {"treatment_level": "none"}):
        assert c.post("/api/treated-water/offers", json={**OFFER, **bad}, headers=org).status_code == 422, bad
    assert c.post("/api/treated-water/requests", json={**REQ, "purpose": "drinking"}, headers=citizen).status_code == 422


def test_ranked_matching_ownership_and_unmet(c, org, org2, citizen):
    near = c.post("/api/treated-water/offers", json=OFFER, headers=org).json()
    far = c.post("/api/treated-water/offers", json={**OFFER, "organization": "Far STP", "area": "Kengeri"}, headers=org2).json()
    wrong_use = c.post("/api/treated-water/offers", json={**OFFER, "organization": "Garden only", "area": "Whitefield",
                                                          "reuse_categories": ["landscaping"]}, headers=org2).json()
    req = c.post("/api/treated-water/requests", json=REQ, headers=citizen).json()
    m = c.get(f"/api/matches?request_id={req['id']}&fresh_rs_per_kl=100").json()["results"][0]
    ids = [x["offer_id"] for x in m["matches"]]
    assert ids.index(near["id"]) < ids.index(far["id"]) and wrong_use["id"] not in ids
    top = m["matches"][0]
    assert top["offer_id"] == near["id"] and top["saving_rs_per_day"] == 60 * 90 and m["unmet"] is False
    blocked = c.get(f"/api/matches?request_id={req['id']}&include_blocked=true").json()["results"][0]["matches"]
    assert any(x["offer_id"] == wrong_use["id"] and not x["eligible"] for x in blocked)
    big = c.post("/api/treated-water/requests", json={**REQ, "qty_kl_per_day": 500}, headers=citizen).json()
    mb = c.get(f"/api/matches?request_id={big['id']}").json()["results"][0]
    assert mb["unmet"] is True and mb["unmet_kl_per_day"] == 420
    # only the owner (or admin) can close
    assert c.delete(f"/api/treated-water/offers/{near['id']}", headers=org2).status_code == 403
    assert c.delete(f"/api/treated-water/offers/{near['id']}", headers=citizen).status_code == 403
    assert c.delete(f"/api/treated-water/offers/{near['id']}", headers=org).status_code == 200
    assert all(o["id"] != near["id"] for o in c.get("/api/treated-water").json()["offers"])
    assert c.get("/api/matches?request_id=999999").status_code == 404
