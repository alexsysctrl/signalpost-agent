# Measurements

What this agent was run on, what it returned, how the results were checked, and what it does not reach.
Every number here comes from a run that happened, and the command that produces it is stated. The run described in
this document is the same code that is in this repository.

## The batch

1,000 organisation numbers drawn from the frozen eligible universe the competition publishes — 411,160 active
Norwegian legal entities whose latest submitted annual accounts are for 2025.

```bash
python3 agent.py --orgs companies.jsonl --out out/run-1 --workers 6 --budget 90
./verify-run.sh out/run-1
```

| | |
|---|---|
| Inputs | 1,000 |
| Terminal envelopes written | **1,000** |
| Envelopes that record a source that did not answer | 3 |
| Inputs with no envelope | 0 |

Two of the 1,000 numbers are not in the frozen bulk snapshot the register publishes; both exist in the live
register and were profiled from it. Where a number is in neither, the envelope says so and lists what was checked.
Where the register did not answer at all, the profile says the source failed — it does not claim the company has
no accounts.

## What a profile contains

Counts are companies out of 1,000. A profile records 36 claims (median), 26 of which state a fact a source
supported; the rest are explicit statements that something was looked for and not found.

| | Companies |
|---|---|
| Legal identity: name, legal form, organisation number | 1,000 |
| Registered activity | 1,000 |
| The year of the latest filed accounts | 998 |
| Filed annual accounts (figures, by year) | 997 — 3 recorded as a failed source |
| Registered role holders | 997 |
| VAT registration | 997 |
| Equity / assets / annual result | 992 / 989 / 970 |
| Revenue | 684 |
| Share capital | 922 |
| Establishment date | 979 |
| Registered workplaces (subunits) | 776 |
| Contact details published by the register: e-mail / phone | 237 / 187 |
| Employee figure | 144 |
| A verified company website | 200 |
| A registered trading name distinct from the legal name | 27 |

Group membership is a field of the register itself (`erIKonsern`), and it answers for every company: 998 of these
1,000 are recorded as **not** part of a group, and the profile says so rather than leaving the reader to infer it
from an absent line. 59 are in a group structure; for 45 of those the register names the entity this company sits
under, and the profile states it.

Figures come from the accounts filed under that organisation number. Where a company also files consolidated
group accounts, the group figures are published only if the company's own filing does not carry that line, and
they are labelled as consolidated group figures.

## A trading name, and what does not count as one

The brief asks for legal identity *and public brand*. The part of that which can be stated from an official
source is the name a company registers for its own subunits (`underenheter` in the register API), so it is
published from the register rather than guessed from a page title. Read out of the batch: GEST BREISETH AS
registers **FIRST HOTEL BREISETH**; KNUDSEN & KNUDSEN AS registers **KKTAKST**; TJOMSLAND AS registers
**REMA 1000 LYNGDAL**; BODØ JUKSAMASKINSERVICE AS registers **BOBRANN**; KULELAGER AS registers **SMK**.

Reading every published example is what made the rule honest rather than merely strict. The first version
published 34 companies; seven of them were not names:

| Rejected | Why |
|---|---|
| `TO KANTEN C/O RUNE BIRKELAND` | a care-of line |
| `SAREPTA AS V/ ADV. TOM STAVNES` | the responsible person, not a brand |
| `JAB JOSEF ANSTOETZ V/ADV. ESPEN TØNDEL` | the same |
| `SOLBAKKEN TERRASSE V/MOBO A/L` | the same |
| `ALUHAK DRIFT AS AVD PEOPLE`, `ALUHAK DRIFT AS AVD STAVANGER` | a branch label and a town |
| `LINDBAK SØRVEST AS AVD STAVANGER`, `THORBJØRNRUD HOTELL AS AVD PU18` | a branch label and a place |

A name counts only when it contributes a word the entity's own registered name does not already contain, after
company suffixes, branch labels and registered locality words are removed — and now also: a word that appears
only after `avd / avdeling / utsalg / butikkavd / filial` names where a branch is, not what it is called, and a
`c/o` or `v/` line names a person. Measured on those same 34 organisations before and after the rule changed:
34 → 27 companies, the seven above dropped, real brands kept. Twelve of these cases are in the self-test as a
table, and the count of accepted brands is printed.

## What was found in sources outside the register

1,602 findings were produced. The competition's own acceptance rules accepted **1,601** and refused 1 — a news
mention that could not establish the exact legal entity. Refusal is recorded, not quietly dropped.

| | Findings |
|---|---|
| Derived from the registers (filing history, workforce) | 1,141 |
| Genuinely outside the registers | **461** |

