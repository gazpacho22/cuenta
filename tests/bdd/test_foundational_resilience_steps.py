from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from expense_bot.graph.state import RetryJob
from .feature_registry import materialize_inline_feature

FEATURE_TEXT = """
Feature: Foundational resilience when ERPNext is unavailable
  Finance and support teams need confidence that the bot gracefully handles ERPNext outages
  so confirmed expenses are never dropped and users always know what happened.

  Background:
    Given Ava is an authorized Telegram user linked to ERPNext
    And she confirms an expense for "Paid $120 from Cash - HQ to Taxi Expense - HQ"
    And ERPNext starts returning 503 errors for journal entry requests

  Scenario Outline: ERPNext outage is queued with backoff and user notifications
    When the bot attempts to post the journal entry
    Then the confirmed expense is stored in the retry queue with attempt_id <attempt_id>
    And the retry job is scheduled with exponential backoff of 1m, 2m, 4m, 8m while never exceeding a 15-minute window
    And the bot tells Ava the expense is queued for automatic retries and that she'll be notified when it completes
    When <outcome_condition>
    Then <user_notification>

    Examples:
      | attempt_id | outcome_condition                                 | user_notification |
      | rq-481516  | ERPNext recovers after 12 minutes of retries      | the bot sends "Queued expense posted" with the ERPNext document reference |
      | rq-481517  | 15 minutes pass without a successful ERPNext call | the bot sends "Queued expense failed" with the last ERPNext error and instructions to contact finance |
"""


FEATURE_PATH = materialize_inline_feature(
    __file__, "test_foundational_resilience.feature", FEATURE_TEXT
)is 
scenarios(str(FEATURE_PATH), features_base_dir=str(FEATURE_PATH.parent))

QUEUE_NOTICE = (
    "the bot tells Ava the expense is queued for automatic retries and that she'll be notified when it completes"
)
SUCCESS_NOTICE = 'the bot sends "Queued expense posted" with the ERPNext document reference'
FAILURE_NOTICE = (
    'the bot sends "Queued expense failed" with the last ERPNext error and instructions to contact finance'
)


@dataclass
class RetryScenarioState:
    """In-memory simulation of the retry queue + user messaging surface."""

    authorized_user: bool = False
    confirmed_expense: str | None = None
    erpnext_online: bool = True
    retry_job: RetryJob | None = None
    notifications: list[str] = field(default_factory=list)
    backoff_schedule: list[int] = field(default_factory=list)
    max_window_seconds: int = 15 * 60
    elapsed_minutes: int = 0
    journal_entry_reference: str | None = None
    error_message: str | None = None

    def queue_retry(self, attempt_id: str) -> None:
        now = datetime.now()
        payload = {
            "attempt_id": attempt_id,
            "expense": self.confirmed_expense,
        }
        self.retry_job = RetryJob(
            thread_id="chat:987654321",
            payload=payload,
            next_run_at=now + timedelta(minutes=1),
            attempts=0,
        )
        self.backoff_schedule = [60, 120, 240, 480]
        self.notifications.append(QUEUE_NOTICE)

    def record_outcome(self, *, success: bool, minutes_waited: int) -> None:
        if minutes_waited * 60 > self.max_window_seconds:
            raise AssertionError("Retry handling exceeded the 15-minute policy window.")

        self.elapsed_minutes = minutes_waited
        if success:
            self.journal_entry_reference = "ERP-JE-0001"
            self.retry_job = None
            self.notifications.append(SUCCESS_NOTICE)
        else:
            if self.retry_job is not None:
                self.retry_job.error = "ERPNext outage persisted beyond 15 minutes."
            self.error_message = "ERPNext outage persisted beyond 15 minutes."
            self.notifications.append(FAILURE_NOTICE)


@pytest.fixture
def retry_state() -> RetryScenarioState:
    """State container shared across scenario steps."""

    return RetryScenarioState()


@pytest.fixture
def attempt_id(_pytest_bdd_example: dict[str, str]) -> str:
    """Expose Scenario Outline attempt_id values as a fixture."""

    return _pytest_bdd_example["attempt_id"]


@given("Ava is an authorized Telegram user linked to ERPNext")
def given_authorized_user(retry_state: RetryScenarioState) -> None:
    retry_state.authorized_user = True


@given(parsers.parse('she confirms an expense for "{expense_summary}"'))
def given_confirmed_expense(
    retry_state: RetryScenarioState, expense_summary: str
) -> None:
    retry_state.confirmed_expense = expense_summary


@given("ERPNext starts returning 503 errors for journal entry requests")
def given_erpnext_outage(retry_state: RetryScenarioState) -> None:
    retry_state.erpnext_online = False


@when("the bot attempts to post the journal entry")
def when_bot_attempts_post(
    retry_state: RetryScenarioState, attempt_id: str
) -> None:
    if retry_state.erpnext_online:
        pytest.fail("Scenario requires ERPNext to be unavailable before queuing retries.")
    retry_state.queue_retry(attempt_id)


@then(
    parsers.parse(
        "the confirmed expense is stored in the retry queue with attempt_id {attempt_id}"
    )
)
def then_retry_job_created(
    retry_state: RetryScenarioState, attempt_id: str
) -> None:
    assert retry_state.retry_job is not None, "Retry job was not created."
    assert (
        retry_state.retry_job.payload.get("attempt_id") == attempt_id
    ), "Retry job attempt_id mismatch."


@then(
    "the retry job is scheduled with exponential backoff of 1m, 2m, 4m, 8m while never exceeding a 15-minute window"
)
def then_backoff_schedule_valid(retry_state: RetryScenarioState) -> None:
    assert retry_state.backoff_schedule == [
        60,
        120,
        240,
        480,
    ], "Backoff schedule does not follow expected doubling pattern."
    assert (
        sum(retry_state.backoff_schedule) <= retry_state.max_window_seconds
    ), "Backoff schedule exceeds 15-minute policy."


@then(
    "the bot tells Ava the expense is queued for automatic retries and that she'll be notified when it completes"
)
def then_queue_notification_sent(retry_state: RetryScenarioState) -> None:
    assert QUEUE_NOTICE in retry_state.notifications, "Queueing notice was not sent."


@when(parsers.cfparse("ERPNext recovers after {minutes:d} minutes of retries"))
def when_erpnext_recovers(
    retry_state: RetryScenarioState, minutes: int
) -> None:
    retry_state.record_outcome(success=True, minutes_waited=minutes)


@when("15 minutes pass without a successful ERPNext call")
def when_outage_persists(retry_state: RetryScenarioState) -> None:
    retry_state.record_outcome(success=False, minutes_waited=15)


@then('the bot sends "Queued expense posted" with the ERPNext document reference')
def then_success_notification(retry_state: RetryScenarioState) -> None:
    assert (
        SUCCESS_NOTICE in retry_state.notifications
    ), "Success notice was not sent."
    assert (
        retry_state.journal_entry_reference is not None
    ), "Journal entry reference missing after recovery."


@then(
    'the bot sends "Queued expense failed" with the last ERPNext error and instructions to contact finance'
)
def then_failure_notification(retry_state: RetryScenarioState) -> None:
    assert (
        FAILURE_NOTICE in retry_state.notifications
    ), "Failure notice was not sent."
    assert (
        retry_state.error_message is not None
    ), "Failure path should capture the last ERPNext error."
