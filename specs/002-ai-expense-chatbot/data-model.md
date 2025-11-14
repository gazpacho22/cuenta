# Data Model

## Overview

The assistant keeps user-facing state inside LangGraph checkpoints and persists ERPNext retry jobs in SQLite. Every structure below uses beginner-friendly names so the finance team can map conversation objects back to ERPNext journal entries.

## Entities

### ConversationState (LangGraph checkpoint)

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `thread_id` | `str` | Stable identifier derived from Telegram chat + user | Required, immutable |
| `messages` | `List[BaseMessage]` | Last six user/assistant turns | Auto-trimmed to ≤6 turns |
| `conversation_summary` | `str` | LLM-generated summary of older context | Regenerated whenever `messages` trims |
| `expense_draft` | [`ExpenseDraft`](#expensedraft) or `None` | Latest parsed expense candidate | Must be complete before confirmation |
| `clarifications_needed` | `List[str]` | Outstanding data gaps (amount, account, etc.) | Empty before posting to ERPNext |
| `account_candidates` | `List[AccountCandidate]` | Ranked choices for debit/credit accounts | Each score between 0 and 1 |
| `confirmation_status` | `Literal["pending","approved","rejected"]` | Tracks user disposition | `approved` requires explicit user ack |
| `erpnext_submission` | [`JournalEntryResult`](#journalentryresult) or `None` | Latest ERPNext API response metadata | Present only after successful post |
| `error_log` | `List[str]` | Human-readable errors surfaced to user | Cleared once resolved |
| `pending_message` | `str` or `None` | Latest raw Telegram text awaiting handling | Required for each graph run |
| `pending_message_id` | `str` or `None` | Telegram message identifier for audit/logging | Optional |
| `pending_user_id` | `int` or `None` | Telegram user id associated with the pending message | Used for authorization checks |
| `chart_of_accounts_override` | `List[dict]` or `None` | Optional chart data injected for testing/offline runs | Cleared after consumption |

### ExpenseDraft

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `amount` | `Decimal` | Monetary value expressed by user | Must be > 0 |
| `currency` | `str` | ISO currency (default from ERPNext company) | Must be supported by ERPNext |
| `debit_account` | `AccountMatch` | Selected expense ledger | Required before confirmation |
| `credit_account` | `AccountMatch` | Funding ledger (e.g., Cash) | Required before confirmation |
| `posting_date` | `date` | Defaults to today unless user specifies | Cannot exceed current date |
| `narration` | `str` | Free-text description / Telegram message | Sanitised to 500 chars |
| `attachments` | `List[AttachmentRef]` | File handles for receipts | Optional, stored via ERPNext file API |
| `source_message_id` | `str` | Telegram message ID for audit | Required |

### AccountCandidate

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `account_name` | `str` | Human-friendly ledger name | Required |
| `account_code` | `str` | ERPNext unique identifier | Required |
| `confidence` | `float` | Combined embedding + fuzzy score | 0.0 ≤ confidence ≤ 1.0 |
| `reason` | `str` | Short explanation shown to user | ≤120 chars |

### AccountMatch

| Field | Type | Description |
|-------|------|-------------|
| `account_code` | `str` | ERPNext ledger identifier chosen |
| `display_name` | `str` | Alias returned to user |
| `confidence` | `float` | Final score used for audit trail |

### JournalEntryResult

| Field | Type | Description |
|-------|------|-------------|
| `journal_entry_id` | `str` | ERPNext document name |
| `posting_date` | `date` | Confirmed posting date |
| `voucher_no` | `str` | ERPNext voucher number |
| `link` | `str` | Direct URL sent to user |

### RetryJob (SQLite table)

| Column | Type | Description | Validation |
|--------|------|-------------|------------|
| `id` | `INTEGER PRIMARY KEY` | Auto-increment job id | Generated |
| `thread_id` | `TEXT` | Conversation identifier | Required |
| `payload` | `JSON` | Serialized journal entry request | Must include debit + credit rows |
| `attempts` | `INTEGER` | How many retries attempted | 0 ≤ attempts ≤ 5 |
| `next_run_at` | `DATETIME` | Scheduled retry timestamp | Must be future |
| `error` | `TEXT` | Last failure message | Optional |

### AccountCatalog (in-memory cache)

| Field | Type | Description |
|-------|------|-------------|
| `accounts` | `List[AccountRecord]` | Snapshot of ERPNext chart of accounts |
| `fetched_at` | `datetime` | Timestamp of last refresh |

### AccountRecord

| Field | Type | Description |
|-------|------|-------------|
| `account_code` | `str` | ERPNext key |
| `account_name` | `str` | Human label |
| `aliases` | `List[str]` | Optional nicknames provided by finance |
| `is_group` | `bool` | Should be false for posting |

### AttachmentRef

| Field | Type | Description |
|-------|------|-------------|
| `file_url` | `str` | ERPNext file URL |
| `caption` | `str` | Optional user text |

## Relationships

- Each `ConversationState` references at most one active `ExpenseDraft`.
- `AccountCandidate` and `AccountMatch` link back to `AccountRecord` via `account_code`.
- Successful `JournalEntryResult` records are linked to their originating `RetryJob` (if any) for audit.

## State Transitions

1. **Idle → Drafting**: New Telegram message arrives → create/update `ExpenseDraft`, populate `clarifications_needed`.
2. **Drafting → Awaiting Clarification**: If any required fields missing, bot asks follow-up; loop until resolved.
3. **Drafting → Awaiting Confirmation**: All required fields populated → send summary card → set `confirmation_status="pending"`.
4. **Awaiting Confirmation → Approved/Rejected**: User response toggles status. Rejection clears `expense_draft`.
5. **Approved → Posting**: Call ERPNext. On success populate `erpnext_submission` and clear `clarifications_needed`. On failure enqueue `RetryJob`.
6. **Posting → Retrying**: Retry worker dequeues job, attempts ERPNext call until success or 15-minute window expires.
7. **Retry Exhausted**: Notify user of final failure, log in `error_log`, keep job for manual follow-up.

## Validation Rules

- Amounts must be positive decimals; currency defaults to company base currency if unspecified.
- Accounts used for debit/credit must not be marked `is_group`.
- Journal entry must balance: sum(debits) == sum(credits) for payload.
- Telegram users must be mapped to ERPNext contacts before processing messages.
- Conversation summaries regenerate whenever `messages` length exceeds six to preserve context while controlling token usage.
