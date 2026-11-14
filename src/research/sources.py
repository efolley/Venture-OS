"""URL safety, page cleaning, source labels, and the wrong-company filter.

All of this is deterministic. Page text is untrusted data and is only ever quoted.
"""

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

_UNSAFE = "Use a public HTTPS website."

# Sentence-level boilerplate: cookie banners, navigation, sign-in prompts, footers.
BOILERPLATE = re.compile(
    r"cookie|consent|privacy policy|terms of (?:use|service)|skip to (?:main )?content|"
    r"\bsign (?:in|up)\b|\blog ?in\b|subscribe|newsletter|accept all|all rights reserved|"
    r"javascript (?:is )?(?:disabled|required)|\bmenu\b",
    re.IGNORECASE,
)
_KIND_HOSTS: dict[str, tuple[str, ...]] = {
    "review": ("g2.com", "capterra.com", "trustpilot.com", "softwareadvice.com",
               "getapp.com", "gartner.com", "producthunt.com"),
    "forum": ("news.ycombinator.com", "reddit.com", "quora.com", "stackoverflow.com"),
    "aggregator": ("leadiq.com", "crunchbase.com", "zoominfo.com", "linkedin.com",
                   "pitchbook.com", "apollo.io", "rocketreach.co", "owler.com", "dnb.com",
                   "cbinsights.com", "tracxn.com"),
    "reference": ("wikipedia.org",),
    "news": ("techcrunch.com", "reuters.com", "bloomberg.com", "wsj.com", "forbes.com",
             "theverge.com", "venturebeat.com", "businesswire.com", "prnewswire.com", "cnbc.com"),
}
_NAME_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited",
    "llc", "plc", "gmbh", "ag", "sa", "technologies", "technology", "labs", "ai", "hq",
}
MIN_NAME_MENTIONS = 3
DOMAIN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


def norm(text: str) -> str:
    return " ".join(text.split())


def public_https_url(value: object) -> str:
    """Return the URL without its fragment, or raise for non-HTTPS, private, or odd URLs."""
    if not isinstance(value, str):
        raise ValueError(_UNSAFE)
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as error:
        raise ValueError(_UNSAFE) from error
    if (parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username
            or parsed.password or port not in (None, 443)):
        raise ValueError(_UNSAFE)
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError(_UNSAFE)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError(_UNSAFE)
    if address is None and not DOMAIN.match(host):
        raise ValueError(_UNSAFE)
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path, parsed.query, ""))


def normalize_website(value: str) -> tuple[str, str | None]:
    """Normalize a user website: add https:// when missing, upgrade http:// to https://.

    Returns the HTTPS URL and the original value when it was changed, else None.
    """
    raw = value.strip()
    candidate = raw
    scheme = urlsplit(raw).scheme.lower() if "://" in raw else ""
    if not scheme:
        candidate = f"https://{raw}"
    elif scheme == "http":
        candidate = "https://" + raw.split("://", 1)[1]
    url = public_https_url(candidate)
    if not urlsplit(url).path:
        url += "/"
    return url, (raw if scheme != "https" else None)


def host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".").removeprefix("www.")


def host_matches(value: str, domain: str) -> bool:
    return bool(domain) and (value == domain or value.endswith("." + domain))


def name_key(value: str) -> str:
    words = re.sub(r"[^\w\s]", " ", value.casefold()).split()
    while len(words) > 1 and words[-1] in _NAME_SUFFIXES:
        words.pop()
    return " ".join(words)


def same_company(left: str, right: str) -> bool:
    """Tolerate case, punctuation, legal suffixes, and short or long forms of 1 name."""
    a, b = name_key(left), name_key(right)
    if not a or not b:
        return False
    return a == b or a.replace(" ", "") == b.replace(" ", "") or (
        re.search(rf"\b{re.escape(a)}\b", b) is not None
        or re.search(rf"\b{re.escape(b)}\b", a) is not None
    )


def name_from_host(domain: str) -> str:
    label = domain.split(".")[0] if domain else ""
    return label.replace("-", " ").title()


def clean_text(text: str) -> str:
    """Drop sentences or lines that contain cookie, navigation, or sign-in markers."""
    pieces = re.split(r"(?<=[.!?])\s+|\n+", text)
    return " ".join(p.strip() for p in pieces if p.strip() and not BOILERPLATE.search(p))


def classify_source(url: str, company_host: str, competitor_hosts: tuple[str, ...] = ()) -> str:
    """Label a source by where it comes from. Not a credibility rating."""
    value = host(url)
    if host_matches(value, company_host):
        return "first_party"
    if any(host_matches(value, other) for other in competitor_hosts):
        return "competitor"
    for kind, domains in _KIND_HOSTS.items():
        if any(host_matches(value, domain) for domain in domains):
            return kind
    return "other"


def off_target_reason(kind: str, title: str, text: str, company: str, company_host: str) -> str | None:
    """Reject pages that are probably about a different organization.

    The company's own pages and known competitor pages pass. Aggregator pages and
    unclassified pages with fewer than 3 name mentions must also mention the website,
    because a name alone cannot separate 2 companies with the same name.
    """
    if kind in ("first_party", "competitor"):
        return None
    haystack = f"{title} {text}".casefold()
    name = name_key(company)
    mentions = len(re.findall(rf"\b{re.escape(name)}\b", haystack)) if name else 0
    if name and not mentions:
        # A name derived from a domain ("acmecloud") should still match "Acme Cloud".
        squashed = name.replace(" ", "")
        mentions = len(re.findall(re.escape(squashed), re.sub(r"[\s-]+", "", haystack)))
    mentions_host = bool(company_host) and company_host in haystack
    if name and not mentions and not mentions_host:
        return "does not mention the company"
    if company_host and not mentions_host and (
        kind == "aggregator" or (kind == "other" and mentions < MIN_NAME_MENTIONS)
    ):
        return "does not mention the company website"
    return None
