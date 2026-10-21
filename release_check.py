"""Refuse a release that reads like working notes.

Everything in this repository becomes public when it is pushed. Working notes are not the same thing as a
product document: they name machines on a local network, scratch directories from earlier runs, decision
numbers from a private log, and people who are not part of this product. None of those mean anything to a
reader at the other end, and their presence says the release was not reviewed.

This runs the check mechanically over the files git would publish, before the push rather than after.

Usage: python3 release_check.py [--root .]
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

# Things that belong to a private workspace. Each pattern is a category, not a one-off word: the point is
# that a new note in the same category is caught too.
# Negative controls for the self-test. They are test data, so the scan skips lines of this file that
# contain them: a checker that flags its own examples cannot be used to check itself.
SAMPLES = {
    "private network address": "BASE = 'http://192.168.0.217:18783/search'",
    "internal workspace path": "see alex-workspace/decisions for why",
    "private decision or task id": "measured on 148 (D213)",
    "scratch run directory": "numbers from out/run150e",
    "a person who is not part of this product": "waiting on Jaiden for the repo",
    "notes-to-self phrasing": "I measured this and decided to stop",
}



CATEGORIES = {
    "private network address": r"\b192\.168\.\d+\.\d+\b|\b10\.\d+\.\d+\.\d+\b|\b172\.\d{2}\.\d+\.\d+\b",
    "local hostname or ssh alias": r"\blab97\b|\balexmac\b|\npc@192|\b\.97\b|\bthis-mac\b",
    "internal workspace path": r"alex-workspace|~/Desktop/|~/.pi/|Time Capsule",
    "private decision or task id": r"\bD\d{3,4}\b(?![_a-z])",
    "scratch run directory": r"\bout/run\d{2,4}[a-z]?\b",
    "another project of the same author": r"\bsolarium\b|\bduskhunt\b|\bkelvar\b|\bsongcraft\b|\bstrata\b",
    "a person who is not part of this product": r"\bJaiden\b",
    "notes-to-self phrasing": r"\bmy own (?:agent|run|notes|prompt|workspace)\b|\bI (?:measured|found|decided)\b|\bnext session\b|\bTODO\b",
}

ALLOWED_IN_CODE_NAMES = {
    # the exception list exists so a check can be strict without being silly: these are identifiers in the
    # competition's own contract or in ordinary English usage, not private shorthand.
    "out/run-1": "an example output directory in the documented command",
    "out/run-0": "an example previous run in the documented command",
}


def tracked_files(root: Path) -> list[str]:
    result = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit("release_check must run inside a git repository — the check is about what would be published")
    return [line for line in result.stdout.splitlines() if line.strip()]


def scan(root: Path) -> dict:
    findings: dict[str, list[str]] = {}
    allowed_hits: list[str] = []
    for relative in tracked_files(root):
        path = root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # The words this checker searches for are the words it contains, and its negative controls are test
        # data. A tool that flags its own vocabulary can never pass its own check.
        own_text = tuple(SAMPLES.values()) + tuple(str(v) for v in CATEGORIES.values())
        own_file = path.name == Path(__file__).name
        for lineno, line in enumerate(text.splitlines(), 1):
            if own_file and any(own in line for own in own_text):
                continue
            for stripped in ALLOWED_IN_CODE_NAMES:
                if stripped in line:
                    allowed_hits.append(f"{relative}:{lineno}: {stripped} — {ALLOWED_IN_CODE_NAMES[stripped]}")
            for category, pattern in CATEGORIES.items():
                match = re.search(pattern, line, re.I)
                if match and not any(word in line for word in ALLOWED_IN_CODE_NAMES):
                    findings.setdefault(category, []).append(f"{relative}:{lineno}: {line.strip()[:110]}")
    return {"files_checked": len(tracked_files(root)), "findings": findings, "allowed_examples": allowed_hits[:8]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    report = scan(root)
    if report["findings"]:
        print("not ready to publish:")
        for category, hits in report["findings"].items():
            print(f"  {category}: {len(hits)}")
            for hit in hits[:6]:
                print(f"    {hit}")
    else:
        print(f"release check clean over {report['files_checked']} tracked files")

    # Self-test: each category is caught, and the allowed examples are not.
    for category, line in SAMPLES.items():
        assert re.search(CATEGORIES[category], line, re.I), (category, line)
    for allowed in ("python3 agent.py --orgs orgs.jsonl --out out/run-1 --budget 90",):
        assert not any(re.search(pattern, allowed, re.I) for pattern in CATEGORIES.values()), allowed
    print("release_check self-test OK: private shorthand is caught, documented example paths are not")
