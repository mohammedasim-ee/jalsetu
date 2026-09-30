"""Admin APIs (role: admin). Every change is written to audit_logs."""
from __future__ import annotations

import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from . import ai, auth, db, ml_runtime, risk, rules
from . import data_store as ds

router = APIRouter(prefix="/api/admin")
admin_only = auth.require("admin")


@router.get("/overview")
def overview(user: dict = Depends(admin_only)):
    by_status = {r["status"]: r["n"] for r in db.rows("SELECT status, COUNT(*) AS n FROM reports GROUP BY status")}
    r = risk.current(record=False)
    ind = ds.indicators()
    fresh = [{"dataset": c["indicator"], "as_of": c["as_of"], "days_old": c["days_old"], "stale": c["stale"], "status": c["status"]}
             for c in r["components"]]
    m = ml_runtime.load("metrics.json")
    return {
        "reports": {"by_status": by_status, "total": sum(by_status.values()),
                    "unresolved": sum(v for k, v in by_status.items() if k in ("SUBMITTED", "UNDER_REVIEW", "VERIFIED"))},
        "risk": {"score": r["score"], "level": r["level"]},
        "warnings": risk.current_warnings(record=False),
        "data_freshness": fresh,
        "pipeline": ds.manifest(),
        "api_health": {"database": db.ping(), "schema_version": db.schema_version(), "dialect": db.DIALECT, "ai_enabled": ai.enabled()},
        "ml": {"version": m["version"], "trained_at": m["trained_at"],
               "classifier": m["classification"]["selected"], "forecaster": m["forecasting"]["selected"],
               "predictions_logged": (db.one("SELECT COUNT(*) AS n FROM model_predictions") or {"n": 0})["n"],
               "recent_predictions": db.rows("SELECT model, version, output, created_at FROM model_predictions ORDER BY created_at DESC LIMIT 5")},
        "exchange": {"open_offers": db.one("SELECT COUNT(*) AS n FROM offers WHERE status='OPEN'")["n"],
                     "open_requests": db.one("SELECT COUNT(*) AS n FROM requests WHERE status='OPEN'")["n"]},
        "users": {r2["role"]: r2["n"] for r2 in db.rows("SELECT role, COUNT(*) AS n FROM users GROUP BY role")},
        "activity": db.rows("SELECT a.action, a.target, a.detail, a.created_at, u.email FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id "
                            "ORDER BY a.created_at DESC LIMIT 20"),
        "sources": {"rainfall": ind["rainfall_current_season"]["source"]},
    }


@router.get("/reports")
def reports(status: Optional[str] = None, limit: int = Query(100, ge=1, le=500), user: dict = Depends(admin_only)):
    from .routes_community import COLS, report_out
    if status and status not in rules.REPORT_STATUSES:
        raise HTTPException(422, "Unknown status.")
    sql = f"SELECT {COLS}, user_id FROM reports" + (" WHERE status=?" if status else "") + " ORDER BY created_at DESC LIMIT ?"  # noqa: S608 (constant columns)
    return {"reports": [report_out(r) | {"user_id": r["user_id"]} for r in db.rows(sql, ((status,) if status else ()) + (limit,))],
            "statuses": rules.REPORT_STATUSES, "allowed_transitions": {k: sorted(v) for k, v in rules.STATUS_FLOW.items()}}


class StatusIn(BaseModel):
    status: Literal["SUBMITTED", "UNDER_REVIEW", "VERIFIED", "RESOLVED", "REJECTED"]
    note: str = Field("", max_length=300)


@router.patch("/reports/{rid}")
def update_report(rid: int, body: StatusIn, request: Request, user: dict = Depends(admin_only)):
    r = db.one("SELECT id, status FROM reports WHERE id=?", (rid,))
    if not r:
        raise HTTPException(404, "Report not found.")
    cur = r["status"] or "SUBMITTED"
    if body.status not in rules.STATUS_FLOW[cur]:
        raise HTTPException(409, f"A {cur} report can't move to {body.status}. Allowed: {', '.join(sorted(rules.STATUS_FLOW[cur])) or 'none (final)'}.")
    now = time.time()
    with db.db() as c:
        c.execute("UPDATE reports SET status=?, updated_at=? WHERE id=?", (body.status, now, rid))
        c.execute("INSERT INTO report_events(report_id,from_status,to_status,note,actor_id,created_at) VALUES(?,?,?,?,?,?)",
                  (rid, cur, body.status, body.note.strip() or None, user["id"], now))
    auth.audit(user, "report_status", f"report:{rid}", f"{cur} -> {body.status} {body.note}", request)
    from .routes_community import get_report
    return get_report(rid)


@router.delete("/reports/{rid}")
def delete_report(rid: int, request: Request, user: dict = Depends(admin_only)):
    """Permanently delete one report, its photo (stored in the same row) and its status history."""
    r = db.one("SELECT id, category, area, status, is_demo FROM reports WHERE id=?", (rid,))
    if not r:
        raise HTTPException(404, "Report not found.")
    with db.db() as c:   # one transaction: history and report go together or not at all
        c.execute("DELETE FROM report_events WHERE report_id=?", (rid,))
        c.execute("DELETE FROM reports WHERE id=?", (rid,))
    auth.audit(user, "report_delete", f"report:{rid}",
               f"{r['category']} · {r['area']} · was {r['status']}{' · demo' if r['is_demo'] else ''}", request)
    return {"deleted": rid}


