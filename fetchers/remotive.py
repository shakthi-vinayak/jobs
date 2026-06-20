"""Fetcher for Remotive API (https://remotive.com/api/remote-jobs)."""
from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

REMOTIVE_URL = "https://remotive.com/api/remote-jobs"


def fetch(delay: float = 1.0, category: str = "devops-sysadmin") -> list[dict]:
    """Fetch jobs from Remotive. Returns normalized job dicts."""
    jobs = []
    # Fetch from the devops-sysadmin category and also a broader search
    urls = [
        f"{REMOTIVE_URL}?category={category}&limit=50",
        f"{REMOTIVE_URL}?search=devops&limit=50",
        f"{REMOTIVE_URL}?search=sre&limit=50",
        f"{REMOTIVE_URL}?search=platform+engineer&limit=50",
    ]

    seen_links = set()

    for url in urls:
        try:
            time.sleep(delay)
            resp = requests.get(url, headers={"User-Agent": "DevOps-Job-Agent/1.0"}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Remotive fetch failed for %s: %s", url, e)
            continue

        for item in data.get("jobs", []):
            link = item.get("url", "")
            if not link or link in seen_links:
                continue
            seen_links.add(link)

            try:
                jobs.append({
                    "source": "remotive",
                    "link": link,
                    "title": item.get("title", "").strip(),
                    "company": item.get("company_name", "").strip(),
                    "location": item.get("candidate_required_location", "Remote"),
                    "posted_at": item.get("publication_date", ""),
                    "raw_description": item.get("description", ""),
                })
            except Exception as e:
                logger.warning("Failed to parse Remotive item: %s", e)
                continue

    logger.info("Remotive: fetched %d jobs", len(jobs))
    return jobs
