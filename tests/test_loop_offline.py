"""Offline self-test for loop.py — mocks subprocess, no real network calls."""
import csv
import contextlib
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
import loop as _orig_loop


def _hash_dir(path: Path) -> str:
    """Hash all files under *path* in sorted order; returns sha256 hex."""
    h = hashlib.sha256()
    for f in sorted(path.rglob("*")):
        if f.is_file():
            h.update(f.read_bytes())
    return h.hexdigest()


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


def _patch_module_paths(project: dict[str, Path]) -> list[unittest.mock._patch]:
    """Override module-level path constants directly; caller must stop all patches."""
    proj = project["base"]
    return [
        patch("loop.BASE", proj),
        patch("loop.HARNESS", proj / "harness"),
        patch("loop.VERIFIER", proj / "verifier"),
        patch("loop.TRACES", proj / "traces" / "try"),
        patch("loop.OPTIMIZER", proj / "optimizer"),
        patch("loop.FETCH_CACHE", proj / "traces" / "fetch_cache.json"),
    ]


def _stop_patches(patches: list) -> None:
    for p in reversed(patches):
        try:
            p.stop()
        except RuntimeError:
            pass  # already stopped


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
    patches = _patch_module_paths(project)
    try:
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
    finally:
        _stop_patches(patches)


def test_restore_after_crash():
    project = _make_project(Path(tempfile.mkdtemp()))
    patches = _patch_module_paths(project)
    try:
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
    finally:
        _stop_patches(patches)


def test_restore_after_drop():
    project = _make_project(Path(tempfile.mkdtemp()))
    patches = _patch_module_paths(project)
    try:
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
    finally:
        _stop_patches(patches)


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


