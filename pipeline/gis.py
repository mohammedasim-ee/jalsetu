"""GIS stage: validate and simplify BBMP ward polygons, place lakes and localities in wards."""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

BENGALURU_BBOX = (12.70, 77.30, 13.25, 77.90)   # lat_min, lng_min, lat_max, lng_max (sanity bounds)


def _perp(p, a, b):
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return math.hypot(x - x1, y - y1)
    return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / math.hypot(dx, dy)


def rdp(points: list, eps: float) -> list:
    """Ramer–Douglas–Peucker line simplification (iterative, keeps first and last point)."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        s, e = stack.pop()
        dmax, idx = 0.0, s
        for i in range(s + 1, e):
            d = _perp(points[i], points[s], points[e])
            if d > dmax:
                dmax, idx = d, i
        if dmax > eps:
            keep[idx] = True
            stack += [(s, idx), (idx, e)]
    return [p for p, k in zip(points, keep) if k]


def _simplify_ring(ring, eps):
    out = rdp([(round(x, 6), round(y, 6)) for x, y in ring[:-1]], eps) if len(ring) > 4 else [tuple(p) for p in ring[:-1]]
    if len(out) < 3:
        out = [tuple(p) for p in ring[:-1]]
    out = [[round(x, 5), round(y, 5)] for x, y in out]
    return out + [out[0]]


def _polygons(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    raise ValueError(f"Unsupported geometry {geom['type']}")


def ring_area_km2(ring) -> float:
    """Planar area on an equirectangular projection at the ring's latitude (good to ~0.5% at city scale)."""
    lat0 = math.radians(sum(p[1] for p in ring) / len(ring))
    kx, ky = 111.320 * math.cos(lat0), 110.574
    a = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        a += (x1 * kx) * (y2 * ky) - (x2 * kx) * (y1 * ky)
    return abs(a) / 2


def point_in_ring(lng, lat, ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_in_feature(lng: float, lat: float, feature: dict[str, Any]) -> bool:
    for poly in _polygons(feature["geometry"]):
        if point_in_ring(lng, lat, poly[0]) and not any(point_in_ring(lng, lat, h) for h in poly[1:]):
            return True
    return False


def process_wards(gj: dict, eps: float = 0.00015) -> tuple[dict, dict]:
    report: dict[str, Any] = {"features_read": len(gj.get("features", [])), "invalid": 0, "duplicate_ids": 0, "issues": []}
    feats: list[dict[str, Any]] = []
    ids: set = set()
    raw_pts = new_pts = 0
    for f in gj["features"]:
        p = f.get("properties", {})
        wid = p.get("KGISWardID")
        if wid in ids:
            report["duplicate_ids"] += 1
            continue
        try:
            polys = _polygons(f["geometry"])
        except (KeyError, ValueError) as e:
            report["invalid"] += 1
            report["issues"].append(f"ward {wid}: {e}")
            continue
        ids.add(wid)
        new_polys = []
        for poly in polys:
            rings = []
            for ring in poly:
                raw_pts += len(ring)
                r = _simplify_ring(ring, eps)
                new_pts += len(r)
                rings.append(r)
            new_polys.append(rings)
        geom = {"type": "Polygon", "coordinates": new_polys[0]} if len(new_polys) == 1 else {"type": "MultiPolygon", "coordinates": new_polys}
        area = sum(ring_area_km2(pl[0]) for pl in new_polys)
        outer = new_polys[0][0]
        feats.append({"type": "Feature", "geometry": geom,
                      "properties": {"ward_id": wid, "ward_no": int(p.get("KGISWardNo") or 0), "name": p.get("KGISWardName", "").strip(),
                                     "lgd_code": p.get("LGD_WardCode"), "area_km2": round(area, 2),
                                     "centroid": [round(sum(q[1] for q in outer[:-1]) / (len(outer) - 1), 5),
                                                  round(sum(q[0] for q in outer[:-1]) / (len(outer) - 1), 5)]}})
    report["features_kept"] = len(feats)
    report["points_before"], report["points_after"] = raw_pts, new_pts
    report["total_area_km2"] = round(sum(f["properties"]["area_km2"] for f in feats), 1)
    return {"type": "FeatureCollection", "features": feats}, report


def ward_for(lat, lng, wards: dict):
    for f in wards["features"]:
        if point_in_feature(lng, lat, f):
            return {"ward_no": f["properties"]["ward_no"], "name": f["properties"]["name"]}
    return None


def in_bbox(lat, lng) -> bool:
    a, b, c, d = BENGALURU_BBOX
    return a <= lat <= c and b <= lng <= d


def process_lakes(path: Path, wards: dict) -> tuple[list, dict]:
    report: dict[str, Any] = {"rows_read": 0, "rows_kept": 0, "issues": []}
    lakes = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            report["rows_read"] += 1
            try:
                lat, lng = float(r["lat"]), float(r["lng"])
            except ValueError:
                report["issues"].append(f"{r.get('name')}: bad coordinates, dropped")
                continue
            if not in_bbox(lat, lng):
                report["issues"].append(f"{r['name']}: outside Bengaluru bounds, dropped")
                continue
            if not r.get("source_url", "").startswith("https://"):
                report["issues"].append(f"{r['name']}: no source URL, dropped")
                continue
            w = ward_for(lat, lng, wards)
            lakes.append({"id": r["name"].lower().split(" lake")[0].replace(" ", "-").replace("(", "").replace(")", ""),
                          "name": r["name"], "lat": lat, "lng": lng, "area_ha": r["area_ha"],
                          "ward": w, "inside_bbmp": w is not None,
                          "source": "Wikipedia article (coordinates and area)", "url": r["source_url"], "retrieved": r["retrieved"],
                          "quality": None,
                          "quality_note": "No per-lake water-quality series is available to JalSetu. KSPCB publishes monthly lake "
                                          "reports; an admin can add observations through /api/admin/lake-observations."})
    report["rows_kept"] = len(lakes)
    return lakes, report


def process_localities(areas: dict, wards: dict) -> list:
    out = []
    for name, (lat, lng) in areas.items():
        out.append({"name": name, "lat": lat, "lng": lng, "ward": ward_for(lat, lng, wards),
                    "note": "Approximate locality centre (hand-entered), not a surveyed point."})
    return out
