# Signalpost agent

A research agent for Norwegian organisations. Given a nine-digit organisation number, it returns one
structured profile: legal identity, filed accounts, leadership, registered workplaces, the company's own
website and social profiles where it can prove they belong to that company, and dated public activity.
Every published fact carries the URL it came from, the time it was read, and a hash of the content that was
read.

It is written for a reader who wants to check the answer, not just read it.

## Run it

```bash
python3 agent.py --orgs organisations.jsonl --out out/run-1 --budget 90
```

`organisations.jsonl` is one organisation number per line (a plain list of numbers also works). The run
writes, in `out/run-1/`:

| file | what it is |
|---|---|
| `envelopes.jsonl` | one terminal envelope per input — the contract output, one line per organisation number asked for |
| `profiles.jsonl` | the same run in the field names the competition's evaluation scripts read |
| `observations.jsonl` | findings about external presence: websites, profile handles, job listings, mentions, ratings |
| `run-report.json` | runtime per company, request count, third-party cost, the rate policy used, and a self-check of the batch contract |
| `snapshots/` | this run's state per company, so a later run can report only what changed |

An organisation number the register does not know still gets an envelope: it states what was checked and what
was not found. Nothing is silently dropped.

## What it reads

Only two things, both free.

- **Brønnøysundregistrene open data** (NLOD 2.0) — the entity register, the accounting register, roles,
  subunits, group structure. Used through the public REST API and the bulk CSV download, which is indexed
  once locally so a batch does not re-download it.
- **Public pages the company publishes itself or that name it** — its own site and the profile links it
  publishes, plus news mentions. Every one is fetched directly and re-checked against the register before
  anything is published under that company's name.

No paid API is used, and no model is used in the research or summary path. The evidence is structured; a
model would be a way to make mistakes about it, not a way to read it.

## What it refuses to do

- **It does not publish a finding about the wrong company.** A page must show the organisation number, or
  match the company's name together with its registered locality or domain. A name-only match is recorded as
  ambiguous and never published as a fact.
- **It does not publish a social profile that is not the company's.** A subsidiary's site linking to its
  parent group's LinkedIn is not the subsidiary's footprint. Handles are only published when they name the
  company or the company is named next to the link.
- **It does not turn a missing fact into a zero.** Absence is recorded as absence, with the sources that were
  checked and why nothing was found.
- **It does not present a group's numbers as a company's.** Where an organisation files both a consolidated
  account and its own, published figures come from its own filing. If the company's own account does not
  carry a line, the group figure is published labelled as consolidated.
- **It does not answer a question it has no evidence for.** Screening and question-answering work only from
  published claims, the filter plan it derived from a question is returned so it can be checked, and a query
  asking for something the batch does not hold abstains.

## Checking the work

- `python3 audit.py --observations out/run-1/observations.jsonl --out out/audit-1` re-derives every published
  finding from the bytes the run kept for it. A run writes each page it hashed into `out/run-1/evidence/`, keyed
  by the SHA-256 its evidence records already carry, so the check runs against exactly what was read when the
  claim was made — with a different parser (registry figures are re-read from the live API, page findings are
  re-matched with `html.parser` rather than the regexes that published them, job links counted again
  independently). The checker then re-asks the live source and records whether it still answers the same way;
  a page that has moved is reported as moved, which is a statement about today, not evidence of a wrong company.
- `python3 check_profile.py --run out/run-1 --page out/profiles.html` reads the rendered summary back and
  rejects any sentence without a claim behind it, any claim shown without evidence, and any fact on the page
  that no source block covers.
- `python3 refresh_report.py --previous out/run-0/snapshots --current out/run-1` reports only material
  changes, and tests that the diff is deterministic and silent when nothing changed.
- Every module carries a self-test and runs on its own: `python3 summary.py`, `python3 research.py`, and so
  on. `RUN.md` lists them.

## Measured

Two batches are published as reports rather than as claims:

- [`docs/SMOKE-TEST.md`](docs/SMOKE-TEST.md) — 100 companies: the batch contract, what came back, what an
  independent re-check measured, and what the batch cost. Its machine-readable twin is
  [`docs/smoke-test-report.json`](docs/smoke-test-report.json), generated from that run's own output.
- [`docs/MEASUREMENTS.md`](docs/MEASUREMENTS.md) — 1,000 companies: the same checks at scale, plus the
  population ceilings and what each kind of information cannot reach.

Every number in both is reproducible with the commands in [`RUN.md`](RUN.md).

**See the output.** [`docs/example-profiles.html`](docs/example-profiles.html) is ten real profiles exactly as
the agent renders them, produced by `render.py` from a run's own envelopes. Nothing in it is written by hand.

## Read the limits

The limits are measured, not assumed, and they are properties of the population. Within the frozen universe of
411,160 eligible organisations, the register itself lists a website for 10.9% of them and an employee count for
14.5%; companies almost never publish a structured rating about themselves. This agent reaches company websites
at roughly twice the rate the registry lists, by deriving candidate domains and proving them. It does not reach
the rest, and its output says which fields were searched and not found instead of leaving that invisible. The
numbers and what each missing family would take are in the measurements document.
