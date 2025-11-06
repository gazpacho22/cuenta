<!--
Sync Impact Report
Version change: 0.0.0 (template) → 1.0.0
Modified principles: Initial population
Added sections: Core Principles, Documentation Standards, Development Workflow, Governance
Removed sections: None
Templates requiring updates: ✅ .specify/templates/plan-template.md, ✅ .specify/templates/spec-template.md, ✅ .specify/templates/tasks-template.md
Follow-up TODOs: None
-->
# Cuenta Constitution

## Core Principles

### I. Beginner-Centered Communication
- MUST write code, docstrings, and supporting text so a beginner can follow the logic without
  prior context, using descriptive names over cleverness.
- MUST use docstrings following the Google style guide and add focused comments only where the
  intent is not obvious from the code.
- MUST explain every implementation session in plain language inside `change_log.md` on the day
  it happens so the tech lead can track learning progress.

Rationale: The project lead is new to programming; accessible language keeps momentum high and
prevents misunderstandings.

### II. Behavior-Driven Development First
- MUST author failing Given/When/Then tests describing the desired behavior before writing or
  changing production code.
- MUST treat BDD scenarios as the canonical specification; any change to expected behavior
  demands a test update reviewed by the product owner.
- MUST keep features small enough that each scenario runs quickly and is easy to understand.

Rationale: Behavior-driven tests protect intent, create executable documentation, and keep the
team aligned on outcomes.

### III. Python Quality Gates
- MUST follow PEP 8 formatting with four-space indentation, snake_case identifiers, and
  SCREAMING_SNAKE_CASE for environment keys.
- MUST provide complete type hints, actionable error messages, and module/function docstrings to
  support discoverability and static analysis.
- MUST ensure linting, typing, and test suites run in continuous integration before merging.

Rationale: Consistent quality gates reduce regressions and give beginners confidence in the code
base.

### IV. MVP Simplicity
- MUST default to the smallest working solution that delivers the user-facing goal before
  exploring enhancements or abstractions.
- MUST justify any increase in complexity inside the relevant spec or plan prior to
  implementation.
- SHOULD provide the AI assistant with sufficient context (even if high-token) when it materially
  improves solution accuracy or clarity.

Rationale: Lean increments support rapid learning, keep maintenance costs low, and accommodate
the MVP timeline.

### V. Transparent Knowledge Sharing
- MUST log test results, design decisions, and follow-up actions alongside each change_log entry
  so future work starts with the latest insight.
- MUST surface blockers, open questions, and assumptions in plain language during hand-offs or
  asynchronous updates.
- SHOULD record links to supporting specs, plans, or notebooks whenever they inform a decision.

Rationale: Consistent knowledge capture empowers new contributors and preserves project intent.

## Documentation Standards
- Every module, class, and function MUST include Google-style docstrings with clear descriptions
  and documented parameters, returns, raises, and examples when relevant.
- `change_log.md` MUST track the date, author, plain-language summary, impacted files, and next
  steps for each collaboration session.
- README and quickstart guides MUST stay aligned with the current MVP state and reference any
  BDD test suites needed to verify functionality.
- Inline comments MUST stay concise and purposeful; remove them when the code becomes
  self-explanatory.

## Development Workflow
1. Capture the goal in a plain-language spec highlighting user stories and Given/When/Then
   scenarios.
2. Draft an implementation plan that references the spec, identifies BDD tests to create first,
   and confirms alignment with the Core Principles.
3. Implement by writing BDD scenarios, confirming they fail, and then writing the minimal code
   to make them pass while keeping quality gates green.
4. Record outcomes in `change_log.md`, update supporting docs, and share the beginner-friendly
   summary with the team.
5. Review and merge only after tests, linters, and type checkers pass and the plain-language
   explanation is complete.

## Governance
- This constitution supersedes conflicting process documents; teams MUST align work with the Core
  Principles before delivery.
- Amendments REQUIRE a documented proposal, review of impacted templates, and confirmation from
  the product owner and tech lead. Record approved changes in `change_log.md`.
- Versioning follows semantic rules: increment MAJOR for principle changes, MINOR for new
  sections or mandates, PATCH for clarifications.
- Compliance reviews occur at the end of each sprint; any violation MUST be logged with a plan
  to resolve it in the next iteration.

**Version**: 1.0.0 | **Ratified**: 2025-11-06 | **Last Amended**: 2025-11-06
