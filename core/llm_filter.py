"""LLM relevance scoring via OpenRouter API with multi-model fallback."""
from __future__ import annotations

import json
import logging
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


def score_batch(jobs: list[dict], models: list[str], api_key: str) -> list[dict]:
    """Score a batch of jobs via OpenRouter, trying models in order until one succeeds.

    Args:
        jobs: List of job dicts to score.
        models: Ordered list of model IDs to try (first = preferred).
        api_key: OpenRouter API key.

    Returns:
        List of {link, score, reason} dicts, or empty list if all models fail.
    """
    if not jobs:
        return []

    prompt = _build_prompt(jobs)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/job-agent",
        "X-Title": "DevOps Job Agent",
    }

    for model in models:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }

        try:
            logger.info("Trying model: %s", model)
            resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)

            if resp.status_code == 429:
                logger.warning("Model %s rate-limited (429), trying next model", model)
                time.sleep(1)
                continue

            resp.raise_for_status()
            data = resp.json()

            content = data["choices"][0]["message"]["content"]
            # Try to extract JSON from the response — LLM may wrap it in markdown
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                content = "\n".join(lines)

            parsed = json.loads(content)
            if not isinstance(parsed, list):
                logger.error("Model %s returned non-list JSON: %s", model, type(parsed))
                continue

            results = []
            for item in parsed:
                results.append({
                    "link": item.get("link", ""),
                    "score": int(item.get("score", 0)),
                    "reason": item.get("reason", ""),
                })

            logger.info("Model %s succeeded — scored %d jobs", model, len(results))
            return results

        except requests.RequestException as e:
            logger.warning("Model %s request failed: %s — trying next", model, e)
            continue
        except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
            logger.warning("Model %s response parse failed: %s — trying next", model, e)
            continue

    logger.error("All %d models failed for this batch", len(models))
    return []


def score_all_jobs(
    jobs: list[dict],
    models: list[str],
    api_key: str,
    batch_size: int = 5,
) -> list[dict]:
    """Score all jobs in batches with multi-model fallback.

    For each batch, models are tried in order. If the first model fails
    (rate limit, timeout, parse error), the next model is attempted.
    Only if all models fail does the batch go unscored.

    Args:
        jobs: List of job dicts to score.
        models: Ordered list of model IDs (first = preferred).
        api_key: OpenRouter API key.
        batch_size: Number of jobs per API call.

    Returns:
        Aggregated list of {link, score, reason} dicts.
    """
    if not models:
        logger.error("No models configured for scoring")
        return []

    all_scores = []
    total = len(jobs)

    for i in range(0, total, batch_size):
        batch = jobs[i : i + batch_size]
        logger.info("Scoring batch %d-%d of %d jobs", i + 1, min(i + batch_size, total), total)

        # First attempt with full model list
        scores = score_batch(batch, models, api_key)

        # Single retry — one more pass through the models
        if not scores:
            logger.warning("Batch scoring returned empty from all models, retrying after delay...")
            time.sleep(3)
            scores = score_batch(batch, models, api_key)

        if not scores:
            logger.error("Batch scoring failed after retry for jobs starting at index %d", i)
            continue

        all_scores.extend(scores)

    logger.info("Scored %d jobs total", len(all_scores))
    return all_scores
