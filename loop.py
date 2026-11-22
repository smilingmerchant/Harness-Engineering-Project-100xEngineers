#!/usr/bin/env python3
"""loop.py - Run the harness agent via `claude -p` (non-interactive mode).

Usage:
    py loop.py brief <run_id>
"""
import os
import sys
import json
import subprocess
from pathlib import Path


def run_brief(run_id: str):
    base_dir = Path(__file__).parent.resolve()

    # 1. Read input files ONLY from harness/ and project root
    claude_md = (base_dir / "harness" / "CLAUDE.md").read_text(encoding="utf-8")
    sources_md = (base_dir / "harness" / "sources.md").read_text(encoding="utf-8")
    memory_md = (base_dir / "harness" / "memory.md").read_text(encoding="utf-8")
    links_txt = (base_dir / "links.txt").read_text(encoding="utf-8")

    # 2. Construct prompt (never referencing verifier/)
    prompt = f"""You are the harness agent. Follow these instructions:

{claude_md}

## Sources
{sources_md}

## Links
{links_txt}

## Memory / Context
{memory_md}

Write the morning brief directly as your response. Return ONLY the markdown brief with three headers:
## What changed
## Who disagrees with whom
## What to do
"""

    # 3. Call `claude -p` using subprocess
    cmd = ["claude", "-p", prompt]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    brief_output = result.stdout.strip()

    # 4. Save outputs to traces/try/
    trace_dir = base_dir / "traces" / "try"
    trace_dir.mkdir(parents=True, exist_ok=True)

    (trace_dir / "brief.md").write_text(brief_output, encoding="utf-8")

    # Save execution record
    trace_data = {
        "run_id": run_id,
        "prompt": prompt,
        "cmd": ["claude", "-p", "..."],
        "stdout": brief_output,
        "stderr": result.stderr,
    }
    (trace_dir / "trace.json").write_text(json.dumps(trace_data, indent=2), encoding="utf-8")

    print(f"Brief written to: {trace_dir / 'brief.md'}")
    print(f"Trace written to: {trace_dir / 'trace.json'}")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "brief":
        print("Usage: py loop.py brief <run_id>")
        sys.exit(1)

    run_brief(sys.argv[2])