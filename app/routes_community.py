"""Write APIs: accounts, community reports, treated-water exchange and matching."""
from __future__ import annotations

import time
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator, model_validator

from . import ai, auth, db, exchange, rules
from . import data_store as ds
from .common import jlog, rate_limit, resolve_location, to_jpeg

router = APIRouter(prefix="/api")
MAX_ROWS = 5000


# ------------------------------------------------------------------ accounts
class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    name: str = Field(max_length=80)
    role: Literal["citizen", "organization"] = "citizen"
    organization: Optional[str] = Field(None, max_length=120)

    @model_validator(mode="after")
    def org_needs_name(self):
        if self.role == "organization" and not (self.organization or "").strip():
            raise ValueError("Organization accounts need an organization name.")
        return self


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


@router.post("/auth/register", status_code=201)
def register(body: RegisterIn, request: Request):
    rate_limit(request, "login")
    u = auth.create_user(body.email, body.password, body.name, body.role, body.organization)
    auth.audit(u, "register", f"user:{u['id']}", u["role"], request)
    token, _ = auth.login(body.email, body.password)
    return {"token": token, "user": u}


@router.post("/auth/login")
def login(body: LoginIn, request: Request):
    rate_limit(request, "login")
    try:
        token, u = auth.login(body.email, body.password)
    except HTTPException:
        jlog("login_failed", ip=request.headers.get("x-forwarded-for", ""))
        raise
    auth.audit(u, "login", f"user:{u['id']}", "", request)
    return {"token": token, "user": u}


@router.post("/auth/admin-check")
def admin_check(body: LoginIn, request: Request):
    rate_limit(request, "login")
    return auth.admin_login_check(body.email, body.password)


@router.post("/auth/logout")
def logout(request: Request, user: dict = Depends(auth.current_user)):
    auth.logout(request.headers.get("authorization", "")[7:])
    return {"ok": True}


@router.get("/auth/me")
def me(user: dict = Depends(auth.current_user)):
    return {"user": user}


# ------------------------------------------------------------------ reports
def report_out(r: dict, events: Optional[list] = None) -> dict:
    cat = r.get("category") or rules.LEGACY_TYPE_TO_CATEGORY.get(r["type"], "other")
    out = {"id": r["id"], "category": cat, "category_label": rules.REPORT_CATEGORIES.get(cat, cat), "area": r["area"],
           "ward": {"ward_no": r["ward_no"], "name": r["ward_name"]} if r.get("ward_no") else None,
           "lat": r.get("lat"), "lng": r.get("lng"), "description": r["note"], "price": r["price"], "litres": r["litres"],
           "status": r.get("status") or "SUBMITTED", "photo_url": f"/api/reports/{r['id']}/photo" if r.get("has_photo") or r.get("photo") else None,
           "ai": {"cls": r["ai_cls"], "text": r["ai_text"]} if r.get("ai_cls") else None,
           "is_demo": bool(r.get("is_demo")), "created_at": r["created_at"], "updated_at": r.get("updated_at")}
    if events is not None:
        out["history"] = events
    return out


COLS = "id,type,category,area,ward_no,ward_name,lat,lng,note,price,litres,status,ai_cls,ai_text,is_demo,created_at,updated_at,(photo IS NOT NULL) AS has_photo"


@router.get("/reports")
def list_reports(limit: int = Query(50, ge=1, le=200), status: Optional[str] = None, category: Optional[str] = None,
                 include_rejected: bool = False, user: Optional[dict] = Depends(auth.optional_user)):
    where, params = [], []
    if status:
        if status not in rules.REPORT_STATUSES:
            raise HTTPException(422, "Unknown status.")
        where.append("status=?"); params.append(status)
    elif not include_rejected:
        where.append("status<>'REJECTED'")
    if category:
        if category not in rules.REPORT_CATEGORIES:
            raise HTTPException(422, "Unknown category.")
        where.append("category=?"); params.append(category)
    # only fixed column names and fixed condition strings are joined; every value is a bound parameter
    sql = f"SELECT {COLS}, user_id FROM reports" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at DESC LIMIT ?"  # noqa: S608
    # 'mine' tells a logged-in reporter which reports they may delete; reporter identities are never returned
    return {"reports": [report_out(r) | {"mine": bool(user and r["user_id"] == user["id"])} for r in db.rows(sql, (*params, limit))]}


