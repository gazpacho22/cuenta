"""Unit tests driving the expense_attempts logging writer contract."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def expense_logger(tmp_path: Path):
    """Instantiate the logger implementation or skip until it exists."""

    logging_module = pytest.importorskip("expense_bot.integrations.logging")
    database = tmp_path / "expense_attempts.sqlite"
    logger = logging_module.ExpenseAttemptLogger(database)
    yield logger, database
    close = getattr(logger, "close", None)
    if callable(close):
        close()


def _fetch_rows(database: Path) -> list[sqlite3.Row]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        cursor = connection.execute(
            """
            SELECT attempt_id, thread_id, status, resolution, erpnext_doc_id, preview_json, latency_ms
            FROM expense_attempts
            ORDER BY id
            """
        )
        return cursor.fetchall()
    finally:
        connection.close()


def _decode_preview_json(value: Any) -> dict[str, Any]:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, dict):
        return value
    raise TypeError(f"preview_json stored with unsupported type: {type(value)!r}")


def test_record_event_serializes_preview_summary(expense_logger: tuple[Any, Path]) -> None:
    """Ensure preview_json survives round-trip serialization with nested data."""

    logger, database = expense_logger
    preview_payload = {
        "summary": "Paid $12 cash for taxi",
        "amount": {"value": 12, "currency": "USD"},
        "accounts": ["Travel Expense - HQ", "Cash - HQ"],
    }
    logger.record_event(
        attempt_id="attempt-200",
        thread_id="chat:123456",
        telegram_user_id=99,
        telegram_message_id=555,
        status="previewed",
        resolution="pending_user_confirmation",
        preview_json=preview_payload,
    )

    rows = _fetch_rows(database)
    assert len(rows) == 1, "Expected a single preview row."
    stored_preview = _decode_preview_json(rows[0]["preview_json"])
    assert stored_preview["summary"] == "Paid $12 cash for taxi"
    assert stored_preview["amount"]["value"] == 12
    assert stored_preview["accounts"] == ["Travel Expense - HQ", "Cash - HQ"]


def test_status_transitions_append_rows(expense_logger: tuple[Any, Path]) -> None:
    """Verify each status transition is appended with matching resolution metadata."""

    logger, database = expense_logger
    base_payload = {
        "attempt_id": "attempt-201",
        "thread_id": "chat:654321",
        "telegram_user_id": 42,
        "telegram_message_id": 777,
        "preview_json": {"summary": "Paid $20 cash for luggage"},
    }

    logger.record_event(
        **base_payload, status="previewed", resolution="pending_user_confirmation"
    )
    logger.record_event(**base_payload, status="confirmed", resolution="user_confirmed")
    logger.record_event(
        **base_payload,
        status="posted",
        resolution="posted",
        erpnext_doc_id="JE-9001",
    )

    rows = _fetch_rows(database)
    assert len(rows) == 3, "Each call must append a new expense_attempt row."

    statuses = [row["status"] for row in rows]
    resolutions = [row["resolution"] for row in rows]

    assert statuses == ["previewed", "confirmed", "posted"], "Status history mismatch."
    assert resolutions == [
        "pending_user_confirmation",
        "user_confirmed",
        "posted",
    ], "Resolution history mismatch."
    assert rows[-1]["erpnext_doc_id"] == "JE-9001", "Posted entry lost ERPNext reference."


def test_posted_entry_captures_latency(expense_logger: tuple[Any, Path]) -> None:
    """latency_ms should persist for monitoring (SC-002 / FR-011)."""

    logger, database = expense_logger
    logger.record_event(
        attempt_id="attempt-202",
        thread_id="chat:999111",
        telegram_user_id=55,
        telegram_message_id=888,
        status="posted",
        resolution="posted",
        preview_json={"summary": "Paid $30 cash for hotel"},
        latency_ms=1425,
    )

    rows = _fetch_rows(database)
    assert len(rows) == 1, "Posted entry should appear once."
    assert rows[0]["latency_ms"] == 1425, "latency_ms must be stored for posted entries."
