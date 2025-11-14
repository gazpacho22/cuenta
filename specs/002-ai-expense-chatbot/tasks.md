# Tasks: AI Expense Chatbot

**Input**: Design documents from `/specs/002-ai-expense-chatbot/`  
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/  
**Tests**: BDD + integration coverage required per Constitution and spec; tasks below place tests before implementation.  
**Organization**: Tasks grouped by user story so each slice is independently deliverable and testable.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish repository scaffolding, dependencies, and environment configuration.

- [X] T001 Update dependencies for LangGraph, LangChain Core, python-telegram-bot==21.*, httpx, RapidFuzz, and pytest-bdd in requirements.txt
- [X] T002 Create environment template with Telegram, ERPNext, OpenAI, and company settings in .env.example
- [X] T003 Create package root with module docstring and logger bootstrap in src/expense_bot/__init__.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Implement shared infrastructure for configuration, state, and integrations that all stories require.

- [X] T004 Implement typed settings loader using Pydantic BaseSettings in src/expense_bot/config.py
- [X] T005 [P] Define ConversationState, ExpenseDraft, AccountCandidate, and RetryJob dataclasses in src/expense_bot/graph/state.py
- [X] T005a [P] Capture ERPNext outage + retry expectations as inline Gherkin within tests/bdd/test_foundational_resilience_steps.py covering queueing, 15-minute backoff, and user notifications.
- [X] T005b [P] Add integration tests for ERPNextClient authentication, chart retrieval, and failure retries in tests/integration/test_erpnext_foundation.py.
- [X] T005c [P] Add unit tests for RetryJob SQLite repository CRUD + locking semantics in tests/unit/test_retry_queue.py.
- [X] T005d [P] Add unit tests for Telegram authorization middleware that blocks unlinked users in tests/unit/test_telegram_auth.py.
- [X] T005e [P] Add BDD scenario that verifies every preview/edit/cancel action records a structured log entry threaded by attempt_id in tests/bdd/test_audit_logging_steps.py.
- [X] T005f [P] Add integration test that simulates multiple edits and asserts the SQLite expense_attempts table stores thread_id + resolution fields in tests/integration/test_expense_logging.py.
- [X] T005g [P] Add unit tests for the logging writer serialization (summary JSON, status transitions) in tests/unit/test_expense_attempt_logger.py.
- [X] T005h [P] Add unit tests verifying latency_ms calculation is captured for each posted attempt in tests/unit/test_expense_attempt_logger.py.
- [X] T006 Implement ERPNextClient with authenticated requests, post_journal_entry stub, and fetch_chart_of_accounts function in src/expense_bot/integrations/erpnext.py
- [X] T007 Create SQLite retry repository matching RetryJob schema in src/expense_bot/integrations/retry_queue.py
- [X] T008 Set up LangGraph SqliteSaver wiring and placeholder StateGraph builder in src/expense_bot/graph/builder.py
- [X] T009 Scaffold Telegram Application factory with auth middleware hooks in src/expense_bot/integrations/telegram.py
- [X] T009a Implement expense_attempts SQLite logging module with append-only writes and thread-aware IDs in src/expense_bot/integrations/logging.py.
- [X] T009b Wire logging hooks into graph nodes/Telegram handlers so previews, confirmations, retries, and cancellations emit structured entries referencing ERPNext doc IDs.
- [X] T009c Record latency_ms between user confirmation and ERPNext completion in the logging hooks so SC-002 monitoring data exists even while sending full charts each turn.

---

## Phase 3: User Story 1 - Capture Expense via Telegram (Priority: P1) 🎯 MVP

**Goal**: Allow authorized Telegram users to describe an expense and confirm posting to ERPNext.  
**Independent Test**: Send "Paid $10 cash for taxi", confirm the summary, and verify ERPNext receives a balanced journal entry while the bot replies with the document reference.

### Tests for User Story 1

- [X] T010 [P] [US1] Author capture + confirmation BDD scenario in tests/bdd/test_expense_flow_steps.py
- [X] T011 [P] [US1] Create ERPNext posting integration test validating 200 response handling in tests/integration/test_erpnext_client.py
- [X] T012 [P] [US1] Create unit tests for expense parsing and account candidate ranking in tests/unit/test_expense_parser.py
- [X] T010a [P] [US1] Extend BDD coverage to assert the bot shares the ERPNext document reference after a successful posting in tests/bdd/test_expense_flow_steps.py.
- [X] T011a [P] [US1] Add integration test ensuring ERPNextClient propagates returned document IDs through the LangGraph flow to the messenger layer in tests/integration/test_erpnext_doc_reference.py.

### Implementation for User Story 1

- [X] T013 [US1] Implement chart-of-accounts LangGraph tool invoking fetch_chart_of_accounts on every turn in src/expense_bot/integrations/tools.py
- [X] T014 [US1] Implement LangGraph nodes for parsing, account selection, confirmation, and cancellation handling in src/expense_bot/graph/nodes.py
- [X] T015 [US1] Wire capture-confirm flow with authorization guard inside StateGraph in src/expense_bot/graph/builder.py
- [X] T015a [US1] Persist ERPNext document identifiers in ConversationState once posting succeeds so downstream nodes/logging can reference them.
- [X] T016 [US1] Implement Telegram handlers for expense messages, confirmations, and rejections in src/expense_bot/integrations/telegram.py
- [X] T017 [US1] Build CLI entrypoint supporting polling and webhook modes in src/expense_bot/app.py
- [ ] T016a [US1] Ensure Telegram confirmation replies include the ERPNext document identifier and durable links once posting succeeds.

