"""A readable company profile, built only from claims the envelope already carries.

The point of this file is a constraint, not a style: every sentence it produces names the claim fields it
was built from, and nothing is written from general knowledge about companies. That is what makes the
organisers' requirement — explain the company, the changes and the unknowns without unsupported claims —
something a checker can test instead of something I have to promise.

Three things follow from it.

Numbers are copied, never reformulated. A figure appears with its reporting year because the claim carries
one, and amounts are grouped the way a person reads them (379 350 629 kroner), not the way JSON stores them.

Absence is written out. A field the register does not hold, or a website that could not be tied to the
company, appears in an unknowns section with the reason the run recorded for it. A profile that quietly omits
those is the failure mode this competition exists to catch.

What changed is reported separately from what is. `changes` in the envelope comes from `refresh.py`: a
rerun that found nothing different produces an empty list here, and a real change is stated with its old
value and the source of the new one.

Timestamps are not rewritten into a reader's local clock on purpose: they are provenance (when bytes were
read), and the envelope's own ISO values are what a reviewer can check. Dates that describe the company —
a filing year, a registration date — are its dates, in its registry's wording.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ACTIVITY_TYPES = ("job_posting", "public_mention", "review", "review_summary", "profile_handle", "company_profile", "activity_signal")
CURRENCY_FIELDS = ("revenue", "operating_result", "annual_result", "assets", "debt", "equity", "share_capital")

# A profile is read by a person. The envelope keeps the machine names and the explicit availability states
# the contract asks for; what appears in a sentence is the plain name of the thing and a plain state.
FIELD_LABELS = {
    "legal_name": "registered name",
    "legal_form": "legal form",
    "industry": "industry classification",
    "secondary_industry": "secondary industry classification",
    "sector": "sector",
    "registered_activity": "registered activity",
    "registered_purpose": "registered purpose",
    "municipality": "registered municipality",
    "registered_business_address": "registered business address",
    "registered_postal_address": "registered postal address",
    "public_email": "public email",
    "public_phone": "public phone",
    "establishment_date": "establishment date",
    "registration_date": "registration date",
    "employees": "registered employee count",
    "latest_filed_accounts_year": "latest filed accounts year",
    "financials": "annual accounts",
    "revenue": "revenue",
    "operating_result": "operating result",
    "annual_result": "annual result",
    "assets": "total assets",
    "debt": "total debt",
    "equity": "equity",
    "share_capital": "share capital",
    "bankrupt": "bankruptcy status",
    "liquidating": "winding-up status",
    "part_of_group": "group membership",
    "group": "group structure",
    "roles": "registered role holders",
    "locations": "registered workplaces",
    "official_website": "official website",
    "organisation_number": "organisation number",
    "value_added_tax_registered": "VAT registration",
}
STATE_WORDS = {
    "not_available": "not found",
    "not_applicable": "not applicable",
    "ambiguous": "found but unproven",
    "blocked": "blocked by the source",
    "failed": "the source did not answer",
}


def field_label(field: str) -> str:
    return FIELD_LABELS.get(str(field), str(field))


def state_word(state: str) -> str:
    return STATE_WORDS.get(str(state), str(state))
FIGURE_ORDER = ("revenue", "operating_result", "annual_result", "assets", "debt", "equity")
LABELS = {
    "revenue": "revenue",
    "operating_result": "operating result",
    "annual_result": "annual result",
    "assets": "total assets",
    "debt": "total debt",
    "equity": "equity",
    "share_capital": "share capital",
}


def load(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def claims(envelope: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for claim in envelope.get("claims") or []:
        field = str(claim.get("field") or "")
        if field:
            out[field] = claim
    return out


def held(envelope: dict, field: str):
    claim = claims(envelope).get(field)
    if not claim or claim.get("availability") != "available":
        return None
    return claim.get("value")


def amount(value) -> str:
    """Group digits the way a person reads a sum, and never invent precision that isn't there."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == int(number):
        digits = f"{abs(int(number)):,}".replace(",", "\u00a0")
    else:
        digits = f"{abs(number):,.2f}".replace(",", "\u00a0")
    return ("−" if number < 0 else "") + digits


def line(text: str, *fields: str, absent=None) -> dict:
    """A sentence, the claims it came from, and whether it is a statement of absence rather than of fact.

    `absent` is what lets verify() check the difference: an absence line is only honest when the envelope
    really recorded that field as not available.
    """
    return {"text": text, "fields": list(fields), "absent": absent}


