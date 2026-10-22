# Smoke test: 100 companies

The local scale test the competition asks an entry to run before submitting. Run on 21 October 2026 with the code
in this repository. The machine-readable twin of this page is [`smoke-test-report.json`](smoke-test-report.json),
generated from that run's own output by `python3 smoke_report.py --run <run-directory> --output <file>` — nothing
in it is typed by hand.

```bash
python3 agent.py --count 100 --out out/smoke-1 --workers 6 --budget 90
./verify-run.sh out/smoke-1
python3 smoke_report.py --run out/smoke-1 --output docs/smoke-test-report.json
```

100 organisation numbers drawn from the frozen eligible universe of 411,160 active Norwegian entities.

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
| Claims per profile | 38 (median), each with its own evidence record |
| Registered role holders | 100 |
| Filed annual accounts | 99 |
| Registered workplaces | 85 |
| A company website proven to belong to that company | 16 |
| A plausible website that could not be tied to the company | 11, recorded as `ambiguous` and not published |
| Registered employee counts | 11 |
| Findings on two or more platforms | 17 |

149 external findings were produced and **all 149 were accepted by the competition's own acceptance rules** — none
had to be dropped: 110 from the registers, 17 from the companies' own sites, 9 Facebook profiles, 6 LinkedIn
company profiles, 4 Instagram, 2 dated news mentions, 1 X profile.

## Correctness, checked by a different path

Every finding in the batch was re-checked by code that does not share the implementation that produced it:
registry figures re-read from the live API, page findings re-derived from the bytes the run kept for them, and job
findings re-counted with a different HTML parser than the one that made the claim.

- **Findings published under the wrong company: 0.**
- Figures that did not re-derive: **1 of 149.** A quoted news passage is no longer on the live article. The
  evidence recorded when it was read — URL, retrieval time, content hash — is intact; the publisher changed the
  page. It is reported as not re-confirmable rather than as correct.
- Entity precision **1.000**, metric precision **0.993**.
- 39 findings were re-derived from archived evidence; when the same 39 sources were then asked again a few
  minutes later, 24 returned identical bytes and 15 had changed, redirected, or stopped answering.
- Read-back of the rendered page: 2,316 stated facts across 100 profiles, 0 sentences without a claim behind
  them, 0 facts without provenance, 100 of 100 profiles stating what was searched and not found.

## What it cost

- 262 seconds of wall clock for 100 companies with 6 workers; median 8.7 seconds per company, 95th percentile
  45.0 seconds, against a 90-second budget per company
- 1,058 HTTP requests, of which 6 were served from the run's own cache and 2 avoided because the host was
  already known to be unreachable; 683 evidence pages written, 15 MB
- **$0.00** to third parties. No paid API, and no model used to read or summarise any evidence (`models_used: []`
  in the run report).
- Request policy: minimum gap per host of 0.05 s to the registry, 0.20 s elsewhere, 0.30 s to news, 0.35 s to
  LinkedIn; 8 s for a candidate-domain probe, 15–20 s for a page or registry read, one 4 s retry; 600 KB per page
  maximum; user agent `Mozilla/5.0 (compatible; SignalpostResearchAgent/1.0; +mailto:alex@sqopa.com)`, which
  every source here answered.

## Limits visible in this batch

16 of 100 companies had a website that could be proven, and 11 more had a plausible candidate that could not be
tied to the company — those 11 are reported as unproven, which is the intended behaviour: an uncertain match is
never published as a fact. Employee counts reached 11 companies because the register itself supplies a number for
only a minority of small entities. Ratings reached none: none of these 100 companies publishes a structured
rating about itself.
