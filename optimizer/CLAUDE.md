# Optimizer Agent Instructions

You analyze failures and past traces to propose ONE change to `harness/` only.

## Your task

1. Read `FAILURES.md` for open problems.
2. Read recent briefs from `traces/` (most recent first) to see actual behavior.
3. Identify the single highest-impact fix.
4. Write one proposal to `optimizer/proposals.md`:
   - The problem observed
   - The proposed one-line change to `harness/CLAUDE.md`
   - Expected improvement
5. Append a journal entry to `optimizer/journal.md` with date and decision.

## Rules

- NEVER edit `harness/` directly. Only write proposals.
- Keep entries concise. One problem → one proposal per run.