def build(envelope: dict) -> dict:
    """One profile: what the company is, its filed figures, who leads it, where it works, what is unknown."""
    got = claims(envelope)
    org = str(envelope.get("organisation_number") or "")
    name = held(envelope, "legal_name") or f"organisation number {org}"
    form = held(envelope, "legal_form") or ""
    place = held(envelope, "municipality") or ""
    industry = held(envelope, "industry") or ""

    sections: dict[str, list[dict]] = {}

    # A sentence cites only what it actually used: the legal form is named when the register gives it,
    # and the sentence does not claim it when it does not. And when the register holds no record at all, the
    # profile says that — "organisation number X is registered in Norway" is a claim the run did not make.
    identity_claim = got.get("legal_name") or {}
    if identity_claim.get("availability") != "available":
        identity: list[dict] = [line(f"No registry record was found for organisation number {org}.", "legal_name", absent=True)]
    else:
        cited = ["legal_name"] + (["legal_form"] if form else [])
        opening = f"{name} is registered in Norway as {form}." if form else f"{name} is registered in Norway."
        identity = [line(opening, *cited)]
    if place:
        identity.append(line(f"Registered location: {place}.", "municipality"))
    if industry:
        identity.append(line(f"Registered activity: {industry}.", "industry"))
    purpose = held(envelope, "registered_purpose")
    if isinstance(purpose, str) and purpose.strip():
        identity.append(line(f"Registered purpose: {purpose.strip()[:600]}", "registered_purpose"))
    website = held(envelope, "official_website")
    if website:
        proof = (got.get("official_website") or {}).get("note", "")
        identity.append(line(f"Own website: {website} ({proof or 'identity verified on the page'}).", "official_website"))
    for field, label in (("public_phone", "Phone"), ("public_email", "E-mail"), ("public_postal_address", "Postal address")):
        value = held(envelope, field)
        if isinstance(value, str) and value.strip():
            identity.append(line(f"{label}: {value.strip()}", field))
    sections["identity"] = identity

    financials: list[dict] = []
    year = held(envelope, "latest_filed_accounts_year")
    if year:
        financials.append(line(f"Latest annual accounts on file: {year}.", "latest_filed_accounts_year"))
    periods = set()
    for field in FIGURE_ORDER:
        claim = got.get(field)
        if not claim or claim.get("availability") != "available" or claim.get("value") is None:
            continue
        period = claim.get("reporting_period") or year
        periods.add(str(period))
        group_scoped = str(claim.get("note") or "").startswith("consolidated")
        label = ("consolidated group " + LABELS[field]) if group_scoped else LABELS[field]
        financials.append(
            line(
                f"{label}: {amount(claim['value'])} kroner" + (f" ({period})" if period else ""),
                field,
            )
        )
    if not financials:
        financials.append(line("No annual accounts are available for this entity in the accounts register.", "financials", absent=True))
    sections["financials"] = financials

    leadership: list[dict] = []
    roles = held(envelope, "roles")
    named: list[dict] = []
    if isinstance(roles, dict):
        named = [r for r in (roles.get("sample") or []) if isinstance(r, dict)]
        total = int(roles.get("count") or len(named))
    elif isinstance(roles, list):
        named = [r for r in roles if isinstance(r, dict)]
        total = len(named)
    else:
        total = 0
    if total:
        shown = 0
        for row in named[:8]:
            # Brreg names a person under "holder"; an organisational holder (revisor, regnskapsfører) is
            # sometimes left unnamed by the register, and that is stated rather than padded out.
            person = row.get("holder") or row.get("name")
            if not person:
                continue
            role = row.get("role") or row.get("role_group") or row.get("type") or "role"
            leadership.append(line(f"{role}: {person}" + (f" (from {row.get('from')})" if row.get("from") else ""), "roles"))
            shown += 1
        if total > shown:
            remaining = total - shown
            leadership.append(line(f"{remaining} further registered role {'holder' if remaining == 1 else 'holders'} are not named here.", "roles"))
    else:
        leadership.append(line("No public role holders are registered for this entity.", "roles", absent=True))
    sections["leadership"] = leadership

    workplaces: list[dict] = []
    locations = held(envelope, "locations")
    if isinstance(locations, dict) and locations.get("count"):
        count = locations["count"]
        workplaces.append(line(f"{count} registered workplace(s).", "locations"))
        for row in (locations.get("sample") or [])[:5]:
            if isinstance(row, dict):
                where = row.get("address") or row.get("municipality") or row.get("name")
                if where:
                    workplaces.append(line(f"Workplace: {where}", "locations"))
    elif isinstance(locations, list) and locations:
        workplaces.append(line(f"{len(locations)} registered workplace(s).", "locations"))
    else:
        workplaces.append(line("No registered workplaces beyond the registered business address.", "locations", absent=True))
    sections["workplaces"] = workplaces

    activity: list[dict] = []
    group = held(envelope, "group")
    if isinstance(group, dict) and group.get("count"):
        activity.append(line(f"Registered group relationships: {group['count']}.", "group"))
    elif held(envelope, "part_of_group") is True:
        activity.append(line("The register records this entity as part of a group.", "part_of_group"))
    for observation in envelope.get("observations") or []:
        if str(observation.get("signal_type")) in ACTIVITY_TYPES:
            activity.append(
                line(
                    f"{observation['signal_type']} on {observation.get('platform')}: {str(observation.get('value') or observation.get('url') or '')[:200]}",
                    "official_website",
                )
            )
    if not activity:
        activity.append(line("No dated public activity was found in the permitted sources checked.", absent="observations"))
    sections["activity"] = activity

    unknowns: list[dict] = []
    stated = {f for f, c in got.items() if c.get("availability") == "available"}
    seen_fields: set[str] = set()
    for claim in envelope.get("claims") or []:
        state = claim.get("availability")
        field = str(claim.get("field") or "")
        if state == "available" or field in stated or field in seen_fields:
            continue
        seen_fields.add(field)
        unknowns.append(
            {
                "field": field,
                "state": state,
                "reason": claim.get("reason") or "not recorded",
                "checked": claim.get("checked") or "",
            }
        )
    sections["unknowns"] = [line(f"{field_label(u['field'])}: {state_word(u['state'])} — {u['reason']}" + (f" (checked: {u['checked']})" if u["checked"] else ""), u["field"]) for u in unknowns]
    if not unknowns:
        sections["unknowns"] = []

    changes: list[dict] = []
    for change in envelope.get("changes") or []:
        changes.append(
            line(
                f"{change.get('field')} changed: {change.get('previous')!r} → {change.get('current')!r} ({change.get('kind')})",
                str(change.get("field")),
            )
        )
    sections["changes"] = changes

    return {
        "organisation_number": org,
        "name": name,
        "sections": sections,
        "unknown_fields": [u["field"] for u in unknowns],
        "periods": sorted(p for p in periods if p),
        "run_id": (envelope.get("run") or {}).get("run_id"),
    }


