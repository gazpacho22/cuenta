"""Unit tests for the chart-of-accounts LangGraph tool."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from expense_bot.integrations.erpnext import DEFAULT_PAGE_LENGTH
from expense_bot.integrations.tools import (
    ChartOfAccountsTool,
    create_chart_of_accounts_tool,
)


class _FakeERPNextClient:
    """Test double that records chart fetch invocations."""

    def __init__(self, default_company: str = "Cuenta HQ") -> None:
        self.default_company = default_company
        self.calls: list[dict[str, Any]] = []

    def fetch_chart_of_accounts(
        self,
        *,
        company: str,
        include_groups: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "company": company,
                "include_groups": include_groups,
                "limit": limit,
            }
        )
        return [
            {"account_name": "Taxi Expense - HQ", "account_code": "5110"},
            {"account_name": "Cash - HQ", "account_code": "1000"},
        ]


def test_chart_tool_fetches_live_accounts_on_every_call() -> None:
    client = _FakeERPNextClient()
    tool = ChartOfAccountsTool(
        erp_client=client,
        default_company=client.default_company,
    )

    first = tool.invoke({})
    assert first["company"] == "Cuenta HQ"
    assert first["account_count"] == 2
    assert "fetched_at" in first
    assert first["accounts"][0]["account_code"] == "5110"
    assert client.calls[0] == {
        "company": "Cuenta HQ",
        "include_groups": False,
        "limit": DEFAULT_PAGE_LENGTH,
    }

    second = tool.invoke(
        {"company": "Cuenta Latam", "include_groups": True, "limit": 10}
    )
    assert second["company"] == "Cuenta Latam"
    assert client.calls[1] == {
        "company": "Cuenta Latam",
        "include_groups": True,
        "limit": 10,
    }


def test_factory_reuses_injected_dependencies() -> None:
    client = _FakeERPNextClient()
    settings = SimpleNamespace(default_company="Cuenta Latam")

    tool = create_chart_of_accounts_tool(
        settings=settings,
        erp_client=client,
        default_limit=250,
    )

    assert tool.erp_client is client
    assert tool.default_company == "Cuenta Latam"
    assert tool.default_limit == 250
