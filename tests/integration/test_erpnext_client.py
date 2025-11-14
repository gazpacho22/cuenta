"""Integration-style tests for the journal entry happy path."""

from __future__ import annotations

import json

import httpx

from expense_bot.integrations.erpnext import ERPNextClient


def test_post_journal_entry_parses_success_payload() -> None:
    """Ensure a 200 response produces a JournalEntryResult with document metadata."""

    captured_json: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_json.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "data": {
                    "name": "JE-9001",
                    "posting_date": "2025-11-07",
                    "voucher_no": "VCH-9001",
                    "link": "https://erp.test/app/journal-entry/JE-9001",
                }
            },
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="https://erp.test") as http_client:
        client = ERPNextClient(
            base_url="https://erp.test",
            api_key="key-123",
            api_secret="secret-456",
            default_company="Cuenta HQ",
            http_client=http_client,
        )
        result = client.post_journal_entry(
            {
                "posting_date": "2025-11-07",
                "accounts": [
                    {
                        "account": "Taxi Expense - HQ",
                        "debit_in_account_currency": 10.0,
                        "credit_in_account_currency": 0.0,
                    },
                    {
                        "account": "Cash - HQ",
                        "debit_in_account_currency": 0.0,
                        "credit_in_account_currency": 10.0,
                    },
                ],
            }
        )

    assert captured_json["company"] == "Cuenta HQ", "Client should backfill default company."
    assert result.journal_entry_id == "JE-9001"
    assert str(result.posting_date) == "2025-11-07"
    assert result.voucher_no == "VCH-9001"
    assert result.link == "https://erp.test/app/journal-entry/JE-9001"
