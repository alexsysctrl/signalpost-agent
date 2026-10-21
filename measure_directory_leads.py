#!/usr/bin/env python3
"""Are directory and aggregator pages useful as *leads*, even though they can never be published?

The 2026-10-21 measurement said a paid search API only moved website discovery from 10/40 to 12/40: the
results are aggregators (rocketreach, leadiq, tracxn, proff, mittanbud) rather than company sites. That
is a different opportunity than "search harder". An aggregator page about a company usually links to the
company's own site. Fetching the aggregator and following its links is a free path the current pipeline
throws away, because directory hosts are filtered out as candidates.

This tests it: search → fetch the directory page → pull external domains off that page → verify them with
the same identity bar everything else has to clear.
"""
from __future__ import annotations

import json
import sys
import re
import urllib.parse
from collections import Counter
from pathlib import Path

import bulk_index
import discover
import fetch
import identity
import searchlayer

HUB_HOSTS = searchlayer.DIRECTORY_HOSTS | {
    "rt.se", "di.no", "voit.no", "tv2.no", "nrk.no", "vg.no", "a-press.com", "cautus.com",
    "wikipedia.org", "gronnhet.com", "epub.no", "unitest.no", "pathmaker.com", "fetchdata.io",
}


def external_links(doc) -> list[str]:
    """Domains this page links to that are not its own site and not another aggregator."""
    own = discover.registrable_domain(doc.url)
    out: list[str] = []
    for href in re.findall(r'href=["\'](https?://[^"\'\s]+)', doc.text()):
        host = urllib.parse.urlsplit(href).netloc.lower().removeprefix("www.")
        registrable = discover.registrable_domain(href)
        if not registrable or registrable == own or registrable in HUB_HOSTS:
            continue
        if registrable not in out:
            out.append(registrable)
    return out


def main() -> None:
    profiles_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("out/run-1/profiles.jsonl")
    rows = [json.loads(line) for line in profiles_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    missing = [r for r in rows if (r.get("evidence", {}).get("website", {}) or {}).get("status") != "available"]
    orgs = [r["organisation_number"] for r in missing][:12]
    bulk = bulk_index.lookup(set(orgs))
    resolved = 0
    for org in orgs:
        row = bulk.get(org)
        if not row:
            continue
        fields = identity.map_bulk(row)
        name = fields.get("legal_name") or ""
        locality = fields.get("business_municipality") or fields.get("postal_address") or ""
        results, provider = searchlayer.search(searchlayer.query_for(org, name, locality))
        # Any result page can be a lead page. The point of the test is whether following the links on a
        # page somebody else wrote gets me to the company's own domain — so I take the top results as
        # they come, directories and data brokers included, and keep the company's own domain out of the
        # published output as always.
        hubs = [r["url"] for r in results][:3]
        leads: list[str] = []
        for hub_url in hubs:
            doc = fetch.get(hub_url, timeout=15, max_bytes=400_000)
            if doc is None or doc.status != 200:
                continue
            leads += [d for d in external_links(doc) if d not in leads]
        if not leads:
            print(f"  {org} {name[:30]:32} hubs={len(hubs)} no outbound company domains")
            continue
        verdict = discover.verify_site(org, name, leads[:4], row, max_fetches=3)
        best = verdict.get("best")
        ok = bool(best and best["level"] in (1, 2))
        resolved += int(ok)
        print(f"  {org} {name[:30]:32} hubs={len(hubs)} leads={len(leads):2} {'FOUND ' + best['final_host'] if ok else 'no proof'}")
    print(f"\ndirectory-lead path resolved {resolved} of {len(orgs)} companies the direct path could not")


if __name__ == "__main__":
    main()
