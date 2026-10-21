#!/usr/bin/env python3
"""Does a search layer actually fix discovery recall? Measured, not assumed.

Take the companies from the last real batch where my free-path discovery (registry field, name-derived
domains, registered mail domain, Wikidata) found nothing, ask a search engine for each one, and run the
same verification on what comes back. A candidate only counts when a fetched page proves the exact
entity at level 1 or 2 — the same bar the rest of the pipeline has to clear.

Usage: python3 measure_search_recall.py --profiles out/run-1/profiles.jsonl
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import bulk_index
import discover
import identity
import searchlayer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()

    rows = [json.loads(line) for line in Path(args.profiles).read_text(encoding="utf-8").splitlines() if line.strip()]
    missing = [r for r in rows if (r.get("evidence", {}).get("website", {}) or {}).get("status") != "available"]
    orgs = [r["organisation_number"] for r in missing][: args.limit]
    print(f"{len(rows)} profiles, {len(missing)} without a verified site; testing {len(orgs)} with the search layer")

    bulk = bulk_index.lookup(set(orgs))
    found = 0
    details = []
    for org in orgs:
        row = bulk.get(org)
        if not row:
            continue
        fields = identity.map_bulk(row)
        name = fields.get("legal_name") or ""
        locality = fields.get("business_municipality") or fields.get("postal_address") or ""
        lead = searchlayer.discover(org, name, locality)
        provider = lead["provider"]
        if provider == "none" or not lead["candidates"]:
            details.append({"org": org, "name": name, "result": "no candidates", "provider": provider})
            print(f"  {org} {name[:30]:32} provider={provider:8} no usable candidates")
            continue
        verdict = discover.verify_site(org, name, lead["candidates"][:5], row, max_fetches=3)
        best = verdict.get("best")
        ok = bool(best and best["level"] in (1, 2))
        found += int(ok)
        details.append(
            {
                "org": org,
                "name": name,
                "provider": provider,
                "candidates": lead["candidates"][:5],
                "result": (f"verified level {best['level']}: {best['final_host']} — {best['proof'][:90]}" if ok else "no candidate proved the entity"),
            }
        )
        status = f"FOUND level {best['level']} at {best['final_host']}" if ok else "no proof"
        print(f"  {org} {name[:30]:32} provider={provider:8} candidates={len(lead['candidates']):2} {status}")

    tested = len([d for d in details if d.get("provider") not in (None, "none")])
    print(f"\nsearch layer recovered {found} of {len(orgs)} companies the free path could not resolve")
    print(f"combined coverage would be {(len(rows) - len(missing) + found)} / {len(rows)} = {(len(rows) - len(missing) + found) / max(1, len(rows)):.1%}")
    Path("out/search-recall.json").write_text(json.dumps({"found": found, "tested": tested, "missing_before": len(missing), "profiles": len(rows), "details": details}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
