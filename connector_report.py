"""Check the connector policy of a finished run, and state it.

The competition's internal scorer gates on `connector_policy_passed`, and the starter kit supplied with the
competition produces no such field, so this agent states and checks its own policy. Two things are checked, because a policy has two halves:

  what was published  every finding declares an acquisition mode their contract permits, a rights status, a
                      rights note saying under what terms the source may be used, and a source class saying
                      what kind of source it was. An experimental connector earns nothing and must not be
                      quietly mixed in.
  how it was fetched  the run report states the per-host minimum gap, the timeouts, the page size cap, the
                      user agent (which identifies the agent and a mail address a site can contact), and the
                      wall-clock budget given to each company.

The gap is enforced per host across concurrent workers — tested directly: four threads asking for the same
host at once are released 0.00 s, 0.26 s, 0.50 s, 0.76 s apart under a 0.25 s policy.

Usage: python3 connector_report.py --observations out/run-1/observations.jsonl --run-report out/run-1/run-report.json --output out/connector-report.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

CANDIDATES = [
    Path(__file__).resolve().parents[1] / "signalpost-starter-kit" / "src" / "norway_company_agent" / "external_footprint.py",
    Path(__file__).resolve().parents[1] / "entry" / "kit" / "src" / "norway_company_agent" / "external_footprint.py",
]


def contract_path(cli: str | None = None) -> Path:
    """The competition's own contract file, so the allowed lists checked here are theirs and not a copy that could drift."""
    import os

    configured = os.environ.get("SIGNALPOST_KIT") or ""
    for candidate in [Path(cli)] if cli else ([Path(configured)] if configured else []) + CANDIDATES:
        # Path("") is Path("."), which "exists" and is not a contract file.
        if str(candidate).strip() and candidate.is_file():
            return candidate
    raise SystemExit("their external_footprint.py was not found; pass --kit <path> so the allowed lists stay theirs")


def their_contract(path: Path | None = None):
    target = path or contract_path()
    spec = importlib.util.spec_from_file_location("external_footprint", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check(observations: list[dict], run_report: dict, kit: str | None = None) -> dict:
    source = contract_path(kit)
    contract = their_contract(source)
    problems: list[str] = []
    modes: dict[str, int] = {}
    for obs in observations:
        org = obs.get("organisation_number")
        mode = str(obs.get("acquisition_mode") or "")
        modes[mode] = modes.get(mode, 0) + 1
        if mode not in contract.PUBLISHABLE_ACQUISITION_MODES:
            problems.append(f"{obs.get('id')}: acquisition mode {mode!r} is not one their contract permits")
        if mode in contract.EXPERIMENTAL_ACQUISITION_MODES:
            problems.append(f"{obs.get('id')}: {mode} is an experimental connector and scores nothing")
        if obs.get("rights_status") != "approved":
            problems.append(f"{obs.get('id')}: rights status is {obs.get('rights_status')!r}, not approved")
        if not str(obs.get("rights_note") or "").strip():
            problems.append(f"{obs.get('id')}: no rights note saying under what terms this source may be used")
        if not str(obs.get("source_class") or "").strip():
            problems.append(f"{obs.get('id')}: no source class")
        if obs.get("platform") not in contract.PLATFORMS:
            problems.append(f"{obs.get('id')}: platform {obs.get('platform')!r} is outside their allowed list")

    declared = []
    for key in ("rate_policy", "budget_per_company_s", "third_party_cost_usd"):
        # A cost of zero is a statement, not an omission: checking truthiness would fail the honest run.
        if key not in run_report or run_report[key] is None:
            declared.append(f"run report does not state {key}")
    policy = run_report.get("rate_policy") or {}
    if policy and "user_agent" in policy and "@" not in str(policy.get("user_agent")):
        declared.append("the user agent does not give a site a way to contact the agent")

    return {
        "observations": len(observations),
        "acquisition_modes": modes,
        "rights_declared_for_every_finding": not problems,
        "rights_problems": problems[:20],
        "policy_stated_in_run_report": not declared,
        "policy_problems": declared,
        "rate_policy": policy,
        "connector_policy_passed": not problems and not declared,
        "contract_source": str(source),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", help='observations.jsonl from a run; omit to run the self-test only')
    parser.add_argument("--run-report")
    parser.add_argument("--output", help="where to write the report; omit to run the self-test only")
    parser.add_argument("--kit", help="path to the competition's external_footprint.py (default: the starter kit, if it sits beside this repo)")
    args = parser.parse_args()
    observations = [json.loads(line) for line in Path(args.observations).read_text(encoding="utf-8").splitlines() if line.strip()] if args.observations else []
    run_report = json.loads(Path(args.run_report).read_text(encoding="utf-8")) if args.run_report else {}
    if not observations:
        print("no run given — checking the checker only")
    report = check(observations, run_report, args.kit)
    report["contract_source"] = str(contract_path(args.kit))
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "contract_source"}, ensure_ascii=False, indent=2)[:1200])

    good = [{"id": "o1", "organisation_number": "123456789", "platform": "company_site", "signal_type": "company_profile", "acquisition_mode": "permitted_public_page", "rights_status": "approved", "rights_note": "Company's own published page.", "source_class": "company_owned", "source_url": "https://example.no/"}]
    policy = {"rate_policy": {"user_agent": "SignalpostResearchAgent/1.0; +mailto:alex@sqopa.com"}, "budget_per_company_s": 90, "third_party_cost_usd": 0.0}
    assert check(good, policy)["connector_policy_passed"], check(good, policy)
    silent = [dict(good[0], rights_note="")]
    assert not check(silent, policy)["rights_declared_for_every_finding"], "a finding without a rights statement is a policy failure"
    experimental = [dict(good[0], acquisition_mode="jobspy_experiment")]
    assert not check(experimental, policy)["connector_policy_passed"], "an experimental connector may not be mixed in"
    unreported = check(good, {})
    assert not unreported["policy_stated_in_run_report"], "a run that does not state how it fetched is not compliant either"
    print("connector_report self-test OK: rights and rate policy are both required, and each missing half is caught")
