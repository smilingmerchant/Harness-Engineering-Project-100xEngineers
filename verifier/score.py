#!/usr/bin/env python3
"""Score a morning brief against decisions.csv.

Scoring rules:
- +1 per link that mattered and made the brief
- +2 per decision called right
- -0.5 per noise item called important
Divided by (number of mattered links + 2 x number of decisions)
"""
import csv
import sys
from pathlib import Path


def score(brief_path: str, decisions_path: str, links_csv_path: str) -> float:
    """Calculate the score for a brief."""
    # Read links to find what mattered
    mattered_links = []
    with open(links_csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("label") == "mattered":
                mattered_links.append(row["url"])

    # Read decisions
    decisions = []
    with open(decisions_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            decision = row.get("decision", "").strip()
            right_answer = row.get("right_answer", "").strip()
            if decision:
                decisions.append((decision, right_answer))

    # Read brief and count hits
    with open(brief_path, encoding="utf-8") as f:
        brief_text = f.read().lower()

    # Check which mattered links appear in brief
    matters_hit = 0
    for url in mattered_links:
        if url.lower() in brief_text:
            matters_hit += 1

    # A decision counts as correct only if its right answer appears in the brief
    decisions_correct = sum(1 for _, ra in decisions if ra and ra.lower() in brief_text)

    # Noise items (non-mattered, non-empty, non-maybe labels)
    noise_items = [row["url"] for row in csv.DictReader(open(links_csv_path, newline="", encoding="utf-8"))
                   if row.get("label") not in ("mattered", "", "maybe")]
    noise_called = sum(1 for url in noise_items if url.lower() in brief_text)

    numerator = (matters_hit * 1) + (decisions_correct * 2) - (noise_called * 0.5)
    denominator = len(mattered_links) + 2 * len(decisions)

    if denominator == 0:
        return 0.0
    return numerator / denominator


if __name__ == "__main__":
    if len(sys.argv) == 2 and Path(sys.argv[1]).is_dir():
        # Auto-fill paths when given a trace directory like `traces/try`
        base = Path(__file__).parent.parent.resolve()
        brief_path = Path(sys.argv[1]) / "brief.md"
        decisions_path = base / "verifier" / "decisions.csv"
        links_csv_path = base / "verifier" / "links.csv"
    elif len(sys.argv) == 4:
        brief_path = sys.argv[1]
        decisions_path = sys.argv[2]
        links_csv_path = sys.argv[3]
    else:
        print("Usage: python score.py <brief_path> <decisions_path> <links_csv_path>")
        print("   or: python score.py <trace_directory>")
        sys.exit(1)

    score_val = score(brief_path, decisions_path, links_csv_path)
    print(f"Score: {score_val:.2f}")