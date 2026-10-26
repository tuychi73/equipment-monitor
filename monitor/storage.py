"""SQLite: tekshiruvlar tarixi, joriy holat va nosozliklar (incident) jurnali."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    device_id  TEXT NOT NULL,
    ts         TEXT NOT NULL,
    status     TEXT NOT NULL,          -- OK | WARN | DOWN
    latency_ms REAL,
    detail     TEXT
);
CREATE INDEX IF NOT EXISTS ix_checks_device_ts ON checks(device_id, ts);

CREATE TABLE IF NOT EXISTS device_state (
    device_id  TEXT PRIMARY KEY,
    status     TEXT NOT NULL,          -- tasdiqlangan holat
    fail_count INTEGER NOT NULL DEFAULT 0,
    since      TEXT NOT NULL,
    detail     TEXT
);

CREATE TABLE IF NOT EXISTS incidents (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id  TEXT NOT NULL,
    kind       TEXT NOT NULL,          -- DOWN | WARN
    opened_at  TEXT NOT NULL,
    closed_at  TEXT,
    detail     TEXT
);
"""


def now() -> datetime:
    return datetime.now(timezone.utc)


class Storage:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Dashboard (web) va monitoring oqimi bir vaqtda ishlatadi
        self.con = sqlite3.connect(str(path), check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.con.executescript(SCHEMA)

    # --- yozish ---
    def add_check(self, device_id: str, ts: datetime, status: str, latency_ms, detail: str) -> None:
        with self.lock, self.con:
            self.con.execute("INSERT INTO checks VALUES (?, ?, ?, ?, ?)",
                             (device_id, ts.isoformat(), status, latency_ms, detail))

    def get_state(self, device_id: str) -> sqlite3.Row | None:
        with self.lock:
            return self.con.execute("SELECT * FROM device_state WHERE device_id = ?", (device_id,)).fetchone()

    def set_state(self, device_id: str, status: str, fail_count: int, since: datetime, detail: str) -> None:
        with self.lock, self.con:
            self.con.execute("""
                INSERT INTO device_state VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET status = excluded.status, fail_count = excluded.fail_count,
                    since = excluded.since, detail = excluded.detail""",
                             (device_id, status, fail_count, since.isoformat(), detail))

    def open_incident(self, device_id: str, kind: str, ts: datetime, detail: str) -> None:
        with self.lock, self.con:
            self.con.execute("INSERT INTO incidents (device_id, kind, opened_at, detail) VALUES (?, ?, ?, ?)",
                             (device_id, kind, ts.isoformat(), detail))

    def close_incident(self, device_id: str, ts: datetime) -> sqlite3.Row | None:
        with self.lock, self.con:
            row = self.con.execute("SELECT * FROM incidents WHERE device_id = ? AND closed_at IS NULL "
                                   "ORDER BY id DESC LIMIT 1", (device_id,)).fetchone()
            if row:
                self.con.execute("UPDATE incidents SET closed_at = ? WHERE id = ?", (ts.isoformat(), row["id"]))
            return row

    # --- o'qish (dashboard va hisobot uchun) ---
    def uptime(self, device_id: str, hours: int = 24) -> float | None:
        since = (now() - timedelta(hours=hours)).isoformat()
        with self.lock:
            row = self.con.execute("""
                SELECT avg(CASE WHEN status <> 'DOWN' THEN 1.0 ELSE 0.0 END) AS up, count(*) AS n
                FROM checks WHERE device_id = ? AND ts >= ?""", (device_id, since)).fetchone()
        return None if row["n"] == 0 else round(100 * row["up"], 2)

    def last_check(self, device_id: str) -> sqlite3.Row | None:
        with self.lock:
            return self.con.execute("SELECT * FROM checks WHERE device_id = ? ORDER BY ts DESC LIMIT 1",
                                    (device_id,)).fetchone()

    def incidents(self, limit: int = 50) -> list[dict]:
        with self.lock:
            rows = self.con.execute("""
                SELECT id, device_id, kind, opened_at, closed_at, detail,
                       round((julianday(coalesce(closed_at, ?)) - julianday(opened_at)) * 1440, 1) AS minutes
                FROM incidents ORDER BY id DESC LIMIT ?""", (now().isoformat(), limit)).fetchall()
        return [dict(r) for r in rows]

    def mttr_minutes(self, device_id: str | None = None) -> float | None:
        """Mean Time To Repair: yopilgan DOWN nosozliklarning o'rtacha davomiyligi."""
        sql = ("SELECT avg((julianday(closed_at) - julianday(opened_at)) * 1440) FROM incidents "
               "WHERE kind = 'DOWN' AND closed_at IS NOT NULL")
        args: tuple = ()
        if device_id:
            sql += " AND device_id = ?"
            args = (device_id,)
        with self.lock:
            v = self.con.execute(sql, args).fetchone()[0]
        return None if v is None else round(v, 1)
