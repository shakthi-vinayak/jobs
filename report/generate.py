"""Generate static HTML report from job database."""
from __future__ import annotations

import json
import logging
import os

from jinja2 import Template

from core.db import get_all_jobs_for_report

logger = logging.getLogger(__name__)

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "template.html.j2")


def generate_report(conn, output_path: str) -> None:
    """Generate the static index.html report with all jobs embedded as JSON."""
    jobs = get_all_jobs_for_report(conn)
    logger.info("Generating report with %d jobs", len(jobs))

    # Serialize jobs for embedding
    jobs_json = json.dumps(jobs, default=str)

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = Template(f.read())

    html = template.render(jobs_json=jobs_json)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("Report written to %s", output_path)