@router.delete("/reports/{rid}")
def delete_own_report(rid: int, request: Request, user: dict = Depends(auth.current_user)):
    """Reporter deletes their own report (reports sent while logged in). Admins use /api/admin/reports/{rid}."""
    r = db.one("SELECT id, user_id, category, area, status FROM reports WHERE id=?", (rid,))
    if not r:
        raise HTTPException(404, "Report not found.")
    if r["user_id"] is None or r["user_id"] != user["id"]:
        raise HTTPException(403, "You can only delete reports you submitted while logged in.")
    with db.db() as c:
        c.execute("DELETE FROM report_events WHERE report_id=?", (rid,))
        c.execute("DELETE FROM reports WHERE id=?", (rid,))
    auth.audit(user, "report_delete_own", f"report:{rid}", f"{r['category']} · {r['area']} · was {r['status']}", request)
    return {"deleted": rid}


@router.post("/reports", status_code=201)
async def create_report(request: Request,
                        category: str = Form(...), area: Optional[str] = Form(None),
                        lat: Optional[float] = Form(None), lng: Optional[float] = Form(None),
                        description: str = Form(""),
                        price: Optional[float] = Form(None), litres: Optional[int] = Form(None),
                        photo: Optional[UploadFile] = File(None),
                        user: Optional[dict] = Depends(auth.optional_user)):
    if category not in rules.REPORT_CATEGORIES:
        raise HTTPException(422, "Choose a category from the list.")
    loc = resolve_location(area, lat, lng)
    description = description.strip()[:500]
    if category == "tanker":
        if price is None or not (0 < price <= 100000):
            raise HTTPException(422, "Enter the tanker price you paid, in rupees.")
        if litres not in rules.TANKER_SIZES:
            raise HTTPException(422, "Choose a tanker size of 6,000, 8,000 or 12,000 litres.")
    else:
        price, litres = None, None
    rate_limit(request)
    jpeg = to_jpeg(await photo.read()) if photo is not None and photo.filename else None
    ai_cls = ai_text = None
    if jpeg and ai.enabled():
        try:
            v = ai.verify_report_photo(jpeg, rules.REPORT_CATEGORIES[category], loc["area"] or "Bengaluru", description)
            ai_cls, ai_text = v["cls"], v["text"]
        except Exception:
            ai_cls, ai_text = "wait", "Photo not checked: AI unavailable right now"
    legacy = {v: k for k, v in rules.LEGACY_TYPE_TO_CATEGORY.items()}.get(category, category)
    now = time.time()
    with db.db() as c:
        if c.execute("SELECT COUNT(*) FROM reports").fetchone()[0] >= MAX_ROWS:
            raise HTTPException(507, "The report store is full. Ask a moderator to archive old reports.")
        cur = c.execute("INSERT INTO reports(type,category,area,lat,lng,ward_no,ward_name,note,price,litres,photo,ai_cls,ai_text,status,user_id,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (legacy, category, loc["area"] or (loc["ward"]["name"] if loc["ward"] else "Bengaluru"), loc["lat"], loc["lng"],
                         loc["ward"]["ward_no"] if loc["ward"] else None, loc["ward"]["name"] if loc["ward"] else None,
                         description, price, litres, jpeg, ai_cls, ai_text, "SUBMITTED", user["id"] if user else None, now, now))
        rid = cur.lastrowid
        c.execute("INSERT INTO report_events(report_id,from_status,to_status,note,actor_id,created_at) VALUES(?,?,?,?,?,?)",
                  (rid, None, "SUBMITTED", "Report submitted", user["id"] if user else None, now))
    jlog("report_created", id=rid, category=category, ward=loc["ward"]["ward_no"] if loc["ward"] else None)
    return get_report(rid)


@router.get("/reports/{rid}")
def get_report(rid: int):
    r = db.one(f"SELECT {COLS} FROM reports WHERE id=?", (rid,))  # noqa: S608 (constant column list)
    if not r:
        raise HTTPException(404, "Report not found.")
    ev = db.rows("SELECT from_status, to_status, note, created_at FROM report_events WHERE report_id=? ORDER BY created_at, id", (rid,))
    return report_out(r, ev)


