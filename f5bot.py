"""
f5bot.py — Searches Reddit and Hacker News for keyword mentions (lead signals).

Inspired by the F5Bot.com approach: monitor public forums for people asking
about products/services you sell, then reach out.

Uses only public, unauthenticated APIs:
  - Reddit  → https://www.reddit.com/search.json
  - HN      → Algolia HN Search  https://hn.algolia.com/api/v1/search
"""

import logging
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "LeadMonitor/1.0 (research bot; contact: admin@example.com)"
}
TIMEOUT = 12


# ── Reddit ─────────────────────────────────────────────────────────────────────

def _search_reddit(keyword: str, limit: int = 25) -> list[dict]:
    url = "https://www.reddit.com/search.json"
    params = {
        "q": keyword,
        "sort": "new",
        "limit": min(limit, 100),
        "type": "link",
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Reddit search failed for %r: %s", keyword, exc)
        return []

    posts = []
    for child in data.get("data", {}).get("children", []):
        p = child.get("data", {})
        created = datetime.fromtimestamp(
            p.get("created_utc", 0), tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M UTC")
        posts.append(
            {
                "source": "reddit",
                "keyword": keyword,
                "title": p.get("title", ""),
                "url": f"https://www.reddit.com{p.get('permalink', '')}",
                "subreddit": p.get("subreddit_name_prefixed", ""),
                "author": p.get("author", ""),
                "score": p.get("score", 0),
                "num_comments": p.get("num_comments", 0),
                "selftext_snippet": (p.get("selftext") or "")[:300],
                "created": created,
            }
        )
    return posts


# ── Hacker News ────────────────────────────────────────────────────────────────

def _search_hn(keyword: str, limit: int = 15) -> list[dict]:
    url = "https://hn.algolia.com/api/v1/search"
    params = {
        "query": keyword,
        "tags": "story",
        "hitsPerPage": min(limit, 50),
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("HN search failed for %r: %s", keyword, exc)
        return []

    posts = []
    for hit in data.get("hits", []):
        ts = hit.get("created_at", "")
        posts.append(
            {
                "source": "hackernews",
                "keyword": keyword,
                "title": hit.get("title", ""),
                "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                "author": hit.get("author", ""),
                "score": hit.get("points", 0),
                "num_comments": hit.get("num_comments", 0),
                "selftext_snippet": "",
                "subreddit": "",
                "created": ts,
            }
        )
    return posts


# ── public API ─────────────────────────────────────────────────────────────────

def monitor_keywords(
    keywords: list[str],
    sources: list[str] | None = None,
    reddit_limit: int = 25,
    hn_limit: int = 15,
) -> tuple[list[dict], list[str]]:
    """
    Search Reddit and/or HN for each keyword.

    Returns (results, errors).
    """
    if sources is None:
        sources = ["reddit", "hn"]

    results: list[dict] = []
    errors: list[str] = []

    for kw in keywords:
        if "reddit" in sources:
            try:
                posts = _search_reddit(kw, limit=reddit_limit)
                results.extend(posts)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Reddit / {kw!r}: {exc}")
            time.sleep(1)  # Reddit rate-limit: ~1 req/s unauthenticated

        if "hn" in sources:
            try:
                posts = _search_hn(kw, limit=hn_limit)
                results.extend(posts)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"HN / {kw!r}: {exc}")
            time.sleep(0.3)

    return results, errors
