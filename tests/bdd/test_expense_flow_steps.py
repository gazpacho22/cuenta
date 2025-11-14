from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from .feature_registry import materialize_inline_feature

FEATURE_TEXT = """
Feature: Capture and confirm a Telegram expense
  Finance needs a reliable capture flow so authorized users can describe an expense,
  review the draft, and confirm it is posted to ERPNext without losing fidelity.

  Background:
    Given Ava is authorized to capture expenses
    And the chart of accounts includes debit "Taxi Expense - HQ" and credit "Cash - HQ"

  Scenario: Ava confirms a taxi expense and posts it to ERPNext
    When she tells the bot "Paid $10 cash for taxi"
    Then the bot drafts a confirmation summary referencing "Taxi Expense - HQ" and "Cash - HQ"
    And the summary echoes the original message "Paid $10 cash for taxi"
    When she approves the expense summary
    Then the ERPNext payload is balanced for $10.00 USD
    And the bot acknowledges the posting to Ava
    And the bot shares the ERPNext document reference "ERP-JE-0001"
"""


FEATURE_PATH = materialize_inline_feature(
    __file__, "test_expense_flow.feature", FEATURE_TEXT
)
scenarios(str(FEATURE_PATH), features_base_dir=str(FEATURE_PATH.parent))


@dataclass
class ExpenseFlowScenarioState:
    """Lightweight simulation of the capture-confirm flow for User Story 1."""

    authorized: bool = False
    debit_account: str | None = None
    credit_account: str | None = None
    pending_summary: str | None = None
    pending_message: str | None = None
    pending_amount: Decimal | None = None
    erpnext_payload: dict[str, Any] | None = None
    notifications: list[str] = field(default_factory=list)
    company: str = "Cuenta HQ"
    erpnext_document_id: str | None = None

    AMOUNT_PATTERN = re.compile(r"\$?(?P<amount>\d+(?:\.\d+)?)")

    def authorize(self) -> None:
        self.authorized = True

    def configure_accounts(self, debit: str, credit: str) -> None:
        self.debit_account = debit
        self.credit_account = credit

    def capture_message(self, message: str) -> None:
        if not self.authorized:
            pytest.fail("User must be authorized before capturing expenses.")
        if not self.debit_account or not self.credit_account:
            pytest.fail("Debit and credit accounts must be configured.")

        match = self.AMOUNT_PATTERN.search(message.replace(",", ""))
        if not match:
            pytest.fail("Scenario message must include a numeric amount.")

        try:
            amount = Decimal(match.group("amount"))
        except (InvalidOperation, ValueError) as exc:
            pytest.fail(f"Invalid amount detected: {exc}")  # pragma: no cover

        self.pending_amount = amount
        self.pending_message = message
        self.pending_summary = (
            f"{message.strip()} → debit {self.debit_account} / credit {self.credit_account}"
        )

    def confirm_posting(self) -> None:
        if self.pending_amount is None or not self.pending_summary:
            pytest.fail("Cannot confirm without a drafted summary.")
        if not self.debit_account or not self.credit_account:
            pytest.fail("Accounts must be set before confirming the expense.")

        posting_date = date.today().isoformat()
        amount = self.pending_amount
        debit_row = {
            "account": self.debit_account,
            "debit_in_account_currency": amount,
            "credit_in_account_currency": Decimal("0"),
        }
        credit_row = {
            "account": self.credit_account,
            "debit_in_account_currency": Decimal("0"),
            "credit_in_account_currency": amount,
        }
        doc_id = "ERP-JE-0001"
        self.erpnext_document_id = doc_id

        self.erpnext_payload = {
            "company": self.company,
            "posting_date": posting_date,
            "user_remark": self.pending_summary,
            "accounts": [debit_row, credit_row],
            "document_id": doc_id,
        }
        self.notifications.append(
            f"Posted {amount:.2f} USD from {self.credit_account} to {self.debit_account} (ERPNext doc {doc_id})"
        )


@pytest.fixture
def expense_flow_state() -> ExpenseFlowScenarioState:
    """Provide isolated scenario state for each execution."""

    return ExpenseFlowScenarioState()


@given("Ava is authorized to capture expenses")
def given_authorized(expense_flow_state: ExpenseFlowScenarioState) -> None:
    expense_flow_state.authorize()


@given(
    parsers.parse(
        'the chart of accounts includes debit "{debit}" and credit "{credit}"'
    )
)
def given_chart_of_accounts(
    expense_flow_state: ExpenseFlowScenarioState, debit: str, credit: str
) -> None:
    expense_flow_state.configure_accounts(debit, credit)


@when(parsers.parse('she tells the bot "{message}"'))
def when_user_describes_expense(
    expense_flow_state: ExpenseFlowScenarioState, message: str
) -> None:
    expense_flow_state.capture_message(message)


@then(
    parsers.parse(
        'the bot drafts a confirmation summary referencing "{debit}" and "{credit}"'
    )
)
def then_summary_references_accounts(
    expense_flow_state: ExpenseFlowScenarioState, debit: str, credit: str
) -> None:
    summary = expense_flow_state.pending_summary
    assert summary, "No summary was generated."
    assert debit in summary and credit in summary, "Summary missing account references."


@then(parsers.parse('the summary echoes the original message "{message}"'))
def then_summary_echoes_message(
    expense_flow_state: ExpenseFlowScenarioState, message: str
) -> None:
    summary = expense_flow_state.pending_summary
    assert summary, "No summary was generated."
    assert message in summary, "Summary did not echo the user's message."


@when("she approves the expense summary")
def when_user_confirms(expense_flow_state: ExpenseFlowScenarioState) -> None:
    expense_flow_state.confirm_posting()


@then(parsers.parse("the ERPNext payload is balanced for ${amount} USD"))
def then_payload_balanced(
    expense_flow_state: ExpenseFlowScenarioState, amount: str
) -> None:
    payload = expense_flow_state.erpnext_payload
    assert payload is not None, "ERPNext payload missing."

    accounts = payload.get("accounts", [])
    assert len(accounts) == 2, "Expected two ledger entries."

    debit_total = sum(entry["debit_in_account_currency"] for entry in accounts)
    credit_total = sum(entry["credit_in_account_currency"] for entry in accounts)
    expected_amount = Decimal(amount)

    assert debit_total == credit_total == expected_amount, "Journal entry is not balanced."


@then("the bot acknowledges the posting to Ava")
def then_user_notified(expense_flow_state: ExpenseFlowScenarioState) -> None:
    assert expense_flow_state.notifications, "No notification was sent."
    assert any(
        notice.startswith("Posted") for notice in expense_flow_state.notifications
    ), "Posting confirmation missing."


@then(
    parsers.parse(
        'the bot shares the ERPNext document reference "{document_id}"'
    )
)
def then_document_reference_shared(
    expense_flow_state: ExpenseFlowScenarioState, document_id: str
) -> None:
    assert (
        expense_flow_state.erpnext_document_id == document_id
    ), "Document id stored in state does not match."
    assert any(
        document_id in notice for notice in expense_flow_state.notifications
    ), "User notification did not include the document reference."
