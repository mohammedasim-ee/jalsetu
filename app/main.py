"""JalSetu backend: REST API + SQLite database + serves the website.

Run locally:   uvicorn app.main:app --reload
Then open:     http://localhost:8000
API docs:      http://localhost:8000/docs
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator

from . import ai, rules

BASE = Path(__file__).resolve().parent
# Postgres when a database URL is set (e.g. Neon on Vercel); otherwise a local SQLite file.
PG_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or ""
_default_db = Path("/tmp/jalsetu.db") if os.environ.get("VERCEL") else BASE.parent / "jalsetu.db"
DB_PATH = Path(os.environ.get("JALSETU_DB", _default_db))
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
MAX_UPLOAD = 8 * 1024 * 1024          # 8 MB per photo
WRITE_LIMIT = int(os.environ.get("JALSETU_WRITE_LIMIT", "30"))   # writes per IP per 10 minutes
MAX_ROWS = 5000                        # keep the database small on free hosting

app = FastAPI(title="JalSetu API", version="1.0",
              description="Water security for Bengaluru: early warning, citizen reports, treated-water exchange, "
                          "IS 10500 water checks and BWSSB rainwater harvesting rules.")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])

# ---------------------------------------------------------------- database
_lock = threading.Lock()


class _PgRow(dict):
    """Row usable both as row["name"] and row[0], like sqlite3.Row."""
    def __getitem__(self, k):
        return list(self.values())[k] if isinstance(k, int) else dict.__getitem__(self, k)


class _PgConn:
    """Tiny adapter so the same SQL (with ? placeholders) runs on Postgres."""
    def __init__(self, con):
        self.con = con

    def execute(self, sql: str, params=()):
        insert = sql.lstrip().upper().startswith("INSERT")
        cur = self.con.cursor(row_factory=lambda c: (lambda vals: _PgRow(zip([d.name for d in c.description], vals))))
        cur.execute(sql.replace("?", "%s") + (" RETURNING id" if insert else ""), params)
        return _PgResult(cur, cur.fetchone()["id"] if insert else None)


class _PgResult:
    def __init__(self, cur, lastrowid):
        self.cur, self.lastrowid, self.rowcount = cur, lastrowid, cur.rowcount

    def fetchone(self):
        return self.cur.fetchone()

    def fetchall(self):
        return self.cur.fetchall()


@contextmanager
def db():
    if PG_URL:
        import psycopg
        con = psycopg.connect(PG_URL, connect_timeout=10)
        try:
            yield _PgConn(con)
            con.commit()
        finally:
            con.close()
        return
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        with _lock:
            yield con
            con.commit()
    finally:
        con.close()


def init_db() -> None:
    if PG_URL:
        with db() as c:
            c.execute("""
            CREATE TABLE IF NOT EXISTS reports(
              id SERIAL PRIMARY KEY,
              type TEXT NOT NULL, area TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
              price DOUBLE PRECISION, litres INTEGER, photo BYTEA,
              ai_cls TEXT, ai_text TEXT, created_at DOUBLE PRECISION NOT NULL)""")
            c.execute("CREATE INDEX IF NOT EXISTS reports_time ON reports(created_at)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS listings(
              id SERIAL PRIMARY KEY,
              kind TEXT NOT NULL, area TEXT NOT NULL, name TEXT NOT NULL, qty INTEGER NOT NULL,
              token_hash TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL)""")
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS reports(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          type TEXT NOT NULL, area TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
          price REAL, litres INTEGER, photo BLOB,
          ai_cls TEXT, ai_text TEXT, created_at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS reports_time ON reports(created_at);
        CREATE TABLE IF NOT EXISTS listings(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          kind TEXT NOT NULL, area TEXT NOT NULL, name TEXT NOT NULL, qty INTEGER NOT NULL,
          token_hash TEXT NOT NULL, created_at REAL NOT NULL);
        """)


init_db()

# ---------------------------------------------------------------- helpers
_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(request: Request) -> None:
    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or (request.client.host if request.client else "?"))
    now, q = time.time(), _hits[ip]
    while q and now - q[0] > 600:
        q.popleft()
    if len(q) >= WRITE_LIMIT:
        raise HTTPException(429, "Too many submissions from this device. Please wait a few minutes.")
    q.append(now)


def to_jpeg(raw: bytes, size: int = 640) -> bytes:
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "Photo is larger than 8 MB.")
    try:
        im = Image.open(io.BytesIO(raw))
        im = im.convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise HTTPException(415, "That file isn't a photo JalSetu can read. Use a JPG or PNG.")
    im.thumbnail((size, size))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=75)
    return buf.getvalue()


def row_to_report(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "type": r["type"], "type_label": rules.REPORT_TYPES[r["type"]], "area": r["area"],
            "note": r["note"], "price": r["price"], "litres": r["litres"],
            "photo_url": f"/api/reports/{r['id']}/photo" if r["photo"] else None,
            "ai": {"cls": r["ai_cls"], "text": r["ai_text"]} if r["ai_cls"] else None,
            "created_at": r["created_at"]}


def hash_token(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


# ---------------------------------------------------------------- meta
@app.get("/api/health")
def health():
    with db() as c:
        n = c.execute("SELECT (SELECT COUNT(*) FROM reports) AS nr, (SELECT COUNT(*) FROM listings) AS nl").fetchone()
    return {"ok": True, "ai": ai.enabled(), "reports": n[0], "listings": n[1], "version": app.version}


@app.get("/api/areas")
def areas():
    return {"areas": list(rules.AREAS), "report_types": rules.REPORT_TYPES, "tanker_sizes": rules.TANKER_SIZES}


# ---------------------------------------------------------------- early warning
@app.get("/api/signals")
def signals():
    data = json.loads((BASE / "data" / "signals.json").read_text())
    for d in data["rain"]["districts"]:
        dep = round((d["actual_mm"] - d["normal_mm"]) / d["normal_mm"] * 100)
        d["departure_pct"] = dep
        d["level"] = "alert" if dep <= -40 else "watch" if dep <= -20 else "normal"
    r = data["reservoirs"]
    r["pct"] = round(r["gross_tmc"] / r["capacity_tmc"] * 100, 1)
    g = data["groundwater"]
    g["pumped_vs_recharge"] = round(g["pumped_mld"] / g["recharge_mld"], 1)
    urban = data["rain"]["districts"][0]
    data["reading"] = {
        "borewell_areas": "alert" if urban["level"] == "alert" and g["pumped_vs_recharge"] > 1 else urban["level"],
        "cauvery_piped_areas": "lower_near_term_risk" if r["pct"] >= 50 else "watch",
        "rule": "Rain 40%+ below normal = alert, 20–39% = watch (JalSetu planning rule, not an official warning)",
    }
    data.pop("_note", None)
    return data


# ---------------------------------------------------------------- reports
@app.get("/api/reports")
def list_reports(limit: int = 50):
    limit = max(1, min(200, limit))
    with db() as c:
        rows = c.execute("SELECT * FROM reports ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return {"reports": [row_to_report(r) for r in rows]}


@app.post("/api/reports", status_code=201)
async def create_report(request: Request,
                        type: str = Form(...), area: str = Form(...), note: str = Form(""),
                        price: Optional[float] = Form(None), litres: Optional[int] = Form(None),
                        photo: Optional[UploadFile] = File(None)):
    if type not in rules.REPORT_TYPES:
        raise HTTPException(422, "Choose what happened from the list.")
    if area not in rules.AREAS:
        raise HTTPException(422, "Choose an area from the list.")
    note = note.strip()[:300]
    if type == "tanker":
        if price is None or not (0 < price <= 100000):
            raise HTTPException(422, "Enter the price you paid, in rupees.")
        if litres not in rules.TANKER_SIZES:
            raise HTTPException(422, "Choose a tanker size of 6,000, 8,000 or 12,000 litres.")
    else:
        price, litres = None, None
    rate_limit(request)
    jpeg = None
    if photo is not None and photo.filename:
        jpeg = to_jpeg(await photo.read())
    ai_cls = ai_text = None
    if jpeg and ai.enabled():
        try:
            v = ai.verify_report_photo(jpeg, rules.REPORT_TYPES[type], area, note)
            ai_cls, ai_text = v["cls"], v["text"]
        except Exception:
            ai_cls, ai_text = "wait", "Photo not checked: AI unavailable right now"
    with db() as c:
        if c.execute("SELECT COUNT(*) FROM reports").fetchone()[0] >= MAX_ROWS:
            c.execute("DELETE FROM reports WHERE id IN (SELECT id FROM reports ORDER BY created_at LIMIT 100)")
        cur = c.execute("INSERT INTO reports(type,area,note,price,litres,photo,ai_cls,ai_text,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?)", (type, area, note, price, litres, jpeg, ai_cls, ai_text, time.time()))
        row = c.execute("SELECT * FROM reports WHERE id=?", (cur.lastrowid,)).fetchone()
    return row_to_report(row)


@app.get("/api/reports/{rid}/photo")
def report_photo(rid: int):
    with db() as c:
        r = c.execute("SELECT photo FROM reports WHERE id=?", (rid,)).fetchone()
    if not r or not r["photo"]:
        raise HTTPException(404, "No photo for this report.")
    return Response(r["photo"], media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.delete("/api/reports/{rid}")
def delete_report(rid: int, x_admin_token: str = Header("")):
    if not ADMIN_TOKEN or not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(403, "Only a moderator can remove reports.")
    with db() as c:
        n = c.execute("DELETE FROM reports WHERE id=?", (rid,)).rowcount
    if not n:
        raise HTTPException(404, "Report not found.")
    return {"deleted": rid}


@app.get("/api/hotspots")
def hotspots(days: int = 30):
    since = time.time() - max(1, min(365, days)) * 86400
    with db() as c:
        rows = c.execute("SELECT area, COUNT(*) n FROM reports WHERE created_at>=? AND type IN ('dry','low','sewage','quality') "
                         "AND (ai_cls IS NULL OR ai_cls!='bad') GROUP BY area ORDER BY n DESC LIMIT 10", (since,)).fetchall()
        t = c.execute("SELECT COUNT(*), AVG(price*1000.0/litres) FROM reports WHERE type='tanker' AND price>0 AND litres>0").fetchone()
    return {"days": days, "areas": [{"area": r["area"], "reports": r["n"]} for r in rows],
            "tanker": {"reports": t[0], "avg_rs_per_1000l": round(t[1], 1) if t[1] else None}}


# ---------------------------------------------------------------- listings (treated water exchange)
class ListingIn(BaseModel):
    kind: Literal["supply", "demand"]
    area: str
    name: str = Field(min_length=1, max_length=60)
    qty: int = Field(ge=1, le=2000, description="kilolitres per day")

    @field_validator("area")
    @classmethod
    def area_known(cls, v):
        if v not in rules.AREAS:
            raise ValueError("Choose an area from the list.")
        return v

    @field_validator("name")
    @classmethod
    def name_clean(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Add a name.")
        return v


def row_to_listing(r) -> dict:
    return {"id": r["id"], "kind": r["kind"], "area": r["area"], "name": r["name"], "qty": r["qty"],
            "created_at": r["created_at"]}


@app.get("/api/listings")
def list_listings():
    with db() as c:
        rows = c.execute("SELECT * FROM listings ORDER BY created_at DESC LIMIT 500").fetchall()
    return {"listings": [row_to_listing(r) for r in rows]}


@app.post("/api/listings", status_code=201)
def create_listing(body: ListingIn, request: Request):
    rate_limit(request)
    token = secrets.token_urlsafe(18)
    with db() as c:
        if c.execute("SELECT COUNT(*) FROM listings").fetchone()[0] >= MAX_ROWS:
            raise HTTPException(507, "The exchange is full. Ask a moderator to remove old listings.")
        cur = c.execute("INSERT INTO listings(kind,area,name,qty,token_hash,created_at) VALUES(?,?,?,?,?,?)",
                        (body.kind, body.area, body.name, body.qty, hash_token(token), time.time()))
        row = c.execute("SELECT * FROM listings WHERE id=?", (cur.lastrowid,)).fetchone()
    # The edit token is shown once; the browser keeps it so only its owner (or a moderator) can remove the listing.
    return {**row_to_listing(row), "edit_token": token}


@app.delete("/api/listings/{lid}")
def delete_listing(lid: int, x_edit_token: str = Header(""), x_admin_token: str = Header("")):
    with db() as c:
        r = c.execute("SELECT token_hash FROM listings WHERE id=?", (lid,)).fetchone()
        if not r:
            raise HTTPException(404, "Listing not found.")
        is_admin = bool(ADMIN_TOKEN) and secrets.compare_digest(x_admin_token, ADMIN_TOKEN)
        if not is_admin and not (x_edit_token and secrets.compare_digest(hash_token(x_edit_token), r["token_hash"])):
            raise HTTPException(403, "Only the person who added this listing can remove it.")
        c.execute("DELETE FROM listings WHERE id=?", (lid,))
    return {"deleted": lid}


@app.get("/api/match")
def match(fresh_rs_per_kl: float = 100):
    with db() as c:
        rows = [row_to_listing(r) for r in c.execute("SELECT * FROM listings").fetchall()]
    m = rules.match(rows)
    moved = sum(x["kl_per_day"] for x in m if x["from"])
    return {"matches": m, "matched_kl_per_day": moved,
            "saving_rs_per_day": round(moved * max(0.0, fresh_rs_per_kl - 10)),
            "treated_rs_per_kl": 10, "note": "Treated water at BWSSB's ₹10/kL, before transport"}


# ---------------------------------------------------------------- rules as a service
class WaterIn(BaseModel):
    values: dict[str, Optional[float]]


@app.post("/api/quality/check")
def quality_check(body: WaterIn):
    return rules.check_water(body.values)


@app.get("/api/quality/limits")
def quality_limits():
    return {k: {"label": v[0], "unit": v[1], "acceptable": v[2], "permissible": v[3], "kind": v[4]}
            for k, v in rules.IS10500.items()}


class RwhIn(BaseModel):
    length_ft: float = Field(ge=0, le=5000)
    width_ft: float = Field(ge=0, le=5000)
    built: Literal["new", "old"] = "new"
    roof_sqm: float = Field(0, ge=0, le=100000)
    paved_sqm: float = Field(0, ge=0, le=100000)
    monthly_bill_rs: float = Field(0, ge=0, le=10000000)


@app.post("/api/rwh")
def rwh(body: RwhIn):
    return rules.rwh_plan(body.length_ft, body.width_ft, body.built, body.roof_sqm, body.paved_sqm, body.monthly_bill_rs)


# ---------------------------------------------------------------- AI (optional)
@app.post("/api/ai/lab-report")
async def ai_lab_report(request: Request, photo: UploadFile = File(...)):
    if not ai.enabled():
        raise HTTPException(503, "AI reading is switched off on this server. Type the values in instead.")
    rate_limit(request)
    jpeg = to_jpeg(await photo.read(), 1400)
    try:
        values = ai.read_lab_report(jpeg, {k: f"{v[0]}{' in ' + v[1] if v[1] else ''}" for k, v in rules.IS10500.items()})
    except Exception:
        raise HTTPException(502, "The AI couldn't read that report right now. Try a clearer photo, or type the values.")
    return {"values": values, "check": rules.check_water(values)}


# ---------------------------------------------------------------- errors + website
@app.exception_handler(HTTPException)
async def http_error(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_, exc: RequestValidationError):
    e = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(x) for x in e.get("loc", [])[1:]) or "input"
    msg = str(e.get("msg", "Invalid input")).removeprefix("Value error, ")
    return JSONResponse({"error": f"{msg} ({field})" if "list" not in msg and "name" not in msg.lower() else msg,
                         "field": field}, status_code=422)


@app.exception_handler(Exception)
async def any_error(_, exc: Exception):
    return JSONResponse({"error": "Something went wrong on the server. Please try again."}, status_code=500)


STATIC = BASE.parent / "static"


PURPOSE = {
    ("GET", "/api/health"): "Server status, AI on or off, number of reports and listings",
    ("GET", "/api/areas"): "Bengaluru areas, report types and tanker sizes the app accepts",
    ("GET", "/api/signals"): "Early warning: IMD rain, reservoir and groundwater figures with alert levels",
    ("GET", "/api/reports"): "Latest citizen reports, newest first",
    ("POST", "/api/reports"): "Add a report (dry borewell, sewage, tanker price, bad water) with optional photo",
    ("GET", "/api/reports/{rid}/photo"): "The resized photo attached to a report",
    ("DELETE", "/api/reports/{rid}"): "Remove a report (moderator key needed)",
    ("GET", "/api/hotspots"): "Areas with most problem reports in the last 30 days, and average tanker price",
    ("GET", "/api/listings"): "Treated-water supply and demand listings",
    ("POST", "/api/listings"): "Offer surplus treated water or ask for non-drinking water",
    ("DELETE", "/api/listings/{lid}"): "Remove a listing (only the person who added it, or a moderator)",
    ("GET", "/api/match"): "Match supply to the nearest demand, with daily savings",
    ("POST", "/api/quality/check"): "Check lab test values against IS 10500:2012",
    ("GET", "/api/quality/limits"): "The IS 10500:2012 limits JalSetu uses",
    ("POST", "/api/rwh"): "BWSSB rainwater harvesting plan: mandatory or not, tank size, yearly harvest",
    ("POST", "/api/ai/lab-report"): "AI reads a lab-report photo (only when an AI key is set)",
}


@app.get("/api", include_in_schema=False)
def api_index():
    """Plain API reference that works offline (the /docs page needs internet for its display code)."""
    import html
    rows = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if not path.startswith("/api/") or not getattr(r, "include_in_schema", True):
            continue
        methods = ", ".join(sorted(m for m in getattr(r, "methods", []) if m != "HEAD"))
        doc = PURPOSE.get((methods, path), r.endpoint.__name__.replace("_", " "))
        rows.append(f"<tr><td><code>{methods}</code></td><td><code>{html.escape(path)}</code></td><td>{html.escape(doc)}</td></tr>")
    page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>JalSetu API</title><style>body{font-family:system-ui,Arial,sans-serif;margin:24px;color:#10292B}"
            "table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid #CCD9D5;padding:8px;text-align:left}"
            "code{color:#0B7572}</style><h1>JalSetu API</h1><p>Version " + app.version + " · "
            f"{len(rows)} endpoints · <a href='/docs'>Interactive docs</a> (needs internet) · <a href='/'>Website</a></p>"
            "<table><tr><th>Method</th><th>Path</th><th>Purpose</th></tr>" + "".join(rows) + "</table>")
    return Response(page, media_type="text/html")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
