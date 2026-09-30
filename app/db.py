"""Database access and versioned migrations for SQLite (local) and PostgreSQL (Neon on Vercel).

The same SQL (with ? placeholders) runs on both. Migrations are numbered and recorded in schema_migrations;
on Postgres they run under an advisory lock so two serverless instances cannot migrate at once.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

BASE = Path(__file__).resolve().parent
PG_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or ""
# On Vercel /tmp is the only writable path (used only if no DATABASE_URL is set); locally, a file next to the app.
_default = Path("/tmp/jalsetu.db") if os.environ.get("VERCEL") else BASE.parent / "jalsetu.db"  # noqa: S108
DB_PATH = Path(os.environ.get("JALSETU_DB", _default))
DIALECT = "postgres" if PG_URL else "sqlite"
_lock = threading.Lock()


class _PgRow(dict):
    def __getitem__(self, k):
        return list(self.values())[k] if isinstance(k, int) else dict.__getitem__(self, k)


class _PgResult:
    def __init__(self, cur, lastrowid):
        self.cur, self.lastrowid, self.rowcount = cur, lastrowid, cur.rowcount

    def fetchone(self):
        return self.cur.fetchone() if self.cur.description else None

    def fetchall(self):
        return self.cur.fetchall() if self.cur.description else []


class _PgConn:
    def __init__(self, con):
        self.con = con

    def execute(self, sql: str, params=()):
        insert = sql.lstrip().upper().startswith("INSERT") and "RETURNING" not in sql.upper()
        cur = self.con.cursor(row_factory=lambda c: (lambda vals: _PgRow(zip([d.name for d in c.description], vals))))
        cur.execute(sql.replace("?", "%s") + (" RETURNING id" if insert else ""), params)
        return _PgResult(cur, cur.fetchone()["id"] if insert else None)


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
    lite = sqlite3.connect(DB_PATH, timeout=10)
    lite.row_factory = sqlite3.Row
    lite.execute("PRAGMA foreign_keys=ON")
    try:
        with _lock:
            yield lite
            lite.commit()
    finally:
        lite.close()


def rows(sql, params=()) -> list[dict]:
    with db() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def one(sql, params=()):
    with db() as c:
        r = c.execute(sql, params).fetchone()
        return dict(r) if r else None


def run(sql, params=()):
    with db() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid if cur.lastrowid is not None else cur.rowcount


# ------------------------------------------------------------------ migrations
T = {"sqlite": {"pk": "INTEGER PRIMARY KEY AUTOINCREMENT", "blob": "BLOB", "float": "REAL"},
     "postgres": {"pk": "SERIAL PRIMARY KEY", "blob": "BYTEA", "float": "DOUBLE PRECISION"}}

MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (1, "v1 schema (reports, listings)", [
        """CREATE TABLE IF NOT EXISTS reports(
             id {pk}, type TEXT NOT NULL, area TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
             price {float}, litres INTEGER, photo {blob}, ai_cls TEXT, ai_text TEXT, created_at {float} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS reports_time ON reports(created_at)",
        """CREATE TABLE IF NOT EXISTS listings(
             id {pk}, kind TEXT NOT NULL, area TEXT NOT NULL, name TEXT NOT NULL, qty INTEGER NOT NULL,
             token_hash TEXT NOT NULL, created_at {float} NOT NULL)""",
    ]),
    (2, "accounts, report workflow, exchange, risk, ML log, ingestion, audit", [
        """CREATE TABLE users(
             id {pk}, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, role TEXT NOT NULL,
             organization TEXT, password_hash TEXT NOT NULL, created_at {float} NOT NULL, last_login_at {float})""",
        """CREATE TABLE sessions(
             id {pk}, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, token_hash TEXT NOT NULL UNIQUE,
             created_at {float} NOT NULL, expires_at {float} NOT NULL)""",
        "ALTER TABLE reports ADD COLUMN category TEXT",
        "ALTER TABLE reports ADD COLUMN status TEXT NOT NULL DEFAULT 'SUBMITTED'",
        "ALTER TABLE reports ADD COLUMN lat {float}",
        "ALTER TABLE reports ADD COLUMN lng {float}",
        "ALTER TABLE reports ADD COLUMN ward_no INTEGER",
        "ALTER TABLE reports ADD COLUMN ward_name TEXT",
        "ALTER TABLE reports ADD COLUMN user_id INTEGER",
        "ALTER TABLE reports ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE reports ADD COLUMN updated_at {float}",
        "UPDATE reports SET category = CASE type WHEN 'dry' THEN 'groundwater' WHEN 'low' THEN 'groundwater' "
        "WHEN 'sewage' THEN 'drainage' WHEN 'quality' THEN 'contamination' WHEN 'tanker' THEN 'tanker' ELSE 'other' END "
        "WHERE category IS NULL",
        "CREATE INDEX IF NOT EXISTS reports_status ON reports(status)",
        """CREATE TABLE report_events(
             id {pk}, report_id INTEGER NOT NULL, from_status TEXT, to_status TEXT NOT NULL, note TEXT,
             actor_id INTEGER, created_at {float} NOT NULL)""",
        """CREATE TABLE offers(
             id {pk}, user_id INTEGER, organization TEXT NOT NULL, area TEXT, lat {float} NOT NULL, lng {float} NOT NULL,
             qty_kl_per_day {float} NOT NULL, treatment_level TEXT NOT NULL, quality_notes TEXT NOT NULL DEFAULT '',
             bod_mg_l {float}, tss_mg_l {float}, available_from TEXT NOT NULL, available_to TEXT NOT NULL,
             reuse_categories TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', is_demo INTEGER NOT NULL DEFAULT 0,
             created_at {float} NOT NULL)""",
        """CREATE TABLE requests(
             id {pk}, user_id INTEGER, requester TEXT NOT NULL, area TEXT, lat {float} NOT NULL, lng {float} NOT NULL,
             qty_kl_per_day {float} NOT NULL, needed_from TEXT NOT NULL, needed_to TEXT NOT NULL, purpose TEXT NOT NULL,
             min_treatment TEXT NOT NULL DEFAULT 'secondary', status TEXT NOT NULL DEFAULT 'OPEN',
             is_demo INTEGER NOT NULL DEFAULT 0, created_at {float} NOT NULL)""",
        """CREATE TABLE risk_scores(
             id {pk}, computed_at {float} NOT NULL, score {float} NOT NULL, level TEXT NOT NULL,
             components TEXT NOT NULL, inputs_hash TEXT NOT NULL, config_version TEXT NOT NULL)""",
        """CREATE TABLE warnings(
             id {pk}, rule_id TEXT NOT NULL, level TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL,
             first_seen {float} NOT NULL, last_seen {float} NOT NULL, active INTEGER NOT NULL DEFAULT 1)""",
        """CREATE TABLE model_predictions(
             id {pk}, model TEXT NOT NULL, version TEXT NOT NULL, inputs TEXT NOT NULL, output TEXT NOT NULL,
             created_at {float} NOT NULL)""",
        """CREATE TABLE reservoir_readings(
             id {pk}, reservoir_id TEXT NOT NULL, reservoir TEXT NOT NULL, date TEXT NOT NULL,
             storage_tmc {float}, capacity_tmc {float}, pct_full {float}, inflow_cusecs {float}, outflow_cusecs {float},
             source TEXT NOT NULL, url TEXT NOT NULL, status TEXT NOT NULL, added_by INTEGER, created_at {float} NOT NULL)""",
        """CREATE TABLE lake_observations(
             id {pk}, lake_id TEXT NOT NULL, date TEXT NOT NULL, parameter TEXT NOT NULL, value {float},
             class TEXT, source TEXT NOT NULL, url TEXT NOT NULL, added_by INTEGER, created_at {float} NOT NULL)""",
        """CREATE TABLE audit_logs(
             id {pk}, actor_id INTEGER, action TEXT NOT NULL, target TEXT, detail TEXT, ip TEXT, created_at {float} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS audit_time ON audit_logs(created_at)",
    ]),
]


def _columns(c, table: str) -> set[str]:
    if DIALECT == "postgres":
        return {r["column_name"] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name=?", (table,)).fetchall()}
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}


def migrate() -> list[int]:
    applied_now = []
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as c:
        if DIALECT == "postgres":
            c.execute("SELECT pg_advisory_xact_lock(470041)")
        c.execute(f"CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at {T[DIALECT]['float']} NOT NULL)")
        done = {r[0] for r in c.execute("SELECT version FROM schema_migrations").fetchall()}
        import time
        for ver, name, stmts in MIGRATIONS:
            if ver in done:
                continue
            for s in stmts:
                sql = s.format(**T[DIALECT])
                if sql.upper().startswith("ALTER TABLE") and " ADD COLUMN " in sql.upper():
                    table = sql.split()[2]
                    col = sql.split(" ADD COLUMN ")[1].split()[0]
                    if col in _columns(c, table):      # tolerate a half-applied earlier attempt
                        continue
                if DIALECT == "sqlite" and sql.startswith("CREATE TABLE ") and "IF NOT EXISTS" not in sql:
                    sql = sql.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
                if DIALECT == "postgres" and sql.startswith("CREATE TABLE ") and "IF NOT EXISTS" not in sql:
                    sql = sql.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
                c.execute(sql)
            c.execute("INSERT INTO schema_migrations(version, name, applied_at) VALUES(?,?,?)"
                      + (" RETURNING version" if DIALECT == "postgres" else ""), (ver, name, time.time()))
            applied_now.append(ver)
    return applied_now


def schema_version() -> int:
    r = one("SELECT MAX(version) AS v FROM schema_migrations")
    return int(r["v"] or 0) if r else 0


def ping() -> bool:
    try:
        one("SELECT 1 AS ok")
        return True
    except Exception:
        return False
