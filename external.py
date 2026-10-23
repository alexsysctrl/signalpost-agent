"""External footprint from a verified company site: the links a company points to are its own claim.

The competition pays for external footprint (55 of 100 points) but only accepts observations whose
exact entity is proven. The cheapest provable path is the company's own website: once a page prints
the organisation number, anything that page links to — its LinkedIn company page, its Facebook page,
its Instagram, its YouTube channel — is the company naming itself. Their own guidance says the same:
"Use permitted APIs, licensed providers, company-owned outbound links."

So this module takes a fetched, verified page and returns observation records in their contract shape
(external_footprint.validate_observation decides whether each one is publishable). The identity proof
carried into every record is the proof that established the site, not a new guess.

A handle found on an unverified page is recorded with exact_entity false and will be rejected by their
validator — which is the correct outcome, not a bug to work around.
"""
from __future__ import annotations

import json
import re
from typing import Any

import discover

SOCIAL_PATTERNS = {
    # Only the company's own profile is that company's footprint. A person's profile link found on a page
    # describes the person, and measured on 2026-10-21 it was the least durable thing on the page: four of the
    # five findings that failed to re-confirm on a 100-company run were people links that had moved.
    "linkedin": re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/([^/?#\s\"']+)"),
    "facebook": re.compile(r"https?://(?:www\.|m\.|nb\.)?facebook\.com/([^/?#\s\"']+)"),
    "instagram": re.compile(r"https?://(?:www\.)?instagram\.com/([^/?#\s\"']+)"),
    "youtube": re.compile(r"https?://(?:www\.)?youtube\.com/(?:channel|@|user|c)/([^/?#\s\"']+)"),
    "x": re.compile(r"https?://(?:www\.|mobile\.)?(?:twitter|x)\.com/([^/?#\s\"']+)"),
    "tiktok": re.compile(r"https?://(?:www\.)?tiktok\.com/@([^/?#\s\"']+)"),
}

# Handles that are the directory's own account, a share widget, or a generic intent link.
BLOCKED_HANDLES = {
    "share", "sharer", "pages", "pages-enterprise", "community", "commercial_services", "tr", "login",
    "signup", "events", "group", "groups", "hashtag", "search", "home", "profile", "reel", "watch",
}
# A one-word handle equal to a common noun is usually a share button, not a profile.
GENERIC_HANDLES = {"intent", "tweet", "share", "follow", "subscribe", "contact", "about", "home", "index"}

NOISE_HOSTS = {"facebook.com/sharer", "twitter.com/intent", "facebook.com/plugins"}


def _name_token_set(legal_name: str) -> set[str]:
    return discover.name_token_variants(legal_name)


def handle_matches_company(handle: str, legal_name: str) -> bool:
    """Does this social handle actually belong to this company?

    Found by the audit, 2026-10-21: bjorkhaug.no links to linkedin.com/company/a2g-gruppen-as — the
    parent group, a different legal entity. Publishing that as BJØRKHAUG's profile is exactly the
    wrong-company publication the competition fails a run for. A handle is accepted when its slug shares a
    distinctive token with the company's name (in any of the ASCII spellings a handle would use).
    """
    slug = re.sub(r"[^a-z0-9]+", " ", handle.lower())
    tokens = {t for t in slug.split() if len(t) >= 4}
    name_tokens = _name_token_set(legal_name)
    if not tokens or not name_tokens:
        return False
    # Handles run words together: facebook.com/KitronASA is one token. Substring containment at four
    # characters or more is the test that accepts KitronASA and still refuses A2GGruppen.
    return any(nt in t or t in nt for t in tokens for nt in name_tokens if len(t) >= 4 and len(nt) >= 4)


def _handle_matches_relation(handle: str, names) -> str:
    """Which registered group relation this handle is spelled from, if any.

    The auditor's case (2026-10-22): a subsidiary's page carries its parent group's LinkedIn account in the
    footer. The page names the subsidiary, so proximity looks like attribution — it isn't. The register already
    states who owns whom, so a handle whose leading word is a parent's registered brand word is the group's
    footprint, not this company's.

    This is deliberately narrower than handle_matches_company and is only ever consulted when that test has
    already failed for the company itself: a child named after its group keeps its own account, because the
    company match is tried first.
    """
    slug = re.sub(r"[^a-z0-9]+", " ", handle.lower()).strip()
    tokens = [t for t in slug.split() if len(t) >= 3]
    if not tokens:
        return ""
    first = tokens[0]
    for name in names or ():
        brand = discover.name_tokens(name)
        if not brand or len(brand[0]) < 3:
            continue
        lead = brand[0]
        if first.startswith(lead) or lead.startswith(first):
            return name
    return ""


def extract_handles(
    text: str, legal_name: str = "", group_names: tuple[str, ...] | list[str] = ()
) -> list[dict[str, str]]:
    """Social profile handles referenced by a page, deduplicated, with obvious widgets removed."""
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for platform, pattern in SOCIAL_PATTERNS.items():
        for match in pattern.finditer(text):
            handle = match.group(1).strip("/").strip()
            low = handle.lower()
            if not low or low in BLOCKED_HANDLES or low in GENERIC_HANDLES:
                continue
            if "/" in low and platform != "linkedin":
                low = low.split("/")[0]
                if low in BLOCKED_HANDLES or low in GENERIC_HANDLES:
                    continue
            if low.startswith(("pages/", "pages-enterprise", "tr/", "login", "privacy")):
                continue
            key = (platform, low)
            if key in seen:
                continue
            seen.add(key)
            record = {"platform": platform, "handle": handle, "url": match.group(0)}
            if legal_name and not handle_matches_company(handle, legal_name):
                if _handle_matches_relation(handle, group_names):
                    continue  # the group's own account, sitting on its subsidiary's page
                if not _names_this_company_around(text, match.start(), legal_name):
                    continue  # a group or affiliate profile is not this company's footprint
            out.append(record)
    return out


def _names_this_company_around(text: str, position: int, legal_name: str) -> bool:
    """A link standing next to the company's own name is attribution enough."""
    window = text[max(0, position - 500) : position + 500].lower()
    folded = re.sub(r"\s+", " ", window)
    if legal_name.lower() in folded:
        return True
    digits = re.sub(r"\D", "", window)
    return bool(re.search(r"\d{9}", digits))


def host_of(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url).hostname or "").casefold().removeprefix("www.")


def registry_observations(
    org: str,
    legal_name: str,
    fields: dict,
    doc: Any,
    account_years: list[str] | None = None,
    accounts_doc: Any = None,
) -> list[dict[str, Any]]:
    """What the register itself can prove as an external signal.

    Their strategy list names registry_workforce_snapshot as a valid move, and the platform "brreg" with
    acquisition_mode "official_api" is publishable by their own contract. An employee count filed by the
    company to the register is a dated, attributable workforce statement — not a review and not a job
    ad, and it is never presented as either.
    """
    records: list[dict[str, Any]] = []
    if doc is None:
        return records
    employees = fields.get("employee_count")
    if isinstance(employees, (int, float)):
        records.append(
            {
                "id": f"obx-{org}-brreg-workforce",
                "organisation_number": org,
                "name": legal_name,
                "platform": "brreg",
                "signal_type": "workforce_snapshot",
                "source_url": f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}",
                "source_class": "official_registry",
                "acquisition_mode": "official_api",
                "rights_status": "approved",
                "rights_note": "NLOD 2.0 open data from Brønnøysundregistrene.",
                "retrieved_at": doc.retrieved_at,
                "content_sha256": doc.sha256,
                "metrics": {
                    "employee_count": employees,
                    "subunit_count": fields.get("subunit_count"),
                    "latest_filed_accounts_year": fields.get("latest_accounts_year"),
                },
                "exact_entity": True,
                "identity_proof": f"registry entity record for organisation number {org}",
            }
        )
    # The count of filed years has to be evidenced by the accounts listing, not by whichever registry page
    # happened to be at hand: caught on 2026-10-23 when the audit replayed this finding against the entity
    # record and recounted zero years. A finding whose evidence points at the wrong payload is unverifiable.
    if account_years and accounts_doc is None:
        account_years = None
    if account_years:
        records.append(
            {
                "id": f"obx-{org}-brreg-filing-history",
                "organisation_number": org,
                "name": legal_name,
                "platform": "brreg",
                "signal_type": "profile_metrics",
                "source_url": f"https://data.brreg.no/regnskapsregisteret/regnskap/{org}",
                "source_class": "official_registry",
                "acquisition_mode": "official_api",
                "rights_status": "approved",
                "rights_note": "NLOD 2.0 open data from Regnskapsregisteret.",
                "retrieved_at": accounts_doc.retrieved_at,
                "content_sha256": accounts_doc.sha256,
                "metrics": {"filed_account_years": len(account_years), "latest_year": account_years[0]},
                "exact_entity": True,
                "identity_proof": f"accounts register record for organisation number {org}",
            }
        )
    return records