| Outside the register | Companies | Findings |
|---|---|---|
| Own website, proven to belong to that company | 200 | 200 |
| — proven by the organisation number printed on the page | 37 | |
| — proven by registered name with locality, or by a domain the company's own records point at | 163 | |
| A plausible website that could not be tied to the company | 99 | reported as `ambiguous`, never published |
| Profile handles: Facebook 95, Instagram 57, LinkedIn 47, X 7, TikTok 5, YouTube 4 | — | 215 |
| Job listings on the company's own site | 27 | 27 |
| Public mentions in news, each dated by its publisher | 11 | 15 |
| Ratings a company publishes about itself | 3 | 4 |
| Companies with at least one finding outside the registers | 206 | |
| Companies with findings from two or more sources | 205 | |
| Companies with two or more distinct open-web platforms (the register not counted) | 99 | |

How the 201 verified sites were reached: 120 from a domain derived from the company's own name, 54 from a website
the register already lists, 27 from the domain of the company's registered e-mail address. 200 of those 201 are
published as the company's own website; the other one was found to belong to its parent group and is recorded that
way instead (below). A name-only match is never published as a fact: 98 candidates in this batch resolved to a real
site that could not be tied to the company, and all of them are reported as unproven. A page that is a domain
marketplace (a parked domain for sale) is not a company's website either — that rule came out of diffing two runs
of this batch, where 2 of 6 reported "website changes" were hughedomains.com and aftermarket.eu listings.

Only the company's own profile counts as its footprint: `linkedin.com/company/…`, not a person's profile link.
That was decided by measurement — on an earlier 100-company batch, four of the five findings that failed to
re-confirm were people links, which describe a person and rotate on the page.

## Three rules a reviewer asked for, and what they changed here

The entry was read by one of the organisers, who raised three specific objections: a website might be a parent
group's rather than the company's; a social handle might belong to a group or an agency; a news item might not be
a real, dated post. Each one was measured before it was coded for, and the honest answers are different.

**A group's site is not its subsidiary's site.** The register's group endpoint (`konsernstruktur/{number}`) does
not answer about the company you asked for. It resolves to the head of the group and returns that record, whose
name and organisation number sit at the top of the response. Reading only the child rows — which is what this
agent did until it was checked — throws that away: of the 59 companies in this batch with a group record,
**45 had a different entity named as the head of their structure**, and none of those facts reached a profile.
The parent is now read out, both into the profile and into a test: a verified domain is treated as the group's
when it is spelled from the group's registered name and the page does not print this organisation number. In this
batch that happened **once** — TELLNES NÆRINGSPARK TOMT 2 AS was about to be given `telle-tre.no`, which is
spelled from its parent TELLE GRUPPEN AS, so the profile records the website as ambiguous and says why.

Across the whole population that is one company in a thousand, and the document says so rather than implying a
bigger fix. What is common instead is a domain shared by a family: RESTECH NORWAY AS on `restech.no` under its
parent RESTECH HOLDING AS, BLADET NORDLYS AS on `nordlys.no` under AMEDIA AS. Those domains match the
subsidiary's own registered brand, so they are published as the company's site, and its accounts and mentions are
filtered by ownership instead. A chain brand that appears in neither registered name (BILPARTNER NAMSOS AS under
BILSENTERET INVEST AS) cannot be assigned from names at all, and no rule pretends otherwise.

**A handle has to belong to this company.** A handle that shares no distinctive word with the company's registered
name was already refused unless the link stood next to the company's name or its organisation number. That second
condition was the hole the reviewer found: a footer reading "part of the group" next to the group's own account
passes proximity and is still not the subsidiary's footprint. A handle whose leading word is a registered group
relation's brand word is now refused even when the page names the company. The company's own account still passes,
because the company is tried first. Result in this batch: 215 handles published, and the rule is in the self-test
against the exact shape — a group's LinkedIn account in a subsidiary's footer.

**A news item has to be dated by its publisher.** A date in a news feed is the feed's claim about when something
was posted; the auditor was asking whether the publisher says it. A published mention now needs a date carried by
the fetched article page itself — a `<time datetime=…>`, an `article:published_time` or `og:published_time` meta
tag, or `datePublished` in the page's own structured data — and each finding records where its date came from.
Measured before the rule was trusted: on a live check of five news items for a real listed company, four were
reachable at their own addresses and **all four carried a publish date on the page**. In this batch all 15
published mentions are publisher-dated, and 1 profile states plainly that the articles it found carried no such
date. The rule costs almost nothing here and makes the family citable.

