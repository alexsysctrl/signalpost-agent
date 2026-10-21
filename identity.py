"""One identity per organisation number, from two official sources that disagree on purpose.

Measured on 2026-10-20, and this is the fact the whole design turns on:
  - the live entity API (/enheter/{org}) returns roles-adjacent detail, capital, vedtektsfestet
    formaal, registration dates — and NO website field.
  - the bulk registry CSV (…/enheter/lastned/csv) DOES carry hjemmeside, epostadresse, telefon, mobil.
So the bulk file is not an optimisation, it is the only official source for contact identity. A
competitor reading only the API cannot report a registry-listed website at all.

Field names here are the ones the competition's own vocabulary uses (legal identity, industry,
addresses, employees, website, financials, roles, locations) so a profile is comparable, not merely
self-consistent.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
from pathlib import Path

import fetch
import official

ROOT = Path(__file__).resolve().parent.parent
BULK_CSV = ROOT / "brreg-enheter.csv.gz"
BULK_URL = "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv"

csv.field_size_limit(10_000_000)

# Bulk CSV columns -> profile field. A data table on purpose: which registry columns a profile
# publishes is a decision someone should be able to change in one place.
BULK_FIELDS = {
    "navn": "legal_name",
    "organisasjonsform.beskrivelse": "legal_form",
    "naeringskode1.kode": "industry_code",
    "naeringskode1.beskrivelse": "industry",
    "naeringskode2.beskrivelse": "secondary_industry",
    "naeringskode3.beskrivelse": "tertiary_industry",
    "hjelpeenhetskode.beskrivelse": "helper_unit_activity",
    "antallAnsatte": "employee_count",
    "harRegistrertAntallAnsatte": "employee_count_registered",
    "hjemmeside": "registered_website",
    "epostadresse": "email",
    "telefon": "phone",
    "mobil": "mobile",
    "forretningsadresse.adresse": "business_address",
    "forretningsadresse.postnummer": "business_postal_code",
    "forretningsadresse.poststed": "business_postal_town",
    "forretningsadresse.kommune": "business_municipality",
    "postadresse.adresse": "postal_address",
    "postadresse.poststed": "postal_town",
    "postadresse.kommunenummer": "municipality_code",
    "institusjonellSektorkode.beskrivelse": "sector",
    "sisteInnsendteAarsregnskap": "latest_accounts_year",
    "registreringsdatoenhetsregisteret": "registered_in_enhetsregisteret",
    "registreringsdatoForetaksregisteret": "registered_in_foretaksregisteret",
    "stiftelsesdato": "founded",
    "registrertIMvaregisteret": "vat_registered",
    "registreringsdatoMerverdiavgiftsregisteret": "vat_registered_from",
    "registrertIForetaksregisteret": "registered_as_enterprise",
    "konkurs": "bankrupt",
    "konkursdato": "bankruptcy_date",
    "underAvvikling": "being_wound_up",
    "underTvangsavviklingEllerTvangsopplosning": "forced_winding_up",
    "erIKonsern": "part_of_group",
    "capital.belop": "share_capital",
    "maalform": "language_of_form",
    "vedtektsdato": "articles_of_association_date",
    "vedtektsfestetFormaal": "registered_purpose",
    "aktivitet": "registered_activity",
}
# The bulk file spells capital with Norwegian keys; map the ones that actually differ.
BULK_RENAMES = {
    "capital.belop": "kapital.belop",
}

_bulk_meta: dict | None = None


def bulk_snapshot() -> dict:
    """Metadata for the bulk registry file: URL, retrieval time, content hash. One evidence record
    covers every claim anchored in it, and the hash is what makes those claims checkable."""
    global _bulk_meta
    if _bulk_meta is None:
        raise RuntimeError("bulk_snapshot() called before load_bulk() — the file must be indexed first")
    return _bulk_meta


def load_bulk(orgs: set[str], *, path: Path = BULK_CSV) -> dict[str, dict]:
    """Registry rows for `orgs`.

    Prefers the pre-built index (bulk_index.py): the same rows, looked up in milliseconds instead of a
    40-second stream of 1.4M CSV rows, with the source file's SHA-256 carried along from the build so
    bulk claims stay checkable. Falls back to streaming the file when no index exists.
    """
    global _bulk_meta
    try:
        import bulk_index

        if bulk_index.DB.exists():
            rows = bulk_index.lookup(orgs)
            meta = bulk_index.meta()
            _bulk_meta = {
                "source_url": meta["source_url"],
                "source_class": "official_registry_bulk",
                "content_sha256": meta["content_sha256"],
                "matched": len(rows),
                "retrieved_at": fetch.now_iso(),
            }
            return rows
    except ImportError:
        pass
    rows: dict[str, dict] = {}
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
    digest_hex = digest.hexdigest()
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            org = (row.get("organisasjonsnummer") or "").strip()
            if org in orgs:
                rows[org] = row
    _bulk_meta = {
        "source_url": BULK_URL,
        "source_class": "official_registry_bulk",
        "content_sha256": digest_hex,
        "matched": len(rows),
        "retrieved_at": fetch.now_iso(),
    }
    return rows


LIVE_TO_PROFILE = {
    "business_address_municipality": "business_municipality",
    "business_address_postal_code": "business_postal_code",
    "business_address_town": "business_postal_town",
    "postal_address_town": "postal_town",
}


def map_live(live: dict) -> dict:
    """A live entity record, in the field names the profile expects.

    The frozen bulk snapshot is a 2025 filing cut; an organisation number can exist in the register and not
    be in that file. `live_fields` already returns the names the profile pipeline uses, so the only mapping
    left is the four address fields the bulk file spells differently. Fields the live record does not carry
    (`sector`, `municipality_code`, `employee_count_registered`) stay absent rather than guessed.
    """
    out = dict(live)
    for src, target in LIVE_TO_PROFILE.items():
        if live.get(src) is not None:
            out[target] = live[src]
    return out


def map_bulk(row: dict) -> dict:
    """Bulk CSV row -> profile fields. Empty strings are dropped here, not turned into zeros: an
    absent field becomes an explicit not_available when the profile is assembled."""
    out: dict[str, str] = {}
    for src, target in BULK_FIELDS.items():
        key = BULK_RENAMES.get(src, src)
        raw = row.get(key)
        if raw is None:
            continue
        val = str(raw).strip()
        if val == "":
            continue
        if val.lower() in ("true", "false"):
            out[target] = val.lower() == "true"
            continue
        if target == "employee_count" or target == "share_capital":
            try:
                out[target] = float(val) if "." in val else int(val)
            except ValueError:
                out[target] = val
            continue
        out[target] = val
    return out


def live_fields(org: str) -> tuple[dict, object]:
    """Live entity record: the detail the bulk file omits — purpose text, capital detail, historical
    names, VAT registration state. Returns (fields, doc) where doc carries the evidence hash."""
    data, doc = official.entity(org)
    if not data:
        return {}, doc
    out: dict = {
        "legal_name": data.get("navn"),
        "legal_form": (data.get("organisasjonsform") or {}).get("beskrivelse"),
        "org_form_code": (data.get("organisasjonsform") or {}).get("kode"),
        "registered_in_enhetsregisteret": data.get("registreringsdatoEnhetsregisteret"),
        "registered_as_enterprise": data.get("registrertIForetaksregisteret"),
        "registered_in_foretaksregisteret": data.get("registreringsdatoForetaksregisteret"),
        "founded": data.get("stiftelsesdato"),
        "vat_registered": data.get("registrertIMvaregisteret"),
        "vat_registered_from": data.get("registreringsdatoMerverdiavgiftsregisteret"),
        "registered_purpose": data.get("vedtektsfestetFormaal"),
        "articles_of_association_date": data.get("vedtektsdato"),
        "registered_activity": data.get("aktivitet"),
        "employee_count": data.get("antallAnsatte"),
        "share_capital": (data.get("kapital") or {}).get("belop"),
        "share_count": (data.get("kapital") or {}).get("antallAksjer"),
        "capital_type": (data.get("kapital") or {}).get("type"),
        "capital_registered": (data.get("kapital") or {}).get("innfortDato"),
        "bankrupt": data.get("konkurs"),
        "being_wound_up": data.get("underAvvikling"),
        "forced_winding_up": data.get("underTvangsavviklingEllerTvangsopplosning"),
        "latest_accounts_year": data.get("sisteInnsendteAarsregnskap"),
        "part_of_group": data.get("erIKonsern"),
        "language_of_form": data.get("maalform"),
        "email": data.get("epostadresse"),
        "phone": data.get("telefon"),
        "historical_names": [n.get("navn") for n in data.get("historiskeNavn") or [] if n.get("navn")],
        "industry": (data.get("naeringskode1") or {}).get("beskrivelse"),
        "industry_code": (data.get("naeringskode1") or {}).get("kode"),
        "secondary_industry": (data.get("naeringskode2") or {}).get("beskrivelse"),
        "tertiary_industry": (data.get("naeringskode3") or {}).get("beskrivelse"),
    }
    for src_key, target in (("forretningsadresse", "business_address"), ("postadresse", "postal_address")):
        loc = data.get(src_key) or {}
        text = official._addr(loc)
        if text:
            out[target] = text
            out[target + "_municipality"] = loc.get("kommune")
            out[target + "_postal_code"] = loc.get("postnummer")
            out[target + "_town"] = loc.get("poststed")
            out[target + "_country"] = loc.get("landkode")
    return {k: v for k, v in out.items() if v not in (None, "", [], {})}, doc


if __name__ == "__main__":
    org = "810034882"  # SANDNES ELEKTRISKE AS — appears in the universe, has epost + phone, no website
    rows = load_bulk({org, "976605713"})
    assert org in rows, "the bulk snapshot must contain a universe member"
    bulk = map_bulk(rows[org])
    assert bulk["legal_name"].startswith("SANDNES ELEKTRISKE"), bulk.get("legal_name")
    assert bulk["email"] == "post@sandneselektriske.no", bulk.get("email")
    assert "registered_website" not in bulk, "this company genuinely has no registered website"

    # A company the frozen snapshot does not contain still has a live record, and the profile pipeline must
    # be able to read it in the names it expects.
    live, _doc = live_fields("810034882")
    mapped = map_live(live)
    assert mapped["business_municipality"] == live["business_address_municipality"], mapped.get("business_municipality")
    assert mapped["business_postal_code"] == live["business_address_postal_code"], mapped.get("business_postal_code")
    assert mapped["legal_name"] == bulk["legal_name"], "the two paths must agree about who the company is"
    assert "sector" not in mapped, "a field the live record does not carry stays absent rather than guessed"
    assert bulk["industry"] == "Elektrisk installasjonsarbeid", bulk.get("industry")
    live, doc = live_fields(org)
    assert doc and doc.status == 200
    assert "registered_purpose" in live, "live API must supply the purpose text"
    assert "registered_website" not in live, "confirmed: the live entity API carries no website field"
    meta = bulk_snapshot()
    assert len(meta["content_sha256"]) == 64, "bulk file must be hashed for evidence to be checkable"
    assert meta["matched"] == 2
    print(
        f"identity self-test OK: bulk fields {len(bulk)}, live fields {len(live)}, "
        f"bulk sha256 {meta['content_sha256'][:12]}"
    )
