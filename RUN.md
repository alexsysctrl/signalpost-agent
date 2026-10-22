# Company research agent — how to run it

An agent that takes a Norwegian organisation number and returns one company profile: registered identity,
latest filed accounts, leadership and workplaces, the company's own website with the proof that it belongs
to that company, its public profiles on other platforms, dated public activity, and an explicit statement
of whatever could not be found. Every published fact carries the source it came from, the time it was read
and a hash of the bytes it was read from.

## Setup

Python 3.12 or newer. Standard library only — no packages to install, no API keys, no paid services.

One file is needed next to this repository, because reading 1.4 million registry rows over the network on
every run is wasteful: the registry's own bulk download, kept as `brreg-enheter.csv.gz` beside the code.

```bash
curl -L -o brreg-enheter.csv.gz https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv
python3 bulk_index.py        # builds a local index over it, once; --rebuild to rebuild
```

The index records the source file's SHA-256, and every claim drawn from the bulk snapshot cites that hash,
so a claim can be traced to the exact file version it came from. Without the index the agent streams the
CSV directly — slower, same data.

Optional extras, neither required: a commercial web-search provider key in `BRAVE_API_KEY` / `TAVILY_API_KEY`
(or a JSON file named by `SIGNALPOST_KEYS`), or a self-hosted SearXNG through `SEARXNG_URL`. On a measured
comparison of 30 companies whose site the free path could not find, a commercial provider recovered 2 and
SearXNG recovered 1, which is why the default path uses neither and no default behaviour depends on either.

## Run

```bash
python3 agent.py --organisations companies.jsonl --out out/run-$(date -u +%Y%m%dT%H%M%SZ) --workers 6 --budget 90
```

`companies.jsonl` is one JSON object per line with an `organisation_number` field, or a plain list of
nine-digit numbers. Every input produces exactly one terminal envelope, including companies whose sources
are missing or blocked.

```bash
python3 agent.py --organisations companies.jsonl --out out/run-2 --previous out/run-1/snapshots
```

`--previous` points at the snapshots a run kept. Each profile is then compared field by field with the
earlier one and real differences are written into the envelope's `changes` list: which field, what it was,
what it is now, and where the new value came from. Re-running with no change in the sources produces an
empty `changes` list, and no earlier run's snapshots are ever overwritten.

## What a run writes

| File | Contents |
|---|---|
| `envelopes.jsonl` | one terminal envelope per input, in input order |
| `observations.jsonl` | external findings, each with source, retrieval time, content hash, rights note and identity proof |
| `profiles.jsonl` | the same profiles in a flat form for screening and comparison |
| `snapshots/` | this run's envelopes, one file per company, for a later run to diff against |
| `run-report.json` | wall clock, requests per company, request total, third-party cost, source hosts, website outcome counts |

## Sources and rights

| Source | What it is used for | Licence / basis |
|---|---|---|
| `data.brreg.no` entity, roles, subunits, group structure | legal identity, leadership, registered workplaces, employee counts | NLOD 2.0, official registry |
| `data.brreg.no` bulk download (`enheter/lastned/csv`) | the frozen identity snapshot every bulk claim is anchored to | NLOD 2.0 |
| `data.brreg.no/regnskapsregisteret` | latest filed accounts and the list of filed years | NLOD 2.0 |
| Company websites and their own pages | verified website, outbound links to the company's profiles on other platforms, job listings and self-published ratings the company marks up itself | permitted public page, quoted as evidence only |
| Wikidata | entities that state a Brønnøysund organisation number, used as an exact join for a website or profile handle | CC0 |
| Bing and Google News RSS, then the publisher's own page | dated public mentions | the publisher's own public page; the RSS is used only to find it |

No source is scraped beyond what its own public pages are offered for. Where a platform restricts automated
collection (LinkedIn, Meta, Indeed), this agent only reads a handle when the company itself links to it from
its own site.

## Cost, measured

Measured on 1,000 companies drawn from the frozen universe (2026-10-21, 6 workers, a 90-second wall-clock
budget per company):

