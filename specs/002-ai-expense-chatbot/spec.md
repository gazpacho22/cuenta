# Feature Specification: AI Expense Chatbot

**Feature Branch**: `002-ai-expense-chatbot`  
**Created**: 2025-11-07  
**Status**: Draft  
**Input**: User description: "I want to build an ai chatbot that helps users register their expenses into the open source erpnext software. the ai chatbot would be interfaced via telegram. so essentially a user would write to telegram things like: i just had an expense of $10 from my cash account to the taxi account and the chatbot would be able to parse the meaning of that recognize the 2 accounts and send back a preview confirmation back to the user of how its proposing to register the expense. if the user confirms it, it gets registered to erpnext."

## Clarifications

### Session 2025-11-06
- Q: What should the bot do when ERPNext is unreachable after the user confirms an expense? → A: Queue the confirmed expense intent, retry automatically with backoff, and notify the user upon success or final failure.
- Q: How should the bot handle users repeating the same expense message shortly after approval? → A: Treat each repeated message as a new expense without duplicate checks.
- Q: What happens if the expense amount exceeds a configured approval threshold? → A: Ignore all high value spend thresholds because none are configured.
- Q: How long should the bot keep retrying a confirmed expense when ERPNext stays unreachable? → A: Retry up to 15 minutes before notifying the user of failure.

## User Scenarios & Testing *(mandatory)*

> Write scenarios in plain language that a beginner can follow, using Given/When/Then phrasing so
> they double as executable BDD tests (Principles I & II).

<!--
  IMPORTANT: User stories should be PRIORITIZED as user journeys ordered by importance.
  Each user story/journey must be INDEPENDENTLY TESTABLE - meaning if you implement just ONE of them,
  you should still have a viable MVP (Minimum Viable Product) that delivers value.
  
  Assign priorities (P1, P2, P3, etc.) to each story, where P1 is the most critical.
  Think of each story as a standalone slice of functionality that can be:
  - Developed independently
  - Tested independently
  - Deployed independently
  - Demonstrated to users independently
-->

### User Story 1 - Capture Expense via Telegram (Priority: P1)

As a business owner chatting with the bot on Telegram, I want to describe an expense in everyday language so it can be recorded in ERPNext without opening the accounting system.

**Why this priority**: Delivers the core promise of hands-free expense capture, saving time for busy users.

**Independent Test**: Send a message such as "Paid $10 cash for taxi" and confirm the bot posts a matching ERPNext expense after approval.

**Acceptance Scenarios**:

1. **Given** the user is an authorized Telegram contact linked to their ERPNext profile, **When** they send "I just had an expense of $10 from my cash account to the taxi account", **Then** the bot replies with a summary showing amount, debit, credit, narration, and **Then** upon explicit confirmation the record appears in ERPNext with matching details and the bot shares the ERPNext document reference.
2. **Given** the user sends an expense message that references multiple possible ERPNext accounts, **When** the bot parses the text, **Then** it asks the user to choose the correct account before presenting the confirmation summary.
3. **Given** the user rejects the confirmation, **When** they reply "cancel" (or similar), **Then** the bot confirms the cancellation and no ERPNext entry is created.
4. **Given** someone whose Telegram account is not linked to ERPNext tries to submit an expense, **When** they send a message describing the expense, **Then** the bot declines the request and explains how to request access from a finance administrator.

---

### User Story 2 - Guide Missing Details (Priority: P2)

As a user, I want helpful prompts when my message is incomplete so I can fix it quickly instead of guessing what went wrong.

**Why this priority**: Clear guidance prevents frustration and builds trust in the bot’s assistance.

**Independent Test**: Send a partial message like "Paid the taxi" and confirm the conversation results in a complete, accurate expense or a graceful stop.

**Acceptance Scenarios**:

1. **Given** the user submits "Paid the taxi", **When** the bot detects the missing amount, **Then** it asks for the amount before continuing the flow.
2. **Given** the user references an unknown account name, **When** the bot fails to find a matching ERPNext ledger, **Then** it tells the user the account is not recognized and offers next steps such as choosing an alternative or asking an administrator to add it.
3. **Given** ERPNext rejects an otherwise valid expense (for example, due to a closed accounting period), **When** the bot receives the error, **Then** it presents the failure reason in chat and offers to retry later or escalate to finance support.

---

### User Story 3 - Retain Conversation Trail (Priority: P3)

As a finance reviewer, I want to see the Telegram conversation that justified an expense so I can audit the entry later.

**Why this priority**: Provides compliance evidence and supports dispute resolution.

**Independent Test**: Approve an expense through Telegram, then review the ERPNext entry and verify the original message context is traceable.

**Acceptance Scenarios**:

1. **Given** the bot successfully records an expense, **When** a reviewer opens the ERPNext record, **Then** they find metadata with the originating Telegram message text, timestamp, and user identifier.

---

[Add more user stories as needed, each with an assigned priority]

### Edge Cases

<!--
  ACTION REQUIRED: The content in this section represents placeholders.
  Fill them out with the right edge cases.
