"""SQLite-backed repository for managing ERPNext retry jobs."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from expense_bot import get_logger
from expense_bot.graph.state import RetryJob

LOGGER = get_logger("integrations.retry_queue")


class RetryQueueError(RuntimeError):
    """Raised when a retry queue operation cannot be fulfilled."""


class RetryQueueRepository:
    """Persistence layer for RetryJob records inside SQLite."""

    def __init__(self, db_path: str | Path, *, timeout: float = 5.0) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            self._db_path,
            timeout=timeout,
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._initialize_schema()

    def close(self) -> None:
        """Close the underlying SQLite connection."""

        self._conn.close()

    def enqueue(self, job: RetryJob) -> RetryJob:
        """Persist a new job and return it with its generated ID."""

        payload_json = self._serialize_payload(job.payload)
        next_run = self._serialize_datetime(job.next_run_at)
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO retry_jobs (
                    thread_id, payload, attempts, next_run_at, error
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (job.thread_id, payload_json, job.attempts, next_run, job.error),
            )
            job_id = int(cursor.lastrowid)
        LOGGER.debug("Enqueued retry job id=%s thread_id=%s", job_id, job.thread_id)
        return replace(job, id=job_id)

    def get(self, job_id: int) -> RetryJob | None:
        """Return a job by id if it exists."""

        row = self._conn.execute(
            "SELECT * FROM retry_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_job(row)

    def acquire_due_job(
        self, lock_id: str, *, now: datetime | None = None
    ) -> RetryJob | None:
        """Fetch the next due job and lock it for the caller."""

        if not lock_id:
            raise ValueError("lock_id is required to acquire a job.")
        current = self._serialize_datetime(now or datetime.now(UTC))
        with self._conn:
            row = self._conn.execute(
                """
                SELECT id
                FROM retry_jobs
                WHERE locked_by IS NULL AND next_run_at <= ?
                ORDER BY next_run_at ASC, id ASC
                LIMIT 1
                """,
                (current,),
            ).fetchone()
            if not row:
                return None
            job_id = int(row["id"])
            updated = self._conn.execute(
                """
                UPDATE retry_jobs
                SET locked_by = ?, locked_at = ?
                WHERE id = ? AND locked_by IS NULL
                """,
                (lock_id, current, job_id),
            )
            if updated.rowcount == 0:
                return None
            row = self._conn.execute(
                "SELECT * FROM retry_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_job(row)

    def mark_failure(
        self,
        job_id: int,
        lock_id: str,
        *,
        error: str,
        next_run_at: datetime,
    ) -> RetryJob:
        """Record a failed attempt, updating next_run_at and unlocking the job."""

        if not lock_id:
            raise ValueError("lock_id is required to mark failure.")
        next_run = self._serialize_datetime(next_run_at)
        with self._conn:
            updated = self._conn.execute(
                """
                UPDATE retry_jobs
                SET attempts = attempts + 1,
                    next_run_at = ?,
                    error = ?,
                    locked_by = NULL,
                    locked_at = NULL
                WHERE id = ? AND locked_by = ?
                """,
                (next_run, error, job_id, lock_id),
            )
            if updated.rowcount == 0:
                raise RetryQueueError(
                    f"Retry job {job_id} is not locked by {lock_id} or does not exist."
                )
            row = self._conn.execute(
                "SELECT * FROM retry_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        job = self._row_to_job(row)
        LOGGER.info(
            "Retry job %s failed (%s attempts); next run scheduled for %s",
            job_id,
            job.attempts,
            next_run,
        )
        return job

    def mark_success(self, job_id: int, lock_id: str) -> None:
        """Remove a job once it succeeds."""

        if not lock_id:
            raise ValueError("lock_id is required to mark success.")
        with self._conn:
            deleted = self._conn.execute(
                "DELETE FROM retry_jobs WHERE id = ? AND locked_by = ?",
                (job_id, lock_id),
            )
            if deleted.rowcount == 0:
                raise RetryQueueError(
                    f"Retry job {job_id} cannot be deleted; lock not owned by {lock_id}."
                )
        LOGGER.info("Retry job %s removed after success.", job_id)

    def reset_lock(self, job_id: int) -> None:
        """Forcefully clear a lock; used when a worker crashes."""

        with self._conn:
            self._conn.execute(
                """
                UPDATE retry_jobs
                SET locked_by = NULL,
                    locked_at = NULL
                WHERE id = ?
                """,
                (job_id,),
            )

    def delete(self, job_id: int) -> None:
        """Remove a job regardless of lock ownership."""

        with self._conn:
            self._conn.execute("DELETE FROM retry_jobs WHERE id = ?", (job_id,))

    def _initialize_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS retry_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_run_at TEXT NOT NULL,
                    error TEXT,
                    locked_by TEXT,
                    locked_at TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_retry_jobs_next_run
                ON retry_jobs(next_run_at, locked_by)
                """
            )

    @staticmethod
    def _serialize_payload(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, default=RetryQueueRepository._json_default)

    @staticmethod
    def _serialize_datetime(value: datetime) -> str:
        return value.replace(microsecond=0).isoformat()

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> RetryJob:
        return RetryJob(
            id=int(row["id"]),
            thread_id=row["thread_id"],
            payload=json.loads(row["payload"]),
            attempts=int(row["attempts"]),
            next_run_at=datetime.fromisoformat(row["next_run_at"]),
            error=row["error"],
        )


__all__ = ["RetryQueueRepository", "RetryQueueError"]
