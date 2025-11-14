"""Authorization middleware for Telegram updates."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from telegram.ext import ApplicationHandlerStop

from expense_bot import get_logger

DeniedCallback = Callable[[Any, int | None], Awaitable[None]]
HandlerCallable = Callable[[Any, dict[str, Any]], Awaitable[Any]]

LOGGER = get_logger("integrations.telegram_auth")


class TelegramAuthorizationMiddleware:
    """Guards Telegram updates so only linked users reach downstream handlers."""

    def __init__(
        self,
        allowed_user_ids: Iterable[int] | None,
        *,
        on_denied: DeniedCallback | None = None,
    ) -> None:
        self._allowed_ids = (
            {int(user_id) for user_id in allowed_user_ids} if allowed_user_ids else set()
        )
        self._on_denied = on_denied

    async def __call__(
        self,
        handler: HandlerCallable,
        update: Any,
        data: dict[str, Any],
    ) -> Any:
        """Invoke the downstream handler if the Telegram user is authorized."""

        user_id = self._extract_user_id(update)
        if not self._is_authorized(user_id):
            LOGGER.warning(
                "Blocked Telegram update from unauthorized user_id=%s", user_id
            )
            await self._deny(update, user_id)
            raise ApplicationHandlerStop

        data["authorized_user_id"] = user_id
        return await handler(update, data)

    def _extract_user_id(self, update: Any) -> int | None:
        """Pull a Telegram user id from common Update sources."""

        effective_user = getattr(update, "effective_user", None)
        if effective_user is not None and hasattr(effective_user, "id"):
            return int(effective_user.id)

        message = getattr(update, "message", None)
        if message is not None:
            from_user = getattr(message, "from_user", None)
            if from_user is not None and hasattr(from_user, "id"):
                return int(from_user.id)

        callback_query = getattr(update, "callback_query", None)
        if callback_query is not None:
            from_user = getattr(callback_query, "from_user", None)
            if from_user is not None and hasattr(from_user, "id"):
                return int(from_user.id)

        return None

    def _is_authorized(self, user_id: int | None) -> bool:
        """Return True when the provided Telegram user id is in the allow list."""

        if user_id is None:
            return False
        return user_id in self._allowed_ids

    async def _deny(self, update: Any, user_id: int | None) -> None:
        """Call the denial callback (if provided) for blocked requests."""

        if self._on_denied is not None:
            await self._on_denied(update, user_id)


__all__ = ["TelegramAuthorizationMiddleware"]
