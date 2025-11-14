"""Telegram Application factory and handler helpers."""

from __future__ import annotations

from functools import partial
from typing import Any, Awaitable, Callable, Iterable, Literal, Sequence

from langgraph.graph.state import CompiledStateGraph
from langsmith import traceable
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, BaseHandler, ContextTypes

from expense_bot import get_logger
from expense_bot.config import Settings, get_settings
from expense_bot.graph.state import ConversationState, ExpenseDraft
from expense_bot.integrations.logging import ConversationLoggingHooks, generate_attempt_id
from expense_bot.integrations.telegram_auth import (
    DeniedCallback,
    HandlerCallable,
    TelegramAuthorizationMiddleware,
)

LOGGER = get_logger("integrations.telegram")
MIDDLEWARES_KEY = "expense_bot.telegram.middlewares"
LOGGING_HOOKS_KEY = "expense_bot.logging.hooks"
GRAPH_KEY = "expense_bot.state_graph"
SETTINGS_KEY = "expense_bot.settings"
ATTEMPT_IDS_KEY = "expense_bot.attempt_ids"

CLARIFICATION_LABELS: dict[str, str] = {
    "amount": "amount",
    "debit_account": "debit account",
    "credit_account": "credit account",
}
CONFIRMATION_PROMPT = (
    "Reply with confirm to post, edit to change the draft, or cancel to abort."
)

MiddlewareCallable = Callable[[HandlerCallable, Any, dict[str, Any]], Awaitable[Any]]


def create_application(
    *,
    settings: Settings | None = None,
    allowed_user_ids: Iterable[int] | None = None,
    on_denied: DeniedCallback | None = None,
    middlewares: Sequence[MiddlewareCallable] | None = None,
    logging_hooks: ConversationLoggingHooks | None = None,
) -> Application:
    """Return a python-telegram-bot Application with middleware metadata."""

    resolved_settings = settings or get_settings()
    token = resolved_settings.telegram_token.get_secret_value()
    application = ApplicationBuilder().token(token).build()

    middleware_stack: list[MiddlewareCallable] = list(middlewares or [])
    auth_ids = list(allowed_user_ids) if allowed_user_ids is not None else list(
        resolved_settings.telegram_allowed_users
    )
    if auth_ids:
        deny_callback = on_denied or partial(
            _default_denied_callback, bot=application.bot
        )
        middleware_stack.insert(
            0, TelegramAuthorizationMiddleware(auth_ids, on_denied=deny_callback)
        )

    application.bot_data[MIDDLEWARES_KEY] = tuple(middleware_stack)
    set_logging_hooks(application, logging_hooks)
    LOGGER.info(
        "Telegram application ready with %d middleware(s).",
        len(middleware_stack),
    )
    return application


def register_handler(
    application: Application,
    handler: BaseHandler[Any, Any, Any],
    *,
    group: int = 0,
    protected: bool = True,
    extra_middlewares: Sequence[MiddlewareCallable] | None = None,
) -> None:
    """Register handler while automatically wrapping the configured middlewares."""

    middlewares = list(extra_middlewares or [])
    if protected:
        middlewares.extend(_get_application_middlewares(application))
    if middlewares:
        _apply_middlewares(handler, middlewares)
    application.add_handler(handler, group=group)


def _get_application_middlewares(application: Application) -> tuple[MiddlewareCallable, ...]:
    stored = application.bot_data.get(MIDDLEWARES_KEY, ())
    if isinstance(stored, tuple):
        return stored
    return tuple(stored)


def _apply_middlewares(
    handler: BaseHandler[Any, Any, Any],
    middlewares: Sequence[MiddlewareCallable],
) -> None:
    original_callback = handler.callback

    async def terminal(update: Update, data: dict[str, Any]) -> Any:
        context = data["context"]
        return await original_callback(update, context)

    chained = _wrap_handler_callable(terminal, middlewares)

    async def wrapped_callback(update: Update, context: Any) -> Any:
        data = {
            "context": context,
            "application": getattr(context, "application", None),
            "bot": getattr(context, "bot", None),
        }
        return await chained(update, data)

    handler.callback = wrapped_callback


