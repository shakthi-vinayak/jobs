"""Fetcher for Hacker News "Who's Hiring" threads via Algolia API."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

HN_ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search"
HN_ALGOLIA_SEARCH_BY_DATE = "https://hn.algolia.com/api/v1/search_by_date"

# Keywords to search for in HN who's hiring threads
SEARCH_TERMS = ["DevOps", "SRE", "Site Reliability", "Platform Engineer", "Cloud Engineer", "Infrastructure Engineer"]


def _is_hiring_comment(item: dict) -> bool:
    """Heuristic to check if an Algolia result is a 'Who's Hiring' comment."""
    title = (item.get("title") or "").lower()
    story_title = (item.get("story_title") or "").lower()
    return "who is hiring" in title or "who is hiring" in story_title or "whos hiring" in title


def fetch(delay: float = 1.0) -> list[dict]:
    """Fetch jobs from HN Who's Hiring via Algolia. Returns normalized job dicts."""
    jobs = []
    seen_links = set()

    for term in SEARCH_TERMS:
        try:
            time.sleep(delay)
            params = {
                "query": term,
                "tags": "comment",
                "hitsPerPage": 50,
                "numericFilters": "created_at_i>0",
            }
            resp = requests.get(
                HN_ALGOLIA_SEARCH_BY_DATE,
                params=params,
                headers={"User-Agent": "DevOps-Job-Agent/1.0"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("HN Algolia fetch failed for term '%s': %s", term, e)
            continue

        for hit in data.get("hits", []):
            object_id = hit.get("objectID", "")
            link = f"https://news.ycombinator.com/item?id={object_id}" if object_id else ""
            if not link or link in seen_links:
                continue
            seen_links.add(link)

            try:
                comment_text = hit.get("comment_text", "") or hit.get("story_text", "") or ""
                story_title = hit.get("story_title", "") or hit.get("title", "")

                # Only include items from "Who's Hiring" threads
                if not _is_hiring_comment(hit):
                    continue

                # Extract a plausible title from the first line of the comment
                first_line = comment_text.split("\n")[0].strip() if comment_text else term
                # Clean HTML entities that Algolia may include
                first_line = first_line.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
                if len(first_line) > 200:
                    first_line = first_line[:200] + "..."

                created_at = hit.get("created_at", "")

                jobs.append({
                    "source": "hackernews",
                    "link": link,
                    "title": first_line,
                    "company": "",
                    "location": "Remote (see posting)",
                    "posted_at": created_at,
                    "raw_description": comment_text[:5000],
                })
            except Exception as e:
                logger.warning("Failed to parse HN item: %s", e)
                continue

    logger.info("HN Algolia: fetched %d jobs", len(jobs))
    return jobs
