"""Finding a company's own website, and proving it belongs to that company.

Why this module exists: measured on 2026-10-20, the official registry lists a website for about 11%
of the eligible universe (13 of a 200-company sample; 44,855 of 411,160 overall). The competition
scores recall against everything any agent or crawler verified, so the other 89% is the whole game.

Design, in order of cost:
  1. Candidate hostnames generated from the legal name — Norwegian orthography has two accepted
     transliterations for ae/oe/aa, and companies register both, so both are generated.
  2. DNS resolution: a lookup is near-free; it prunes almost everything before any HTTP.
  3. HTTP fetch of the survivors, and a proof test. A domain is only published when the page itself
     carries the organisation number or the exact legal name. Guessing a match is how wrong-company
     publications happen, and one of those can cost an entire run.

No search API is used, so this costs nothing and is reproducible. A search connector can be added
later as a declared, priced source.
"""
from __future__ import annotations

import re
import socket
import time
from urllib.parse import urlsplit

import fetch

TLDS = (".no", ".com", ".net", ".eu", ".site", ".shop", ".org")

# Norwegian characters have more than one Latin transliteration; domains use whichever was typed.
TRANSLIT = [
    {"æ": "ae", "ø": "oe", "å": "aa"},
    {"æ": "a", "ø": "o", "å": "a"},
]

LEGAL_SUFFIXES = frozenset(
    {
        "as", "asa", "ans", "ba", "ds", "kf", "nkf", "ansvarlig", "se", "uf",
        "holding", "gruppen", "group", "management", "forvaltning", "drift", "eiendom",
    }
)
NOISE_WORDS = {"norsk", "the", "norwegian"}

socket.setdefaulttimeout(3)


