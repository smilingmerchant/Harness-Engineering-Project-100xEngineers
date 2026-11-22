# Failures Log

## F1 — brief had no URLs, now fixed

- **Saw:** Brief items referenced sources by name only (e.g. "the GitHub page") instead of citing full URLs.
- **Expected:** Every item in the brief cites its full URL verbatim so each one can be checked against labels.
- **Fix applied:** Added rule `(F1)` to `harness/CLAUDE.md`. Committed as "F1: brief must cite full URLs". Verified in trace `traces/try/brief.md` — all 12 source URLs are now cited.

## F2 — brief listed URLs without opening them

- **Saw:** The brief enumerated source URLs but never fetched or ingested any of their content. It reported that sources were "unread" rather than reporting what the sources actually say.
- **Expected:** Harness agent opens each source with `harness/tools/fetch.py` (or equivalent stdlib fetcher) and bases every item on what it finds there.
- **Status:** Not yet fixed. This is the current top priority for the optimizer.
