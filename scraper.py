"""
SBA Business Search — Website Contact Scraper
Visits a business website and extracts contact details from:
  1. Schema.org JSON-LD structured data (most reliable)
  2. Footer section (mailto: and tel: links)
  3. Contact / About page
  4. Regex patterns as last resort
"""
import re
import json
import time
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

# ── HTTP session with browser-like headers ────────────────────────────────────
# Many small business sites block Python's default "python-requests" user agent.
# We send a real browser header to avoid being blocked.
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
})

TIMEOUT = 8  # seconds per request

# ── Regex patterns ────────────────────────────────────────────────────────────

EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

# Matches common US phone formats:
#   (555) 555-5555  |  555-555-5555  |  555.555.5555  |  +1 555 555 5555
PHONE_RE = re.compile(
    r"(\+?1[\s\-.]?)?(\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4})"
)

# Emails that are never useful for outreach — filter these out
JUNK_EMAILS = {
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "mailer", "postmaster", "webmaster", "admin",
    "support", "help", "hello", "info",           # too generic
    "privacy", "legal", "billing", "sales",
    "example", "test", "sample",
}

# Contact-like page paths — we'll try these after the homepage
CONTACT_SLUGS = [
    "/contact", "/contact-us", "/contact_us", "/contactus",
    "/about",   "/about-us",   "/about_us",
    "/reach-us", "/get-in-touch", "/connect",
]

# ── Fetch helper ──────────────────────────────────────────────────────────────