## Correctness, checked by a second path

400 published findings were sampled across companies and signal types and re-checked by code that does not share
the implementation that produced them. The split of methods is published, because the strength of a check depends
on which one ran:

| How the finding was re-derived | Findings |
|---|---|
| Filing counts recounted from the bytes this run kept, with a parser written separately from the one that made the claim | 255 |
| Page findings (websites, profiles, job listings, news mentions, ratings) re-derived from the bytes this run kept | 101 |
| Register workforce figures compared against the live register API | 44 |
356 of the 400 were therefore re-derived from evidence this run kept rather than from whatever the web happens
to say today. The audit report publishes these counts itself (`re-derived_from_kept_evidence`,
`live_source_reasked`), so the split is checkable rather than asserted.

Job findings are the case where the independence matters most: the agent finds links with a regular expression
over the raw HTML, and the verifier walks the document with `html.parser` — real anchor tags, real text nodes —
while applying the **same published definition of a job link**. A verifier that carried its own word list would
only have proven that two definitions disagree, which is what it did before this was fixed: three findings were
reported as wrong numbers and every one of them was the verifier being wrong.

| Result | Value |
|---|---|
| Findings published under the wrong company | **0** |
| Figures that did not re-derive | **0** |
| Entity precision | **1.000** |
| Metric precision | **1.000** |
| Qualification under the external-footprint gates | **passed** |

Separately, every rendered profile was read back against the claims it says it came from: 24,886 stated facts
across 1,000 profiles, 0 sentences without a claim behind them, 0 facts presented without provenance, and 1,000
of 1,000 profiles stating what was searched for and not found.

Two defects were caught by that read-back rather than by looking at a page. The register states the same fact in
two shapes — a purpose as one text with line breaks in its bulk file, and the identical text as a list of lines
in its API; an employee count as `"14"` in one and `14` in the other. Comparing them exactly said "different",
so 3,070 profiles carried the same fact twice. Values are now normalised by shape before anything decides
whether a fact is new; this batch records 4 such profiles, each one a wording difference between the register's
two sources rather than a duplicate. The second defect was a link pattern: `<a…` matches
`<article … href=…>` and `<aside href=…>`, which is how three sites came to be counted as carrying two job
links when they carried one.

## Sources move. That is measured too.

Re-checking a claim is not the same as asking the source again. Of the 101 findings re-derived from kept *pages*,
the live source was then asked a few minutes later: 59 returned identical bytes, **42 had changed, redirected
elsewhere, or stopped answering**. (The register-derived findings are not counted there: their check already
re-reads the live register, and a byte-for-byte comparison against a bulk file is not a measurement of anything.) A claim is stored against the bytes it was made from — URL,
retrieval time, content hash — so a publisher changing a page is a fact about the web, not a defect in the
profile.

The same thing shows up between runs, and it is the part most worth stating plainly. With this build, a 120-company
pair run back to back reports **no field-level changes at all**, and pointing `--resume` at the finished
1,000-company run re-emits all 1,000 profiles — envelopes, findings and the flat profiles — byte-for-byte with no
request made. Earlier builds measured the other case on the same companies: two runs an hour apart reported **2
field-level changes on 2 companies** — storelva1.webnode.no no longer answered, and one site moved from a proven
website to an unproven one. The pair of runs before that reported 3 changes on 3 companies, all in the same family,
and the next pair reported 2 — dugnadsportalen.no and damsgaardregnskap.no, which had "disappeared" in one
comparison, came back. Same agent, same companies: those two sites were simply unreachable in one run and present
in the next.

So an availability change is read here as *what this run could establish*, never as "the company removed its
website". A live replay of 50 companies 40 minutes after a run reproduced 1 of 3 change sets, and the two it did
not reproduce were exactly those reachability cases. What is stable is the diff: running the comparison twice over
the same bytes gives the same answer, and a snapshot compared with itself reports nothing.

The diff needed a fix of its own to say any of that honestly. Comparing two runs of this batch first reported
roughly two hundred changes in registered purpose and activity text — not because the register had rewritten two
hundred companies, but because one build recorded a purpose as the list of lines the API returns and the next
recorded the identical text as the single string the bulk file holds. A comparison that looks at representations
reports its own code as news. Values are now normalised by shape on both sides — a fact and its absence, the same
text in one piece or in parts, `"14"` and `14` — and the same two runs compared under that rule report 2 changes,
both real.

Run-to-run variation is measured rather than assumed. Six runs of the same 1,000 companies across two days — the
last two with this exact code, the earlier four on the builds live at the time: **201, 203, 204, 202, 201 and 202**
verified websites. A difference of one or two companies at this scale is noise, and nothing in this document claims
better than that.

