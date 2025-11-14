"""Unit tests for ConversationLoggingHooks wiring."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from expense_bot.graph.state import AccountCandidate, AccountMatch, ConversationState, ExpenseDraft
from expense_bot.integrations.logging import ConversationLoggingHooks, ExpenseAttemptLogger


@pytest.fixture
def logging_hooks(tmp_path: Path):
    """Provide ConversationLoggingHooks backed by a temporary SQLite database."""

    database = tmp_path / "expense_attempts.sqlite"
    logger = ExpenseAttemptLogger(database)
    hooks = ConversationLoggingHooks(logger)
    yield hooks, database
    logger.close()


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


def _build_state(thread_id: str = "chat:200") -> ConversationState:
    draft = ExpenseDraft(
        amount=Decimal("10.00"),
        currency="USD",
        debit_account=AccountMatch(
            account_code="5110",
            display_name="Taxi Expense - HQ",
            confidence=0.99,
        ),
        credit_account=AccountMatch(
            account_code="1000",
            display_name="Cash - HQ",
            confidence=0.97,
        ),
        posting_date=date(2025, 11, 6),
        narration="Paid $10 cash for taxi",
    )
    candidates = [
        AccountCandidate(
            account_name="Taxi Expense - HQ",
            account_code="5110",
            confidence=0.82,
            reason="Matched alias taxi expense",
        )
    ]
    return ConversationState(
        thread_id=thread_id,
        expense_draft=draft,
        clarifications_needed=["receipt"],
        account_candidates=candidates,
        conversation_summary="Taxi expense capture",
    )


def test_log_preview_includes_state_snapshot(logging_hooks: tuple[ConversationLoggingHooks, Path]) -> None:
    hooks, database = logging_hooks
    state = _build_state()

    hooks.log_preview(
        attempt_id="attempt-301",
        thread_id=None,
        telegram_user_id=77,
        telegram_message_id=555,
        preview_json={"summary": "Paid $10 cash for taxi"},
        state=state,
    )

    rows = _fetch_rows(database)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "previewed"
    payload = _decode_preview_json(row["preview_json"])
    assert payload["summary"] == "Paid $10 cash for taxi"
    snapshot = payload["state_snapshot"]
    assert snapshot["thread_id"] == "chat:200"
    assert snapshot["expense_draft"]["amount"] == "10.00"
    assert snapshot["clarifications_needed"] == ["receipt"]


def test_log_confirmation_records_doc_id(logging_hooks: tuple[ConversationLoggingHooks, Path]) -> None:
    hooks, database = logging_hooks

    hooks.log_confirmation(
        attempt_id="attempt-302",
        thread_id="chat:300",
        telegram_user_id=80,
        telegram_message_id=777,
        preview_json={"summary": "Paid $15 cash for taxi"},
        erpnext_doc_id="ERP-JE-9001",
    )

    rows = _fetch_rows(database)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "confirmed"
    assert row["erpnext_doc_id"] == "ERP-JE-9001"


def test_log_retry_and_cancel(logging_hooks: tuple[ConversationLoggingHooks, Path]) -> None:
    hooks, database = logging_hooks
    hooks.log_retry_enqueued(
        attempt_id="attempt-303",
        thread_id="chat:400",
        telegram_user_id=81,
        telegram_message_id=111,
        preview_json={"summary": "Paid $20 cash for taxi"},
        resolution="queued_for_retry",
    )
    hooks.log_cancellation(
        attempt_id="attempt-303",
        thread_id="chat:400",
        telegram_user_id=81,
        telegram_message_id=112,
        reason="user_cancelled",
        preview_json={"summary": "Cancelled expense"},
    )

    rows = _fetch_rows(database)
    assert len(rows) == 2
    assert rows[0]["status"] == "retrying"
    assert rows[1]["status"] == "cancelled"


def test_posted_latency_defaults_to_confirmation_delta(
    logging_hooks: tuple[ConversationLoggingHooks, Path]
) -> None:
    hooks, database = logging_hooks
    confirm_at = datetime(2025, 11, 7, 12, 0, 0, tzinfo=UTC)
    posted_at = confirm_at + timedelta(milliseconds=2500)

    hooks.log_confirmation(
        attempt_id="attempt-304",
        thread_id="chat:500",
        telegram_user_id=90,
        telegram_message_id=333,
        preview_json={"summary": "Paid $22 cash for wifi"},
        confirmed_at=confirm_at,
    )
    hooks.log_posted(
        attempt_id="attempt-304",
        thread_id="chat:500",
        telegram_user_id=90,
        telegram_message_id=333,
        preview_json={"summary": "Paid $22 cash for wifi"},
        erpnext_doc_id="ERP-JE-42",
        completed_at=posted_at,
    )

    rows = _fetch_rows(database)
    assert len(rows) == 2
    assert rows[-1]["status"] == "posted"
    assert rows[-1]["latency_ms"] == 2500, "Latency should reflect confirmation-to-post delta."
