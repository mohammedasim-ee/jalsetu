"""Black-box QA of accounts, admin, reports and photos against a RUNNING local server.

Never point this at production: it creates and deletes records. It refuses to run
against a non-local URL. Every record it creates contains QA-TEST-DO-NOT-KEEP.

    QA_BASE=http://127.0.0.1:8850 QA_ADMIN_EMAIL=... QA_ADMIN_PASSWORD=... python scripts/qa_audit.py [phase]

phase = "all" (default), "setup" (create a QA report and stop) or "after-restart" (check it survived, then clean up).
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlparse

from PIL import Image

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:8850")
if urlparse(BASE).hostname not in ("127.0.0.1", "localhost"):
    sys.exit("Refusing to run destructive QA against a non-local server.")
ADMIN = (os.environ["QA_ADMIN_EMAIL"], os.environ["QA_ADMIN_PASSWORD"])
TAG = "QA-TEST-DO-NOT-KEEP"
STATE = os.environ.get("QA_STATE", "qa_state.json")
results: list[tuple[str, bool, str]] = []


def call(method, path, token=None, json_body=None, form=None, files=None, raw_headers=None):
    headers = dict(raw_headers or {})
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif form is not None:
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in form.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for k, (fname, content, ctype) in (files or {}).items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{fname}"\r\n'
                         f"Content-Type: {ctype}\r\n\r\n".encode() + content + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (local URL enforced above)
            body = r.read()
            status, ctype = r.status, r.headers.get("content-type", "")
    except urllib.error.HTTPError as e:
        body, status, ctype = e.read(), e.code, e.headers.get("content-type", "")
    if "json" in ctype:
        return status, json.loads(body or b"null")
    return status, body


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def img(fmt, size=(1200, 900), color=(30, 90, 160)):
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, fmt)
    return b.getvalue()


def report(token=None, photo=None, **extra):
    form = {"category": "groundwater", "area": "Whitefield", "description": f"{TAG} " + extra.pop("desc", "automated QA report")}
    form.update(extra)
    return call("POST", "/api/reports", token=token, form=form, files={"photo": photo} if photo else None)


def admin_token():
    s, b = call("POST", "/api/auth/login", json_body={"email": ADMIN[0], "password": ADMIN[1]})
    assert s == 200, f"admin login failed: {s}"
    return b["token"]


# ------------------------------------------------------------------ phase 2: accounts
def accounts():
    email = f"qa-{uuid.uuid4().hex[:8]}@qa-test-do-not-keep.test"
    pw = "qa-" + uuid.uuid4().hex
    s, b = call("POST", "/api/auth/register", json_body={"email": email, "password": pw, "name": TAG})
    check("register: valid account -> 201 + token", s == 201 and b.get("token") and b["user"]["role"] == "citizen", str(s))
    check("register: password hash never returned", "password_hash" not in json.dumps(b))
    s, b = call("POST", "/api/auth/register", json_body={"email": email.upper(), "password": pw, "name": TAG})
    check("register: duplicate email (any case) -> 409", s == 409, str(s))
    s, _ = call("POST", "/api/auth/register", json_body={"email": "not-an-email", "password": pw, "name": TAG})
    check("register: invalid email -> 422", s == 422, str(s))
    s, _ = call("POST", "/api/auth/register", json_body={"email": "x" + email, "password": "short", "name": TAG})
    check("register: short password -> 422", s == 422, str(s))
    s, _ = call("POST", "/api/auth/register", json_body={"email": "y" + email, "password": pw, "name": ""})
    check("register: empty name -> 422", s == 422, str(s))
    s, _ = call("POST", "/api/auth/register", json_body={"email": "z" + email})
    check("register: missing fields -> 422", s == 422, str(s))
    s, _ = call("POST", "/api/auth/register", json_body={"email": "w" + email, "password": pw, "name": TAG, "role": "admin"})
    check("register: cannot self-register as admin -> 422", s == 422, str(s))

    s, b = call("POST", "/api/auth/login", json_body={"email": f"  {email.upper()} ", "password": pw})
    check("login: correct credentials (email case/space tolerant) -> 200", s == 200 and b.get("token"), str(s))
    tok = b.get("token")
    s, b1 = call("POST", "/api/auth/login", json_body={"email": email, "password": pw + "x"})
    s2, b2 = call("POST", "/api/auth/login", json_body={"email": "nobody-" + email, "password": pw})
    check("login: wrong password -> 401", s == 401, str(s))
    check("login: unknown account -> 401 with the SAME message", s2 == 401 and b1 == b2, f"{s2} {b1} {b2}")
    s, _ = call("POST", "/api/auth/login", json_body={"email": "", "password": ""})
    check("login: empty fields -> 401/422, not 500", s in (401, 422), str(s))
    s, _ = call("POST", "/api/auth/login", json_body={"email": "a" * 300, "password": "b"})
    check("login: oversized input -> 422", s == 422, str(s))

    s, b = call("GET", "/api/auth/me", token=tok)
    check("session: token works on a later request (refresh)", s == 200 and b["user"]["email"] == email, str(s))
    s, _ = call("GET", "/api/auth/me", token=tok + "tampered")
    check("session: forged token -> 401", s == 401, str(s))
    s, _ = call("GET", "/api/auth/me")
    check("session: no token -> 401", s == 401, str(s))
    s, _ = call("POST", "/api/auth/logout", token=tok)
    s2, _ = call("GET", "/api/auth/me", token=tok)
    check("logout: 200 and the token stops working", s == 200 and s2 == 401, f"{s} {s2}")
    s, b = call("POST", "/api/auth/login", json_body={"email": email, "password": pw})
    return email, pw, b["token"]


# ------------------------------------------------------------------ phase 3+4+5
def admin_and_reports(cit_tok):
    adm = admin_token()
    s, b = call("GET", "/api/auth/me", token=adm)
    check("admin: login returns role admin", s == 200 and b["user"]["role"] == "admin", str(s))
    for path in ("/api/admin/overview", "/api/admin/reports", "/api/admin/users", "/api/admin/audit-logs"):
        s1, _ = call("GET", path)
        s2, _ = call("GET", path, token=cit_tok)
        s3, _ = call("GET", path, token=adm)
        check(f"authz {path}: anon 401, citizen 403, admin 200", (s1, s2, s3) == (401, 403, 200), f"{s1} {s2} {s3}")

    # report lifecycle with a JPEG photo, sent while logged in
    s, r = report(cit_tok, photo=("qa.jpg", img("JPEG"), "image/jpeg"))
    check("report: valid submission with JPEG -> 201 SUBMITTED + photo_url", s == 201 and r["status"] == "SUBMITTED" and r["photo_url"], str(s))
    rid = r["id"]
    check("report: ward found automatically", r.get("ward") is not None)
    s, lst = call("GET", "/api/reports?limit=200", token=cit_tok)
    mine = [x for x in lst["reports"] if x["id"] == rid]
    check("report: appears in public list, marked mine, no user_id leaked", mine and mine[0]["mine"] and "user_id" not in mine[0])
    s, ph = call("GET", r["photo_url"])
    im = Image.open(io.BytesIO(ph))
    check("photo: served as JPEG, resized to <=640px", s == 200 and im.format == "JPEG" and max(im.size) <= 640, f"{s} {getattr(im, 'size', '')}")

    for fmt, ctype in (("PNG", "image/png"), ("WEBP", "image/webp")):
        s, rr = report(photo=(f"qa.{fmt.lower()}", img(fmt), ctype))
        ok = s == 201 and rr["photo_url"]
        if ok:
            s2, ph = call("GET", rr["photo_url"])
            ok = s2 == 200 and Image.open(io.BytesIO(ph)).format == "JPEG"
            call("DELETE", f"/api/admin/reports/{rr['id']}", token=adm)
        check(f"photo: {fmt} accepted and re-encoded to JPEG", ok, str(s))
    s, _ = report(photo=("evil.jpg", b"%PDF-1.4 not an image", "image/jpeg"))
    check("photo: non-image with .jpg name + image/jpeg MIME -> 415 (content checked)", s == 415, str(s))
    s, _ = report(photo=("../../etc/passwd.png", b"", "image/png"))
    check("photo: empty file -> 415", s == 415, str(s))
    s, _ = report(photo=("broken.jpg", img("JPEG")[:400], "image/jpeg"))
    check("photo: corrupt/truncated JPEG -> 415", s == 415, str(s))
    s, _ = report(photo=("big.jpg", b"\xff" * (8 * 1024 * 1024 + 10), "image/jpeg"))
    check("photo: over 8 MB -> 413", s == 413, str(s))
    s, rr = report(photo=None)
    check("photo: missing photo is allowed (photo_url null)", s == 201 and rr["photo_url"] is None, str(s))
    s2, _ = call("GET", f"/api/reports/{rr['id']}/photo")
    check("photo: report without photo -> photo URL 404", s2 == 404, str(s2))
    call("DELETE", f"/api/admin/reports/{rr['id']}", token=adm)

    # validation
    s, _ = call("POST", "/api/reports", form={"category": "not-a-category", "area": "Whitefield"})
    check("report: unknown category -> 422", s == 422, str(s))
    s, _ = call("POST", "/api/reports", form={"area": "Whitefield"})
    check("report: missing category -> 422", s == 422, str(s))
    s, _ = call("POST", "/api/reports", form={"category": "groundwater", "lat": "19.07", "lng": "72.87"})
    check("report: location outside Bengaluru -> 422", s == 422, str(s))
    s, rr = report(desc="<script>alert(1)</script>" + "x" * 5000)
    check("report: long + HTML text stored as plain text, capped at 500", s == 201 and len(rr["description"]) == 500 and "<script>" in rr["description"], str(s))
    call("DELETE", f"/api/admin/reports/{rr['id']}", token=adm)
    for bad in ("999999999", "abc", "-1"):
        s, _ = call("GET", f"/api/reports/{bad}")
        check(f"report: invalid id {bad} -> 404/422, not 500", s in (404, 422), str(s))

    # admin review
    s, _ = call("PATCH", f"/api/admin/reports/{rid}", token=cit_tok, json_body={"status": "VERIFIED"})
    check("review: citizen cannot change status -> 403", s == 403, str(s))
    s, _ = call("PATCH", f"/api/admin/reports/{rid}", token=adm, json_body={"status": "RESOLVED"})
    check("review: disallowed jump SUBMITTED->RESOLVED -> 409", s == 409, str(s))
    s, _ = call("PATCH", f"/api/admin/reports/{rid}", token=adm, json_body={"status": "BOGUS"})
    check("review: unknown status -> 422", s == 422, str(s))
    _, before = call("GET", "/api/risk/current")
    s1, _ = call("PATCH", f"/api/admin/reports/{rid}", token=adm, json_body={"status": "UNDER_REVIEW", "note": TAG})
    s2, r2 = call("PATCH", f"/api/admin/reports/{rid}", token=adm, json_body={"status": "VERIFIED"})
    check("review: SUBMITTED->UNDER_REVIEW->VERIFIED, history recorded", s1 == s2 == 200 and r2["status"] == "VERIFIED" and len(r2["history"]) == 3, f"{s1} {s2}")
    _, after = call("GET", "/api/risk/current")
    comm = lambda r: next(c for c in r["components"] if c["key"] == "community")["value"]  # noqa: E731
    check("review: verifying a report raises the community risk input by 1", comm(after) == comm(before) + 1, f"{comm(before)} -> {comm(after)}")
    s, _ = call("PATCH", "/api/admin/reports/999999999", token=adm, json_body={"status": "VERIFIED"})
    check("review: unknown report id -> 404", s == 404, str(s))
    s, rej = report()
    call("PATCH", f"/api/admin/reports/{rej['id']}", token=adm, json_body={"status": "REJECTED"})
    _, lst = call("GET", "/api/reports?limit=200")
    check("review: REJECTED report hidden from public list", all(x["id"] != rej["id"] for x in lst["reports"]))
    call("DELETE", f"/api/admin/reports/{rej['id']}", token=adm)
    _, logs = call("GET", "/api/admin/audit-logs", token=adm)
    check("audit: status change written to audit log", any(x["action"] == "report_status" and x["target"] == f"report:{rid}" for x in logs["logs"]))
    return adm, rid


def deletion(adm, cit_tok, rid):
    # someone else's report / anonymous report cannot be deleted by a citizen
    s, other = report(photo=("qa.jpg", img("JPEG"), "image/jpeg"))
    s1, _ = call("DELETE", f"/api/reports/{other['id']}", token=cit_tok)
    s2, _ = call("DELETE", f"/api/admin/reports/{other['id']}", token=cit_tok)
    s3, _ = call("DELETE", f"/api/admin/reports/{other['id']}/photo", token=cit_tok)
    s4, _ = call("DELETE", f"/api/reports/{other['id']}")
    check("delete authz: citizen can't delete others' report/photo (403 x3), anon 401", (s1, s2, s3, s4) == (403, 403, 403, 401), f"{s1} {s2} {s3} {s4}")

    # admin removes only the photo
    s, _ = call("DELETE", f"/api/admin/reports/{other['id']}/photo", token=adm)
    s2, _ = call("GET", f"/api/reports/{other['id']}/photo")
    _, again = call("GET", f"/api/reports/{other['id']}")
    check("photo delete: 200, photo URL now 404, report kept with photo_url null", s == 200 and s2 == 404 and again["photo_url"] is None, f"{s} {s2}")
    s, _ = call("DELETE", f"/api/admin/reports/{other['id']}/photo", token=adm)
    check("photo delete: repeated -> 404, not 500", s == 404, str(s))

    # admin deletes the report
    s, _ = call("DELETE", f"/api/admin/reports/{other['id']}", token=adm)
    s2, _ = call("GET", f"/api/reports/{other['id']}")
    s3, _ = call("DELETE", f"/api/admin/reports/{other['id']}", token=adm)
    check("admin delete: 200, then GET 404, repeated delete 404", (s, s2, s3) == (200, 404, 404), f"{s} {s2} {s3}")

    # owner deletes own report with photo: photo goes with it
    photo_url = f"/api/reports/{rid}/photo"
    s0, _ = call("GET", photo_url)
    s, _ = call("DELETE", f"/api/reports/{rid}", token=cit_tok)
    s2, _ = call("GET", f"/api/reports/{rid}")
    s3, _ = call("GET", photo_url)
    s4, _ = call("DELETE", f"/api/reports/{rid}", token=cit_tok)
    _, lst = call("GET", "/api/reports?limit=200&include_rejected=true")
    check("owner delete: photo existed, delete 200, report 404, photo 404, repeat 404, gone from list",
          (s0, s, s2, s3, s4) == (200, 200, 404, 404, 404) and all(x["id"] != rid for x in lst["reports"]), f"{s0} {s} {s2} {s3} {s4}")
    _, logs = call("GET", "/api/admin/audit-logs?limit=200", token=adm)
    txt = json.dumps(logs)
    check("audit: report_delete, report_delete_own, report_photo_remove logged", all(a in txt for a in ("report_delete", "report_delete_own", "report_photo_remove")))


def security(cit_tok):
    s, h = 0, {}
    req = urllib.request.Request(BASE + "/")  # noqa: S310
    with urllib.request.urlopen(req) as r:  # noqa: S310
        h = {k.lower(): v for k, v in r.headers.items()}
    check("headers: CSP, X-Frame-Options DENY, nosniff on pages",
          "script-src 'self'" in h.get("content-security-policy", "") and h.get("x-frame-options") == "DENY" and h.get("x-content-type-options") == "nosniff")
    s, b = call("GET", "/api/reports?category=groundwater%27%20OR%20%271%27%3D%271")
    check("sqli: injected filter value rejected (422), not executed", s == 422, str(s))
    s, b = call("GET", "/api/admin-setup-status")
    check("setup status: no secret or email in response", ADMIN[1] not in json.dumps(b) and ADMIN[0] not in json.dumps(b))
    s, b = call("GET", "/api/health")
    check("health: no secret in response", ADMIN[1] not in json.dumps(b))
    s, b = call("GET", "/api/admin/users", token=admin_token())
    check("admin users list: no password hashes", "password_hash" not in json.dumps(b) and "scrypt" not in json.dumps(b))


def setup_persist(cit_tok):
    s, r = report(cit_tok, photo=("persist.jpg", img("JPEG", color=(200, 20, 20)), "image/jpeg"), desc="persistence across restart")
    json.dump({"rid": r["id"]}, open(STATE, "w"))
    check("persistence: QA report with photo created before restart", s == 201 and r["photo_url"], str(s))


def after_restart():
    rid = json.load(open(STATE))["rid"]
    s, r = call("GET", f"/api/reports/{rid}")
    s2, ph = call("GET", f"/api/reports/{rid}/photo")
    check("persistence: report and photo still there after server restart",
          s == 200 and TAG in r["description"] and s2 == 200 and Image.open(io.BytesIO(ph)).getpixel((5, 5))[0] > 150, f"{s} {s2}")
    adm = admin_token()
    s, _ = call("DELETE", f"/api/admin/reports/{rid}", token=adm)
    check("cleanup: QA persistence report deleted", s == 200, str(s))


def leftovers():
    adm = admin_token()
    _, b = call("GET", "/api/admin/reports?limit=500", token=adm)
    left = [x["id"] for x in b["reports"] if TAG in (x["description"] or "")]
    for i in left:
        call("DELETE", f"/api/admin/reports/{i}", token=adm)
    _, b = call("GET", "/api/admin/reports?limit=500", token=adm)
    check("cleanup: no QA-TEST-DO-NOT-KEEP reports remain", not [x for x in b["reports"] if TAG in (x["description"] or "")], str(left))


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    if phase in ("all", "setup"):
        email, pw, tok = accounts()
        adm, rid = admin_and_reports(tok)
        deletion(adm, tok, rid)
        security(tok)
        setup_persist(tok)
    if phase in ("all", "after-restart"):
        after_restart()
        leftovers()
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)} passed, {len(bad)} failed")
    sys.exit(1 if bad else 0)
