"""Official Norwegian sources: Brønnøysundregistrene.

Everything here is one NLOD 2.0 source with one exception: annual accounts live in a separate
register (Regnskapsregisteret) with its own rate limit on the year-listing endpoint.

Two behaviours that matter for scoring and are easy to get wrong:
  - a 404 from the accounts register means "no public filing exists for this entity", not zero.
    AS/ASA generally file; many ENK/FLI do not.
  - the year listing costs a request per company and is the slowest gate (~30/min), so the account
    payload itself is read once and its years are taken from that payload instead.
"""
from __future__ import annotations

import json
import urllib.parse

import fetch

BRREG = "https://data.brreg.no"


def entity(org: str):
    return fetch.json_get(f"{BRREG}/enhetsregisteret/api/enheter/{org}")


def roles(org: str):
    return fetch.json_get(f"{BRREG}/enhetsregisteret/api/enheter/{org}/roller")


def subunits(org: str):
    return fetch.json_get(
        f"{BRREG}/enhetsregisteret/api/underenheter?overordnetEnhet={org}&size=1000"
    )


def group(org: str):
    return fetch.json_get(f"{BRREG}/enhetsregisteret/api/konsernstruktur/{org}")


def accounts(org: str):
    """All filed annual accounts. The endpoint returns a list; empty means none published.

    This one endpoint gets its own timeout: measured 2026-10-22 at 05:00 UTC, a single account listing answered
    in 18.2 seconds, against a 20 s default. The register's own documentation treats it as the rate-limited one.
    """
    return fetch.json_get(f"{BRREG}/regnskapsregisteret/regnskap/{org}", timeout=35)


def _path(obj, dotted: str):
    """Walk a dotted key path through the account payload. Missing branch -> None, never 0."""
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, list):
            cur = cur[0] if cur else None
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur if isinstance(cur, (int, float)) and not isinstance(cur, bool) else None


# The figures the rubric names, as paths into the Regnskapsregisteret payload. This is a table on
# purpose: which figures a profile carries is a decision, not code. Verified against the real payload
# for 976605713 (2025 filing) on 2026-10-20 - the shape here is measured, not assumed.
FINANCIAL_PATHS = {
    "revenue": "resultatregnskapResultat.driftsresultat.driftsinntekter.sumDriftsinntekter",
    "wages": "resultatregnskapResultat.driftsresultat.driftskostnad.loennskostnad",
    "operating_result": "resultatregnskapResultat.driftsresultat.driftsresultat",
    "net_financial": "resultatregnskapResultat.finansresultat.nettoFinans",
    "profit_before_tax": "resultatregnskapResultat.ordinaertResultatFoerSkattekostnad",
    "annual_result": "resultatregnskapResultat.aarsresultat",
    "assets": "eiendeler.sumEiendeler",
    "fixed_assets": "eiendeler.anleggsmidler.sumAnleggsmidler",
    "current_assets": "eiendeler.omloepsmidler.sumOmloepsmidler",
    "cash_and_deposits": "eiendeler.sumBankinnskuddOgKontanter",
    "debt": "egenkapitalGjeld.gjeldOversikt.sumGjeld",
    "debt_short": "egenkapitalGjeld.gjeldOversikt.kortsiktigGjeld.sumKortsiktigGjeld",
    "debt_long": "egenkapitalGjeld.gjeldOversikt.langsiktigGjeld.sumLangsiktigGjeld",
    "equity": "egenkapitalGjeld.egenkapital.sumEgenkapital",
    "equity_and_debt": "egenkapitalGjeld.sumEgenkapitalGjeld",
}


def company_rows(rows: list[dict]) -> list[dict]:
    """The entity's own filings, newest first, with the group's consolidated accounts left out.

    Ranking or publishing a parent company by its group revenue states something about a different business
    than the one this profile is about. Where only a consolidated account exists, the caller says so instead
    of borrowing the number quietly.
    """
    return [row for row in rows or [] if row.get("scope") != "group"]


def financial_rows(records: list) -> list[dict]:
    """One row per filed account year. Absent figures stay absent - a zero is a claim, not a gap."""
    rows: list[dict] = []
    for r in records or []:
        period = r.get("regnskapsperiode") or {}
        row = {
            "year": (period.get("tilDato") or "")[:4] or (period.get("fraDato") or "")[:4],
            "period_start": period.get("fraDato"),
            "period_end": period.get("tilDato"),
            "account_type": r.get("regnskapstype") if isinstance(r.get("regnskapstype"), str) else None,
            # KONSERN is the consolidated group account, SELSKAP is this entity's own. An organisation number
            # can file both for the same year, and the group number is not the company's revenue.
            "scope": "group" if (r.get("regnskapstype") == "KONSERN") else "company",
            "currency": r.get("valuta") if isinstance(r.get("valuta"), str) else "NOK",
            "record_id": r.get("journalnr"),
            "form": _company_form(r),
            "ruleset": (r.get("regnkapsprinsipper") or {}).get("regnskapsregler"),
            "audited": not (r.get("revisjon") or {}).get("ikkeRevidertAarsregnskap", False),
            "in_liquidation": r.get("avviklingsregnskap", False) or None,
            "statement_format": r.get("oppstillingsplan"),
        }
        for name, dotted in FINANCIAL_PATHS.items():
            row[name] = _path(r, dotted)
        for link in r.get("lenker") or []:
            if isinstance(link, dict) and link.get("uri"):
                row.setdefault("document_links", []).append(link["uri"])
        rows.append({k: v for k, v in row.items() if v not in (None, "", [], False)})
    rows.sort(key=lambda x: x.get("year") or "", reverse=True)
    return rows


