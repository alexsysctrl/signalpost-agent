# Measurements

What this agent was run on, what it returned, how the results were checked, and what it does not reach.
Every number here comes from a run that happened, and the command that produces it is stated.

## The batch

1,000 organisation numbers drawn from the frozen eligible universe the competition publishes — 411,160 active
Norwegian legal entities whose latest submitted annual accounts are for 2025.

```bash
python3 agent.py --count 1000 --out out/run-1 --workers 6 --budget 90
./verify-run.sh out/run-1
```

Every input produced exactly one terminal envelope. Two of the 1,000 numbers are not in the frozen bulk
snapshot the registry publishes; both exist in the live register and were profiled from it, and where a number
is in neither, the envelope records that, with the sources that were checked.

## What a profile contains

| | Share of the 1,000 |
|---|---|
| Claims per profile | 38 (median), each with its own evidence record |
| Legal identity | 1,000 of 1,000 |
| Registered activity | 998 |
| Filed annual accounts | 99.7% |
| Registered role holders | 99.7% |
| Registered workplaces (subunits) | 77.6% |
| A verified company website | 20.6% |

Figures come from the accounts filed under that organisation number. Where a company also files consolidated
group accounts, the group figures are published only if the company's own filing does not carry that line, and
they are labelled as consolidated group figures.

## What was found in sources outside the register

1,603 external findings were produced; the competition's own acceptance rules accepted 1,601 and rejected 2
(both news mentions that could not establish the exact legal entity). Rejection is recorded rather than
quietly dropped.

| Finding | Companies | Observations |
|---|---|---|
| Own website, proven to belong to that company | 206 | 206 |
| — proven by the organisation number printed on the page | 38 | |
| — proven by registered name with locality, or by a domain the company's own records point at | 168 | |
| Found on two or more platforms (own site plus at least one profile) | 211 | |
| Profile handles published | 100 | 223 — Facebook 98, Instagram 58, LinkedIn 48, X 8, YouTube 6, TikTok 5 |
| Registered employee counts or workforce signals | 151 | 144 workforce snapshots |
| Job listings on the company's own site | 15 | 15 |
| Dated public mentions in news | 9 | 12 |
| Ratings a company publishes about itself | 3 | 4 |

A name-only match is recorded as `ambiguous` and is never published as a fact: 97 of the 1,000 had a
candidate site that could not be tied to the company, and those are reported as unproven rather than found.

## Correctness, checked by a second path

400 published findings were sampled across companies and signal types and re-checked by code that does not
share the implementation that produced them: registry figures re-read from the live API, page findings
re-fetched and re-matched independently, and job findings re-counted with a different HTML parser than the one
that made the claim.

| Result | Value |
|---|---|
| Findings published under the wrong company | **0** |
| Entity precision | **1.000** |
| Metric precision | **0.9925** (3 of 400) |

All three disagreements are explained rather than averaged away:

- Two news mentions whose quoted passage is no longer on the live page. The evidence recorded at the time —
  URL, retrieval timestamp, content hash — is intact; the publisher changed the page. Reported as not
  re-confirmable rather than as correct.
- One careers page that now carries a single job link where the run counted two. The company is still the
  right company; the count is the thing that moved.

Separately, every rendered profile was read back against the claims it says it came from: 22,937 facts across
1,000 profiles, 0 sentences without a claim behind them, 0 facts presented without provenance, 1,000 of 1,000
profiles stating what was not found and what was checked.

## What it costs

For the 1,000-company batch, 6 workers, a 90-second wall-clock budget per company:

- 2,244 seconds of wall clock; median 8.8 seconds per company, 95th percentile 37.6 seconds
- 10,159 HTTP requests, of which 74 were served from the run's own cache and 157 avoided because the host was
  already known to be unreachable
- **$0.00** to third parties: no paid API is used, and no model is used to read or summarise the evidence

## What it does not reach

These are properties of the population, not settings to tune.

- **Websites.** The register lists a website for 10.9% of the eligible universe. This agent reaches 20.6%,
  roughly double, by deriving candidate domains from the company's own name and its registered email domain and
  then proving each candidate. The remaining four fifths of small entities appear to have no website at all.
  Third-party search was measured on 30 companies whose site the free path could not find: a commercial search
  API recovered 2, a self-hosted general search engine recovered 1. Search results for this population point at
  directories, not at companies, so the default path does not use search.
- **Employee counts.** The register supplies a number for 14.5% of the universe; the agent reaches 15.1% by
  including registered subunits. Reading subunit counts separately adds no additional companies.
- **Reviews and ratings.** 3 companies in 1,000. The only permitted source is what a company publishes about itself, and
  Norwegian companies almost never publish a structured self-rating. This is reported as 0.3%, not as a
  capability.
- **Hiring.** 15 companies in 1,000 list two or more openings on their own site. A national vacancy feed was
  tested against this batch and matched none of them, because the listings most Norwegian employers use are
  excluded from its interface.
- **Sentiment.** Not attempted. A defensible sentiment claim needs several hundred independently labelled
  Norwegian company texts; nothing with usable rights was available, so no sentiment label is published.
- **Time.** This is a current-state agent. Each run is a snapshot; a later run reports the fields that actually
  changed. Replaying 1,000 companies against their own snapshots from an hour earlier produced 5 field-level
  differences across 4 companies: one domain had moved to a for-sale landing page, one company's site had become
  unreachable, and three came from two inputs the earlier version of the agent had not profiled. Replaying a
  batch where nothing had changed reported nothing.