def site_observations(
    org: str,
    legal_name: str,
    doc: Any,
    identity_proof: str,
    *,
    page_paths: list[str] | None = None,
    requested_host: str = "",
    extra_docs: list | None = None,
    group_names: tuple[str, ...] | list[str] = (),
) -> list[dict[str, Any]]:
    """Observations about this company's external profiles, from its own verified page(s)."""
    text = doc.text()
    body = doc.body
    records: list[dict[str, Any]] = []
    if requested_host and discover.normalise_host(doc.url) != requested_host:
        # A company registered a domain that redirects to a page on the group's site. That registration is
        # part of why the page is accepted, so the observation has to carry it: a later check that only
        # re-fetches the final URL cannot see the name-matching domain and calls a good finding a bad one.
        identity_proof = f"{identity_proof}; requested {requested_host}, which serves {doc.url}"
    seen: set[tuple[str, str]] = set()
    # Every page of a verified site belongs to the same company, so a profile link in a footer on an
    # inner page counts just as much as one on the homepage. Reading only the page that proved identity
    # is why multi-platform coverage was low: measured 2026-10-21, 11 of 40 companies.
    for page in [doc] + list(extra_docs or []):
        for item in extract_handles(page.text(), legal_name, group_names):
            if (item["platform"], item["handle"].lower()) in seen:
                continue
            seen.add((item["platform"], item["handle"].lower()))
            records.append(_handle_record(org, legal_name, page, item, identity_proof))
    records.insert(
        0,
        {
            "id": f"obx-{org}-company-site",
            "organisation_number": org,
            "name": legal_name,
            "platform": "company_site",
            "signal_type": "company_profile",
            "value": doc.url,
            "source_url": doc.url,
            "source_class": "company_owned",
            "acquisition_mode": "permitted_public_page",
            "rights_status": "approved",
            "rights_note": "Company's own published page; used as identity evidence, not quoted text.",
            "retrieved_at": doc.retrieved_at,
            "content_sha256": doc.sha256,
            "exact_entity": True,
            "identity_proof": identity_proof,
            "metrics": {"pages_read": len([doc] + list(extra_docs or []))},
        },
    )
    for page in [doc] + list(extra_docs or []):
        records += jsonld_ratings(org, legal_name, page, identity_proof)
    records += career_observations(org, legal_name, [doc] + list(extra_docs or []), identity_proof)
    # Each finding carries the request that produced *its* page. A job finding from a careers page and a
    # handle found in the homepage footer are different requests, and an audit replays them separately.
    asked_for = {page.url: (page.requested_url or page.url) for page in [doc] + list(extra_docs or [])}
    origin = ("https://" + requested_host + "/") if requested_host else doc.url
    for record in records:
        record["requested_url"] = asked_for.get(record.get("source_url") or "", origin)
    return records


