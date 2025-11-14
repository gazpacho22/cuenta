# Decision Record: LangGraph Async Checkpointing

## Context

This work is part of **Task T015** (“Wire capture-confirm flow with authorization guard inside StateGraph”). We are wiring LangGraph for the AI Expense Chatbot so Telegram conversations can be parsed, confirmed, logged, and resumed. Each turn must be checkpointed (SQLite) so crashes or retries do not lose state. Because the bot is expected to juggle multiple Telegram chats, the design goal was to keep the entire flow asynchronous: python-telegram-bot v21, httpx, LangGraph nodes, and the checkpoint saver should all yield control instead of blocking.

## Problem

As soon as we replaced the synchronous `SqliteSaver` with `AsyncSqliteSaver`, every LangGraph run began to hang indefinitely. The hang reproduced in:

- Our real graph (builder + nodes + state models)
- Minimal toy graphs (single node, int state)
- Both `ainvoke` and `astream_events`
- Direct scripts and pytest tests

The process produced no stack trace; it simply blocked until manually killed. Staying synchronous would serialize every Telegram user on the same thread, so we initially kept trying to unlock the async path.

## Investigation & Research

1. **Local experiments**
   - Wrapped every saver usage in `async with AsyncSqliteSaver.from_conn_string(...)`.
   - Ensured we only called async graph APIs (`ainvoke`, `astream_events`).
   - Added logging in entry/parse/resolve nodes to confirm nodes ran—the hang always occurred after node execution, during LangGraph shutdown/cleanup.

2. **Online research (GitHub issues)**
   - [`langgraph#789`](https://github.com/langchain-ai/langgraph/issues/789): Async saver hangs unless the connection is closed; recommended fixes are using `async with ...` or closing `memory.conn` manually.
   - [`langgraph#1800`](https://github.com/langchain-ai/langgraph/issues/1800) and [`#2992`](https://github.com/langchain-ai/langgraph/issues/2992): Mixing sync APIs (`invoke`, `get_state`) with an async checkpointer causes hangs.

   Even after adopting the recommended patterns (context manager + async-only calls) our environment still hung, matching those reports exactly.

## Attempted Solutions

| Attempt | Result |
| --- | --- |
| Keep synchronous `SqliteSaver` everywhere | Works, but blocks the event loop; unsuitable if many Telegram users chat concurrently. |
| Use `AsyncSqliteSaver` via context manager + async graph APIs | Hang reproduced in real graph and toy examples (no output, process never exits). |
| Run git-issue repro verbatim | Same hang; confirms it’s an upstream LangGraph issue on this stack. |
| Install/upgrade LangGraph + aiosqlite | Already on latest release; no improvement. |
| Investigate doc site | Confirms need for context manager, but no additional fix. |

## Current Status

- T015 remains **in progress**. The graph wiring is largely complete, but the async persistence requirement is blocked.
- Async checkpointing is **blocked** because LangGraph’s async saver never returns in this environment, even for toy graphs. Root cause is upstream (acknowledged in GitHub issues).
- To keep development moving, we will **fall back to the synchronous checkpoint saver** for now, even though it serializes conversations. Future work can revisit async persistence once LangGraph releases a fix/patch.
- Tests will also operate in synchronous mode (or use MemorySaver/mocks) so they remain stable.

## Next Steps

1. Reconfigure builder/tests to rely on `SqliteSaver` or `MemorySaver`.
2. Leave a TODO in the planner to revisit async persistence after LangGraph fixes the hang (track issue #789/#1800).
3. When ready, repeat the async migration using the context-manager pattern and ensure all graph calls remain async.
