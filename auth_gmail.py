"""One-time Gmail OAuth2 authorization helper.

Run this script on your local machine (with a browser) to generate token.json.
Then mount both credentials.json and token.json into the Docker container.

Steps:
  1. Go to https://console.cloud.google.com/
  2. Create a project (or select existing)
  3. Enable the Gmail API
  4. Create OAuth 2.0 credentials (Desktop app)
  5. Download the credentials.json file
  6. Place it in your data directory (same as DATA_DIR)
  7. Run this script: python auth_gmail.py
  8. Follow the browser prompt to authorize
  9. token.json will be created next to credentials.json

Both files should be mounted into the container at /data.
"""
from __future__ import annotations

import os
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
CREDENTIALS_FILENAME = "credentials.json"
TOKEN_FILENAME = "token.json"


def main():
    data_dir = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
    token_path = os.path.join(data_dir, TOKEN_FILENAME)
    creds_path = os.path.join(data_dir, CREDENTIALS_FILENAME)

    if not os.path.exists(creds_path):
        print("ERROR: %s not found in %s" % (CREDENTIALS_FILENAME, data_dir))
        print("Download it from Google Cloud Console > APIs & Services > Credentials")
        sys.exit(1)

    creds = None

    # Check for existing token
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, GMAIL_SCOPES)
        if creds.valid:
            print("Existing token.json is valid — nothing to do.")
            print("If you want to re-authorize, delete token.json and run again.")
            return

    # Refresh if possible
    if creds and creds.expired and creds.refresh_token:
        print("Refreshing expired token...")
        creds.refresh(Request())
        with open(token_path, "w") as f:
            f.write(creds.to_json())
        print("Token refreshed and saved to %s" % token_path)
        return

    # Run interactive OAuth2 flow
    print("Starting Gmail OAuth2 authorization flow...")
    print("A browser window will open — sign in and grant send-only access.")
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, GMAIL_SCOPES)
    creds = flow.run_local_server(port=0)

    with open(token_path, "w") as f:
        f.write(creds.to_json())

    print("Authorization successful!")
    print("Token saved to %s" % token_path)
    print("Mount both %s and %s into the Docker container at /data" % (CREDENTIALS_FILENAME, TOKEN_FILENAME))


if __name__ == "__main__":
    main()