def _clean(text: str) -> str:
    """Lowercase and strip punctuation, keeping æ/ø/å intact.

    NFKD normalisation must not be used here: it decomposes å to a + combining ring, which the
    strip then removes, and the aa/ae transliterations never happen. That silently cut half the
    candidate domains for any name with Norwegian characters.
    """
    t = text.lower()
    t = re.sub(r"[^a-z0-9æøå \-]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# Mail hosts that many unrelated companies share. A candidate from one of these is not a lead, it is
# noise — the register lists a mailbox, not a website.
FREEMAIL_HOSTS = {
    "gmail.com", "googlemail.com", "online.no", "start.no", "broadpark.no", "getmail.no",
    "mail.com", "telia.com", "vel.com", "cybermail.net", "power.no", "homenet.no", "skolemail.no",
    "freenet.de", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.no", "fibred.no", "altibox.no",
    "dr.no", "epost.inn.no", "mailno.com", "sunnspost.no", "post.com", "icloud.com", "me.com",
    "c2i.net", "c2i.com", "nextgentel.com", "tilpost.com", "skya.com", "epost.inn.no", "mail.no",
    "broadband.no", "nord-noc.net", "sol.no", "online.com", "jrcl.no", "privatmail.no",
}


def email_candidates(email: str) -> list[str]:
    """Candidate hosts from the registered email address.

    Measured 2026-10-21 across 200,000 registry rows: 37.8% of listed entities publish an e-postadresse
    and only 11.4% publish a hjemmeside. Where both exist, the mail domain is the website domain 59% of
    the time. So the mail field is a pointer to a site the register never lists — worth about as many
    leads as the registry's own website column, for free. Every one of them still has to pass proof.
    """
    email = (email or "").strip().lower()
    if "@" not in email:
        return []
    host = email.split("@", 1)[1].strip().rstrip(".")
    if not host or host in FREEMAIL_HOSTS:
        return []
    host = host.removeprefix("mail.").removeprefix("www.")
    if "." not in host:
        return []
    out = [host, "www." + host]
    # Some companies run their mail on the apex and their site on a subdomain of the same registrable
    # domain, or the reverse; both spellings are tried, and only a proven one is published.
    parts = host.split(".")
    if len(parts) >= 3:
        apex = ".".join(parts[-2:])
        out.extend([apex, "www." + apex])
    return [h for h in dict.fromkeys(out) if h not in FREEMAIL_HOSTS]


def name_slugs(name: str) -> list[str]:
    """Candidate domain bodies from a legal name, most-likely first.

    'SANDNES ELEKTRISKE AS' -> sandneselektriske, sandnes-elektriske, elektrisk...
    Both transliterations of æ/ø/å, hyphenated and joined. Order matters: this list is tried in
    sequence and DNS pruning makes the cost of extra candidates small.
    """
    base = _clean(name)
    words = [w for w in base.split() if w not in LEGAL_SUFFIXES and w not in NOISE_WORDS]
    if not words:
        words = [w for w in base.split()]
    out: list[str] = []

    def add(seq: list[str]) -> None:
        for joiner in ("", "-"):
            s = joiner.join(seq)
            s = re.sub(r"[^a-z0-9-]", "", s).strip("-")
            if 2 < len(s) <= 40 and s not in out:
                out.append(s)

    for table in TRANSLIT:
        tr = [ "".join(table.get(ch, ch) for ch in w) for w in words ]
        add(tr)                                   # full name, joined or hyphenated
        if len(tr) >= 2:
            add(tr[:2])                          # drop brand-legal tail
            add([tr[0], tr[-1]])
            add(tr[0:1])                         # single distinctive word
            add([w[:1] for w in tr])             # initials, e.g. 'se' for sandnes elektriske
    # A company registered with a numeric org in its domain is rare; skip.
    return out


def candidates(name: str, limit: int = 28) -> list[str]:
    hosts: list[str] = []
    for slug in name_slugs(name):
        for tld in TLDS:
            for prefix in ("www.", ""):
                hosts.append(prefix + slug + tld)
    # Cheap-first ordering: the .no apex and its www form, then the rest. A name generates dozens of
    # plausible domains; trying all of them costs more than the whole registry portion of the run.
    hosts.sort(key=lambda h: (0 if h.endswith(".no") else 1, 0 if h.startswith("www.") else 1, len(h)))
    return hosts[:limit]


HOST_SHAPE = re.compile(r"^[a-z0-9.\-\u00e6\u00f8\u00e5]{1,253}$")


def resolves(host: str) -> bool:
    """Can this host be looked up? A malformed candidate is a no, not an exception.

    Found 2026-10-21: a link extracted from a directory page produced a host with a 73-character label
    and getaddrinfo raised UnicodeEncodeError inside a thread pool — 'label too long'. Candidate hosts come
    from other people's pages, so shape-check them before spending a lookup on them.
    """
    host = (host or "").strip().lower()
    if not HOST_SHAPE.match(host) or any(len(label) > 63 for label in host.split(".")):
        return False
    fetch.count_dns()
    try:
        socket.getaddrinfo(host, None)
        return True
    except Exception:
        return False


ORG_PATTERNS = [
    re.compile(r"\b(\d{3})[ .]?(\d{3})[ .]?(\d{3})\b"),
    re.compile(r"organisasjonsnummer[^\d]{0,20}(\d{9})", re.I),
    re.compile(r"org\.?nr[^\d]{0,20}(\d{9})", re.I),
    re.compile(r"\"(?:organizationNumber|orgnr|organisationNumber)\"\s*:\s*\"?(\d{9})", re.I),
]


def org_numbers_in(text: str) -> set[str]:
    found: set[str] = set()
    for pat in ORG_PATTERNS:
        for m in pat.finditer(text):
            if m.re.groups == 3:
                found.add("".join(m.groups()))
            else:
                found.add(m.group(1))
    return found


GENERIC_TOKENS = LEGAL_SUFFIXES | {
    "norge", "norsk", "as", "group", "holding", "drift", "forvaltning", "eiendom", "service",
    "services", "consulting", "management", "development", "no", "www",
}


def registrable_domain(host: str) -> str:
    parts = [p for p in host.split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def name_tokens(name: str) -> list[str]:
    """Distinctive tokens only. 'HAFSLUND KRAFT INNLANDET AS' -> hafslund, kraft, innlandet.
    A subsidiary's own homepage says 'Hafslund', not its full registered name, so the proof test
    must not demand every token — it demands the distinctive ones, in descending rarity."""
    words = [w for w in _clean(name).split() if len(w) >= 3 and w not in GENERIC_TOKENS]
    return words


def name_token_variants(name: str) -> set[str]:
    """Distinctive tokens, plus the ASCII spellings a domain or handle would actually use."""
    out: set[str] = set()
    for token in name_tokens(name):
        out.add(token)
        for table in TRANSLIT:
            out.add("".join(table.get(ch, ch) for ch in token))
    return {t for t in out if len(t) >= 4}


def full_name_strings(name: str) -> list[str]:
    """The registered name spelled as a phrase, with and without its legal suffix.

    A news article that says "Kitron ASA" is about Kitron. An article that says "Kitron" might be a
    share ticker, a comment under a different company's story, or a different company. Requiring the
    phrase is the difference between a mention we can publish and one we cannot.
    """
    cleaned = _clean(name)
    words = [w for w in cleaned.split() if w]
    out: list[str] = []
    core = [w for w in words if w not in LEGAL_SUFFIXES]
    for seq in (words, core):
        if len(seq) >= 2:
            phrase = " ".join(seq)
            if len(phrase) >= 8 and phrase not in out:
                out.append(phrase)
    return out


def name_domain_slugs(legal_name: str) -> set[str]:
    """The ASCII spellings a company would plausibly use for its own name in a domain.

    A domain is typed in ASCII; a registered Norwegian name is not. Comparing 'torbjørn' with
    'torbjorn' finds nothing, which is why the first version of this rule rejected the cases it was
    written for. Every accepted transliteration of the name is generated here, in both the ae/oe/aa and
    a/o/aa forms, joined and hyphenated.
    """
    tokens = name_tokens(legal_name)
    if not tokens:
        return set()
    out: set[str] = set()
    for table in TRANSLIT:
        ascii_tokens = ["".join(table.get(ch, ch) for ch in t) for t in tokens]
        out.add("".join(ascii_tokens))
        out.add("-".join(ascii_tokens))
    return out


def domain_derived_from_name(legal_name: str, host: str) -> str:
    """Is this domain the company's own name spelled out?

    'TEAM TUR AS' and teamtur.no: the concatenation of every distinctive token. That is a second,
    independent signal — the company chose a domain after its own legal name, and the page then names
    the company. A match on a domain that has nothing to do with the name is a different situation and
    stays unpublished.

    Single-token names need a longer token: a company called VIRAL AS and a site named viral.no is not
    the same certainty as Gaupset Holding and gaupset.no.
    """
    tokens = name_tokens(legal_name)
    sld = registrable_domain(host).split(".")[0]
    if sld not in name_domain_slugs(legal_name):
        return ""
    if len(tokens) >= 2:
        return f"domain {sld} spells every distinctive token of the registered name"
    if len(tokens) == 1 and len(tokens[0]) >= 7:
        return f"domain {sld} is the full distinctive token of the registered name"
    return ""


def name_match(name: str, body: str) -> tuple[bool, str]:
    tokens = name_tokens(name)
    lowered = body.lower()
    if not tokens:
        base = [w for w in _clean(name).split() if w]
        ok = bool(base) and all(w in lowered for w in base)
        return ok, "full registered name on page" if ok else "no distinctive name tokens found"
    hits = [t for t in tokens if t in lowered]
    if len(hits) == len(tokens) and hits:
        return True, f"all distinctive name tokens on page: {hits}"
    # Two tokens including the leading brand token is enough: subsidiaries drop the trailing ones.
    if len(hits) >= 2 and tokens[0] in hits:
        return True, f"brand plus {len(hits) - 1} name tokens on page: {hits}"
    return False, f"only {len(hits)} of {len(tokens)} name tokens on page: {hits}"


def place_tokens(record: dict) -> list[str]:
    """Locality words from the registry row: municipality, address, postal city. Used as corroboration
    when a page carries the brand but not the number — two companies can share a name, far fewer share
    a name and a town."""
    out: list[str] = []
    for key in ("kommune", "municipality", "postadresse.poststed", "forretningsadresse.poststed", "postnummer"):
        v = str(((record or {}).get(key)) or "").strip().lower()
        if len(v) >= 3 and v not in out:
            out.append(v)
    return out


def identity_proof(org: str, legal_name: str, text: str, record: dict | None = None, host: str = "") -> dict:
    """Graded evidence that a page belongs to this company.

    1 org_number — the nine digits printed on the page. Unambiguous.
    2 name_and_place — distinctive legal-name tokens plus a registered locality on the page.
    2 name_and_domain — distinctive tokens on a page whose domain is the company's own name spelled out.
    3 name only, on an unrelated domain — recorded as ambiguous, never published: two companies can
      share a brand, and one wrong-company publication can void an entire run.
    """
    if org and org in org_numbers_in(text):
        return {"level": 1, "publishable": True, "proof": f"organisation number {org} printed on page"}
    name_ok, reason = name_match(legal_name, text)
    if not name_ok:
        return {"level": 0, "publishable": False, "proof": reason}
    places = [p for p in place_tokens(record or {}) if p in text.lower()]
    if places:
        return {"level": 2, "publishable": True, "proof": f"{reason}; registered locality on page: {places}"}
    if host:
        derived = domain_derived_from_name(legal_name, host)
        if derived:
            return {"level": 2, "publishable": True, "proof": f"{reason}; {derived}"}
    return {"level": 3, "publishable": False, "proof": f"{reason}; no organisation number, locality or matching domain"}


def mention_identity_proof(org: str, legal_name: str, text: str) -> dict:
    """Proof used for third-party text (articles, posts), where no candidate-generation signal supports
    the match. Stricter than page proof: the organisation number, or the registered name spelled as a
    phrase, or two or more distinctive name tokens including the brand. A single distinctive word is
    not enough outside the company's own domain.
    """
    if org and org in org_numbers_in(text):
        return {"level": 1, "publishable": True, "proof": f"organisation number {org} appears in the text"}
    lowered = re.sub(r"\s+", " ", text.lower())
    for phrase in full_name_strings(legal_name):
        if phrase in lowered:
            return {"level": 2, "publishable": True, "proof": f"registered name '{phrase}' appears verbatim in the text"}
    tokens = name_tokens(legal_name)
    hits = [t for t in tokens if t in lowered]
    if len(hits) >= 2 and tokens and tokens[0] in hits:
        return {"level": 2, "publishable": True, "proof": f"brand and {len(hits) - 1} further name tokens appear: {hits}"}
    return {"level": 0, "publishable": False, "proof": f"no organisation number and no full registered name in the text (tokens present: {hits})"}


def normalise_host(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


DEEP_PATHS = ("/om", "/om-oss", "/about", "/contact", "/kontakt", "/about-us", "/society", "/company-info")


def settled(org: str, legal_name: str, text: str, record: dict | None = None, host: str = "") -> dict:
    return identity_proof(org, legal_name, text, record, host)


def verify_site(
    org: str,
    legal_name: str,
    hosts: list[str],
    record: dict | None = None,
    max_fetches: int = 3,
    deep: bool = True,
    probe: bool = False,
    deadline: float | None = None,
) -> dict:
    """Return the site for this company, or nothing.

    Candidate hosts are resolved in parallel first: a name generates dozens of plausible domains and
    resolving them one at a time costs more than every registry call for the company combined, and the
    batch has a latency budget. Only domains that actually resolve are fetched, in likelihood order,
    and a fetch is followed by the identity pages (/om, /contact) only when the homepage does not
    already settle it.

    A homepage that carries neither the number nor the full legal name is not evidence of a wrong
    domain: subsidiaries put their brand on the homepage and their legal identity elsewhere. Measured
    2026-10-21 on 300 sampled companies, most discovery failures were domains that resolved correctly
    and were rejected by a single-page test.

    probe=True is for generated candidates — domains guessed from the company name, most of which do not
    exist. There one attempt with a short timeout is the right amount of interest, because the retry
    chain (browser-UA recovery plus backoff) was measured at up to 100 s per dead domain and that is what
    put this batch's per-company p95 at 215 s. A host the register itself recorded, or one taken from the
    company's registered e-mail, is kept on the full path: a 403 there is worth a second approach.
    """
    from concurrent.futures import ThreadPoolExecutor

    fetch_timeout = 6 if probe else 8
    with ThreadPoolExecutor(max_workers=12) as pool:
        alive = [h for h, ok in zip(hosts, pool.map(resolves, hosts)) if ok]
    tried = 0
    live: list[dict] = []
    best: dict | None = None
    for host in alive:
        if deadline is not None and time.monotonic() > deadline:
            break
        if not resolves(host):
            continue
        if tried >= max_fetches:
            break
        tried += 1
        first = fetch.get("https://" + host + "/", timeout=fetch_timeout, max_bytes=400_000, probe=probe)
        if first is None or first.status != 200 or len(first.body) < 200:
            continue
        docs = [first]
        text = first.text()
        verdict = settled(org, legal_name, text, record, host)
        if not verdict["publishable"] and deep:
            for path in DEEP_PATHS[:1 if probe else 2]:
                page = fetch.get("https://" + host + path, timeout=fetch_timeout, max_bytes=250_000, probe=probe)
                if page is None or page.status != 200 or len(page.body) < 200:
                    continue
                docs.append(page)
                text += "\n" + page.text()
                candidate = settled(org, legal_name, text, record, host)
                if candidate["level"] > verdict["level"]:
                    verdict = candidate
                if verdict["publishable"]:
                    break
        entry = {
            "host": host,
            "url": docs[0].url,
            "status": docs[0].status,
            "final_host": normalise_host(docs[0].url),
            "pages": [d.url for d in docs],
            "matched_orgs": sorted(o for o in org_numbers_in(text) if o),
            "proof": verdict["proof"],
            "level": verdict["level"],
            "strong": verdict["publishable"],
            "doc": docs[0],
            "docs": docs,
            "text": text,
        }
        live.append(entry)
        if best is None or entry["level"] > best["level"]:
            best = entry
        if verdict["publishable"]:
            break
    return {"tried": tried, "live": live, "best": best}


if __name__ == "__main__":
    import sys

    slugs = name_slugs("SANDNES ELEKTRISKE AS")
    assert slugs[:2] == ["sandneselektriske", "sandnes-elektriske"], slugs[:2]
    assert "se" in slugs or "sandnes" in slugs, slugs
    # æ/ø/å both spellings must appear for names that carry them, and '&' must not become a token.
    s2 = name_slugs("KÅRØ & MØLLER AS")
    joined = [s for s in s2 if "moeller" in s or "moller" in s]
    assert any("oe" in s for s in joined) and any("o" in s and "oe" not in s for s in joined), s2[:8]
    assert not any("&" in s for s in s2), s2[:8]
    assert org_numbers_in("Org.nr 976 605 713") == {"976605713"}, org_numbers_in("x")
    assert org_numbers_in("organisasjonsnummer: 810034882") == {"810034882"}
    assert org_numbers_in('"organizationNumber":"976605713"') == {"976605713"}
    assert registrable_domain("www.sandneselektriske.no") == "sandneselektriske.no"
    assert email_candidates("post@sandneselektriske.no")[0] == "sandneselektriske.no", email_candidates("post@sandneselektriske.no")
    assert email_candidates("info@online.no") == [], "a shared mailbox is not a lead"
    assert email_candidates("post@mail.fjord1.no")[0] == "fjord1.no", "a mail subdomain must fall back to the registrable domain"
    # Graded proof: the number beats the name, the name plus a town beats the name alone.
    page = "Sandnes Elektriske AS provides electrical services in Sandnes." + "org.nr 810 034 882"
    g1 = identity_proof("810034882", "SANDNES ELEKTRISKE AS", page, {})
    assert g1["level"] == 1 and g1["publishable"], g1
    g2 = identity_proof("999999999", "SANDNES ELEKTRISKE AS", page, {"kommune": "SANDNES"})
    assert g2["level"] == 2 and g2["publishable"], g2
    g3 = identity_proof("999999999", "SANDNES ELEKTRISKE AS", page, {"kommune": "TROMSØ"})
    assert g3["level"] == 3 and not g3["publishable"], g3
    g0 = identity_proof("111111111", "AKUR MODUL AS", page, {})
    assert g0["level"] == 0, g0
    # The domain rule: a page whose domain is the registered name spelled out is corroborating.
    assert domain_derived_from_name("TEAM TUR AS", "teamtur.no") != "", "full-name domain must be recognised"
    assert domain_derived_from_name("TEAM TUR AS", "tur-team.no") == "", "reordered tokens are not the same claim"
    assert domain_derived_from_name("VIRAL AS", "viral.no") == "", "a four-letter brand on its own is too weak"
    assert domain_derived_from_name("GAUPSET HOLDING AS", "gaupset.no") != "", "gaupset is distinctive enough"
    # Norwegian characters: the name is registered with ø, the domain is typed without it.
    assert domain_derived_from_name("TORBJØRN PEDERSEN AS", "torbjornpedersen.no") != "", "ASCII transliteration must match"
    assert domain_derived_from_name("TORBJØRN PEDERSEN AS", "torbjoernpedersen.no") != "", "ae/oe spelling must also match"
    assert domain_derived_from_name("KÅRØ & MØLLER AS", "karomoller.no") != "", "a/o transliteration must match"
    weak = identity_proof("999999999", "TEAM TUR AS", "Team Tur offers guided trips in the mountains.", {"kommune": "OSLO"}, "teamtur.no")
    assert weak["level"] == 2 and weak["publishable"], weak
    same_text_other_domain = identity_proof("999999999", "TEAM TUR AS", "Team Tur offers guided trips in the mountains.", {"kommune": "OSLO"}, "someothersite.no")
    assert same_text_other_domain["level"] == 3 and not same_text_other_domain["publishable"], same_text_other_domain
    assert normalise_host("https://www.kitron.com/solutions") == "kitron.com"
    # Mention proof is stricter than page proof: a bare brand mention in third-party text is not enough.
    article = "Kitron delivered strong results this quarter."
    m1 = mention_identity_proof("976605713", "KITRON ASA", article)
    assert m1["level"] == 0 and not m1["publishable"], m1
    m2 = mention_identity_proof("976605713", "KITRON ASA", "Kitron ASA reported quarterly results.")
    assert m2["level"] == 2 and m2["publishable"], m2
    m3 = mention_identity_proof("976605713", "KITRON ASA", "Kitron (OSL:KIT), org.nr 976 605 713, reported results.")
    assert m3["level"] == 1, m3
    print(
        f"discover self-test OK: {len(slugs)} slug variants with both transliterations, "
        f"graded page proof 1/2/3/0 correct, mention proof rejects a bare brand mention"
    )

    if "--live" in sys.argv:
        res = verify_site("976605713", "KITRON ASA", ["kitron.com", "kitron.no"], {}, max_fetches=2, deep=False)
        hit = res.get("best")
        assert hit and hit["level"] in (1, 2), res["live"]
        assert hit["final_host"] == "kitron.com", hit
        print(f"live probe OK: KITRON ASA verified at {hit['url']} ({hit['proof']})")
