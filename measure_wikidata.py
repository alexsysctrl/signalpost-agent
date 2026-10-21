"""How much of this batch does Wikidata already describe, and what would it add?

The entity register's number is a Wikidata property (P2333), so the join is exact: no name matching, no
ambiguity. That makes it worth measuring before it is worth building. What is counted here is the marginal
gain — a website Wikidata lists that my own discovery did not find — because that is the only kind of
coverage a shared union rewards.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (compatible; SignalpostResearchAgent/1.0; +mailto:alex@sqopa.com)"
ENDPOINT = "https://query.wikidata.org/sparql"

QUERY = """
SELECT ?item ?org ?website ?facebook ?instagram ?linkedin ?youtube ?wikipedia WHERE {
  VALUES ?org { %s }
  ?item wdt:P2333 ?org.
  OPTIONAL { ?item wdt:P856 ?website }
  OPTIONAL { ?item wdt:P2013 ?facebook }
  OPTIONAL { ?item wdt:P2003 ?instagram }
  OPTIONAL { ?item wdt:P4852 ?linkedin }
  OPTIONAL { ?item wdt:P4004 ?youtube }
  OPTIONAL { ?article schema:about ?item; schema:isPartOf <https://no.wikipedia.org/>; schema:name ?wikipedia }
}
"""


def ask(orgs: list[str]) -> list[dict]:
    values = " ".join(f'"{o}"' for o in orgs)
    query = QUERY % values
    data = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
    request = urllib.request.Request(ENDPOINT, data=data, method="POST", headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = []
    for binding in payload.get("head", {}).get("vars") and payload["results"]["bindings"] or []:
        row = {}
        for key, value in binding.items():
            row[key] = value.get("value")
        rows.append(row)
    return rows


if __name__ == "__main__":
    run = sys.argv[1] if len(sys.argv) > 1 else "out/run-1"
    envelopes_path = Path(run, "envelopes.jsonl")
    mine = {}
    for line in envelopes_path.open():
        envelope = json.loads(line)
        for claim in envelope["claims"]:
            if claim.get("field") == "official_website" and claim.get("availability") == "available":
                mine[str(envelope["organisation_number"])] = str(claim.get("value") or "").lower()
    found = [str(json.loads(line)["organisation_number"]) for line in Path(run, "observations.jsonl").open() if json.loads(line).get("signal_type") == "profile_handle"]
    rows = ask(orgs)
    by_org: dict[str, dict] = {}
    for row in rows:
        by_org.setdefault(str(row.get("org")), []).append(row)
    entities = len(by_org)
    with_site = sum(1 for rows_for_org in by_org.values() if any(r.get("website") for r in rows_for_org))
    added_site = 0
    added_social = 0
    examples = []
    for org, rows_for_org in by_org.items():
        site = next((r.get("website") for r in rows_for_org if r.get("website")), None)
        if site and org not in mine:
            added_site += 1
            if len(examples) < 6:
                examples.append((org, site))
        social = [r.get(key) for r in rows_for_org for key in ("facebook", "instagram", "linkedin", "youtube") if r.get(key)]
        if social and org not in found:
            added_social += 1
    print(f"batch: {len(orgs)} organisation numbers")
    print(f"described in Wikidata (joined by exact organisation number): {entities}")
    print(f"  with an official website listed: {with_site}")
    print(f"  a website my agent did not find: {added_site}")
    print(f"  a social account my agent did not publish: {added_social}")
    for org, site in examples:
        print(f"    {org} -> {site}")
    # Self-test: the join must be exact and the query must be honest about an entity that is not there.
    probe = ask(["976605713", "123456789"])
    kitron = next((r for r in probe if r.get("org") == "976605713"), None)
    assert kitron and "wikidata.org" in str(kitron.get("item")), "KITRON ASA has a Wikidata entity and the join must find it"
    assert not any(r.get("org") == "123456789" for r in probe), "a number with no entity must return nothing, not a near match"
    print("measure_wikidata self-test OK: exact join confirmed, an unknown number returns no row")
