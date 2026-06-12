"""
SBA Business Search — Website Finder (Google Places replacement)
Finds a business's official website without any paid API:

  1. DuckDuckGo search ("name city state") via the ddgs package
     - directory/aggregator domains are filtered out
     - candidates scored by business-name token overlap with domain + title
  2. Domain guessing (joespizza.com, joes-pizza.com, ...) as fallback
  3. Identity verification: fetch the homepage and confirm the business
     name and location actually appear on it before trusting the match

Returns the same shape places_lookup() used to, so /api/enrich,
the frontend, and the CSV export work unchanged.
"""
import re
import time
from urllib.parse import urlparse, quote_plus

from ddgs import DDGS

from scraper import fetch  # reuses the browser-header session + timeout

# ── Domains that are never a business's own website ──────────────────────────
AGGREGATOR_DOMAINS = {
    "yelp.com", "tripadvisor.com", "facebook.com", "instagram.com",
    "linkedin.com", "twitter.com", "x.com", "youtube.com", "tiktok.com",
    "yellowpages.com", "bbb.org", "mapquest.com", "foursquare.com",
    "google.com", "maps.google.com", "opentable.com", "doordash.com",
    "grubhub.com", "ubereats.com", "seamless.com", "postmates.com",
    "manta.com", "dnb.com", "zoominfo.com", "buzzfile.com", "dandb.com",
    "opencorporates.com", "bizapedia.com", "corporationwiki.com",
    "chamberofcommerce.com", "superpages.com", "citysearch.com",
    "merchantcircle.com", "angi.com", "angieslist.com", "thumbtack.com",
    "houzz.com", "homeadvisor.com", "porch.com", "nextdoor.com",
    "indeed.com", "glassdoor.com", "ziprecruiter.com",
    "zillow.com", "loopnet.com", "realtor.com",
    "sba.gov", "usaspending.gov", "federalpay.org", "propublica.org",
    "wikipedia.org", "crunchbase.com", "pitchbook.com",
    "groupon.com", "amazon.com", "ebay.com", "etsy.com",
    "apple.com", "play.google.com", "menupages.com", "allmenus.com",
    "restaurantji.com", "birdeye.com", "podium.com",
}

# Legal suffixes to strip when matching the business name
LEGAL_SUFFIXES = re.compile(
    r"\b(llc|l\.l\.c\.|inc|incorporated|corp|corporation|co|company|"
    r"ltd|limited|llp|lp|pllc|pc|p\.c\.|pa|p\.a\.|dba|the)\b",
    re.IGNORECASE,
)

SEARCH_DELAY = 1.0  # polite delay between DDG queries (seconds)


def _name_tokens(business_name):
    """Lowercase, strip legal suffixes and punctuation, return word tokens."""
    cleaned = LEGAL_SUFFIXES.sub(" ", business_name.lower())
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    return [t for t in cleaned.split() if len(t) > 1]


def _root_domain(url):
    """'https://www.foo.bar.com/x' -> 'bar.com' (good enough for .com/.net/.org)."""
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _score_candidate(tokens, url, title):
    """How likely is this search result the business's own site? 0.0–1.0+"""
    domain = _root_domain(url)
    title_lower = (title or "").lower()
    domain_compact = domain.split(".")[0]

    if not tokens:
        return 0.0

    in_domain = sum(1 for t in tokens if t in domain_compact)
    in_title = sum(1 for t in tokens if t in title_lower)

    score = 0.6 * (in_domain / len(tokens)) + 0.4 * (in_title / len(tokens))
    # A domain that is exactly the squashed business name is a strong signal
    if domain_compact == "".join(tokens):
        score += 0.5
    # Deep paths (/Biz-Name/10751977.htm) are directory listings, not homepages
    path_depth = len([p for p in urlparse(url).path.split("/") if p])
    if path_depth >= 2:
        score -= 0.25
    return score


def _search(query, max_results=8, attempts=2):
    """DDG search with one retry — results and availability vary run to run."""
    for attempt in range(attempts):
        try:
            hits = DDGS().text(query, max_results=max_results)
            if hits:
                return hits
        except Exception:
            pass
        time.sleep(SEARCH_DELAY * (attempt + 1))
    return []


def _verify_site(url, tokens, city, state):
    """
    Fetch the homepage and check the business identity actually appears.
    Returns (verified: bool, matched_title: str|None).
    """
    soup = fetch(url)
    if soup is None:
        return False, None

    text = soup.get_text(" ", strip=True).lower()
    title = soup.title.string.strip() if soup.title and soup.title.string else None

    name_hits = sum(1 for t in tokens if t in text)
    name_ok = tokens and (name_hits / len(tokens)) >= 0.5

    location_ok = bool(
        (city and city.lower() in text) or
        (state and re.search(rf"\b{re.escape(state.lower())}\b", text))
    )
    return (name_ok and location_ok), title


def _candidate_domains(tokens):
    """Guess likely domains from the business name."""
    squashed = "".join(tokens)
    hyphened = "-".join(tokens)
    guesses = []
    for stem in dict.fromkeys([squashed, hyphened]):  # dedup, keep order
        if 3 <= len(stem) <= 40:
            guesses.append(f"https://www.{stem}.com")
            guesses.append(f"https://{stem}.com")
    return guesses


def _maps_search_url(name, city, state):
    """Key-free Google Maps link (official URL scheme, no API needed)."""
    q = quote_plus(f"{name} {city} {state}")
    return f"https://www.google.com/maps/search/?api=1&query={q}"


def find_website(business_name, city, state):
    """
    Entry point — drop-in replacement for places_lookup().
    Returns: {website, phone, maps_url, match_name, source}
    `phone` is always None here (it now comes from the scraper stage).
    """
    result = {
        "website": None,
        "phone": None,
        "maps_url": _maps_search_url(business_name, city, state),
        "match_name": None,
        "source": None,
    }
    tokens = _name_tokens(business_name)
    if not tokens:
        return result

    # ── Tier 1: DuckDuckGo search ─────────────────────────────────────────────
    hits = _search(f"{business_name} {city} {state}")

    candidates = []
    for h in hits or []:
        url = h.get("href", "")
        if not url.startswith("http"):
            continue
        if _root_domain(url) in AGGREGATOR_DOMAINS:
            continue
        score = _score_candidate(tokens, url, h.get("title", ""))
        if score >= 0.4:
            candidates.append((score, url, h.get("title", "")))

    candidates.sort(key=lambda c: c[0], reverse=True)

    for score, url, title in candidates[:3]:
        verified, page_title = _verify_site(url, tokens, city, state)
        if verified:
            base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            result.update(
                website=base,
                match_name=page_title or title,
                source="search",
            )
            return result
        time.sleep(0.3)

    # ── Tier 2: domain guessing ───────────────────────────────────────────────
    for guess in _candidate_domains(tokens):
        verified, page_title = _verify_site(guess, tokens, city, state)
        if verified:
            result.update(
                website=guess.replace("https://www.", "https://"),
                match_name=page_title,
                source="domain-guess",
            )
            return result

    return result
