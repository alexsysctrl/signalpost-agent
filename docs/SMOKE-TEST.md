# Smoke test: 100 companies

The local scale test the competition asks an entry to run before submitting. Run on 23 October 2026 with the same code that is in this repository. The machine-readable twin of this page is [`smoke-test-report.json`](smoke-test-report.json),
generated from that run's own output by `python3 smoke_report.py --run <run-directory> --output <file>` — nothing
in it is typed by hand.

```bash
python3 agent.py --count 100 --out out/smoke-1 --workers 6 --budget 90
./verify-run.sh out/smoke-1
python3 smoke_report.py --run out/smoke-1 --output docs/smoke-test-report.json
```

100 organisation numbers drawn from the frozen eligible universe of 411,160 active Norwegian entities. This is an
independent draw, not a subset of the 1,000-company batch described in [`MEASUREMENTS.md`](MEASUREMENTS.md).

## The batch contract

| | |
|---|---|
| Inputs | 100 |
| Terminal envelopes written | **100** |
| Inputs with no envelope | 0 |
| Output order matches input | yes |
| Contract validation | passed |

## What came back

| | Companies |
|---|---|
| Claims recorded per profile | 36 (median), of which 26 state a fact the register or a page supported |
| Legal identity | 100 |
| Registered role holders | 100 |
| Filed annual accounts | 99 (one account read timed out; that profile says the source failed, not that the company files nothing) |
| Registered workplaces (subunits) | 85 |
| An employee figure | 11 |
| A registered trading name distinct from the legal name | 3 |
| A company website proven to belong to that company | 16 |
| A plausible website that could not be tied to the company | 11, recorded as `ambiguous` and never published |

149 findings were produced and **all 149 were accepted by the competition's own acceptance rules** — none had to
be dropped: 110 from the registers, 17 from the companies' own sites, 9 Facebook profiles, 6 LinkedIn company
profiles, 4 Instagram, 1 X profile, 2 news mentions. 17 companies appear on two or more sources and 8 on two or
more open-web platforms, and 3 of these companies have a registered trading name distinct from their legal name.

What the three rules the reviewer asked for did on this sample: 8 of the 100 profiles name the group they sit
under, read from the register's own group structure; **no** verified website in this batch turned out to be a
parent group's domain, so the group-ownership guard published nothing here and refused nothing here — that is the
honest reading of a 100-company sample, and the 1,000-company batch reports one such case; and both news findings
in this batch carry their date from the publisher's own page.

A profile claim and a published finding are different records, and the counts above are deliberately separated:
claims fill the profile, findings are the cross-source observations the external evaluator reads. Every one of the
every company with an employee figure also has a workforce finding published for it — that was checked, not assumed.

## Correctness, checked by a different path

Every finding in the batch — all 149, not a sample — was re-checked by code that does not share the implementation
that produced it: registry filing counts recounted from the bytes the run kept, page findings re-derived from those
same bytes, job findings re-counted by walking the document with `html.parser` instead of a regex, and
register figures compared against the live API.

- **Findings published under the wrong company: 0.**
- **Figures that did not re-derive: 0.**
- Entity precision **1.000**, metric precision **1.000**, qualification passed.
- 138 of the 149 findings were re-derived from evidence this run kept (99 filing counts from the register
  payloads, 39 from kept pages); the other 11 were register workforce figures compared against the live register
  API. Of those 39 pages, re-asked a few minutes later, 22 returned identical bytes and
  **22 had changed, redirected elsewhere, or stopped answering.**
- Read-back of the rendered page: 2,511 stated facts across 100 profiles, 0 sentences without a claim behind them,
  0 facts presented without provenance, 100 of 100 profiles stating what was searched and not found.

## What it cost

- 283 seconds of wall clock for 100 companies with 6 workers; median 11.2 seconds per company, 95th percentile
  45.5 seconds, worst 81.0 seconds, against a 90-second budget per company
- 1,056 HTTP requests, of which 6 were served from the run's own cache and 3 avoided because the host was already
  known to be unreachable; 686 evidence pages written, 16 MB
- **$0.00** to third parties. No paid API, and no model used to read or summarise any evidence (`models_used: []`
  in the run report).
- Request policy: minimum gap per host of 0.05 s to the registry, 0.20 s elsewhere, 0.30 s to news, 0.35 s to
  LinkedIn; 8 s for a candidate-domain probe, 15–20 s for a page or registry read, 35 s for the accounts register
  listing, one 4 s retry; 30 s maximum cool-down on a host that just failed; 600 KB per page maximum; user agent
  `Mozilla/5.0 (compatible; SignalpostResearchAgent/1.0; +mailto:alex@sqopa.com)`, which every source here answered.

## Limits visible in this batch

16 of 100 companies had a website that could be proven, and 11 more had a plausible candidate that could not be
tied to the company — those 11 are reported as unproven, which is the intended behaviour: an uncertain match is
never published as a fact. Employee figures reached 11 companies, and the register itself supplies a number for
only a minority of small entities. Not one of these 100 companies publishes a structured rating about itself, so
this batch published no rating at all — an absence, stated here, rather than a zero.
