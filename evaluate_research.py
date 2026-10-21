"""Run the research layer over a real batch and report what it can and cannot answer.

This is my own version of the organisers' `evaluate_research_agent.py`, pointed at my envelopes. Their
suite states which companies a screen should return, and those expectations belong to their corpus, not
mine — so this script checks the parts that do not depend on the corpus: that an answer only contains
facts whose source is carried with it, that a query becomes a plan naming the right fields in the order
they were asked for, that a ranking is applied, and that a field nobody has produces abstention. Where a
number depends on my own batch (how many companies a screen returns) it is reported, not asserted.

Usage: python3 evaluate_research.py --envelopes out/run-1/envelopes.jsonl
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import research

THEIR_SUITES = [
    "companies in Oslo with more than 5 employees and revenue over 1 million top 10 by revenue",
    "top 5 by revenue",
]
THEIR_UNSUPPORTED = "companies in Oslo with positive Glassdoor sentiment"
THEIR_QUESTION = "Who leads this company and what financial facts and locations are available?"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--envelopes", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    envelopes = research.load_envelopes(args.envelopes)
    print(f"{len(envelopes)} envelopes loaded")

    # The single-company question, run against the richest profiles in the batch and against ordinary ones.
    ranked = sorted(envelopes, key=lambda e: -len(research.available_fields(e)))
    qa_rows = []
    for envelope in ranked[:5] + ranked[-3:]:
        answer = research.answer_profile(envelope, THEIR_QUESTION)
        facts = answer["facts"]
        complete = all(f.get("source_url") and f.get("retrieved_at") and f.get("content_sha256") for f in facts)
        qa_rows.append(
            {
                "organisation_number": envelope.get("organisation_number"),
                "name": (research.claims(envelope).get("legal_name") or {}).get("value"),
                "facts": len(facts),
                "fields": answer["stated_fields"],
                "sources_complete": complete,
                "stated_unknowns": answer["not_available"],
            }
        )
    cited = [r for r in qa_rows if r["sources_complete"]]
    over_six = [r for r in qa_rows if r["facts"] >= 6]
    print(f"\nsingle-company questions answered: {len(qa_rows)}")
    print(f"  every fact carried its source: {len(cited)}/{len(qa_rows)}")
    print(f"  at least six cited facts (their bar): {len(over_six)}/{len(qa_rows)}")
    for r in qa_rows[:2]:
        print(f"  example {r['organisation_number']} {r['name']}: {r['facts']} facts over {r['fields']}")
        print(f"    unknowns stated: {r['stated_unknowns']}")

    print()
    for query in THEIR_SUITES:
        plan = research.parse_screen_query(query)
        result = research.screen_profiles(envelopes, query)
        citations = [c for item in result["results"] for c in item["citations"]]
        complete = all(c.get("source_url") and c.get("retrieved_at") and c.get("content_sha256") for c in citations) if citations else None
        print(f"query: {query}")
        print(f"  plan filters: {[f['field'] for f in plan['filters']]} rank: {plan['rank']} limit: {plan['limit']}")
        print(f"  returned: {len(result['results'])} companies, citations complete: {complete}")
        for item in result["results"][:5]:
            values = {c["field"]: c.get("value") for c in item["citations"]}
            print(f"    {item['organisation_number']} {item['name']} {values}")

    skip = research.screen_profiles(envelopes, THEIR_UNSUPPORTED)
    print(f"\nunsupported field query: {THEIR_UNSUPPORTED}")
    print(f"  abstained: {skip['abstained']}  why: {skip.get('why_abstained')}")

    report = {
        "envelopes": len(envelopes),
        "single_company": {"asked": len(qa_rows), "sources_complete": len(cited), "six_or_more_facts": len(over_six)},
        "screens": [
            {
                "query": q,
                "plan_filters": [f["field"] for f in research.parse_screen_query(q)["filters"]],
                "results": len(research.screen_profiles(envelopes, q)["results"]),
            }
            for q in THEIR_SUITES
        ],
        "unsupported_abstention": skip["abstained"] is True,
        "claim_boundary": "Corpus-independent behaviour checked against my own batch; the organisers' expected membership is not reproducible here.",
    }
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {args.output}")


if __name__ == "__main__":
    main()
