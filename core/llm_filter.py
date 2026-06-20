"""LLM relevance scoring via OpenRouter API."""
from __future__ import annotations

import json
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SCORING_PROMPT = """You are a technical recruiter evaluating job listings for relevance to DevOps, SRE, Platform Engineering, Cloud Engineering, and Infrastructure Engineering roles.

For each job below, assign a relevance score from 0 to 100 based on:
- How closely the role matches DevOps/SRE/Platform/Cloud/Infrastructure Engineering (not generic software engineering)
- Seniority and tech stack alignment (Kubernetes, Terraform, CI/CD, cloud providers, etc.)
- Remote-friendliness (remote or hybrid is preferred but not required for a high score)

Return a JSON array with exactly one object per job, matching this format:
[
  {{"link": "<the job's link>", "score": <0-100>, "reason": "<one-line explanation>"}}
]

Jobs to evaluate:
{jobs_json}
"""


def _build_prompt(jobs: list[dict]) -> str:
    """Build the scoring prompt with job details."""
    job_summaries = []
    for job in jobs:
        job_summaries.append({
            "link": job.get("link", ""),
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "description_snippet": (job.get("raw_description") or "")[:2000],
        })
    return SCORING_PROMPT.format(jobs_json=json.dumps(job_summaries, indent=2))


def score_batch(jobs: list[dict], model: str, api_key: str) -> list[dict]:
    """Score a batch of jobs via OpenRouter. Returns list of {link, score, reason}."""
    if not jobs:
        return []

    prompt = _build_prompt(jobs)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/job-agent",
        "X-Title": "DevOps Job Agent",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
    }

    try:
        resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"]
        # Try to extract JSON from the response — LLM may wrap it in markdown
        content = content.strip()
        if content.startswith("```"):
            # Strip markdown code fences
            lines = content.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines)

        parsed = json.loads(content)
        if not isinstance(parsed, list):
            logger.error("LLM returned non-list JSON: %s", type(parsed))
            return []

        results = []
        for item in parsed:
            results.append({
                "link": item.get("link", ""),
                "score": int(item.get("score", 0)),
                "reason": item.get("reason", ""),
            })
        return results

    except requests.RequestException as e:
        logger.error("OpenRouter API request failed: %s", e)
        return []
    except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
        logger.error("Failed to parse LLM response: %s", e)
        return []


def score_all_jobs(jobs: list[dict], model: str, api_key: str, batch_size: int = 5) -> list[dict]:
    """Score all jobs in batches. Returns aggregated list of {link, score, reason}."""
    all_scores = []
    total = len(jobs)

    for i in range(0, total, batch_size):
        batch = jobs[i : i + batch_size]
        logger.info("Scoring batch %d-%d of %d jobs", i + 1, min(i + batch_size, total), total)

        # First attempt
        scores = score_batch(batch, model, api_key)

        # Retry once on failure
        if not scores:
            logger.warning("Batch scoring returned empty, retrying...")
            time.sleep(2)
            scores = score_batch(batch, model, api_key)

        if not scores:
            logger.error("Batch scoring failed after retry for jobs starting at index %d", i)
            continue

        all_scores.extend(scores)

    logger.info("Scored %d jobs total", len(all_scores))
    return all_scores