- 38 minutes of wall clock end to end, a median of 9.2 seconds per company;
- 10,140 HTTP requests in total for the batch;
- third-party cost **$0.00**: no paid API is used.

Retrying unreachable domains is the one setting that trades coverage against time, and it was measured on
the same 148 companies four ways before being decided:

| Candidate-domain behaviour | Companies with a verified website | Per-company p95 |
|---|---|---|
| Unbounded retries | 32 / 148 | 215 s |
| One attempt, short timeout, no retries | 22 / 148 | 32 s |
| One attempt plus one short retry (shipped) | 26 / 148 | 50 s |

The shipped behaviour is the third: a batch that does not finish is worth nothing, and the tail was four
times the median. Removing it cost six verified websites out of 148, and that is the price, stated.

## What it refuses to do

- It does not publish a website it cannot tie to the company. A domain that only matches the company's name
  is recorded as `ambiguous`, with the match stated, and is not counted as found.
- It does not turn absence into zero. A company with no filed accounts, no registered employee count and no
  site gets `not_available` with the reason and the sources that were checked.
- It does not publish a social profile handle unless the handle names the company or the company is named
  next to the link. A subsidiary's page linking to its parent group's profile is not the subsidiary's profile.
- It does not answer a question about data it does not hold. `research.py` returns an explicit abstention
  when a query asks for a field no profile carries.

## Verifying a run

One command runs the four checks that belong to a run:

```bash
./verify-run.sh out/run-1
```

It re-derives published findings through different code paths, runs the competition's own
external-footprint evaluator over them, checks the rights and rate policy of every finding, and reads every
rendered profile back against the claims it says it came from. Its outputs land in `out/run-1/checks/`.

## The 100-company smoke test

The competition asks every entry to have run its agent on 100 companies and to publish that result. It is a
short run and one command chain:

```bash
python3 agent.py --count 100 --out out/smoke-1 --workers 6 --budget 90
./verify-run.sh out/smoke-1
python3 smoke_report.py --run out/smoke-1 --output docs/smoke-test-report.json
```

`smoke_report.py` collects what the run already wrote — the batch report, the independent re-check, the
competition's evaluator output, the rights check and the profile read-back — into one file, so the published
artifact is the run's own output rather than a description of it. `docs/SMOKE-TEST.md` is the same thing in
prose.

## Self-tests

Every module carries its own self-test at the bottom of the file and can be run directly:

```bash
for m in fetch identity claims external news official discover refresh research workspace bulk_index searchlayer summary render check_profile refresh_report connector_report ux_report smoke_report audit release_check; do python3 $m.py || break; done

# then, over a real run:
python3 agent.py --orgs orgs.jsonl --out out/run-1 --budget 90            # batch (keeps evidence bytes in out/run-1/evidence)
python3 audit.py --observations out/run-1/observations.jsonl --out out/audit-1 --limit 400
python3 evaluate_research_kit.py --envelopes out/run-1/envelopes.jsonl --output out/research-report.json
python3 refresh_report.py --previous out/run-0/snapshots --current out/run-1 --rerun out/run-1b --output out/refresh-report.json
python3 render.py --envelopes out/run-1/envelopes.jsonl --output out/profiles.html
python3 check_profile.py --run out/run-1 --page out/profiles.html --output out/profile-check.json
python3 ux_report.py --envelopes out/run-1/envelopes.jsonl --page out/profiles.html --observations out/run-1/observations.jsonl --output out/ux-report.json
```

Each of those is a check on something different: the audit re-derives published findings from the evidence bytes
the run kept, through different code paths, and reports separately whether each source still answers the same
way on the live web, `check_profile.py` reads the rendered summary back against the claims it says it came
from, `refresh_report.py` proves the diff behaves as a diff (deterministic, silent on an unchanged state,
identical across two live runs), and `ux_report.py` scores the page against a checklist written in that file.

`release_check.py` is the last one in that loop on purpose: it reads the files git would publish, fails
if any of them carry a private network address, a scratch directory from an earlier run, a decision number
from a private log, or notes-to-self phrasing. A released repository should read like a product, not like
someone's working notes, and that is a checkable property rather than an intention.
