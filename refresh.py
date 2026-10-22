"""Material changes between a previous snapshot of a profile and the current one.

The output contract wants `changes` to mean something: a run that re-reads the same sources and reports
nothing changed must emit an empty list, and a run that finds a real difference must say which field,
what it was, what it is now, and where the new value came from. That is why the comparison is done on
claims by field name rather than on whole documents — a re-fetched page has a new sha256 and a new
timestamp every time, and none of that is a change to the company.

Nothing here decides whether a change matters to a reader; it reports what differs, with provenance.
"""
from __future__ import annotations

import json
from pathlib import Path

# Fields where a difference is a fact about the company, worth telling a reader about.
TRACKED_FIELDS = (
    "official_website",
    "legal_name",
    "employees",
    "registered_business_address",
    "registered_postal_address",
    "municipality",
    "latest_filed_accounts_year",
    "registered_purpose",
    "registered_activity",
    "share_capital",
    "bankrupt",
    "liquidating",
    "value_added_tax_registered",
    "part_of_group",
    "public_email",
    "public_phone",
)

# Availability moved but the value did not: a source went from reachable to blocked, or the reverse.
AVAILABILITY_CHANGES = "availability"


def load_previous(directory: str | Path | None, org: str) -> dict | None:
    """Read a prior envelope for this organisation number, if one was kept."""
    if not directory:
        return None
    root = Path(directory)
    for candidate in (root / f"{org}.json", root / "snapshots" / f"{org}.json"):
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
    for candidate in sorted(root.glob("*.jsonl")):
        for line in candidate.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(row.get("organisation_number")) == str(org):
                return row
    return None


def _claims_by_field(envelope: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for claim in envelope.get("claims") or []:
        field = str(claim.get("field") or "")
        if field:
            out[field] = claim
    return out


def _evidence_url(envelope: dict, claim: dict) -> str:
    ids = {str(i) for i in claim.get("evidence_ids") or []}
    for item in envelope.get("evidence") or []:
        if str(item.get("id")) in ids and item.get("source_url"):
            return str(item["source_url"])
    return ""


def same_value(left, right) -> bool:
    """Are these two records the same fact, or a different fact wearing a different shape?

    The register states some facts two ways: a purpose as one text with line breaks in the bulk file, and the
    identical text as a list of lines in the API; an employee count as "14" in one and 14 in the other. A diff
    that compares values exactly reports a hundred "changes" when two builds of this agent recorded the same
    company differently — which is a claim about my code, not about Norway. Shape is normalised before anything
    is called a change.
    """
    def norm(value):
        if isinstance(value, (list, tuple)):
            return " ".join(str(part).strip() for part in value if str(part).strip())
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, (int, float)):
            return f"{value:g}"
        return " ".join(str(value or "").split())

    a, b = norm(left), norm(right)
    if not a and not b:
        return True  # two absences are the same state, and repeating one is not news
    if not a or not b:
        return False
    return a.lower() == b.lower()


def material_changes(previous: dict | None, current: dict) -> list[dict]:
    """Field-level differences between an earlier snapshot and this one."""
    if not previous:
        return []
    old = _claims_by_field(previous)
    new = _claims_by_field(current)
    changes: list[dict] = []
    for field in TRACKED_FIELDS:
        before, after = old.get(field), new.get(field)
        if before is None and after is None:
            continue
        before_value = before.get("value") if before else None
        after_value = after.get("value") if after else None
        before_state = (before or {}).get("availability")
        after_state = (after or {}).get("availability")
        # Equal availability and equal value is not a change, whatever that state is. An "ambiguous"
        # website finding stays ambiguous between runs, and reporting it as churn every day would make the
        # change list describe my diffing rather than the company.
        if before_state == after_state and _same(before_value, after_value):
            continue
        if before_state == "available" and after_state == "available":
            kind = "changed"
        elif before is None or before_state in (None, "not_available", "not_applicable"):
            if after_state != "available":
                continue
            kind = "appeared"
        elif after is None or after_state in (None, "not_available", "not_applicable"):
            if before_state != "available":
                continue
            kind = "gone"
        else:
            kind = AVAILABILITY_CHANGES
        changes.append(
            {
                "field": field,
                "kind": kind,
                "previous": before_value,
                "current": after_value,
                "previous_availability": before_state,
                "current_availability": after_state,
                "source_url": _evidence_url(current, after) if after else "",
                "previous_run_id": (previous.get("run") or {}).get("run_id"),
                "detected_at": (current.get("run") or {}).get("completed_at"),
            }
        )
    return changes