---

## Phase 4: User Story 2 - Guide Missing Details (Priority: P2)

**Goal**: Prompt users to fill missing or invalid expense details and explain ERPNext rejections.  
**Independent Test**: Send "Paid the taxi", supply missing fields when prompted, and observe either a successful journal entry or actionable error message.

### Tests for User Story 2

- [ ] T018 [P] [US2] Add BDD scenarios for missing amount, unknown account, and ERPNext rejection flows in tests/bdd/test_missing_details_steps.py
- [ ] T019 [P] [US2] Add integration test covering retry scheduling after ERPNext failure in tests/integration/test_expense_retries.py
- [ ] T020 [P] [US2] Add unit tests for clarifications_needed reducer logic in tests/unit/test_clarifications.py

### Implementation for User Story 2

- [ ] T021 [US2] Extend nodes to request and merge missing amount/account responses in src/expense_bot/graph/nodes.py
- [ ] T022 [US2] Update StateGraph transitions to loop on clarifications before confirmation in src/expense_bot/graph/builder.py
- [ ] T023 [US2] Enhance ERPNextClient to enqueue RetryJob records and surface failure reasons in src/expense_bot/integrations/erpnext.py
- [ ] T024 [US2] Update Telegram adapter to deliver clarification prompts and failure notifications in src/expense_bot/integrations/telegram.py

---

## Phase 5: User Story 3 - Retain Conversation Trail (Priority: P3)

**Goal**: Preserve Telegram conversation context with each ERPNext expense for audit review.  
**Independent Test**: Approve an expense and verify the ERPNext journal entry references the original Telegram message plus conversation summary.

### Tests for User Story 3

- [ ] T025 [P] [US3] Add BDD scenario validating audit metadata in tests/bdd/test_audit_trail_steps.py
- [ ] T026 [P] [US3] Add integration test ensuring journal entry payload stores Telegram IDs in tests/integration/test_audit_metadata.py
- [ ] T027 [P] [US3] Add unit tests for conversation summary reducer in tests/unit/test_memory_reducer.py

### Implementation for User Story 3

- [ ] T028 [US3] Persist conversation_summary and source_message_id fields in ConversationState updates in src/expense_bot/graph/state.py
- [ ] T029 [US3] Append Telegram transcript metadata to journal entry payloads in src/expense_bot/integrations/erpnext.py
- [ ] T030 [US3] Implement reducer that rolls older messages into conversation_summary in src/expense_bot/memory/reducers.py

---

## Final Phase: Polish & Cross-Cutting Concerns

**Purpose**: Harden observability, documentation, and rollout guidance across all stories.

- [ ] T031 [P] Add structured logging and error reporting hooks across bot startup in src/expense_bot/app.py
- [ ] T032 [P] Update README.md with Telegram linking, retry queue monitoring, and audit review instructions
- [ ] T033 [P] Log feature summary, test commands, and deployment notes in change_log.md

---

## Dependencies & Execution Order

- **Phase sequence**: Complete Setup (T001–T003) before Foundational (T004–T009). Finish Foundational prior to starting US1 tasks (T010–T017). US2 (T018–T024) builds on US1’s flow, and US3 (T025–T030) depends on US1 + US2 to enrich audit data. Polish tasks (T031–T033) land last.
- **Critical task links**:
  - T006 depends on T004 for credential loading.
  - T013 relies on T006 for ERPNextClient access to fetch_chart_of_accounts.
  - T021 and T022 extend the nodes and builder created in T014 and T015.
  - T028–T030 extend state and memory components introduced by T005 and T014.
- **Story independence**: Each user story phase concludes with its tests passing, ensuring deployable increments before moving on.

---

## Parallel Execution Examples

- **User Story 1**: T010, T011, and T012 can be authored in parallel before implementation; once tests exist, execute T013 → T014 → T015 sequentially, then T016 and T017.
- **User Story 2**: T018, T019, and T020 can proceed concurrently; follow with T021 → T022 → T023 → T024.
- **User Story 3**: T025, T026, and T027 can run together; after that, complete T028 → T029 → T030.
- **Shared phases**: T005 can begin while T004 is in progress, and T031–T033 can be divided among team members after all story work is complete.

---

## Implementation Strategy

### MVP First (User Story 1)
013d
1. Execute T001–T009 to establish the foundation.  
2. Deliver T010–T017 and confirm all US1 tests pass.  
3. Deploy or demo the Telegram capture flow as the initial MVP.

### Incremental Delivery

1. With US1 stable, implement T018–T024 to add guidance and retry handling.  
2. Next, complete T025–T030 to satisfy audit requirements.  
3. Finish with T031–T033 to polish logging, documentation, and rollout notes.

### Parallel Team Strategy

1. Split Setup/Foundational tasks among team members (T001–T009).  
2. After US1 tests are drafted, one engineer owns T013–T017 while others progress US2 tests (T018–T020).  
3. Once US1 is merged, dedicate streams to US2 implementation (T021–T024) and US3 test preparation (T025–T027).  
4. Reconverge for US3 implementation (T028–T030) and collectively wrap up Polish tasks (T031–T033).