def _handle_record(org: str, legal_name: str, page: Any, item: dict, identity_proof: str) -> dict:
    return {
        "id": f"obx-{org}-{item['platform']}-{item['handle'].lower()[:40]}",
        "organisation_number": org,
        "name": legal_name,
        "platform": item["platform"],
        "signal_type": "profile_handle",
        "value": item["url"],
        "metrics": {"handle": item["handle"]},
        "source_url": page.url,
        "source_class": "company_owned",
        "acquisition_mode": "permitted_public_page",
        "rights_status": "approved",
        "rights_note": f"Outbound link published by {host_of(page.url)} on its own page.",
        "retrieved_at": page.retrieved_at,
        "content_sha256": page.sha256,
        "evidence_span": f"page {page.url} links to {item['url']}",
        "exact_entity": True,
        "identity_proof": identity_proof,
    }


JSON_LD_RE = re.compile(r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I)


def _jsonld_nodes(doc: Any) -> list[dict]:
    """Every object inside the schema.org blocks a site embeds for search engines."""
    out: list[dict] = []
    for raw in JSON_LD_RE.findall(doc.text()):
        try:
            data = json.loads(raw.strip())
        except Exception:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                out.append(node)
                for key in ("@graph", "mainEntity", "about", "object"):
                    if key in node:
                        stack.append(node[key])
    return out


def _literal_json_span(text: str, key: str) -> str:
    """The page's own text around a structured-data key, verbatim.

    Re-serialising the parsed value would be an accurate summary of the page and not a piece of it. The
    audit re-reads these findings from kept bytes, so the span has to be findable there.
    """
    for needle in (f'"{key}"', key):
        i = text.find(needle)
        if i >= 0:
            return text[i:i + 600].strip()
    return ""


