"""Unit tests for graph node helpers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from expense_bot.graph import ConversationState, ExpenseDraft, AccountMatch
from expense_bot.graph.nodes import (
    apply_confirmation_decision,
    cancel_expense_attempt,
    parse_expense_message,
    select_accounts_for_draft,
)


def test_parse_expense_message_populates_draft_when_message_complete() -> None:
    state = ConversationState(thread_id="chat:42")

    parsed = parse_expense_message(
        state,
        message="Paid $10 cash for taxi",
        default_currency="USD",
        source_message_id="99",
    )

    assert parsed.amount == Decimal("10")
    assert state.clarifications_needed == []
    assert state.expense_draft is not None
    assert state.expense_draft.amount == Decimal("10")
    assert state.expense_draft.currency == "USD"
    assert state.expense_draft.narration == "Paid $10 cash for taxi"
    assert state.expense_draft.source_message_id == "99"
    assert state.expense_draft.debit_account.display_name.lower().startswith("taxi")
    assert state.confirmation_status == "pending"


def test_parse_expense_message_marks_missing_fields_when_incomplete() -> None:
    state = ConversationState(thread_id="chat:99")

    parsed = parse_expense_message(
        state,
        message="Paid cash for taxi",
        default_currency="USD",
    )

    assert "amount" in state.clarifications_needed
    assert parsed.amount is None
    assert state.expense_draft is None


def _chart_of_accounts() -> list[dict[str, str]]:
    return [
        {
            "account_code": "5110",
            "account_name": "Taxi Expense - HQ",
            "aliases": ["Taxi", "Ground Travel"],
        },
        {"account_code": "1000", "account_name": "Cash - HQ", "aliases": ["Cash"]},
        {"account_code": "2210", "account_name": "Accounts Payable - HQ"},
    ]


def test_select_accounts_for_draft_auto_selects_high_confidence_matches() -> None:
    state = ConversationState(thread_id="chat:auto")
    parse_expense_message(state, message="Paid $15 cash for taxi", default_currency="USD")

    result = select_accounts_for_draft(
        state,
        chart_of_accounts=_chart_of_accounts(),
    )

    assert state.clarifications_needed == []
    assert state.account_candidates == []
    assert state.expense_draft is not None
    assert state.expense_draft.debit_account.account_code == "5110"
    assert state.expense_draft.credit_account.account_code == "1000"
    assert result["debit"][0].account_code == "5110"


def test_select_accounts_for_draft_requests_clarification_when_low_confidence() -> None:
    state = ConversationState(thread_id="chat:manual")
    parse_expense_message(state, message="Paid $15 cash for taxi", default_currency="USD")

    ambiguous_accounts = [
        {"account_code": "5200", "account_name": "Ground Transportation"},
        {"account_code": "1200", "account_name": "Operations Wallet"},
    ]

    selection = select_accounts_for_draft(
        state,
        chart_of_accounts=ambiguous_accounts,
        auto_select_threshold=0.99,
        min_candidate_confidence=0.2,
        max_suggestions=3,
    )

    assert state.clarifications_needed == ["debit_account", "credit_account"]
    assert state.account_candidates == selection["debit"]

    # Provide explicit user selections on the second pass.
    select_accounts_for_draft(
        state,
        chart_of_accounts=ambiguous_accounts,
        auto_select_threshold=0.99,
        min_candidate_confidence=0.2,
        debit_choice=selection["debit"][0].account_code,
        credit_choice=selection["credit"][0].account_code,
    )

    assert state.clarifications_needed == []
    assert state.expense_draft is not None
    assert state.expense_draft.debit_account.account_code == selection["debit"][0].account_code
    assert state.expense_draft.credit_account.account_code == selection["credit"][0].account_code


def test_select_accounts_for_draft_requires_existing_draft() -> None:
    state = ConversationState(thread_id="chat:empty")

    with pytest.raises(ValueError):
        select_accounts_for_draft(state, chart_of_accounts=_chart_of_accounts())


def test_apply_confirmation_decision_updates_status() -> None:
    state = ConversationState(
        thread_id="chat:confirm",
        expense_draft=ExpenseDraft(
            amount=Decimal("10"),
            currency="USD",
            debit_account=AccountMatch("5110", "Taxi Expense - HQ", 0.99),
            credit_account=AccountMatch("1000", "Cash - HQ", 0.98),
            posting_date=date.today(),
            narration="Paid $10 cash for taxi",
        ),
    )

    assert apply_confirmation_decision(state, user_input="Confirm") == "approved"
    assert state.confirmation_status == "approved"

    assert apply_confirmation_decision(state, user_input="edit") == "edit"
    assert state.confirmation_status == "pending"

    assert apply_confirmation_decision(state, user_input="cancel") == "rejected"
    assert state.confirmation_status == "rejected"

    assert apply_confirmation_decision(state, user_input="nonsense") == "invalid"
    assert state.confirmation_status == "pending"


def test_cancel_expense_attempt_clears_state_and_logs_reason() -> None:
    draft = ExpenseDraft(
        amount=Decimal("25"),
        currency="USD",
        debit_account=AccountMatch("7000", "Meals - HQ", 0.7),
        credit_account=AccountMatch("1000", "Cash - HQ", 0.8),
        posting_date=date.today(),
        narration="Lunch with client",
    )
    state = ConversationState(
        thread_id="chat:cancel",
        expense_draft=draft,
        clarifications_needed=["debit_account"],
        account_candidates=[],
    )

    cancel_expense_attempt(state, reason="User sent cancel command.")

    assert state.expense_draft is None
    assert state.confirmation_status == "rejected"
    assert state.account_candidates == []
    assert state.clarifications_needed == []
    assert "User sent cancel command." in state.error_log
