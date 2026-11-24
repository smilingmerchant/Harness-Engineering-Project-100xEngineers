## [2026-11-22]

# Proposal
Add rule **(F2)** to `harness/CLAUDE.md`: *Before writing any item, fetch every URL in `sources.md` with `python harness/tools/fetch.py <url>` (or equivalent stdlib fetch) and base each item on the fetched content — not on verifier labels or assumptions.*

# Rationale
F2 is the current top priority in `FAILURES.md`; the trace confirms all 12 source URLs were left unread, so the brief reports nothing but verifier label classifications instead of actual sourced observations. One line in `harness/CLAUDE.md` forces ingestion before summarization, closing the gap at minimal cost.
## [2026-11-24]

Revise rule **(F2)** in `harness/CLAUDE.md` to read: *Before writing any item, you MUST fetch every URL in `sources.md` using `python harness/tools/fetch.py <url>` as your primary method; do NOT attempt raw curl, Invoke-WebRequest, or direct stdlib calls.*

**Rationale:** The current `(F2)` rule includes "(or equivalent stdlib fetch)" which the latest trace (`traces/try/brief.md`) interprets as permission to bypass `fetch.py` entirely â€” the agent tried raw PowerShell/WebFetch instead, hit permission blocks, and produced a brief with zero fetched content. Removing the alternative makes `fetch.py` the mandatory path.
