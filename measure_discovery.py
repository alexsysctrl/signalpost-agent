"""Measuring website discovery: precision and recall, on ground truth the registry supplies.

Two labelled populations, because they answer different questions.

A. Companies whose registry row lists a website. Brreg's own field is authoritative-ish ground truth.
   Here the test is: does discovery republish that domain, publish a different one, or miss?
   A different domain is not automatically wrong — companies run sites they never registered — so every
   such case is printed for a human to read, and only the org-number proof counts as independent.

B. Companies with no registry website (measured: 89% of the eligible universe). No ground truth exists.
   Here the honest measure is how many candidates reach proof level 1 — the page prints our exact
   organisation number, which is not a guess about who the site belongs to.

Publication policy follows the competition gate (precision 99.5%, recall 70%): level 1 and level 2
(number on page, or legal name plus registered locality) may be published; level 3 (name alone) is
recorded as ambiguous, because two companies can share a brand.

Run: python3 measure_discovery.py [sample_size]
"""
from __future__ import annotations

import sys

import batch
import discover
import identity


def main(n: int = 300) -> None:
    rows = batch.select_batch(n)
    orgs = {r["organisation_number"] for r in rows}
    idx = identity.load_bulk(orgs)
    labelled, unlabelled = [], []
    for r in rows:
        row = idx.get(r["organisation_number"])
        if not row:
            continue
        fields = identity.map_bulk(row)
        site = (row.get("hjemmeside") or "").strip()
        (labelled if site else unlabelled).append((r["organisation_number"], fields, site, row))

    print(f"sampled {n}: registry-listed websites {len(labelled)}, none {len(unlabelled)}")

    exact = diff = miss = 0
    for org, fields, site, row in labelled:
        want = discover.registrable_domain(discover.normalise_host("https://" + site))
        res = discover.verify_site(org, fields["legal_name"], discover.candidates(fields["legal_name"]), row)
        best = res.get("best")
        if best and best["level"] in (1, 2):
            got = discover.registrable_domain(best["final_host"])
            if got == want:
                exact += 1
            else:
                diff += 1
                print(f"  DIFF L{best['level']} {org} {fields['legal_name'][:28]:30} registry={want:28} got={got}  [{best['proof']}]")
        else:
            miss += 1
            note = f"best L{best['level']} {best['final_host']} [{best['proof']}]" if best else "no candidate resolved"
            print(f"  MISS      {org} {fields['legal_name'][:28]:30} want={want:28} {note}")

    verified = ambiguous = unresolved = 0
    shown = 0
    for org, fields, _, row in unlabelled:
        res = discover.verify_site(org, fields["legal_name"], discover.candidates(fields["legal_name"]), row)
        best = res.get("best")
        if best and best["level"] in (1, 2):
            verified += 1
            if shown < 6:
                shown += 1
                print(f"  +        {org} {fields['legal_name'][:28]:30} found={best['final_host']:28} L{best['level']} [{best['proof'][:70]}]")
        elif best and best["level"] == 3:
            ambiguous += 1
        else:
            unresolved += 1

    total = len(labelled)
    print("\n--- against registry-listed sites (labelled) ---")
    if total:
        print(f"  republished the same domain : {exact} ({exact / total:.0%})")
        print(f"  different domain reached    : {diff} ({diff / total:.0%})  <- printed above for review")
        print(f"  nothing reached             : {miss} ({miss / total:.0%})")
    print("--- where the registry has no website ---")
    print(f"  proven by the org number or name+locality : {verified}")
    print(f"  name only (recorded, not published)       : {ambiguous}")
    print(f"  unresolved                                : {unresolved}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 300)
