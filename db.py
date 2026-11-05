"""Хранение результатов тестов в SQLite."""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).with_name("results.db")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS results (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                username   TEXT,
                full_name  TEXT,
                topic      TEXT NOT NULL,
                score      INTEGER NOT NULL,
                total      INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )


def save_result(user_id: int, username: str | None, full_name: str,
                topic: str, score: int, total: int) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO results (user_id, username, full_name, topic, score, total, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, full_name, topic, score, total,
             datetime.now().strftime("%Y-%m-%d %H:%M")),
        )


def user_history(user_id: int, limit: int = 10) -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute(
            "SELECT * FROM results WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()


def summary() -> dict:
    with _conn() as c:
        total, users = c.execute(
            "SELECT COUNT(*), COUNT(DISTINCT user_id) FROM results"
        ).fetchone()
        by_topic = c.execute(
            "SELECT topic, COUNT(*) AS n, AVG(100.0 * score / total) AS avg_pct "
            "FROM results GROUP BY topic"
        ).fetchall()
        last = c.execute("SELECT * FROM results ORDER BY id DESC LIMIT 10").fetchall()
    return {"total": total, "users": users, "by_topic": by_topic, "last": last}


def all_results() -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute("SELECT * FROM results ORDER BY id").fetchall()


def init_leads() -> None:
    with _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS leads (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                username   TEXT,
                full_name  TEXT,
                score      INTEGER,
                level      TEXT,
                created_at TEXT NOT NULL
            )"""
        )


def save_lead(user_id: int, username: str | None, full_name: str,
              score: int | None, level: str | None) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO leads (user_id, username, full_name, score, level, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, full_name, score, level,
             datetime.now().strftime("%Y-%m-%d %H:%M")),
        )


def last_leads(limit: int = 20) -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute("SELECT * FROM leads ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
