"""
scraper.py – Core web-scraping logic.

For each domain we:
  1. Normalise the URL (add https:// if missing).
  2. Fetch the page with requests + a realistic User-Agent.
  3. Parse the HTML with BeautifulSoup and extract visible text.
  4. Check every keyword against the full text (case-insensitive).
  5. Return a list of result dicts and a list of error strings.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
}

_TIMEOUT = 15  # seconds


def _normalise_url(domain: str) -> str:
    """Ensure the domain has a scheme so requests can fetch it."""
    domain = domain.strip().rstrip("/")
    if not re.match(r"^https?://", domain, re.IGNORECASE):
        domain = "https://" + domain
    parsed = urlparse(domain)
    # Keep only scheme + netloc + path; drop any stray query/fragment
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", "", ""))


def _visible_text(soup: BeautifulSoup) -> str:
    """Extract human-readable text, ignoring scripts and styles."""
    for tag in soup(["script", "style", "noscript", "head"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def _scrape_one(domain: str, keywords: list[str]) -> dict[str, Any]:
    url = _normalise_url(domain)
    result: dict[str, Any] = {
        "domain": domain,
        "url": url,
        "status": None,
        "found_keywords": [],
        "keyword_matches": {},  # keyword -> list of short context snippets
        "error": None,
    }

    try:
        response = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT, allow_redirects=True)
        result["status"] = response.status_code

        if response.status_code >= 400:
            result["error"] = f"HTTP {response.status_code}"
            return result

        soup = BeautifulSoup(response.text, "html.parser")
        text = _visible_text(soup)
        text_lower = text.lower()

        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in text_lower:
                result["found_keywords"].append(kw)
                # Collect up to 3 short context snippets (±60 chars around match)
                snippets: list[str] = []
                start = 0
                while len(snippets) < 3:
                    idx = text_lower.find(kw_lower, start)
                    if idx == -1:
                        break
                    snippet_start = max(0, idx - 60)
                    snippet_end = min(len(text), idx + len(kw_lower) + 60)
                    snippet = text[snippet_start:snippet_end].replace("\n", " ").strip()
                    snippets.append(f"...{snippet}...")
                    start = idx + 1
                result["keyword_matches"][kw] = snippets

    except requests.exceptions.SSLError:
        # Retry with HTTP if SSL fails
        http_url = url.replace("https://", "http://", 1)
        try:
            response = requests.get(http_url, headers=_HEADERS, timeout=_TIMEOUT, allow_redirects=True)
            result["url"] = http_url
            result["status"] = response.status_code
            soup = BeautifulSoup(response.text, "html.parser")
            text = _visible_text(soup)
            text_lower = text.lower()
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in text_lower:
                    result["found_keywords"].append(kw)
                    snippets = []
                    start = 0
                    while len(snippets) < 3:
                        idx = text_lower.find(kw_lower, start)
                        if idx == -1:
                            break
                        snippet_start = max(0, idx - 60)
                        snippet_end = min(len(text), idx + len(kw_lower) + 60)
                        snippet = text[snippet_start:snippet_end].replace("\n", " ").strip()
                        snippets.append(f"...{snippet}...")
                        start = idx + 1
                    result["keyword_matches"][kw] = snippets
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)
    except requests.exceptions.ConnectionError as exc:
        result["error"] = f"No se pudo conectar: {exc}"
    except requests.exceptions.Timeout:
        result["error"] = "Tiempo de espera agotado"
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)

    return result


def scrape_domains(
    domains: list[str], keywords: list[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Scrape all domains and return (results, errors)."""
    results: list[dict[str, Any]] = []
    errors: list[str] = []

    for domain in domains:
        res = _scrape_one(domain, keywords)
        results.append(res)
        if res["error"]:
            errors.append(f"{domain}: {res['error']}")

    return results, errors
