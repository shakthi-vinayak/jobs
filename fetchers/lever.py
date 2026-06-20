"""Fetcher for Lever job boards (https://api.lever.co/v0/postings/{company}?mode=json)."""
from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

LEVER_BASE = "https://api.lever.co/v0/postings"


def fetch(company_slugs: list[str], delay: float = 1.0) -> list[dict]:
    """Fetch jobs from configured Lever boards. Returns normalized job dicts."""
    jobs = []

    for company in company_slugs:
        try:
            time.sleep(delay)
            url = f"{LEVER_BASE}/{company}?mode=json"
            resp = requests.get(url, headers={"User-Agent": "DevOps-Job-Agent/1.0"}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Lever fetch failed for %s: %s", company, e)
            continue

        for item in data.get("postings", []):
            link = item.get("hostedUrl", "") or item.get("applyUrl", "")
            if not link:
                continue

            try:
                # Build location from categories
                categories = item.get("categories", {})
                location = categories.get("location", "") or categories.get("team", "") or "See posting"
                commitment = categories.get("commitment", "")
                if commitment and location:
                    location = f"{location} — {commitment}"
                elif commitment:
                    location = commitment

                description_parts = []
                desc = item.get("description", "")
                if isinstance(desc, str):
                    description_parts.append(desc)
                for section in item.get("lists", []):
                    if isinstance(section, dict):
                        description_parts.append(section.get("content", ""))
                description = "\n".join(description_parts)

                jobs.append({
                    "source": f"lever:{company}",
                    "link": link,
                    "title": item.get("text", "").strip(),
                    "company": company.replace("-", " ").replace("_", " ").title(),
                    "location": location,
                    "posted_at": item.get("createdAt", ""),
                    "raw_description": description,
                })
            except Exception as e:
                logger.warning("Failed to parse Lever item for %s: %s", company, e)
                continue

    logger.info("Lever: fetched %d jobs", len(jobs))
    return jobs