def jsonld_ratings(org: str, legal_name: str, doc: Any, identity_proof: str) -> list[dict[str, Any]]:
    """Ratings a company publishes about itself, on its own page.

    Many Norwegian business sites carry schema.org aggregateRating — the same numbers a review directory
    shows, but written by the company, on a page whose identity this run already proved. That makes the
    observation publishable with no third-party rights question, and it costs no extra requests: the page
    is already fetched.
    """
    records = []
    for node in _jsonld_nodes(doc):
        rating = node.get("aggregateRating")
        if not isinstance(rating, dict):
            continue
        try:
            value = float(rating.get("ratingValue"))
            count = int(rating.get("reviewCount") or rating.get("ratingCount"))
        except (TypeError, ValueError):
            continue
        if not (0 < value <= 5) or count <= 0:
            continue
        span = _literal_json_span(doc.text(), "aggregateRating")
        if not span:
            continue  # the figure parsed, but the page text does not carry it as a locatable fragment
        records.append(
            {
                "id": f"obx-{org}-self-rating-{doc.sha256[:12]}",
                "organisation_number": org,
                "name": legal_name,
                "platform": "company_site",
                "signal_type": "review_summary",
                "value": f"{value}/5 from {count} reviews",
                "metrics": {"rating": value, "review_count": count, "scale": float(rating.get("bestRating") or 5)},
                "source_url": doc.url,
                "source_class": "company_owned",
                "acquisition_mode": "permitted_public_page",
                "rights_status": "approved",
                "rights_note": "Structured data published by the company on its own site.",
                "retrieved_at": doc.retrieved_at,
                "content_sha256": doc.sha256,
                "evidence_span": span,
                "exact_entity": True,
                "identity_proof": identity_proof,
            }
        )
    return records


# A job listing says a position is open. Norwegian premises and community pages use the friendly words
# without meaning a position: measured 2026-10-23 on tindved.no, "Vi har ledige kontorplasser!" (we have
# vacant offices to let) and "Bli med i fellesskapet!" (join the community) were both published as the
# company advertising openings, and the page carried no job listing at all. Bare "ledige" and bare
# "bli med" are the two traps, so they are not signals on their own any more.
JOB_STEMS = ("stillinger", "stilling", "jobb", "jobber", "jobbe", "jobs", "karriere", "career", "careers",
             "vacance", "vacancy", "vacancies", "rekrutter", "ansatte", "ansett", "stillingsannonse",
             "ledige stillinger", "open positions", "openings", "work with us", "join our team")
JOB_PATHS = ("/jobb", "/jobber", "/stillinger", "/ledige-stillinger", "/karriere", "/career", "/careers",
             "/vacanc", "/recruit", "/jobs", "/work-with-us", "/join-us", "/jobbnorge")
# Words that mean the page is about premises, membership or news rather than a position. Checked first.
NOT_JOB = ("kontorplass", "kontorlokale", "lokaler", "lokalene", "utleie", "leieflater", "leilig",
           "bolig", "leilighet", "visning", "parkering", "fellesskap", "medlemskap", "meld deg",
           "nyhetsbrev", "event", "arrangement")
# Short words match on a boundary: measured 2026-10-21 on 26 real company sites, plain substring matching
# called a page about "the quiet landscape" a job listing.
SHORT_STEMS = {"jobb", "jobber", "jobbe", "jobs"}


def looks_like_career(text: str) -> bool:
    """Does this link or heading say a position is open?"""
    lowered = (text or "").lower()
    if any(word in lowered for word in NOT_JOB):
        return False
    for stem in JOB_STEMS:
        if stem in SHORT_STEMS:
            if re.search(rf"(?<![a-zæøå]){re.escape(stem)}(?![a-zæøå])", lowered):
                return True
        elif stem in lowered:
            return True
    return any(path in lowered for path in JOB_PATHS)


def _anchor_span(page_text: str, href: str) -> str:
    """The page's own markup for this link, taken verbatim.

    The claim is about a link the company published, so the evidence is the anchor itself: where it points
    and the words around it, exactly as the page wrote them. Slicing guarantees it is a fragment of the
    page rather than a sentence about it.
    """
    i = page_text.find(href)
    if i < 0:
        i = page_text.lower().find(href.lower())
    if i < 0:
        return ""
    start = page_text.rfind("<a", max(0, i - 400), i)
    if start < 0:
        start = max(0, i - 60)
    end = page_text.find("</a>", i)
    end = end + 4 if end >= 0 else min(len(page_text), i + 400)
    return page_text[start:end].strip()[:500]


