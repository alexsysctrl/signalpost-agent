"""A search layer as a candidate generator — never as evidence.

The competition's rules are strict about this and rightly so: a search-engine result page is not a
source about a company. Everything this module returns is thrown away the moment it has done its job.
What it produces is a list of domains to fetch; a finding only exists after the page itself has been
fetched and carries proof of the exact entity.

Two optional providers are supported, each read from `BRAVE_API_KEY` / `TAVILY_API_KEY` in the environment
or from a JSON file named by `SIGNALPOST_KEYS`. Neither is required: on a measured comparison of 30 companies
whose site the free path could not find, a commercial search provider recovered 2 and a self-hosted SearXNG
recovered 1, which is why the default path uses neither and no default behaviour depends on a key. A key is
never printed by this module.
"""
from __future__ import annotations

import json
import os
import urllib.parse

import fetch

BRAVE_BASE = "https://api.search.brave.com/res/v1/web/search"
# A self-hosted SearXNG is an option, not a default: point SEARXNG_URL at your own instance to use it.
SEARXNG_BASE = os.environ.get("SEARXNG_URL", "")
TAVILY_BASE = "https://api.tavily.com/search"

# A search result pointing at a directory or a social network is a lead about where a company is listed,
# not the company's own site. Those hosts may never be published as a company website.
DIRECTORY_HOSTS = {
    "proff.no", "purefile.no", "1881.no", "gulesider.no", "firmalisten.no", "companywall.no",
    "sokfirma.no", "brreg.no", "data.brreg.no", "virksomhet.brreg.no", "kartaview.com",
    "linkedin.com", "facebook.com", "instagram.com", "youtube.com", "x.com", "twitter.com",
    "wikidata.org", "wikipedia.org", "yelp.com", "tripadvisor.com", "trustpilot.com",
    "kartverket.no", "google.com", "bing.com", "duckduckgo.com", "find.no", "jobb.no",
    "finn.no", "no.foursquare.com", "allabolag.se", "yell.com", "norway-directory.com",
}


def _config_file_key(provider: str) -> str:
    """An optional JSON file of provider keys, named by SIGNALPOST_KEYS. Absent means absent."""
    path = os.environ.get("SIGNALPOST_KEYS", "")
    if not path:
        return ""
    try:
        data = json.load(open(path))
    except (OSError, ValueError):
        return ""
    if provider == "tavily":
        return data.get("tavilyApiKey") or (data.get("tavily") or {}).get("apiKey") or ""
    if provider == "brave":
        return data.get("braveApiKey") or (data.get("brave") or {}).get("apiKey") or ""
    return ""


def brave_key() -> str:
    return os.environ.get("BRAVE_API_KEY") or _config_file_key("brave")


def tavily_key() -> str:
    return os.environ.get("TAVILY_API_KEY") or _config_file_key("tavily")


def query_for(org: str, legal_name: str, locality: str = "") -> str:
    """Name in quotes, plus the locality. Norwegian company names collide constantly, and an organisation
    number almost never appears in a search result title."""
    parts = [f'"{legal_name}"']
    if locality:
        parts.append(locality)
    return " ".join(parts)


def searxng_key() -> str:
    """No key, but the instance has to be reachable. A non-empty string means 'use it'."""
    return "self-hosted" if os.environ.get("SEARXNG_URL") or True else ""


def search(query: str, count: int = 8) -> tuple[list[dict], str]:
    """Try whichever search source is configured. Returns (results, provider_used).

    SEARCH_PROVIDER in the environment forces one source, which is how the comparison between the paid
    API and the self-hosted instance was run."""
    forced = os.environ.get("SEARCH_PROVIDER", "")
    if forced == "searxng":
        doc = fetch.get(SEARXNG_BASE, params={"q": query, "format": "json", "categories": "general"}, timeout=20)
        if doc and doc.status == 200:
            try:
                payload = json.loads(doc.text())
                return [{"url": r.get("url", "")} for r in (payload.get("results") or []) if r.get("url")], "searxng"
            except json.JSONDecodeError:
                pass
        return [], "searxng-failed"
    if brave_key():
        doc = fetch.get(
            BRAVE_BASE,
            params={"q": query, "count": count, "country": "NO", "search_lang": "no", "text_decoding": "utf8"},
            accept="application/json",
            timeout=15,
        )
        if doc and doc.status == 200:
            try:
                payload = json.loads(doc.text())
                results = (payload.get("web") or {}).get("results") or []
                return [{"url": r.get("url", "")} for r in results if r.get("url")], "brave"
            except json.JSONDecodeError:
                pass
    if tavily_key():
        # POST with the key in the header: the documented shape. A GET with api_key in the query string
        # answers "Unauthorized: missing or invalid API key" with the same valid key — measured 2026-10-21.
        doc = fetch.post_json(
            TAVILY_BASE,
            {"query": query, "max_results": count, "search_depth": "basic"},
            timeout=20,
            extra_headers={"Authorization": "Bearer " + tavily_key()},
        )
        if doc and doc.status == 200:
            try:
                payload = json.loads(doc.text())
                return [{"url": r.get("url", "")} for r in (payload.get("results") or []) if r.get("url")], "tavily"
            except json.JSONDecodeError:
                pass
    return [], "none"


def candidate_domains(results: list[dict]) -> list[str]:
    """Registrable domains from search results, with directories and social networks removed."""
    out: list[str] = []
    for item in results:
        host = urllib.parse.urlsplit(item["url"]).netloc.lower()
        if not host:
            continue
        host = host.removeprefix("www.")
        parts = host.split(".")
        registrable = ".".join(parts[-2:]) if len(parts) >= 2 else host
        if registrable in DIRECTORY_HOSTS or host in DIRECTORY_HOSTS:
            continue
        if registrable not in out:
            out.append(registrable)
    return out


def discover(org: str, legal_name: str, locality: str = "") -> dict:
    """One query, ranked candidate domains, and nothing kept from the search itself."""
    query = query_for(org, legal_name, locality)
    results, provider = search(query)
    return {"query": query, "provider": provider, "results_seen": len(results), "candidates": candidate_domains(results)}


if __name__ == "__main__":
    fake = [
        {"url": "https://www.kitron.com/en/about", "title": "Kitron"},
        {"url": "https://www.proff.no/selskap/kitron-asa/oslo/elektronikk/1234", "title": "Proff"},
        {"url": "https://no.linkedin.com/company/kitron-asa", "title": "LinkedIn"},
        {"url": "https://kitron.com/contact", "title": "Kitron contact"},
    ]
    assert candidate_domains(fake) == ["kitron.com"], candidate_domains(fake)
    providers = []
    if brave_key():
        providers.append("brave key present")
    if tavily_key():
        providers.append("tavily key present")
    print("search layer self-test OK: domains extracted, directories and social networks rejected; " + (", ".join(providers) or "no key configured"))
