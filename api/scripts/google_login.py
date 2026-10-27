"""Sign in with a Google account that can view the sheet, and save a token the API syncs with.

A stopgap until there's a service account. Setup (once), in Google Cloud:
  1. Enable the Google Sheets API.
  2. APIs & Services → OAuth consent screen: External, add your Google account as a test user.
  3. APIs & Services → Credentials → Create credentials → OAuth client ID → Desktop app; download the
     JSON to api/secrets/google-oauth-client.json.

Usage (from api/):
    python -m scripts.google_login [--client-secret PATH] [--out PATH]

Opens a browser to sign in, saves the token (default api/secrets/google-user-token.json), and prints
the TRACKER_GOOGLE_CREDENTIALS line for .env. While the consent screen is in Testing, Google expires
the token after about 7 days; run this again when Admin → Sheet says the sign-in expired.
"""

import argparse
import os
from pathlib import Path

from app.config import API_DIR, ROOT_DIR
from app.google_sheet import SCOPES

SECRETS = API_DIR / "secrets"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--client-secret", type=Path, default=SECRETS / "google-oauth-client.json",
                        help="OAuth client JSON (Desktop app) from Google Cloud")
    parser.add_argument("--out", type=Path, default=SECRETS / "google-user-token.json", help="where to save the token")
    args = parser.parse_args()

    if not args.client_secret.is_file():
        parser.exit(1, f"OAuth client file not found: {args.client_secret} (see setup in --help)\n")

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(args.client_secret), SCOPES)
    # prompt=consent makes Google always return a refresh token, even on a repeat sign-in.
    creds = flow.run_local_server(port=0, prompt="consent")

    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(creds.to_json())
    os.chmod(out, 0o600)
    shown = out.relative_to(ROOT_DIR) if out.is_relative_to(ROOT_DIR) else out
    print(f"Saved {shown}. In .env set:\n  TRACKER_GOOGLE_CREDENTIALS={shown}\nthen restart the API.")


if __name__ == "__main__":
    main()
