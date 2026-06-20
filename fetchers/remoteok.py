"""Fetcher for RemoteOK API (https://remoteok.com/api)."""
from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

REMOTEOK_URL = "https://remoteok.com/api"


def fetch(delay: float = 1.0) -> list[dict]:
    """Fetch jobs from RemoteOK. Returns normalized job dicts."""
    try:
        time.sleep(delay)
        resp = requests.get(REMOTEOK_URL, headers={"User-Agent": "DevOps-Job-Agent/1.0"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("RemoteOK fetch failed: %s", e)
        return []

    jobs = []
    # First item in the response is metadata — skip it
    for item in data[1:] if len(data) > 1 and isinstance(data[0], dict) and "legal" in data[0] else data:
        try:
            link = item.get("url", "")
            if not link:
                continue

            # Build location from tags
            tags = item.get("tags", [])
            location = ", ".join(tags) if tags else "Remote"

            jobs.append({
                "source": "remoteok",
                "link": link,
                "title": item.get("position", "").strip(),
                "company": item.get("company", "").strip(),
                "location": location,
                "posted_at": item.get("date", ""),
                "raw_description": item.get("description", ""),
            })
        except Exception as e:
            logger.warning("Failed to parse RemoteOK item: %s", e)
            continue

    logger.info("RemoteOK: fetched %d jobs", len(jobs))
    return jobs
