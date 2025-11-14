"""Unit tests for the Telegram authorization middleware."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import ApplicationHandlerStop

from expense_bot.integrations.telegram_auth import TelegramAuthorizationMiddleware


@pytest.fixture(name="anyio_backend")
def _anyio_backend() -> str:
    """Force anyio plugin to use asyncio backend for predictable tests."""

    return "asyncio"


def _make_update(
    *,
    user_id: int | None,
    source: str = "effective",
) -> SimpleNamespace:
    """Build a lightweight Update facsimile for middleware tests."""

    update = SimpleNamespace(effective_user=None, message=None, callback_query=None)
    user = SimpleNamespace(id=user_id) if user_id is not None else None
    if source == "effective":
        update.effective_user = user
    elif source == "message":
        update.message = SimpleNamespace(from_user=user)
    elif source == "callback":
        update.callback_query = SimpleNamespace(from_user=user)
    else:
        raise ValueError(f"Unknown source {source}")
    return update


@pytest.mark.anyio()
async def test_authorized_user_reaches_handler() -> None:
    middleware = TelegramAuthorizationMiddleware([111])
    handler = AsyncMock(return_value="ok")
    update = _make_update(user_id=111)
    data: dict[str, object] = {}

    result = await middleware(handler, update, data)

    handler.assert_awaited_once_with(update, data)
    assert result == "ok"
    assert data["authorized_user_id"] == 111


@pytest.mark.anyio()
async def test_unauthorized_user_is_blocked() -> None:
    denied = AsyncMock()
    handler = AsyncMock()
    middleware = TelegramAuthorizationMiddleware([222], on_denied=denied)
    update = _make_update(user_id=999)
    data: dict[str, object] = {}

    with pytest.raises(ApplicationHandlerStop):
        await middleware(handler, update, data)

    handler.assert_not_called()
    denied.assert_awaited_once()
    assert denied.await_args.args == (update, 999)


@pytest.mark.anyio()
async def test_missing_user_information_is_denied() -> None:
    denied = AsyncMock()
    handler = AsyncMock()
    middleware = TelegramAuthorizationMiddleware([333], on_denied=denied)
    update = _make_update(user_id=None, source="message")
    data: dict[str, object] = {}

    with pytest.raises(ApplicationHandlerStop):
        await middleware(handler, update, data)

    handler.assert_not_called()
    denied.assert_awaited_once()
    assert denied.await_args.args == (update, None)


@pytest.mark.anyio()
async def test_message_source_used_when_effective_user_missing() -> None:
    middleware = TelegramAuthorizationMiddleware([444])
    handler = AsyncMock(return_value="ok")
    update = _make_update(user_id=444, source="message")
    data: dict[str, object] = {}

    result = await middleware(handler, update, data)

    handler.assert_awaited_once_with(update, data)
    assert result == "ok"
    assert data["authorized_user_id"] == 444