-->

- If ERPNext is unreachable after the user confirms an expense, the bot stores the confirmed intent, retries submission with exponential backoff for up to 15 minutes, and posts completion or final failure status to the user.
- If a user repeats the same expense message shortly after approval, the bot processes it as a separate expense without duplicate suppression.
- How does the system handle multiple expense submissions arriving within seconds of each other?
- There is no configured approval threshold; all confirmed expenses submit automatically without third-party approval.
- How are unsupported currencies reported back to the user?

## Requirements *(mandatory)*

<!--
  ACTION REQUIRED: The content in this section represents placeholders.
  Fill them out with the right functional requirements.
-->

### Functional Requirements

- **FR-001**: System MUST interpret expense details (amount, currency, source account, destination account, date, narration) from natural-language Telegram messages.
- **FR-002**: System MUST confirm parsed details back to the user and require explicit approval before submitting any expense to ERPNext.
- **FR-003**: System MUST allow the user to correct or supply missing details within the chat before continuing.
- **FR-004**: System MUST post the approved expense to ERPNext using the user’s authorized identity, ensuring ledger balances align with provided accounts.
- **FR-005**: System MUST prevent unlinked or unauthorized Telegram users from initiating expense submissions.
- **FR-006**: System MUST log each conversation step (user inputs, bot prompts, approvals, cancellations, ERPNext responses) so reviewers can audit the process.
- **FR-007**: System MUST let users cancel an in-progress submission at any point and confirm that no ERPNext record was created.
- **FR-008**: System MUST notify the user when ERPNext rejects an expense and present recovery options such as retrying later or contacting finance support.
- **FR-009**: System MUST capture the final ERPNext document identifier and share it with the user once the expense is recorded.
- **FR-010**: System MUST persist confirmed expenses when ERPNext is unreachable, retry submission with backoff for up to 15 minutes, and inform the user if the expense ultimately fails or succeeds.
- **FR-011**: System MUST append a structured log entry for every expense attempt, edit, retry, and cancellation that records attempt_id, thread_id, Telegram identifiers, the full confirmation preview payload, status, resolution, ERPNext document reference (if any), timestamps, and latency_ms between user confirmation and ERPNext completion inside a lightweight SQLite table that auditors can query.

### Key Entities *(include if feature involves data)*

- **ExpenseIntent**: Represents a pending expense extracted from chat, including user identifier, amount, currency, debit account, credit account, posting date, narration, status, confirmation history, and ERPNext document reference once posted.
- **TelegramUserLink**: Stores the relationship between a Telegram user and their ERPNext profile, including activation status and audit timestamps.
- **AccountAlias**: Captures approved nicknames or shorthand labels for ERPNext ledger accounts along with confidence scores and steward ownership.
- **ExpenseAttemptLog**: Append-only SQLite-backed table with attempt_id (UUID), thread_id (UUID referencing the first attempt in a conversation), telegram_user_id, telegram_message_id, timestamp, proposed_summary_json, status (`previewed`, `confirmed`, `posted`, `failed`, `edited`, `cancelled`, `retrying`), resolution (`posted`, `user_cancelled`, `user_edited`, `expired`, `retrying`), erpnext_doc_id, latency_ms, and optional error metadata so each conversational step is auditable, threaded, and performance-monitored.

## Success Criteria *(mandatory)*

<!--
  ACTION REQUIRED: Define measurable success criteria.
  These must be technology-agnostic and measurable.
-->

### Measurable Outcomes

- **SC-001**: 90% of straightforward expense messages (amount and accounts clearly stated) result in the correct ERPNext accounts without manual intervention during pilot testing.
- **SC-002**: Median time from user message to confirmed ERPNext record remains under 60 seconds for successful submissions.
- **SC-003**: 100% of expenses recorded through the bot include a reference to the originating Telegram message and approving user.
- **SC-004**: Weekly error rate for failed ERPNext submissions stays below 2% after launch, with each failure surfaced to the user at the time it occurs.

## Assumptions

- Finance administrators will pre-register eligible Telegram users and provide each with a one-time code to link their chat identity to ERPNext.
- The finance team maintains a curated list of account aliases so the bot can translate common phrases to official ERPNext ledger names.
- Approved expenses will be recorded as ERPNext Journal Entries with debit/credit lines matching the user’s message unless finance policy changes later.
- ERPNext exposes an audit-friendly field where the original Telegram message text and identifiers can be stored or referenced.
- Current finance policy has no high-value approval threshold; all confirmed expenses should post automatically.

## Knowledge Sharing Requirements

- Summarize the feature in beginner-friendly language for `change_log.md`, highlighting how Telegram conversations create ERPNext expenses after confirmation.
- Update onboarding materials to explain how to link a Telegram account, submit an expense, review confirmations, and locate the resulting ERPNext records.
- Document required test suites (BDD chat scenarios, unit parsing checks, integration tests against a sandbox ERPNext tenant) and ensure they are referenced in CI instructions.