@router.delete("/reports/{rid}/photo")
def remove_photo(rid: int, request: Request, user: dict = Depends(admin_only)):
    """Remove only the photo from a report; the report and its history stay."""
    r = db.one("SELECT id, (photo IS NOT NULL) AS has_photo FROM reports WHERE id=?", (rid,))
    if not r:
        raise HTTPException(404, "Report not found.")
    if not r["has_photo"]:
        raise HTTPException(404, "This report has no photo.")
    db.run("UPDATE reports SET photo=NULL, ai_cls=NULL, ai_text=NULL, updated_at=? WHERE id=?", (time.time(), rid))
    auth.audit(user, "report_photo_remove", f"report:{rid}", "", request)
    return {"photo_removed": rid}


class ReservoirIn(BaseModel):
    reservoir_id: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    reservoir: str = Field(min_length=2, max_length=80)
    date: str
    storage_tmc: Optional[float] = Field(None, ge=0, le=1000)
    capacity_tmc: Optional[float] = Field(None, gt=0, le=1000)
    pct_full: Optional[float] = Field(None, ge=0, le=100)
    inflow_cusecs: Optional[float] = Field(None, ge=0, le=1_000_000)
    outflow_cusecs: Optional[float] = Field(None, ge=0, le=1_000_000)
    source: str = Field(min_length=3, max_length=200)
    url: str = Field(pattern=r"^https://", max_length=500)
    status: Literal["historical", "manually uploaded", "live"] = "manually uploaded"

    @field_validator("date")
    @classmethod
    def iso(cls, v):
        from datetime import date
        d = date.fromisoformat(v)
        if d > date.today():
            raise ValueError("Date can't be in the future.")
        return d.isoformat()


@router.post("/reservoir-readings", status_code=201)
def add_reservoir(body: ReservoirIn, request: Request, user: dict = Depends(admin_only)):
    if body.pct_full is None and (body.storage_tmc is None or body.capacity_tmc is None):
        raise HTTPException(422, "Give either % full, or storage and capacity.")
    if body.storage_tmc is not None and body.capacity_tmc is not None and body.storage_tmc > body.capacity_tmc:
        raise HTTPException(422, "Storage can't be above capacity.")
    rid = db.run("INSERT INTO reservoir_readings(reservoir_id,reservoir,date,storage_tmc,capacity_tmc,pct_full,inflow_cusecs,outflow_cusecs,"
                 "source,url,status,added_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (body.reservoir_id, body.reservoir, body.date, body.storage_tmc, body.capacity_tmc, body.pct_full, body.inflow_cusecs,
                  body.outflow_cusecs, body.source, body.url, body.status, user["id"], time.time()))
    auth.audit(user, "reservoir_reading_add", f"reservoir:{body.reservoir_id}", f"{body.date} {body.pct_full or body.storage_tmc}", request)
    return {"id": rid, "readings": [r for r in ds.reservoir_readings() if r["id"] == body.reservoir_id]}


class LakeObsIn(BaseModel):
    lake_id: str
    date: str
    parameter: str = Field(min_length=1, max_length=60)
    value: Optional[float] = None
    klass: Optional[Literal["A", "B", "C", "D", "E"]] = Field(None, alias="class")
    source: str = Field(min_length=3, max_length=200)
    url: str = Field(pattern=r"^https://", max_length=500)


@router.post("/lake-observations", status_code=201)
def add_lake_obs(body: LakeObsIn, request: Request, user: dict = Depends(admin_only)):
    if not any(l["id"] == body.lake_id for l in ds.processed("lakes.json")):
        raise HTTPException(404, "Unknown lake.")
    oid = db.run("INSERT INTO lake_observations(lake_id,date,parameter,value,class,source,url,added_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                 (body.lake_id, body.date, body.parameter, body.value, body.klass, body.source, body.url, user["id"], time.time()))
    auth.audit(user, "lake_observation_add", f"lake:{body.lake_id}", f"{body.parameter}={body.value} {body.klass or ''}", request)
    return {"id": oid}


@router.get("/audit-logs")
def audit_logs(limit: int = Query(100, ge=1, le=1000), user: dict = Depends(admin_only)):
    return {"logs": db.rows("SELECT a.id, a.action, a.target, a.detail, a.ip, a.created_at, u.email FROM audit_logs a "
                            "LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.created_at DESC LIMIT ?", (limit,))}


@router.get("/users")
def users(user: dict = Depends(admin_only)):
    return {"users": db.rows("SELECT id, email, name, role, organization, created_at, last_login_at FROM users ORDER BY created_at DESC LIMIT 500")}


@router.get("/predictions")
def predictions(limit: int = Query(50, ge=1, le=500), user: dict = Depends(admin_only)):
    return {"predictions": db.rows("SELECT * FROM model_predictions ORDER BY created_at DESC LIMIT ?", (limit,))}
