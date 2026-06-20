"""Fetcher for We Work Remotely RSS feeds."""
from __future__ import annotations

import logging
import time

import feedparser
import requests

logger = logging.getLogger(__name__)

WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "https://weworkremotely.com/categories/remote-system-admin-jobs.rss",
]


def fetch(delay: float = 1.0) -> list[dict]:
    """Fetch jobs from We Work Remotely RSS. Returns normalized job dicts."""
    jobs = []

    for feed_url in WWR_FEEDS:
        try:
            time.sleep(delay)
            resp = requests.get(feed_url, headers={"User-Agent": "DevOps-Job-Agent/1.0"}, timeout=30)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except Exception as e:
            logger.error("WWR fetch failed for %s: %s", feed_url, e)
            continue

        for entry in feed.entries:
            link = entry.get("link", "") or entry.get("id", "")
            if not link:
                continue

            try:
                # Extract company from title — WWR format is typically "Company: Job Title"
                title_text = entry.get("title", "")
                company = ""
                title = title_text
                if ": " in title_text:
                    parts = title_text.split(": ", 1)
                    company = parts[0].strip()
                    title = parts[1].strip()

                description = entry.get("summary", "") or entry.get("description", "")

                jobs.append({
                    "source": "wwr",
                    "link": link,
                    "title": title,
                    "company": company,
                    "location": "Remote",
                    "posted_at": entry.get("published", ""),
                    "raw_description": description,
                })
            except Exception as e:
                logger.warning("Failed to parse WWR item: %s", e)
                continue

    logger.info("WWR: fetched %d jobs", len(jobs))
    return jobs