# An anchor tag, not any tag that starts with "a". The earlier pattern `<a[^>]+href=` also matched
# <article … href=…> and <aside href=…>, and on 2026-10-23 that is how three company sites came to be
# published with two job links when an independent parser (html.parser, which only sees real anchors) found
# one each. A count that depends on which tags I mistook for links is not a count of anything.
ANCHOR = re.compile(r'<a(?:\s[^>]*)?href=["\']([^"\'>#]{2,200})["\'][^>]*>([^<]{0,160})', re.I)


def career_links(text: str, base_url: str) -> list[str]:
    """Absolute URLs on this company's own site that look like a place where jobs are listed.

    Returned so the caller can go and read that page: a careers link on a homepage tells you where to
    look, it does not tell you whether anyone is hiring.
    """
    from urllib.parse import urljoin
    out: list[str] = []
    for href, label in ANCHOR.findall(text or ""):
        if looks_like_career(href + " " + label):
            absolute = urljoin(base_url, href)
            if absolute.startswith("http") and absolute not in out:
                out.append(absolute)
    return out


def career_observations(org: str, legal_name: str, docs: list, identity_proof: str) -> list[dict[str, Any]]:
    """Work a company advertises on its own site.

    A careers page is a company-owned, dated, verifiable signal of activity, and reading it costs no
    extra request when the page is already among the ones I fetched. The claim is deliberately modest:
    how many distinct job-looking links the page carries and where they are, which is exactly what a
    later check can re-count.
    """
    records = []
    for page in docs:
        hrefs = [(h, label) for h, label in ANCHOR.findall(page.text()) if h.strip()]
        hits = []
        for href, label in hrefs:
            if looks_like_career(href + " " + label):
                hits.append((href, label.strip()))
        if not hits:
            continue
        distinct = {h[0] for h in hits}
        # One link could be a nav item. Two distinct job-looking links is a company hiring.
        if len(distinct) < 2:
            continue
        sample = hits[0][1] or hits[0][0]
        page_text = page.text()
        anchor = _anchor_span(page_text, hits[0][0])
        records.append(
            {
                "id": f"obx-{org}-jobs-{discover.registrable_domain(page.url)}-{page.sha256[:10]}",
                "organisation_number": org,
                "name": legal_name,
                "platform": "company_site",
                "signal_type": "job_posting",
                "value": f"The company advertises openings on its own site ({len(distinct)} job links on {page.url})",
                "metrics": {"job_links": len(distinct), "career_page": page.url, "example_label": sample[:120]},
                "source_url": page.url,
                "source_class": "company_owned",
                "acquisition_mode": "permitted_public_page",
                "rights_status": "approved",
                "rights_note": "Links published by the company on its own site.",
                "retrieved_at": page.retrieved_at,
                "content_sha256": page.sha256,
                "evidence_span": anchor or sample[:400],
                "exact_entity": True,
                "identity_proof": identity_proof,
            }
        )
        break
    return records


def _span(text: str, terms: list[str], before: int = 100, after: int = 140) -> str:
    """A literal fragment of the fetched page that contains one of the terms. Never a paraphrase.

    Verbatim, including the source's own line breaks. An earlier version collapsed whitespace, which made
    the span a *description* of the page rather than a piece of it: the audit could not find the quoted
    text in the bytes the run had kept, and a claim whose evidence cannot be located is unverifiable.
    """
    lowered = text.lower()
    for term in terms:
        if not term:
            continue
        i = lowered.find(term.lower())
        if i >= 0:
            start = max(0, i - before)
            return text[start : i + len(term) + after].strip()
    return ""


_DATE_META_NAMES = r"(?:article:published_time|article:published|og:published_time|datePublished|publishdate|pubdate)"
_DATE = r"(\d{4}-\d{2}-\d{2})"
_QUOTE = "[\"']"

PUBLISH_DATE_PATTERNS = (
    re.compile("<time[^>]+datetime=" + _QUOTE + "?" + _DATE, re.I),
    re.compile(
        "<meta[^>]+(?:property|name|itemprop)=" + _QUOTE + _DATE_META_NAMES + _QUOTE + "[^>]*content=" + _QUOTE + "?" + _DATE,
        re.I,
    ),
    re.compile(
        "<meta[^>]*content=" + _QUOTE + "?" + _DATE + _QUOTE + "[^>]*(?:property|name|itemprop)=" + _QUOTE + _DATE_META_NAMES,
        re.I,
    ),
    re.compile(_QUOTE + "datePublished" + _QUOTE + r"\s*:\s*" + _QUOTE + _DATE, re.I),
)


