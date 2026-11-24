# Harness Session

An autonomous agent harness that iterates on morning briefs using Claude Code. The loop has three stages:

| Command | What it does |
|---------|--------------|
| `py loop.py brief <run_id>` | Generates today's morning brief via `claude -p` (#1 in the loop). |
| `py loop.py optimize` | Asks the optimizer agent to propose one rule change based on recent traces. |
| `py loop.py try` | Applies the latest proposal, regenerates the brief (`claude -p` #2), scores both visible and hidden sets, then **keeps** only if visible improves **and** hidden doesn't drop — otherwise restores the original `harness/CLAUDE.md`. |

## Scoring formula (`verifier/score.py`)

```
numerator   = +1 · matters_hit  +  2 · decisions_correct  −  0.5 · noise_called
denominator = len(mattered_links)  +  2 · len(decisions)
score       = numerator / denominator    (0.0 for an empty brief)
```

Labels: `mattered` counts toward the score, `ignore` is negative if surfaced, `maybe` is neutral. A decision is counted correct when its `right_answer` appears verbatim inside the brief text (case-insensitive). The scoring formula must not be changed — it is the ground truth against which proposals are judged.

## Hidden set

`verifier/hidden_links.csv` holds a holdout of labelled links to prevent overfitting to the visible `verifier/links.csv`. When the hidden set contains any `mattered` items, the KEEP guard requires `hidden_score ≥ prev_hidden`. Otherwise the hidden check is skipped and the visible score alone decides. To enable a meaningful split, at least 3 links need explicit labels (currently 2 matters in each set; hidden needs ~2 more).

## How to run (offline tests only)

```bash
py tests/test_loop_offline.py          # unit tests (mocked, no real network)
```

Full integration requires `claude` CLI access and live link fetching. The offline test suite covers every decision branch in `loop.run_try()` plus isolation guarantees for `traces/`, `optimizer/`, and `harness/CLAUDE.md`.

## Project structure

```
harness-session/
├── loop.py                # orchestrator (brief / optimize / try)
├── verifier/
│   ├── score.py           # scoring formula (read-only core)
│   ├── links.csv          # visible labelled set
│   ├── hidden_links.csv   # holdout set
│   └── decisions.csv      # right-answer expectations
├── harness/
│   └── CLAUDE.md          # rules under optimisation (preserved across DROP)
├── optimizer/
│   ├── best_score.json    # running best visible/hidden scores
│   ├── proposals.md       # proposal history
│   └── journal.md         # chronicle of every keep/drop
├── traces/try/
│   ├── brief.md           # last generated brief
│   └── trace.json         # prompt + stdout from the last try
└── tests/test_loop_offline.py
```

## Known limitations

- **Single proposal window.** The `try` subcommand only evaluates the most recent block in `proposals.md`; older proposals are buried unless re-appended.
- **No cross-proposal comparison.** Each attempt is scored in isolation — there is no global search.
- **Hidden set is small.** With fewer than ~3 matter links, the hidden guard has low resolution; consider labelling more rows before relying on it for gating.
- **Visible set can overfit.** A proposal that hits all 2 mattered visible URLs but ignores the brief structure may still keep if the hidden set is insufficiently populated.
- **Offline tests mock `subprocess.run`.** They don't exercise the actual fetch network path, so edge cases around failed fetches or malformed responses aren't covered by the automated suite.