def set_logging_hooks(
    application: Application, hooks: ConversationLoggingHooks | None
) -> None:
    """Attach logging hooks so Telegram handlers can emit audit events."""

    application.bot_data[LOGGING_HOOKS_KEY] = hooks


def get_logging_hooks(source: Any) -> ConversationLoggingHooks | None:
    """Return logging hooks from an Application or CallbackContext."""

    application = source if isinstance(source, Application) else getattr(
        source, "application", None
    )
    if application is None:
        return None
    hooks = application.bot_data.get(LOGGING_HOOKS_KEY)
    if isinstance(hooks, ConversationLoggingHooks):
        return hooks
    return None


def _wrap_handler_callable(
    handler: HandlerCallable, middlewares: Sequence[MiddlewareCallable]
) -> HandlerCallable:
    wrapped = handler
    for middleware in reversed(middlewares):
        previous = wrapped

        async def _call(
            update: Any,
            data: dict[str, Any],
            *,
            middleware: MiddlewareCallable = middleware,
            next_handler: HandlerCallable = previous,
        ) -> Any:
            return await middleware(next_handler, update, data)

        wrapped = _call
    return wrapped


async def _default_denied_callback(
    update: Update,
    user_id: int | None,
    *,
    bot: Any,
) -> None:
    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None)
    LOGGER.warning("Unauthorized Telegram access user_id=%s chat_id=%s", user_id, chat_id)
    if chat_id is None or bot is None:
        return
    try:
        await bot.send_message(
            chat_id,
            "You are not authorized to use this bot. Please contact a finance administrator.",
        )
    except Exception:  # pragma: no cover - depends on network state
        LOGGER.exception("Failed to notify unauthorized user_id=%s", user_id)


def _resolve_application(source: Any) -> Application | None:
    if isinstance(source, Application):
        return source
    application = getattr(source, "application", None)
    if isinstance(application, Application):
        return application
    candidate = source if hasattr(source, "bot_data") else None
    if candidate is not None:
        return candidate
    if application is not None and hasattr(application, "bot_data"):
        return application  # type: ignore[return-value]
    return None


def set_state_graph(
    application: Application, graph: CompiledStateGraph[ConversationState, Any, Any, Any]
) -> None:
    """Store the compiled LangGraph inside the Application for handler reuse."""

    application.bot_data[GRAPH_KEY] = graph


def get_state_graph(source: Any) -> CompiledStateGraph[ConversationState, Any, Any, Any] | None:
    """Retrieve the compiled LangGraph associated with the Application."""

    application = _resolve_application(source)
    if application is None:
        return None
    graph = application.bot_data.get(GRAPH_KEY)
    return graph  # type: ignore[return-value]


def set_application_settings(application: Application, settings: Settings) -> None:
    """Attach shared Settings to the Application for easy lookup."""

    application.bot_data[SETTINGS_KEY] = settings


def get_application_settings(source: Any) -> Settings:
    """Return the Settings instance stored on the Application or fall back to env."""

    application = _resolve_application(source)
    if application:
        stored = application.bot_data.get(SETTINGS_KEY)
        if isinstance(stored, Settings):
            return stored
    return get_settings()


def _store_attempt_id(application: Application, thread_id: str, attempt_id: str) -> None:
    mapping = application.bot_data.setdefault(ATTEMPT_IDS_KEY, {})
    if isinstance(mapping, dict):
        mapping[thread_id] = attempt_id


def _get_attempt_id(application: Application, thread_id: str) -> str | None:
    mapping = application.bot_data.get(ATTEMPT_IDS_KEY)
    if isinstance(mapping, dict):
        return mapping.get(thread_id)
    return None


ResponseEvent = Literal["preview", "confirmation", "cancellation"]


def _make_thread_id(chat_id: int | None) -> str | None:
    return f"telegram:{int(chat_id)}" if chat_id is not None else None


