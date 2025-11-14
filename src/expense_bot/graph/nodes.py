"""LangGraph node helpers for the expense capture conversation flow."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Mapping, Sequence

from expense_bot import get_logger
from expense_bot.graph.state import (
    AccountCandidate,
    AccountMatch,
    ConversationState,
    ExpenseDraft,
)
from expense_bot.parsing import ParsedExpense, parse_expense_text, rank_account_candidates

LOGGER = get_logger("graph.nodes")

AccountRole = Literal["debit_account", "credit_account"]

AUTO_SELECTION_THRESHOLD = 0.85
MAX_ACCOUNT_SUGGESTIONS = 5
MIN_CANDIDATE_CONFIDENCE = 0.5

CONFIRM_COMMANDS = {"confirm", "confirmed", "approve", "approved", "yes", "y"}
CANCEL_COMMANDS = {"cancel", "cancelled", "reject", "rejected", "stop", "no", "n"}
EDIT_COMMANDS = {"edit", "change", "update", "revise"}

ROLE_LABELS: dict[AccountRole, str] = {
    "debit_account": "Debit account",
    "credit_account": "Credit account",
}


def parse_expense_message(
    state: ConversationState,
    *,
    message: str,
    default_currency: str,
    source_message_id: str | None = None,
) -> ParsedExpense:
    """Parse the latest Telegram message into a structured draft."""

    parsed = parse_expense_text(
        message,
        default_currency=default_currency,
        source_message_id=source_message_id,
    )
    state.account_candidates = []
    state.erpnext_submission = None
    state.clarifications_needed = sorted(parsed.missing_fields)

    if parsed.missing_fields:
        LOGGER.debug(
            "parse_expense_message missing fields: %s", sorted(parsed.missing_fields)
        )
        state.expense_draft = None
        return parsed

    if parsed.amount is None or parsed.debit_hint is None or parsed.credit_hint is None:
        # Safety guard: missing_fields would have captured this, but defend anyway.
        LOGGER.warning(
            "parse_expense_message missing critical data despite empty flags (fields=%s)",
            sorted(parsed.missing_fields),
        )
        state.clarifications_needed = ["amount", "debit_account", "credit_account"]
        state.expense_draft = None
        return parsed

    resolved_currency = parsed.currency or default_currency
    draft = ExpenseDraft(
        amount=parsed.amount,
        currency=resolved_currency,
        debit_account=_placeholder_account(parsed.debit_hint, "debit_account"),
        credit_account=_placeholder_account(parsed.credit_hint, "credit_account"),
        posting_date=date.today(),
        narration=parsed.narration,
        source_message_id=parsed.source_message_id,
    )
    state.expense_draft = draft
    state.confirmation_status = "pending"
    return parsed


def select_accounts_for_draft(
    state: ConversationState,
    *,
    chart_of_accounts: Sequence[Mapping[str, Any]] | None,
    auto_select_threshold: float = AUTO_SELECTION_THRESHOLD,
    min_candidate_confidence: float = MIN_CANDIDATE_CONFIDENCE,
    max_suggestions: int = MAX_ACCOUNT_SUGGESTIONS,
    debit_choice: str | None = None,
    credit_choice: str | None = None,
) -> dict[str, list[AccountCandidate]]:
    """Resolve debit and credit accounts using chart-of-accounts data."""

    if state.expense_draft is None:
        raise ValueError("Cannot resolve accounts without an expense draft.")
    if not (0.0 < auto_select_threshold <= 1.0):
        raise ValueError("auto_select_threshold must be between 0 and 1.")
    if not (0.0 <= min_candidate_confidence <= 1.0):
        raise ValueError("min_candidate_confidence must be between 0 and 1.")
    if max_suggestions <= 0:
        raise ValueError("max_suggestions must be a positive integer.")

    ledger_rows: Sequence[Mapping[str, Any]] = chart_of_accounts or ()
    parsed = parse_expense_text(
        state.expense_draft.narration,
        default_currency=state.expense_draft.currency,
        source_message_id=state.expense_draft.source_message_id,
    )

    debit_candidates = _rank_candidates(
        hint=parsed.debit_hint,
        keywords=parsed.keywords,
        accounts=ledger_rows,
        limit=max_suggestions,
        min_confidence=min_candidate_confidence,
    )
    credit_candidates = _rank_candidates(
        hint=parsed.credit_hint,
        keywords=parsed.keywords,
        accounts=ledger_rows,
        limit=max_suggestions,
        min_confidence=min_candidate_confidence,
    )

    unresolved: list[AccountRole] = []
    if not _resolve_account(
        state,
        role="debit_account",
        candidates=debit_candidates,
        auto_threshold=auto_select_threshold,
        user_choice=debit_choice,
    ):
        unresolved.append("debit_account")
    if not _resolve_account(
        state,
        role="credit_account",
        candidates=credit_candidates,
        auto_threshold=auto_select_threshold,
        user_choice=credit_choice,
    ):
        unresolved.append("credit_account")

    state.clarifications_needed = unresolved
    if unresolved:
        first_role = unresolved[0]
        state.account_candidates = (
            list(debit_candidates)
            if first_role == "debit_account"
            else list(credit_candidates)
        )
    else:
        state.account_candidates = []

    if unresolved and not ledger_rows:
        state.record_error(
            "Chart of accounts data is unavailable; unable to auto-select ledgers."
        )

    return {"debit": debit_candidates, "credit": credit_candidates}


def apply_confirmation_decision(
    state: ConversationState,
    *,
    user_input: str,
) -> Literal["approved", "rejected", "edit", "invalid"]:
    """Update confirmation status based on the user's reply."""

    normalized = (user_input or "").strip().lower()
    if not normalized:
        state.record_error("Confirmation input is required.")
        return "invalid"

    if normalized in CONFIRM_COMMANDS:
        if state.expense_draft is None:
            state.record_error("There is no expense draft to approve.")
            return "invalid"
        state.confirmation_status = "approved"
        return "approved"
    if normalized in CANCEL_COMMANDS:
        state.confirmation_status = "rejected"
        return "rejected"
    if normalized in EDIT_COMMANDS:
        state.confirmation_status = "pending"
        return "edit"

    state.record_error(
        f"'{user_input}' is not a valid confirmation command. "
        "Reply with confirm, edit, or cancel."
    )
    state.confirmation_status = "pending"
    return "invalid"