@router.get("/reports/{rid}/photo")
def report_photo(rid: int):
    r = db.one("SELECT photo FROM reports WHERE id=?", (rid,))
    if not r or not r["photo"]:
        raise HTTPException(404, "No photo for this report.")
    return Response(bytes(r["photo"]), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/hotspots")
def hotspots(days: int = Query(30, ge=1, le=365), verified_only: bool = False):
    since = time.time() - days * 86400
    st = "status IN ('VERIFIED','RESOLVED')" if verified_only else "status<>'REJECTED'"
    base = f"FROM reports WHERE created_at>=? AND {st} AND category<>'tanker' AND (ai_cls IS NULL OR ai_cls<>'bad')"
    areas = db.rows(f"SELECT area, COUNT(*) AS reports {base} GROUP BY area ORDER BY reports DESC, area LIMIT 15", (since,))
    wards = db.rows(f"SELECT ward_no, ward_name, COUNT(*) AS reports {base} AND ward_no IS NOT NULL GROUP BY ward_no, ward_name ORDER BY reports DESC LIMIT 243", (since,))
    t = db.one("SELECT COUNT(*) AS n, AVG(price*1000.0/litres) AS avg FROM reports WHERE category='tanker' AND status<>'REJECTED' AND price>0 AND litres>0")
    return {"days": days, "verified_only": verified_only, "areas": areas, "wards": wards,
            "tanker": {"reports": t["n"], "avg_rs_per_1000l": round(t["avg"], 1) if t["avg"] else None}}


# ------------------------------------------------------------------ treated-water exchange
def _date(v: str) -> str:
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError as e:
        raise ValueError("Use dates like 2026-10-01.") from e


class Located(BaseModel):
    area: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class OfferIn(Located):
    organization: str = Field(min_length=1, max_length=120)
    qty_kl_per_day: float = Field(gt=0, le=5000)
    treatment_level: Literal["secondary", "tertiary"]
    quality_notes: str = Field("", max_length=300)
    bod_mg_l: Optional[float] = Field(None, ge=0, le=1000)
    tss_mg_l: Optional[float] = Field(None, ge=0, le=5000)
    available_from: str
    available_to: str
    reuse_categories: list[str] = Field(min_length=1, max_length=5)

    _d1 = field_validator("available_from", "available_to")(lambda cls, v: _date(v))

    @field_validator("reuse_categories")
    @classmethod
    def cats(cls, v):
        bad = [x for x in v if x not in exchange.REUSE_CATEGORIES]
        if bad:
            raise ValueError(f"Unknown reuse category: {bad[0]}")
        return sorted(set(v))

    @field_validator("organization")
    @classmethod
    def strip(cls, v):
        if not v.strip():
            raise ValueError("Add the organization name.")
        return v.strip()

    @model_validator(mode="after")
    def order(self):
        if self.available_to < self.available_from:
            raise ValueError("'Available to' must be on or after 'available from'.")
        return self


class RequestIn(Located):
    requester: str = Field(min_length=1, max_length=120)
    qty_kl_per_day: float = Field(gt=0, le=5000)
    needed_from: str
    needed_to: str
    purpose: str
    min_treatment: Literal["secondary", "tertiary"] = "secondary"

    _d2 = field_validator("needed_from", "needed_to")(lambda cls, v: _date(v))

    @field_validator("purpose")
    @classmethod
    def purpose_ok(cls, v):
        if v not in exchange.REUSE_CATEGORIES:
            raise ValueError("Choose a reuse purpose from the list.")
        return v

    @field_validator("requester")
    @classmethod
    def strip(cls, v):
        if not v.strip():
            raise ValueError("Add your name or site name.")
        return v.strip()

    @model_validator(mode="after")
    def order(self):
        if self.needed_to < self.needed_from:
            raise ValueError("'Needed to' must be on or after 'needed from'.")
        return self


def _offer_out(o):
    return {**{k: o[k] for k in ("id", "organization", "area", "lat", "lng", "qty_kl_per_day", "treatment_level", "quality_notes",
                                  "bod_mg_l", "tss_mg_l", "available_from", "available_to", "status", "created_at", "user_id")},
            "reuse_categories": o["reuse_categories"].split(","), "is_demo": bool(o["is_demo"])}


def _req_out(r):
    return {**{k: r[k] for k in ("id", "requester", "area", "lat", "lng", "qty_kl_per_day", "needed_from", "needed_to", "purpose",
                                  "min_treatment", "status", "created_at", "user_id")}, "is_demo": bool(r["is_demo"])}


@router.get("/treated-water")
def treated_water():
    return {"offers": [_offer_out(o) for o in db.rows("SELECT * FROM offers WHERE status='OPEN' ORDER BY created_at DESC LIMIT 500")],
            "requests": [_req_out(r) for r in db.rows("SELECT * FROM requests WHERE status='OPEN' ORDER BY created_at DESC LIMIT 500")],
            "reuse_categories": exchange.REUSE_CATEGORIES, "treatment_levels": list(exchange.TREATMENT_LEVELS),
            "treated_price": ds.indicators()["treated_water_price"],
            "note": "JalSetu lists and matches offers and requests. It does not process payments or transactions."}


@router.post("/treated-water/offers", status_code=201)
def create_offer(body: OfferIn, request: Request, user: dict = Depends(auth.require("organization", "admin"))):
    rate_limit(request)
    loc = resolve_location(body.area, body.lat, body.lng)
    oid = db.run("INSERT INTO offers(user_id,organization,area,lat,lng,qty_kl_per_day,treatment_level,quality_notes,bod_mg_l,tss_mg_l,"
                 "available_from,available_to,reuse_categories,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (user["id"], body.organization, loc["area"], loc["lat"], loc["lng"], body.qty_kl_per_day, body.treatment_level,
                  body.quality_notes.strip(), body.bod_mg_l, body.tss_mg_l, body.available_from, body.available_to,
                  ",".join(body.reuse_categories), time.time()))
    auth.audit(user, "offer_create", f"offer:{oid}", body.organization, request)
    return _offer_out(db.one("SELECT * FROM offers WHERE id=?", (oid,)))