def _langsmith_extra_for_update(event: str, update: Update) -> dict[str, Any]:
    text, chat_id, user_id, message_id = _extract_message_data(update)
    thread_id = _make_thread_id(chat_id)
    metadata: dict[str, Any] = {
        "event": event,
        "thread_id": thread_id,
        "chat_id": chat_id,
        "telegram_user_id": user_id,
        "telegram_message_id": message_id,
    }
    snippet = (text or "").strip()
    if snippet:
        metadata["message_snippet"] = snippet[:200]
    filtered_metadata = {key: value for key, value in metadata.items() if value is not None}
    return {
        "metadata": filtered_metadata,
        "tags": ["telegram", f"event:{event}"],
    }


def _extract_message_data(update: Update) -> tuple[str | None, int | None, int | None, int | None]:
    message = getattr(update, "message", None) or getattr(update, "edited_message", None)
    text = getattr(message, "text", None) if message is not None else None
    text = text.strip() if isinstance(text, str) and text.strip() else None
    chat = getattr(update, "effective_chat", None) or getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    user = getattr(update, "effective_user", None) or getattr(message, "from_user", None)
    user_id = getattr(user, "id", None)
    message_id = getattr(message, "message_id", None)
    return text, chat_id, user_id, message_id


async def _reply_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    chat_id: int | None,
) -> None:
    if not text:
        return
    target = getattr(update, "effective_message", None)
    if target is not None and hasattr(target, "reply_text"):
        await target.reply_text(text)
        return
    if chat_id is not None:
        await context.bot.send_message(chat_id=chat_id, text=text)


def _format_preview(draft: ExpenseDraft) -> str:
    amount = f"{draft.amount:.2f}"
    narration = draft.narration or "No description provided."
    lines = [
        "Here is your expense draft:",
        f"- Amount: {amount} {draft.currency}",
        f"- Debit account: {draft.debit_account.display_name}",
        f"- Credit account: {draft.credit_account.display_name}",
        f"- Narration: {narration}",
        "",
        CONFIRMATION_PROMPT,
    ]
    return "\n".join(lines)


def _format_clarification(missing_fields: Sequence[str]) -> str:
    labels = [CLARIFICATION_LABELS.get(field, field.replace("_", " ")) for field in missing_fields]
    return (
        "I still need the following detail(s) to draft your expense: "
        f"{', '.join(labels)}. Please include them in your next message."
    )


def _format_confirmation(state: ConversationState) -> str:
    submission = state.erpnext_submission
    reference = ""
    if submission is not None:
        link = submission.link or submission.journal_entry_id
        if link:
            reference = f" (ERPNext reference: {link})"
    return f"Expense confirmed and queued for ERPNext{reference}. Send another message when you're ready for the next entry."


def _format_cancellation(state: ConversationState) -> str:
    reason = state.error_log[-1] if state.error_log else None
    extra = f" Reason: {reason}" if reason else ""
    return f"Expense attempt cancelled.{extra} You can start over by sending a new message."


def _format_errors(errors: Sequence[str]) -> str | None:
    if not errors:
        return None
    return "\n".join(errors)


def _append_error(original: str | None, error_text: str | None) -> str | None:
    if not original:
        return error_text
    if not error_text:
        return original
    return f"{original}\n\n{error_text}"


def _render_telegram_response(state: ConversationState) -> tuple[str | None, ResponseEvent | None, dict[str, Any]]:
    error_text = _format_errors(state.error_log)
    if state.confirmation_status == "approved":
        message = _format_confirmation(state)
        payload = {"summary": message}
        return _append_error(message, error_text), "confirmation", payload
    if state.confirmation_status == "rejected" and state.expense_draft is None:
        message = _format_cancellation(state)
        payload = {"summary": message}
        return _append_error(message, error_text), "cancellation", payload
    if state.clarifications_needed:
        message = _format_clarification(state.clarifications_needed)
        payload = {"summary": message}
        return _append_error(message, error_text), None, payload
    if state.expense_draft and state.confirmation_status == "pending":
        message = _format_preview(state.expense_draft)
        payload = {"summary": message}
        return _append_error(message, error_text), "preview", payload
    if error_text:
        return error_text, None, {"summary": error_text}
    return None, None, {}


