"""Unit tests for expense parsing helpers and account ranking."""

from __future__ import annotations

from decimal import Decimal

import pytest

from expense_bot.graph.state import AccountCandidate
from expense_bot.parsing.expense import ParsedExpense, parse_expense_text, rank_account_candidates


def test_parse_expense_text_extracts_amount_currency_and_hints() -> None:
    result = parse_expense_text(
        "Paid $10 cash for taxi", default_currency="USD", source_message_id="42"
    )

    assert isinstance(result, ParsedExpense)
    assert result.amount == Decimal("10")
    assert result.currency == "USD"
    assert result.narration == "Paid $10 cash for taxi"
    assert result.debit_hint == "taxi"
    assert result.credit_hint == "cash"
    assert "taxi" in result.keywords and "cash" in result.keywords
    assert result.source_message_id == "42"
    assert result.missing_fields == set()


def test_parse_expense_text_flags_missing_components_when_absent() -> None:
    result = parse_expense_text(
        "Booked a hotel using corporate card", default_currency="USD"
    )

    assert result.amount is None
    assert result.currency == "USD"
    assert result.debit_hint is None
    assert result.credit_hint == "corporate card"
    assert "amount" in result.missing_fields
    assert "debit_account" in result.missing_fields


def test_rank_account_candidates_prioritizes_alias_matches() -> None:
    accounts = [
        {"account_code": "5110", "account_name": "Taxi Expense - HQ", "aliases": ["Taxi", "Ground Travel"]},
        {"account_code": "5120", "account_name": "Travel Meals - HQ", "aliases": ["Meals"]},
        {"account_code": "1000", "account_name": "Cash - HQ", "aliases": ["Cash on Hand", "Cash"]},
    ]

    results = rank_account_candidates(
        query_terms=["taxi", "cash"],
        accounts=accounts,
        limit=3,
        min_confidence=0.4,
    )

    assert [candidate.account_code for candidate in results[:2]] == ["5110", "1000"]
    assert results[0].confidence > results[1].confidence
    assert all(isinstance(candidate, AccountCandidate) for candidate in results)


def test_rank_account_candidates_applies_minimum_confidence_threshold() -> None:
    accounts = [
        {"account_code": "5110", "account_name": "Taxi Expense - HQ"},
        {"account_code": "1000", "account_name": "Cash - HQ"},
    ]

    results = rank_account_candidates(
        query_terms="office supplies",
        accounts=accounts,
        min_confidence=0.75,
    )

    assert results == []
