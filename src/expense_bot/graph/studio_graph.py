"""LangGraph export used by LangGraph CLI / LangSmith Studio."""

from __future__ import annotations

from expense_bot.graph.builder import build_state_graph

# When serving via LangGraph CLI, let the platform manage persistence.
graph = build_state_graph(checkpointer=False)

__all__ = ["graph"]