def fetch(url, timeout=TIMEOUT):
    """Fetch a URL and return a BeautifulSoup object, or None on failure."""
    try:
        resp = SESSION.get(url, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200 and "text/html" in resp.headers.get("Content-Type", ""):
            return BeautifulSoup(resp.text, "html.parser")
    except Exception:
        pass
    return None

# ── Extraction helpers ────────────────────────────────────────────────────────

def clean_emails(raw_emails):
    """Remove junk, dedup, and return a sorted list of useful emails."""
    result = set()
    for email in raw_emails:
        email = email.lower().strip()
        local = email.split("@")[0]
        # Skip junk local parts
        if any(j in local for j in JUNK_EMAILS):
            continue
        # Skip image/file false positives (e.g. "photo@2x.png")
        if email.endswith((".png", ".jpg", ".gif", ".svg", ".jpeg", ".webp")):
            continue
        result.add(email)
    return sorted(result)

def clean_phones(raw_phones):
    """Normalise and dedup phone numbers — return 10-digit strings."""
    seen, result = set(), []
    for _, number in raw_phones:
        digits = re.sub(r"\D", "", number)
        if digits.startswith("1") and len(digits) == 11:
            digits = digits[1:]
        if len(digits) == 10 and digits not in seen:
            seen.add(digits)
            # Format as (555) 555-5555
            result.append(f"({digits[:3]}) {digits[3:6]}-{digits[6:]}")
    return result

def extract_from_soup(soup):
    """Pull emails and phones from any BeautifulSoup page."""
    emails, phones = [], []

    # 1. Explicit mailto: and tel: links — most reliable
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("mailto:"):
            email = href[7:].split("?")[0].strip()
            if email:
                emails.append(email)
        elif href.startswith("tel:"):
            phone = re.sub(r"\D", "", href[4:])
            if len(phone) >= 10:
                phones.append(("", phone[-10:]))

    # 2. Schema.org JSON-LD in <script type="application/ld+json">
    # These blocks often contain telephone, email, and contactPoint
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            # data can be a dict or a list
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    if "email" in item:
                        emails.append(item["email"])
                    if "telephone" in item:
                        phones.append(("", re.sub(r"\D", "", str(item["telephone"]))))
                    # contactPoint sub-object
                    cp = item.get("contactPoint", {})
                    if isinstance(cp, dict):
                        if "email" in cp:    emails.append(cp["email"])
                        if "telephone" in cp: phones.append(("", re.sub(r"\D", "", str(cp["telephone"]))))
        except Exception:
            pass

    # 3. Regex scan of visible text (fallback)
    text = soup.get_text(" ", strip=True)
    emails += EMAIL_RE.findall(text)
    phones += PHONE_RE.findall(text)

    return emails, phones

def extract_name_from_soup(soup):
    """
    Try to find an owner/contact person name.
    Looks in Schema.org first, then <meta> author tag.
    """
    # Schema.org
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    owner = item.get("founder") or item.get("owner") or item.get("author")
                    if isinstance(owner, dict):
                        return owner.get("name")
                    if isinstance(owner, str) and owner:
                        return owner
        except Exception:
            pass
    # Meta author tag
    meta = soup.find("meta", attrs={"name": "author"})
    if meta and meta.get("content"):
        return meta["content"].strip()
    return None

# ── Contact page finder ───────────────────────────────────────────────────────

def find_contact_url(soup, base_url):
    """
    Scan all links on the page for anything that looks like a contact page.
    Returns an absolute URL or None.
    """
    for a in soup.find_all("a", href=True):
        href = a["href"].lower().strip()
        text = a.get_text(strip=True).lower()
        if any(slug.strip("/") in href for slug in CONTACT_SLUGS) or \
           any(word in text for word in ["contact", "reach us", "get in touch"]):
            return urljoin(base_url, a["href"])
    return None

# ── Footer-focused extraction ─────────────────────────────────────────────────

def extract_from_footer(soup):
    """
    Specifically target the <footer> element — highest signal-to-noise
    for contact details on small business sites.
    """
    footer = soup.find("footer")
    if footer:
        return extract_from_soup(footer)
    # Fallback: divs/sections with footer-like class or id names
    for tag in soup.find_all(["div", "section"], class_=True):
        classes = " ".join(tag.get("class", [])).lower()
        if "footer" in classes or "contact" in classes:
            return extract_from_soup(tag)
    return [], []

# ── Main public function ──────────────────────────────────────────────────────

def scrape_contact(website_url):
    """
    Entry point. Given a business website URL, return a dict with:
      - email        : best email found (str or None)
      - phone        : best phone found (str or None)
      - contact_name : owner/contact name if found (str or None)
      - all_emails   : all unique emails found
      - all_phones   : all unique phones found
      - source       : which page the data came from
    """
    if not website_url:
        return _empty()

    # Normalise URL
    if not website_url.startswith(("http://", "https://")):
        website_url = "https://" + website_url

    base = f"{urlparse(website_url).scheme}://{urlparse(website_url).netloc}"

    all_emails, all_phones = [], []
    contact_name = None
    source = None

    # ── Step 1: Homepage ──────────────────────────────────────────────────────
    homepage = fetch(website_url)
    if homepage:
        source = "homepage"
        contact_name = extract_name_from_soup(homepage)

        # Footer first (most reliable)
        fe, fp = extract_from_footer(homepage)
        all_emails += fe
        all_phones += fp

        # Full page if footer didn't yield much
        if not all_emails and not all_phones:
            pe, pp = extract_from_soup(homepage)
            all_emails += pe
            all_phones += pp

        # ── Step 2: Contact page ──────────────────────────────────────────────
        contact_url = find_contact_url(homepage, base)
        if contact_url and contact_url != website_url:
            time.sleep(0.5)   # polite delay between requests
            contact_page = fetch(contact_url)
            if contact_page:
                source = "contact page"
                ce, cp = extract_from_soup(contact_page)
                all_emails += ce
                all_phones += cp
                if not contact_name:
                    contact_name = extract_name_from_soup(contact_page)

        # ── Step 3: Try common contact slugs if no contact link was found ─────
        elif not all_emails:
            for slug in CONTACT_SLUGS[:4]:   # only try top 4
                time.sleep(0.4)
                page = fetch(base + slug)
                if page:
                    ce, cp = extract_from_soup(page)
                    if ce or cp:
                        all_emails += ce
                        all_phones += cp
                        source = f"{slug} page"
                        break

    cleaned_emails = clean_emails(all_emails)
    cleaned_phones = clean_phones(all_phones)

    return {
        "email":        cleaned_emails[0] if cleaned_emails else None,
        "phone_scraped": cleaned_phones[0] if cleaned_phones else None,
        "contact_name": contact_name,
        "all_emails":   cleaned_emails,
        "all_phones":   cleaned_phones,
        "source":       source,
    }

def _empty():
    return {
        "email": None, "phone_scraped": None,
        "contact_name": None, "all_emails": [],
        "all_phones": [], "source": None,
    }
