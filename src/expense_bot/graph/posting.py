"""Helpers for posting confirmed expenses to ERPNext."""

from __future__ import annotations

from typing import Any, Mapping

from expense_bot.graph.state import (
    ConversationState,
    ExpenseDraft,
    JournalEntryResult,
)
from expense_bot.integrations.erpnext import ERPNextClient


class ExpensePostingError(RuntimeError):
    """Raised when the conversation state is not ready for ERPNext posting."""


def post_confirmed_expense(
    state: ConversationState,
    *,
    erp_client: ERPNextClient,
    extra_payload: Mapping[str, Any] | None = None,
) -> JournalEntryResult:
    """
    Submit the confirmed expense draft to ERPNext and store the resulting metadata.

    Args:
        state: Current conversation state, expected to contain an approved draft.
        erp_client: Configured ERPNext client instance.
        extra_payload: Optional fields to merge into the journal entry payload.

    Returns:
        JournalEntryResult with the ERPNext document identifiers.

    Raises:
        ExpensePostingError: If no draft is available or confirmation is missing.
        ERPNextClientError: Bubble up HTTP/ERPNext failures from the client.
    """

    draft = state.expense_draft
    if draft is None:
        raise ExpensePostingError("ConversationState is missing an expense draft.")
    if state.confirmation_status != "approved":
        raise ExpensePostingError(
            "Expense cannot be posted before the user approves the summary."
        )

    payload = _build_journal_entry_payload(draft, extra_payload=extra_payload)
    result = erp_client.post_journal_entry(payload)
    state.erpnext_submission = result
    return result


def _build_journal_entry_payload(
    draft: ExpenseDraft,
    *,
    extra_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    amount_value = float(draft.amount)
    payload: dict[str, Any] = {
        "posting_date": draft.posting_date.isoformat(),
        "user_remark": draft.narration,
        "accounts": [
            {
                "account": draft.debit_account.account_code,
                "debit_in_account_currency": amount_value,
                "credit_in_account_currency": 0.0,
            },
            {
                "account": draft.credit_account.account_code,
                "debit_in_account_currency": 0.0,
                "credit_in_account_currency": amount_value,
            },
        ],
    }
    if extra_payload:
        payload.update(extra_payload)
    return payload


__all__ = ["ExpensePostingError", "post_confirmed_expense"]