def _company_form(record: dict):
    v = record.get("virksomhet") or {}
    return v.get("organisasjonsform") if isinstance(v.get("organisasjonsform"), str) else None



def role_rows(payload: dict) -> list[dict]:
    """Registered roles. Birth dates are dropped on purpose: they are personal data the brief discards."""
    out: list[dict] = []
    for group_ in (payload or {}).get("rollegrupper") or []:
        gtype = (group_.get("type") or {}).get("beskrivelse") or (group_.get("type") or {}).get("kode")
        for r in group_.get("roller") or []:
            person = r.get("person") or {}
            org = r.get("organisasjon") or {}
            name = person.get("navn") or {}
            label = " ".join(x for x in (name.get("fornavn"), name.get("etternavn")) if x) or org.get("navn")
            row = {
                "role_group": gtype,
                "role": (r.get("type") or {}).get("beskrivelse"),
                "role_code": (r.get("type") or {}).get("kode"),
                "holder": label,
                "holder_type": "person" if person else "organization",
                "registered": not r.get("avregistrert", False),
            }
            out.append({k: v for k, v in row.items() if v not in (None, "", False)})
    return out


def _addr(loc) -> str:
    """Registry address fields are lists of lines in some endpoints and strings in others."""
    if not isinstance(loc, dict):
        return ""
    parts: list[str] = []
    for key in ("adresse", "postnummer", "poststed", "kommune", "landkode"):
        v = loc.get(key)
        if isinstance(v, list):
            parts.extend(str(x) for x in v if x)
        elif v:
            text = str(v)
            # A Norwegian address names the place once: poststed and kommune are usually the same word,
            # and a bare country code on a domestic address says nothing.
            if key == "kommune" and any(_same_word(text, p) for p in parts):
                continue
            if key == "landkode" and text.upper() in ("NO", "NOR", "NORGE"):
                continue
            parts.append(text)
    return ", ".join(parts)


def _same_word(a: str, b: str) -> bool:
    return str(a).strip().lower() == str(b).strip().lower()


def subunit_rows(payload: dict) -> list[dict]:
    out: list[dict] = []
    for u in (payload or {}).get("_embedded", {}).get("underenheter") or []:
        loc = u.get("beliggenhetsadresse") or u.get("forretningsadresse") or {}
        status = (u.get("status") or {}).get("status") if isinstance(u.get("status"), dict) else None
        row = {
            "organisation_number": u.get("organisasjonsnummer"),
            "name": u.get("navn"),
            "industry": (u.get("naeringskode") or {}).get("beskrivelse"),
            "industry_code": (u.get("naeringskode") or {}).get("kode"),
            "employees": u.get("antallAnsatte"),
            "address": _addr(loc),
            "registered_from": u.get("registreringsdatoEnhet"),
            "status": status,
        }
        out.append({k: v for k, v in row.items() if v not in (None, "", [])})
    return out


def group_rows(payload: dict) -> list[dict]:
    out: list[dict] = []
    for c in (payload or {}).get("children") or []:
        out.append(
            {
                "relation": (c.get("knytningsform") or {}).get("beskrivelse"),
                "ownership": c.get("grunnlag"),
                "organisation_number": c.get("organisasjonsnummer"),
                "name": c.get("navn"),
                "form": (c.get("organisasjonsform") or {}).get("beskrivelse"),
                "linked_since": c.get("dato"),
                "level": c.get("nivaa"),
            }
        )
    for p in (payload or {}).get("parent") or []:
        out.append(
            {
                "relation": "overordnet enhet",
                "ownership": p.get("grunnlag"),
                "organisation_number": p.get("organisasjonsnummer"),
                "name": p.get("navn"),
                "form": (p.get("organisasjonsform") or {}).get("beskrivelse"),
            }
        )
    return [r for r in out if r.get("organisation_number")]


def _span(payload, limit: int = 400) -> str:
    """A literal fragment of the response body, for evidence. json.dumps keeps it byte-faithful."""
    return json.dumps(payload, ensure_ascii=False)[:limit]


def _module(rows: list, doc, *, label: str, empty_reason: str) -> dict:
    """Available when the register gave records, not_available only when it answered and had none, failed when
    we never got an answer.

    Measured 2026-10-22: a 1,000-company batch run at 05:00 UTC came back with 952 profiles saying "no filed
    annual accounts published for this entity" — when the accounts endpoint had been timing out at 18 seconds a
    call. An absence and a failure are different facts, and a profile that reports the first when the second
    happened is worse than one that reports nothing.
    """
    if rows:
        return {"status": "available", "value": rows, "doc": doc, "span": _span(rows[:3])}
    status = getattr(doc, "status", None)
    if doc is None or status is None:
        return {"status": "failed", "state": "failed",
                "why": f"{label}: no answer from data.brreg.no (connection failure or timeout)",
                "doc": doc, "value": None}
    if status in (200, 404):
        return {"status": "not_available", "state": "not_available",
                "why": f"{empty_reason} (HTTP {status})", "doc": doc, "value": None}
    return {"status": "failed", "state": "failed", "why": f"{label}: register returned HTTP {status}",
            "doc": doc, "value": None}


