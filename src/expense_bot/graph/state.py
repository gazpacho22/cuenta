"""Conversation and retry state models for the LangGraph expense bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from langchain_core.messages import BaseMessage

MAX_RECENT_MESSAGES = 6
MAX_RETRY_ATTEMPTS = 5


@dataclass(slots=True)
class AttachmentRef:
    """Reference to a receipt or supporting document stored in ERPNext."""

    file_url: str
    caption: str | None = None


@dataclass(slots=True)
class AccountMatch:
    """Finalized ledger match surfaced to the user and stored for audit."""

    account_code: str
    display_name: str
    confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("AccountMatch confidence must be between 0 and 1.")


@dataclass(slots=True)
class AccountCandidate:
    """Potential ledger match ranked by the LLM/tooling layer."""

    account_name: str
    account_code: str
    confidence: float
    reason: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("AccountCandidate confidence must be between 0 and 1.")


@dataclass(slots=True)
class JournalEntryResult:
    """Lightweight representation of an ERPNext journal entry response."""

    journal_entry_id: str
    posting_date: date
    voucher_no: str
    link: str | None = None


@dataclass(slots=True)
class ExpenseDraft:
    """Structured snapshot of an expense extracted from the conversation."""

    amount: Decimal
    currency: str
    debit_account: AccountMatch
    credit_account: AccountMatch
    posting_date: date
    narration: str
    attachments: list[AttachmentRef] = field(default_factory=list)
    source_message_id: str | None = None

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError("Expense amount must be greater than zero.")
        if len(self.narration) > 500:
            raise ValueError("Narration cannot exceed 500 characters.")


@dataclass(slots=True)
class RetryJob:
    """Represents a pending ERPNext submission retry stored in SQLite."""

    thread_id: str
    payload: dict[str, Any]
    next_run_at: datetime
    attempts: int = 0
    id: int | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.attempts < 0:
            raise ValueError("Retry attempts cannot be negative.")
        if self.attempts > MAX_RETRY_ATTEMPTS:
            raise ValueError(
                f"Retry attempts cannot exceed {MAX_RETRY_ATTEMPTS} per policy."
            )

    @property
    def is_exhausted(self) -> bool:
        """Return True when the retry budget is exhausted."""
        return self.attempts >= MAX_RETRY_ATTEMPTS


def _default_thread_id() -> str:
    return f"studio-{uuid4().hex}"


@dataclass(slots=True)
class ConversationState:
    """LangGraph checkpoint state for a Telegram chat thread."""

    thread_id: str = field(default_factory=_default_thread_id)
    messages: list[BaseMessage] = field(default_factory=list)
    conversation_summary: str | None = None
    expense_draft: ExpenseDraft | None = None
    clarifications_needed: list[str] = field(default_factory=list)
    account_candidates: list[AccountCandidate] = field(default_factory=list)
    confirmation_status: Literal["pending", "approved", "rejected"] = "pending"
    erpnext_submission: JournalEntryResult | None = None
    error_log: list[str] = field(default_factory=list)
    pending_message: str | None = None
    pending_message_id: str | None = None
    pending_user_id: int | None = None
    chart_of_accounts_override: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        self.messages = list(self.messages)[-MAX_RECENT_MESSAGES:]

    def append_message(self, message: BaseMessage) -> None:
        """Append a message while enforcing the rolling window limit."""
        self.messages.append(message)
        if len(self.messages) > MAX_RECENT_MESSAGES:
            self.messages = self.messages[-MAX_RECENT_MESSAGES:]

    def record_error(self, message: str) -> None:
        """Add a human-readable error entry."""
        if message:
            self.error_log.append(message)


__all__ = [
    "AccountCandidate",
    "AccountMatch",
    "AttachmentRef",
    "ConversationState",
    "ExpenseDraft",
    "JournalEntryResult",
    "MAX_RECENT_MESSAGES",
    "MAX_RETRY_ATTEMPTS",
    "RetryJob",
]
