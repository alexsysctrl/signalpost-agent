# Submission

Entry for the Signalpost competition. Submitted by Alex Sys, alex@sqopa.com.

| | |
|---|---|
| Agent name | `sqopa-signalpost` (the crawler user agent and the run report both carry this name) |
| Repository | https://github.com/alexsysctrl/signalpost-agent |
| Versions submitted | `v1` and `v2`, both tagged in this repository; the commit hash for the version being scored is given in the submission email |
| Contact for results | alex@sqopa.com |

## One run command

```bash
python3 agent.py --orgs <companies.jsonl> --out out/official --workers 6 --budget 90
```

Setup before it, both documented in [`RUN.md`](RUN.md):

```bash
curl -L -o brreg-enheter.csv.gz https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv
python3 bulk_index.py
```

That downloads the public Brønnøysundregistrene bulk register (155 MB gzipped) and builds a local index over it
in about two minutes. The agent runs without it — it falls back to the live register API — but it finds fewer
company websites that way, and the numbers below assume the bulk register is present.

Environment: Python 3.12 or newer, standard library only. There are no dependencies to install, no API keys, no
server-side secrets. `release_check.py` proves the import claim as part of the self-test loop.

## What was run locally

- **100 companies** — the required smoke test: [`docs/SMOKE-TEST.md`](docs/SMOKE-TEST.md), with the
  machine-readable version at [`docs/smoke-test-report.json`](docs/smoke-test-report.json), produced from the
  run's own output by `smoke_report.py`.
- **1,000 companies** — the same checks at scale: [`docs/MEASUREMENTS.md`](docs/MEASUREMENTS.md).
- [`docs/example-profiles.html`](docs/example-profiles.html) shows ten real profiles exactly as the agent renders
  them, generated from a run's own envelopes.

## Models, APIs, licences

No model is used to read, decide, or summarise anything. Profiles and summaries are built from the structured
claims, so a wrong sentence has to correspond to a wrong claim, which is something a reviewer can check. The run
report states this as `models_used: []`.

No paid API is used, and no search-engine result pages are scraped. Sources:

| Source | Rights |
|---|---|
| Brønnøysundregistrene — Enhetsregisteret and Regnskapsregisteret APIs, and the bulk CSV download | Norwegian public open data (NLOD 2.0); each claim records which file or request it came from |
| Companies' own public pages | read as an identified crawler, `Mozilla/5.0 (compatible; SignalpostResearchAgent/1.0; +mailto:alex@sqopa.com)` |
| Dated news mentions | publisher pages, fetched directly; each finding carries the publisher URL, the retrieval time, a content hash, and the quoted span |

Every published finding declares an acquisition mode (`official_api` or `permitted_public_page`) and a rights
status, and `connector_report.py` checks that every one of them passes and that the rate policy is stated in the
run report. Request pacing: 0.05 s minimum gap to the registry, 0.20 s elsewhere, 0.30 s to news, 0.35 s to
LinkedIn, enforced per host across concurrent workers; 8 s for a candidate-domain probe, 15–20 s for a page or
registry read, one 4 s retry; 600 KB per page maximum.

## Expected cost per official batch (1,000–1,100 companies)

- **$0.00** to third parties.
- Requests: about 10,200–11,300.
- Wall clock: 39 to 55 minutes measured for 1,000 companies with 6 workers across four batches of the same
  companies (median 8.9–9.4 s per company, 95th percentile 41–45 s, against a 90-second budget per company). The
  request counts varied by 0.1% between those runs and the wall clock by 40%: the difference is upstream response
  time, not work. With 1,100 companies expect the same shape at the same worker count; wall clock scales with
  workers, while per-host pressure stays bounded by the gaps above.
- Disk: the run writes its outputs plus an evidence archive — measured 6,768 pages, 123 MB for 1,000 companies.
- Memory: about 60 MB resident during a batch (measured on a running batch).

## What this entry is careful about

- **Absence is written as absence.** `not_available`, `ambiguous`, `blocked`, `not_applicable` and `failed` are
  recorded with what was checked. Nothing is turned into zero.
- **A finding is never published under an uncertain company.** A website is published only when the page carries
  the organisation number, or the registered name with the registered locality, or a domain the company's own
  registry record points at. A name-only match is reported as unproven. Only a company's own profile counts as
  its footprint — a person's profile link found on a page is not published as the company's.
- **Financial figures are the entity's own accounts.** Consolidated group accounts are published only when the
  company's own filing lacks that line, and they are labelled as consolidated group figures.
- **A trading name is published only when it says something the legal name does not.** The register records a name
  for each of a company's own subunits, and that is where a public brand is stated officially. Care-of lines
  (`TO KANTEN C/O RUNE BIRKELAND`), responsible-person annotations (`SAREPTA AS V/ ADV. TOM STAVNES`) and branch
  labels naming a town (`… AVD STAVANGER`) are not brands and are not published. This was decided by reading every
  published example, not by sampling one: 34 candidates became 27.
- **Claims are stored against the bytes they were read from.** Every evidence record carries a content hash and a
  retrieval time, and the run writes the page it hashed. Sources on the open web change — measured, 38% of
  re-checked live sources had changed or stopped answering within about an hour — so a claim is verifiable
  against what was actually read, and a later change is reported as a change rather than mistaken for an error.
- **Repetition is expected, not hidden.** `--previous` replays a batch against its own snapshots and reports only
  field-level changes; re-deriving the same diff twice gives the same answer, and a snapshot compared with itself
  reports nothing. `--resume` re-emits a completed run byte-for-byte without a single request.

## Limits, stated plainly

The population sets the ceiling, not the implementation. Within the frozen universe the register lists a website
for 10.9% of organisations and an employee count for 14.5%; this agent reaches websites at roughly double the
listed rate and employee counts at the register's own rate. Company self-published ratings are close to absent in
Norway (3 companies in 1,000 measured). Hiring signals are sparse (27 companies in 1,000 carry two or more
job links on their own site; a national vacancy feed matched none of them). Dated activity is sparser still (4 of
the 202 company sites a run kept publish machine-readable dates). Sentiment is not attempted, because
no Norwegian company-text dataset with usable rights and independent labels was available — so no sentiment
claim is published rather than a weak one.
