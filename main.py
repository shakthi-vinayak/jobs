"""Main orchestrator for the DevOps Job Aggregator Agent."""
from __future__ import annotations

import logging
import os
import sys

import yaml
from dotenv import load_dotenv

from core.db import (
    finish_run,
    get_notifiable_jobs,
    has_previous_runs,
    init_db,
    insert_jobs,
    mark_jobs_notified,
    start_run,
    update_llm_scores,
)
from core.llm_filter import score_all_jobs
from core.normalizer import normalize_batch, pre_filter
from fetchers import remoteok, remotive, wwr_rss, hn_algolia, arbeitnow, greenhouse, lever
from notify.emailer import send_digest
from report.generate import generate_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_pipeline(config: dict, env_path: str = ".env") -> None:
    """Execute the full job aggregation pipeline."""
    load_dotenv(env_path)

    # Paths — default to /data volume inside Docker, local dir otherwise
    data_dir = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(data_dir, "jobs.db")
    report_path = os.path.join(data_dir, "index.html")

    # Initialize database
    conn = init_db(db_path)

    # Start run log
    is_bootstrap = not has_previous_runs(conn)
    run_id = start_run(conn)
    logger.info("=== Run #%d started (bootstrap=%s) ===", run_id, is_bootstrap)

    delay = config.get("request_delay", 1.0)
    keywords = config.get("keywords", [])

    # ---- Step 1: Fetch from all sources ----
    all_raw_jobs = []

    fetchers = [
        ("RemoteOK", lambda: remoteok.fetch(delay=delay)),
        ("Remotive", lambda: remotive.fetch(delay=delay)),
        ("WWR", lambda: wwr_rss.fetch(delay=delay)),
        ("HN Algolia", lambda: hn_algolia.fetch(delay=delay)),
        ("Arbeitnow", lambda: arbeitnow.fetch(delay=delay)),
        ("Greenhouse", lambda: greenhouse.fetch(
            company_slugs=config.get("greenhouse_companies", []), delay=delay
        )),
        ("Lever", lambda: lever.fetch(
            company_slugs=config.get("lever_companies", []), delay=delay
        )),
    ]

    for name, fetch_fn in fetchers:
        try:
            logger.info("Fetching from %s...", name)
            jobs = fetch_fn()
            logger.info("%s returned %d raw jobs", name, len(jobs))
            all_raw_jobs.extend(jobs)
        except Exception as e:
            logger.error("Fetcher %s failed: %s", name, e)
            continue

    total_fetched = len(all_raw_jobs)
    logger.info("Total raw jobs fetched: %d", total_fetched)

    # ---- Step 2: Normalize and pre-filter ----
    all_normalized = []
    for job in all_raw_jobs:
        source = job.get("source", "unknown")
        all_normalized.append(normalize_batch([job], source)[0] if job.get("link") else None)

    all_normalized = [j for j in all_normalized if j is not None and j.get("link")]

    # Apply keyword pre-filter (unless bootstrap first run — grab everything)
    if is_bootstrap and keywords:
        logger.info("Bootstrap run — applying keyword filter to %d jobs", len(all_normalized))
        filtered = pre_filter(all_normalized, keywords)
    elif keywords:
        filtered = pre_filter(all_normalized, keywords)
    else:
        filtered = all_normalized

    # ---- Step 3: Insert into DB ----
    new_count = insert_jobs(conn, filtered)
    logger.info("Inserted %d new jobs (total fetched: %d)", new_count, total_fetched)

    # ---- Step 4: LLM relevance scoring (new unscored jobs only) ----
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
    model = config.get("openrouter_model", "deepseek/deepseek-chat-v3-0324:free")
    batch_size = config.get("llm_batch_size", 5)

    if openrouter_key and new_count > 0:
        logger.info("Scoring new jobs with LLM...")
        # Get newly inserted jobs that need scoring
        unscored = []
        cur = conn.execute(
            "SELECT id, source, link, title, company, location, posted_at, '' as raw_description "
            "FROM jobs WHERE status = 'new' AND relevance_score IS NULL"
        )
        columns = [desc[0] for desc in cur.description]
        unscored = [dict(zip(columns, row)) for row in cur.fetchall()]

        if unscored:
            scores = score_all_jobs(unscored, model, openrouter_key, batch_size)
            if scores:
                update_llm_scores(conn, scores)
                logger.info("Updated %d job scores", len(scores))
        else:
            logger.info("No unscored jobs to process")
    elif not openrouter_key:
        logger.warning("OPENROUTER_API_KEY not set — skipping LLM scoring")
    else:
        logger.info("No new jobs to score")

    # ---- Step 5: Generate HTML report ----
    try:
        generate_report(conn, report_path)
    except Exception as e:
        logger.error("Report generation failed: %s", e)

    # ---- Step 6: Email alerts ----
    threshold = config.get("relevance_threshold", 70)
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user)
    alert_email_to = os.environ.get("ALERT_EMAIL_TO", "")

    if smtp_host and smtp_user and smtp_pass and alert_email_to:
        notifiable = get_notifiable_jobs(conn, threshold)
        if notifiable:
            logger.info("Found %d jobs above threshold %d for notification", len(notifiable), threshold)
            success = send_digest(
                notifiable, smtp_host, smtp_port, smtp_user, smtp_pass, smtp_from, alert_email_to
            )
            if success:
                mark_jobs_notified(conn, [j["id"] for j in notifiable])
                logger.info("Marked %d jobs as notified", len(notifiable))
        else:
            logger.info("No jobs above threshold %d — no email sent", threshold)
    else:
        logger.info("SMTP not configured — skipping email alerts")

    # ---- Step 7: Finish run log ----
    finish_run(conn, run_id, total_fetched, new_count)
    conn.close()
    logger.info("=== Run #%d complete ===", run_id)


def main():
    """Entry point — load config and run the pipeline."""
    config_path = os.environ.get("CONFIG_PATH", "config.yaml")
    env_path = os.environ.get("ENV_PATH", ".env")

    if not os.path.exists(config_path):
        logger.error("Config file not found: %s", config_path)
        sys.exit(1)

    config = load_config(config_path)

    try:
        run_pipeline(config, env_path)
    except Exception as e:
        logger.critical("Pipeline failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
