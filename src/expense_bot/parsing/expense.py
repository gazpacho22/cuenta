"""Expense message parsing and account candidate ranking utilities."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Iterable, Sequence

from rapidfuzz import fuzz

from expense_bot.graph.state import AccountCandidate

_AMOUNT_PATTERN = re.compile(
    r"""
    (?P<prefix_currency>\$|€|£|usd|eur|gbp|cad|aud|mxn|cop|clp|pen|ars|brl)?   # currency symbol/code before amount
    \s*
    (?P<amount>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)                    # numeric amount with optional commas
    \s*
    (?P<suffix_currency>usd|eur|gbp|cad|aud|mxn|cop|clp|pen|ars|brl)?         # currency code after amount
    """,
    re.IGNORECASE | re.VERBOSE,
)

_DEBIT_PATTERN = re.compile(
    r"(?:for|to|on)\s+(?P<account>[a-z0-9][a-z0-9\s:/&-]*)",
    re.IGNORECASE,
)
_CREDIT_PATTERN = re.compile(
    r"(?:from|using|with|via)\s+(?P<account>[a-z0-9][a-z0-9\s:/&-]*)",
    re.IGNORECASE,
)
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "of",
    "on",
    "paid",
    "the",
    "to",
    "using",
    "with",
    "via",
}
_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}


@dataclass(slots=True)
class ParsedExpense:
    """Structured representation of a parsed expense message."""

    amount: Decimal | None
    currency: str | None
    narration: str
    debit_hint: str | None
    credit_hint: str | None
    keywords: tuple[str, ...]
    missing_fields: set[str]
    source_message_id: str | None = None


def parse_expense_text(
    message: str,
    *,
    default_currency: str | None = None,
    source_message_id: str | None = None,
) -> ParsedExpense:
    """Extract amount, currency, and ledger hints from a Telegram message."""

    narration = message.strip()
    working_text = " ".join(narration.lower().split())

    amount, currency, amount_span = _extract_amount_and_currency(
        working_text, default_currency
    )
    debit_hint, debit_span = _extract_debit_hint(working_text)
    credit_hint = _extract_credit_hint(
        working_text, amount_span=amount_span, debit_span=debit_span, debit_hint=debit_hint
    )

    keywords = _extract_keywords(working_text)
    missing_fields: set[str] = set()
    if amount is None:
        missing_fields.add("amount")
    if debit_hint is None:
        missing_fields.add("debit_account")
    if credit_hint is None:
        missing_fields.add("credit_account")

    return ParsedExpense(
        amount=amount,
        currency=currency,
        narration=narration,
        debit_hint=debit_hint,
        credit_hint=credit_hint,
        keywords=keywords,
        missing_fields=missing_fields,
        source_message_id=source_message_id,
    )


def rank_account_candidates(
    *,
    query_terms: Sequence[str] | str,
    accounts: Sequence[dict[str, object]],
    limit: int = 5,
    min_confidence: float = 0.5,
) -> list[AccountCandidate]:
    """Rank ERPNext accounts most relevant to the provided query terms."""

    tokens = _normalize_query_terms(query_terms)
    if not tokens:
        return []

    scored: list[AccountCandidate] = []
    seen_codes: set[str] = set()
    combined_query = " ".join(tokens)

    for record in accounts:
        account_name = str(record.get("account_name") or record.get("name") or "").strip()
        account_code = str(record.get("account_code") or record.get("name") or "").strip()
        if not account_name or not account_code or account_code in seen_codes:
            continue

        alias_values = record.get("aliases") or record.get("alias") or []
        aliases: list[str]
        if isinstance(alias_values, str):
            aliases = [alias_values]
        elif isinstance(alias_values, Iterable):
            aliases = [str(alias) for alias in alias_values if alias]
        else:
            aliases = []

        cleaned_name = account_name.lower()
        best_score = _score_label(cleaned_name, tokens, combined_query)
        for alias in aliases:
            alias_score = _score_alias(str(alias).lower(), tokens)
            best_score = max(best_score, alias_score)

        confidence = round(best_score, 4)
        if confidence < min_confidence:
            continue

        seen_codes.add(account_code)
        reason = f"Matched '{account_name}'" if confidence >= 0.95 else f"Similar to '{account_name}'"
        scored.append(
            AccountCandidate(
                account_name=account_name,
                account_code=account_code,
                confidence=confidence,
                reason=reason,
            )
        )

    scored.sort(key=lambda candidate: candidate.confidence, reverse=True)
    return scored[:limit] if limit and len(scored) > limit else scored


def _extract_amount_and_currency(
    text: str, default_currency: str | None
) -> tuple[Decimal | None, str | None, tuple[int, int] | None]:
    match = _AMOUNT_PATTERN.search(text)
    if not match:
        return None, default_currency, None

    raw_amount = match.group("amount").replace(",", "")
    try:
        amount = Decimal(raw_amount)
    except (InvalidOperation, ValueError):
        return None, default_currency, None

    currency_token = match.group("prefix_currency") or match.group("suffix_currency")
    normalized_currency = _normalize_currency(currency_token, default_currency)

    return amount, normalized_currency, match.span()


def _normalize_currency(token: str | None, fallback: str | None) -> str | None:
    if not token:
        return fallback
    cleaned = token.strip().upper()
    return _CURRENCY_SYMBOLS.get(cleaned, cleaned)


def _extract_debit_hint(text: str) -> tuple[str | None, tuple[int, int] | None]:
    match = _DEBIT_PATTERN.search(text)
    if not match:
        return None, None
    hint = _clean_hint(match.group("account"))
    return hint, match.span() if hint else (None, None)


def _extract_credit_hint(
    text: str,
    *,
    amount_span: tuple[int, int] | None,
    debit_span: tuple[int, int] | None,
    debit_hint: str | None,
) -> str | None:
    match = _CREDIT_PATTERN.search(text)
    if match:
        return _clean_hint(match.group("account"))

    if amount_span and debit_span and amount_span[1] < debit_span[0]:
        between = text[amount_span[1] : debit_span[0]]
        hint = _clean_hint(between)
        if hint:
            return hint

    if amount_span:
        trailing = text[amount_span[1] :]
        hint = _clean_hint(trailing)
        if hint and hint != debit_hint:
            return hint

    return None


def _clean_hint(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip(" .,:;")
    cleaned = re.split(r"\b(?:and|but|then)\b", cleaned, maxsplit=1)[0]
    cleaned = re.split(r"[.,;]", cleaned, maxsplit=1)[0]
    cleaned = cleaned.replace(" account", "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or None


def _extract_keywords(text: str) -> tuple[str, ...]:
    tokens = []
    for token in _TOKEN_PATTERN.findall(text):
        if token in _STOPWORDS or token in tokens:
            continue
        tokens.append(token)
    return tuple(tokens)


def _normalize_query_terms(
    query_terms: Sequence[str] | str,
) -> list[str]:
    if isinstance(query_terms, str):
        return [token for token in _TOKEN_PATTERN.findall(query_terms.lower()) if token]
    tokens: list[str] = []
    for term in query_terms:
        if not term:
            continue
        for token in _TOKEN_PATTERN.findall(str(term).lower()):
            if token and token not in tokens:
                tokens.append(token)
    return tokens


def _score_label(label: str, tokens: Sequence[str], combined_query: str) -> float:
    if not label:
        return 0.0
    combined_score = fuzz.token_set_ratio(combined_query, label) / 100
    weighted_max = _weighted_token_max(label, tokens)
    return max(combined_score, weighted_max)


def _score_alias(alias: str, tokens: Sequence[str]) -> float:
    return _weighted_token_max(alias, tokens)


def _weighted_token_max(label: str, tokens: Sequence[str]) -> float:
    score = 0.0
    for index, token in enumerate(tokens):
        weight = max(0.2, 1.0 - index * 0.15)
        score = max(score, weight * (fuzz.partial_ratio(token, label) / 100))
    return score


__all__ = ["ParsedExpense", "parse_expense_text", "rank_account_candidates"]
