"""Integration-focused tests for ERPNextClient request handling."""

from __future__ import annotations

import json

import httpx
import pytest

from expense_bot.integrations.erpnext import ERPNextClient, ERPNextClientError


def test_client_attaches_bearer_token_header() -> None:
    """Ensure every ERPNext request carries the expected Authorization header."""

    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers["Authorization"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json={"data": []})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="https://erp.test") as http_client:
        client = ERPNextClient(
            base_url="https://erp.test",
            api_key="key-123",
            api_secret="secret-456",
            default_company="Cuenta HQ",
            http_client=http_client,
        )
        client.fetch_chart_of_accounts()

    assert captured_headers["Authorization"] == "token key-123:secret-456"


def test_fetch_chart_of_accounts_builds_filters_and_fields() -> None:
    """Validate chart retrieval sends the correct filters, fields, and limit."""

    seen_params: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen_params["filters"] = json.loads(params["filters"])
        seen_params["fields"] = json.loads(params["fields"])
        seen_params["limit_page_length"] = params["limit_page_length"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"name": "Travel Expense - HQ", "is_group": 0},
                    {"name": "Cash - HQ", "is_group": 0},
                ]
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
        result = client.fetch_chart_of_accounts(
            company="Cuenta Latam",
            include_groups=True,
            fields=("name", "is_group"),
            limit=10,
            extra_filters=(("root_type", "=", "Expense"),),
        )

    filters = seen_params["filters"]
    assert ["company", "=", "Cuenta Latam"] in filters
    assert ["root_type", "=", "Expense"] in filters
    assert not any(item[0] == "is_group" for item in filters)
    assert seen_params["fields"] == ["name", "is_group"]
    assert seen_params["limit_page_length"] == "10"
    assert [row["name"] for row in result] == [
        "Travel Expense - HQ",
        "Cash - HQ",
    ]


def test_post_journal_entry_allows_manual_retry_after_failure() -> None:
    """Simulate retry handling: first ERPNext call fails, second succeeds."""

    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                503,
                json={"message": "ERPNext temporarily unavailable"},
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "name": "JE-0001",
                    "posting_date": "2025-11-07",
                    "voucher_no": "VCH-1",
                    "link": "https://erp.test/app/journal-entry/JE-0001",
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

        payload = {
            "posting_date": "2025-11-07",
            "accounts": [
                {"account": "Travel Expense - HQ", "debit_in_account_currency": 12.0},
                {"account": "Cash - HQ", "credit_in_account_currency": 12.0},
            ],
        }

        with pytest.raises(ERPNextClientError, match="temporarily unavailable"):
            client.post_journal_entry(payload)

        result = client.post_journal_entry(payload)

    assert attempts == 2
    assert result.journal_entry_id == "JE-0001"
    assert str(result.posting_date) == "2025-11-07"
