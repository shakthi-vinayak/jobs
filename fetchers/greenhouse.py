"""Fetcher for Greenhouse job boards (https://boards-api.greenhouse.io/v1/boards/{company}/jobs)."""
from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

GREENHOUSE_BASE = "https://boards-api.greenhouse.io/v1/boards"


def _fetch_job_detail(company: str, job_id: int, delay: float) -> dict | None:
    """Fetch detail for a single Greenhouse job listing."""
    try:
        time.sleep(delay)
        url = f"{GREENHOUSE_BASE}/{company}/jobs/{job_id}"
        resp = requests.get(url, headers={"User-Agent": "DevOps-Job-Agent/1.0"}, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("Greenhouse detail fetch failed for %s job %d: %s", company, job_id, e)
        return None


def fetch(company_slugs: list[str], delay: float = 1.0) -> list[dict]:
    """Fetch jobs from configured Greenhouse boards. Returns normalized job dicts."""
    jobs = []

    for company in company_slugs:
        try:
            time.sleep(delay)
            url = f"{GREENHOUSE_BASE}/{company}/jobs"
            resp = requests.get(url, headers={"User-Agent": "DevOps-Job-Agent/1.0"}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Greenhouse fetch failed for %s: %s", company, e)
            continue

        for item in data.get("jobs", []):
            job_id = item.get("id")
            link = item.get("absolute_url", "") or f"https://boards.greenhouse.io/{company}/jobs/{job_id}"
            title = item.get("title", "").strip()

            try:
                # Fetch detail for description (rate-limited)
                detail = _fetch_job_detail(company, job_id, delay) if job_id else None
                description = ""
                location = ""
                if detail:
                    content = detail.get("content", "") or ""
                    description = content
                    # Greenhouse sometimes puts location in the job's location property
                    location = detail.get("location", {}).get("name", "") if isinstance(detail.get("location"), dict) else str(detail.get("location", ""))

                jobs.append({
                    "source": f"greenhouse:{company}",
                    "link": link,
                    "title": title,
                    "company": company.replace("-", " ").replace("_", " ").title(),
                    "location": location or "See posting",
                    "posted_at": item.get("updated_at", ""),
                    "raw_description": description,
                })
            except Exception as e:
                logger.warning("Failed to parse Greenhouse job %s/%d: %s", company, job_id, e)
                # Add without detail
                jobs.append({
                    "source": f"greenhouse:{company}",
                    "link": link,
                    "title": title,
                    "company": company.replace("-", " ").replace("_", " ").title(),
                    "location": "See posting",
                    "posted_at": item.get("updated_at", ""),
                    "raw_description": "",
                })
                continue

    logger.info("Greenhouse: fetched %d jobs", len(jobs))
    return jobs