@router.post("/treated-water/requests", status_code=201)
def create_request(body: RequestIn, request: Request, user: dict = Depends(auth.current_user)):
    rate_limit(request)
    loc = resolve_location(body.area, body.lat, body.lng)
    rid = db.run("INSERT INTO requests(user_id,requester,area,lat,lng,qty_kl_per_day,needed_from,needed_to,purpose,min_treatment,created_at) "
                 "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                 (user["id"], body.requester, loc["area"], loc["lat"], loc["lng"], body.qty_kl_per_day, body.needed_from, body.needed_to,
                  body.purpose, body.min_treatment, time.time()))
    auth.audit(user, "request_create", f"request:{rid}", body.requester, request)
    return _req_out(db.one("SELECT * FROM requests WHERE id=?", (rid,)))


def _delete_owned(table: str, item_id: int, user: dict, request: Request):
    if table not in ("offers", "requests"):   # table name comes only from this module; never from user input
        raise ValueError("unknown table")
    row = db.one(f"SELECT id, user_id FROM {table} WHERE id=?", (item_id,))  # noqa: S608 (allow-listed table)
    if not row:
        raise HTTPException(404, "Not found.")
    if user["role"] != "admin" and row["user_id"] != user["id"]:
        raise HTTPException(403, "Only the account that created this can remove it.")
    db.run(f"UPDATE {table} SET status='CLOSED' WHERE id=?", (item_id,))  # noqa: S608 (allow-listed table)
    auth.audit(user, f"{table[:-1]}_close", f"{table[:-1]}:{item_id}", "", request)
    return {"closed": item_id}


@router.delete("/treated-water/offers/{oid}")
def close_offer(oid: int, request: Request, user: dict = Depends(auth.current_user)):
    return _delete_owned("offers", oid, user, request)


@router.delete("/treated-water/requests/{rid}")
def close_request(rid: int, request: Request, user: dict = Depends(auth.current_user)):
    return _delete_owned("requests", rid, user, request)


@router.get("/matches")
def matches(request_id: Optional[int] = None, fresh_rs_per_kl: float = Query(100, ge=0, le=100000), include_blocked: bool = False):
    offers = [_offer_out(o) for o in db.rows("SELECT * FROM offers WHERE status='OPEN'")]
    treated = ds.indicators()["treated_water_price"]["rs_per_kl"]
    if request_id is not None:
        r = db.one("SELECT * FROM requests WHERE id=?", (request_id,))
        if not r:
            raise HTTPException(404, "Request not found.")
        reqs = [_req_out(r)]
    else:
        reqs = [_req_out(r) for r in db.rows("SELECT * FROM requests WHERE status='OPEN' ORDER BY created_at DESC LIMIT 100")]
    out = []
    for q in reqs:
        ranked = exchange.rank_offers(q, offers, fresh_rs_per_kl, treated, include_blocked)
        best = next((m for m in ranked if m["eligible"]), None)
        out.append({"request": q, "matches": ranked[:10], "best_offer_id": best["offer_id"] if best else None,
                    "unmet": best is None or best["kl_per_day"] < q["qty_kl_per_day"],
                    "unmet_kl_per_day": q["qty_kl_per_day"] - (best["kl_per_day"] if best else 0)})
    return {"results": out, "weights": exchange.WEIGHTS, "fresh_rs_per_kl": fresh_rs_per_kl, "treated_rs_per_kl": treated,
            "method": exchange.__doc__.strip()}
