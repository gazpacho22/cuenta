# Knowledge Layers & Tooling Primer

This note captures how “knowledge bases” appear inside LangGraph-style assistants and why different storage strategies matter as the bot grows beyond simple expense capture.

## 1. Direct ERP Tools (Structured APIs)

- **What they are**: LangGraph nodes that call ERPNext (or other systems) via Python functions—e.g., `query_recent_transactions`, `post_to_erpnext`, `fetch_budget_targets`.  
- **How they work**: The node receives the current `ConversationState`, builds an HTTP request, and returns structured data (JSON, dataclasses). The LLM can then summarize or decide the next step.  
- **When to use**: Anytime the question has a deterministic answer in ERPNext (“Show my last 5 expenses”, “Post this journal entry”). Accuracy is guaranteed because you’re reading the system of record directly.

## 2. Analysis Helpers (Computed Knowledge)

- **What they are**: Pure Python (or pandas, NumPy) nodes that crunch numbers coming from ERPNext or prior state—running forecasts, aggregations, or anomaly checks.  
- **How they work**: The node takes structured inputs (e.g., a list of expenses) and outputs analytics (totals, projections). The LLM then narrates the result.  
- **When to use**: When insights require computation rather than retrieval (“Project cash burn next month”, “Compare taxi spend vs. last quarter”).

## 3. Retrieval QA (Unstructured Knowledge Bases)

- **What it is**: A retrieval pipeline that lets the LLM ground its answers in large collections of documents (policy PDFs, onboarding wikis, FAQs). Users can ask “How do reimbursements work?” and the system cites the right passages.  
- **How it works**:
  1. Documents are chunked and embedded into vectors (using an embedding model).  
  2. At runtime, the graph issues a similarity search (via vector store) using the user’s question.  
  3. Retrieved snippets are fed into the LLM prompt, ensuring responses stay grounded.
- **Why a vector store instead of plain text**: Free-form text becomes unwieldy as the corpus grows. Vector search lets the assistant find semantically similar content even if the wording differs. Without it, you would have to maintain brittle keyword maps or load huge documents into every prompt, which is slow and expensive. Vector stores also track metadata (source URL, section) so the bot can cite answers.

> Think of retrieval QA as a “knowledge base API” for unstructured information, complementing structured ERP tools.

## Putting It Together

| Capability | Knowledge Layer | Graph Placement |
| --- | --- | --- |
| Expense capture | Direct ERP tools | `post_to_erpnext`, `resolve_accounts` nodes |
| Transaction lookup | Direct ERP tools + light analytics | `query_recent_transactions → summarize_transactions` |
| Budget forecasts | Analysis helpers + ERP data | `run_projection → explain_projection` |
| Policy/help answers | Retrieval QA (vector store) | `general_help.retrieve_policy_docs → answer_question` |

By naming these layers explicitly, you can design future LangGraph branches that mix deterministic tools, analytics, and retrieval while keeping the conversation state machine understandable.


You’re already structuring the bot as a LangGraph with explicit state and checkpoints, so bolting on a router +
extra branches is an incremental evolution, not a rewrite. The biggest lift will be building the new capabilities
themselves (transaction queries, budgeting logic, retrieval pipeline), but the graph scaffolding, logging, and retry infrastructure we’ve outlined stays reusable.

- Smart path forward: finish the expense branch with solid abstractions (clear state schema, tool adapters,
logging hooks). Then introduce a route_intent node and gradually add new subgraphs one by one—start with a simple
transaction lookup flow, then layer in budgeting, then retrieval QA. Because each branch is independent, you can
iterate without destabilizing the expense flow.