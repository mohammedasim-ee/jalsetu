"""Generate API.md from the app's OpenAPI schema:  python scripts/gen_api_docs.py"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("JALSETU_DB", os.path.join(tempfile.mkdtemp(), "x.db"))
from app.main import app  # noqa: E402

spec = app.openapi()
AUTH = {"/api/treated-water/offers": "organization or admin", "/api/treated-water/requests": "logged in", "/api/auth/logout": "logged in", "/api/auth/me": "logged in"}
groups = {}
for path, ops in spec["paths"].items():
    g = path.split("/")[2] if path.count("/") > 1 else "meta"
    for m, op in ops.items():
        a = "admin" if path.startswith("/api/admin") else AUTH.get(path, "")
        if m == "delete" and path.startswith("/api/treated-water"): a = "owner or admin"
        if path == "/api/reports" and m == "post": a = "optional (anonymous allowed)"
        desc = (op.get("description") or op.get("summary") or "").strip().split("\n")[0]
        params = [p["name"] for p in op.get("parameters", []) if p["in"] in ("query", "path")]
        body = ""
        if "requestBody" in op:
            ct = list(op["requestBody"]["content"])[0]
            ref = op["requestBody"]["content"][ct].get("schema", {}).get("$ref", "")
            body = ("multipart form" if "multipart" in ct else "JSON") + (f" `{ref.split('/')[-1]}`" if ref else "")
        groups.setdefault(g, []).append((m.upper(), path, a, desc, ", ".join(params), body))
out = ["# JalSetu API reference", "", f"Version {app.version}. Generated from the OpenAPI schema by `python scripts/gen_api_docs.py`. Interactive docs: `/docs`; offline list: `/api`.", "",
       "## Conventions", "",
       "- JSON in and out. Errors are always `{\"error\": \"plain-language message\"}` (500 errors also include a `ref` that matches a server log line).",
       "- Status codes: 200 OK · 201 created · 401 not logged in · 403 wrong role/owner · 404 not found · 409 conflict (duplicate email, invalid status change) · 413 file too large · 415 not an image · 422 validation · 429 rate limited · 502/503 AI unavailable · 507 store full.",
       "- Auth: `Authorization: Bearer <token>` from `/api/auth/login` or `/api/auth/register`. Tokens last 7 days; only their SHA-256 is stored.",
       "- Every data response includes provenance fields (`source`, `url`, `as_of`/`period`, `status`).", ""]
for g in sorted(groups):
    out += [f"## {g}", "", "| Method | Path | Auth | Purpose | Params | Body |", "| --- | --- | --- | --- | --- | --- |"]
    for r in groups[g]:
        out.append("| " + " | ".join(f"`{r[0]}`" if i == 0 else f"`{r[1]}`" if i == 1 else (x or "–") for i, x in enumerate(r)) + " |")
    out.append("")
out += ["## Schemas", ""]
for name, sch in spec["components"]["schemas"].items():
    if name in ("HTTPValidationError", "ValidationError") or name.startswith("Body_"): continue
    req = set(sch.get("required", []))
    fields = ", ".join(f"`{k}`{'*' if k in req else ''}" for k in sch.get("properties", {}))
    out.append(f"- **{name}**: {fields}  (* required)")
open("API.md", "w").write("\n".join(out) + "\n")
print(sum(len(v) for v in groups.values()), "endpoints")
