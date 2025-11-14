"""Tests for the Telegram application factory helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import ApplicationHandlerStop, TypeHandler

from expense_bot.config import Settings
from expense_bot.integrations.telegram import (
    MIDDLEWARES_KEY,
    create_application,
    register_handler,
)
from expense_bot.integrations.telegram_auth import TelegramAuthorizationMiddleware


@pytest.fixture(name="anyio_backend")
def _anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def base_settings(tmp_path) -> Settings:
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    return Settings.model_validate(
        {
            "TELEGRAM_TOKEN": "123:ABC",
            "TELEGRAM_WEBHOOK_SECRET": "secret",
            "TELEGRAM_ALLOWED_USERS": [111],
            "ERP_BASE_URL": "https://erp.test",
            "ERP_API_KEY": "key",
            "ERP_API_SECRET": "secret",
            "DEFAULT_COMPANY": "Cuenta HQ",
            "DEFAULT_CURRENCY": "USD",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_MODEL": "gpt-4o-mini",
            "CHECKPOINT_DB": str(db_dir / "checkpoint.sqlite"),
            "RETRY_DB": str(db_dir / "retry.sqlite"),
            "LOG_LEVEL": "INFO",
        }
    )


@pytest.mark.anyio()
async def test_create_application_attaches_auth_middleware(base_settings: Settings) -> None:
    app = create_application(settings=base_settings)

    stack = app.bot_data[MIDDLEWARES_KEY]
    assert len(stack) == 1
    assert isinstance(stack[0], TelegramAuthorizationMiddleware)


class RecordingMiddleware:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, handler, update, data):  # type: ignore[override]
        self.calls += 1
        data["recorded"] = True
        return await handler(update, data)


@pytest.mark.anyio()
async def test_register_handler_wraps_callback_with_middlewares(
    base_settings: Settings,
) -> None:
    recording = RecordingMiddleware()
    app = create_application(
        settings=base_settings.model_copy(update={"telegram_allowed_users": []}),
        middlewares=(recording,),
    )
    callback = AsyncMock(return_value="ok")
    handler = TypeHandler(object, callback)

    register_handler(app, handler)
    registered = app.handlers[0][0]

    context = SimpleNamespace(application=app, bot=app.bot)
    result = await registered.callback(object(), context)

    callback.assert_awaited_once()
    assert recording.calls == 1
    assert result == "ok"


def _update_with_user(user_id: int | None):
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id))


@pytest.mark.anyio()
async def test_authorization_middleware_blocks_unlisted_user(base_settings: Settings) -> None:
    app = create_application(settings=base_settings)
    callback = AsyncMock()
    handler = TypeHandler(object, callback)

    register_handler(app, handler)
    registered = app.handlers[0][0]
    context = SimpleNamespace(application=app, bot=app.bot)

    with pytest.raises(ApplicationHandlerStop):
        await registered.callback(_update_with_user(555), context)
    callback.assert_not_called()

    await registered.callback(_update_with_user(111), context)
    callback.assert_awaited_once()


@pytest.mark.anyio()
async def test_unprotected_handler_skips_middlewares(base_settings: Settings) -> None:
    app = create_application(settings=base_settings)
    callback = AsyncMock(return_value="ok")
    handler = TypeHandler(object, callback)

    register_handler(app, handler, protected=False)
    registered = app.handlers[0][0]
    context = SimpleNamespace(application=app, bot=app.bot)

    result = await registered.callback(_update_with_user(555), context)

    callback.assert_awaited_once()
    assert result == "ok"
