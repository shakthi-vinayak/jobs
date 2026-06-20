"""Email notification for high-relevance job alerts via Gmail API (OAuth2)."""
from __future__ import annotations

import base64
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Gmail API scope — send only
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

# Paths — resolved at call time from data_dir
CREDENTIALS_FILENAME = "credentials.json"
TOKEN_FILENAME = "token.json"


def _get_gmail_credentials(data_dir: str) -> Credentials | None:
    """Load or refresh Gmail OAuth2 credentials.

    Looks for token.json in data_dir (refreshes if expired).
    Falls back to credentials.json for initial auth (requires interactive browser).
    In a Docker container, token.json should already exist from a prior `auth_gmail.py` run.
    """
    token_path = os.path.join(data_dir, TOKEN_FILENAME)
    creds_path = os.path.join(data_dir, CREDENTIALS_FILENAME)

    creds = None

    # 1. Try loading existing token
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, GMAIL_SCOPES)
        except Exception as e:
            logger.warning("Failed to load token.json: %s", e)
            creds = None

    # 2. If credentials exist and are valid, return them
    if creds and creds.valid:
        return creds

    # 3. Try refreshing expired credentials
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Save refreshed token
            with open(token_path, "w") as f:
                f.write(creds.to_json())
            logger.info("Gmail OAuth2 token refreshed successfully")
            return creds
        except Exception as e:
            logger.error("Failed to refresh Gmail OAuth2 token: %s", e)
            return None

    # 4. No valid token — need interactive auth (not possible in Docker cron)
    if not os.path.exists(creds_path):
        logger.error(
            "No Gmail credentials found. Run 'python auth_gmail.py' first to authorize, "
            "then mount credentials.json and token.json into the container."
        )
        return None

    try:
        flow = InstalledAppFlow.from_client_secrets_file(creds_path, GMAIL_SCOPES)
        creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
        logger.info("Gmail OAuth2 authorization completed")
        return creds
    except Exception as e:
        logger.error("Gmail OAuth2 interactive auth failed: %s", e)
        return None


def _build_html_email(jobs: list[dict], sender: str, recipient: str) -> MIMEMultipart:
    """Build an HTML+text email for the job digest."""
    rows = ""
    for job in jobs:
        score = job.get("relevance_score", 0)
        score_color = "#3fb950" if score >= 70 else "#d29922" if score >= 40 else "#f85149"
        rows += """
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #30363d;">
            <a href="{link}" style="color:#58a6ff;text-decoration:none;font-weight:500;">{title}</a>
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #30363d;color:#d2a8ff;">{company}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #30363d;color:{score_color};font-weight:700;">{score}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #30363d;color:#8b949e;font-size:0.85rem;">{reason}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #30363d;">
            <a href="{link}" style="color:#f0883e;text-decoration:none;">Apply</a>
          </td>
        </tr>""".format(
            link=job.get("link", "#"),
            title=job.get("title", "N/A"),
            company=job.get("company", "N/A"),
            score=score,
            reason=job.get("llm_reason", ""),
            score_color=score_color,
        )

    plural = "s" if len(jobs) != 1 else ""
    html_body = """
    <html>
    <body style="background:#0d1117;color:#c9d1d9;font-family:sans-serif;padding:20px;">
      <h2 style="color:#58a6ff;">DevOps Job Alert — {count} New Matching Position{plural}</h2>
      <table style="width:100%;border-collapse:collapse;background:#161b22;border-radius:8px;overflow:hidden;">
        <thead>
          <tr style="background:#21262d;">
            <th style="padding:10px 12px;text-align:left;color:#8b949e;font-size:0.8rem;">Title</th>
            <th style="padding:10px 12px;text-align:left;color:#8b949e;font-size:0.8rem;">Company</th>
            <th style="padding:10px 12px;text-align:left;color:#8b949e;font-size:0.8rem;">Score</th>
            <th style="padding:10px 12px;text-align:left;color:#8b949e;font-size:0.8rem;">Reason</th>
            <th style="padding:10px 12px;text-align:left;color:#8b949e;font-size:0.8rem;">Link</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="color:#484f58;font-size:0.8rem;margin-top:16px;">
        Generated by DevOps Job Agent &mdash; update your preferences in config.yaml
      </p>
    </body>
    </html>""".format(count=len(jobs), plural=plural, rows=rows)

    text_lines = ["DevOps Job Alert — %d New Matching Position%s\n" % (len(jobs), plural)]
    for job in jobs:
        text_lines.append("  [%d] %s at %s" % (job.get("relevance_score", 0), job.get("title", "N/A"), job.get("company", "N/A")))
        text_lines.append("       %s" % job.get("llm_reason", ""))
        text_lines.append("       Apply: %s" % job.get("link", ""))
        text_lines.append("")
    text_body = "\n".join(text_lines)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "DevOps Job Alert — %d New Position%s" % (len(jobs), plural)
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    return msg


def send_digest(
    jobs: list[dict],
    data_dir: str,
    alert_email_to: str,
) -> bool:
    """Send a single digest email via Gmail API. Returns True on success."""
    if not jobs:
        logger.info("No jobs to notify about — skipping email")
        return True

    try:
        creds = _get_gmail_credentials(data_dir)
        if not creds:
            logger.error("Gmail OAuth2 credentials not available — cannot send email")
            return False

        service = build("gmail", "v1", credentials=creds)

        # Gmail API needs the "me" alias for the authenticated user
        sender = "me"

        msg = _build_html_email(jobs, sender, alert_email_to)
        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

        send_result = service.users().messages().send(
            userId="me",
            body={"raw": raw_message},
        ).execute()

        logger.info(
            "Sent digest email with %d jobs to %s (messageId: %s)",
            len(jobs), alert_email_to, send_result.get("id", "unknown"),
        )
        return True

    except HttpError as e:
        logger.error("Gmail API error sending digest: %s", e)
        return False
    except Exception as e:
        logger.error("Unexpected error sending digest email: %s", e)
        return False
