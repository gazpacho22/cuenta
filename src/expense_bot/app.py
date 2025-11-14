"""CLI entrypoint for the AI expense chatbot."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlparse

from telegram.ext import MessageHandler, filters

from expense_bot import get_logger
from expense_bot.config import get_settings
from expense_bot.graph import build_state_graph
from expense_bot.graph.nodes import CANCEL_COMMANDS, CONFIRM_COMMANDS, EDIT_COMMANDS
from expense_bot.integrations import (
    ConversationLoggingHooks,
    ExpenseAttemptLogger,
    create_application,
    register_handler,
    set_application_settings,
    set_state_graph,
)
from expense_bot.integrations.telegram import (
    handle_confirmation,
    handle_expense_message,
    handle_rejection,
)

LOGGER = get_logger("app")
_DEFAULT_ATTEMPT_DB = Path("var/checkpoints/expense_attempts.sqlite")


class _WebhookMode:
    POLLING = "polling"
    WEBHOOK = "webhook"


def _build_command_pattern(commands: Iterable[str]) -> str:
    candidates = sorted({cmd.strip() for cmd in commands if cmd.strip()})
    if not candidates:
        return r"^$"
    escaped = "|".join(re.escape(candidate) for candidate in candidates)
    return rf"^\s*(?:{escaped})\s*$"


def _register_handlers(application) -> None:
    confirm_pattern = _build_command_pattern(CONFIRM_COMMANDS | EDIT_COMMANDS)
    cancel_pattern = _build_command_pattern(CANCEL_COMMANDS)

    confirm_filter = filters.Regex(re.compile(confirm_pattern, flags=re.IGNORECASE))
    cancel_filter = filters.Regex(re.compile(cancel_pattern, flags=re.IGNORECASE))
    control_filter = confirm_filter | cancel_filter

    register_handler(
        application,
        MessageHandler(confirm_filter, handle_confirmation),
    )
    register_handler(
        application,
        MessageHandler(cancel_filter, handle_rejection),
    )
    register_handler(
        application,
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & ~control_filter,
            handle_expense_message,
        ),
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Cuenta expense bot in polling or webhook mode."
    )
    parser.add_argument(
        "--mode",
        choices=(_WebhookMode.POLLING, _WebhookMode.WEBHOOK),
        default=_WebhookMode.POLLING,
        help="Bot execution mode (default: polling).",
    )
    parser.add_argument(
        "--listen",
        default="0.0.0.0",
        help="IP address or host to listen on when running the webhook server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8443,
        help="TCP port for the webhook listener (default: 8443).",
    )
    parser.add_argument(
        "--webhook-url",
        help="Full HTTPS URL Telegram should call when running in webhook mode.",
    )
    parser.add_argument(
        "--url-path",
        help="Override the path portion used by the webhook server (defaults to the path from --webhook-url).",
    )
    parser.add_argument(
        "--drop-pending-updates",
        action="store_true",
        help="Drop pending Telegram updates before starting (both modes).",
    )
    parser.add_argument(
        "--max-connections",
        type=int,
        default=40,
        help="Number of allowed simultaneous webhook connections (default: 40).",
    )
    args = parser.parse_args(argv)
    if args.mode == _WebhookMode.WEBHOOK and not args.webhook_url:
        parser.error("--webhook-url is required when --mode webhook")
    return args


def _normalize_url_path(path: str | None) -> str:
    if not path:
        return ""
    trimmed = path.strip()
    trimmed = trimmed.lstrip("/")
    trimmed = trimmed.rstrip("/")
    return trimmed


def _extract_path_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path or ""


def _resolve_webhook_path(webhook_url: str, override: str | None) -> str:
    candidate = override or _extract_path_from_url(webhook_url)
    return _normalize_url_path(candidate)


def _bool_flag(value: bool) -> bool | None:
    return True if value else None


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    settings = get_settings()

    attempt_db = _DEFAULT_ATTEMPT_DB
    attempt_logger = ExpenseAttemptLogger(attempt_db)
    logging_hooks = ConversationLoggingHooks(attempt_logger)

    application = create_application(
        settings=settings,
        logging_hooks=logging_hooks,
    )
    graph = build_state_graph(settings=settings)
    set_state_graph(application, graph)
    set_application_settings(application, settings)
    _register_handlers(application)

    drop_updates_value = _bool_flag(args.drop_pending_updates)
    try:
        if args.mode == _WebhookMode.POLLING:
            LOGGER.info("Starting Telegram polling (dropping pending=%s)", drop_updates_value)
            application.run_polling(drop_pending_updates=drop_updates_value)
            return
        webhook_path = _resolve_webhook_path(args.webhook_url, args.url_path)
        LOGGER.info(
            "Starting Telegram webhook listener on %s:%d/%s (webhook=%s)",
            args.listen,
            args.port,
            webhook_path or "",
            args.webhook_url,
        )
        application.run_webhook(
            listen=args.listen,
            port=args.port,
            webhook_url=args.webhook_url,
            url_path=webhook_path,
            drop_pending_updates=drop_updates_value,
            max_connections=args.max_connections,
            secret_token=settings.telegram_webhook_secret,
        )
    finally:
        attempt_logger.close()


if __name__ == "__main__":
    main()
