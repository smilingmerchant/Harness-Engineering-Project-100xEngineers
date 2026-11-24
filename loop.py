#!/usr/bin/env python3
"""loop.py — orchestrates brief generation, optimization, and evaluation.

Subcommands:
    py loop.py brief <run_id>   Generate a morning brief (runs claude -p #1).
    py loop.py optimize         Ask the optimizer agent to propose one change.
    py loop.py try              Apply the latest proposal and evaluate it.
                                Runs: brief (claude -p #2), optional hidden check.
"""
import csv
import json
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

BASE = Path(__file__).parent.resolve()
HARNESS = BASE / "harness"
VERIFIER = BASE / "verifier"
TRACES = BASE / "traces" / "try"
OPTIMIZER = BASE / "optimizer"
FETCH_CACHE = TRACES.parent / "fetch_cache.json"

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
    old_v, old_h = _load_best_score()
    # Only save if better than existing, or if this is the first score
    if old_v is not None and visible <= old_v:
        return  # Don't downgrade
    if hidden is not None and old_h is not None and hidden < old_h:
        return  # Don't downgrade hidden
    _write(OPTIMIZER / "best_score.json", json.dumps({
        "visible": visible, "hidden": hidden
    }, indent=2))


def _fetch_pages() -> dict[str, str]:
    """Fetch URLs from links.txt, cache results, return {url: text}.

    shortcut: caches all fetched pages; upgrade by adding per-URL TTL if needed.
    """
    links_txt = _read(BASE / "links.txt")
    urls = [line.strip() for line in links_txt.splitlines() if line.strip()]

    # Load cache
    cache: dict[str, str] = {}
    if FETCH_CACHE.exists():
        try:
            cache = json.loads(FETCH_CACHE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cache = {}

    # Fetch missed URLs
    import urllib.request

    for url in urls:
        if url in cache:
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode("utf-8", errors="ignore")[:2500]
            cache[url] = text
        except Exception as e:
            cache[url] = f"FETCH FAILED: {e}"

    _write(FETCH_CACHE, json.dumps(cache, indent=2, ensure_ascii=False))
    return cache


def _build_fetched_section(cache: dict[str, str]) -> str:
    """Build the ## Fetched pages section for the brief prompt."""
    lines = ["## Fetched pages"]
    for url, text in cache.items():
        if text.startswith("FETCH FAILED:"):
            lines.append(f"\n### {url}")
            lines.append(f"{text}")
        else:
            lines.append(f"\n### {url}")
            lines.append(text)
    return "\n".join(lines)


def _parse_proposal(raw: str) -> tuple[str | None, str | None]:
    """Parse optimizer output into (rule_id, rule_text).

    Expects inside '# Proposal':
        RULE_ID: F2   (or NEW)
        RULE_TEXT: <the rule exactly as it should appear in CLAUDE.md>

    Tolerates bold (**), backticks, blank lines.
    Returns (None, None) on parse failure.
    """
    prop_match = re.search(r"# Proposal\s*\n(.*?)(?:\n\n# Rationale|\Z)", raw, re.DOTALL)
    if not prop_match:
        return None, None
    block = prop_match.group(1)

    rid_match = re.search(r"RULE_ID\s*:\s*(.+)", block)
    rt_match = re.search(r"RULE_TEXT\s*:\s*(.+)", block)
    if not rid_match or not rt_match:
        return None, None

    rule_id = re.sub(r"\*", "", rid_match.group(1).strip())
    # Strip markdown formatting from rule text
    rule_text = rt_match.group(1).strip()
    rule_text = re.sub(r"\*\*", "", rule_text)   # remove bold markers
    rule_text = re.sub(r"`", "", rule_text)       # remove backticks
    rule_text = rule_text.strip()

    return rule_id, rule_text


def _apply_rule(claudemd: Path, original: str, rule_id_: str | None, rule_text_: str | None, proposed_change: str) -> None:
    """Apply parsed rule: replace existing line or append new."""
    if rule_id_ is None or rule_text_ is None:
        # Fallback: keep old behavior (append raw)
        modified = original.rstrip() + "\n\n" + proposed_change + "\n"
        _write(claudemd, modified)
        return
    lines = original.splitlines(keepends=True)
    prefix = f"({rule_id_})"
    replaced = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix):
            new_lines.append(rule_text_ + "\n")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(rule_text_ + "\n")
    _write(claudemd, "".join(new_lines))


