"""LangGraph builder and checkpoint wiring for the expense bot."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from expense_bot import get_logger
from expense_bot.config import Settings, get_settings
from expense_bot.graph.nodes import (
    apply_confirmation_decision,
    cancel_expense_attempt,
    parse_expense_message,
    select_accounts_for_draft,
)
from expense_bot.graph.state import ConversationState
from expense_bot.integrations.tools import (
    ChartOfAccountsTool,
    create_chart_of_accounts_tool,
)

LOGGER = get_logger("graph.builder")
ENTRY_NODE = "conversation_entry"
PARSE_NODE = "parse_expense"
RESOLVE_NODE = "resolve_accounts"
CONFIRM_NODE = "confirm_or_cancel"


def create_sqlite_saver(
    *,
    settings: Settings | None = None,
    db_path: str | Path | None = None,
) -> SqliteSaver:
    """Return a SqliteSaver configured for LangGraph checkpoints."""

    resolved_settings = settings or get_settings()
    checkpoint_path = Path(db_path or resolved_settings.checkpoint_db).expanduser()
    checkpoint_path = checkpoint_path.resolve()
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    LOGGER.debug("Connecting SqliteSaver to %s", checkpoint_path)
    connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
    return SqliteSaver(connection)


def build_state_graph(
    *,
    settings: Settings | None = None,
    checkpointer: BaseCheckpointSaver[Any] | bool | None = None,
    chart_tool: ChartOfAccountsTool | None = None,
) -> CompiledStateGraph[ConversationState, Any, Any, Any]:
    """Compile the capture-confirm LangGraph wired to the SQLite checkpoint saver."""

    resolved_settings = settings or get_settings()
    catalog_tool = chart_tool or create_chart_of_accounts_tool(settings=resolved_settings)

    builder = StateGraph(ConversationState)
    builder.add_node(ENTRY_NODE, _create_entry_node(resolved_settings))
    builder.add_node(PARSE_NODE, _create_parse_node(resolved_settings))
    builder.add_node(RESOLVE_NODE, _create_resolve_node(catalog_tool))
    builder.add_node(CONFIRM_NODE, _handle_confirmation)

    builder.add_edge(START, ENTRY_NODE)
    builder.add_conditional_edges(
        ENTRY_NODE,
        _route_from_entry,
        path_map={"parse": PARSE_NODE, "confirm": CONFIRM_NODE},
    )
    builder.add_edge(PARSE_NODE, RESOLVE_NODE)
    builder.add_edge(RESOLVE_NODE, END)
    builder.add_edge(CONFIRM_NODE, END)

    memory: BaseCheckpointSaver[Any] | None
    if checkpointer is False:
        memory = None
    else:
        memory = checkpointer or create_sqlite_saver(settings=resolved_settings)
    graph = builder.compile(checkpointer=memory)
    db_location: str | Path | None = None
    if memory and hasattr(memory, "conn"):
        connection = getattr(memory, "conn")
        db_location = getattr(connection, "database", None)
    elif memory:
        db_location = memory.__class__.__name__
    LOGGER.info("LangGraph compiled with checkpoint database at %s", db_location)
    return graph


def _create_entry_node(
    settings: Settings,
) -> Callable[[ConversationState], ConversationState]:
    allowed_users: set[int] = {int(user_id) for user_id in settings.telegram_allowed_users}

    def _node(
        state: ConversationState,
    ) -> ConversationState:
        message_text = (state.pending_message or "").strip()
        if not message_text:
            raise ValueError("pending_message is required for graph execution.")
        user_id = state.pending_user_id
        LOGGER.debug("ENTRY_NODE thread=%s user=%s", state.thread_id, user_id)

        if allowed_users:
            if user_id is None or user_id not in allowed_users:
                LOGGER.warning(
                    "Blocked graph execution for unauthorized Telegram user_id=%s thread=%s",
                    user_id,
                    state.thread_id,
                )
                raise PermissionError(
                    "Telegram user is not authorized to capture expenses."
                )
        _append_user_message(
            state,
            message_text,
            state.pending_message_id,
            user_id=user_id,
        )
        return state

    return _node


def _create_parse_node(
    settings: Settings,
) -> Callable[[ConversationState], ConversationState]:
    default_currency = settings.default_currency

    def _node(
        state: ConversationState,
    ) -> ConversationState:
        message_text = (state.pending_message or "").strip()
        if not message_text:
            raise ValueError("pending_message is required before parsing.")
        source_id = state.pending_message_id

        parse_expense_message(
            state,
            message=message_text,
            default_currency=default_currency,
            source_message_id=source_id,
        )
        LOGGER.debug("PARSE_NODE thread=%s draft=%s", state.thread_id, state.expense_draft)
        state.pending_message = None
        state.pending_message_id = None
        return state

    return _node


def _create_resolve_node(
    chart_tool: ChartOfAccountsTool,
) -> Callable[[ConversationState], Any]:
    def _resolve(state: ConversationState) -> ConversationState:
        if state.expense_draft is None or state.clarifications_needed:
            return state

        chart_rows = _get_chart_override(state)
        if chart_rows is None:
            try:
                response = chart_tool.invoke({})
            except Exception as exc:  # pragma: no cover - network/state dependent
                LOGGER.exception("Failed to fetch chart of accounts: %s", exc)
                state.record_error(
                    "Unable to fetch the chart of accounts right now. Please try again."
                )
                return state
            chart_rows = _parse_chart_rows(response)

        if chart_rows is None:
            state.record_error("Chart of accounts response was empty.")
            return state

        try:
            select_accounts_for_draft(state, chart_of_accounts=chart_rows)
        except Exception as exc:  # pragma: no cover - defensive guard
            LOGGER.exception("Account resolution failed: %s", exc)
            state.record_error("Unable to resolve ledger accounts automatically.")
        LOGGER.debug(
            "RESOLVE_NODE thread=%s clarifications=%s",
            state.thread_id,
            state.clarifications_needed,
        )
        return state

    return _resolve


def _handle_confirmation(state: ConversationState) -> ConversationState:
    user_input = (state.pending_message or "").strip()
    if not user_input:
        state.record_error("Confirmation input is required.")
        return state

    decision = apply_confirmation_decision(state, user_input=user_input)
    state.pending_message = None
    state.pending_message_id = None
    if decision == "rejected":
        cancel_expense_attempt(state, reason="User cancelled the expense.")
    elif decision == "edit":
        cancel_expense_attempt(state, reason="User requested edits.")
        state.confirmation_status = "pending"
    return state


def _route_from_entry(state: ConversationState) -> Literal["parse", "confirm"]:
    if (
        state.expense_draft is not None
        and not state.clarifications_needed
        and state.confirmation_status == "pending"
    ):
        return "confirm"
    return "parse"


def _append_user_message(
    state: ConversationState,
    message_text: str,
    message_id: str | None,
    *,
    user_id: int | None,
) -> None:
    metadata: dict[str, Any] = {}
    if message_id:
        metadata["telegram_message_id"] = message_id
    if user_id is not None:
        metadata["telegram_user_id"] = user_id
    state.append_message(HumanMessage(content=message_text, additional_kwargs=metadata))


def _get_chart_override(state: ConversationState) -> Sequence[Mapping[str, Any]] | None:
    override = state.chart_of_accounts_override
    if not override:
        return None
    rows = [row for row in override if isinstance(row, Mapping)]
    state.chart_of_accounts_override = None
    return rows or None


def _parse_chart_rows(payload: Any) -> Sequence[Mapping[str, Any]] | None:
    if isinstance(payload, Mapping):
        accounts = payload.get("accounts")
        if isinstance(accounts, Sequence) and not isinstance(accounts, (str, bytes)):
            rows = [row for row in accounts if isinstance(row, Mapping)]
            return rows or None
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        rows = [row for row in payload if isinstance(row, Mapping)]
        return rows or None
    return None


__all__ = ["build_state_graph", "create_sqlite_saver", "ENTRY_NODE"]