def _same(a, b) -> bool:
    """Compare values the way a reader would: a URL with or without a trailing slash is the same site, and the
    same text or number in a different shape is the same fact."""
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().rstrip("/").lower() == b.strip().rstrip("/").lower()
    return same_value(a, b)


def save_snapshot(directory: str | Path, org: str, envelope: dict) -> None:
    """Keep this run's envelope so the next run has something honest to compare against."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{org}.json").write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    shape_change = material_changes(
        {
            "claims": [
                {"field": "registered_activity", "availability": "available", "value": ["Boligsameie."]},
                {"field": "employees", "availability": "available", "value": "14"},
            ]
        },
        {
            "claims": [
                {"field": "registered_activity", "availability": "available", "value": "Boligsameie."},
                {"field": "employees", "availability": "available", "value": 14},
            ],
            "evidence": [],
        },
    )
    assert not shape_change, f"a value re-spelled by a different source is not a change: {shape_change}"

    base = {
        "organisation_number": "1234567",
        "run": {"run_id": "r1", "completed_at": "2026-10-20T00:00:00Z"},
        "evidence": [{"id": "ev-1", "source_url": "https://example.no/"}],
        "claims": [
            {"field": "official_website", "value": "https://example.no/", "availability": "available", "evidence_ids": ["ev-1"]},
            {"field": "employees", "value": 12, "availability": "available", "evidence_ids": ["ev-1"]},
            {"field": "public_phone", "availability": "not_available", "evidence_ids": []},
        ],
    }
    later = json.loads(json.dumps(base))
    later["run"] = {"run_id": "r2", "completed_at": "2026-10-21T00:00:00Z"}
    later["claims"][0]["value"] = "https://example.no/om-oss"
    later["claims"][1]["availability"] = "not_available"
    later["claims"][2] = {"field": "public_phone", "value": "+47 900 00 000", "availability": "available", "evidence_ids": ["ev-1"]}

    same = material_changes(base, json.loads(json.dumps(base)))
    assert same == [], f"an unchanged rerun must report nothing, got {same}"

    # A name-only match is a state a run keeps: a candidate was found and could not be proved. Measured
    # 2026-10-21, on 148 companies, my own diff reported one of these as a change on every rerun — churn
    # that described the diffing, not the company. It must stay silent, and moving to proved must not be
    # called "appeared", because there was a candidate before.
    unproven = {"organisation_number": "7654321", "run": {"run_id": "r1"}, "evidence": [{"id": "ev-1", "source_url": "https://example.no/"}],
                "claims": [{"field": "official_website", "value": None, "availability": "ambiguous", "reason": "name matches only", "evidence_ids": []}]}
    assert material_changes(unproven, json.loads(json.dumps(unproven))) == [], material_changes(unproven, json.loads(json.dumps(unproven)))
    proved = json.loads(json.dumps(unproven))
    proved["claims"][0] = {"field": "official_website", "value": "https://example.no/", "availability": "available", "evidence_ids": ["ev-1"]}
    gained = material_changes(unproven, proved)
    assert len(gained) == 1 and gained[0]["kind"] == "availability", gained
    assert gained[0]["previous_availability"] == "ambiguous" and gained[0]["current_availability"] == "available", gained
    moved = material_changes(base, later)
    kinds = {c["field"]: c["kind"] for c in moved}
    assert kinds == {"official_website": "changed", "employees": "gone", "public_phone": "appeared"}, kinds
    assert moved[0]["source_url"] == "https://example.no/", "a change has to name where the new value came from"
    # A URL that only gained a trailing slash is not a change.
    cosmetic = json.loads(json.dumps(base))
    cosmetic["claims"][0]["value"] = "https://example.no"
    assert material_changes(base, cosmetic) == [], "trailing slash is not a material change"
    print("refresh self-test OK: unchanged rerun reports nothing; three real changes reported with provenance")