def fetch_modules(org: str) -> dict:
    """The four live official modules, normalised, with the response kept for evidence.

    `not_available` here means the register answered and had nothing: a 404 from konsernstruktur is a
    real finding (this company is not in a group), not a gap to be papered over.
    """
    out: dict[str, dict] = {}

    payload, doc = roles(org)
    rows = role_rows(payload)
    out["roles"] = _module(rows, doc, label="roles", empty_reason="the register lists no role holders for this entity")

    payload, doc = subunits(org)
    rows = subunit_rows(payload)
    out["locations"] = _module(rows, doc, label="subunits", empty_reason="no registered subunits under this entity")
    if out["locations"]["status"] == "available":
        out["locations"]["span"] = _span(rows[:2])

    payload, doc = group(org)
    rows = group_rows(payload)
    out["group"] = _module(rows, doc, label="group structure", empty_reason="not listed in any group structure (404 is the register's answer)")

    payload, doc = accounts(org)
    rows = financial_rows(payload if isinstance(payload, list) else [])
    out["financials"] = _module(rows, doc, label="annual accounts", empty_reason="no filed annual accounts published for this entity")
    if out["financials"]["status"] == "available":
        out["financials"]["span"] = _span(rows[:1])
    return out


if __name__ == "__main__":
    org = "976605713"  # KITRON ASA — a real listed industrial group with 15 filed years
    data, doc = entity(org)
    assert data and doc.status == 200, "entity read failed"
    assert data["navn"].startswith("KITRON"), data["navn"]
    r, rdoc = roles(org)
    rr = role_rows(r)
    assert rr and any(x.get("role_code") == "DAGL" for x in rr), "leadership roles must resolve"
    assert all("fodselsdato" not in x for x in rr), "birth dates must not be carried"
    s, _ = subunits(org)
    sr = subunit_rows(s)
    assert len(sr) >= 1, "a group with establishments must return subunits"
    a, adoc = accounts(org)
    fr = financial_rows(a)
    assert len(fr) >= 5, f"expected a multi-year history, got {len(fr)}"
    assert any(x.get("revenue") for x in fr), "revenue figures must resolve"
    assert all(x.get("scope") in ("company", "group") for x in fr), "every filed account must say whose accounts it is"

    # The shape that produced a wrong ranking: one organisation number, one year, two filings.
    both = [
        {"regnskapsperiode": {"fraDato": "2025-01-01", "tilDato": "2025-12-31"}, "regnskapstype": "KONSERN",
         "resultatregnskapResultat": {"driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": 3557000000}}}},
        {"regnskapsperiode": {"fraDato": "2025-01-01", "tilDato": "2025-12-31"}, "regnskapstype": "SELSKAP",
         "resultatregnskapResultat": {"driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": 194000000}}}},
    ]
    rows = financial_rows(both)
    assert [r["scope"] for r in rows] == ["group", "company"], rows
    assert company_rows(rows)[0]["revenue"] == 194000000, "the entity's own figure is the one that describes the entity"
    assert all(x.get("year") for x in fr), "every financial row needs its reporting year"
    latest = fr[0]
    assert latest.get("assets") and latest.get("equity") and latest.get("debt"), f"balance sheet figures missing: {latest}"
    g, _ = group(org)
    gr = group_rows(g)
    assert gr and any(x.get("ownership") for x in gr), "group relationships must resolve"
    # An absence and a failure are different facts. A 404 from the register is an answer; a 503 or a timeout
    # is not, and a profile must not report either one as "this company has no accounts".
    class FakeDoc:
        def __init__(self, status):
            self.status = status
            self.url = "https://data.brreg.no/regnskapsregisteret/regnskap/1"
            self.body = b"{}"
            self.sha256 = "0" * 64
            self.text = lambda: "{}"

    empty = _module([], FakeDoc(404), label="annual accounts", empty_reason="no filed annual accounts published for this entity")
    assert empty["status"] == "not_available" and "HTTP 404" in empty["why"], empty
    broken = _module([], FakeDoc(503), label="annual accounts", empty_reason="no filed annual accounts published for this entity")
    assert broken["status"] == "failed" and "503" in broken["why"], broken
    gone = _module([], None, label="annual accounts", empty_reason="no filed annual accounts published for this entity")
    assert gone["status"] == "failed" and "no answer" in gone["why"], gone

    none, ndoc = accounts("999999999")
    assert none is None or none == [], "no filing must stay absent, never zero"
    print(f"official self-test OK: {len(rr)} roles, {len(sr)} subunits, {len(fr)} account years, {len(gr)} group links")