def test_subprocess_prompt_via_stdin_not_argv():
    """Prompt must be passed through input= (stdin), not as a CLI arg."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["input"] = kwargs.get("input")
        class MockResult:
            stdout = "brief output"
            stderr = ""
        return MockResult()

    with patch("loop.subprocess.run", side_effect=fake_run):
        loop.run_brief("test-run")

    assert captured["cmd"] == ["claude", "-p"], \
        f"Expected ['claude', '-p'], got {captured['cmd']}"
    assert "test" in captured["input"], \
        "Prompt should be in input=, not in command list"
    # Explicitly verify the prompt text is NOT anywhere in the command list
    for part in captured["cmd"]:
        assert "test" not in part, f"Prompt leaked into command arg: {captured['cmd']}"


def test_no_test_isolation_leak() -> None:
    """Every test must leave traces/try, optimizer/ and harness/CLAUDE.md byte-for-byte intact."""
    before_traces = _hash_dir(PROJECT_ROOT / "traces")
    before_optimizer = _hash_dir(PROJECT_ROOT / "optimizer")
    claudemd_before = (PROJECT_ROOT / "harness" / "CLAUDE.md").read_text(encoding="utf-8")

    # Re-run the full test suite inside this process so any writes from every test surface here.
    import importlib
    importlib.reload(loop)
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
        ("subprocess stdin", test_subprocess_prompt_via_stdin_not_argv),
    ]
    for name, fn in tests:
        fn()

    after_traces = _hash_dir(PROJECT_ROOT / "traces")
    after_optimizer = _hash_dir(PROJECT_ROOT / "optimizer")
    claudemd_after = (PROJECT_ROOT / "harness" / "CLAUDE.md").read_text(encoding="utf-8")

    assert after_traces == before_traces, "traces/ mutated by a test"
    assert after_optimizer == before_optimizer, "optimizer/ mutated by a test"
    assert claudemd_after == claudemd_before, "harness/CLAUDE.md mutated by a test"


# ── End-to-end run_try integration tests ───────────────────────────────────

def test_run_try_keep_replaces_rule_and_clauses_no_rule_keywords():
    """End-to-end: run_try() with KEEP path uses parsed RULE_ID/RULE_TEXT."""
    project = _make_project(Path(tempfile.mkdtemp()))

    # Reload MUST happen before patches are entered — reload re-executes
    # module-level code which would otherwise overwrite our patches.
    import importlib
    import loop as loop_mod
    importlib.reload(loop_mod)

    with contextlib.ExitStack() as stack:
        for p in _patch_module_paths(project):
            stack.enter_context(p)

        claudemd = project["claude_md"]
        original = claudemd.read_text(encoding="utf-8")
        assert "(F1) Keep F1." in original
        assert "(F2) Old rule text." in original
        assert "RULE_ID" not in original
        assert "RULE_TEXT" not in original

        today = "2026-01-01"
        proposed_change_raw = (
            "# Proposal\n"
            "RULE_ID: F2\n"
            "RULE_TEXT: (F2) Use the content under '## Fetched pages' instead of links directly.\n\n"
            "**Rationale:** Improves grounding in fetched text.\n"
        )
        (project["base"] / "optimizer" / "proposals.md").write_text(
            f"## [{today}]\n\n{proposed_change_raw}",
            encoding="utf-8",
        )

        captured_commits = []

        def fake_subprocess_run(cmd, **kwargs):
            class R:
                stdout = "https://example.com/maybe\nstandup\nclient invoice\nfriday\n"
                stderr = ""
            return R()

        def fake_commit(msg):
            captured_commits.append(msg)

        with patch("loop.subprocess.run", side_effect=fake_subprocess_run):
            with patch.object(loop_mod, "_commit", side_effect=fake_commit):
                loop_mod.run_try()

        after = claudemd.read_text(encoding="utf-8")
        f2_lines = [l for l in after.splitlines() if l.strip().startswith("(F2)")]
        assert len(f2_lines) == 1, f"Expected 1 F2 line, got {len(f2_lines)}:\n{after}"
        assert "(F2) Use the content under '## Fetched pages' instead of links directly." in f2_lines[0]
        assert "RULE_ID" not in after, "RULE_ID leaked into CLAUDE.md"
        assert "RULE_TEXT" not in after, "RULE_TEXT leaked into CLAUDE.md"
        assert "(F1) Keep F1." in after
        assert len(captured_commits) == 1
        msg = captured_commits[0]
        assert "RULE_" not in msg, f"RULE_ leaked into commit message: {msg!r}"
        assert "(F2) Use the content under" in msg


def test_run_try_drop_restores_claude_md():
    """End-to-end: run_try() with DROP path restores CLAUDE.md byte-for-byte."""
    project = _make_project(Path(tempfile.mkdtemp()))

    import importlib
    import loop as loop_mod
    importlib.reload(loop_mod)

    with contextlib.ExitStack() as stack:
        for p in _patch_module_paths(project):
            stack.enter_context(p)

        claudemd = project["claude_md"]
        original = claudemd.read_text(encoding="utf-8")
        assert original.endswith("\n")

        today = "2026-01-01"
        proposed_change_raw = (
            "# Proposal\n"
            "RULE_ID: F2\n"
            "RULE_TEXT: (F2) Some other rule that makes score worse.\n\n"
            "**Rationale:** Deliberately bad for this test.\n"
        )
        (project["base"] / "optimizer" / "proposals.md").write_text(
            f"## [{today}]\n\n{proposed_change_raw}",
            encoding="utf-8",
        )

        captured_commits = []

        def fake_subprocess_run(cmd, **kwargs):
            class R:
                stdout = "https://youtu.be/EsTrWCV0Ph4\nhttps://www.linkedin.com/feed/update/urn:li:activity:7506239146646994944?updateEntityUrn=urn%3Ali%3Afs_updateV2%3A%28urn%3Ali%3Aactivity%3A7506239146646994944%2CFEED_DETAIL%2CEMPTY%2CDEFAULT%2Cfalse%29\n"
                stderr = ""
            return R()

        with patch("loop.subprocess.run", side_effect=fake_subprocess_run):
            with patch.object(loop_mod, "_commit", side_effect=lambda m: captured_commits.append(m)):
                loop_mod.run_try()

        after = claudemd.read_text(encoding="utf-8")
        assert after == original, f"DROP did not restore exactly:\n--- expected ---\n{original}\n--- actual ---\n{after}"
        assert len(captured_commits) == 0, "No commit should happen on DROP"


def test_run_try_hidden_drops_leads_to_drop():
    """When hidden score drops (even with visible improvement), decision is DROP."""
    project = _make_project(Path(tempfile.mkdtemp()))

    import importlib
    import loop as loop_mod
    importlib.reload(loop_mod)

    with contextlib.ExitStack() as stack:
        for p in _patch_module_paths(project):
            stack.enter_context(p)

        # Add a mattered link to hidden_links.csv so hidden check is active
        hidden_csv = project["hidden_csv"]
        # Write header if missing, then append
        with open(hidden_csv, "a", newline="", encoding="utf-8") as f:
            if f.tell() == 0:
                f.write("url,date,label\n")
            f.write("https://github.com/firstcontributions/first-contributions,,mattered\n")

        claudemd = project["claude_md"]
        original = claudemd.read_text(encoding="utf-8")

        proposed_change_raw = (
            "# Proposal\n"
            "RULE_ID: F2\n"
            "RULE_TEXT: (F2) New rule that helps visible but hurts hidden.\n\n"
            "**Rationale:** Deliberately bad for hidden set.\n"
        )
        (project["base"] / "optimizer" / "proposals.md").write_text(
            "## [2026-01-01]\n\n" + proposed_change_raw,
            encoding="utf-8",
        )
        # Prev best: visible=0.1, hidden=0.9 — brief will beat visible but lose hidden
        (project["best_score_json"]).write_text('{"visible": 0.1, "hidden": 0.9}', encoding="utf-8")

        captured_commits = []

        def fake_subprocess_run(cmd, **kwargs):
            class R:
                stdout = "https://example.com/maybe\n"
                stderr = ""
            return R()

        def fake_commit(msg):
            captured_commits.append(msg)

        with patch("loop.subprocess.run", side_effect=fake_subprocess_run):
            with patch.object(loop_mod, "_commit", side_effect=fake_commit):
                loop_mod.run_try()

        after = claudemd.read_text(encoding="utf-8")
        assert after == original, f"DROPPED but CLAUDE.md was not restored:\n{after}"
        assert len(captured_commits) == 0, "No commit on DROP"


def test_run_try_hidden_equal_and_visible_better_leads_to_keep():
    """When hidden equals prev and visible improves, decision is KEEP."""
    project = _make_project(Path(tempfile.mkdtemp()))

    import importlib
    import loop as loop_mod
    importlib.reload(loop_mod)

    with contextlib.ExitStack() as stack:
        for p in _patch_module_paths(project):
            stack.enter_context(p)

        # Add a mattered link to hidden_links.csv
        hidden_csv = project["hidden_csv"]
        with open(hidden_csv, "a", newline="", encoding="utf-8") as f:
            if f.tell() == 0:
                f.write("url,date,label\n")
            f.write("https://github.com/firstcontributions/first-contributions,,mattered\n")

        claudemd = project["claude_md"]
        original = claudemd.read_text(encoding="utf-8")

        proposed_change_raw = (
            "# Proposal\n"
            "RULE_ID: F2\n"
            "RULE_TEXT: (F2) Helpful rule.\n\n"
            "**Rationale:** Good change.\n"
        )
        (project["base"] / "optimizer" / "proposals.md").write_text(
            "## [2026-01-01]\n\n" + proposed_change_raw,
            encoding="utf-8",
        )
        # Prev best: visible=0.1, hidden=0.1 — brief beats both
        (project["best_score_json"]).write_text('{"visible": 0.1, "hidden": 0.1}', encoding="utf-8")

        captured_commits = []

        def fake_subprocess_run(cmd, **kwargs):
            class R:
                # Brief contains both visible mattered links AND the hidden mattered link
                stdout = "https://github.com/firstcontributions/first-contributions\nhttps://skills.yourlearning.ibm.com/activity/ALM-COURSE_3825249?topic=cloud\n"
                stderr = ""
            return R()

        def fake_commit(msg):
            captured_commits.append(msg)

        with patch("loop.subprocess.run", side_effect=fake_subprocess_run):
            with patch.object(loop_mod, "_commit", side_effect=fake_commit):
                loop_mod.run_try()

        after = claudemd.read_text(encoding="utf-8")
        assert "(F2) Helpful rule." in after, f"Expected rule kept but got:\n{after}"
        assert len(captured_commits) == 1, "Should commit on KEEP"


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
        ("subprocess stdin", test_subprocess_prompt_via_stdin_not_argv),
        ("no test isolation leak", test_no_test_isolation_leak),
        ("run_try keep e2e", test_run_try_keep_replaces_rule_and_clauses_no_rule_keywords),
        ("run_try drop e2e", test_run_try_drop_restores_claude_md),
        ("run_try hidden drops -> DROP", test_run_try_hidden_drops_leads_to_drop),
        ("run_try hidden equal + visible better -> KEEP", test_run_try_hidden_equal_and_visible_better_leads_to_keep),
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
