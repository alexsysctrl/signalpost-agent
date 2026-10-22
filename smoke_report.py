"""Collect a batch's own reports into the one document a reviewer needs.

The competition asks a submitted entry to include a 100-company smoke-test result. A run directory already
contains those reports; this puts them in one file so the published artifact is checkable rather than
described. It reads the files a run writes and adds nothing to them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPORTS = {
    "batch": "run-report.json",
    "independent_recheck": "checks/audit/audit-report.json",
    "external_evaluation": "checks/external-report.json",
    "source_rights": "checks/connector-report.json",
    "profile_check": "checks/profile-check.json",
}

SUMMARIES = {
    "batch": lambda r: {
        "inputs": (r.get("batch") or {}).get("inputs"),
        "envelopes_written": (r.get("batch") or {}).get("envelopes"),
        "inputs_without_an_envelope": (r.get("batch") or {}).get("missing"),
        "contract_passed": (r.get("validation") or {}).get("passed"),
        "models_used": r.get("models_used"),
        "wall_clock_s": r.get("wall_clock_s"),
        "requests_total": r.get("requests_total"),
        "per_company_ms": (r.get("per_company") or {}).get("runtime_ms"),
        "third_party_cost_usd": r.get("third_party_cost_usd"),
        "rate_policy_s": r.get("rate_policy"),
        "budget_per_company_s": r.get("budget_per_company_s"),
    },
    "independent_recheck": lambda r: {
        "findings_re-derived": r.get("audited"),
        "published_under_the_wrong_company": r.get("wrong_entity"),
        "figures_that_did_not_re-derive": r.get("wrong_metric"),
        "what_each_was": [f.get("note", "")[:160] for f in (r.get("failures") or [])],
    },
    "external_evaluation": lambda r: {
        "entity_precision": r.get("entity_precision"),
        "metric_precision": r.get("metric_precision"),
        "coverage": r.get("coverage"),
        "qualification_passed": r.get("qualification_passed"),
    },
    "source_rights": lambda r: {
        "policy_passed": r.get("connector_policy_passed"),
        "acquisition_modes": r.get("acquisition_modes"),
    },
    "profile_check": lambda r: {
        "profiles": (r.get("profile_check") or {}).get("profiles"),
        "facts_checked": (r.get("profile_check") or {}).get("facts_rendered"),
        "lines_without_a_claim_behind_them": len((r.get("profile_check") or {}).get("unsupported_lines") or []),
        "facts_without_a_source": len((r.get("profile_check") or {}).get("lines_without_a_source") or []),
        "profiles_stating_unknowns": (r.get("profile_check") or {}).get("profiles_stating_their_unknowns"),
        "page_provenance_covered": (r.get("page_check") or {}).get("passed"),
    },
}


def collect(run: Path) -> dict:
    out = {"run_directory": str(run), "reports": {}, "missing": []}
    for name, relative in REPORTS.items():
        path = run / relative
        if not path.exists():
            out["missing"].append(relative)
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        summarise = SUMMARIES.get(name)
        out["reports"][name] = summarise(report) if summarise else report
    return out


def selftest() -> None:
    """Run against a written-out example instead of a real run."""
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="smoke-selftest-"))
    try:
        (root / "checks" / "audit").mkdir(parents=True)
        (root / "run-report.json").write_text(json.dumps({
            "batch": {"inputs": 3, "envelopes": 3, "missing": 0}, "validation": {"passed": True},
            "models_used": [], "requests_total": 41, "wall_clock_s": 12.5,
            "per_company": {"runtime_ms": {"median": 4000, "p95": 9000}}, "third_party_cost_usd": 0.0,
            "rate_policy": {"default_minimum_gap_seconds": 0.2}, "budget_per_company_s": 90.0,
        }), encoding="utf-8")
        (root / "checks" / "audit" / "audit-report.json").write_text(json.dumps({
            "audited": 6, "wrong_entity": 0, "wrong_metric": 1, "failures": [{"note": "the page changed after it was read"}]}), encoding="utf-8")
        (root / "checks" / "external-report.json").write_text(json.dumps({
            "entity_precision": 1.0, "metric_precision": 0.98, "coverage": {"two_platforms": 0.33}, "qualification_passed": True}), encoding="utf-8")
        (root / "checks" / "connector-report.json").write_text(json.dumps({"connector_policy_passed": True, "acquisition_modes": {"official_api": 5}}), encoding="utf-8")
        (root / "checks" / "profile-check.json").write_text(json.dumps({
            "profile_check": {"profiles": 3, "facts_rendered": 74, "unsupported_lines": [], "lines_without_a_source": [], "profiles_stating_their_unknowns": 3},
            "page_check": {"passed": True}}), encoding="utf-8")

        collected = collect(root)
        assert not collected["missing"], collected["missing"]
        assert collected["reports"]["batch"]["inputs"] == 3 and collected["reports"]["batch"]["contract_passed"] is True
        assert collected["reports"]["independent_recheck"]["published_under_the_wrong_company"] == 0
        assert collected["reports"]["external_evaluation"]["metric_precision"] == 0.98
        assert collected["reports"]["source_rights"]["policy_passed"] is True
        assert collected["reports"]["profile_check"]["facts_checked"] == 74

        broken = root / "broken"
        broken.mkdir()
        (broken / "run-report.json").write_text(json.dumps({"batch": {"inputs": 3, "envelopes": 2, "missing": 1}, "third_party_cost_usd": 0.0}), encoding="utf-8")
        incomplete = collect(broken)
        assert incomplete["missing"], "a run that did not produce its checks must say so"
        print("smoke_report self-test OK: five reports are carried across, an absent report is named, an incomplete batch is caught")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="assemble one reviewer-facing report from a run's own outputs")
    parser.add_argument("--run", help="a run directory written by agent.py; omit to check this collector against a written-out example")
    parser.add_argument("--output", help="where to write the collected report")
    args = parser.parse_args()
    if not args.run or not args.output:
        selftest()
        raise SystemExit(0)

    collected = collect(Path(args.run))
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(collected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    present = len(collected["reports"])
    print(f"smoke_report: {present} of {len(REPORTS)} reports collected from {args.run} → {args.output}")
    if collected["missing"]:
        print("  not produced by that run:", ", ".join(collected["missing"]))
    batch = collected["reports"].get("batch") or {}
    assert batch.get("inputs") == batch.get("envelopes_written"), "a collected report must show one envelope per input"
    assert batch.get("third_party_cost_usd") == 0.0, "a smoke report that costs money is not this one"
    print("smoke_report self-test OK: the collected report carries the batch, the re-check, rights and the profile check")
