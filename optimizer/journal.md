
- **2026-11-22** Proposed: Add rule **(F2)** to `harness/CLAUDE.md`: *Before writing any item, fetch every URL in `sources.md` with `python harness/tools/fetch.py <url>` (or equivalent stdlib fetch) and base each item on the fetched content â€” not on verifier labels or assumptions.*
- **2026-11-22** Kept 'Add rule **(F2)** to `harness/CLAUDE.md`: *Before writing an...' (visible=0.50, hidden=N/A)
- **2026-11-22** Dropped 'Add rule **(F2)** to `harness/CLAUDE.md`: *Before writing an...' (visible=0.00, hidden=N/A)
- **2026-11-24** Proposed: Revise rule **(F2)** in `harness/CLAUDE.md` to read: *Before writing any item, you MUST fetch every URL in `sources.md` using `python harness/tools/fetch.py <url>` as your primary method; do NOT attempt raw curl, Invoke-WebRequest, or direct stdlib calls.*
