"""Integration test ensuring ERPNext document IDs reach the messenger layer."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import httpx

from expense_bot.graph.posting import post_confirmed_expense
from expense_bot.graph.state import AccountMatch, ConversationState, ExpenseDraft
from expense_bot.integrations.erpnext import ERPNextClient


class MessengerProbe:
    """In-memory messenger that captures confirmation payloads."""

    def __init__(self) -> None:
        self.messages: list[dict[str, str | None]] = []

    def send_posted_notice(
        self, *, thread_id: str, document_id: str, document_link: str | None
    ) -> None:
        self.messages.append(
            {
                "thread_id": thread_id,
                "document_id": document_id,
                "document_link": document_link,
            }
        )


def _build_state() -> ConversationState:
    draft = ExpenseDraft(
        amount=Decimal("10.00"),
        currency="USD",
        debit_account=AccountMatch(
            account_code="5110",
            display_name="Taxi Expense - HQ",
            confidence=0.99,
        ),
        credit_account=AccountMatch(
            account_code="1000",
            display_name="Cash - HQ",
            confidence=0.98,
        ),
        posting_date=date(2025, 11, 7),
        narration="Paid $10 cash for taxi",
    )
    return ConversationState(
        thread_id="chat:481516",
        expense_draft=draft,
        confirmation_status="approved",
    )


def test_document_reference_flows_from_erpnext_to_messenger() -> None:
    """The LangGraph posting flow must echo ERPNext doc IDs back to Telegram."""

    captured_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payload.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "data": {
                    "name": "JE-4242",
                    "posting_date": "2025-11-07",
                    "voucher_no": "VCH-4242",
                    "link": "https://erp.test/app/journal-entry/JE-4242",
                }
            },
        )

    transport = httpx.MockTransport(handler)
    messenger = MessengerProbe()
    state = _build_state()

    with httpx.Client(
        transport=transport,
        base_url="https://erp.test",
    ) as http_client:
        client = ERPNextClient(
            base_url="https://erp.test",
            api_key="key-123",
            api_secret="secret-456",
            default_company="Cuenta HQ",
            http_client=http_client,
        )
        result = post_confirmed_expense(state, erp_client=client)
        messenger.send_posted_notice(
            thread_id=state.thread_id,
            document_id=result.journal_entry_id,
            document_link=result.link,
        )

    assert captured_payload["accounts"][0]["account"] == "5110"
    assert state.erpnext_submission is not None, "ERPNext submission metadata missing."
    assert state.erpnext_submission.journal_entry_id == "JE-4242"
    assert messenger.messages == [
        {
            "thread_id": "chat:481516",
            "document_id": "JE-4242",
            "document_link": "https://erp.test/app/journal-entry/JE-4242",
        }
    ]
