#!/usr/bin/env python3
"""loop.py — orchestrates brief generation, optimization, and evaluation.

Subcommands:
    py loop.py brief <run_id>   Generate a morning brief (runs claude -p #1).
    py loop.py optimize         Ask the optimizer agent to propose one change.
    py loop.py try              Apply the latest proposal and evaluate it.
                                Runs: brief (claude -p #2), optional hidden check.
"""
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).parent.resolve()
HARNESS = BASE / "harness"
VERIFIER = BASE / "verifier"
TRACES = BASE / "traces" / "try"
OPTIMIZER = BASE / "optimizer"

# Added to sys.path so we can import from verifier package
sys.path.insert(0, str(BASE))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _score(brief_path: Path, links_csv: Path, decisions_csv: Path) -> float:
    """Score using verifier/score.py; treats 'maybe' as neutral."""
    from verifier.score import score
    return score(str(brief_path), str(decisions_csv), str(links_csv))


def _count_mattered(csv_path: Path) -> int:
    count = 0
    import csv
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("label", "").strip() == "mattered":
                count += 1
    return count


def _commit(msg: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=BASE, capture_output=True, text=True)
    subprocess.run(["git", "commit", "--no-verify", "-m", msg],
                   cwd=BASE, capture_output=True, text=True)


def _load_best_score() -> tuple[float | None, float | None]:
    """Load best scores from optimizer/best_score.json or compute initial baseline."""
    best_path = OPTIMIZER / "best_score.json"
    if best_path.exists():
        data = json.loads(best_path.read_text(encoding="utf-8"))
        return data.get("visible"), data.get("hidden")
    # No saved best — score current brief as initial baseline
    brief_path = TRACES / "brief.md"
    if not brief_path.exists():
        return None, None
    visible = _score(brief_path, VERIFIER / "links.csv", VERIFIER / "decisions.csv")
    hidden = None
    if _count_mattered(VERIFIER / "hidden_links.csv") > 0:
        hidden = _score(brief_path, VERIFIER / "hidden_links.csv", VERIFIER / "decisions.csv")
    _write(best_path, json.dumps({"visible": visible, "hidden": hidden}, indent=2))
    return visible, hidden


def _save_best_score(visible: float, hidden: float | None) -> None:
    _write(OPTIMIZER / "best_score.json", json.dumps({
        "visible": visible, "hidden": hidden
    }, indent=2))


# ── brief ────────────────────────────────────────────────────────────────────

