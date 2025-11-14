# Change Log

## 2025-11-06

### Constitution shaped for beginner workflow
- I filled in the project constitution so it now explains our beginner-friendly rules, the BDD testing habit, and the MVP focus.
- I updated the planning, specification, and task templates so they remind us to write Given/When/Then tests, keep notes simple, and log updates in `change_log.md`.
- I set the constitution version to 1.0.0 and wrote down the ratification date so we have a clear starting point.

**Impacted files**: `.specify/memory/constitution.md`, `.specify/templates/plan-template.md`, `.specify/templates/spec-template.md`, `.specify/templates/tasks-template.md`

**Next steps**: Follow the new principles on the next feature by planning BDD tests first and writing a short beginner summary in this log when the work is done.

## 2025-11-07

### AI Expense Chatbot analysis follow-up
- Logged two unresolved ambiguities from the AI Expense Chatbot spec review so future iterations remember to clarify them: (1) how to handle multiple submissions arriving within seconds of each other, and (2) how the bot reports unsupported currencies to the user.
- Noted that we are deliberately deferring both clarifications for now because they are low risk for the MVP scope; they remain open items in the next planning cycle.

**Impacted files**: `specs/002-ai-expense-chatbot/spec.md` (context), `change_log.md`

**Next steps**: Revisit these open questions before `/speckit.plan` is rerun or implementation begins, adding explicit rules plus tests when priorities allow.

### Inline BDD features + constitution tweak
- Collapsed pytest-bdd `.feature` files into inline Gherkin strings stored beside their step modules so the `tests/bdd` folder stays manageable as scenarios grow.
- Added a reusable `materialize_inline_feature` helper that materializes each inline scenario into a cached file before pytest-bdd collects it.
- Updated the Constitution, plan, research notes, tasks list, and quickstart guide so they describe the inline workflow, require `materialize_inline_feature()`, and point to the new `*_steps.py` targets.

**Impacted files**: `.specify/memory/constitution.md`, `tests/__init__.py`, `tests/bdd/__init__.py`, `tests/bdd/feature_registry.py`, `tests/bdd/test_foundational_resilience_steps.py`, `specs/002-ai-expense-chatbot/tasks.md`, `specs/002-ai-expense-chatbot/plan.md`, `specs/002-ai-expense-chatbot/research.md`, `specs/002-ai-expense-chatbot/quickstart.md`, `change_log.md`

**Next steps**: Follow the inline pattern for upcoming BDD work (e.g., `test_expense_flow_steps.py`) so each scenario’s Gherkin lives next to its Python glue.
