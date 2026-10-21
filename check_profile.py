"""Check a finished run before anyone reads it.

Three questions, answered for every profile in the run:

1. Does every sentence trace back to a claim the run actually published? `summary.verify` does this one and
   is strict about it: an absence statement is only allowed where the run really found nothing.
2. Is anything shown without a source a reader could open — URL, retrieval time, content hash?
3. Are the unknowns present, so absence is stated rather than implied?

It also states the layout properties the page claims, because those are claims too: one column, no hard pixel
widths, source text allowed to break. This script checks the HTML for them and refuses a page that claims a
phone layout it does not have.

Usage: python3 check_profile.py --run out/run-1
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import render as rendermod
import summary as summarymod

REQUIRED_SECTIONS = ("identity", "financials", "leadership", "workplaces", "unknowns")


def check_run(envelopes: list[dict]) -> dict:
    problems: list[str] = []
    no_source: list[str] = []
    missing_sections: list[str] = []
    unknowns_stated = 0
    facts = 0

    for envelope in envelopes:
        org = str(envelope.get("organisation_number"))
        profile = summarymod.build(envelope)
        for problem in summarymod.verify(envelope, profile):
            problems.append(f"{org}: {problem}")
        for name, lines in profile["sections"].items():
            for item in lines:
                facts += 1
                if name in ("unknowns", "changes") or item.get("absent"):
                    # An absence is sourced by the run itself — what was checked is recorded in unknowns.
                    # A change is sourced by the two records it compares, and `summary.verify` already
                    # requires that it exists in the envelope's change list rather than being invented.
                    continue
                sourced = any(rendermod.evidence_for(envelope, f) for f in item.get("fields") or [])
                if not sourced:
                    no_source.append(f"{org}: {name}: {item['text'][:70]}")
        for section in REQUIRED_SECTIONS:
            if section not in profile["sections"]:
                missing_sections.append(f"{org}: section {section} missing")
        if profile["sections"].get("unknowns"):
            unknowns_stated += 1

    return {
        "profiles": len(envelopes),
        "facts_rendered": facts,
        "unsupported_lines": problems,
        "lines_without_a_source": no_source,
        "missing_sections": missing_sections,
        "profiles_stating_their_unknowns": unknowns_stated,
        "passed": not problems and not no_source and not missing_sections,
    }


def check_source_coverage(html: str, envelopes: list[dict]) -> dict:
    """Prove that every fact on the page has its provenance on the page.

    The renderer groups consecutive facts that came from the same source and states that source once, so the
    guarantee is no longer visible as a suffix on every line — it has to be checked where it actually lives,
    in the `data-fields` each block and line declares. A field with an available claim that no block claims
    to cover is a fact printed without a source, which is the one thing this page is not allowed to do.
    """
    missing: list[str] = []
    checked_profiles = 0
    for match in re.finditer(r"<section class='card' id='(\d{9})'>(.*?)(?=<section class='card'|</body>)", html, re.S):
        org, body = match.group(1), match.group(2)
        envelope = next((e for e in envelopes if str(e.get("organisation_number")) == org), None)
        if envelope is None:
            continue
        checked_profiles += 1
        available = {str(c.get("field")) for c in envelope.get("claims") or [] if c.get("availability") == "available"}
        required: set[str] = set()
        for name, lines in summarymod.build(envelope)["sections"].items():
            if name == "unknowns":
                continue
            for item in lines:
                required |= {str(f) for f in (item.get("fields") or []) if str(f) in available}
        covered: set[str] = set()
        for declaration in re.finditer(r"data-fields='([^']*)'", body):
            covered |= {f for f in declaration.group(1).split() if f}
        for field in sorted(required - covered):
            missing.append(f"{org}: {field} is stated on the page with no source block covering it")
    return {"profiles_checked": checked_profiles, "fields_without_a_source_on_the_page": missing, "passed": not missing}


def check_page(html: str, envelopes: list[dict] | None = None) -> dict:
    problems: list[str] = []
    if "width=device-width" not in html:
        problems.append("no viewport meta: a phone would render this at desktop width")
    if "max-width: 760px" not in html or "grid-template-columns: minmax(0, 1fr)" not in html:
        problems.append("no single-column rule at phone width")
    hard = re.findall(r"(?<!max-)(?<!min-)\bwidth:\s*\d+px", html)
    if hard:
        problems.append(f"hard pixel widths would overflow a narrow screen: {hard[:5]}")
    if ".src a {" in html and "overflow-wrap:anywhere" not in html:
        problems.append("source URLs are not allowed to break")
    coverage = check_source_coverage(html, envelopes or [])
    if not coverage["passed"]:
        problems.extend(coverage["fields_without_a_source_on_the_page"][:10])
    return {"page_problems": problems, "source_coverage": coverage, "passed": not problems}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", help="a run directory containing envelopes.jsonl")
    parser.add_argument("--envelopes", help="or the envelopes file directly")
    parser.add_argument("--page", help="and the rendered page to check")
    parser.add_argument("--output", help="write a machine-readable report here")
    args = parser.parse_args()

    if args.envelopes or args.run:
        path = Path(args.envelopes) if args.envelopes else Path(args.run) / "envelopes.jsonl"
        report = check_run(summarymod.load(path))
        page_report = check_page(Path(args.page).read_text(encoding="utf-8"), summarymod.load(path)) if args.page else None
        combined = {"profile_check": report, "page_check": page_report}
        print(json.dumps(combined, ensure_ascii=False, indent=2)[:4000])
        if args.output:
            Path(args.output).write_text(json.dumps(combined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        print("no run given — checking the checker only")

    # Self-test: a clean profile passes, and three ways of being wrong are each caught.
    good = {
        "organisation_number": "123456789", "run": {"run_id": "t"},
        "evidence": [{"id": "e1", "source_url": "https://example.no/", "retrieved_at": "2026-10-21T00:00:00Z", "content_sha256": "d" * 64}],
        "claims": [
            {"field": "legal_name", "value": "GOOD AS", "availability": "available", "evidence_ids": ["e1"]},
            {"field": "financials", "availability": "not_available", "reason": "404", "checked": "accounts register", "evidence_ids": []},
        ],
    }
    assert check_run([good])["passed"], check_run([good])
    assert check_run([good])["profiles_stating_their_unknowns"] == 1
    assert check_run([dict(good, organisation_number="1")])["passed"], "a one-character organisation number is still a profile"

    # The check has to catch a sentence no builder produced either, so add one by hand and see if the
    # reading-back catches it.
    from summary import verify

    injected = summarymod.build(good)
    injected["sections"]["identity"].append(summarymod.line("A long-standing family firm.", ""))
    caught = verify(good, injected)
    assert any("no claim behind it" in c for c in caught), caught
    injected2 = summarymod.build(good)
    injected2["sections"]["identity"].append(summarymod.line("Registered location: OSLO.", "municipality"))
    assert any("municipality" in c for c in verify(good, injected2)), "a stated field the run never found must be caught"

    assert check_page("<html></html>")["passed"] is False
    rendered = rendermod.page([good])
    assert check_page(rendered, [good])["passed"], check_page(rendered, [good])
    # Remove every declared field coverage from the page and ask whether the checker notices. If it does not,
    # the coverage test is decoration.
    stripped = re.sub(r"data-fields='[^']*'", "data-fields=''", rendered)
    caught = check_page(stripped, [good])
    assert not caught["passed"] and any("no source block covering it" in p for p in caught["page_problems"]), caught
    print("check_profile self-test OK: a clean run passes, an uncited sentence is caught, a page without a phone layout fails")
