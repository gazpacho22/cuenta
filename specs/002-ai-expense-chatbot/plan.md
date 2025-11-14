# Implementation Plan: AI Expense Chatbot

**Branch**: `002-ai-expense-chatbot` | **Date**: 2025-11-07 | **Spec**: `/specs/002-ai-expense-chatbot/spec.md`
**Input**: Feature specification from `/specs/002-ai-expense-chatbot/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

Build a Telegram-facing assistant that interprets natural-language expense messages, keeps conversational context with LangGraph tooling, and posts confirmed entries to ERPNext via the Journal Entry API while echoing confirmations back to the user.

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: Python 3.11+ (per repo README)  
**Primary Dependencies**: LangGraph, LangChain Core/OpenAI, python-telegram-bot v21, httpx  
**Storage**: LangGraph SQLite checkpoint saver for conversations  
**Audit Logging**: Lightweight SQLite table `expense_attempts` storing per-attempt structured logs (attempt_id, thread_id, Telegram identifiers, preview payload, status/resolution, ERPNext doc id, errors) to satisfy FR-006/FR-011 without introducing external infrastructure  
**Testing**: pytest with pytest-bdd for GWT scenarios and integration mocks  
**Target Platform**: Linux server hosting Telegram bot webhook or long polling worker  
**Project Type**: Backend service (headless bot + LangGraph agent)  
**Performance Goals**: Median time from user message to ERPNext confirmation under 60 seconds (SC-002)  
**Constraints**: Must queue ERPNext failures with exponential backoff for up to 15 minutes; prioritize response quality over token cost even when sending the full chart of accounts each turn—latency trade-offs will be tracked via the expense_attempts log (latency_ms field); every successful posting must echo the ERPNext document reference back to the user (FR-009)  
**Scale/Scope**: Target pilot of ≤50 concurrent Telegram users and ≈500 expenses/day with headroom for horizontal scaling

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- BDD scenarios ✅ — Spec already lists Given/When/Then flows for priority stories; plan will map each to automated tests before implementation.
- Documentation deliverables ✅ — Will log each working session in `change_log.md` and extend onboarding/quickstart per Knowledge Sharing requirements.
- Quality gates ✅ — Lint with `ruff`, type-check with `mypy`, and run `pytest` (unit, integration, BDD); feature engineer owns local runs, CI mirrors the same commands.
- Scope ✅ — Focus remains on Telegram expense capture MVP; any additional tooling (e.g., account matching) will be justified when proposed.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/
└── expense_bot/
    ├── __init__.py
    ├── app.py                 # Telegram entrypoint (webhook/polling dispatcher)
    ├── config.py              # Env loading for Telegram & ERPNext credentials
    ├── graph/
    │   ├── __init__.py
    │   ├── builder.py         # LangGraph construction & memory wiring
    │   └── nodes.py           # Tool & conversational node implementations
    ├── integrations/
    │   ├── telegram.py        # Bot API helpers, message adapters
    │   ├── erpnext.py         # Journal entry client + retry queue
    │   ├── tools.py           # ERPNext chart lookup, account resolver tools
    │   └── logging.py         # ExpenseAttemptLog writer/query helpers (SQLite)
    ├── memory/
    │   ├── __init__.py
    │   └── reducers.py        # Conversation summarization/reducer logic
    └── prompts/
        └── expense.md         # System & tool prompts

tests/
├── bdd/
│   └── test_expense_flow_steps.py  # Inline Gherkin + Given/When/Then step bindings
├── integration/
│   ├── test_erpnext_client.py
│   └── test_telegram_adapter.py
└── unit/
    ├── test_account_resolver.py
    └── test_memory_reducer.py
```

**Structure Decision**: Adopt a `src/expense_bot` package for the Telegram/LangGraph service with dedicated subpackages for graph construction, integrations, memory, and prompts; pair with `tests/` subdirectories aligned to BDD, integration, and unit coverage.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
