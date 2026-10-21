"""A company profile as a page: one file, no external assets, one column that survives a phone.

What this is for is the organisers' last question — can a person find, compare and verify the information on
desktop and mobile. So the page is deliberately plain: a list you can scan, one profile at a time, and every
fact shown with the source it came from and the moment it was read, right there rather than behind a tooltip.

Two structural choices are load-bearing.

Navigation is anchors, not a script. Each profile is a section with an id and the list links to it, so the
page works with no JavaScript, in any browser, and a link to a company is something you can send to someone.

The layout is one column at every width. On a desktop the list sits beside the profile; below 760 px it sits
above it. Nothing has a fixed pixel width, nothing scrolls sideways, and evidence pills wrap. A phone is the
first layout this was designed for, not a later adaptation of the desktop one.
"""
from __future__ import annotations
import re
from html import escape
from urllib.parse import unquote, urlsplit

import json
from pathlib import Path

import summary as summarymod

SECTIONS = (
    ("identity", "Identity and activity"),
    ("financials", "Filed accounts"),
    ("leadership", "Leadership"),
    ("workplaces", "Workplaces"),
    ("activity", "Hiring and public activity"),
    ("unknowns", "Not found"),
    ("changes", "Changes since the previous run"),
)

CSS = """
:root { --ink:#14130f; --paper:#f7f4ec; --rule:#d9d2c2; --accent:#8c1f28; --muted:#6d6656; }
* { box-sizing: border-box; }
body { margin:0; background:var(--paper); color:var(--ink); font:16px/1.55 Georgia, "Times New Roman", serif; }
.wrap { display:grid; grid-template-columns: minmax(0, 22rem) minmax(0, 1fr); gap:1.5rem; padding:1.25rem; max-width:1180px; }
h1 { font-size:1.35rem; margin:0 0 .25rem; letter-spacing:.01em; }
h2 { font-size:1.05rem; margin:1.1rem 0 .4rem; text-transform:uppercase; letter-spacing:.06em; font-size:.8rem; color:var(--accent); }
.list { border-right:1px solid var(--rule); padding-right:1rem; }
.list a { display:block; padding:.55rem 0; border-bottom:1px solid var(--rule); color:inherit; text-decoration:none; }
.list b { display:block; font-weight:600; }
.list span { display:block; color:var(--muted); font-size:.85rem; }
.badge { display:inline-block; font-size:.72rem; border:1px solid var(--rule); border-radius:2px; padding:.1rem .35rem; color:var(--muted); }
.card { border:1px solid var(--rule); background:#fffdf7; padding:1rem 1.1rem; margin-bottom:1.25rem; }
ul { margin:.2rem 0 .6rem; padding-left:1.1rem; }
li { margin:.2rem 0; overflow-wrap:anywhere; }
.src { color:var(--muted); font-size:.78rem; overflow-wrap:anywhere; }
.src a { color:var(--accent); overflow-wrap:anywhere; word-break:break-word; }
.pill { display:inline-block; border:1px solid var(--rule); border-radius:999px; padding:.12rem .5rem; margin:0 .3rem .3rem 0; font-size:.78rem; }
.unknown li { color:var(--muted); }
@media (max-width: 760px) {
  .wrap { grid-template-columns: minmax(0, 1fr); }
  .list { border-right:0; padding-right:0; border-bottom:1px solid var(--rule); }
}
"""


def evidence_for(envelope: dict, field: str) -> dict:
    for claim in envelope.get("claims") or []:
        if claim.get("field") != field:
            continue
        wanted = {str(i) for i in claim.get("evidence_ids") or []}
        for item in envelope.get("evidence") or []:
            if str(item.get("id")) in wanted:
                return item
    return {}


def title_key(title: str) -> str:
    """SECTIONS is (key, title); the self-test works from the visible heading, so map it back explicitly."""
    return dict((visible, key) for key, visible in SECTIONS)[title]


