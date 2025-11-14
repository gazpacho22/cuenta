# Research Notes

## Telegram Bot Integration

Decision: Use `python-telegram-bot` v21 async `Application` with long-polling for development and webhook handler extension for deployment.  
Rationale: Library is mature, supports asyncio (aligns with LangGraph async execution), handles retry/backoff, and maps cleanly to Telegram webhook security best practices. It also provides middlewares for auth and throttling needed for finance data.  
Alternatives considered: `aiogram` (excellent but steeper learning curve for beginners, fewer synchronous examples in LangChain modules), manual REST polling (lighter dependency but would require rebuilding update parsing, keyboards, and rate limiting).

## LangGraph Conversation Architecture

Decision: Model the assistant with a `StateGraph` capturing `messages`, `conversation_summary`, `expense_draft`, `clarifications_needed`, and `erpnext_submission` fields, using `LangGraph` conditional edges to branch between information gathering, account resolution, confirmation, and ERP submission nodes.  
Rationale: Mirrors module patterns (intent classifier → tool execution → human-in-the-loop) while keeping state explicit for auditing. Conditional edges let us loop for follow-up questions until the expense draft is complete before confirmation.  
Alternatives considered: A simple sequential chain (would complicate retries and branching for missing details), pure AgentExecutor (less transparent state management, harder to persist checkpoints), bespoke asyncio FSM (re-implements features LangGraph already provides).

## Memory Strategy

Decision: Persist conversation state with `langgraph.checkpoint.sqlite.SqliteSaver`, store the last 6 user/assistant messages in `messages`, and trigger a reducer node that summarizes older turns into `conversation_summary` when the window exceeds 6.  
Rationale: Aligns with course guidance on checkpoint savers, gives Copilot-style “recent history + summary”, and the SQLite backend survives restarts. Summaries keep token usage bounded while retaining context for long-running finance chats.  
Alternatives considered: Unlimited history (token blow-up, expensive OpenAI calls), custom Redis store (more ops overhead), LLM-based retrieval memory per query (unnecessary complexity for MVP).

## Account Resolution Tooling

Decision: Retrieve the full ERPNext chart of accounts on each expense turn and provide it directly to the LLM so it can choose debit/credit ledgers without local caching or embeddings.  
Rationale: Avoids reliance on OpenAI embedding APIs (currently unavailable) and keeps v1 simple while still giving the model all necessary data to pick accurate matches.  
Alternatives considered: Local caching + embeddings (deferred until embedding access issues resolved), fuzzy-matching heuristics (risk of incorrect ledger selection without semantic signals).

## ERPNext Journal Entry Integration

Decision: Use REST `POST /api/resource/Journal Entry` with bearer token auth (`token <api_key>:<api_secret>`), composing payloads with `accounts` debit/credit rows, `posting_date`, and custom fields storing the Telegram message ID + conversation URL; queue failures in SQLite for retry with exponential backoff up to 15 minutes.  
Rationale: ERPNext’s documented REST pattern is stable, works with the existing API credentials, and journal entries accept structured account rows. Persisting retries locally satisfies the clarification about outage handling.  
Alternatives considered: ERPNext GraphQL (not universally enabled), Frappe client library (adds dependency with minimal benefit), webhook-based custom DocType (more ERPNext customization than necessary).

## Testing Approach

Decision: Adopt `pytest` for unit/integration coverage and `pytest-bdd` for the Given/When/Then chat scenarios referenced in the spec.  
Rationale: Keeps the stack consistent (single test runner), integrates with fixtures for Telegram/ERP mocks, and lets us express BDD scenarios as inline Gherkin (materialized at runtime) that aligns with Constitution requirements.  
Alternatives considered: `behave` (separate runner complicates CI), plain pytest without BDD (violates Constitution), Robot Framework (overkill for Python-first repo).

## Deployment & Scaling Assumptions

Decision: Run the LangGraph + Telegram worker locally while connecting over HTTPS to the hosted ERPNext instance using existing API keys; continue targeting up to 50 concurrent users and 500 expenses/day.  
Rationale: Matches the current infra setup (cloud ERPNext, local bot runtime), keeps network boundaries simple, and still supports the expected pilot scale.  
Alternatives considered: Deploying the bot beside ERPNext in the cloud (adds ops work for v1), assuming offline ERPNext access (inaccurate given hosted instance).

## Documentation & Knowledge Sharing

Decision: Update `change_log.md` with a beginner-friendly summary after implementation sessions and extend onboarding docs with a Quickstart covering env setup, Telegram linking, and ERPNext tracing steps.  
Rationale: Satisfies Constitution Principles I & V and ensures stakeholders can track progress without inspecting code.  
Alternatives considered: Relying on inline code comments only (insufficient for onboarding), deferring documentation to post-implementation (risks omissions).
