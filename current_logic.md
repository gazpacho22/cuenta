 1. Regex-based parsing, no LLM yet (parse_expense_text)
      - File: src/expense_bot/parsing/expense.py.
      - We strip/normalize the message and run simple regexes:
          - _AMOUNT_PATTERN extracts a number (with optional currency prefix/suffix); converts it to Decimal. If absent, missing_fields gets amount.
          - _DEBIT_PATTERN looks for phrases like “for account_name” to get a debit hint.
          - _CREDIT_PATTERN searches for “from/using/with/via account_name”; if that fails, it heuristically grabs the text between amount and debit hint, or everything after the
            amount.
          - _extract_keywords tokenizes the sentence into a bag of words (keywords) for later candidate ranking.
      - The function returns a ParsedExpense dataclass containing the amount, currency, narration, debit hint, credit hint, keywords, missing field flags, and optional
        source_message_id.
      - The LangGraph node parse_expense_message calls parse_expense_text.
      - It copies parsed.missing_fields into state.clarifications_needed. If the set is non-empty, it clears state.expense_draft and stops—the graph will ask the user for whatever
        fields are missing.
      - If all required fields are present, it builds an ExpenseDraft using the parsed amount/currency and placeholder AccountMatch objects (the real ledger codes will be filled
        later). Still no LLM calls; it’s all local logic.
  3. Chart-of-accounts ranking (select_accounts_for_draft)
      - This node receives the ExpenseDraft plus a list of accounts (fetched earlier via ChartOfAccountsTool, which likely hits ERPNext but you already have that working).
      - It calls parse_expense_text again on the narration to re-use the keywords/hints.
      - _rank_candidates takes the hint + keywords, compares them against each chart row using RapidFuzz similarity, and produces up to MAX_ACCOUNT_SUGGESTIONS AccountCandidate
        objects per role (debit and credit). Still no LLM—just fuzzy matching.
      - _resolve_account auto-selects the top candidate only if its confidence ≥ AUTO_SELECTION_THRESHOLD (0.85). Otherwise it leaves that role unresolved, adds it to
        state.clarifications_needed, and exposes the candidate list so the UI can show options.
      - If any roles stay unresolved, the graph returns and the Telegram layer asks the user to clarify. If both roles are settled, the draft is complete and the conversation moves
        to confirmation.
  4. Confirmation / posting (apply_confirmation_decision, post_confirmed_expense, etc.)
      - Once the user types “confirm”, we call ERPNext through the integration layer to post the journal entry. Those interactions use the structured data collected earlier.

  So to answer your question directly: parse_expense_text just runs regex/string parsing and never talks to the LLM or chart. The chart lookup comes one node later in
  select_accounts_for_draft, and even there we don’t call an LLM—we score the chart rows with RapidFuzz. The only LLM in this flow is wherever you defined it inside the LangGraph
  nodes (e.g., if parse_expense_text ever fails and you added extra nodes to ask the model for clarifications), but in the code you’ve shown there’s no LLM in the critical path
  between user message and ledger selection. That’s why, in Studio, you see clarifications_needed set when the regex parser can’t find enough clues: it’s entirely deterministic and
  only extracts what’s explicitly in the text.