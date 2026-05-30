"""
f5bot.py – Reddit & Hacker News keyword monitoring (F5Bot-style).

Searches Reddit and Hacker News for recent mentions of each keyword,
helping surface live conversations where potential leads are actively
asking about or discussing topics relevant to your business.

Reddit is queried via its public JSON API (no auth required).
Hacker News is queried via the Algolia search API (free, no auth).
"""

from __future__ import annotations

import re
import time
from typing import Any

import requests

_HEADERS = {
    "User-Agent": "ScraperLeads/1.0 (lead monitoring; contact admin@example.com)",
    "Accept": "application/json",
}
_TIMEOUT = 12  # seconds


# ── Helpers ───────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", " ", text or "")


def _truncate(text: str, max_len: int = 320) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


# ── Reddit ────────────────────────────────────────────────────────

def _search_reddit(keyword: str, limit: int = 25) -> list[dict[str, Any]]:
    """Search Reddit for recent posts/comments matching *keyword*."""
    url = "https://www.reddit.com/search.json"
    params = {
        "q": keyword,
        "sort": "new",
        "limit": min(limit, 100),
        "type": "link,comment",
        "t": "month",
    }
    try:
        resp = requests.get(url, headers=_HEADERS, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        return [{"_error": f"Reddit: tiempo de espera agotado para '{keyword}'"}]
    except Exception as exc:
        return [{"_error": f"Reddit search failed ({keyword}): {exc}"}]

    items: list[dict[str, Any]] = []
    for child in data.get("data", {}).get("children", []):
        d = child.get("data", {})
        is_comment = child.get("kind") == "t1"
        body = d.get("body") or d.get("selftext") or d.get("title") or ""
        items.append({
            "platform": "Reddit",
            "type": "comment" if is_comment else "post",
            "title": d.get("title") or d.get("link_title") or "(comentario)",
            "snippet": _truncate(body),
            "author": d.get("author", ""),
            "subreddit": d.get("subreddit", ""),
            "url": "https://reddit.com" + d.get("permalink", ""),
            "score": d.get("score", 0),
            "created_utc": int(d.get("created_utc") or 0),
            "keyword": keyword,
        })
    return items


# ── Hacker News ───────────────────────────────────────────────────

def _search_hn(keyword: str, limit: int = 15) -> list[dict[str, Any]]:
    """Search Hacker News for recent stories/comments matching *keyword*."""
    url = "https://hn.algolia.com/api/v1/search_by_date"
    params = {
        "query": keyword,
        "tags": "(story,comment)",
        "hitsPerPage": min(limit, 50),
    }
    try:
        resp = requests.get(url, headers=_HEADERS, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        return [{"_error": f"HN: tiempo de espera agotado para '{keyword}'"}]
    except Exception as exc:
        return [{"_error": f"HN search failed ({keyword}): {exc}"}]

    items: list[dict[str, Any]] = []
    for hit in data.get("hits", []):
        tags = hit.get("_tags", [])
        is_comment = "comment" in tags
        raw_body = (
            hit.get("comment_text")
            or hit.get("story_text")
            or hit.get("title")
            or ""
        )
        body = _strip_html(raw_body)
        object_id = hit.get("objectID", "")
        hn_url = f"https://news.ycombinator.com/item?id={object_id}" if object_id else ""

        # Parse ISO timestamp to unix if available
        created = 0
        raw_ts = hit.get("created_at_i") or hit.get("created_at")
        if isinstance(raw_ts, int):
            created = raw_ts

        items.append({
            "platform": "Hacker News",
            "type": "comment" if is_comment else "story",
            "title": hit.get("title") or hit.get("story_title") or "(comentario)",
            "snippet": _truncate(body),
            "author": hit.get("author", ""),
            "subreddit": "",
            "url": hn_url,
            "score": hit.get("points") or 0,
            "created_utc": created,
            "keyword": keyword,
        })
    return items


# ── Public API ────────────────────────────────────────────────────

def monitor_keywords(
    keywords: list[str],
    sources: list[str] | None = None,
    reddit_limit: int = 25,
    hn_limit: int = 15,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Search Reddit and/or HN for each keyword.

    Args:
        keywords: List of keywords to search for.
        sources: List of sources to query. Valid values: "reddit", "hn".
                 Defaults to both.
        reddit_limit: Max results per keyword from Reddit (max 100).
        hn_limit: Max results per keyword from HN (max 50).

    Returns:
        Tuple of (results, errors).  Results are sorted newest-first.
    """
    if sources is None:
        sources = ["reddit", "hn"]

    all_results: list[dict[str, Any]] = []
    errors: list[str] = []

    for kw in keywords:
        if "reddit" in sources:
            for item in _search_reddit(kw, reddit_limit):
                if "_error" in item:
                    errors.append(item["_error"])
                else:
                    all_results.append(item)
            # Polite delay – Reddit rate-limits aggressive clients
            time.sleep(1.0)

        if "hn" in sources:
            for item in _search_hn(kw, hn_limit):
                if "_error" in item:
                    errors.append(item["_error"])
                else:
                    all_results.append(item)

    # Sort newest first (Reddit items have created_utc; HN items may have 0)
    all_results.sort(key=lambda x: x.get("created_utc", 0), reverse=True)
    return all_results, errors
