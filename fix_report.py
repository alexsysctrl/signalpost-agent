"""What the reviewer's three rules changed, counted on a finished run.

Asked for by the auditor on 2026-10-22: a site must be the company's own and not a parent group's, a social
handle must belong to the company and not a group or an agency, and a news item must be a real dated post.
Each rule is easy to state and easy to claim. This reads the run's own output and reports what each one
actually did, so the answer is a number and not a description.

Usage: python3 fix_report.py --run out/run-1 --output out/run-1/checks/fix-report.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

GROUP_RELATIONS = ("overordnet konsern", "overordnet enhet")
GROUP_SITE_REASON = "a group relation of this company"
UNDATED_NEWS_REASON = "publish date on the publisher's own page"


def _claims(envelope: dict) -> dict[str, dict]:
    return {str(c.get("field")): c for c in envelope.get("claims") or []}


def summarise(run_dir: Path) -> dict:
    envelopes = [json.loads(line) for line in (run_dir / "envelopes.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    observations = [json.loads(line) for line in (run_dir / "observations.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    group_named = 0
    group_site_refused = 0
    undated_news_stated = 0
    website_states: Counter[str] = Counter()
    for env in envelopes:
        claims = _claims(env)
        group = claims.get("group") or {}
        value = group.get("value")
        if isinstance(value, dict) and any(str(r.get("relation")) in GROUP_RELATIONS for r in (value.get("sample") or [])):
            group_named += 1
        website = claims.get("official_website") or {}
        website_states[str(website.get("availability"))] += 1
        if website.get("availability") == "ambiguous" and GROUP_SITE_REASON in str(website.get("reason") or ""):
            group_site_refused += 1
        news_claim = claims.get("news_mentions") or {}
        if news_claim.get("availability") == "not_available" and UNDATED_NEWS_REASON in str(news_claim.get("reason") or ""):
            undated_news_stated += 1

    news = [o for o in observations if o.get("platform") == "news"]
    date_sources = Counter(str(o.get("publish_date_source")) for o in news)
    handles = [o for o in observations if o.get("signal_type") == "profile_handle"]
    return {
        "profiles": len(envelopes),
        "group_membership": {
            "profiles_naming_the_group_they_sit_under": group_named,
            "note": "the register's own group structure, read from the root of its response",
        },
        "group_owned_sites": {
            "websites_refused_because_the_domain_belongs_to_a_group_relation": group_site_refused,
            "website_states": dict(website_states),
        },
        "news_dates": {
            "published_news_findings": len(news),
            "by_date_source": dict(date_sources),
            "profiles_stating_undated_matches": undated_news_stated,
            "rule": "a news finding is published only when the publisher's own page carries the date",
        },
        "social_handles_published": len(handles),
    }


def selftest() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp)
        (run / "envelopes.jsonl").write_text(
            json.dumps(
                {
                    "claims": [
                        {"field": "group", "availability": "available", "value": {"count": 2, "sample": [{"relation": "overordnet konsern", "name": "HOLDING AS"}]}},
                        {"field": "official_website", "availability": "ambiguous", "reason": "example.no is spelled from HOLDING AS, " + GROUP_SITE_REASON},
                        {"field": "news_mentions", "availability": "not_available", "reason": "2 articles matched the company name; none carried a " + UNDATED_NEWS_REASON},
                    ]
                }
            )
            + "\n"
            + json.dumps({"claims": [{"field": "official_website", "availability": "available", "value": "https://other.no/"}]})
            + "\n",
            encoding="utf-8",
        )
        (run / "observations.jsonl").write_text(
            json.dumps({"platform": "news", "signal_type": "public_mention", "publish_date_source": "publisher_page", "organisation_number": "1"})
            + "\n"
            + json.dumps({"platform": "linkedin", "signal_type": "profile_handle", "organisation_number": "1"})
            + "\n",
            encoding="utf-8",
        )
        report = summarise(run)
    assert report["profiles"] == 2, report
    assert report["group_membership"]["profiles_naming_the_group_they_sit_under"] == 1, report
    assert report["group_owned_sites"]["websites_refused_because_the_domain_belongs_to_a_group_relation"] == 1, report
    assert report["news_dates"]["published_news_findings"] == 1, report
    assert report["news_dates"]["by_date_source"] == {"publisher_page": 1}, report
    assert report["news_dates"]["profiles_stating_undated_matches"] == 1, report
    assert report["social_handles_published"] == 1, report
    print(
        "fix_report self-test OK: a group-named site refusal, an undated-news statement and a publisher-dated "
        "finding are each counted once, and a profile without them is not counted"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.run is None:
        selftest()
    else:
        report = summarise(args.run)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
