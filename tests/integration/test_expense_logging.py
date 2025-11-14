"""Integration coverage for the expense_attempts logging writer."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def expense_logger(tmp_path: Path):
    """Provide a logger instance backed by a temporary SQLite database."""

    logging_module = pytest.importorskip("expense_bot.integrations.logging")
    database = tmp_path / "expense_attempts.sqlite"
    logger = logging_module.ExpenseAttemptLogger(database)
    yield logger, database
    close = getattr(logger, "close", None)
    if callable(close):
        close()


def _fetch_attempt_rows(database: Path, attempt_id: str) -> list[sqlite3.Row]:
    """Return raw rows for an attempt so thread/resolution columns can be asserted."""

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        cursor = connection.execute(
            """
            SELECT attempt_id, thread_id, status, resolution, preview_json
            FROM expense_attempts
            WHERE attempt_id = ?
            ORDER BY id
            """,
            (attempt_id,),
        )
        return cursor.fetchall()
    finally:
        connection.close()


def _log_edit(
    logger: Any,
    *,
    attempt_id: str,
    thread_id: str,
    telegram_user_id: int,
    telegram_message_id: int,
    summary: str,
) -> None:
    """Helper to append an edited entry using the shared logger contract."""

    logger.record_event(
        attempt_id=attempt_id,
        thread_id=thread_id,
        telegram_user_id=telegram_user_id,
        telegram_message_id=telegram_message_id,
        status="edited",
        resolution="user_edited",
        preview_json={"summary": summary},
    )


def test_multiple_edits_preserve_thread_and_resolution(expense_logger: tuple[Any, Path]) -> None:
    """Simulate multiple edits and ensure thread_id + resolution persist per FR-011."""

    logger, database = expense_logger
    attempt_id = "attempt-777"
    thread_id = "chat:998877"
    preview_payload = {
        "attempt_id": attempt_id,
        "thread_id": thread_id,
        "telegram_user_id": 44,
        "telegram_message_id": 99,
        "status": "previewed",
        "resolution": "pending_user_confirmation",
        "preview_json": {"summary": "Paid $12 cash for taxi"},
    }

    logger.record_event(**preview_payload)
    _log_edit(
        logger,
        attempt_id=attempt_id,
        thread_id=thread_id,
        telegram_user_id=44,
        telegram_message_id=100,
        summary="Paid $18 cash for taxi",
    )
    _log_edit(
        logger,
        attempt_id=attempt_id,
        thread_id=thread_id,
        telegram_user_id=44,
        telegram_message_id=101,
        summary="Paid $18 cash for taxi (airport)",
    )

    rows = _fetch_attempt_rows(database, attempt_id)
    assert len(rows) == 3, "Preview plus two edits should yield three log rows."

    statuses = [row["status"] for row in rows]
    assert statuses == ["previewed", "edited", "edited"], "Unexpected status sequence."

    for row in rows:
        assert row["thread_id"] == thread_id, "thread_id linkage must persist across entries."
        assert row["resolution"], "resolution cannot be blank."

    edited_rows = [row for row in rows if row["status"] == "edited"]
    assert {row["resolution"] for row in edited_rows} == {"user_edited"}
    assert edited_rows[-1]["preview_json"] is not None, "preview_json should persist for edits."
