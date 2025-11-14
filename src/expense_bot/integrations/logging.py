"""SQLite-backed expense_attempts audit logging writer."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from expense_bot import get_logger
from expense_bot.graph.state import (
    AccountCandidate,
    AccountMatch,
    AttachmentRef,
    ConversationState,
    ExpenseDraft,
    JournalEntryResult,
)

LOGGER = get_logger("integrations.logging")
_THREAD_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")


def generate_attempt_id(thread_id: str, *, now: datetime | None = None) -> str:
    """Return a thread-aware attempt identifier suitable for SQLite rows."""

    if not thread_id:
        raise ValueError("thread_id is required to generate an attempt_id.")
    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%d%H%M%S")
    slug = _THREAD_SLUG_RE.sub("-", thread_id).strip("-") or "thread"
    suffix = uuid4().hex[:6]
    return f"{slug}-{timestamp}-{suffix}"


@dataclass(slots=True)
class ExpenseAttemptLogEntry:
    """Typed representation of a single expense_attempts log row."""

    attempt_id: str
    thread_id: str
    status: str
    resolution: str
    telegram_user_id: int
    telegram_message_id: int
    preview_json: Mapping[str, Any]
    erpnext_doc_id: str | None = None
    latency_ms: int | None = None
    created_at: datetime | None = None


class ExpenseAttemptLogger:
    """Append-only writer that records conversational events for auditing."""

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

    def record_event(
        self,
        *,
        attempt_id: str,
        thread_id: str,
        telegram_user_id: int,
        telegram_message_id: int,
        status: str,
        resolution: str,
        preview_json: Mapping[str, Any] | None = None,
        erpnext_doc_id: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        """Persist an expense_attempt event without mutating prior history."""

        normalized_attempt = attempt_id.strip()
        normalized_thread = thread_id.strip()
        if not normalized_attempt:
            raise ValueError("attempt_id cannot be blank.")
        if not normalized_thread:
            raise ValueError("thread_id cannot be blank.")
        if not status:
            raise ValueError("status is required.")
        if not resolution:
            raise ValueError("resolution is required.")
        if latency_ms is not None and latency_ms < 0:
            raise ValueError("latency_ms cannot be negative.")

        payload = self._serialize_preview(preview_json or {})
        created_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO expense_attempts (
                    attempt_id,
                    thread_id,
                    telegram_user_id,
                    telegram_message_id,
                    status,
                    resolution,
                    erpnext_doc_id,
                    preview_json,
                    latency_ms,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_attempt,
                    normalized_thread,
                    int(telegram_user_id),
                    int(telegram_message_id),
                    status,
                    resolution,
                    erpnext_doc_id,
                    payload,
                    latency_ms,
                    created_at,
                ),
            )
        LOGGER.debug(
            "Recorded expense attempt event",
            extra={
                "attempt_id": normalized_attempt,
                "thread_id": normalized_thread,
                "status": status,
                "resolution": resolution,
            },
        )

    def _initialize_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS expense_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    telegram_message_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    erpnext_doc_id TEXT,
                    preview_json TEXT NOT NULL,
                    latency_ms INTEGER,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_expense_attempts_attempt
                ON expense_attempts(attempt_id, thread_id)
                """
            )

    @staticmethod
    def _serialize_preview(payload: Mapping[str, Any]) -> str:
        try:
            return json.dumps(
                payload, ensure_ascii=False, default=ExpenseAttemptLogger._json_default
            )
        except TypeError as exc:
            raise TypeError(f"preview_json contains non-serializable data: {exc}") from exc

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


