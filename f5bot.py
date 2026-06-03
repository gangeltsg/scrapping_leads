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
        author = p.get("author", "")
        posts.append(
            {
                "source": "reddit",
                "result_type": "post",
                "keyword": keyword,
                "title": p.get("title", ""),
                "url": f"https://www.reddit.com{p.get('permalink', '')}",
                "post_url": f"https://www.reddit.com{p.get('permalink', '')}",
                "subreddit": p.get("subreddit_name_prefixed", ""),
                "author": author,
                "author_profile_url": f"https://www.reddit.com/user/{author}" if author not in ("", "[deleted]") else "",
                "score": p.get("score", 0),
                "num_comments": p.get("num_comments", 0),
                "selftext_snippet": (p.get("selftext") or "")[:300],
                "created": created,
            }
        )
    return posts


def _search_reddit_comments(keyword: str, limit: int = 25) -> list[dict]:
    """Search Reddit *comments* for keyword mentions — finds individual users expressing needs."""
    url = "https://www.reddit.com/search.json"
    params = {
        "q": keyword,
        "sort": "new",
        "limit": min(limit, 100),
        "type": "comment",
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Reddit comment search failed for %r: %s", keyword, exc)
        return []

    comments = []
    for child in data.get("data", {}).get("children", []):
        p = child.get("data", {})
        if not p:
            continue
        created = datetime.fromtimestamp(
            p.get("created_utc", 0), tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M UTC")
        author = p.get("author", "")
        comments.append(
            {
                "source": "reddit",
                "result_type": "comment",
                "keyword": keyword,
                "title": p.get("link_title", ""),
                "url": f"https://www.reddit.com{p.get('permalink', '')}",
                "post_url": f"https://www.reddit.com{p.get('link_permalink', '')}",
                "subreddit": p.get("subreddit_name_prefixed", ""),
                "author": author,
                "author_profile_url": f"https://www.reddit.com/user/{author}" if author not in ("", "[deleted]") else "",
                "score": p.get("score", 0),
                "num_comments": 0,
                "selftext_snippet": (p.get("body") or "")[:300],
                "created": created,
            }
        )
    return comments


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
        hn_author = hit.get("author", "")
        posts.append(
            {
                "source": "hackernews",
                "result_type": "post",
                "keyword": keyword,
                "title": hit.get("title", ""),
                "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                "post_url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                "subreddit": "",
                "author": hn_author,
                "author_profile_url": f"https://news.ycombinator.com/user?id={hn_author}" if hn_author else "",
                "score": hit.get("points", 0),
                "num_comments": hit.get("num_comments", 0),
                "selftext_snippet": "",
                "created": ts,
            }
        )
    return posts


# ── Stack Overflow ─────────────────────────────────────────────────────────────

def _search_stackoverflow(keyword: str, limit: int = 10) -> list[dict]:
    """Search Stack Overflow questions — useful for finding developers/tech buyers."""
    url = "https://api.stackexchange.com/2.3/search"
    params = {
        "intitle": keyword,
        "site": "stackoverflow",
        "sort": "creation",
        "order": "desc",
        "pagesize": min(limit, 50),
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("StackOverflow search failed for %r: %s", keyword, exc)
        return []

    posts = []
    for item in data.get("items", []):
        owner = item.get("owner", {})
        so_author = owner.get("display_name", "")
        so_author_id = owner.get("user_id", "")
        created_ts = item.get("creation_date", 0)
        created = (
            datetime.fromtimestamp(created_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if created_ts
            else ""
        )
        link = item.get("link", "")
        posts.append(
            {
                "source": "stackoverflow",
                "result_type": "post",
                "keyword": keyword,
                "title": item.get("title", ""),
                "url": link,
                "post_url": link,
                "subreddit": ", ".join(item.get("tags", [])),
                "author": so_author,
                "author_profile_url": f"https://stackoverflow.com/users/{so_author_id}" if so_author_id else "",
                "score": item.get("score", 0),
                "num_comments": item.get("answer_count", 0),
                "selftext_snippet": "",
                "created": created,
            }
        )
    return posts


# ── public API ─────────────────────────────────────────────────────────────────

def monitor_keywords(
    keywords: list[str],
    sources: list[str] | None = None,
    reddit_limit: int = 25,
    hn_limit: int = 15,
    so_limit: int = 10,
    include_comments: bool = True,
) -> tuple[list[dict], list[str]]:
    """
    Search Reddit, HN, and/or Stack Overflow for each keyword.
    When include_comments=True also searches Reddit comments (higher signal for buying intent).

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
                errors.append(f"Reddit posts / {kw!r}: {exc}")
            time.sleep(1)  # Reddit rate-limit: ~1 req/s unauthenticated

            if include_comments:
                try:
                    comments = _search_reddit_comments(kw, limit=reddit_limit)
                    results.extend(comments)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"Reddit comentarios / {kw!r}: {exc}")
                time.sleep(1)

        if "hn" in sources:
            try:
                posts = _search_hn(kw, limit=hn_limit)
                results.extend(posts)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"HN / {kw!r}: {exc}")
            time.sleep(0.3)

        if "stackoverflow" in sources:
            try:
                posts = _search_stackoverflow(kw, limit=so_limit)
                results.extend(posts)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"StackOverflow / {kw!r}: {exc}")
            time.sleep(0.5)

    return results, errors
