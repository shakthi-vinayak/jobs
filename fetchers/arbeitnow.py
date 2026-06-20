"""Fetcher for Arbeitnow API (https://www.arbeitnow.com/api/job-board-api)."""
from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"


def fetch(delay: float = 1.0) -> list[dict]:
    """Fetch remote jobs from Arbeitnow. Returns normalized job dicts."""
    jobs = []
    seen_links = set()

    # Search for relevant terms
    search_terms = ["devops", "sre", "platform engineer", "cloud engineer", "site reliability"]
    for term in search_terms:
        try:
            time.sleep(delay)
            params = {
                "search": term,
                "remote": "true",
                "page": 1,
            }
            resp = requests.get(
                ARBEITNOW_URL,
                params=params,
                headers={"User-Agent": "DevOps-Job-Agent/1.0"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Arbeitnow fetch failed for term '%s': %s", term, e)
            continue

        for item in data.get("data", []):
            link = item.get("url", "") or item.get("slug", "")
            if not link:
                continue

            # Build full URL if only slug is provided
            if link and not link.startswith("http"):
                link = f"https://www.arbeitnow.com/jobs/{link}"

            if link in seen_links:
                continue
            seen_links.add(link)

            try:
                location_parts = []
                if item.get("location"):
                    location_parts.append(item.get("location"))
                if item.get("country"):
                    location_parts.append(item.get("country"))
                location = ", ".join(location_parts) if location_parts else "Remote"

                remote_flag = item.get("remote", False)
                if remote_flag:
                    location = f"Remote — {location}" if location != "Remote" else "Remote"

                jobs.append({
                    "source": "arbeitnow",
                    "link": link,
                    "title": item.get("title", "").strip(),
                    "company": item.get("company_name", "").strip(),
                    "location": location,
                    "posted_at": item.get("created_at", ""),
                    "raw_description": item.get("description", ""),
                })
            except Exception as e:
                logger.warning("Failed to parse Arbeitnow item: %s", e)
                continue

    logger.info("Arbeitnow: fetched %d jobs", len(jobs))
    return jobs