class ConversationLoggingHooks:
    """Helper that exposes high-level logging methods for graph/Telegram events."""

    def __init__(self, attempt_logger: ExpenseAttemptLogger):
        self._attempt_logger = attempt_logger
        self._confirmation_events: dict[str, datetime] = {}

    def log_preview(
        self,
        *,
        attempt_id: str,
        thread_id: str | None,
        telegram_user_id: int,
        telegram_message_id: int,
        preview_json: Mapping[str, Any] | None = None,
        state: ConversationState | None = None,
    ) -> None:
        """Record a preview event prior to user confirmation."""

        payload = self._build_preview_payload(preview_json, state)
        self._record(
            attempt_id=attempt_id,
            thread_id=thread_id or (state.thread_id if state else None),
            telegram_user_id=telegram_user_id,
            telegram_message_id=telegram_message_id,
            status="previewed",
            resolution="pending_user_confirmation",
            preview_json=payload,
        )

    def log_confirmation(
        self,
        *,
        attempt_id: str,
        thread_id: str | None,
        telegram_user_id: int,
        telegram_message_id: int,
        preview_json: Mapping[str, Any] | None = None,
        state: ConversationState | None = None,
        resolution: str = "user_confirmed",
        erpnext_doc_id: str | None = None,
        confirmed_at: datetime | None = None,
    ) -> None:
        """Record that a user confirmed (or re-confirmed) the preview."""

        attempt_key = self._normalize_attempt_id(attempt_id)
        self._remember_confirmation(attempt_key, confirmed_at)
        payload = self._build_preview_payload(preview_json, state)
        self._record(
            attempt_id=attempt_id,
            thread_id=thread_id or (state.thread_id if state else None),
            telegram_user_id=telegram_user_id,
            telegram_message_id=telegram_message_id,
            status="confirmed",
            resolution=resolution,
            preview_json=payload,
            erpnext_doc_id=erpnext_doc_id,
        )

    def log_posted(
        self,
        *,
        attempt_id: str,
        thread_id: str | None,
        telegram_user_id: int,
        telegram_message_id: int,
        preview_json: Mapping[str, Any] | None = None,
        state: ConversationState | None = None,
        erpnext_doc_id: str | None,
        latency_ms: int | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        """Record a successful ERPNext posting so doc identifiers are audit-ready."""

        attempt_key = self._normalize_attempt_id(attempt_id)
        resolved_latency = latency_ms
        if resolved_latency is None:
            resolved_latency = self._calculate_latency(attempt_key, completed_at)
        payload = self._build_preview_payload(preview_json, state)
        self._record(
            attempt_id=attempt_id,
            thread_id=thread_id or (state.thread_id if state else None),
            telegram_user_id=telegram_user_id,
            telegram_message_id=telegram_message_id,
            status="posted",
            resolution="posted",
            preview_json=payload,
            erpnext_doc_id=erpnext_doc_id,
            latency_ms=resolved_latency,
        )

    def log_retry_enqueued(
        self,
        *,
        attempt_id: str,
        thread_id: str | None,
        telegram_user_id: int,
        telegram_message_id: int,
        preview_json: Mapping[str, Any] | None = None,
        state: ConversationState | None = None,
        resolution: str = "queued_for_retry",
        erpnext_doc_id: str | None = None,
    ) -> None:
        """Record that ERPNext is unavailable and the attempt entered the retry queue."""

        payload = self._build_preview_payload(preview_json, state)
        self._record(
            attempt_id=attempt_id,
            thread_id=thread_id or (state.thread_id if state else None),
            telegram_user_id=telegram_user_id,
            telegram_message_id=telegram_message_id,
            status="retrying",
            resolution=resolution,
            preview_json=payload,
            erpnext_doc_id=erpnext_doc_id,
        )

    def log_cancellation(
        self,
        *,
        attempt_id: str,
        thread_id: str | None,
        telegram_user_id: int,
        telegram_message_id: int,
        reason: str = "user_cancelled",
        preview_json: Mapping[str, Any] | None = None,
        state: ConversationState | None = None,
    ) -> None:
        """Record that a user cancelled the expense attempt."""

        payload = self._build_preview_payload(preview_json, state)
        self._record(
            attempt_id=attempt_id,
            thread_id=thread_id or (state.thread_id if state else None),
            telegram_user_id=telegram_user_id,
            telegram_message_id=telegram_message_id,
            status="cancelled",
            resolution=reason or "user_cancelled",
            preview_json=payload,
        )

    def _record(
        self,
        *,
        attempt_id: str,
        thread_id: str | None,
        telegram_user_id: int,
        telegram_message_id: int,
        status: str,
        resolution: str,
        preview_json: Mapping[str, Any],
        erpnext_doc_id: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        resolved_thread_id = (thread_id or "").strip()
        if not resolved_thread_id:
            raise ValueError("thread_id is required for expense attempt logging.")
        if not attempt_id:
            raise ValueError("attempt_id is required for expense attempt logging.")

        self._attempt_logger.record_event(
            attempt_id=attempt_id,
            thread_id=resolved_thread_id,
            telegram_user_id=telegram_user_id,
            telegram_message_id=telegram_message_id,
            status=status,
            resolution=resolution,
            preview_json=preview_json,
            erpnext_doc_id=erpnext_doc_id,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _build_preview_payload(
        preview_json: Mapping[str, Any] | None,
        state: ConversationState | None,
    ) -> Mapping[str, Any]:
        payload: dict[str, Any] = dict(preview_json or {})
        if state is not None:
            payload.setdefault("state_snapshot", _state_snapshot(state))
        return payload

    @staticmethod
    def _normalize_attempt_id(attempt_id: str) -> str:
        trimmed = attempt_id.strip()
        if not trimmed:
            raise ValueError("attempt_id is required for expense attempt logging.")
        return trimmed

    def _remember_confirmation(
        self,
        attempt_id: str,
        confirmed_at: datetime | None,
    ) -> None:
        timestamp = self._resolve_timestamp(confirmed_at)
        self._confirmation_events[attempt_id] = timestamp

    def _calculate_latency(
        self,
        attempt_id: str,
        completed_at: datetime | None,
    ) -> int | None:
        started_at = self._confirmation_events.pop(attempt_id, None)
        if started_at is None:
            return None
        finished_at = self._resolve_timestamp(completed_at)
        delta = finished_at - started_at
        milliseconds = int(delta.total_seconds() * 1000)
        return milliseconds if milliseconds >= 0 else 0

    @staticmethod
    def _resolve_timestamp(moment: datetime | None) -> datetime:
        timestamp = moment or datetime.now(UTC)
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC)


def _state_snapshot(state: ConversationState) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "thread_id": state.thread_id,
        "confirmation_status": state.confirmation_status,
        "clarifications_needed": list(state.clarifications_needed),
        "error_log": list(state.error_log),
    }
    if state.conversation_summary:
        snapshot["conversation_summary"] = state.conversation_summary
    if state.expense_draft:
        snapshot["expense_draft"] = _draft_to_dict(state.expense_draft)
    if state.account_candidates:
        snapshot["account_candidates"] = [
            _candidate_to_dict(candidate) for candidate in state.account_candidates
        ]
    if state.erpnext_submission:
        snapshot["erpnext_submission"] = _submission_to_dict(state.erpnext_submission)
    return snapshot


def _draft_to_dict(draft: ExpenseDraft) -> dict[str, Any]:
    payload = {
        "amount": str(draft.amount),
        "currency": draft.currency,
        "posting_date": draft.posting_date.isoformat(),
        "narration": draft.narration,
        "debit_account": _account_match_to_dict(draft.debit_account),
        "credit_account": _account_match_to_dict(draft.credit_account),
        "attachments": [_attachment_to_dict(att) for att in draft.attachments],
    }
    if draft.source_message_id:
        payload["source_message_id"] = draft.source_message_id
    return payload


def _account_match_to_dict(match: AccountMatch) -> dict[str, Any]:
    return {
        "account_code": match.account_code,
        "display_name": match.display_name,
        "confidence": match.confidence,
    }


def _attachment_to_dict(attachment: AttachmentRef) -> dict[str, Any]:
    data = {"file_url": attachment.file_url}
    if attachment.caption:
        data["caption"] = attachment.caption
    return data


def _candidate_to_dict(candidate: AccountCandidate) -> dict[str, Any]:
    payload = {
        "account_name": candidate.account_name,
        "account_code": candidate.account_code,
        "confidence": candidate.confidence,
    }
    if candidate.reason:
        payload["reason"] = candidate.reason
    return payload


def _submission_to_dict(submission: JournalEntryResult) -> dict[str, Any]:
    payload = {
        "journal_entry_id": submission.journal_entry_id,
        "posting_date": submission.posting_date.isoformat(),
        "voucher_no": submission.voucher_no,
    }
    if submission.link:
        payload["link"] = submission.link
    return payload


__all__ = [
    "ConversationLoggingHooks",
    "ExpenseAttemptLogEntry",
    "ExpenseAttemptLogger",
    "generate_attempt_id",
]
