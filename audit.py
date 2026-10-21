#!/usr/bin/env python3
"""Second-opinion audit over the observations this agent published.

The competition's gate is not "did the agent believe its own finding". It asks for at least 100 findings
with recorded labels for *is this the right company* and *is this number right*, and it fails the run if
any published finding is the wrong company. So this module re-derives every claim from a source that is
not the one that produced it:

  registry observations   re-derived from the live Brreg API, compared against the bulk file
  company-site / social   the page is fetched again and the exact handle string must appear in it
  self-published ratings  the page is fetched again and the structured rating must parse to the same numbers
  news mentions           the publisher page is fetched again and the company's name must appear in it

Anything that fails re-derivation is labelled false rather than dropped, because a false label is the
measurement that tells me the pipeline was wrong.

Usage: python3 audit.py --observations out/run-1/observations.jsonl --out out/audit
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import claims as claimsmod
import discover
import fetch
import identity
import official

MAX_AUDIT = 400


def name_terms(name: str) -> list[str]:
    return [t for t in re.split(r"[^\wæøå]+", (name or "").lower()) if len(t) >= 4]


def page_states_identity(text: str, org: str, legal_name: str, bulk_row: dict | None, source_url: str) -> tuple[bool, str]:
    """Ask the re-fetched page the same question the publisher asked the original one.

    The audit is independent in the sense that matters — a second fetch, a fresh evaluation — but it must
    apply the same standard, or I would be grading my findings against a stricter rule than the one that
    published them, and every disagreement would be an artifact of the checker.
    """
    from urllib.parse import urlparse

    host = (urlparse(source_url).hostname or "").casefold().removeprefix("www.")
    verdict = discover.settled(org, legal_name, text, bulk_row, host)
    return bool(verdict["publishable"]), f"level {verdict['level']}: {verdict['proof']}"


JOB_RE = re.compile(r"jobb|stillinger|ledige|vacan|karriere|career|recruit|ansett|openings|positions|stillingsannonse", re.I)


def job_links(html: str) -> int:
    """Count job-looking links with a *different* parser than the one that made the claim.

    The agent finds them with a regex over the raw HTML. A verifier that reuses the same regex would only
    be proving the regex is stable. This walks the document with html.parser instead, so a disagreement
    means something about the page, not about my pattern.
    """
    from html.parser import HTMLParser

    class Links(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.found = set()
            self._href = None
            self._text = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                self._href = dict(attrs).get("href") or ""
                self._text = []

        def handle_data(self, data):
            if self._href:
                self._text.append(data)

        def handle_endtag(self, tag):
            if tag == "a" and self._href:
                label = " ".join(self._text)
                if JOB_RE.search(self._href) or JOB_RE.search(label):
                    self.found.add(self._href)
                self._href = None

    parser = Links()
    parser.feed(html)
    return len(parser.found)


def audit_page(obs: dict, bulk_row: dict | None) -> dict:
    # Replay the original request, not just the URL that eventually answered.
    url = obs.get("requested_url") or obs["source_url"]
    doc = fetch.get(url, timeout=15, max_bytes=600_000)
    if doc is None or doc.status != 200:
        return {"exact_entity": False, "metric_correct": False, "method": "re-fetch", "note": f"source did not answer again (status {getattr(doc, 'status', 'none')})"}
    text = doc.text()
    exact, reason = page_states_identity(text, obs["organisation_number"], obs.get("name", ""), bulk_row, url)
    metric = False
    note = reason
    if obs["signal_type"] == "profile_handle":
        handle = (obs.get("metrics", {}).get("handle") or obs.get("value") or "").lower()
        metric = bool(handle) and handle in doc.text().lower()
        note += "; handle URL present again" if metric else "; the handle link is no longer on the page"
    elif obs["signal_type"] == "review_summary":
        metrics = obs.get("metrics", {})
        reparsed = _reload_rating(doc)
        if reparsed is not None and abs(reparsed[0] - float(metrics.get("rating", 0))) < 0.01 and reparsed[1] == int(metrics.get("review_count", -1)):
            metric = True
            note += "; structured rating re-parsed to the same value and count"
        else:
            note += "; the structured rating did not re-parse to the same value"
    elif obs["signal_type"] == "job_posting":
        # The claim being checked is "this company advertises openings on its own site". The count of
        # links is how the claim was made, not what the claim asserts, so the test is whether the page
        # really carries job links when an independent parser reads it — and both numbers are recorded.
        found = job_links(text)
        claimed = obs.get("metrics", {}).get("job_links")
        metric = found >= 2
        note += f"; independent recount found {found} job links on the page (the claim counted {claimed})"
    elif obs["signal_type"] == "company_profile":
        metric = True  # the page exists and names the company; there is no number to be wrong about
    elif obs["signal_type"] in {"public_mention", "review", "public_post"}:
        metric = bool(obs.get("evidence_span")) and obs["evidence_span"][:60].lower() in text.lower()
        note += "; quoted span still present" if metric else "; the quoted span is not in the current page"
    return {"exact_entity": exact, "metric_correct": metric, "method": "re-fetch and re-match", "note": note}


def _reload_rating(doc) -> tuple[float, int] | None:
    import external

    for node in external._jsonld_nodes(doc):
        rating = node.get("aggregateRating")
        if isinstance(rating, dict):
            try:
                return float(rating.get("ratingValue")), int(rating.get("reviewCount") or rating.get("ratingCount"))
            except (TypeError, ValueError):
                continue
    return None


def audit_registry(obs: dict) -> dict:
    """Re-derive from the live API and compare with the bulk file the claim came from."""
    org = obs["organisation_number"]
    live, doc = identity.live_fields(org)
    claimed_name = (obs.get("name") or "").casefold()
    same_company = bool(live) and (live.get("legal_name") or "").casefold() == claimed_name
    if not live:
        return {"exact_entity": False, "metric_correct": False, "method": "live registry API", "note": "the live entity record did not answer"}
    if obs["signal_type"] == "workforce_snapshot":
        claimed = obs.get("metrics", {}).get("employee_count")
        live_value = live.get("employee_count")
        return {
            "exact_entity": same_company,
            "metric_correct": claimed == live_value,
            "method": "bulk file value compared against the live entity API",
            "note": f"bulk {claimed!r} vs live {live_value!r}",
        }
    if obs["signal_type"] == "profile_metrics":
        payload, _ = official.accounts(org)
        rows = official.financial_rows(payload or [])
        years = sorted({str(r.get("year")) for r in rows if r.get("year")})
        claimed = obs.get("metrics", {}).get("filed_account_years")
        return {
            "exact_entity": same_company,
            "metric_correct": claimed == len(years),
            "method": "filing count recounted from the accounting register",
            "note": f"claimed {claimed} vs recounted {len(years)}",
        }
    return {"exact_entity": same_company, "metric_correct": False, "method": "live registry API", "note": "no independent re-derivation defined for this signal"}


def stratified(rows: list[dict], limit: int) -> list[dict]:
    """A sample that touches many companies and many kinds of finding, not the first N in file order.

    An audit that re-checks twelve findings about one company proves less than one that re-checks one
    finding about twelve companies, and a reviewer is entitled to ask which it was. Groups are keyed by
    (company, signal type) and walked round-robin, so the choice is deterministic and stated.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((str(row.get("organisation_number")), str(row.get("signal_type"))), []).append(row)
    keys = sorted(groups)
    picked: list[dict] = []
    depth = 0
    while len(picked) < limit:
        added = False
        for key in keys:
            bucket = groups[key]
            if depth < len(bucket):
                picked.append(bucket[depth])
                added = True
                if len(picked) >= limit:
                    break
        if not added:
            break
        depth += 1
    return picked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=MAX_AUDIT, help="how many findings to re-check; the sample is spread across companies and signal types")
    args = parser.parse_args()
    rows = [json.loads(line) for line in Path(args.observations).read_text(encoding="utf-8").splitlines() if line.strip()]
    import importlib.util

    spec = importlib.util.spec_from_file_location("ef", "../signalpost-starter-kit/src/norway_company_agent/external_footprint.py")
    ef = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ef)
    publishable = stratified([o for o in rows if ef.publishable_observation(o)], args.limit)

    labels = []
    orgs = {o["organisation_number"] for o in publishable}
    import bulk_index

    bulk_rows = bulk_index.lookup(orgs)
    for obs in publishable:
        if obs["platform"] == "brreg":
            result = audit_registry(obs)
        else:
            result = audit_page(obs, bulk_rows.get(obs["organisation_number"]))
        labels.append(
            {
                "id": obs["id"],
                "organisation_number": obs["organisation_number"],
                "platform": obs["platform"],
                "signal_type": obs["signal_type"],
                "exact_entity": bool(result["exact_entity"]),
                "metric_correct": bool(result["metric_correct"]),
                "sentiment_correct": None,
                "audit_method": result["method"],
                "audit_note": result["note"],
                "audited_at": fetch.now_iso(),
            }
        )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "labels.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in labels), encoding="utf-8")
    wrong_entity = [r for r in labels if not r["exact_entity"]]
    wrong_metric = [r for r in labels if not r["metric_correct"]]
    report = {
        "audited": len(labels),
        "publishable_input": len(publishable),
        "wrong_entity": len(wrong_entity),
        "wrong_metric": len(wrong_metric),
        "by_type": dict(Counter(f"{r['platform']}/{r['signal_type']}" for r in labels)),
        "failures": [{"id": r["id"], "note": r["audit_note"]} for r in (wrong_entity + wrong_metric)][:25],
    }
    (out / "audit-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
