"""Accounts, sessions and roles.

- Passwords: scrypt (N=2^14, r=8, p=1, 16-byte salt), never stored in plain text.
- Sessions: random 32-byte token given to the browser once; only its SHA-256 is stored; expire after 7 days.
- Roles: citizen, organization, admin. Admin accounts cannot self-register; they come from ADMIN_EMAIL/ADMIN_PASSWORD.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from typing import Optional

from fastapi import Header, HTTPException, Request

from . import db

ROLES = ("citizen", "organization", "admin")
SESSION_DAYS = 7
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}$")
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, dklen=64, maxmem=64 * 1024 * 1024, **SCRYPT)
    return "scrypt${n}${r}${p}${s}${h}".format(**SCRYPT, s=base64.b64encode(salt).decode(), h=base64.b64encode(h).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, s, h = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(s), n=int(n), r=int(r), p=int(p), dklen=64,
                              maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def token_hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def validate_new_account(email: str, password: str, name: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    if len(password) < 8 or len(password) > 200:
        raise HTTPException(422, "Password must be 8 to 200 characters.")
    if password.lower() in {"password", "12345678", "123456789", "qwertyui", "jalsetu123"} or password.lower() == email:
        raise HTTPException(422, "That password is too easy to guess. Choose another.")
    if not name.strip() or len(name) > 80:
        raise HTTPException(422, "Enter your name (up to 80 characters).")
    return email


def create_user(email: str, password: str, name: str, role: str, organization: Optional[str] = None) -> dict:
    if role not in ROLES:
        raise HTTPException(422, "Unknown role.")
    email = validate_new_account(email, password, name)
    if db.one("SELECT id FROM users WHERE email=?", (email,)):
        raise HTTPException(409, "An account with this email already exists.")
    uid = db.run("INSERT INTO users(email,name,role,organization,password_hash,created_at) VALUES(?,?,?,?,?,?)",
                 (email, name.strip(), role, (organization or "").strip() or None, hash_password(password), time.time()))
    return public_user(db.one("SELECT * FROM users WHERE id=?", (uid,)))


def public_user(u: dict) -> dict:
    return {"id": u["id"], "email": u["email"], "name": u["name"], "role": u["role"], "organization": u.get("organization")}


def login(email: str, password: str) -> tuple[str, dict]:
    u = db.one("SELECT * FROM users WHERE email=?", (email.strip().lower(),))
    # verify against a dummy hash when the user doesn't exist, so timing doesn't reveal which emails exist
    ok = verify_password(password, u["password_hash"] if u else _DUMMY)
    if not u or not ok:
        raise HTTPException(401, "Email or password is incorrect.")
    token = secrets.token_urlsafe(32)
    now = time.time()
    db.run("INSERT INTO sessions(user_id,token_hash,created_at,expires_at) VALUES(?,?,?,?)",
           (u["id"], token_hash(token), now, now + SESSION_DAYS * 86400))
    db.run("UPDATE users SET last_login_at=? WHERE id=?", (now, u["id"]))
    db.run("DELETE FROM sessions WHERE expires_at < ?", (now,))
    return token, public_user(u)


def logout(token: str) -> None:
    db.run("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))


_DUMMY = hash_password(secrets.token_hex(8))


def _bearer(authorization: str) -> str:
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def user_from_header(authorization: str) -> Optional[dict]:
    t = _bearer(authorization or "")
    if not t:
        return None
    r = db.one("SELECT u.*, s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?", (token_hash(t),))
    if not r or r["expires_at"] < time.time():
        return None
    return public_user(r)


def optional_user(authorization: str = Header("")) -> Optional[dict]:
    return user_from_header(authorization)


def current_user(authorization: str = Header("")) -> dict:
    u = user_from_header(authorization)
    if not u:
        raise HTTPException(401, "Please log in first.")
    return u


def require(*roles: str):
    def dep(authorization: str = Header("")) -> dict:
        u = current_user(authorization)
        if u["role"] not in roles:
            raise HTTPException(403, "Your account type can't do this.")
        return u
    return dep


def ensure_admin_from_env() -> Optional[int]:
    """Create or update the admin account from ADMIN_EMAIL / ADMIN_PASSWORD (never hard-coded)."""
    email, pw = os.environ.get("ADMIN_EMAIL", "").strip().lower(), os.environ.get("ADMIN_PASSWORD", "").strip()
    if not email or not pw:
        return None
    if len(pw) < 8:   # same minimum as every account; never take the whole site down over a bad setting
        import logging
        logging.getLogger("jalsetu").error("ADMIN_PASSWORD is shorter than 8 characters; admin account not created or updated")
        return None
    u = db.one("SELECT * FROM users WHERE email=?", (email,))
    if u:
        if u["role"] != "admin" or not verify_password(pw, u["password_hash"]):
            db.run("UPDATE users SET role='admin', password_hash=? WHERE id=?", (hash_password(pw), u["id"]))
        return u["id"]
    return db.run("INSERT INTO users(email,name,role,organization,password_hash,created_at) VALUES(?,?,?,?,?,?)",
                  (email, "Administrator", "admin", None, hash_password(pw), time.time()))


def audit(actor: Optional[dict], action: str, target: str = "", detail: str = "", request: Optional[Request] = None) -> None:
    ip = ""
    if request is not None:
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")
    db.run("INSERT INTO audit_logs(actor_id,action,target,detail,ip,created_at) VALUES(?,?,?,?,?,?)",
           (actor["id"] if actor else None, action, target, detail[:500], ip, time.time()))