def _log_event(
    event: ResponseEvent | None,
    state: ConversationState,
    user_id: int | None,
    message_id: int | None,
    payload: dict[str, Any],
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if event is None or user_id is None or message_id is None:
        return
    hooks = get_logging_hooks(context)
    if hooks is None:
        return

    application = context.application
    thread_id = state.thread_id
    stored_attempt = _get_attempt_id(application, thread_id)
    attempt_id = stored_attempt or generate_attempt_id(thread_id)
    if stored_attempt is None:
        _store_attempt_id(application, thread_id, attempt_id)

    telegram_user_id = int(user_id)
    telegram_message_id = int(message_id)

    if event == "preview":
        hooks.log_preview(
            attempt_id=attempt_id,
            thread_id=thread_id,
            telegram_user_id=telegram_user_id,
            telegram_message_id=telegram_message_id,
            preview_json=payload,
            state=state,
        )
        return

    if event == "confirmation":
        erp_doc = state.erpnext_submission and state.erpnext_submission.journal_entry_id
        hooks.log_confirmation(
            attempt_id=attempt_id,
            thread_id=thread_id,
            telegram_user_id=telegram_user_id,
            telegram_message_id=telegram_message_id,
            preview_json=payload,
            state=state,
            erpnext_doc_id=erp_doc,
        )
        return

    if event == "cancellation":
        reason = state.error_log[-1] if state.error_log else "user_cancelled"
        hooks.log_cancellation(
            attempt_id=attempt_id,
            thread_id=thread_id,
            telegram_user_id=telegram_user_id,
            telegram_message_id=telegram_message_id,
            preview_json=payload,
            state=state,
            reason=reason,
        )


@traceable(run_type="tool", name="telegram.update")
async def _process_telegram_update(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    graph = get_state_graph(context)
    if graph is None:
        raise RuntimeError("LangGraph state graph is not configured for Telegram handlers.")

    text, chat_id, user_id, message_id = _extract_message_data(update)
    thread_id = _make_thread_id(chat_id)
    if not text or thread_id is None:
        return

    state = ConversationState(thread_id=thread_id)
    state.pending_message = text
    state.pending_message_id = str(message_id) if message_id is not None else None
    state.pending_user_id = user_id
    config: dict[str, dict[str, str]] = {"configurable": {"thread_id": thread_id}}

    try:
        raw_result = graph.invoke(state, config=config)
    except PermissionError as exc:
        await _reply_text(update, context, str(exc), chat_id)
        return
    except Exception as exc:
        LOGGER.exception("Telegram update failed to process", exc_info=exc)
        await _reply_text(
            update,
            context,
            "Sorry, I couldn't process that message right now. Please try again.",
            chat_id,
        )
        return

    if not isinstance(raw_result, dict):
        LOGGER.warning("LangGraph returned unexpected response: %s", raw_result)
        return

    try:
        conversation = ConversationState(**raw_result)
    except TypeError as exc:
        LOGGER.exception("Invalid conversation state returned by LangGraph", exc_info=exc)
        await _reply_text(
            update,
            context,
            "Internal error: unable to interpret the conversation state.",
            chat_id,
        )
        return

    response, event, payload = _render_telegram_response(conversation)
    if response:
        await _reply_text(update, context, response, chat_id)

    _log_event(event, conversation, user_id, message_id, payload, context)


async def handle_expense_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle free-form messages that describe an expense."""

    extra = _langsmith_extra_for_update("expense_message", update)
    await _process_telegram_update(update, context, langsmith_extra=extra)


async def handle_confirmation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle explicit confirmation replies from the user."""

    extra = _langsmith_extra_for_update("confirmation", update)
    await _process_telegram_update(update, context, langsmith_extra=extra)


async def handle_rejection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle explicit cancellation replies from the user."""

    extra = _langsmith_extra_for_update("rejection", update)
    await _process_telegram_update(update, context, langsmith_extra=extra)


__all__ = [
    "create_application",
    "get_logging_hooks",
    "register_handler",
    "set_logging_hooks",
    "MiddlewareCallable",
    "set_state_graph",
    "get_state_graph",
    "set_application_settings",
    "get_application_settings",
    "handle_expense_message",
    "handle_confirmation",
    "handle_rejection",
]
