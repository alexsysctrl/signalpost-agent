"""Third-party published activity about a company.

Free, no API key, and the dates come from the publisher, not from us.

Two public news indexes are used, and neither one is a scrape of a results page:

  Bing News RSS  — items carry a Bing redirect whose `url=` parameter is the publisher's own article
                   URL, so the item hands us a real address to fetch.
  Google News RSS — items are opaque news.google.com routes with no recoverable target (verified
                   2026-10-21: neither the item page nor `?oc=5` exposes the publisher URL, and the
                   article id decodes to an opaque token). It is kept only for the publisher *domain*
                   and the publication date, which is enough to confirm that a company was in the news
                   and not enough to cite. It is never the evidence for a published claim.

The evidence rule follows the competition's own transient-provider pattern: the search output is used to
find a candidate, the candidate page is fetched immediately, and only the fetched page is retained —
URL, retrieval time, content hash, and the span that carries the company name. Snippets and titles from
the index are discarded, because an index snippet is not something anyone can check later.

Entity matching is graded exactly like site proof (discover.identity_proof). A headline containing a
company name is not proof of that company: Norwegian names collide constantly.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import discover
import fetch

BING_RSS = "https://www.bing.com/news/search"
GOOGLE_RSS = "https://news.google.com/rss/search"


def _text(item: ET.Element, tag: str) -> str:
    node = item.find(tag)
    return (node.text or "").strip() if node is not None and node.text else ""


def _publisher_url(link: str) -> str:
    """Unwrap Bing's apiclick redirect to the publisher's own article URL."""
    if "apiclick" not in link and "url=" not in link:
        return link
    query = parse_qs(urlparse(link).query)
    target = (query.get("url") or [""])[0]
    return unquote(target)


def bing_articles(legal_name: str, municipality: str = "", limit: int = 5) -> list[dict]:
    name = " ".join(legal_name.split())
    if not name:
        return []
    query = f'"{name}"' + (f' "{municipality}"' if municipality else "")
    doc = fetch.get(BING_RSS + "?" + "format=rss&count=20&q=" + quote_plus(query), timeout=15)
    if doc is None or doc.status != 200 or b"<rss" not in doc.body[:400]:
        return []
    try:
        root = ET.fromstring(doc.text())
    except ET.ParseError:
        return []
    out: list[dict] = []
    for item in root.iter("item"):
        title = _text(item, "title")
        link = _text(item, "link")
        target = _publisher_url(link)
        if not title or not target:
            continue
        host = (urlparse(target).hostname or "").casefold().removeprefix("www.")
        if not host or "bing.com" in host:
            continue
        out.append(
            {
                "index": "bing_news",
                "title": title,
                "article_url": target,
                "publisher_domain": host,
                "published_at": _text(item, "pubDate"),
                "query": query,
                "index_url": doc.url,
            }
        )
        if len(out) >= limit:
            break
    return out


def google_news_domains(legal_name: str, limit: int = 5) -> list[dict]:
    """Coverage check only: is this company appearing in Norwegian news, and where.

    Not citable evidence — the item's real article URL is not recoverable from Google's feed — so this
    is used to know that a signal exists, never to publish a fact.
    """
    name = " ".join(legal_name.split())
    if not name:
        return []
    doc = fetch.get(GOOGLE_RSS + "?" + "hl=no&gl=NO&ceid=NO:no&q=" + quote_plus(f'"{name}"'), timeout=15)
    if doc is None or doc.status != 200 or b"<rss" not in doc.body[:400]:
        return []
    try:
        root = ET.fromstring(doc.text())
    except ET.ParseError:
        return []
    out: list[dict] = []
    for item in root.iter("item"):
        source = item.find("source")
        domain = (source.get("url") or "").casefold().removeprefix("www.") if source is not None else ""
        if not domain:
            continue
        out.append({"index": "google_news", "publisher_domain": domain, "title": _text(item, "title"), "published_at": _text(item, "pubDate")})
        if len(out) >= limit:
            break
    return out


def search_articles(legal_name: str, municipality: str = "", limit: int = 5) -> list[dict]:
    return bing_articles(legal_name, municipality, limit)


def exact_entity_in_article(legal_name: str, text: str) -> dict:
    """Strict grading, the same one the agent publishes with."""
    return discover.mention_identity_proof("", legal_name, text)


def fetch_article(item: dict):
    """Fetch the publisher's own page. Returns a Doc or None — the caller records which happened."""
    url = item.get("article_url") or ""
    if not url:
        return None
    doc = fetch.get(url, timeout=12, max_bytes=400_000)
    if doc is not None and doc.status == 200 and len(doc.body) > 800:
        return doc
    return None


if __name__ == "__main__":
    items = bing_articles("KITRON ASA", limit=5)
    assert items, "KITRON ASA is in the news; a live index query must return candidates"
    assert all("bing.com" not in i["article_url"] for i in items), [i["article_url"] for i in items]
    # A live test must not fail because one publisher happens to block us today. What has to hold is that a
    # real news item can be reached at its own address — so every candidate is tried, and the test reports
    # how many were reachable rather than assuming the first one is.
    reached = [(item, doc) for item in items if (doc := fetch_article(item)) is not None]
    assert reached, f"none of {len(items)} real news items could be fetched from the publisher directly: {[i['article_url'] for i in items]}"
    item, doc = reached[0]
    landed = (urlparse(doc.url).hostname or "").casefold().removeprefix("www.")
    assert landed == item["publisher_domain"], f"redirect landed elsewhere: {landed} vs {item['publisher_domain']}"
    verdict = exact_entity_in_article("KITRON ASA", doc.text())
    assert verdict["level"] == 2, f"a Kitron ASA article must prove the registered name phrase, got {verdict}"
    collision = exact_entity_in_article("HUNDRALEDEN 4 BORETTSLAG UKN", doc.text())
    assert collision["level"] == 0, collision

    import external

    dated = sum(1 for _, d in reached if external.publisher_date(d.text()))
    print(
        f"news self-test OK: {len(reached)} of {len(items)} real articles fetched from the publisher directly, "
        f"{dated} of those {len(reached)} carry a publish date on the page itself (feed dates are never published)"
    )
    g = google_news_domains("KITRON ASA", limit=3)
    assert all(x["publisher_domain"] for x in g)
    print(
        f"news self-test OK: {len(items)} candidates, publisher page {doc.url} fetched ({len(doc.body)} bytes), "
        f"match level {verdict['level']}; google gives {len(g)} domains, used for coverage only"
    )
