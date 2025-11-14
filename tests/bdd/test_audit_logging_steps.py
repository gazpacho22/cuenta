from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from .feature_registry import materialize_inline_feature

FEATURE_TEXT = """
Feature: Audit logging for previews, edits, and cancellations
  Finance and compliance reviewers need to inspect every expense attempt
  so each conversational action is threaded by attempt_id and stored with the
  structured payload required by FR-011.

  Background:
    Given Ava starts a new expense attempt "attempt-481516" in thread "chat:987654321"
    And no audit log entries exist yet

  Scenario: Preview, edit, and cancel actions are logged with shared attempt context
    When she previews the expense summary "Paid $12 cash for taxi"
    Then the audit log records a "previewed" entry with attempt_id "attempt-481516" and thread "chat:987654321"
    And the payload snapshot stores "Paid $12 cash for taxi"
    When she edits the expense to "Paid $18 cash for taxi"
    Then the audit log records a "edited" entry with attempt_id "attempt-481516" and thread "chat:987654321"
    And the payload snapshot stores "Paid $18 cash for taxi"
    When she cancels the expense because "she found the corporate card receipt"
    Then the audit log records a "cancelled" entry with attempt_id "attempt-481516" and thread "chat:987654321"
    And every log entry for attempt "attempt-481516" contains attempt_id, thread_id, status, resolution, preview_json fields
"""


FEATURE_PATH = materialize_inline_feature(
    __file__, "test_audit_logging.feature", FEATURE_TEXT
)
scenarios(str(FEATURE_PATH), features_base_dir=str(FEATURE_PATH.parent))


@dataclass
class AuditLogEntry:
    """Structured record captured for each conversational action."""

    attempt_id: str
    thread_id: str
    action: str
    payload: dict[str, Any]


@dataclass
class AuditLogScenarioState:
    """Light-weight simulation of the expense_attempts logging writer."""

    attempt_id: str | None = None
    thread_id: str | None = None
    entries: list[AuditLogEntry] = field(default_factory=list)
    last_summary: str | None = None

    def configure_attempt(self, attempt_id: str, thread_id: str) -> None:
        self.attempt_id = attempt_id
        self.thread_id = thread_id

    def log_preview(self, summary: str) -> None:
        self.last_summary = summary
        self._log(action="previewed", resolution="pending_user_confirmation")

    def log_edit(self, summary: str) -> None:
        self.last_summary = summary
        self._log(action="edited", resolution="user_edited")

    def log_cancel(self, reason: str) -> None:
        self._log(action="cancelled", resolution=reason)

    def _log(self, *, action: str, resolution: str) -> None:
        if not self.attempt_id or not self.thread_id:
            raise AssertionError("Attempt context must be configured before logging.")
        payload = {
            "attempt_id": self.attempt_id,
            "thread_id": self.thread_id,
            "status": action,
            "resolution": resolution,
            "preview_json": {
                "summary": self.last_summary,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            },
        }
        self.entries.append(
            AuditLogEntry(
                attempt_id=self.attempt_id,
                thread_id=self.thread_id,
                action=action,
                payload=payload,
            )
        )


@pytest.fixture
def audit_state() -> AuditLogScenarioState:
    """Provide isolated scenario state for each BDD execution."""

    return AuditLogScenarioState()


@given(parsers.parse('Ava starts a new expense attempt "{attempt_id}" in thread "{thread_id}"'))
def given_attempt_context(
    audit_state: AuditLogScenarioState, attempt_id: str, thread_id: str
) -> None:
    audit_state.configure_attempt(attempt_id, thread_id)


@given("no audit log entries exist yet")
def given_empty_log(audit_state: AuditLogScenarioState) -> None:
    assert audit_state.entries == []


@when(parsers.parse('she previews the expense summary "{summary}"'))
def when_preview(audit_state: AuditLogScenarioState, summary: str) -> None:
    audit_state.log_preview(summary)


@when(parsers.parse('she edits the expense to "{summary}"'))
def when_edit(audit_state: AuditLogScenarioState, summary: str) -> None:
    audit_state.log_edit(summary)


@when(parsers.parse('she cancels the expense because "{reason}"'))
def when_cancel(audit_state: AuditLogScenarioState, reason: str) -> None:
    audit_state.log_cancel(reason)


@then(
    parsers.parse(
        'the audit log records a "{action}" entry with attempt_id "{attempt_id}" and thread "{thread_id}"'
    )
)
def then_entry_logged(
    audit_state: AuditLogScenarioState, action: str, attempt_id: str, thread_id: str
) -> None:
    assert audit_state.entries, "No audit entries were recorded."
    entry = audit_state.entries[-1]
    assert entry.action == action, f"Expected latest action '{action}', got '{entry.action}'."
    assert entry.attempt_id == attempt_id
    assert entry.thread_id == thread_id


@then(parsers.parse('the payload snapshot stores "{summary}"'))
def then_payload_snapshot(audit_state: AuditLogScenarioState, summary: str) -> None:
    entry = audit_state.entries[-1]
    preview_json = entry.payload.get("preview_json", {})
    assert preview_json.get("summary") == summary, "Preview JSON did not reflect the latest summary."


@then(
    parsers.parse(
        'every log entry for attempt "{attempt_id}" contains attempt_id, thread_id, status, resolution, preview_json fields'
    )
)
def then_entries_structured(audit_state: AuditLogScenarioState, attempt_id: str) -> None:
    assert len(audit_state.entries) == 3, "Preview, edit, and cancel actions should produce three entries."
    required_fields = {"attempt_id", "thread_id", "status", "resolution", "preview_json"}
    for entry in audit_state.entries:
        assert entry.attempt_id == attempt_id, "Entry attempt_id mismatch."
        payload = entry.payload
        missing = required_fields - payload.keys()
        assert not missing, f"Entry missing required fields: {sorted(missing)}"
        assert payload["attempt_id"] == attempt_id
        assert payload["thread_id"] == entry.thread_id
        assert isinstance(payload["preview_json"], dict), "preview_json must be structured data."
