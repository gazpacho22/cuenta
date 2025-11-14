# Conversation Flow Primer

This document extends the Mermaid diagram (`langgraph_architecture.mmd`) with concrete user-facing examples and the “conversation contracts” that govern each stage. It is meant to help newcomers visualize how the guided workflow feels before full implementation.

## Example Transcripts Per Stage

Each transcript uses short exchanges to highlight the happy path and at least one out-of-flow input.

### 1. Ingest Message → Parse Expense

1. **User**: “Paid $10 cash for taxi.”  
   **Bot**: “Got it—processing your taxi expense…” *(transitions to `parse_expense`).*
2. **User**: “Hi, can you add me?” (unauthorized sender)  
   **Bot**: “I can only assist linked accounts. Ask finance to enable your Telegram ID.” *(ingest handles denial, no state change).*

### 2. Parse Expense → Fill Gaps Loop

1. **Bot**: “I see ‘taxi’ but no amount. How much did you pay?”  
   **User**: “$10.” *(state updated, loop returns to parsing).*  
2. **User**: “Paid the driver.”  
   **Bot**: “I still need the amount to continue. Please share it.” *(re-prompts, stays in `fill_gaps`).*

### 3. Resolve Accounts

1. **Bot**: “I matched ‘cash on hand’ (100%) and ‘Travel:Taxi’ (96%). Sound right?”  
   **User**: “Yes.” *(proceeds to confirmation).*  
2. **User**: “Use marketing budget instead.”  
   **Bot**: “Okay, updating credit account to ‘Marketing:Travel’. Anything else?” *(remains in `resolve_accounts`).*

### 4. Confirm or Edit

1. **Bot**: “Confirm posting $10 debit Taxi / credit Cash?”  
   **User**: “Confirm.” *(moves to `post_to_erpnext`).*  
2. **User**: “Wait, what’s my balance?”  
   **Bot**: “I need ‘confirm’, ‘edit’, or ‘cancel’. Type ‘edit’ to change details.” *(stays in `confirm_or_edit` or routes to fallback if we add one.)*

### 5. Post to ERPNext & Retry

1. **Bot**: “Posted Journal Entry JE-0021. Ref: https://erp/JE-0021.” *(success → `log_and_notify`).*  
2. **Bot**: “ERPNext is temporarily unreachable. I’ve queued the attempt and will retry for 15 minutes.” *(failure → `queue_retry`).*  
   **User**: “Okay.” *(retry loop continues silently until resolution.)*

### 6. Logging and Notification

1. **Bot**: “Expense logged and traceable under Attempt #A-392. Reply ‘details’ for the audit trail.”  
2. **Bot**: “Retries exhausted after 15 minutes. Contact finance with Attempt #A-395 to finish manually.”

## Conversation Contracts (Interaction Rules)

| Stage | Acceptable Inputs | If Something Else Happens |
| --- | --- | --- |
| `ingest_message` | Any Telegram text from authorized users | Unauthorized senders get access instructions; nothing moves forward |
| `parse_expense` | Expense description containing amount + accounts + narration | Missing info triggers `fill_gaps`; nonsense text gets a polite re-ask |
| `fill_gaps` | Direct answers for whichever field is missing | Bot reiterates the outstanding field; optionally offer “cancel” |
| `resolve_accounts` | Confirm suggested ledgers or specify replacements | Ambiguous replies prompt clarifications; unknown account names surface alternatives |
| `confirm_or_edit` | `confirm`, `edit`, `cancel` (or synonyms) | Bot reminds user of valid commands; future enhancement could send to fallback help |
| `post_to_erpnext` | No user input (system action) | Failure auto-routes to `queue_retry` and informs user |
| `queue_retry` | Optional “status?” or “cancel” | User updates can short-circuit retries; otherwise the system notifies on completion/failure |
| `log_and_notify` | Acknowledgment or follow-up questions | Provide audit references or route to human support |

### Blend With Fallback Mode

If we decide to add a more flexible, general-purpose helper, insert a `handle_misc` node reachable from every stage once the stage-specific intent parser fails. That node can:

1. Answer informational questions (“What accounts can I use?”).  
2. Offer quick tips (“Type ‘edit’ if you need to change the amount”).  
3. Route back to the originating stage once the off-topic request has been satisfied.

Documenting the fallback as just another stage keeps the workflow strict for compliance while giving end-users a friendlier escape hatch.
