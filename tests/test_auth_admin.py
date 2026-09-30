"""Authentication, roles, admin workflow, ingestion, audit logs."""
import time

import pytest

from app import auth, db


def test_password_hashing_never_plaintext():
    h = auth.hash_password("long-enough-pass")
    assert h.startswith("scrypt$") and "long-enough-pass" not in h
    assert auth.verify_password("long-enough-pass", h) and not auth.verify_password("wrong", h)
    assert auth.hash_password("same") != auth.hash_password("same")       # salted
    assert not auth.verify_password("x", "garbage")


def test_register_login_me_logout(c):
    r = c.post("/api/auth/register", json={"email": "Asha@Example.com", "password": "long-enough-pass", "name": "Asha"})
    assert r.status_code == 201 and r.json()["user"]["role"] == "citizen" and r.json()["user"]["email"] == "asha@example.com"
    row = db.one("SELECT password_hash FROM users WHERE email='asha@example.com'")
    assert row["password_hash"].startswith("scrypt$")
    assert c.post("/api/auth/register", json={"email": "asha@example.com", "password": "long-enough-pass", "name": "A"}).status_code == 409
    tok = c.post("/api/auth/login", json={"email": "asha@example.com", "password": "long-enough-pass"}).json()["token"]
    h = {"authorization": f"Bearer {tok}"}
    assert c.get("/api/auth/me", headers=h).json()["user"]["name"] == "Asha"
    assert db.one("SELECT token_hash FROM sessions WHERE token_hash=?", (auth.token_hash(tok),))
    assert not db.one("SELECT id FROM sessions WHERE token_hash=?", (tok,))          # raw token never stored
    assert c.post("/api/auth/logout", headers=h).status_code == 200
    assert c.get("/api/auth/me", headers=h).status_code == 401


@pytest.mark.parametrize("body,code", [
    ({"email": "bad", "password": "long-enough-pass", "name": "X"}, 422),
    ({"email": "a@b.co", "password": "short", "name": "X"}, 422),
    ({"email": "a@b.co", "password": "password", "name": "X"}, 422),
    ({"email": "a@b.co", "password": "long-enough-pass", "name": " "}, 422),
    ({"email": "a@b.co", "password": "long-enough-pass", "name": "X", "role": "admin"}, 422),
    ({"email": "a@b.co", "password": "long-enough-pass", "name": "X", "role": "organization"}, 422),
])
def test_register_validation(c, body, code):
    assert c.post("/api/auth/register", json=body).status_code == code


