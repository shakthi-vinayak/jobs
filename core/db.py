"""SQLite database layer for job aggregator."""
from __future__ import annotations

import sqlite3
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SCHEMA_JOBS = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    link TEXT NOT NULL UNIQUE,
    title TEXT,
    company TEXT,
    location TEXT,
    posted_at TEXT,
    fetched_at TEXT NOT NULL,
    relevance_score INTEGER,
    llm_reason TEXT,
    status TEXT DEFAULT 'new'
);
"""

SCHEMA_RUN_LOG = """
CREATE TABLE IF NOT EXISTS run_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_started_at TEXT NOT NULL,
    run_finished_at TEXT,
    jobs_fetched INTEGER,
    jobs_new INTEGER
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    """Return a connection with WAL mode and foreign keys enabled."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str) -> sqlite3.Connection:
    """Create tables if they don't exist and return a connection."""
    conn = get_connection(db_path)
    conn.executescript(SCHEMA_JOBS + SCHEMA_RUN_LOG)
    conn.commit()
    logger.info("Database initialized at %s", db_path)
    return conn


def insert_jobs(conn: sqlite3.Connection, jobs: list[dict]) -> int:
    """Insert jobs, skipping duplicates via ON CONFLICT. Returns count of newly inserted rows."""
    now = datetime.now(timezone.utc).isoformat()
    new_count = 0
    for job in jobs:
        try:
            cursor = conn.execute(
                """
                INSERT INTO jobs (source, link, title, company, location, posted_at, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(link) DO NOTHING
                """,
                (
                    job.get("source"),
                    job.get("link"),
                    job.get("title"),
                    job.get("company"),
                    job.get("location"),
                    job.get("posted_at"),
                    job.get("fetched_at", now),
                ),
            )
            if cursor.rowcount > 0:
                new_count += 1
        except sqlite3.Error as e:
            logger.error("Failed to insert job %s: %s", job.get("link"), e)
    conn.commit()
    return new_count


def get_new_unscored_jobs(conn: sqlite3.Connection) -> list[dict]:
    """Return jobs with status='new' and relevance_score IS NULL."""
    cur = conn.execute(
        """
        SELECT id, source, link, title, company, location, posted_at, raw_description
        FROM jobs WHERE status = 'new' AND relevance_score IS NULL
        """
    )
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def update_llm_scores(conn: sqlite3.Connection, scores: list[dict]) -> None:
    """Update relevance_score and llm_reason for scored jobs."""
    for item in scores:
        conn.execute(
            """
            UPDATE jobs SET relevance_score = ?, llm_reason = ?
            WHERE link = ?
            """,
            (item.get("score"), item.get("reason"), item.get("link")),
        )
    conn.commit()


def get_notifiable_jobs(conn: sqlite3.Connection, threshold: int) -> list[dict]:
    """Return jobs with status='new' and relevance_score >= threshold."""
    cur = conn.execute(
        """
        SELECT id, source, link, title, company, location, relevance_score, llm_reason, fetched_at
        FROM jobs WHERE status = 'new' AND relevance_score >= ?
        ORDER BY relevance_score DESC
        """,
        (threshold,),
    )
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def mark_jobs_notified(conn: sqlite3.Connection, job_ids: list[int]) -> None:
    """Set status='notified' for the given job IDs."""
    conn.executemany(
        "UPDATE jobs SET status = 'notified' WHERE id = ?",
        [(jid,) for jid in job_ids],
    )
    conn.commit()


def start_run(conn: sqlite3.Connection) -> int:
    """Insert a new run_log entry and return its ID."""
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO run_log (run_started_at) VALUES (?)",
        (now,),
    )
    conn.commit()
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, jobs_fetched: int, jobs_new: int) -> None:
    """Update run_log entry with completion details."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE run_log SET run_finished_at = ?, jobs_fetched = ?, jobs_new = ?
        WHERE id = ?
        """,
        (now, jobs_fetched, jobs_new, run_id),
    )
    conn.commit()


def has_previous_runs(conn: sqlite3.Connection) -> bool:
    """Check if any run_log entries exist (used for bootstrap detection)."""
    cur = conn.execute("SELECT COUNT(*) FROM run_log")
    return cur.fetchone()[0] > 0


def get_all_jobs_for_report(conn: sqlite3.Connection) -> list[dict]:
    """Return all jobs for HTML report generation, newest first."""
    cur = conn.execute(
        """
        SELECT id, source, link, title, company, location, posted_at, fetched_at,
               relevance_score, llm_reason, status
        FROM jobs ORDER BY fetched_at DESC
        """
    )
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]
