"""Normalization and keyword pre-filtering for job listings."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# The normalized schema every fetcher must produce:
# source, link, title, company, location, posted_at, raw_description

REQUIRED_FIELDS = ("source", "link", "title")


def matches_keywords(job: dict, keywords: list[str]) -> bool:
    """Check if a job's title or raw_description matches any keyword (case-insensitive)."""
    text = f"{job.get('title', '')} {job.get('raw_description', '')}".lower()
    return any(kw.lower() in text for kw in keywords)


def pre_filter(jobs: list[dict], keywords: list[str]) -> list[dict]:
    """Filter jobs that match at least one keyword."""
    matched = []
    for job in jobs:
        if matches_keywords(job, keywords):
            matched.append(job)
        else:
            logger.debug("Filtered out: %s — %s", job.get("source"), job.get("title"))
    logger.info("Keyword pre-filter: %d / %d jobs matched", len(matched), len(jobs))
    return matched


def normalize_job(job: dict, source: str) -> dict:
    """Ensure a job dict has all required fields, filling blanks as needed."""
    now = datetime.now(timezone.utc).isoformat()

    normalized = {
        "source": job.get("source", source),
        "link": job.get("link", "").strip(),
        "title": job.get("title", "").strip(),
        "company": job.get("company", "").strip() or None,
        "location": job.get("location", "").strip() or None,
        "posted_at": job.get("posted_at") or None,
        "fetched_at": job.get("fetched_at", now),
        "raw_description": job.get("raw_description", ""),
    }

    if not normalized["link"]:
        logger.warning("Job without link from %s: %s", source, normalized["title"])

    return normalized


def normalize_batch(jobs: list[dict], source: str) -> list[dict]:
    """Normalize a batch of jobs from a single source."""
    return [normalize_job(job, source) for job in jobs if job.get("link")]
