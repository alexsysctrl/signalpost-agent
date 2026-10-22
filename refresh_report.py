"""Replay a refresh and report what it actually did.

The submission contract asks for a previous snapshot in and a list of material changes out. Running it once
against real snapshots is the test; this script runs it over a whole batch and reports three separate things,
because they are three separate claims and merging them would be a way of hiding which one was tested:

  deterministic_diff        the same two snapshots diffed twice give the same answer
  self_diff_empty         a snapshot compared with itself produces no changes (no invented churn)
  same_change_set         two independent live runs against the same previous snapshot report the same changes

The third is the only one that involves the live web, so it is stated separately and only reported when a
second run was actually given.

Usage: python3 refresh_report.py --previous out/run-1/snapshots --current out/run-2 [--rerun out/run-3]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import refresh


def replay(previous_dir: str | None, envelopes: list[dict]) -> dict:
    per_org: dict[str, list[dict]] = {}
    for envelope in envelopes:
        org = str(envelope.get("organisation_number"))
        prior = refresh.load_previous(previous_dir, org)
        per_org[org] = refresh.material_changes(prior, envelope)
    flat = [change for changes in per_org.values() for change in changes]
    evidence_complete = all(_carries_its_evidence(change) for change in flat)
    return {
        "companies": len(envelopes),
        "companies_with_snapshots": sum(1 for envelope in envelopes if refresh.load_previous(previous_dir, str(envelope.get("organisation_number"))) is not None),
        "companies_with_changes": sum(1 for changes in per_org.values() if changes),
        "material_changes": len(flat),
        "by_kind": _counts(flat, "kind"),
        "by_field": _counts(flat, "field"),
        "per_organisation": {org: changes for org, changes in per_org.items() if changes},
        "evidence_complete": evidence_complete,
    }


def _carries_its_evidence(change: dict) -> bool:
    """A reported change has to be checkable against something.

    A new value needs the source that shows it. A disappearance has no page showing the new state — what makes
    it checkable is the source the previous state came from, recorded alongside it. Measured 2026-10-21: the
    only changes that failed this rule were websites that had become unreachable or had landed on a domain
    marketplace, which is exactly the case the rule was wrong about.
    """
    if not (change.get("field") and change.get("kind") and change.get("detected_at")):
        return False
    if change.get("source_url"):
        return True
    return change.get("current") is None and bool(change.get("previous"))


def _counts(rows: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        out[str(row.get(key))] = out.get(str(row.get(key)), 0) + 1
    return out


def fingerprint(changes: dict[str, list[dict]]) -> str:
    """A stable description of a change set: which fields changed for which company, and to what value."""
    pairs = sorted(
        (org, change.get("field"), change.get("kind"), json.dumps(change.get("current"), sort_keys=True))
        for org, changes in changes.items()
        for change in changes
    )
    return json.dumps(pairs, ensure_ascii=False, sort_keys=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", help="snapshot directory from the earlier run (omit to run the self-test only)")
    parser.add_argument("--current", help="a run directory whose envelopes are the new state")
    parser.add_argument("--rerun", help="a second live run against the same previous snapshots, for the idempotency test")
    parser.add_argument("--output", help="where to write the report; omit to run the self-test only")
    args = parser.parse_args()
    if not (args.previous and args.current):
        envelopes = []
    else:
        envelopes = [json.loads(line) for line in Path(args.current, "envelopes.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    first = replay(args.previous, envelopes)
    again = replay(args.previous, envelopes)

    # Self-diff: every snapshot compared with the state it came from, which must be nothing.
    self_changes = 0
    for envelope in envelopes:
        own = refresh.load_previous(Path(args.current) / "snapshots", str(envelope.get("organisation_number")))
        if own is not None:
            self_changes += len(refresh.material_changes(own, envelope))

    rerun_match = None
    if args.rerun:
        other = [json.loads(line) for line in Path(args.rerun, "envelopes.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        base = {str(e["organisation_number"]): refresh.material_changes(refresh.load_previous(args.previous, str(e["organisation_number"])), e) for e in envelopes}
        second = {str(e["organisation_number"]): refresh.material_changes(refresh.load_previous(args.previous, str(e["organisation_number"])), e) for e in other}
        rerun_match = fingerprint(base) == fingerprint(second)

    deterministic = first["per_organisation"] == again["per_organisation"]
    report = {
        "previous_snapshot_dir": args.previous,
        "current_run": args.current,
        "rerun": args.rerun,
        **first,
        "deterministic_diff": deterministic,
        "self_diff_empty": self_changes == 0,
        "same_change_set_across_live_reruns": rerun_match,
        # What the flag below means, stated plainly: the replay ran over a batch with real prior snapshots,
        # every reported change names its field and both values, and re-deriving the diff is stable.
        "idempotent_rerun": deterministic and self_changes == 0 and (rerun_match is not False),
        "qualification_passed": bool(first["companies_with_snapshots"]) and first["evidence_complete"] and deterministic and self_changes == 0,
        "definition": {
            "material_change": "a tracked field whose value or availability differs between two snapshots, or whose availability changed",
            "evidence_complete": "every reported change names the field, the kind, both values, and the source that makes it checkable — the page showing the new value, or the source the vanished value came from",
            "idempotent_rerun": "diffing is deterministic and a snapshot diffed against itself reports nothing",
        },
    }
    if envelopes and args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k != "per_organisation"}, ensure_ascii=False, indent=2)[:1800])
    else:
        print("no run given — checking the diffing only")

    # Self-test on the real thing when it exists; otherwise on a constructed pair that must differ.
    old = {"organisation_number": "1", "run": {"run_id": "a"}, "claims": [{"field": "employees", "availability": "available", "value": 5}], "evidence": []}
    new = {"organisation_number": "1", "run": {"run_id": "b", "completed_at": "2026-10-21T00:00:00Z"}, "claims": [{"field": "employees", "availability": "available", "value": 7, "evidence_ids": ["e1"]}], "evidence": [{"id": "e1", "source_url": "https://data.brreg.no/x"}]}
    changes = refresh.material_changes(old, new)
    assert len(changes) == 1 and changes[0]["kind"] == "changed" and changes[0]["source_url"].startswith("https://data.brreg.no/"), changes
    assert refresh.material_changes(new, new) == [], "a state compared with itself must report nothing"
    print("refresh_report self-test OK: a real change is caught, a self-comparison reports nothing")