## What it costs

The same 1,000 organisation numbers, 6 workers, a 90-second wall-clock budget per company, measured twice with the
shipped code an hour apart. The work is the same every time; the waiting is not:

| | first measurement | second measurement |
|---|---|---|
| wall clock | 2,371 s | 2,356 s |
| per company, median | 9.3 s | 9.1 s |
| per company, 95th percentile | 44.2 s | 44.5 s |
| HTTP requests | 10,205 | 10,184 |
| served from the run's own cache | 75 | 76 |
| avoided because the host was already unreachable | 158 | 159 |
| evidence pages written | 6,769 (126 MB) | 6,768 (125 MB) |
| source calls that failed outright | 3 | 3 |
| cost to third parties | **$0.00** | **$0.00** |

A build from earlier the same day measured 3,278 s with 10,192 requests. Request counts vary by 0.1%; wall clock
varies by 40%. That gap is upstream response time, not work. A published cost that quoted only the favourable run
would be a number about a good hour, not about this agent.

Request policy: minimum gap per host of 0.05 s to the registry, 0.20 s elsewhere, 0.30 s to news, 0.35 s to
LinkedIn; 8 s for a candidate-domain probe, 15–20 s for a page or registry read, 35 s for the accounts register
listing, one 4 s retry, 30 s maximum cool-down on a host that just failed, 600 KB per page maximum.

The accounts register deserves its own note. At 05:00 UTC one call to it answered in **18.2 seconds**, and a
batch run that night recorded **952 profiles as "no filed annual accounts published for this entity"** when the
truth was that no answer had arrived. Two changes came out of that:

- A module that never got an answer is recorded as a **failure**, not as an absence. A 404 or an empty 200 is an
  answer from the register; a timeout, a connection failure, or a 5xx is not. `official.py` carries a self-test
  that asserts the three cases produce three different states.
- After a host fails, every worker backs off that host for up to 30 seconds. Six workers asking a struggling
  endpoint at the normal rate is how one slow endpoint becomes a batch of fake absences.

In the run reported here that classification records **3 account-read failures out of 1,000 companies** — visible
in `run-report.json` as `source_failures`, instead of appearing as 952 companies that file nothing.

Nothing was paid for: no search API, no paid data, no model used to read or summarise evidence. A resumed run
makes this concrete in the other direction: pointing `--resume` at a completed run re-emits all 1,000 profiles
byte-for-byte — envelopes, profiles and findings identical — in 1.6 seconds, with `requests_this_run: 0`.

## What it does not reach

These are properties of the population, not settings to tune.

- **Websites.** The register lists a website for 10.9% of the eligible universe. This agent reaches 20.0%, about
  double, by deriving candidate domains from the company's own name and its registered e-mail domain and then
  proving each candidate against the page. The remaining four fifths of small entities appear to have no website
  at all. Third-party search was measured on 30 companies whose site the free path could not find: a commercial
  search API recovered 2, a self-hosted general search engine recovered 1, and following the links on the pages it
  returned recovered 0 of 12. Search results for this population point at directories rather than companies, so
  the default path does not use search.
- **Employee counts.** The register supplies a number for 14.5% of the universe; this agent reaches 14.4% of this
  batch. Reading subunit counts separately adds no additional companies — the same 22 are reachable either way.
- **Reviews and ratings.** 3 companies in 1,000. The only permitted source is what a company publishes about
  itself, and Norwegian companies almost never publish a structured self-rating.
- **Hiring.** 27 companies in 1,000 carry two or more job links on their own site. A national vacancy feed was
  tested against this batch and matched none of them, because the listings most Norwegian employers use are
  excluded from its interface.
- **Dated activity.** Measured before writing any extractor, and measured again on this build: of the 214 distinct
  company-site pages this run kept, **5 carry a `<time datetime=…>` and 1 an `itemprop=datePublished`, covering 4
  companies**. Fourteen more pages carry dates as printed text, which is a different thing — a `dd.mm.yyyy` on a
  page can be a copyright year or a contract date. A family reachable for 0.4% of the batch does not justify its
  own failure modes, so no activity-date claim is published.
- **Sentiment.** Not attempted. A defensible sentiment claim needs several hundred independently labelled
  Norwegian company texts; nothing with usable rights was available, so no sentiment label is published.
- **Time.** This is a current-state agent. Each run is a snapshot; a later run reports the fields that actually
  changed, and only those — with the understanding above about what "changed" can mean when a source was merely
  unreachable.