# ── brief ────────────────────────────────────────────────────────────────────

def run_brief(run_id: str) -> None:
    claude_md = _read(HARNESS / "CLAUDE.md")
    sources_md = _read(HARNESS / "sources.md")
    memory_md = _read(HARNESS / "memory.md")
    links_txt = _read(BASE / "links.txt")

    # Task 5: fetch pages in Python before building prompt
    cache = _fetch_pages()
    fetched_section = _build_fetched_section(cache)

    prompt = (
        "You are the harness agent. Follow these instructions:\n\n"
        f"{claude_md}\n\n"
        "## Sources\n"
        f"{sources_md}\n\n"
        "## Links\n"
        f"{links_txt}\n\n"
        "## Memory / Context\n"
        f"{memory_md}\n\n"
        f"{fetched_section}\n\n"
        "Write the morning brief directly as your response. Return ONLY the "
        "markdown brief with three headers:\n"
        "## What changed\n"
        "## Who disagrees with whom\n"
        "## What to do\n"
    )

    print(f"Running claude -p brief (can take up to 10 minutes)")
    t0 = time.time()
    try:
        result = subprocess.run(["claude", "-p", prompt],
                                capture_output=True, text=True, check=True,
                                timeout=900)
    except subprocess.TimeoutExpired:
        print("ERROR: claude -p timed out after 900 seconds (10 minutes).", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        elapsed = time.time() - t0
        print(f"ERROR: claude command failed (exit {e.returncode}) after {elapsed:.1f}s", file=sys.stderr)
        print(f"STDERR:\n{e.stderr}", file=sys.stderr)
        print(f"STDOUT:\n{e.stdout}", file=sys.stderr)
        sys.exit(1)
    else:
        elapsed = time.time() - t0
        print(f"Brief completed in {elapsed:.1f}s")

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

    # Task 3: new strict prompt format
    prompt = (
        "You are the optimizer agent.\n\n"
        f"{_read(OPTIMIZER / 'CLAUDE.md')}\n\n"
        "## Failures\n"
        f"{failures_md}\n\n"
        "## Recent traces\n"
        f"{traces_info}\n\n"
        "Respond with exactly this format (fill in the values):\n"
        "# Proposal\n"
        "RULE_ID: F2\n"
        "RULE_TEXT: (F2) <the rule exactly as it should appear in harness/CLAUDE.md, one line>\n\n"
        "# Rationale\n"
        "<one sentence explaining why this addresses an open failure>\n"
    )

    print(f"Running claude -p optimize (can take up to 10 minutes)")
    t0 = time.time()
    try:
        result = subprocess.run(["claude", "-p", prompt],
                                capture_output=True, text=True, check=True,
                                timeout=900)
    except subprocess.TimeoutExpired:
        print("ERROR: claude -p timed out after 900 seconds (10 minutes).", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        elapsed = time.time() - t0
        print(f"ERROR: claude command failed (exit {e.returncode}) after {elapsed:.1f}s", file=sys.stderr)
        print(f"STDERR:\n{e.stderr}", file=sys.stderr)
        print(f"STDOUT:\n{e.stdout}", file=sys.stderr)
        sys.exit(1)
    else:
        elapsed = time.time() - t0
        print(f"Optimize completed in {elapsed:.1f}s")

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

    # Task 6: preflight warning — check if any decision right_answer appears nowhere in sources
    decisions_path = VERIFIER / "decisions.csv"
    source_files = [HARNESS / "sources.md", HARNESS / "memory.md", BASE / "links.txt"]
    source_text = ""
    for sf in source_files:
        if sf.exists():
            source_text += sf.read_text(encoding="utf-8").lower() + "\n"
    with open(decisions_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ra = row.get("right_answer", "").strip()
            if ra and ra.lower() not in source_text:
                print(f"WARNING: decision answer can never be matched by the brief: {ra}")

    # Task 6: warn if hidden set is empty
    hidden_csv = VERIFIER / "hidden_links.csv"
    if _count_mattered(hidden_csv) == 0:
        print("WARNING: hidden check is empty, the KEEP decision uses the visible set only.")

    # Task 2: Safe restore — wrap everything after reading original CLAUDE.md
    claudemd = HARNESS / "CLAUDE.md"
    original_claude_md = claudemd.read_text(encoding="utf-8")
    keep = False

    # Task 3: Parse RULE_ID and RULE_TEXT from proposal
    rule_id, rule_text = _parse_proposal(proposed_change)

    try:
        _apply_rule(claudemd, original_claude_md, rule_id, rule_text, proposed_change)

        run_brief("try-applied")

        visible_score = _score(
            TRACES / "brief.md",
            VERIFIER / "links.csv",
            VERIFIER / "decisions.csv",
        )

        prev_visible, prev_hidden = _load_best_score()
        pv_str = f"{prev_visible:.2f}" if prev_visible is not None else "N/A"
        ph_str = f"{prev_hidden:.2f}" if prev_hidden is not None else "N/A"
        print(f"Previous best: visible={pv_str}, hidden={ph_str}")
        print(f"Visible score (after apply): {visible_score:.2f}")

        hidden_score = None
        if _count_mattered(hidden_csv) > 0:
            hidden_score = _score(TRACES / "brief.md", hidden_csv, VERIFIER / "decisions.csv")
            print(f"Hidden score (after apply): {hidden_score:.2f}")

        # Task 7: Keep only if strictly better
        if prev_visible is None or visible_score > prev_visible:
            if prev_hidden is None or (hidden_score is not None and hidden_score >= prev_hidden):
                keep = True

        opt_journal = OPTIMIZER / "journal.md"
        journal_existing = opt_journal.read_text(encoding="utf-8").rstrip() + "\n" if opt_journal.exists() else ""

        if keep:
            _commit(proposed_change[:70])
            _save_best_score(visible_score, hidden_score)
            h_str = "N/A" if hidden_score is None else f"{hidden_score:.2f}"
            v_str = f"{visible_score:.2f}"
            _write(opt_journal, f"{journal_existing}- **{date.today().isoformat()}** Kept '{proposed_change[:60]}...' "
                   f"(visible={v_str}, hidden={h_str})\n")
            print("Decision: KEEP [yes]")
            print("Committed to git. Best scores updated.")
        else:
            _write(claudemd, original_claude_md)
            h_str = "N/A" if hidden_score is None else f"{hidden_score:.2f}"
            v_str = f"{visible_score:.2f}"
            _write(opt_journal, f"{journal_existing}- **{date.today().isoformat()}** Dropped '{proposed_change[:60]}...' "
                   f"(visible={v_str}, hidden={h_str})\n")
            print("Decision: DROP [no]")
            print("Restored harness/CLAUDE.md.")

        # Task 7: Summary line
        vis_old = f"{prev_visible:.2f}" if prev_visible is not None else "N/A"
        hid_old = f"{prev_hidden:.2f}" if prev_hidden is not None else "N/A"
        vis_new = f"{visible_score:.2f}"
        hid_new = f"{hidden_score:.2f}" if hidden_score is not None else "N/A"
        action = "KEEP" if keep else "DROP"
        print(f"RESULT: {action} | proposal | visible {vis_old}->{vis_new} | hidden {hid_old}->{hid_new}")

    finally:
        # Task 2: Always restore original unless kept
        if not keep:
            _write(claudemd, original_claude_md)


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
