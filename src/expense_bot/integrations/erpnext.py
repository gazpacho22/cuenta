"""HTTP client for interacting with ERPNext."""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

import httpx
from langsmith import traceable

from expense_bot import get_logger
from expense_bot.graph.state import JournalEntryResult

try:  # Optional type hinting without forcing a runtime dependency cycle.
    from pydantic import SecretStr
except ImportError:  # pragma: no cover - SecretStr always available in runtime env.
    SecretStr = Any  # type: ignore[misc,assignment]

if TYPE_CHECKING:
    from expense_bot.config import Settings


LOGGER = get_logger("integrations.erpnext")


DEFAULT_ACCOUNT_FIELDS: Sequence[str] = (
    "name",
    "account_name",
    "account_number",
    "is_group",
    "root_type",
    "report_type",
    "company",
    "parent_account",
)
DEFAULT_PAGE_LENGTH = 500


class ERPNextClientError(RuntimeError):
    """Raised when ERPNext responds with an error or an unexpected payload."""


class ERPNextClient:
    """Lightweight synchronous client for ERPNext REST operations."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | SecretStr,
        api_secret: str | SecretStr,
        default_company: str,
        timeout: float = 10.0,
        http_client: httpx.Client | None = None,
        user_agent: str = "expense-bot/0.1",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self.default_company = default_company

        key = self._secret_value(api_key)
        secret = self._secret_value(api_secret)
        self._auth_header = f"token {key}:{secret}"

        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers={"User-Agent": user_agent},
        )

    @classmethod
    def from_settings(
        cls, settings: "Settings", **client_kwargs: Any
    ) -> "ERPNextClient":
        """Instantiate a client from shared Settings."""

        return cls(
            base_url=settings.erp_base_url,
            api_key=settings.erp_api_key,
            api_secret=settings.erp_api_secret,
            default_company=settings.default_company,
            **client_kwargs,
        )

    def __enter__(self) -> "ERPNextClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client if we created it."""
        if self._owns_client:
            self._client.close()

    def fetch_chart_of_accounts(
        self,
        *,
        company: str | None = None,
        include_groups: bool = False,
        fields: Sequence[str] | None = None,
        limit: int = DEFAULT_PAGE_LENGTH,
        extra_filters: Iterable[Sequence[Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Return the chart of accounts for the requested company."""

        target_company = company or self.default_company
        metadata = {
            "company": target_company,
            "include_groups": include_groups,
            "limit": limit,
        }
        return self._fetch_chart_of_accounts_impl(
            company=target_company,
            include_groups=include_groups,
            fields=fields,
            limit=limit,
            extra_filters=extra_filters,
            langsmith_extra={"metadata": metadata},
        )

    @traceable(run_type="tool", name="erpnext.fetch_chart_of_accounts")
    def _fetch_chart_of_accounts_impl(
        self,
        *,
        company: str,
        include_groups: bool,
        fields: Sequence[str] | None,
        limit: int,
        extra_filters: Iterable[Sequence[Any]] | None,
    ) -> list[dict[str, Any]]:
        """Traced helper that performs the ERPNext chart request."""

        filters: list[list[Any]] = [["company", "=", company]]
        if not include_groups:
            filters.append(["is_group", "=", 0])
        if extra_filters:
            for flt in extra_filters:
                filters.append(list(flt))

        params = {
            "fields": json.dumps(list(fields or DEFAULT_ACCOUNT_FIELDS)),
            "filters": json.dumps(filters),
            "limit_page_length": limit,
            "order_by": "account_name asc",
        }

        response = self._request("GET", "/api/resource/Account", params=params)

        payload = self._safe_json(response)
        accounts = payload.get("data", [])
        if not isinstance(accounts, list):
            raise ERPNextClientError("Unexpected ERPNext response format for accounts.")
        LOGGER.debug("Fetched %d ERPNext accounts for company %s", len(accounts), company)
        return accounts

    def post_journal_entry(self, payload: Mapping[str, Any]) -> JournalEntryResult:
        """Post a journal entry and return the parsed ERPNext response."""

        body = dict(payload)
        body.setdefault("company", self.default_company)
        metadata = {
            "company": body.get("company"),
            "account_lines": len(body.get("accounts") or []),
        }
        return self._post_journal_entry_impl(
            payload=body,
            langsmith_extra={"metadata": metadata},
        )

    @traceable(run_type="tool", name="erpnext.post_journal_entry")
    def _post_journal_entry_impl(
        self, *, payload: Mapping[str, Any]
    ) -> JournalEntryResult:
        response = self._request("POST", "/api/resource/Journal Entry", json=payload)

        payload = self._safe_json(response)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ERPNextClientError("ERPNext response is missing journal entry data.")

        entry_id = data.get("name")
        posting_date_str = data.get("posting_date")
        voucher = (
            data.get("voucher_number")
            or data.get("voucher_no")
            or data.get("name")
            or ""
        )
        link = data.get("link") or self._build_document_link("Journal Entry", entry_id)

        if not entry_id or not posting_date_str:
            raise ERPNextClientError(
                "ERPNext response missing required fields (name/posting_date)."
            )

        try:
            posting_date = date.fromisoformat(posting_date_str)
        except ValueError as exc:  # pragma: no cover - depends on ERPNext input
            raise ERPNextClientError(
                f"Invalid posting_date returned from ERPNext: {posting_date_str}"
            ) from exc

        return JournalEntryResult(
            journal_entry_id=entry_id,
            posting_date=posting_date,
            voucher_no=voucher,
            link=link,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        merged_headers = {"Accept": "application/json", "Authorization": self._auth_header}
        if headers:
            merged_headers.update(headers)
        if "json" in kwargs and "Content-Type" not in merged_headers:
            merged_headers["Content-Type"] = "application/json"

        try:
            response = self._client.request(
                method.upper(), path, headers=merged_headers, **kwargs
            )
            response.raise_for_status()
            return response
        except httpx.TimeoutException as exc:
            raise ERPNextClientError("ERPNext request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            detail = self._extract_error(exc.response)
            raise ERPNextClientError(detail) from exc
        except httpx.HTTPError as exc:
            raise ERPNextClientError(f"ERPNext request failed: {exc}") from exc

    def _build_document_link(self, doctype: str, docname: str | None) -> str | None:
        if not docname:
            return None
        slug = doctype.strip().lower().replace(" ", "-")
        return f"{self._base_url}/app/{slug}/{docname}"

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:  # pragma: no cover - server controls JSON
            raise ERPNextClientError("ERPNext response was not valid JSON.") from exc
        if not isinstance(data, dict):
            raise ERPNextClientError("Expected ERPNext response to be an object.")
        return data

    @staticmethod
    def _extract_error(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            return payload.get("message") or payload.get("exc_type") or str(response)
        return response.text or f"ERPNext error {response.status_code}"

    @staticmethod
    def _secret_value(value: str | SecretStr) -> str:
        if isinstance(value, str):
            return value
        return value.get_secret_value()


__all__ = ["ERPNextClient", "ERPNextClientError"]