def test_login_wrong_password_and_unknown_user_same_message(c):
    a = c.post("/api/auth/login", json={"email": "admin@jalsetu.test", "password": "nope-nope-nope"})
    b = c.post("/api/auth/login", json={"email": "nobody@jalsetu.test", "password": "nope-nope-nope"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_expired_and_forged_tokens_rejected(c, citizen):
    assert c.get("/api/auth/me", headers={"authorization": "Bearer forged"}).status_code == 401
    tok = citizen["authorization"][7:]
    db.run("UPDATE sessions SET expires_at=? WHERE token_hash=?", (time.time() - 1, auth.token_hash(tok)))
    assert c.get("/api/auth/me", headers=citizen).status_code == 401


def test_admin_routes_need_admin(c, citizen, org, admin):
    for h in ({}, citizen, org):
        assert c.get("/api/admin/overview", headers=h).status_code in (401, 403)
    o = c.get("/api/admin/overview", headers=admin).json()
    assert o["api_health"]["database"] is True and o["ml"]["classifier"] and o["data_freshness"]


def test_report_review_workflow_and_audit(c, admin):
    rid = c.post("/api/reports", data={"category": "shortage", "area": "Hebbal", "description": "no water 3 days"}).json()["id"]
    assert c.patch(f"/api/admin/reports/{rid}", json={"status": "RESOLVED"}, headers=admin).status_code == 409   # skip not allowed
    assert c.patch(f"/api/admin/reports/{rid}", json={"status": "UNDER_REVIEW"}, headers=admin).json()["status"] == "UNDER_REVIEW"
    r = c.patch(f"/api/admin/reports/{rid}", json={"status": "VERIFIED", "note": "ward engineer confirmed"}, headers=admin).json()
    assert r["status"] == "VERIFIED" and [e["to_status"] for e in r["history"]] == ["SUBMITTED", "UNDER_REVIEW", "VERIFIED"]
    assert c.patch(f"/api/admin/reports/{rid}", json={"status": "RESOLVED"}, headers=admin).json()["status"] == "RESOLVED"
    assert c.patch(f"/api/admin/reports/{rid}", json={"status": "REJECTED"}, headers=admin).status_code == 409    # final
    logs = c.get("/api/admin/audit-logs", headers=admin).json()["logs"]
    assert any(l["action"] == "report_status" and l["target"] == f"report:{rid}" for l in logs)
    assert c.patch("/api/admin/reports/999999", json={"status": "VERIFIED"}, headers=admin).status_code == 404


def test_rejected_reports_hidden_by_default(c, admin):
    rid = c.post("/api/reports", data={"category": "other", "area": "Hebbal", "description": "spam"}).json()["id"]
    c.patch(f"/api/admin/reports/{rid}", json={"status": "REJECTED"}, headers=admin)
    assert all(r["id"] != rid for r in c.get("/api/reports?limit=200").json()["reports"])
    assert any(r["id"] == rid for r in c.get("/api/reports?status=REJECTED").json()["reports"])


def test_verified_reports_raise_community_component(c, admin):
    before = next(x for x in c.get("/api/risk/current").json()["components"] if x["key"] == "community")["value"]
    rid = c.post("/api/reports", data={"category": "groundwater", "area": "Yelahanka"}).json()["id"]
    c.patch(f"/api/admin/reports/{rid}", json={"status": "VERIFIED"}, headers=admin)
    after = next(x for x in c.get("/api/risk/current").json()["components"] if x["key"] == "community")["value"]
    assert after == before + 1
    assert len(c.get("/api/risk/history").json()["history"]) >= 2


def test_reservoir_ingestion_and_trend(c, admin, citizen):
    body = {"reservoir_id": "cauvery_total", "reservoir": "Cauvery basin reservoirs", "date": "2026-09-20",
            "storage_tmc": 50.0, "capacity_tmc": 86.3, "source": "Test bulletin", "url": "https://example.org/bulletin"}
    assert c.post("/api/admin/reservoir-readings", json=body, headers=citizen).status_code == 403
    assert c.post("/api/admin/reservoir-readings", json={**body, "url": "http://insecure"}, headers=admin).status_code == 422
    assert c.post("/api/admin/reservoir-readings", json={**body, "storage_tmc": 99}, headers=admin).status_code == 422
    assert c.post("/api/admin/reservoir-readings", json={**body, "date": "2099-01-01"}, headers=admin).status_code == 422
    assert c.post("/api/admin/reservoir-readings", json=body, headers=admin).status_code == 201
    r = c.get("/api/reservoirs/cauvery_total").json()
    assert r["latest"]["pct_full"] == 57.9 and r["trend"]["change_pct_points"] == -5.8
    db.run("DELETE FROM reservoir_readings")      # keep other tests on the official figure


def test_lake_observation_ingestion(c, admin):
    assert c.post("/api/admin/lake-observations", json={"lake_id": "nope", "date": "2025-11-01", "parameter": "class", "class": "E",
                                                         "source": "KSPCB", "url": "https://kspcb.karnataka.gov.in"}, headers=admin).status_code == 404
    assert c.post("/api/admin/lake-observations", json={"lake_id": "bellandur", "date": "2025-11-01", "parameter": "class", "class": "E",
                                                         "source": "KSPCB", "url": "https://kspcb.karnataka.gov.in"}, headers=admin).status_code == 201
    assert c.get("/api/lakes/bellandur").json()["observations"][0]["class"] == "E"


def test_admin_from_env_is_idempotent():
    a = auth.ensure_admin_from_env()
    b = auth.ensure_admin_from_env()
    assert a == b and db.one("SELECT role FROM users WHERE id=?", (a,))["role"] == "admin"


def test_admin_delete_report_removes_only_that_report(c, admin, citizen):
    from tests.conftest import jpeg
    keep = c.post("/api/reports", data={"category": "leakage", "area": "Hebbal", "description": "keep me"}).json()["id"]
    rid = c.post("/api/reports", data={"category": "groundwater", "area": "Yelahanka", "description": "rehearsal"},
                 files={"photo": ("p.jpg", jpeg(400, 300), "image/jpeg")}).json()["id"]
    c.patch(f"/api/admin/reports/{rid}", json={"status": "VERIFIED"}, headers=admin)
    comm = lambda: next(x for x in c.get("/api/risk/current").json()["components"] if x["key"] == "community")["value"]
    before = comm()
    assert c.delete(f"/api/admin/reports/{rid}").status_code == 401                 # not logged in
    assert c.delete(f"/api/admin/reports/{rid}", headers=citizen).status_code == 403  # not admin
    assert c.delete(f"/api/admin/reports/{rid}", headers=admin).json() == {"deleted": rid}
    assert c.get(f"/api/reports/{rid}").status_code == 404
    assert c.get(f"/api/reports/{rid}/photo").status_code == 404
    assert db.one("SELECT COUNT(*) AS n FROM report_events WHERE report_id=?", (rid,))["n"] == 0
    assert c.get(f"/api/reports/{keep}").status_code == 200                         # unrelated report untouched
    assert comm() == before - 1                                                      # verified count drops by exactly one
    assert c.delete(f"/api/admin/reports/{rid}", headers=admin).status_code == 404
    logs = c.get("/api/admin/audit-logs", headers=admin).json()["logs"]
    assert any(l["action"] == "report_delete" and l["target"] == f"report:{rid}" and "was VERIFIED" in l["detail"] for l in logs)


def test_short_admin_password_does_not_crash(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "other-admin@jalsetu.test")
    monkeypatch.setenv("ADMIN_PASSWORD", "short")
    assert auth.ensure_admin_from_env() is None
    assert db.one("SELECT id FROM users WHERE email='other-admin@jalsetu.test'") is None


def test_admin_login_applies_current_settings_and_health_reports_it(c, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "changed-later-pass")
    r = c.post("/api/auth/login", json={"email": " Admin@JalSetu.test ", "password": "changed-later-pass "})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    h = c.get("/api/health").json()["admin"]
    assert h == {"settings_present": True, "password_long_enough": True, "account_exists": True}
    monkeypatch.setenv("ADMIN_PASSWORD", "correct-horse-battery")
    assert c.post("/api/auth/login", json={"email": "admin@jalsetu.test", "password": "correct-horse-battery"}).status_code == 200