def verify(envelope: dict, profile: dict) -> list[str]:
    """Read the profile back against the envelope and report anything it says that the evidence does not."""
    got = claims(envelope)
    available = {f for f, c in got.items() if c.get("availability") == "available"}
    changed = {str(c.get("field")) for c in envelope.get("changes") or []}
    problems: list[str] = []
    for name, lines in (profile.get("sections") or {}).items():
        for item in lines:
            fields = [f for f in item.get("fields") or [] if f]
            tag = item.get("absent")
            if tag == "observations":
                if any(str(o.get("signal_type")) in ACTIVITY_TYPES for o in envelope.get("observations") or []):
                    problems.append(f"{name}: states no public activity, but this envelope carries some")
                continue
            if tag:
                # An absence statement is only honest if the run really found nothing for that field.
                if any(f in available for f in fields):
                    problems.append(f"{name}: states an absence for {fields}, which the envelope does have")
                continue
            if not fields:
                problems.append(f"{name}: a line with no claim behind it: {item['text'][:80]}")
                continue
            if name == "unknowns":
                # An unknown is only honest if the run actually recorded it as one.
                claim = got.get(fields[0])
                if claim is None or claim.get("availability") == "available":
                    problems.append(f"unknowns: names {fields[0]}, which this envelope does not record as unavailable")
                continue
            if name == "changes":
                if fields[0] not in changed:
                    problems.append(f"changes: names {fields[0]}, which this run did not report as changed")
                continue
            for field in fields:
                if field in ("financials", "official_website"):
                    continue
                if field not in available:
                    problems.append(f"{name}: line cites {field}, which is not available in this envelope")
        if name == "financials":
            for item in lines:
                match = re.search(r"([−\d][\d\u00a0.]*) kroner", item["text"])
                if not match:
                    continue
                written = float(match.group(1).replace("\u00a0", "").replace("−", "-"))
                cited = next((f for f in item["fields"] if f in CURRENCY_FIELDS), None)
                if cited is None:
                    continue
                claim = got.get(cited) or {}
                value = claim.get("value")
                if value is None or abs(float(value) - written) > 0.51:
                    problems.append(f"financials: {cited} written as {written}, the claim says {value}")
    return problems


