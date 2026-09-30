"""Migrations: idempotent, and v1 data survives the upgrade with categories mapped."""
import importlib
import os
import sqlite3
import time


def test_v1_database_upgrades(tmp_path, monkeypatch):
    path = tmp_path / "v1.db"
    con = sqlite3.connect(path)
    con.executescript("""CREATE TABLE reports(id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, area TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '', price REAL, litres INTEGER, photo BLOB, ai_cls TEXT, ai_text TEXT, created_at REAL NOT NULL);
        CREATE TABLE listings(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, area TEXT NOT NULL, name TEXT NOT NULL,
        qty INTEGER NOT NULL, token_hash TEXT NOT NULL, created_at REAL NOT NULL);""")
    con.execute("INSERT INTO reports(type,area,note,created_at) VALUES('dry','Whitefield','old report',?)", (time.time(),))
    con.execute("INSERT INTO reports(type,area,note,created_at) VALUES('sewage','Bellandur','foam',?)", (time.time(),))
    con.commit(); con.close()
    monkeypatch.setenv("JALSETU_DB", str(path))
    pg = (os.environ.pop("DATABASE_URL", None), os.environ.pop("POSTGRES_URL", None))
    from app import db
    importlib.reload(db)
    try:
        assert db.migrate() == [1, 2, 3]
        assert db.migrate() == []                              # idempotent
        rows = db.rows("SELECT type, category, status FROM reports ORDER BY id")
        assert rows == [{"type": "dry", "category": "groundwater", "status": "SUBMITTED"},
                        {"type": "sewage", "category": "drainage", "status": "SUBMITTED"}]
        assert db.schema_version() == 3
    finally:
        if pg[0]:
            os.environ["DATABASE_URL"] = pg[0]
        if pg[1]:
            os.environ["POSTGRES_URL"] = pg[1]
        monkeypatch.undo()
        importlib.reload(db)


def test_cleanup_migration_removes_only_the_three_rehearsal_reports(tmp_path, monkeypatch):
    path = tmp_path / "v2.db"
    monkeypatch.setenv("JALSETU_DB", str(path))
    pg = (os.environ.pop("DATABASE_URL", None), os.environ.pop("POSTGRES_URL", None))
    from app import db
    importlib.reload(db)
    try:
        keep_migrations = db.MIGRATIONS
        db.MIGRATIONS = keep_migrations[:2]
        db.migrate()
        t = 1790755000     # 30 Sep 2026, 07:56 UTC (inside the window)
        rows = [("groundwater", "Banashankari", t), ("groundwater", "Banashankari", t + 60), ("groundwater", "Basavanagudi", t + 120),
                ("groundwater", "Whitefield", t), ("leakage", "Banashankari", t), ("groundwater", "Banashankari", 1790770000)]
        for cat, area, ts in rows:
            rid = db.run("INSERT INTO reports(type,category,area,note,status,created_at) VALUES(?,?,?,?,?,?)", ("dry", cat, area, "", "SUBMITTED", ts))
            db.run("INSERT INTO report_events(report_id,to_status,created_at) VALUES(?,?,?)", (rid, "SUBMITTED", ts))
        db.MIGRATIONS = keep_migrations
        assert db.migrate() == [3]
        left = db.rows("SELECT category, area, created_at FROM reports ORDER BY id")
        assert left == [{"category": "groundwater", "area": "Whitefield", "created_at": t},
                        {"category": "leakage", "area": "Banashankari", "created_at": t},
                        {"category": "groundwater", "area": "Banashankari", "created_at": 1790770000}]
        assert db.one("SELECT COUNT(*) AS n FROM report_events")["n"] == 3
        assert db.one("SELECT COUNT(*) AS n FROM audit_logs WHERE detail LIKE 'cleanup migration 3%'")["n"] == 3
    finally:
        db.MIGRATIONS = keep_migrations
        if pg[0]:
            os.environ["DATABASE_URL"] = pg[0]
        if pg[1]:
            os.environ["POSTGRES_URL"] = pg[1]
        monkeypatch.undo()
        importlib.reload(db)