def run_brief(run_id: str) -> None:
    claude_md = _read(HARNESS / "CLAUDE.md")
    sources_md = _read(HARNESS / "sources.md")
    memory_md = _read(HARNESS / "memory.md")
    links_txt = _read(BASE / "links.txt")

    prompt = (
        "You are the harness agent. Follow these instructions:\n\n"
        f"{claude_md}\n\n"
        "## Sources\n"
        f"{sources_md}\n\n"
        "## Links\n"
        f"{links_txt}\n\n"
        "## Memory / Context\n"
        f"{memory_md}\n\n"
        "Write the morning brief directly as your response. Return ONLY the "
        "markdown brief with three headers:\n"
        "## What changed\n"
        "## Who disagrees with whom\n"
        "## What to do\n"
    )

    try:
        result = subprocess.run(["claude", "-p", prompt],
                                capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: claude command failed (exit {e.returncode})", file=sys.stderr)
        print(f"STDERR:\n{e.stderr}", file=sys.stderr)
        print(f"STDOUT:\n{e.stdout}", file=sys.stderr)
        sys.exit(1)

    brief_output = result.stdout.strip()

    TRACES.mkdir(parents=True, exist_ok=True)
    _write(TRACES / "brief.md", brief_output)
    trace_data = {
        "run_id": run_id,
        "prompt": prompt,
        "cmd": ["claude", "-p", "..."],
        "stdout": brief_output,
        "stderr": result.stderr,
    }
    _write(TRACES / "trace.json", json.dumps(trace_data, indent=2))
    print(f"Brief written to: {TRACES / 'brief.md'}")
    print(f"Trace written to: {TRACES / 'trace.json'}")


# ── optimize ─────────────────────────────────────────────────────────────────

def run_optimize() -> None:
    failures_md = _read(BASE / "FAILURES.md")
    recent_briefs = sorted(
        [p for p in TRACES.glob("brief.md")]
        + [p for p in TRACES.glob("*.md")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:3]
    traces_info = "\n".join(p.read_text(encoding="utf-8")[:1500] for p in recent_briefs)

    prompt = (
        "You are the optimizer agent.\n\n"
        f"{_read(OPTIMIZER / 'CLAUDE.md')}\n\n"
        "## Failures\n"
        f"{failures_md}\n\n"
        "## Recent traces\n"
        f"{traces_info}\n\n"
        "Respond with exactly two sections using these exact headings, filling each:\n"
        "# Proposal\n"
        "<the rule text itself, exactly as it should appear in harness/CLAUDE.md>\n\n"
        "# Rationale\n"
        "<one sentence explaining why this addresses an open failure>\n"
    )

    try:
        result = subprocess.run(["claude", "-p", prompt],
                                capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: claude command failed (exit {e.returncode})", file=sys.stderr)
        print(f"STDERR:\n{e.stderr}", file=sys.stderr)
        print(f"STDOUT:\n{e.stdout}", file=sys.stderr)
        sys.exit(1)

    raw = result.stdout.strip()

    prop_match = re.search(r"# Proposal\s*\n(.*?)(?:\n\n|$)", raw, re.DOTALL)
    rat_match = re.search(r"# Rationale\s*\n(.*?)(?:\n\n|$)", raw, re.DOTALL)
    proposal_text = (prop_match.group(1).strip() if prop_match else "").replace("# Proposal", "").strip()
    rationale_text = rat_match.group(1).strip() if rat_match else ""

    if not proposal_text or not rationale_text:
        print(f"ERROR: optimizer returned empty response.\nRAW OUTPUT:\n{raw}")
        sys.exit(1)

    opt_proposals = OPTIMIZER / "proposals.md"
    existing = opt_proposals.read_text(encoding="utf-8").rstrip() + "\n" if opt_proposals.exists() else ""
    _write(opt_proposals, f"{existing}## [{date.today().isoformat()}]\n\n{proposal_text}\n\n"
           f"**Rationale:** {rationale_text}\n")

    opt_journal = OPTIMIZER / "journal.md"
    journal_existing = opt_journal.read_text(encoding="utf-8").rstrip() + "\n" if opt_journal.exists() else ""
    _write(opt_journal, f"{journal_existing}- **{date.today().isoformat()}** Proposed: {proposal_text}\n")

    print("Optimization complete.")
    print(f"Proposal saved to: {OPTIMIZER / 'proposals.md'}")
    print(f"Journal entry added to: {OPTIMIZER / 'journal.md'}")


# ── try ──────────────────────────────────────────────────────────────────────

def run_try() -> None:
    proposals_file = OPTIMIZER / "proposals.md"
    if not proposals_file.exists():
        print("No proposals found in optimizer/proposals.md. Run `py loop.py optimize` first.")
        sys.exit(1)

    proposals_content = proposals_file.read_text(encoding="utf-8")
    matches = list(re.finditer(r"^## \[\d{4}-\d{2}-\d{2}\]", proposals_content, re.MULTILINE))
    if not matches:
        # Fall back: use the whole file as the proposal block
        proposal_block = proposals_content
    else:
        last_match = matches[-1]
        proposal_block = proposals_content[last_match.start():].split("\n\n## [")[0]

    prop_match = re.search(r"^## \[\d{4}-\d{2}-\d{2}\]\s*\n(.*?)\n\n\*\*Rationale:\*\*", proposal_block, re.DOTALL)
    proposed_change = prop_match.group(1).strip() if prop_match else ""

    if not proposed_change:
        print("Could not parse a proposal from optimizer/proposals.md.")
        sys.exit(1)

    print(f"Proposed change: {proposed_change}")

    claudemd = HARNESS / "CLAUDE.md"
    original_claude_md = claudemd.read_text(encoding="utf-8")
    modified_claude_md = original_claude_md.rstrip() + "\n\n" + proposed_change + "\n"
    _write(claudemd, modified_claude_md)

    run_brief("try-applied")

    visible_score = _score(
        TRACES / "brief.md",
        VERIFIER / "links.csv",
        VERIFIER / "decisions.csv",
    )
    print(f"Visible score (after apply): {visible_score:.2f}")

    hidden_score = None
    hidden_csv = VERIFIER / "hidden_links.csv"
    if _count_mattered(hidden_csv) > 0:
        hidden_score = _score(TRACES / "brief.md", hidden_csv, VERIFIER / "decisions.csv")
        print(f"Hidden score (after apply): {hidden_score:.2f}")
    else:
        print("Hidden set skipped: no mattered links defined.")

    # FIX 2: Load previous best scores
    pv = f"{prev_visible:.2f}" if prev_visible is not None else "N/A"
    ph = f"{prev_hidden:.2f}" if prev_hidden is not None else "N/A"
    print(f"Previous best: visible={pv}, hidden={ph}")

    # FIX 2: Keep only if strictly better than best so far
    keep = False
    if prev_visible is None or visible_score > prev_visible:
        if prev_hidden is None or (hidden_score is not None and hidden_score >= prev_hidden):
            keep = True

    opt_journal = OPTIMIZER / "journal.md"
    journal_existing = opt_journal.read_text(encoding="utf-8").rstrip() + "\n" if opt_journal.exists() else ""

    if keep:
        _commit(proposed_change[:70])
        _save_best_score(visible_score, hidden_score)
        hidden_str = "N/A" if hidden_score is None else f"{hidden_score:.2f}"
        _write(opt_journal, f"{journal_existing}- **{date.today().isoformat()}** Kept '{proposed_change[:60]}...' "
               f"(visible={visible_score:.2f}, hidden={hidden_str})\n")
        print("Decision: KEEP [yes]")
        print("Committed to git. Best scores updated.")
    else:
        _write(claudemd, original_claude_md)
        hidden_str = "N/A" if hidden_score is None else f"{hidden_score:.2f}"
        _write(opt_journal, f"{journal_existing}- **{date.today().isoformat()}** Dropped '{proposed_change[:60]}...' "
               f"(visible={visible_score:.2f}, hidden={hidden_str})\n")
        print("Decision: DROP [no]")
        print("Restored harness/CLAUDE.md.")


# ── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py loop.py <brief|optimize|try> [args...]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "brief":
        if len(sys.argv) < 3:
            print("Usage: py loop.py brief <run_id>")
            sys.exit(1)
        run_brief(sys.argv[2])
    elif cmd == "optimize":
        run_optimize()
    elif cmd == "try":
        run_try()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
