"""Helpers shared by the API routes: rate limiting, photo handling, locations and wards, logging."""
from __future__ import annotations

import io
import json
import logging
import os
import time
from collections import defaultdict, deque
from functools import lru_cache
from typing import Optional

from fastapi import HTTPException, Request
from PIL import Image, UnidentifiedImageError

from . import data_store, rules

MAX_UPLOAD = 8 * 1024 * 1024
WRITE_LIMIT = int(os.environ.get("JALSETU_WRITE_LIMIT", "30"))     # writes per IP per 10 minutes
LOGIN_LIMIT = int(os.environ.get("JALSETU_LOGIN_LIMIT", "10"))     # login attempts per IP per 10 minutes
_hits: dict[str, deque] = defaultdict(deque)

log = logging.getLogger("jalsetu")
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    log.propagate = False


def jlog(event: str, **kw) -> None:
    """Structured JSON log line (Vercel and Render collect stdout)."""
    log.info(json.dumps({"ts": round(time.time(), 3), "event": event, **kw}, default=str))


def client_ip(request: Request) -> str:
    return (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "?"))


def rate_limit(request: Request, bucket: str = "write", limit: Optional[int] = None) -> None:
    lim = limit if limit is not None else (LOGIN_LIMIT if bucket == "login" else WRITE_LIMIT)
    key = f"{bucket}:{client_ip(request)}"
    now, q = time.time(), _hits[key]
    while q and now - q[0] > 600:
        q.popleft()
    if len(q) >= lim:
        raise HTTPException(429, "Too many attempts from this device. Please wait a few minutes.")
    q.append(now)


def to_jpeg(raw: bytes, size: int = 640) -> bytes:
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "Photo is larger than 8 MB.")
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise HTTPException(415, "That file isn't a photo JalSetu can read. Use a JPG or PNG.") from e
    im.thumbnail((size, size))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=75)
    return buf.getvalue()


# ------------------------------------------------------------------ geography
def _in_ring(lng, lat, ring) -> bool:
    inside, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


@lru_cache(maxsize=1)
def _wards():
    return data_store.processed("wards.geojson")["features"]


def ward_for(lat: float, lng: float) -> Optional[dict]:
    for f in _wards():
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for poly in polys:
            if _in_ring(lng, lat, poly[0]) and not any(_in_ring(lng, lat, h) for h in poly[1:]):
                return {"ward_no": f["properties"]["ward_no"], "name": f["properties"]["name"]}
    return None


BENGALURU_BOUNDS = (12.70, 77.30, 13.25, 77.90)


def resolve_location(area: Optional[str], lat: Optional[float], lng: Optional[float]) -> dict:
    """Area name (approximate centre) or an exact map point. Returns lat, lng, area, ward."""
    if lat is not None and lng is not None:
        a, b, c, d = BENGALURU_BOUNDS
        if not (a <= lat <= c and b <= lng <= d):
            raise HTTPException(422, "That location is outside Bengaluru.")
        w = ward_for(lat, lng)
        return {"lat": round(lat, 5), "lng": round(lng, 5), "area": area if area in rules.AREAS else None, "ward": w, "precision": "map point"}
    if area in rules.AREAS:
        la, lo = rules.AREAS[area]
        return {"lat": la, "lng": lo, "area": area, "ward": ward_for(la, lo), "precision": "approximate area centre"}
    raise HTTPException(422, "Choose an area from the list or pick a point on the map.")
