"""Unit tests for the Telegram expense handlers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from expense_bot.graph.state import (
    AccountMatch,
    ExpenseDraft,
    JournalEntryResult,
)
from expense_bot.integrations.telegram import (
    handle_confirmation,
    handle_expense_message,
    set_state_graph,
)


@pytest.fixture(name="anyio_backend")
def _anyio_backend() -> str:
    return "asyncio"


def _make_message(
    text: str,
    *,
    chat_id: int = 123,
    user_id: int = 99,
    message_id: int = 42,
) -> SimpleNamespace:
    message = SimpleNamespace(
        message_id=message_id,
        text=text,
        chat=SimpleNamespace(id=chat_id),
        from_user=SimpleNamespace(id=user_id),
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(
        message=message,
        edited_message=None,
        callback_query=None,
        effective_chat=message.chat,
        effective_user=message.from_user,
        effective_message=message,
    )
    return update


def _make_context() -> SimpleNamespace:
    return SimpleNamespace(
        application=SimpleNamespace(bot_data={}, stop=None),
        bot=SimpleNamespace(send_message=AsyncMock()),
    )


def _build_draft() -> ExpenseDraft:
    debit = AccountMatch("5110", "Taxi Expense - HQ", 0.95)
    credit = AccountMatch("1000", "Cash - HQ", 0.9)
    return ExpenseDraft(
        amount=Decimal("10"),
        currency="USD",
        debit_account=debit,
        credit_account=credit,
        posting_date=date(2025, 1, 1),
        narration="Paid $10 cash for taxi",
    )


class FakeGraph:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result

    def invoke(self, state: object, config: dict[str, dict[str, str]]) -> dict[str, object]:
        return self.result



def _expense_result(
    *,
    thread_id: str = "telegram:123",
    confirmation_status: str = "pending",
    submission: JournalEntryResult | None = None,
) -> dict[str, object]:
    draft = _build_draft()
    return {
        "thread_id": thread_id,
        "messages": [],
        "conversation_summary": None,
        "expense_draft": draft,
        "clarifications_needed": [],
        "account_candidates": [],
        "confirmation_status": confirmation_status,
        "erpnext_submission": submission,
        "error_log": [],
        "pending_message": None,
        "pending_message_id": None,
        "pending_user_id": 99,
        "chart_of_accounts_override": None,
    }


@pytest.mark.anyio()
async def test_handle_expense_message_sends_preview_and_logs() -> None:
    update = _make_message("Paid $10 cash for taxi")
    context = _make_context()
    graph = FakeGraph(_expense_result())
    set_state_graph(context.application, graph)

    await handle_expense_message(update, context)

    update.effective_message.reply_text.assert_awaited_once()
    text = update.effective_message.reply_text.await_args.args[0]
    assert "Amount: 10.00 USD" in text
    assert "Debit account" in text
    assert "confirm" in text.lower()


@pytest.mark.anyio()
async def test_handle_confirmation_logs_erpnext_reference() -> None:
    update = _make_message("confirm")
    context = _make_context()
    submission = JournalEntryResult(
        journal_entry_id="ERP-JE-0001",
        posting_date=date(2025, 1, 1),
        voucher_no="V-0001",
        link="https://erp.example.com/app/journal-entry/ERP-JE-0001",
    )
    graph = FakeGraph(
        _expense_result(confirmation_status="approved", submission=submission)
    )
    set_state_graph(context.application, graph)

    await handle_confirmation(update, context)

    text = update.effective_message.reply_text.await_args.args[0]
    assert "ERPNext reference" in text
