"""
scraper.py — Scrapes a list of domains looking for contact info and keyword matches.

For each domain it visits:
  - homepage  (/)
  - /contact, /contacto, /about, /acerca (if reachable)

Extracts:
  - emails
  - phone numbers
  - social-media links (WhatsApp, LinkedIn, Instagram, Facebook, Twitter/X)
  - which keywords were found on the page
"""

import re
import time
import logging
import json as _json
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── constants ──────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; LeadScraper/1.0; +https://github.com)"
    )
}
TIMEOUT = 10  # seconds per request
EXTRA_PATHS = ["/contact", "/contacto", "/about", "/acerca", "/about-us"]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(
    r"(?<!\d)(\+?[\d\s\-().]{7,20})(?!\d)",
)
SOCIAL_PATTERNS = {
    "whatsapp": re.compile(r"wa\.me/|whatsapp\.com/send", re.I),
    "linkedin": re.compile(r"linkedin\.com/(in|company)/", re.I),
    "instagram": re.compile(r"instagram\.com/", re.I),
    "facebook": re.compile(r"facebook\.com/", re.I),
    "twitter": re.compile(r"twitter\.com/|x\.com/", re.I),
}


# ── helpers ────────────────────────────────────────────────────────────────────

def _normalise_domain(domain: str) -> str:
    domain = domain.strip()
    if not domain.startswith(("http://", "https://")):
        domain = "https://" + domain
    parsed = urlparse(domain)
    return f"{parsed.scheme}://{parsed.netloc}"


def _fetch(url: str) -> tuple[str, dict] | tuple[None, None]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if resp.ok and "text/html" in resp.headers.get("Content-Type", ""):
            return resp.text, dict(resp.headers)
    except Exception as exc:
        logger.debug("fetch error %s: %s", url, exc)
    return None, None


def _extract_emails(text: str) -> set[str]:
    return {m.lower() for m in EMAIL_RE.findall(text)}


def _extract_phones(soup: BeautifulSoup) -> set[str]:
    phones: set[str] = set()
    # prefer <a href="tel:...">
    for a in soup.find_all("a", href=re.compile(r"^tel:", re.I)):
        number = re.sub(r"[^\d+]", "", a["href"].replace("tel:", ""))
        if len(number) >= 7:
            phones.add(number)
    # fallback: regex on visible text
    for match in PHONE_RE.finditer(soup.get_text(" ")):
        candidate = match.group(1).strip()
        digits = re.sub(r"\D", "", candidate)
        if 7 <= len(digits) <= 15:
            phones.add(candidate)
    return phones


def _extract_socials(soup: BeautifulSoup) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {k: [] for k in SOCIAL_PATTERNS}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        for name, pattern in SOCIAL_PATTERNS.items():
            if pattern.search(href):
                found[name].append(href)
    return {k: list(set(v)) for k, v in found.items() if v}


def _keywords_found(text: str, keywords: list[str]) -> list[str]:
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]


def _extract_company_name(soup: BeautifulSoup) -> str:
    og = soup.find("meta", property="og:site_name")
    if og and og.get("content"):
        return og["content"].strip()
    title = soup.find("title")
    if title:
        raw = title.get_text().strip()
        for sep in ["|", "-", "·", "–", "—", ":"]:
            if sep in raw:
                return raw.split(sep)[0].strip()
        return raw
    return ""


def _extract_meta_description(soup: BeautifulSoup) -> str:
    for attrs in [{"name": "description"}, {"property": "og:description"}]:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return tag["content"].strip()[:300]
    return ""


def _extract_address(soup: BeautifulSoup) -> str:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = _json.loads(script.string or "")
            if isinstance(data, list):
                data = data[0] if data else {}
            addr = data.get("address", {})
            if isinstance(addr, dict):
                parts = [
                    addr.get("streetAddress", ""),
                    addr.get("addressLocality", ""),
                    addr.get("addressRegion", ""),
                    addr.get("postalCode", ""),
                    addr.get("addressCountry", ""),
                ]
                result = ", ".join(p for p in parts if p)
                if result:
                    return result
        except Exception:
            pass
    tag = soup.find(attrs={"itemprop": "address"})
    if tag:
        return tag.get_text(" ").strip()[:200]
    return ""


def _detect_technology(html: str, headers: dict) -> list[str]:
    techs: list[str] = []
    html_lower = html.lower()
    if "cdn.shopify.com" in html_lower or "shopify.com/s/files" in html_lower:
        techs.append("Shopify")
    if 'content="wordpress' in html_lower or "wp-content/themes" in html_lower:
        techs.append("WordPress")
    if "wix.com/_api" in html_lower or "static.wixstatic.com" in html_lower:
        techs.append("Wix")
    if "squarespace.com" in html_lower and "static1.squarespace" in html_lower:
        techs.append("Squarespace")
    if "webflow.com" in html_lower and "webflow.js" in html_lower:
        techs.append("Webflow")
    if "tiendanube.com" in html_lower or "mitiendanube.com" in html_lower:
        techs.append("Tiendanube")
    server = headers.get("Server", headers.get("server", ""))
    if server and server.lower() not in ("cloudflare", ""):
        techs.append(f"Server:{server}")
    return techs


def _extract_whatsapp_numbers(socials: dict) -> list[str]:
    numbers: list[str] = []
    for url in socials.get("whatsapp", []):
        match = re.search(r"wa\.me/(\d+)", url)
        if match:
            numbers.append("+" + match.group(1))
    return list(set(numbers))


# ── public API ─────────────────────────────────────────────────────────────────

def scrape_domain(domain: str, keywords: list[str]) -> dict:
    base = _normalise_domain(domain)
    urls_to_visit = [base] + [base + p for p in EXTRA_PATHS]

    all_emails: set[str] = set()
    all_phones: set[str] = set()
    all_socials: dict[str, list[str]] = {}
    matched_keywords: set[str] = set()
    pages_scraped = 0
    company_name = ""
    description = ""
    address = ""
    technologies: set[str] = set()

    for url in urls_to_visit:
        html, resp_headers = _fetch(url)
        if not html:
            continue
        pages_scraped += 1
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(" ")

        if not company_name:
            company_name = _extract_company_name(soup)
        if not description:
            description = _extract_meta_description(soup)
        if not address:
            address = _extract_address(soup)
        technologies |= set(_detect_technology(html, resp_headers or {}))

        all_emails |= _extract_emails(text)
        all_phones |= _extract_phones(soup)
        for net, links in _extract_socials(soup).items():
            all_socials.setdefault(net, [])
            all_socials[net] = list(set(all_socials[net] + links))
        matched_keywords |= set(_keywords_found(text, keywords))

        time.sleep(0.5)  # polite delay

    whatsapp_numbers = _extract_whatsapp_numbers(all_socials)

    return {
        "domain": base,
        "company_name": company_name,
        "description": description,
        "address": address,
        "technologies": sorted(technologies),
        "pages_scraped": pages_scraped,
        "emails": sorted(all_emails),
        "phones": sorted(all_phones),
        "whatsapp_numbers": whatsapp_numbers,
        "socials": all_socials,
        "keywords_found": sorted(matched_keywords),
        "has_leads": bool(all_emails or all_phones or all_socials),
    }


def scrape_domains(
    domains: list[str], keywords: list[str]
) -> tuple[list[dict], list[str]]:
    results: list[dict] = []
    errors: list[str] = []

    for domain in domains:
        try:
            result = scrape_domain(domain, keywords)
            results.append(result)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{domain}: {exc}")

    return results, errors
