"""Claims and evidence — the output contract.

A claim without a source is worth nothing here, and a source whose bytes can't be checked later is
worth almost nothing. So every published fact carries an evidence id, and evidence carries URL,
retrieval time, content hash and the span of the source that carries the claim.

Availability states are load-bearing, not decoration: `not_available` (checked, nothing there),
`blocked` (source refused us), `failed` (our own request failed), `ambiguous` (can't be sure it's
this company) and `not_applicable` (this kind of entity never has it) are different findings, and the
competition scores them differently. Turning absence into zero is the specific error the brief warns
about, so this module refuses to do it.
"""
from __future__ import annotations

import time
import uuid

from fetch import Doc

STATES = ("available", "not_available", "blocked", "not_applicable", "ambiguous", "failed")


class Record:
    def __init__(self, org: str, run_id: str | None = None):
        self.org = org
        self.run_id = run_id or time.strftime("%Y-%m-%dT%H%M%SZ", time.gmtime())
        self.started = time.time()
        self.started_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.claims: list[dict] = []
        self.evidence: list[dict] = []
        self.errors: list[dict] = []
        self.requests = 0
        self.third_party_cost = 0.0
        self._seen_evidence: dict[str, str] = {}

    # ---- evidence -------------------------------------------------------------------------------
    def evidence_for(self, doc: Doc | None, span: str = "", source_class: str = "other_public") -> str | None:
        if doc is None:
            return None
        key = f"{doc.url}|{doc.sha256}"
        if key in self._seen_evidence:
            return self._seen_evidence[key]
        eid = "ev-" + uuid.uuid4().hex[:8]
        self._seen_evidence[key] = eid
        self.evidence.append(
            {
                "id": eid,
                "source_url": doc.url,
                "source_class": source_class,
                "retrieved_at": doc.retrieved_at,
                "content_sha256": doc.sha256,
                "claim_span": span or "",
            }
        )
        return eid

    def evidence_for_bulk(self, span: str) -> str | None:
        """Bulk registry claims are anchored in the frozen bulk file, not a per-company request."""
        import identity

        meta = identity.bulk_snapshot()
        key = meta["source_url"] + "|bulk"
        if key in self._seen_evidence:
            return self._seen_evidence[key]
        eid = "ev-bulk"
        self._seen_evidence[key] = eid
        self.evidence.append(
            {
                "id": eid,
                "source_url": meta["source_url"],
                "source_class": "official_registry_bulk",
                "retrieved_at": meta["retrieved_at"],
                "content_sha256": meta["content_sha256"],
                "claim_span": span[:400],
            }
        )
        return eid

    # ---- claims -----------------------------------------------------------------------------
    def claim(
        self,
        field: str,
        value,
        *,
        doc: Doc | None = None,
        span: str = "",
        source_class: str = "official_registry",
        confidence: float = 1.0,
        period: str | None = None,
        note: str | None = None,
        bulk: bool = False,
        extra_evidence: list[str] | None = None,
    ) -> None:
        if value in (None, "", [], {}):
            raise ValueError(f"{self.org}: refusing to publish an empty claim for {field}")
        eid = self.evidence_for_bulk(span) if bulk else self.evidence_for(doc, span, source_class)
        ids = [i for i in ([eid] + (extra_evidence or [])) if i]
        if not ids:
            self.record_failed(field, "no evidence could be attached")
            return
        c: dict = {
            "field": field,
            "value": value,
            "availability": "available",
            "confidence": round(confidence, 3),
            "evidence_ids": ids,
        }
        if period:
            c["reporting_period"] = period
        if note:
            c["note"] = note
        self.claims.append(c)

    def record(self, field: str, availability: str, why: str = "", checked: str | None = None) -> None:
        if availability not in STATES:
            raise ValueError(f"unknown availability state {availability}")
        c: dict = {"field": field, "availability": availability}
        if availability != "available":
            c["value"] = None
        if why:
            c["reason"] = why
        if checked:
            c["checked_source"] = checked
        self.claims.append(c)

    def record_not_available(self, field: str, checked: str) -> None:
        self.record(field, "not_available", "the official source was queried and returned no record", checked)

    def record_failed(self, field: str, why: str) -> None:
        self.record(field, "failed", why)
        self.errors.append({"field": field, "error": why})

    def count_request(self, cost: float = 0.0) -> None:
        self.requests += 1
        self.third_party_cost += cost

    # ---- envelope ---------------------------------------------------------------------------
    def envelope(self) -> dict:
        return {
            "organisation_number": self.org,
            "run": {
                "run_id": self.run_id,
                "started_at": self.started_iso,
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "terminal_status": "completed",
            },
            "claims": self.claims,
            "evidence": self.evidence,
            "changes": [],
            "errors": self.errors,
            "operations": {
                "requests": self.requests,
                "runtime_ms": int((time.time() - self.started) * 1000),
                "third_party_cost_usd": round(self.third_party_cost, 4),
            },
        }


def summary(envelope: dict) -> dict:
    """Coverage by field, the number a submission is judged on. Printing it is the point."""
    by_field: dict[str, dict] = {}
    for c in envelope.get("claims", []):
        f = c["field"]
        s = by_field.setdefault(f, {"available": 0, "not_available": 0, "other": 0})
        st = c.get("availability", "")
        if st == "available":
            s["available"] += 1
        elif st == "not_available":
            s["not_available"] += 1
        else:
            s["other"] += 1
    return {
        "organisation_number": envelope.get("organisation_number"),
        "claims_total": sum(s["available"] for s in by_field.values()),
        "fields_present": len([s for s in by_field.values() if s["available"]]),
        "by_field": by_field,
        "evidence_records": len(envelope.get("evidence", [])),
        "requests": envelope.get("operations", {}).get("requests"),
        "runtime_ms": envelope.get("operations", {}).get("runtime_ms"),
    }


if __name__ == "__main__":
    r = Record("123456789")
    d = Doc(url="https://example.no/", status=200, body=b"Example AS, organisation number 123 456 789", retrieved_at="2026-01-01T00:00:00Z")
    d.__post_init__()
    r.claim("official_website", "https://example.no/", doc=d, span="Example AS, organisation number", source_class="company_owned")
    r.record_not_available("employee_count", "https://data.brreg.no/enhetsregisteret/api/enheter/123456789")
    r.record_failed("annual_accounts", "request timed out")
    env = r.envelope()
    assert env["claims"][0]["evidence_ids"], "an available claim must carry evidence"
    assert env["claims"][1]["value"] is None, "absence must never carry a value"
    assert all(c.get("evidence_ids") for c in env["claims"] if c["availability"] == "available")
    s = summary(env)
    assert s["claims_total"] == 1 and s["fields_present"] == 1, s
    try:
        r.claim("email", "", doc=d)
        raise AssertionError("empty claim should have raised")
    except ValueError:
        pass
    print("claims self-test OK: evidence required, absence kept as absence, coverage counted")
