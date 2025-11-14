"""LangGraph tool definitions for ERPNext-powered workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from expense_bot import get_logger
from expense_bot.config import Settings, get_settings
from expense_bot.integrations.erpnext import DEFAULT_PAGE_LENGTH, ERPNextClient

LOGGER = get_logger("integrations.tools")


@runtime_checkable
class ChartCatalogClient(Protocol):
    """Protocol describing the client required by ChartOfAccountsTool."""

    default_company: str

    def fetch_chart_of_accounts(
        self,
        *,
        company: str,
        include_groups: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return ERPNext account rows for the requested company."""


class ChartOfAccountsInput(BaseModel):
    """Input schema for the chart-of-accounts LangGraph tool."""

    company: str | None = Field(
        default=None,
        description=(
            "Optional ERPNext company to fetch the chart for. "
            "Defaults to the bot's configured company."
        ),
    )
    include_groups: bool = Field(
        default=False,
        description="Set to true only when grouping accounts are needed.",
    )
    limit: int = Field(
        default=DEFAULT_PAGE_LENGTH,
        ge=1,
        le=2000,
        description="Maximum number of ledger records to fetch per invocation.",
    )


class ChartOfAccountsTool(BaseTool):
    """LangGraph tool that fetches the ERPNext chart of accounts every turn."""

    name: str = "chart_of_accounts"
    description: str = (
        "Fetch the live ERPNext chart of accounts for a company. "
        "Use this before ranking or validating ledger selections so suggestions "
        "are based on the latest data. Returns a JSON object containing the "
        "company, fetched_at timestamp, account_count, and the raw account rows."
    )
    args_schema: type[BaseModel] = ChartOfAccountsInput

    erp_client: ChartCatalogClient
    default_company: str
    default_limit: int = Field(
        default=DEFAULT_PAGE_LENGTH,
        description="Fallback limit when the caller omits one.",
    )

    def _run(
        self,
        company: str | None = None,
        include_groups: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        candidate_company = (company or "").strip()
        target_company = candidate_company or self.default_company
        account_limit = limit or self.default_limit

        accounts = self.erp_client.fetch_chart_of_accounts(
            company=target_company,
            include_groups=include_groups,
            limit=account_limit,
        )
        fetched_at = datetime.now(timezone.utc).isoformat()
        LOGGER.debug(
            "ChartOfAccountsTool fetched %d accounts for %s (include_groups=%s, limit=%d)",
            len(accounts),
            target_company,
            include_groups,
            account_limit,
        )
        return {
            "company": target_company,
            "fetched_at": fetched_at,
            "account_count": len(accounts),
            "accounts": accounts,
        }


def create_chart_of_accounts_tool(
    *,
    settings: Settings | None = None,
    erp_client: ChartCatalogClient | None = None,
    default_limit: int = DEFAULT_PAGE_LENGTH,
) -> ChartOfAccountsTool:
    """Factory helper that wires the tool to the configured ERPNext client."""

    if default_limit <= 0:
        raise ValueError("default_limit must be a positive integer.")

    resolved_settings = settings or get_settings()
    client: ChartCatalogClient = (
        erp_client or ERPNextClient.from_settings(resolved_settings)
    )
    return ChartOfAccountsTool(
        erp_client=client,
        default_company=resolved_settings.default_company,
        default_limit=default_limit,
    )


__all__ = [
    "ChartOfAccountsInput",
    "ChartOfAccountsTool",
    "create_chart_of_accounts_tool",
]
