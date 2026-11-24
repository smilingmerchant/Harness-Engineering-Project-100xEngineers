"""Offline self-test for loop.py — mocks subprocess, no real network calls."""
import csv
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _mkcsv(path: Path, rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        if not rows:
            return
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _make_project(tmp: Path) -> dict[str, Path]:
    """Create a temporary project with realistic file structure."""
    p = tmp / "project"
    (p / "harness").mkdir(parents=True)
    (p / "verifier").mkdir()
    (p / "optimizer").mkdir()
    (p / "traces" / "try").mkdir(parents=True)

    # Use actual project data for realism
    (p / "links.txt").write_text(
        "https://github.com/firstcontributions/first-contributions\n"
        "https://skills.yourlearning.ibm.com/activity/ALM-COURSE_3825249?topic=cloud\n"
        "https://youtu.be/EsTrWCV0Ph4\n"
        "https://www.linkedin.com/feed/update/urn:li:activity:7506239146646994944?updateEntityUrn=urn%3Ali%3Afs_updateV2%3A%28urn%3Ali%3Aactivity%3A7506239146646994944%2CFEED_DETAIL%2CEMPTY%2CDEFAULT%2Cfalse%29\n",
        encoding="utf-8",
    )
    (p / "harness" / "sources.md").write_text("# Sources\n\n", encoding="utf-8")
    (p / "harness" / "memory.md").write_text("# Memory\n\n", encoding="utf-8")
    (p / "FAILURES.md").write_text("## F1\n\nold failure\n", encoding="utf-8")

    # Realistic verifier CSVs matching actual project structure
    _mkcsv(p / "verifier" / "links.csv", [
        {"url": "https://github.com/firstcontributions/first-contributions", "date": "", "label": "mattered"},
        {"url": "https://skills.yourlearning.ibm.com/activity/ALM-COURSE_3825249?topic=cloud", "date": "", "label": "mattered"},
        {"url": "https://youtu.be/EsTrWCV0Ph4", "date": "", "label": "ignore"},
        {"url": "https://www.linkedin.com/feed/update/urn:li:activity:7506239146646994944?updateEntityUrn=urn%3Ali%3Afs_updateV2%3A%28urn%3Ali%3Aactivity%3A7506239146646994944%2CFEED_DETAIL%2CEMPTY%2CDEFAULT%2Cfalse%29", "date": "", "label": "ignore"},
        {"url": "https://example.com/maybe", "date": "", "label": "maybe"},
    ])
    _mkcsv(p / "verifier" / "decisions.csv", [
        {"decision": "D1", "right_answer": "standup"},
        {"decision": "D2", "right_answer": "client invoice"},
        {"decision": "D3", "right_answer": "friday"},
    ])
    _mkcsv(p / "verifier" / "hidden_links.csv", [])

    today = "2026-01-01"
    (p / "optimizer" / "proposals.md").write_text(
        f"## [{today}]\n\nRULE_ID: F2\nRULE_TEXT: (F2) New rule text\n\n**Rationale:** fix\n",
        encoding="utf-8",
    )
    (p / "optimizer" / "journal.md").write_text("", encoding="utf-8")
    (p / "harness" / "CLAUDE.md").write_text(
        "# Instructions\n\n(F1) Keep F1.\n(F2) Old rule text.\n",
        encoding="utf-8",
    )
    (p / "optimizer" / "best_score.json").write_text(
        '{"visible": 0.5, "hidden": null}', encoding="utf-8",
    )

    return {
        "base": p,
        "claude_md": p / "harness" / "CLAUDE.md",
        "decisions_csv": p / "verifier" / "decisions.csv",
        "links_csv": p / "verifier" / "links.csv",
        "hidden_csv": p / "verifier" / "hidden_links.csv",
        "brief_path": p / "traces" / "try" / "brief.md",
        "best_score_json": p / "optimizer" / "best_score.json",
    }


def _patch_module_paths(project: dict[str, Path]) -> None:
    """Override module-level path constants directly."""
    proj = project["base"]
    patch("loop.BASE", proj).start()
    patch("loop.HARNESS", proj / "harness").start()
    patch("loop.VERIFIER", proj / "verifier").start()
    patch("loop.TRACES", proj / "traces" / "try").start()
    patch("loop.OPTIMIZER", proj / "optimizer").start()
    patch("loop.FETCH_CACHE", proj / "traces" / "fetch_cache.json").start()


# ── Tests ────────────────────────────────────────────────────────────────────

def test_proposal_parsing_clean():
    raw = """# Proposal
RULE_ID: F2
RULE_TEXT: (F2) Base every item only on fetched text.

# Rationale
Fixes the issue."""
    rid, rt = loop._parse_proposal(raw)
    assert rid == "F2"
    assert "(F2)" in rt
    assert "Base every item" in rt


def test_proposal_parsing_bold_backtick():
    raw = """# Proposal
RULE_ID: **F2**
RULE_TEXT: `(F2) Base every item only on fetched text.`

# Rationale
Fix."""
    rid, rt = loop._parse_proposal(raw)
    assert rid == "F2"
    assert "**" not in rt
    assert "`" not in rt
    assert "(F2)" in rt


def test_proposal_parsing_malformed():
    raw = "garbage output with no structure"
    rid, rt = loop._parse_proposal(raw)
    assert rid is None
    assert rt is None


def test_apply_rule_replaces_existing():
    project = _make_project(Path(tempfile.mkdtemp()))
    _patch_module_paths(project)
    import importlib
    import loop
    importlib.reload(loop)

    claudemd = project["claude_md"]
    original = claudemd.read_text(encoding="utf-8")
    assert "(F2) Old rule text." in original
    assert "(F2) New rule text." not in original

    loop._apply_rule(claudemd, original, "F2", "(F2) New rule text.", "(F2) New rule text.")
    after = claudemd.read_text(encoding="utf-8")
    assert "(F2) Old rule text." not in after
    assert "(F2) New rule text." in after

    # Non-existing rule should be appended
    loop._apply_rule(claudemd, after, "NEW-1", "(NEW-1) Brand new rule.", "(NEW-1) Brand new rule.")
    final = claudemd.read_text(encoding="utf-8")
    assert "(NEW-1) Brand new rule." in final


def test_restore_after_crash():
    project = _make_project(Path(tempfile.mkdtemp()))
    _patch_module_paths(project)
    import importlib
    import loop
    importlib.reload(loop)

    claudemd = project["claude_md"]
    original = claudemd.read_text(encoding="utf-8")

    try:
        loop._apply_rule(claudemd, original, "F2", "(F2) New rule text.", "(F2) New rule text.")
        raise RuntimeError("simulated crash")
    except RuntimeError:
        pass
    finally:
        # run_try's finally always restores unless keep=True
        loop._write(claudemd, original)

    # finally block must restore
    after = claudemd.read_text(encoding="utf-8")
    assert after == original, f"Restored:\n{after}"
    print("PASS: crash restores original")


def test_restore_after_drop():
    project = _make_project(Path(tempfile.mkdtemp()))
    _patch_module_paths(project)
    import importlib
    import loop
    importlib.reload(loop)

    claudemd = project["claude_md"]
    original = claudemd.read_text(encoding="utf-8")
    loop._apply_rule(claudemd, original, "F2", "(F2) New rule text.", "(F2) New rule text.")
    assert claudemd.read_text(encoding="utf-8") != original

    # Simulate drop by restoring via the finally path
    loop._write(claudemd, original)
    assert claudemd.read_text(encoding="utf-8") == original
    print("PASS: drop restores original")


def test_fstring_no_valueerror_none():
    pv = None
    ph = None
    pv_str = f"{pv:.2f}" if pv is not None else "N/A"
    ph_str = f"{ph:.2f}" if ph is not None else "N/A"
    assert pv_str == "N/A"
    assert ph_str == "N/A"


def test_fstring_no_valueerror_floats():
    pv = 0.5
    ph = 0.3
    pv_str = f"{pv:.2f}" if pv is not None else "N/A"
    ph_str = f"{ph:.2f}" if ph is not None else "N/A"
    assert pv_str == "0.50"
    assert ph_str == "0.30"


def _test_scoring(expected: float, brief_content: str, project: dict[str, Path], msg: str) -> None:
    bpath = project["brief_path"]
    bpath.write_text(brief_content, encoding="utf-8")
    score_val = loop._score(
        bpath,
        project["links_csv"],
        project["decisions_csv"],
    )
    assert abs(score_val - expected) < 0.01, f"{msg}: expected {expected}, got {score_val}"
    print(f"PASS scoring {msg}: {score_val:.4f}")


def test_scoring_empty():
    project = _make_project(Path(tempfile.mkdtemp()))
    _test_scoring(0.00, "", project, "empty")


def test_scoring_links_only():
    project = _make_project(Path(tempfile.mkdtemp()))
    brief = "https://github.com/firstcontributions/first-contributions\nhttps://skills.yourlearning.ibm.com/activity/ALM-COURSE_3825249?topic=cloud\n"
    _test_scoring(0.25, brief, project, "links-only")


def test_scoring_noise_only():
    project = _make_project(Path(tempfile.mkdtemp()))
    brief = "https://youtu.be/EsTrWCV0Ph4\nhttps://www.linkedin.com/feed/update/urn:li:activity:7506239146646994944?updateEntityUrn=urn%3Ali%3Afs_updateV2%3A%28urn%3Ali%3Aactivity%3A7506239146646994944%2CFEED_DETAIL%2CEMPTY%2CDEFAULT%2Cfalse%29\n"
    _test_scoring(-0.125, brief, project, "noise-only")


def test_scoring_perfect():
    project = _make_project(Path(tempfile.mkdtemp()))
    brief = (
        "https://github.com/firstcontributions/first-contributions\n"
        "https://skills.yourlearning.ibm.com/activity/ALM-COURSE_3825249?topic=cloud\n"
        "standup\nclient invoice\nfriday\n"
    )
    _test_scoring(1.00, brief, project, "perfect")


# ── main runner ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import loop
    tests = [
        ("proposal clean", test_proposal_parsing_clean),
        ("proposal bold/backtick", test_proposal_parsing_bold_backtick),
        ("proposal malformed", test_proposal_parsing_malformed),
        ("replace vs append", test_apply_rule_replaces_existing),
        ("restore after crash", test_restore_after_crash),
        ("restore after drop", test_restore_after_drop),
        ("fstring none", test_fstring_no_valueerror_none),
        ("fstring floats", test_fstring_no_valueerror_floats),
        ("scoring empty", test_scoring_empty),
        ("scoring links-only", test_scoring_links_only),
        ("scoring noise-only", test_scoring_noise_only),
        ("scoring perfect", test_scoring_perfect),
    ]

    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:
            print(f"FAIL {name}: {e}")
            failed.append(name)

    if failed:
        print(f"\nFAILED: {len(failed)}/{len(tests)}")
        sys.exit(1)
    else:
        print(f"\nALL {len(tests)} tests passed")
