"""Run their frozen research-agent suite against my research layer, and score it the way they score it.

Their `evaluate_research_agent.py` imports their own agent, so running it measures their work, not mine. This
uses the same suite, the same six items and the same point values, over profiles my agent produced. The point
of matching their item names exactly is that the number means the same thing.

One item their scorer reads is not emitted by their own evaluator: `external_footprint_qa_passed`. It is
defined here, tested, and the definition is written into the report:

    every fact the answer states carries the source, retrieval time and content hash it was published with,
    the unsupported question abstains, and where the run published a non-registry source for that company,
    the answer uses at least one of them. A company with no external footprint cannot be made to pass that
    last part, so the requirement only applies when such a source exists — and the report says which case
    was actually met.

Usage: python3 evaluate_research_kit.py --envelopes out/suite14/envelopes.jsonl \
        --suite ../entry/kit/tests/fixtures/research-agent-suite-submission-1000.json --output out/research-report.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

import research
import workspace as workspace_mod

REGISTRY_HOSTS = {"data.brreg.no", "www.data.brreg.no", "s2336772.diskusjon.no", "api.data.brreg.no"}


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def external_sources(envelope: dict) -> list[dict]:
    out = []
    for item in envelope.get("evidence") or []:
        host = (urlsplit(str(item.get("source_url") or "")).hostname or "").lower()
        if host and host not in REGISTRY_HOSTS:
            out.append(item)
    return out


ACTIVITY_QUESTION = "What does this company do, and what does it publish itself — its own site, activity or openings?"


def host_of(url: str) -> str:
    return (urlsplit(str(url or "")).hostname or "").lower()


def footprint_activity_probe(envelopes: list[dict]) -> dict:
    """Ask a footprint question of a company whose footprint the run actually found.

    Choosing a company with no external evidence would make the test vacuous, so the company is chosen by
    the evidence: the first profile in the batch with a source outside the register. If the batch has none,
    the probe reports that it could not be run rather than reporting a pass.
    """
    target = next((e for e in envelopes if external_sources(e)), None)
    if target is None:
        return {"passed": False, "reason": "no company in this corpus has a source outside the register, so the probe could not be run"}
    answer = research.answer_profile(target, ACTIVITY_QUESTION)
    cited = [f for f in answer["facts"] if f.get("source_url") and f.get("retrieved_at") and f.get("content_sha256")]
    external_cited = sorted({host_of(f["source_url"]) for f in cited} - REGISTRY_HOSTS)
    return {
        "passed": bool(answer["facts"]) and len(cited) == len(answer["facts"]) and bool(external_cited),
        "organisation_number": target.get("organisation_number"),
        "name": next((c.get("value") for c in target.get("claims", []) if c.get("field") == "legal_name"), None),
        "question": ACTIVITY_QUESTION,
        "facts": len(answer["facts"]),
        "cited": len(cited),
        "non_registry_hosts_cited": external_cited,
        "external_sources_published_for_this_company": len(external_sources(target)),
    }


def evaluate(envelopes: list[dict], suite: dict) -> dict:
    by_org = {str(row["organisation_number"]): row for row in envelopes}

    spec = suite["single_company"]
    envelope = by_org.get(str(spec["organisation_number"]))
    answer = research.answer_profile(envelope, spec["question"]) if envelope else {"facts": []}
    cited = [f for f in answer["facts"] if f.get("source_url") and f.get("retrieved_at") and f.get("content_sha256")]
    single_supported = len(answer["facts"]) >= spec["minimum_facts"] and len(cited) == len(answer["facts"])

    # Is the answer standing on the published footprint, or only on the registry? Tested in three parts,
    # because "evidence-bounded" is not one property: a leadership question genuinely belongs to the
    # register, while a question about what a company does and where it publishes belongs to the footprint
    # the run found. Both have to hold, and the third (not inventing a sentiment) has to hold too.
    bounded = bool(answer["facts"]) and len(cited) == len(answer["facts"])
    activity_probe = footprint_activity_probe(envelopes)

    screen_results: list[dict] = []
    exact_screens = exact_plans = 0
    citations_complete = True
    state = workspace_mod.empty_workspace()
    for screen in suite["screens"]:
        result = research.screen_profiles(envelopes, screen["query"])
        actual = [str(item["organisation_number"]) for item in result.get("results", [])]
        exact = actual == [str(o) for o in screen["expected_organisation_numbers"]]
        plan_fields = [item["field"] for item in result.get("plan", {}).get("filters", [])]
        plan_exact = plan_fields == list(screen["expected_filter_fields"])
        complete = all(
            citation.get("source_url") and citation.get("retrieved_at") and citation.get("content_sha256")
            for item in result.get("results", [])
            for citation in item.get("citations", [])
        )
        exact_screens += int(exact)
        exact_plans += int(plan_exact)
        citations_complete = citations_complete and complete
        state = workspace_mod.record_screen(state, result, pin_organisations=actual[:1])
        screen_results.append(
            {
                "query": screen["query"],
                "expected": screen["expected_organisation_numbers"],
                "actual": actual,
                "exact_membership_and_order": exact,
                "exact_plan": plan_exact,
                "citations_complete": complete,
                "plan": result.get("plan"),
            }
        )

    unsupported = research.screen_profiles(envelopes, suite["unsupported"]["query"])
    abstention = bool(unsupported.get("abstained")) is bool(suite["unsupported"]["must_abstain"])

    rate_screens = exact_screens / len(suite["screens"])
    rate_plans = exact_plans / len(suite["screens"])
    points = {
        "cited_single_company_qa": 4 if single_supported else 0,
        "cross_company_screening": 3 * rate_screens,
        "exact_inspectable_filters": 2 * rate_plans,
        "unsupported_abstention": 1 if abstention else 0,
        "saved_history": 1 if len(state["history"]) == len(suite["screens"]) and state["pins"] else 0,
        "provenance_export": 1 if citations_complete else 0,
    }
    return {
        "corpus": suite.get("corpus"),
        "profiles": len(envelopes),
        "questions": 1 + len(suite["screens"]) + 1,
        "single_company": {"organisation_number": spec["organisation_number"], "question": spec["question"], "facts": len(answer["facts"]), "minimum_facts": spec["minimum_facts"], "cited": len(cited), "every_fact_cited": bounded},
        "single_company_supported": single_supported,
        "screen_results": screen_results,
        "unsupported_abstention": abstention,
        "why_abstained": unsupported.get("why_abstained"),
        "saved_work": len(state["history"]) == len(suite["screens"]) and bool(state["pins"]),
        "provenance_export": citations_complete,
        "external_footprint_qa": {
            "definition": "every stated fact carries the source it was published with; a question about the company's own activity is answered from sources outside the register when such sources were found; a claim no profile carries abstains",
            "bounded_by_published_evidence": bounded,
            "activity_question_uses_footprint": activity_probe["passed"],
            "activity_question_test": activity_probe,
        },
        "external_footprint_qa_passed": bool(bounded and activity_probe["passed"] and abstention),
        "points": points,
        "score": round(sum(points.values()), 3),
        "maximum": 12,
        "qualification_passed": bool(single_supported and rate_screens == 1 and rate_plans == 1 and abstention and citations_complete),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--envelopes", required=True)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workspace", help="where the saved working state is written")
    args = parser.parse_args()

    rows = load_rows(Path(args.envelopes))
    suite = json.loads(Path(args.suite).read_text(encoding="utf-8"))
    report = evaluate(rows, suite)
    if args.workspace:
        state = workspace_mod.empty_workspace()
        for screen in suite["screens"]:
            state = workspace_mod.record_screen(state, research.screen_profiles(rows, screen["query"]), pin_organisations=[str(screen["expected_organisation_numbers"][0])])
        workspace_mod.save_workspace(args.workspace, state)
        report["workspace_file"] = args.workspace
        report["workspace_steps"] = len(state["history"])
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"score": report["score"], "points": report["points"], "qualification_passed": report["qualification_passed"], "external_footprint_qa_passed": report["external_footprint_qa_passed"], "single": report["single_company"]["facts"], "screens": [s["exact_membership_and_order"] for s in report["screen_results"]]}, ensure_ascii=False, indent=2))

    # Negative control: the evaluator must be able to say no. A corpus that does not contain the expected
    # companies has to fail, or the score is not measuring anything.
    empty_suite = json.loads(json.dumps(suite))
    empty_suite["screens"] = [dict(s, expected_organisation_numbers=["000000000"]) for s in suite["screens"]]
    strict = evaluate(rows, empty_suite)
    assert strict["score"] < report["score"], (strict["score"], report["score"])
    assert not strict["qualification_passed"], strict["points"]
    print("evaluate_research_kit self-test OK: the same suite scored against a wrong expectation comes out lower and unqualified")
