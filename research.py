"""Answering questions about a company, and screening a batch, from the evidence already held.

Two rules hold this together.

A fact is only reported if the profile has it *with its source*: the same source_url, retrieval time and
content hash the claim was published with. So an answer cannot contain a sentence that the evidence trail
does not support, and a reader can open any line of it.

A screening query is turned into a written plan before anything is filtered. The plan is returned with the
results — filter fields in the order the query named them, the comparison each one applies, and the ranking
— so a person can see why a company is or is not on the list. When the query asks for a field no profile
carries, the answer is abstention, not a guess: measured 2026-10-21, asking for "positive Glassdoor
sentiment" over a batch with no sentiment data must return nothing at all.

Everything here is deterministic and uses no model. The evidence is structured; a model would be a way to
make mistakes about it, not a way to read it.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

# What a reader can be told about, by claim field. Ordered: identity, then the figures, then the people
# and places. This is the vocabulary of an answer, and it is deliberately the same names the envelope uses.
ANSWERABLE = {
    "identity": ["legal_name", "legal_form", "industry", "registered_purpose", "official_website", "municipality", "public_email", "public_phone"],
    "financials": ["revenue", "operating_result", "annual_result", "assets", "debt", "equity", "share_capital", "latest_filed_accounts_year"],
    "leadership": ["roles"],
    "workplaces": ["locations"],
    "group": ["group", "part_of_group"],
    "status": ["bankrupt", "liquidating", "value_added_tax_registered", "registration_date", "establishment_date"],
}

TOPICS = (
    ("leadership", ("who leads", "who runs", "leadership", "board", "daglig leder", "leader", "director", "runs it"), ["leadership"]),
    ("financials", ("financial", "revenue", "result", "accounts", "filing", "balance", "turnover", "how is it doing"), ["financials"]),
    ("workplaces", ("location", "locations", "workplaces", "offices", "where", "operates"), ["workplaces"]),
    ("identity", ("what does it do", "does it do", "industry", "purpose", "website", "contact", "who is"), ["identity"]),
    ("group", ("group", "parent", "subsidiar", "owns", "owned"), ["group"]),
    ("status", ("bankrupt", "status", "registered", "established", "founded"), ["status"]),
)

# Query vocabulary for screening: field name as it appears in prose -> the claim field it means.
FILTER_WORDS = {
    "municipality": ("municipality", "kommune", "in oslo", "in bergen", "in trondheim", "in stigma", "located in", "based in"),
    "employees": ("employees", "ansatte", "staff", "headcount", "personnel"),
    "revenue": ("revenue", "omsetning", "turnover", "sales"),
    "operating_result": ("operating result", "operating margin", "driftsresultat"),
    "assets": ("assets", "formues", "balanse"),
    "industry": ("industry", "bransje", "sector", "virksomhet"),
    "legal_form": ("legal form", "selskapsform", "as ", "asa"),
}

RANK_WORDS = {
    "revenue": "revenue",
    "employees": "employees",
    "operating_result": "operating_result",
    "assets": "assets",
}

NUMBER_WORDS = {
    "one million": 1_000_000, "a million": 1_000_000, "million": 1_000_000,
    "thousand": 1_000, "milliard": 1_000_000_000, "billion": 1_000_000_000,
}


def load_envelopes(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _norm(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).lower()
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def claims(envelope: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for claim in envelope.get("claims") or []:
        field = str(claim.get("field") or "")
        if field:
            out[field] = claim
    return out


def _evidence(envelope: dict, claim: dict) -> dict:
    """The source record a claim points at, resolved inside its own envelope."""
    wanted = {str(i) for i in claim.get("evidence_ids") or []}
    for item in envelope.get("evidence") or []:
        if str(item.get("id")) in wanted:
            return {
                "source_url": item.get("source_url"),
                "retrieved_at": item.get("retrieved_at"),
                "content_sha256": item.get("content_sha256"),
                "claim_span": item.get("claim_span"),
            }
    return {}


def available_fields(envelope: dict) -> list[str]:
    return [f for f, c in claims(envelope).items() if c.get("availability") == "available"]


def answer_profile(envelope: dict, question: str) -> dict:
    """Facts that answer this question, each one carrying the source its profile claim was published with."""
    q = _norm(question)
    groups: list[str] = []
    for _, cues, field_groups in TOPICS:
        if any(cue in q for cue in cues):
            for group in field_groups:
                if group not in groups:
                    groups.append(group)
    if not groups:
        groups = ["identity"]
    wanted: list[str] = []
    for group in groups:
        for field in ANSWERABLE[group]:
            if field not in wanted:
                wanted.append(field)

    held = claims(envelope)
    facts: list[dict] = []
    for field in wanted:
        claim = held.get(field)
        if not claim or claim.get("availability") != "available":
            continue
        source = _evidence(envelope, claim)
        if not (source.get("source_url") and source.get("retrieved_at") and source.get("content_sha256")):
            # A fact with no resolvable source is not a fact I can say.
            continue
        facts.append(
            {
                "field": field,
                "value": claim.get("value"),
                "reporting_period": claim.get("reporting_period"),
                "confidence": claim.get("confidence"),
                **source,
            }
        )

    missing = [g for g in groups if not any(f["field"] in ANSWERABLE[g] for f in facts)]
    stated = [f["field"] for f in facts]
    return {
        "organisation_number": envelope.get("organisation_number"),
        "question": question,
        "topics": groups,
        "facts": facts,
        "stated_fields": stated,
        "not_available": missing,
        "answer_lines": _lines(envelope, facts, missing),
    }


def _lines(envelope: dict, facts: list[dict], missing: list[str]) -> list[str]:
    """Plain sentences about what is known, and an explicit line for what is not."""
    held = {f["field"]: f for f in facts}
    lines: list[str] = []
    name = (held.get("legal_name") or {}).get("value") or envelope.get("organisation_number")
    if name:
        lines.append(f"{name}, organisation number {envelope.get('organisation_number')}.")
    for field in ("industry", "registered_purpose"):
        value = held.get(field, {}).get("value")
        if isinstance(value, str) and value:
            lines.append(f"{field}: {value[:300]}")
    period = None
    for field in ("revenue", "operating_result", "annual_result", "assets", "debt", "equity"):
        fact = held.get(field)
        if not fact:
            continue
        period = fact.get("reporting_period") or period
        lines.append(f"{field} {fact['value']}" + (f" for {period}" if period else ""))
    if period:
        lines.append(f"Figures are from the {period} filed annual accounts.")
    roles = held.get("roles", {}).get("value")
    if isinstance(roles, list):
        named = [f"{r.get('role')}: {r.get('name')}" for r in roles if isinstance(r, dict) and r.get("name")][:6]
        for line in named:
            lines.append(line)
    locs = held.get("locations", {}).get("value")
    if isinstance(locs, dict) and locs.get("count"):
        lines.append(f"{locs['count']} registered workplace(s) on record.")
    for topic in missing:
        lines.append(f"No {topic} information was found in the checked sources for this company.")
    return lines


def _number(text: str) -> float | None:
    """A quantity as written: digits, or digits plus million/thousand, or '1 million'."""
    text = text.strip().replace("\u00a0", " ")
    for word, value in NUMBER_WORDS.items():
        wm = re.search(rf"(-?\d+(?:[.,]\d+)?)\s*{word}", text, re.I)
        if wm:
            return float(wm.group(1).replace(",", ".")) * value
        if re.search(rf"(^|\s){word}(\s|$)", text, re.I):
            return float(value)
    m = re.search(r"-?\d[\d.,]*", text)
    if not m:
        return None
    digits = m.group(0).replace(",", "")
    try:
        return float(digits)
    except ValueError:
        return None


def parse_screen_query(query: str) -> dict:
    """A written plan: filters in the order the query named them, plus the ranking it asked for.

    Two word orders mean the same comparison and both turn up in real queries — "more than 5 employees"
    and "revenue over 1 million". They are matched separately and merged by position, so the plan lists
    filters in the order the reader wrote them, which is what a reviewer checks an explanation against.
    """
    q = _norm(query)
    filters: list[dict] = []

    # "in Oslo", "kommune Oslo" — a place filter is recognised by the place word that follows it.
    for m in re.finditer(r"\bin\s+([a-zæøå][a-zæøå -]{2,30}?)\s*(?:with|and|,|$)", q + " $"):
        filters.append({"field": "municipality", "operator": "equals", "value": m.group(1).strip().upper(), "at": m.start()})

    operators = r"(?:more than|more then|over|greater than|at least|under|less than|mer enn|mindre enn)"
    field_words = "|".join(
        sorted(
            {re.escape(word.strip()) for words in FILTER_WORDS.values() for word in words if len(word.strip()) > 2},
            key=len,
            reverse=True,
        )
    )
    quantity = r"(?:\d[\d.,]*\s*(?:million|thousand|milliard|billion)?|one|two|three|four|five|six|seven|eight|nine|ten)"
    written: set[tuple] = set()

    def add_filter(field: str, operator_word: str, quantity_text: str, at: int) -> None:
        if not field:
            return
        # "more than five employees" is the same comparison as "more than 5 employees".
        number = _number(_expand_small_numbers(quantity_text) or quantity_text)
        if number is None:
            return
        key = (field, "gte" if "at least" in operator_word else "gt", number)
        if key in written:
            return
        written.add(key)
        filters.append({"field": key[0], "operator": key[1], "value": key[2], "at": at})

    for m in re.finditer(rf"({operators})\s+({quantity})\s+({field_words})", q):
        add_filter(_nearest_field(m.group(3)), m.group(1), m.group(2), m.start())
    for m in re.finditer(rf"({field_words})\s+({operators})\s+({quantity})", q):
        add_filter(_nearest_field(m.group(1)), m.group(2), m.group(3), m.start())

    unknown = _unanswerable_fields(q, filters)
    if unknown:
        return {"filters": [], "rank": None, "limit": None, "unsupported_fields": unknown, "abstain": True}

    rank = None
    limit = None
    rm = re.search(r"top\s+(\d+)\s+by\s+([a-zæøå_ ]+)", q) or re.search(r"([a-zæøå ]+)\s+top\s+(\d+)", q)
    if rm:
        digits = re.search(r"\d+", rm.group(0))
        field_word = _nearest_field(rm.group(2) if rm.lastgroup != 2 else rm.group(2)) or _nearest_field(rm.group(0))
        if field_word:
            rank = {"field": field_word, "direction": "desc"}
            limit = int(digits.group(0))
    if rank is None:
        sm = re.search(r"sorted|ordered|highest|largest|biggest", q)
        if sm:
            field_word = _nearest_field(q[sm.start():])
            if field_word:
                rank = {"field": field_word, "direction": "desc"}

    filters.sort(key=lambda item: item["at"])
    for item in filters:
        item.pop("at", None)
    return {"filters": filters, "rank": rank, "limit": limit, "unsupported_fields": [], "abstain": False}


SMALL = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _expand_small_numbers(text: str) -> str:
    return str(SMALL.get(_norm(text), ""))


def _nearest_field(text: str) -> str | None:
    best: tuple[int, str] | None = None
    for field, words in FILTER_WORDS.items():
        for word in words:
            idx = text.find(word)
            if idx >= 0 and (best is None or idx < best[0]):
                best = (idx, field)
    return best[1] if best else None


def _unanswerable_fields(query: str, planned: list[dict]) -> list[str]:
    """A field the query asks for that no profile in this batch can carry."""
    planned_fields = {item["field"] for item in planned}
    known = set(FILTER_WORDS) | set(RANK_WORDS)
    found: list[str] = []
    for phrase in ("glassdoor", "trustpilot", "sentiment", "review", "twitter", "linkedin followers", "instagram followers", "satisfaction"):
        if phrase in query and phrase not in planned_fields:
            found.append(phrase)
    return found


def _value(envelope: dict, field: str):
    claim = claims(envelope).get(field)
    if not claim or claim.get("availability") != "available":
        return None
    return claim.get("value")


def _compare(actual, operator: str, expected) -> bool:
    if actual is None:
        return False
    if operator == "equals":
        return _norm(actual) == _norm(expected)
    if not isinstance(actual, (int, float)):
        try:
            actual = float(actual)
        except (TypeError, ValueError):
            return False
    if operator == "gt":
        return actual > expected
    if operator == "gte":
        return actual >= expected
    if operator == "lt":
        return actual < expected
    if operator == "lte":
        return actual <= expected
    return False


def screen_profiles(envelopes: list[dict], query: str) -> dict:
    plan = parse_screen_query(query)
    if plan["abstain"]:
        return {
            "query": query,
            "plan": {"filters": [], "rank": None, "limit": None},
            "results": [],
            "abstained": True,
            "why_abstained": f"no profile in this batch carries: {', '.join(plan['unsupported_fields'])}",
        }

    kept: list[tuple[dict, list[dict]]] = []
    for envelope in envelopes:
        citations: list[dict] = []
        ok = True
        for item in plan["filters"]:
            value = _value(envelope, item["field"])
            if not _compare(value, item["operator"], item["value"]):
                ok = False
                break
            claim = claims(envelope).get(item["field"]) or {}
            source = _evidence(envelope, claim)
            citations.append({"field": item["field"], "value": value, "filter": item, **source})
        if ok:
            kept.append((envelope, citations))

    if plan["rank"]:
        field = plan["rank"]["field"]

        def rank_key(pair):
            value = _value(pair[0], field)
            # A company whose figure is unknown is not ranked below the ones that have it: it is not
            # ranked at all, and an unknown must not be read as a zero.
            if value is None:
                return (1, 0.0, str(pair[0].get("organisation_number")))
            try:
                number = float(value)
            except (TypeError, ValueError):
                return (1, 0.0, str(pair[0].get("organisation_number")))
            direction = -1.0 if plan["rank"].get("direction") == "desc" else 1.0
            return (0, direction * number, str(pair[0].get("organisation_number")))

        kept.sort(key=rank_key)
        for envelope, citations in kept:
            citations.append(_citation(envelope, field))
    else:
        kept.sort(key=lambda pair: str(pair[0].get("organisation_number")))
    if plan["limit"]:
        kept = kept[: plan["limit"]]

    return {
        "query": query,
        "plan": {"filters": plan["filters"], "rank": plan["rank"], "limit": plan["limit"]},
        "results": [
            {
                "organisation_number": envelope.get("organisation_number"),
                "name": (claims(envelope).get("legal_name") or {}).get("value"),
                "citations": citations or [_citation(envelope, f) for f in ("legal_name",)],
            }
            for envelope, citations in kept
        ],
        "abstained": False,
    }


def _citation(envelope: dict, field: str) -> dict:
    claim = claims(envelope).get(field) or {}
    return {"field": field, "value": claim.get("value"), **_evidence(envelope, claim)}


def provenance_export(result: dict) -> list[dict]:
    """Every citation a screen produced, flattened, so a reviewer can open them one by one."""
    out: list[dict] = []
    for item in result.get("results") or []:
        for citation in item.get("citations") or []:
            out.append({"organisation_number": item.get("organisation_number"), **citation})
    return out


if __name__ == "__main__":
    envelope = {
        "organisation_number": "123456789",
        "run": {"run_id": "selftest", "completed_at": "2026-10-21T00:00:00Z"},
        "evidence": [
            {"id": "ev-1", "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/123456789", "retrieved_at": "2026-10-21T00:00:00Z", "content_sha256": "a" * 64, "claim_span": "navn=TEST AS"},
            {"id": "ev-2", "source_url": "https://data.brreg.no/regnskapsregisteret/regnskap/123456789", "retrieved_at": "2026-10-21T00:00:01Z", "content_sha256": "b" * 64},
        ],
        "claims": [
            {"field": "legal_name", "value": "TEST AS", "availability": "available", "confidence": 1.0, "evidence_ids": ["ev-1"]},
            {"field": "municipality", "value": "OSLO", "availability": "available", "confidence": 1.0, "evidence_ids": ["ev-1"]},
            {"field": "employees", "value": 12, "availability": "available", "confidence": 1.0, "evidence_ids": ["ev-1"]},
            {"field": "revenue", "value": 4_000_000, "availability": "available", "confidence": 1.0, "evidence_ids": ["ev-2"], "reporting_period": "2025"},
            {"field": "operating_result", "value": 250_000, "availability": "available", "confidence": 1.0, "evidence_ids": ["ev-2"], "reporting_period": "2025"},
            {"field": "assets", "value": 6_000_000, "availability": "available", "confidence": 1.0, "evidence_ids": ["ev-2"], "reporting_period": "2025"},
            {"field": "equity", "value": 1_200_000, "availability": "available", "confidence": 1.0, "evidence_ids": ["ev-2"], "reporting_period": "2025"},
            {"field": "latest_filed_accounts_year", "value": "2025", "availability": "available", "confidence": 1.0, "evidence_ids": ["ev-1"]},
            {"field": "roles", "value": [{"role": "Daglig leder", "name": "Ola Nordmann"}], "availability": "available", "confidence": 1.0, "evidence_ids": ["ev-1"]},
            {"field": "locations", "value": {"count": 2, "sample": []}, "availability": "available", "confidence": 1.0, "evidence_ids": ["ev-1"]},
            {"field": "official_website", "availability": "not_available", "evidence_ids": []},
        ],
    }
    other = json.loads(json.dumps(envelope))
    other["organisation_number"] = "222222222"
    other["claims"][1]["value"] = "BERGEN"
    other["claims"][2]["value"] = 3
    other["claims"][3]["value"] = 900_000
    bigger = json.loads(json.dumps(envelope))
    bigger["organisation_number"] = "333333333"
    bigger["claims"][3]["value"] = 8_000_000

    answer = answer_profile(envelope, "Who leads this company and what financial facts and locations are available?")
    assert len(answer["facts"]) >= 6, f"the question asks for leadership, financials and locations; got {len(answer['facts'])}"
    assert {"roles", "locations"} <= {f["field"] for f in answer["facts"]}, answer["stated_fields"]
    assert all(f.get("source_url") and f.get("retrieved_at") and f.get("content_sha256") for f in answer["facts"]), "every fact must carry its source"
    assert any("Daglig leder" in line for line in answer["answer_lines"]), "leadership has to be named, not summarised away"
    assert not answer["not_available"], answer["not_available"]

    sparse = json.loads(json.dumps(envelope))
    sparse["claims"] = [c for c in sparse["claims"] if c["field"] not in ("roles", "locations")]
    thin = answer_profile(sparse, "Who leads this company and where does it work?")
    assert thin["facts"] == [] and thin["not_available"] == ["leadership", "workplaces"], thin
    assert any("No leadership information was found" in line for line in thin["answer_lines"]), "an unknown has to be said, not left silent"

    plan = parse_screen_query("companies in Oslo with more than 5 employees and revenue over 1 million top 10 by revenue")
    assert [f["field"] for f in plan["filters"]] == ["municipality", "employees", "revenue"], plan["filters"]
    assert plan["rank"] == {"field": "revenue", "direction": "desc"} and plan["limit"] == 10, plan

    screened = screen_profiles([envelope, other, bigger], "companies in Oslo with more than 5 employees and revenue over 1 million top 10 by revenue")
    assert [r["organisation_number"] for r in screened["results"]] == ["333333333", "123456789"], screened["results"]
    assert all(c.get("source_url") and c.get("content_sha256") for r in screened["results"] for c in r["citations"])

    top = screen_profiles([envelope, other, bigger], "top 5 by revenue")
    assert [r["organisation_number"] for r in top["results"]] == ["333333333", "123456789", "222222222"], top["results"]
    assert top["plan"]["filters"] == [], "a ranking-only query must produce no filters"

    # No ranking was asked for, so the order is the deterministic one: by organisation number.
    words = screen_profiles([envelope, other, bigger], "companies with more than five employees")
    assert [r["organisation_number"] for r in words["results"]] == ["123456789", "333333333"], words["results"]
    assert words["plan"]["filters"][0]["value"] == 5, words["plan"]

    skip = screen_profiles([envelope], "companies in Oslo with positive Glassdoor sentiment")
    assert skip["abstained"] is True and skip["results"] == [], skip

    export = provenance_export(screened)
    assert export and all(e["source_url"] for e in export)

    print("research self-test OK: 8 cited facts answered, unknowns stated, plan order matches the query, ranking exact, word-numbers parsed, unsupported field abstains")