def cancel_expense_attempt(
    state: ConversationState,
    *,
    reason: str | None = None,
) -> None:
    """Clear the current draft and mark the attempt as cancelled."""

    state.expense_draft = None
    state.account_candidates = []
    state.clarifications_needed = []
    state.confirmation_status = "rejected"
    state.erpnext_submission = None
    if reason:
        state.record_error(reason)


def _placeholder_account(hint: str | None, role: AccountRole) -> AccountMatch:
    label = hint.strip() if hint else ROLE_LABELS[role]
    code = (hint or f"unresolved_{role}").strip().lower().replace(" ", "_")
    return AccountMatch(
        account_code=code or f"unresolved_{role}",
        display_name=label or ROLE_LABELS[role],
        confidence=0.0,
    )


def _rank_candidates(
    *,
    hint: str | None,
    keywords: Sequence[str],
    accounts: Sequence[Mapping[str, Any]],
    limit: int,
    min_confidence: float,
) -> list[AccountCandidate]:
    query_terms: list[str] = []
    if hint:
        query_terms.append(hint)
    query_terms.extend(keywords)
    if not query_terms:
        query_terms.append("expense")
    return rank_account_candidates(
        query_terms=query_terms,
        accounts=accounts,
        limit=limit,
        min_confidence=min_confidence,
    )


def _resolve_account(
    state: ConversationState,
    *,
    role: AccountRole,
    candidates: Sequence[AccountCandidate],
    auto_threshold: float,
    user_choice: str | None,
) -> bool:
    match: AccountCandidate | None = None
    if user_choice:
        match = _match_user_choice(candidates, user_choice)
    elif candidates and candidates[0].confidence >= auto_threshold:
        match = candidates[0]

    if match is None:
        return False

    account_match = AccountMatch(
        account_code=match.account_code,
        display_name=match.account_name,
        confidence=match.confidence,
    )
    if state.expense_draft is None:
        return False
    if role == "debit_account":
        state.expense_draft.debit_account = account_match
    else:
        state.expense_draft.credit_account = account_match
    LOGGER.debug(
        "Resolved %s to %s (confidence=%.2f)",
        role,
        match.account_code,
        match.confidence,
    )
    return True


def _match_user_choice(
    candidates: Sequence[AccountCandidate],
    choice: str | None,
) -> AccountCandidate | None:
    if not choice:
        return None
    normalized = choice.strip().lower()
    if not normalized:
        return None
    if normalized.isdigit():
        index = int(normalized) - 1
        if 0 <= index < len(candidates):
            return candidates[index]

    for candidate in candidates:
        if normalized in {
            candidate.account_code.lower(),
            candidate.account_name.lower(),
        }:
            return candidate
    return None


__all__ = [
    "apply_confirmation_decision",
    "cancel_expense_attempt",
    "parse_expense_message",
    "select_accounts_for_draft",
]