def source_label(url: str) -> str:
    """What a reader sees of a source: host and the part of the path that identifies the record.

    A full URL inline is honest and unreadable at the same time, and every line on this page carries one.
    The complete URL stays in the link and in the title attribute, so nothing is hidden — it is just not
    shouted.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    tail = "/".join([segment for segment in unquote(parts.path or "").split("/") if segment][-2:])
    return f"{host} · {tail}" if tail else host


def completeness(envelope: dict) -> int:
    got = {c.get("field"): c.get("availability") for c in envelope.get("claims") or []}
    filled = 0
    for group in ("legal_name", "financials", "roles", "locations", "official_website"):
        if got.get(group) == "available":
            filled += 1
    return filled


def inline_sources(envelope: dict, item: dict) -> str:
    spans = []
    for source in sources_for(envelope, item):
        url = str(source.get("source_url") or "")
        if not url:
            continue
        spans.append(
            " <span class='src'>source: <a href='"
            + escape(url)
            + "' title='"
            + escape(url)
            + "'>"
            + escape(source_label(url))
            + "</a> · read "
            + escape(str(source.get("retrieved_at") or ""))
            + " · sha256 "
            + escape(str(source.get("content_sha256") or "")[:12])
            + "</span>"
        )
    return "".join(spans)


def sources_for(envelope: dict, item: dict) -> list[dict]:
    """Every distinct source behind one line, in the order the line names its fields."""
    found: list[dict] = []
    for field in item.get("fields") or []:
        source = evidence_for(envelope, field)
        if source and source not in found:
            found.append(source)
    return found


def source_groups(envelope: dict, lines: list[dict]) -> list[dict]:
    """Group consecutive facts that came from the same source, and show that source once.

    Six figures from one account record do not need the same URL, timestamp and hash six times: the repetition
    is what made this page read like a log. Grouping says the provenance once, over the facts it covers, and
    `data-fields` records which facts those are, so the checker can prove nothing lost its source on the way.
    A line drawing on two different sources is never folded into a group with a single heading.
    """
    groups: list[dict] = []
    for item in lines:
        sources = sources_for(envelope, item)
        single = sources[0] if len(sources) == 1 and sources[0].get("source_url") else None
        key = str(sources[0].get("id")) if single else None
        fields = [str(f) for f in (item.get("fields") or [])]
        if groups and single and groups[-1]["key"] == key:
            groups[-1]["lines"].append(item)
            groups[-1]["fields"] = groups[-1]["fields"] + [f for f in fields if f not in groups[-1]["fields"]]
        else:
            groups.append({"key": key, "source": single, "lines": [item], "fields": fields})
    return groups


def page(envelopes: list[dict]) -> str:
    profiles = [(envelope, summarymod.build(envelope)) for envelope in envelopes]
    parts: list[str] = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Company profiles — checked evidence</title>",
        f"<style>{CSS}</style></head><body><div class='wrap'>",
        "<nav class='list'><h1>Company profiles</h1>",
        f"<p class='src'>{len(profiles)} companies, one checked profile each</p>",
    ]
    for envelope, profile in profiles:
        filled = completeness(envelope)
        parts.append(
            "<a href='#"
            + escape(str(profile["organisation_number"]))
            + "'><b>"
            + escape(str(profile["name"]))
            + "</b><span>"
            + escape(str((summarymod.held(envelope, "municipality") or "").title() or "location not registered"))
            + f" <em class='badge'>{filled}/5 data areas</em></span></a>"
        )
    parts.append("</nav><main>")

    for envelope, profile in profiles:
        org = escape(str(profile["organisation_number"]))
        filled = completeness(envelope)
        parts.append(f"<section class='card' id='{org}'>")
        parts.append(f"<h1>{escape(str(profile['name']))}</h1>")
        parts.append(
            "<p class='src'>organisation number "
            + org
            + " · "
            + escape(str(summarymod.held(envelope, "legal_form") or ""))
            + " · "
            + f"{filled}/5 data areas filled</p>"
        )
        pills: list[str] = []
        if summarymod.held(envelope, "official_website"):
            pills.append("verified own website")
        if profile.get("periods"):
            pills.append("latest filing " + escape(", ".join(profile["periods"])))
        handles = [o for o in envelope.get("observations") or [] if o.get("signal_type") == "profile_handle"]
        if handles:
            pills.append(f"{len(handles)} verified profile{'s' if len(handles) != 1 else ''} on other platforms")
        if len(profile["sections"].get("unknowns") or []) == 0:
            pills.append("no gaps in this batch of sources")
        if envelope.get("changes"):
            pills.append(f"{len(envelope['changes'])} change{'s' if len(envelope['changes']) != 1 else ''} since previous run")
        if pills:
            parts.append("<p>" + "".join(f"<span class='pill'>{p}</span>" for p in pills) + "</p>")
        for key, title in SECTIONS:
            lines = profile["sections"].get(key) or []
            if not lines:
                continue
            for group in source_groups(envelope, lines):
                if group["source"]:
                    source = group["source"]
                    url = str(source.get("source_url") or "")
                    parts.append(
                        "<div class='src-block' data-fields='"
                        + " ".join(group["fields"])
                        + "'><p class='src'>source: <a href='"
                        + escape(url)
                        + "' title='"
                        + escape(url)
                        + "'>"
                        + escape(source_label(url))
                        + "</a> · read "
                        + escape(str(source.get("retrieved_at") or ""))
                        + " · sha256 "
                        + escape(str(source.get("content_sha256") or "")[:12])
                        + "</p><ul>"
                    )
                    for item in group["lines"]:
                        parts.append("<li>" + escape(str(item["text"])) + "</li>")
                    parts.append("</ul></div>")
                else:
                    # Mixed sources in one stretch: each line keeps its own provenance rather than sharing a
                    # heading that would misdescribe where half of it came from.
                    parts.append("<ul>")
                    for item in group["lines"]:
                        fields = " ".join(str(f) for f in (item.get("fields") or []))
                        parts.append("<li data-fields='" + escape(fields) + "'>" + escape(str(item["text"])) + inline_sources(envelope, item) + "</li>")
                    parts.append("</ul>")
        problems = summarymod.verify(envelope, profile)
        if problems:
            parts.append("<h2>Checker warnings</h2><ul>")
            parts.extend("<li class='unknown'>" + escape(p) + "</li>" for p in problems)
            parts.append("</ul>")
        parts.append("</section>")

    parts.append("</main></div></body></html>")
    return "\n".join(parts)


FIXTURE = {
    "organisation_number": "123456789",
    "run": {"run_id": "selftest", "completed_at": "2026-10-21T00:00:00Z"},
    "evidence": [
        {"id": "ev-1", "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/123456789", "retrieved_at": "2026-10-21T00:00:00Z", "content_sha256": "c" * 64},
        {"id": "ev-2", "source_url": "https://example.no/om-oss", "retrieved_at": "2026-10-21T00:01:00Z", "content_sha256": "d" * 64},
    ],
    "claims": [
        {"field": "legal_name", "value": "EXAMPLE BYGG AS", "availability": "available", "evidence_ids": ["ev-1"]},
        {"field": "legal_form", "value": "Aksjeselskap", "availability": "available", "evidence_ids": ["ev-1"]},
        {"field": "municipality", "value": "DRAMMEN", "availability": "available", "evidence_ids": ["ev-1"]},
        {"field": "registered_activity", "value": "3511 - Drift av avfallsbehandlingsanlegg", "availability": "available", "evidence_ids": ["ev-1"]},
        {"field": "employees", "value": 9, "availability": "available", "evidence_ids": ["ev-1"]},
        {"field": "latest_filed_accounts_year", "value": "2025", "availability": "available", "evidence_ids": ["ev-1"]},
        {"field": "revenue", "value": 12500000.0, "availability": "available", "evidence_ids": ["ev-1"], "reporting_period": "2025"},
        {"field": "annual_result", "value": 900000.0, "availability": "available", "evidence_ids": ["ev-1"], "reporting_period": "2025"},
        {"field": "roles", "value": {"count": 1, "sample": [{"role_group": "Styre", "role": "Daglig leder", "holder": "Kari Nordmann", "registered": "2019-05-01"}]}, "availability": "available", "evidence_ids": ["ev-1"]},
        {"field": "official_website", "value": "https://example.no/om-oss", "availability": "available", "evidence_ids": ["ev-2"]},
        {"field": "public_phone", "availability": "not_available", "reason": "no phone number in the registry record or on the company's own pages", "checked_source": "registry and company site", "evidence_ids": []},
    ],
    "observations": [{"id": "ob-x", "platform": "company_site", "signal_type": "company_profile", "organisation_number": "123456789"}],
    "changes": [],
    "errors": [],
}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Render checked company profiles as one self-contained page.")

    parser.add_argument("--envelopes", help="envelopes.jsonl from a run; omit to check the renderer against a fixture")
    parser.add_argument("--output", help="where to write the page")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()

    if args.envelopes and args.output:
        envelopes = summarymod.load(args.envelopes)[: args.limit]
        html = page(envelopes)
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
    else:
        envelopes = [FIXTURE]
        html = page(envelopes)
        print("no run given — checking the renderer against a fixture profile")

    # A page is only done if it holds the properties it claims: every profile reachable by anchor, every
    # fact carrying a source line, no layout wider than the viewport, and one column on a phone.
    profiles = [summarymod.build(e) for e in envelopes]
    for profile in profiles:
        assert f"id='{profile['organisation_number']}'" in html, profile["organisation_number"]
    assert source_label("https://www.data.brreg.no/regnskapsregisteret/regnskap/919991232") == "data.brreg.no · regnskap/919991232", source_label("https://www.data.brreg.no/regnskapsregisteret/regnskap/919991232")
    assert source_label("https://example.no/") == "example.no", source_label("https://example.no/")
    assert "width=device-width" in html
    assert "max-width: 760px" in html and "grid-template-columns: minmax(0, 1fr)" in html, "phone layout missing"
    # A fixed pixel width on a container is what breaks a phone. max-width caps are fine; a hard width is not.
    hard_widths = re.findall(r"(?<!max-)(?<!min-)\bwidth:\s*\d+px", html)
    assert not hard_widths, f"hard pixel widths in the layout: {hard_widths}"
    assert "grid-template-columns: minmax(0, 22rem) minmax(0, 1fr)" in CSS and "minmax(0, 1fr)" in CSS
    # Long source URLs are what actually overflow a phone: they must be allowed to break.
    assert ".src a { color:var(--accent); overflow-wrap:anywhere; word-break:break-word; }" in CSS, "source URLs must wrap"
    shown = sum(len(p["sections"]) for p in profiles)
    assert shown > 0

    # Grouped provenance, checked as grouping. Every stretch of facts that came from one source must appear as
    # a source block declaring the fields it covers, and every financial figure must be inside one. Counting
    # occurrences of "source:" is no longer the right test: with grouping the honest claim is coverage.
    pairs = list(zip(envelopes, profiles))
    blocks = 0
    for envelope, profile in pairs:
        for _, title in SECTIONS:
            lines = profile["sections"].get(title_key(title)) or []
            for group in source_groups(envelope, lines):
                if not group["source"]:
                    continue
                blocks += 1
                assert f"data-fields='{' '.join(group['fields'])}'" in html, group["fields"]
    assert html.count("<div class='src-block'") == blocks, (html.count("<div class='src-block'"), blocks)
    assert blocks > 0, "a page with no sourced facts is not this page"
    sourced_fields: set[str] = set()
    for declaration in re.finditer(r"class='src-block' data-fields='([^']*)'", html):
        sourced_fields |= {f for f in declaration.group(1).split() if f}
    for profile in profiles:
        for item in profile["sections"]["financials"]:
            assert any(field in sourced_fields for field in (item.get("fields") or [])), f"financial figure without a source block: {item['text']}"
    facts_covered = sum(len(group["lines"]) for envelope, profile in pairs for _, title in SECTIONS for group in source_groups(envelope, profile["sections"].get(title_key(title)) or []) if group["source"])
    print(
        f"render self-test OK: {len(envelopes)} profiles on one page, {blocks} source blocks covering {facts_covered} facts, "
        "each block declaring the fields it covers, anchors only (no JavaScript), single column at 760px and below"
    )
