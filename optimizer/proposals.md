## [2026-11-22]

# Proposal
Add rule **(F2)** to `harness/CLAUDE.md`: *Before writing any item, fetch every URL in `sources.md` with `python harness/tools/fetch.py <url>` (or equivalent stdlib fetch) and base each item on the fetched content — not on verifier labels or assumptions.*

# Rationale
F2 is the current top priority in `FAILURES.md`; the trace confirms all 12 source URLs were left unread, so the brief reports nothing but verifier label classifications instead of actual sourced observations. One line in `harness/CLAUDE.md` forces ingestion before summarization, closing the gap at minimal cost.
