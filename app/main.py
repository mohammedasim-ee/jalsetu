"""JalSetu API: water-security data, risk engine, ML, community reports and treated-water exchange for Bengaluru.

Run locally:   uvicorn app.main:app --reload     then open http://localhost:8000
"""
from __future__ import annotations

import html
import json
import os
import secrets
import time
import uuid

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import ai, auth, db, ml_runtime, rules
from . import data_store as ds
from .common import jlog, rate_limit, to_jpeg
from .routes_admin import router as admin_router
from .routes_community import router as community_router
from .routes_data import router as data_router

VERSION = "2.0.0"
BASE = ds.ROOT
STATIC = BASE / "static"
STARTED = time.time()

app = FastAPI(title="JalSetu API", version=VERSION,
              description="Water security for Bengaluru: official data with provenance, explainable risk score, early warnings, "
                          "ML with published evaluation, GIS, community reports with review, treated-water matching.")
_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["GET", "POST", "PATCH", "DELETE"],
                       allow_headers=["authorization", "content-type"])


CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data: https://*.tile.openstreetmap.org https://tile.openstreetmap.org; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


@app.middleware("http")
async def observe(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    t0 = time.perf_counter()
    try:
        resp = await call_next(request)
    except Exception as e:                      # logged here, turned into JSON by the handler below
        jlog("unhandled_error", rid=rid, path=request.url.path, error=type(e).__name__)
        raise
    ms = round((time.perf_counter() - t0) * 1000, 1)
    resp.headers["x-request-id"] = rid
    resp.headers["x-content-type-options"] = "nosniff"
    resp.headers["referrer-policy"] = "strict-origin-when-cross-origin"
    resp.headers["x-frame-options"] = "DENY"
    if not request.url.path.startswith("/api/") and not request.url.path.startswith("/docs"):
        resp.headers["content-security-policy"] = CSP
    if request.url.path.startswith("/api/"):
        jlog("request", rid=rid, method=request.method, path=request.url.path, status=resp.status_code, ms=ms)
    return resp


app.include_router(data_router)
app.include_router(community_router)
app.include_router(admin_router)


def _openapi():
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi

    from .api_docs import DESCRIPTIONS
    spec = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if (method, path) in DESCRIPTIONS:
                op["description"] = DESCRIPTIONS[(method, path)]
    app.openapi_schema = spec
    return spec


app.openapi = _openapi  # type: ignore[method-assign]


# ------------------------------------------------------------------ startup: migrations, admin, demo data
def startup() -> dict:
    applied = db.migrate()
    admin = auth.ensure_admin_from_env()
    demo = seed_demo() if os.environ.get("JALSETU_DEMO") == "1" else 0
    jlog("startup", migrations_applied=applied, admin_configured=bool(admin), demo_rows=demo, dialect=db.DIALECT)
    return {"applied": applied, "demo": demo}


def seed_demo() -> int:
    """Insert clearly labelled demonstration rows (is_demo=1) once. Never counted in the risk score."""
    if db.one("SELECT id FROM reports WHERE is_demo=1 LIMIT 1"):
        return 0
    seed = json.loads((BASE / "data" / "sample" / "demo_seed.json").read_text())
    now = time.time()
    n = 0
    for r in seed["reports"]:
        la, lo = rules.AREAS[r["area"]]
        db.run("INSERT INTO reports(type,category,area,lat,lng,note,status,is_demo,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (r["category"], r["category"], r["area"], la, lo, "[DEMO] " + r["description"], r["status"], 1, now - r["hours_ago"] * 3600, now))
        n += 1
    for o in seed["offers"]:
        la, lo = rules.AREAS[o["area"]]
        db.run("INSERT INTO offers(organization,area,lat,lng,qty_kl_per_day,treatment_level,quality_notes,available_from,available_to,"
               "reuse_categories,is_demo,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               ("[DEMO] " + o["organization"], o["area"], la, lo, o["qty"], o["treatment"], "Demonstration listing", o["from"], o["to"],
                ",".join(o["categories"]), 1, now))
        n += 1
    for q in seed["requests"]:
        la, lo = rules.AREAS[q["area"]]
        db.run("INSERT INTO requests(requester,area,lat,lng,qty_kl_per_day,needed_from,needed_to,purpose,min_treatment,is_demo,created_at) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               ("[DEMO] " + q["requester"], q["area"], la, lo, q["qty"], q["from"], q["to"], q["purpose"], q["min_treatment"], 1, now))
        n += 1
    return n


startup()


# ------------------------------------------------------------------ meta
@app.get("/api/health")
def health():
    counts = {}
    try:
        counts = {"reports": db.one("SELECT COUNT(*) AS n FROM reports")["n"],
                  "offers": db.one("SELECT COUNT(*) AS n FROM offers WHERE status='OPEN'")["n"],
                  "requests": db.one("SELECT COUNT(*) AS n FROM requests WHERE status='OPEN'")["n"]}
    except Exception as e:
        jlog("health_counts_failed", error=str(e)[:200])
    m = ml_runtime.load("metrics.json") if ml_runtime.available() else None
    demo = bool(counts) and bool(db.one("SELECT id FROM reports WHERE is_demo=1 LIMIT 1"))
    return {"ok": db.ping(), "version": VERSION, "ai": ai.enabled(), "database": db.DIALECT, "schema_version": db.schema_version(),
            "data_mode": "DEMONSTRATION + official data" if demo else "official data + community submissions",
            "data_pipeline": {"generated_at": ds.manifest()["generated_at"], "version": ds.manifest()["pipeline_version"]},
            "models": {"version": m["version"], "trained_at": m["trained_at"]} if m else None,
            "admin": {"settings_present": bool(os.environ.get("ADMIN_EMAIL", "").strip() and os.environ.get("ADMIN_PASSWORD", "").strip()),
                      "password_long_enough": len(os.environ.get("ADMIN_PASSWORD", "").strip()) >= 8,
                      "account_exists": _admin_exists()},
            "uptime_s": round(time.time() - STARTED), **counts}


def _admin_exists() -> bool:
    try:
        return bool(db.one("SELECT id FROM users WHERE role='admin' LIMIT 1"))
    except Exception:
        return False


@app.get("/api/meta")
def meta():
    from . import exchange
    return {"areas": sorted(rules.AREAS), "report_categories": rules.REPORT_CATEGORIES, "report_statuses": rules.REPORT_STATUSES,
            "tanker_sizes": rules.TANKER_SIZES, "reuse_categories": exchange.REUSE_CATEGORIES, "treatment_levels": list(exchange.TREATMENT_LEVELS)}


@app.get("/api/areas")
def areas_v1():
    return {"areas": sorted(rules.AREAS), "report_categories": rules.REPORT_CATEGORIES, "tanker_sizes": rules.TANKER_SIZES}


# ------------------------------------------------------------------ AI (optional)
@app.post("/api/ai/lab-report")
async def ai_lab_report(request: Request, photo: UploadFile = File(...)):
    if not ai.enabled():
        raise HTTPException(503, "AI reading is switched off on this server. Type the values in instead.")
    rate_limit(request)
    jpeg = to_jpeg(await photo.read(), 1400)
    try:
        values = ai.read_lab_report(jpeg, {k: f"{v[0]}{' in ' + v[1] if v[1] else ''}" for k, v in rules.IS10500.items()})
    except Exception as e:
        raise HTTPException(502, "The AI couldn't read that report right now. Try a clearer photo, or type the values.") from e
    return {"values": values, "check": rules.check_water(values)}


# ------------------------------------------------------------------ errors
@app.exception_handler(HTTPException)
async def http_error(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_, exc: RequestValidationError):
    e = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(x) for x in e.get("loc", [])[1:]) or "input"
    msg = str(e.get("msg", "Invalid input")).removeprefix("Value error, ")
    return JSONResponse({"error": msg if field in ("", "input") else f"{msg} ({field})", "field": field}, status_code=422)


@app.exception_handler(Exception)
async def any_error(request: Request, exc: Exception):
    ref = secrets.token_hex(4)
    jlog("server_error", ref=ref, path=request.url.path, error=f"{type(exc).__name__}: {exc}"[:300])
    return JSONResponse({"error": "Something went wrong on the server. Please try again.", "ref": ref}, status_code=500)


# ------------------------------------------------------------------ docs + website
@app.get("/api", include_in_schema=False)
def api_index():
    """Plain API reference that works offline (the /docs page needs internet for its display code)."""
    rows = []
    for path, ops in app.openapi()["paths"].items():
        for method, op in ops.items():
            doc = (op.get("description") or op.get("summary") or "").strip().split("\n")[0]
            auth_note = "admin" if path.startswith("/api/admin") else ""
            rows.append(f"<tr><td><code>{method.upper()}</code></td><td><code>{html.escape(path)}</code></td><td>{html.escape(doc)}</td><td>{auth_note}</td></tr>")
    page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>JalSetu API</title><style>body{font-family:system-ui,Arial,sans-serif;margin:24px;color:#10292B}"
            "table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid #CCD9D5;padding:8px;text-align:left}"
            "code{color:#0B7572}</style><h1>JalSetu API</h1><p>Version " + VERSION + " · "
            f"{len(rows)} endpoints · <a href='/docs'>Interactive docs</a> (needs internet) · <a href='/'>Website</a> · full reference in API.md</p>"
            "<table><tr><th>Method</th><th>Path</th><th>Purpose</th><th>Auth</th></tr>" + "".join(rows) + "</table>")
    return Response(page, media_type="text/html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(STATIC / "admin.html", headers={"Cache-Control": "no-cache"})
