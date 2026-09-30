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
        assert db.migrate() == [1, 2]
        assert db.migrate() == []                              # idempotent
        rows = db.rows("SELECT type, category, status FROM reports ORDER BY id")
        assert rows == [{"type": "dry", "category": "groundwater", "status": "SUBMITTED"},
                        {"type": "sewage", "category": "drainage", "status": "SUBMITTED"}]
        assert db.schema_version() == 2
    finally:
        if pg[0]:
            os.environ["DATABASE_URL"] = pg[0]
        if pg[1]:
            os.environ["POSTGRES_URL"] = pg[1]
        monkeypatch.undo()
        importlib.reload(db)
