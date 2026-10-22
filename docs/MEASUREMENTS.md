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

Every input produced exactly one terminal envelope. Two numbers in this batch are not in the frozen bulk
snapshot the register publishes; both exist in the live register and were profiled from it. Where a number is in
neither, the envelope says so and lists the sources that were checked.

## What a profile contains

| | Share of the 1,000 |
|---|---|
| Claims per profile | 38 (median), each with its own evidence record |
| Legal identity | 1,000 of 1,000 |
| Registered activity | 998 |
| Filed annual accounts | 99.7% |
| Registered role holders | 99.7% |
| Registered workplaces (subunits) | 77.6% |
| A verified company website | 20.1% |

Figures come from the accounts filed under that organisation number. Where a company also files consolidated
group accounts, the group figures are published only if the company's own filing does not carry that line, and
they are labelled as consolidated group figures.

## What was found in sources outside the register

1,593 external findings were produced; the competition's own acceptance rules accepted 1,591 and refused 2 (both
news mentions that could not establish the exact legal entity). Refusal is recorded rather than quietly dropped.

| Finding | Companies | Observations |
|---|---|---|
| Own website, proven to belong to that company | 201 | 201 |
| — proven by the organisation number printed on the page | 37 | |
| — proven by registered name with locality, or by a domain the company's own records point at | 164 | |
| A plausible website that could not be tied to the company | 100 | reported as `ambiguous`, never published |
| Found on two or more platforms (own site plus at least one profile) | 206 | |
| Profile handles published | 97 | 217 — Facebook 97, Instagram 57, LinkedIn 47, X 7, TikTok 5, YouTube 4 |
| Registered employee counts or workforce signals | 150 | 144 workforce snapshots |
| Job listings on the company's own site | 14 | 14 |
| Dated public mentions in news | 10 | 14 |
| Ratings a company publishes about itself | 3 | 4 |

Only the company's own profile counts as its footprint. A person's profile link found on a page was published
until it was measured: on a 100-company test, four of the five findings that failed to re-confirm were people
links, which describe a person rather than the company and rotate on the page. Publishing company profiles only
cost 2 of 48 LinkedIn observations in this batch and raised measured precision by 2.5 points.

A name-only match is never published as a fact: 100 candidates in this batch resolved to a real site that could
not be tied to the company, and those are reported as unproven.

## Correctness, checked by a second path

400 published findings were sampled across companies and signal types and re-checked by code that does not share
the implementation that produced them: registry figures re-read from the live API, page findings re-derived from
the bytes the run kept for them (every evidence record carries a SHA-256, and a run writes the page it hashed
into `out/run-1/evidence/`), and job findings re-counted with a different HTML parser than the one that made the
claim.

| Result | Value |
|---|---|
| Findings published under the wrong company | **0** |
| Entity precision | **1.000** |
| Metric precision | **0.9925** (3 of 400) |

All three disagreements are explained rather than averaged away:

- Two news mentions whose quoted passage is no longer on the live article. The evidence recorded when it was read
  — URL, retrieval timestamp, content hash — is intact; the publisher changed the page.
- One careers page that now carries a single job link where the run counted two. The company is still the right
  company; the count is the thing that moved.

Separately, every rendered profile was read back against the claims it says it came from: 22,936 facts across
1,000 profiles, 0 sentences without a claim behind them, 0 facts presented without provenance, 1,000 of 1,000
profiles stating what was not found and what was checked.

## Sources move. That is measured too.

Re-checking is not the same claim as re-fetching. Of the 99 sampled findings that were re-derived from the bytes
the run kept, the live source was then asked again, a few minutes later:

| Live source state | Findings |
|---|---|
| Returned the identical bytes | 61 |
| Had changed, redirected elsewhere, or stopped answering | 38 |

So **38% of web sources had visibly changed within about an hour** of being read — page churn of any kind, not a
changed fact, but the reason claims are stored against the bytes they were made from rather than a URL. The
same pattern shows up across two runs of this batch an hour apart: replaying 1,000 companies against their own
snapshots reported 4 field-level changes on 4 companies, all of them a website becoming unreachable, becoming
unprovable, or landing on a domain-marketplace listing. A replay against a snapshot where nothing had changed
reported nothing.

Run-to-run variation is also measured rather than assumed: three batches of 1,000 drawn from the same universe in
the same day produced 206, 204 and 201 verified websites. Differences of about one percentage point at this scale
are noise, and nothing in this document claims better than that.

## What it costs

For the 1,000-company batch, 6 workers, a 90-second wall-clock budget per company:

- 2,337 seconds of wall clock; median 9.3 seconds per company, 95th percentile 41.2 seconds
- 10,178 HTTP requests, of which 74 were served from the run's own cache and 160 avoided because the host was
  already known to be unreachable
- 6,751 evidence files written, 121 MB — the pages every published claim was read from
- **$0.00** to third parties: no paid API is used, and no model is used to read or summarise the evidence
- Request policy: minimum gap per host of 0.05 s to the registry, 0.20 s elsewhere, 0.30 s to news, 0.35 s to
  LinkedIn; 8 s for a candidate-domain probe, 15–20 s for a page or registry read, one 4 s retry; 600 KB per page
  maximum

## What it does not reach

These are properties of the population, not settings to tune.

- **Websites.** The register lists a website for 10.9% of the eligible universe. This agent reaches 20.1%, about
  double, by deriving candidate domains from the company's own name and its registered email domain and then
  proving each candidate against the page. The remaining four fifths of small entities appear to have no website
  at all. Third-party search was measured on 30 companies whose site the free path could not find: a commercial
  search API recovered 2, a self-hosted general search engine recovered 1. Search results for this population
  point at directories rather than companies, so the default path does not use search.
- **Employee counts.** The register supplies a number for 14.5% of the universe; the agent reaches 14.4% of this
  batch by its own path plus 15.0% including registered subunits. Reading subunit counts separately adds no
  additional companies — the same 22 are reachable either way.
- **Reviews and ratings.** 3 companies in 1,000. The only permitted source is what a company publishes about
  itself, and Norwegian companies almost never publish a structured self-rating.
- **Hiring.** 14 companies in 1,000 list two or more openings on their own site. A national vacancy feed was
  tested against this batch and matched none of them, because the listings most Norwegian employers use are
  excluded from its interface.
- **Sentiment.** Not attempted. A defensible sentiment claim needs several hundred independently labelled
  Norwegian company texts; nothing with usable rights was available, so no sentiment label is published.
- **Time.** This is a current-state agent. Each run is a snapshot; a later run reports the fields that actually
  changed, and only those.