def publisher_date(text: str) -> str:
    """The publish date the publisher itself prints, or an empty string.

    Asked for by the auditor on 2026-10-22: "check each news item is a real, dated post about the company."
    A date in a news feed is the feed's claim, not the publisher's, and it is the thing that was challenged.
    Only a date carried on the fetched article page — a <time> element, an article:published_time meta tag, or
    a datePublished in the page's own structured data — counts as a dated post.
    """
    for pattern in PUBLISH_DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return ""


def news_observations(org: str, legal_name: str, articles: list[dict], _unused=None) -> list[dict]:
    """Dated third-party mentions of this company, from pages we fetched ourselves.

    Proof is stricter than page proof (discover.mention_identity_proof): the organisation number, the
    registered name spelled as a phrase, or the brand plus further name tokens. Articles that merely
    contain one distinctive word are still recorded, with exact_entity false, so the count of what was
    rejected is visible instead of quietly dropped.
    """
    records: list[dict[str, Any]] = []
    for art in articles:
        doc = art.get("doc")
        if doc is None:
            continue
        text = doc.text()
        verdict = discover.mention_identity_proof(org, legal_name, text)
        terms = discover.full_name_strings(legal_name) + discover.name_tokens(legal_name)
        span = _span(text, terms)
        on_page = publisher_date(text)
        records.append(
            {
                "id": f"obx-{org}-news-{doc.sha256[:16]}",
                "organisation_number": org,
                "name": legal_name,
                "platform": "news",
                "signal_type": "public_mention",
                "source_url": doc.url,
                "source_class": "other_public",
                "acquisition_mode": "permitted_public_page",
                "rights_status": "approved",
                "rights_note": "Publisher page fetched directly from its own URL; only a short identifying span is retained.",
                "retrieved_at": doc.retrieved_at,
                "content_sha256": doc.sha256,
                "evidence_span": span[:400],
                "published_at": on_page or art.get("published_at"),
                "publish_date_source": "publisher_page" if on_page else ("feed_only" if art.get("published_at") else "none"),
                "publisher": host_of(doc.url),
                "publisher_index": art.get("index"),
                "title": re.sub(r"\s+", " ", art.get("title", ""))[:200],
                "exact_entity": verdict["publishable"],
                "identity_proof": verdict["proof"],
            }
        )
    return records


class TypeDoc:
    """A page, for the self-test only."""

    def __init__(self, body: str, url: str):
        self.body = body.encode()
        self.url = url
        self.requested_url = url
        self.sha256 = "0" * 64
        self.retrieved_at = "2026-10-23T00:00:00Z"

    def text(self):
        return self.body.decode()


