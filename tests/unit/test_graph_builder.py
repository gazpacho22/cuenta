"""Unit tests for the LangGraph builder wiring."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Sequence

import pytest

from expense_bot.config import Settings
from expense_bot.graph import AccountMatch, ConversationState, ExpenseDraft
from expense_bot.graph.builder import ENTRY_NODE, build_state_graph, create_sqlite_saver


def _make_settings(
    tmp_path: Path,
    *,
    allowed_users: Sequence[int] | None = None,
) -> Settings:
    """Return a fully-populated Settings instance for tests."""

    allowlist = ",".join(str(user_id) for user_id in allowed_users or [])

    return Settings(
        TELEGRAM_TOKEN="123:ABC",
        TELEGRAM_WEBHOOK_SECRET="secret",
        ERP_BASE_URL="https://erp.example.com",
        ERP_API_KEY="erp-key",
        ERP_API_SECRET="erp-secret",
        DEFAULT_COMPANY="Cuenta HQ",
        DEFAULT_CURRENCY="USD",
        OPENAI_API_KEY="sk-test",
        OPENAI_MODEL="gpt-test",
        CHECKPOINT_DB=tmp_path / "graph.sqlite",
        RETRY_DB=tmp_path / "retry.sqlite",
        LOG_LEVEL="INFO",
        TELEGRAM_ALLOWED_USERS=allowlist,
    )


class _FakeChartTool:
    """Minimal chart tool stub to avoid real ERPNext calls in tests."""

    def __init__(self, accounts: Sequence[dict[str, str]] | None = None) -> None:
        self._accounts = [dict(row) for row in accounts or []]

    def invoke(self, *_: object, **__: object) -> dict[str, object]:
        return {"accounts": list(self._accounts)}


def test_create_sqlite_saver_initializes_database(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "checkpoints.sqlite"
    settings = _make_settings(tmp_path)

    saver = create_sqlite_saver(db_path=db_path, settings=settings)
    try:
        assert db_path.exists()
        saver.setup()
        cursor = saver.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'"
        )
        assert cursor.fetchone() == ("checkpoints",)
    finally:
        saver.conn.close()


def test_build_state_graph_uses_settings_checkpoint(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)

    graph = build_state_graph(settings=settings)
    try:
        assert ENTRY_NODE in graph.builder.nodes
        database_rows = graph.checkpointer.conn.execute("PRAGMA database_list").fetchall()
        db_files = {Path(row[2]).resolve() for row in database_rows if row[2]}
        assert settings.checkpoint_db.resolve() in db_files
    finally:
        graph.checkpointer.conn.close()


def test_build_state_graph_accepts_custom_checkpointer(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    external = create_sqlite_saver(
        db_path=tmp_path / "external.sqlite", settings=settings
    )

    graph = build_state_graph(settings=settings, checkpointer=external)
    assert graph.checkpointer is external
    graph.checkpointer.conn.close()


def test_capture_flow_parses_and_resolves_accounts(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    accounts = [
        {"account_code": "5110", "account_name": "Taxi Expense - HQ"},
        {"account_code": "1000", "account_name": "Cash - HQ"},
    ]
    checkpointer = create_sqlite_saver(settings=settings)
    try:
        graph = build_state_graph(
            settings=settings,
            checkpointer=checkpointer,
            chart_tool=_FakeChartTool(accounts),
        )
        state = ConversationState(thread_id="chat:42")
        state.pending_message = "Paid $10 cash for taxi"
        state.pending_message_id = "99"
        state.pending_user_id = 111
        config = {
            "configurable": {
                "thread_id": state.thread_id,
            }
        }

        result = graph.invoke(state, config=config)
    finally:
        checkpointer.conn.close()

    updated = ConversationState(**result)
    assert updated.expense_draft is not None
    assert updated.expense_draft.debit_account.account_code == "5110"
    assert updated.expense_draft.credit_account.account_code == "1000"
    assert updated.confirmation_status == "pending"
    assert updated.clarifications_needed == []
    assert len(updated.messages) == 1


def test_confirmation_flow_respects_pending_draft(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    checkpointer = create_sqlite_saver(settings=settings)
    try:
        graph = build_state_graph(
            settings=settings,
            checkpointer=checkpointer,
            chart_tool=_FakeChartTool([]),
        )
        draft = ExpenseDraft(
            amount=Decimal("10"),
            currency="USD",
            debit_account=AccountMatch("5110", "Taxi Expense - HQ", 0.99),
            credit_account=AccountMatch("1000", "Cash - HQ", 0.98),
            posting_date=date.today(),
            narration="Paid $10 cash for taxi",
        )
        state = ConversationState(
            thread_id="chat:confirm",
            expense_draft=draft,
            confirmation_status="pending",
        )
        state.pending_message = "confirm"
        state.pending_user_id = 111
        config = {
            "configurable": {
                "thread_id": state.thread_id,
            }
        }

        result = graph.invoke(state, config=config)
    finally:
        checkpointer.conn.close()

    updated = ConversationState(**result)
    assert updated.confirmation_status == "approved"
    assert updated.expense_draft is not None


def test_entry_node_enforces_authorization(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, allowed_users=[999])
    checkpointer = create_sqlite_saver(settings=settings)
    try:
        graph = build_state_graph(
            settings=settings,
            checkpointer=checkpointer,
            chart_tool=_FakeChartTool([]),
        )
        state = ConversationState(thread_id="chat:blocked")
        state.pending_message = "Paid $10 cash for taxi"
        state.pending_user_id = 111
        config = {
            "configurable": {
                "thread_id": state.thread_id,
            }
        }

        with pytest.raises(PermissionError):
            graph.invoke(state, config=config)
    finally:
        checkpointer.conn.close()