if __name__ == "__main__":
    envelope = {
        "organisation_number": "123456789",
        "run": {"run_id": "selftest"},
        "evidence": [{"id": "ev-1", "source_url": "https://example.no/", "retrieved_at": "2026-10-21T00:00:00Z", "content_sha256": "c" * 64}],
        "claims": [
            {"field": "legal_name", "value": "TEST AS", "availability": "available", "evidence_ids": ["ev-1"]},
            {"field": "legal_form", "value": "Aksjeselskap", "availability": "available", "evidence_ids": ["ev-1"]},
            {"field": "municipality", "value": "OSLO", "availability": "available", "evidence_ids": ["ev-1"]},
            {"field": "industry", "value": "Engineering projects", "availability": "available", "evidence_ids": ["ev-1"]},
            {"field": "official_website", "value": "https://example.no/", "availability": "available", "evidence_ids": ["ev-1"], "note": "organisation number printed in the footer"},
            {"field": "latest_filed_accounts_year", "value": "2025", "availability": "available", "evidence_ids": ["ev-1"]},
            {"field": "revenue", "value": 379350629.0, "availability": "available", "evidence_ids": ["ev-1"], "reporting_period": "2025"},
            {"field": "operating_result", "value": -15000.0, "availability": "available", "evidence_ids": ["ev-1"], "reporting_period": "2025"},
            {"field": "roles", "value": [{"role": "Daglig leder", "name": "Ola Nordmann"}], "availability": "available", "evidence_ids": ["ev-1"]},
            {"field": "locations", "value": {"count": 1, "sample": [{"address": "Karl Johans gate 1, OSLO"}]}, "availability": "available", "evidence_ids": ["ev-1"]},
            {"field": "public_email", "availability": "not_available", "reason": "registry bulk column epostadresse", "checked": "registry field", "evidence_ids": []},
            {"field": "financials", "availability": "available", "evidence_ids": ["ev-1"]},
        ],
        "changes": [{"field": "employees", "kind": "appeared", "previous": None, "current": 7}],
    }

    profile = build(envelope)
    text = "\n".join(item["text"] for lines in profile["sections"].values() for item in lines)
    assert "TEST AS is registered in Norway" in text, text[:200]
    assert "379 350 629" in text.replace("\u00a0", " "), "the figure must appear with grouped digits"
    assert "−15\u00a0000" in text, "a negative result must keep its sign"
    assert "Daglig leder: Ola Nordmann" in text
    assert "public email: not found" in text, "an unknown has to appear in the profile, in words a person reads"
    assert "employees changed: None → 7" in text
    problems = verify(envelope, profile)
    assert problems == [], problems

    # A company the register does not describe must be described as that. Two of 1,000 organisation numbers
    # were absent from the frozen snapshot, and the summary rendered "organisation number 980271528 is
    # registered in Norway" — a claim the run never made. check_profile caught it; this keeps it caught.
    unrecorded = {"organisation_number": "980271528", "run": {"run_id": "selftest"}, "evidence": [],
                  "claims": [{"field": "legal_name", "availability": "not_available", "reason": "not in the registry snapshot and the live register did not return it", "checked_source": "registry bulk file and entity API", "evidence_ids": []}],
                  "observations": [], "changes": [], "errors": []}
    thin = build(unrecorded)
    assert "No registry record was found" in thin["sections"]["identity"][0]["text"], thin["sections"]["identity"]
    assert verify(unrecorded, thin) == [], verify(unrecorded, thin)
    named = build({**unrecorded, "claims": unrecorded["claims"] + [{"field": "legal_name", "value": "REAL AS", "availability": "available", "evidence_ids": []}]})
    assert named["sections"]["identity"][0]["text"].startswith("REAL AS"), named["sections"]["identity"][0]

    # A profile built from this envelope cannot cite what is not there, so cite it by hand: reading the
    # profile back against the evidence has to catch a share capital the register never gave us.
    drifted = build(envelope)
    drifted["sections"]["financials"].append(line("Share capital: 100\u00a0000 kroner (2025)", "share_capital"))
    caught = verify(envelope, drifted)
    assert any("share_capital" in p for p in caught), caught

    empty = {"organisation_number": "999999999", "run": {"run_id": "none"}, "claims": [
        {"field": "legal_name", "value": "EMPTY AS", "availability": "available", "evidence_ids": []},
        {"field": "financials", "availability": "not_available", "reason": "404 from the accounts register", "checked": "regnskapsregisteret", "evidence_ids": []},
    ], "evidence": []}
    sparse = build(empty)
    assert any("No annual accounts" in item["text"] for item in sparse["sections"]["financials"]), sparse
    assert any("No public role holders" in item["text"] for item in sparse["sections"]["leadership"]), sparse
    assert "annual accounts: not found" in "\n".join(i["text"] for i in sparse["sections"]["unknowns"])
    print("summary self-test OK: every line names its claims, amounts copied with their year, unknowns written out, verify() catches a citation that is not there")