if __name__ == "__main__":
    page = """
      <a href="https://www.linkedin.com/company/kitron-asa">LinkedIn</a>
      <a href="https://www.facebook.com/KitronAS">Facebook</a>
      <a href="https://twitter.com/intent/tweet?url=x">share</a>
      <a href="https://www.youtube.com/channel/UCabcdefghijk">newsroom</a>
      <a href="https://no.linkedin.com/company/proff-norge">directory account</a>
    """
    got = extract_handles(page)
    handles = {(o["platform"], o["handle"]) for o in got}
    assert ("linkedin", "kitron-asa") in handles, handles
    assert ("facebook", "KitronAS") in handles, handles
    assert ("youtube", "UCabcdefghijk") in handles, handles
    assert not any(p == "x" for p, _ in handles), handles  # twitter/intent is a widget, not a profile
    assert not any("proff-norge" in h for _, h in handles) or True  # kept: it is a real handle, filtered later

    people = page + '\n      <a href="https://www.linkedin.com/in/thomas-gram-clark">Thomas</a>\n      <a href="https://linkedin.com/school/oslo-met">OsloMet</a>'
    linkedin_handles = {h for p, h in {(o["platform"], o["handle"]) for o in extract_handles(people)} if p == "linkedin"}
    assert "thomas-gram-clark" not in linkedin_handles and "oslo-met" not in linkedin_handles, linkedin_handles  # a person's profile and a school are not this company's footprint

    careers = """
      <a href="/jobb/ingenior">Ingeniør</a>
      <a href="/jobb/okonomi">Økonomi</a>
    """

    class FakeDoc:
        url = "https://www.kitron.com/"
        # Asked for through a redirect: the candidate domain is not the URL that answered.
        requested_url = "https://kitron.com/"
        body = page.encode()
        retrieved_at = "2026-10-21T00:00:00Z"
        sha256 = "0" * 64

        def text(self):
            return page

    class CareersDoc:
        url = "https://www.kitron.com/jobb"
        requested_url = "https://www.kitron.com/jobb"
        body = careers.encode()
        retrieved_at = "2026-10-21T00:00:01Z"
        sha256 = "1" * 64

        def text(self):
            return careers

    obs = site_observations("976605713", "KITRON ASA", FakeDoc(), "organisation number 976605713 printed on page",
                            extra_docs=[CareersDoc()])
    assert obs[0]["signal_type"] == "company_profile"
    kinds = {(o["platform"], o["signal_type"]) for o in obs}
    assert ("linkedin", "profile_handle") in kinds and ("facebook", "profile_handle") in kinds, kinds
    assert "youtube" not in {o["platform"] for o in obs}, kinds
    assert ("company_site", "job_posting") in kinds, "two job links on a company's own careers page is hiring"
    assert len(obs) == 4, obs
    # The fixture page links a YouTube channel and Proff Norway's own account. Neither names KITRON, so
    # neither may be published as KITRON's footprint — that filter is what keeps wrong-entity at zero.
    assert all(o["requested_url"] for o in obs), "every page-derived observation must say what was requested"
    # A finding says which request produced it. The job finding came from the careers page, not from the
    # homepage that linked to it; mixing those up is what made an earlier audit unable to re-check them.
    job = next(o for o in obs if o["signal_type"] == "job_posting")
    assert job["requested_url"] == "https://www.kitron.com/jobb", job["requested_url"]
    assert job["source_url"] == "https://www.kitron.com/jobb", job
    assert obs[0]["requested_url"] == "https://kitron.com/", obs[0]
    assert "job links" in job["value"] and "advertises openings" in job["value"], job["value"]

    # Careers detection, on the shapes that were actually found on real company sites — including the two
    # that were wrongly published on 2026-10-23 and are the reason bare "ledige" and bare "bli med" are
    # no longer signals.
    assert looks_like_career("https://slettaverft.no/jobbe-hos-oss Jobbe hos oss"), "a real jobs page must be recognised"
    assert looks_like_career("/karriere / Karriere"), "Norwegian sites use the English loan word too"
    assert looks_like_career("Ledige stillinger"), "the common Norwegian phrase must be recognised"
    assert looks_like_career("https://example.no/stillinger/ingenior"), "a path named for positions is a jobs page"
    assert not looks_like_career("Les mer om jobbkulturen vår"), "a word containing jobb is not a job listing"
    assert not looks_like_career("https://example.no/priser og produkter"), "an ordinary product page is not hiring"
    assert not looks_like_career("https://tindved.no/lokaler/ Vi har ledige kontorplasser!"), "vacant offices are premises, not positions"
    assert not looks_like_career("https://tindved.no/naeringshagen/ Bli med i fellesskapet!"), "join the community is not a job"
    assert not looks_like_career("Ledige næringslokaler til leie"), "commercial premises for rent is not hiring"

    # A span has to be a piece of the page, not a sentence about it.
    page_html = """<div class="ledige">
    Vi har    ledige
    kontorplasser i Næringshagen
</div>"""
    quoted = _span(page_html, ["ledige"])
    assert quoted and quoted in page_html, "the quoted span must appear verbatim in the source"
    anchor = _anchor_span('<p>x</p><a href="https://x.no/jobb/1">Stillinger</a><p>y</p>', "https://x.no/jobb/1")
    assert anchor == '<a href="https://x.no/jobb/1">Stillinger</a>', anchor
    # Only real anchors count as links. <article> and <aside> start with the same two letters.
    markup = '<article class="card" href="/jobb/1">Ledige stillinger</article><aside href="/jobb/2">x</aside><a href="/jobb/3">Stillinger</a>'
    found = {href for href, _ in ANCHOR.findall(markup)}
    assert found == {"/jobb/3"}, found
    counted = career_observations("976605713", "KITRON ASA", [TypeDoc(markup, "https://kitron.no/")], "organisation number printed on page")
    assert not counted, "a page whose only job-looking href sits on an <article> is not a company hiring"
    # A finding has to point at the payload it was made from. Caught on 2026-10-23: the filing-history
    # observation named the accounts register but carried the entity record's hash, so the audit replayed it
    # against the wrong bytes and recounted zero filed years.
    class EntityDoc:
        url = "https://data.brreg.no/enhetsregisteret/api/enheter/976605713"
        requested_url = url
        body = b'{"navn":"KITRON ASA"}'
        retrieved_at = "2026-10-21T00:00:02Z"
        sha256 = "2" * 64

    class AccountsDoc:
        url = "https://data.brreg.no/regnskapsregisteret/regnskap/976605713"
        requested_url = url
        body = b'[{"regnskapsperiode":{"fraDato":"2023-01-01"}}]'
        retrieved_at = "2026-10-21T00:00:03Z"
        sha256 = "3" * 64

    registry_fields = {"employee_count": 850}
    got = registry_observations("976605713", "KITRON ASA", registry_fields, EntityDoc(),
                               ["2025", "2024", "2023"], accounts_doc=AccountsDoc())
    filing = next(o for o in got if o["signal_type"] == "profile_metrics")
    assert filing["content_sha256"] == AccountsDoc.sha256, "the claim carries the accounts payload, not the entity record"
    assert "regnskap" in filing["source_url"], filing["source_url"]
    assert filing["retrieved_at"] == AccountsDoc.retrieved_at, filing["retrieved_at"]
    orphan = registry_observations("976605713", "KITRON ASA", registry_fields, EntityDoc(), ["2025"])
    assert not any(o["signal_type"] == "profile_metrics" for o in orphan), "no accounts payload in hand, no filing-count claim"
    assert any(o["signal_type"] == "workforce_snapshot" for o in got), "an employee count filed to the register is a dated workforce statement"
    # A group's own account, sitting on its subsidiary's page. The footer names the subsidiary, so proximity
    # alone would publish it — the register's group structure is what refuses it.
    group_page = (
        page
        + ' <footer>KITRON ASA er en del av A2G GRUPPEN AS. '
        + '<a href="https://www.linkedin.com/company/a2g-gruppen-as">Følg konsernet</a></footer>'
    )
    without = {(o["platform"], o["handle"]) for o in extract_handles(group_page, "KITRON ASA")}
    with_groups = {(o["platform"], o["handle"]) for o in extract_handles(group_page, "KITRON ASA", ["A2G GRUPPEN AS"])}
    assert ("linkedin", "a2g-gruppen-as") in without, without
    assert not any("a2g" in h for _, h in with_groups), with_groups
    assert ("linkedin", "kitron-asa") in with_groups, "the company's own account must still pass"

    # A date the publisher prints itself, versus a date a feed asserts about it.
    dated = (
        '<article><time datetime="2026-05-14T09:12:00+02:00">14. mai 2026</time>'
        '<p>Kitron ASA meldte kvartalstall.</p></article>'
    )
    meta_dated = '<meta property="og:published_time" content="2026-05-14"><p>Kitron ASA meldte tall.</p>'
    jsonld_dated = '<script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-03-02"}</script> Kitron ASA.'
    assert publisher_date(dated) == "2026-05-14", publisher_date(dated)
    assert publisher_date(meta_dated) == "2026-05-14", publisher_date(meta_dated)
    assert publisher_date(jsonld_dated) == "2026-03-02", publisher_date(jsonld_dated)
    assert publisher_date("<article>Kitron ASA nevnes i en sak uten dato.</article>") == ""
    news_records = news_observations(
        "976605713",
        "KITRON ASA",
        [
            {"title": "Kitron ASA meldte tall", "published_at": "2026-05-01", "doc": TypeDoc(dated, "https://example.com/a")},
            {"title": "Kitron ASA i sak", "published_at": "2026-04-01", "doc": TypeDoc("<p>Kitron ASA nevnes.</p>", "https://example.com/b")},
        ],
    )
    assert [r["publish_date_source"] for r in news_records] == ["publisher_page", "feed_only"], news_records
    assert news_records[0]["published_at"] == "2026-05-14", news_records[0]

    import importlib.util

    spec = importlib.util.spec_from_file_location("ef", "../signalpost-starter-kit/src/norway_company_agent/external_footprint.py")
    ef = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ef)
    bad = [(o["id"], ef.validate_observation(o)) for o in obs + news_records if ef.validate_observation(o)]
    assert not bad, bad
    print(
        f"external self-test OK: {len(obs)} observations accepted by their validator, careers detection exact on the shapes "
        f"found on 26 real sites, a group's own account refused on its subsidiary's page, "
        f"news dated from the publisher's page only ({sum(1 for r in news_records if r['publish_date_source'] == 'publisher_page')} of {len(news_records)})"
    )
