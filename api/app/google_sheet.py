"""Read the client's Google Sheet through the Sheets API with a service account or a signed-in user.

Setup: create a service account in Google Cloud with the Sheets API enabled, download its JSON key,
share the sheet with the account's email as Editor, and set TRACKER_GOOGLE_SHEET and
TRACKER_GOOGLE_CREDENTIALS in .env. Until there's a service account, TRACKER_GOOGLE_CREDENTIALS can
instead point at a user token saved by `python -m scripts.google_login` (see that script).

Returns the same {tab: grid} shape as sheet_import.read_workbook(), using each cell's computed value
and its own background color (not conditional formatting, matching the .xlsx export).
"""

import json
import re
from pathlib import Path

from .sheet_import import Cell, Grid, parse_tab_name

API = "https://sheets.googleapis.com/v4/spreadsheets"
READ_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
# Asked for by scripts.google_login and service accounts: deals entered in the app are written to the sheet.
SCOPES = [WRITE_SCOPE]
# Month tabs are about 40 rows by 33 columns; leave plenty of room.
TAB_RANGE = "A1:AZ300"


class SheetError(Exception):
    """A problem reaching or reading the sheet, worded for an admin."""


def spreadsheet_id(sheet: str) -> str:
    """The ID from a docs.google.com/spreadsheets/d/<id>/... URL, or the ID itself."""
    match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", sheet)
    if match:
        return match[1]
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", sheet.strip()):
        return sheet.strip()
    raise SheetError("TRACKER_GOOGLE_SHEET isn't a Google Sheets URL or ID")


def service_account_email(credentials: Path) -> str | None:
    try:
        return json.loads(credentials.read_text(encoding="utf-8")).get("client_email")
    except (OSError, ValueError):
        return None


def is_user_token(credentials: Path) -> bool:
    # Tokens saved by scripts.google_login: newer google-auth writes them without "type", so go by refresh_token.
    try:
        info = json.loads(credentials.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return info.get("type") == "authorized_user" or ("refresh_token" in info and "client_email" not in info)


def token_scopes(credentials: Path) -> list[str]:
    try:
        scopes = json.loads(credentials.read_text(encoding="utf-8")).get("scopes") or []
    except (OSError, ValueError):
        return []
    return scopes.split() if isinstance(scopes, str) else list(scopes)


def write_access(credentials: Path | None) -> str:
    """'ready', 'read_only' (a sign-in saved before writing existed), or 'unknown'.

    A service account always asks for write access; whether it has it depends on being shared the sheet
    as Editor, which only shows when a write is tried.
    """
    if not credentials or not credentials.is_file():
        return "unknown"
    if is_user_token(credentials):
        return "ready" if WRITE_SCOPE in token_scopes(credentials) else "read_only"
    return "unknown"


def load_credentials(credentials: Path):
    """Service-account key or saved user token, whichever the file is."""
    if not credentials.is_file():
        raise SheetError(f"Google credentials not found at {credentials}")
    try:
        is_oauth_client = "installed" in json.loads(credentials.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        is_oauth_client = False
    if is_oauth_client:
        raise SheetError(
            f"{credentials.name} is the OAuth client file, not a sign-in token. Run `python -m scripts.google_login` "
            "in api/ and set TRACKER_GOOGLE_CREDENTIALS to the token it saves (api/secrets/google-user-token.json)."
        )
    try:
        if is_user_token(credentials):
            from google.oauth2.credentials import Credentials

            # Use the scopes the token was granted: asking a read-only token for write access fails its refresh,
            # which would stop syncing too. token_scopes() tells whether it can write.
            return Credentials.from_authorized_user_file(str(credentials))
        from google.oauth2 import service_account

        return service_account.Credentials.from_service_account_file(str(credentials), scopes=SCOPES)
    except (ValueError, KeyError) as e:
        raise SheetError(f"Couldn't read the Google credentials file: {e}") from None


def hex_color(color: dict | None) -> str | None:
    if not color:
        return None
    return "".join(f"{round(color.get(c, 0) * 255):02X}" for c in ("red", "green", "blue"))


def to_cell(value: dict) -> Cell:
    effective = value.get("effectiveValue") or {}
    v = effective.get("numberValue", effective.get("stringValue", effective.get("boolValue")))
    if isinstance(v, str):
        v = v.strip() or None
    fmt = value.get("userEnteredFormat") or {}
    color = (fmt.get("backgroundColorStyle") or {}).get("rgbColor") or fmt.get("backgroundColor")
    return Cell(v, hex_color(color))


def to_grid(sheet_data: dict) -> Grid:
    rows = (sheet_data.get("data") or [{}])[0].get("rowData") or []
    return [[to_cell(v) for v in row.get("values") or []] for row in rows]


def quote(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


class SheetsApi:
    """Calls to one spreadsheet, with Google's errors turned into SheetError messages an admin can act on.

    `session` is an authorized requests-style session (tests pass a fake).
    """

    def __init__(self, sheet: str, credentials: Path, session=None):
        self.sheet_id = spreadsheet_id(sheet)
        self.credentials = credentials
        if session is None:
            from google.auth.transport.requests import AuthorizedSession

            session = AuthorizedSession(load_credentials(credentials))
        self.session = session

    def get(self, params: dict, path: str = "") -> dict:
        return self._call("get", path, params=params)

    def post(self, path: str, body: dict) -> dict:
        return self._call("post", path, json=body)

    def _call(self, method: str, path: str, **kwargs) -> dict:
        credentials = self.credentials
        try:
            res = getattr(self.session, method)(f"{API}/{self.sheet_id}{path}", timeout=60, **kwargs)
        except Exception as e:  # network errors, token refresh failures
            if is_user_token(credentials) and "invalid_grant" in str(e):
                raise SheetError("Google sign-in expired; run ./renew_api.sh (or `python -m scripts.google_login` in api/)") from None
            raise SheetError(f"Couldn't reach Google Sheets: {e}") from None
        if res.status_code == 403 and method != "get" and is_user_token(credentials):
            raise SheetError("The signed-in Google account can't edit the sheet: share it as Editor, and make sure the "
                             "sign-in allows editing (./renew_api.sh --check)")
        if res.status_code == 403 and is_user_token(credentials):
            raise SheetError("The signed-in Google account can't open the sheet; share the sheet with it as Editor")
        if res.status_code == 403:
            email = service_account_email(credentials)
            who = f" ({email})" if email else ""
            raise SheetError(f"The service account{who} can't open or edit the sheet; share the sheet with it as Editor")
        if res.status_code == 404:
            raise SheetError("Sheet not found; check TRACKER_GOOGLE_SHEET")
        if res.status_code != 200:
            raise SheetError(f"Google Sheets returned {res.status_code}: {res.text[:300]}")
        return res.json()


def read_spreadsheet(sheet: str, credentials: Path, session=None) -> dict[str, Grid]:
    """Fetch every month tab. `session` is an authorized requests-style session (for tests)."""
    api = SheetsApi(sheet, credentials, session)
    titles = [s["properties"]["title"] for s in api.get({"fields": "sheets.properties.title"}).get("sheets", [])]
    months = [t for t in titles if parse_tab_name(t)]
    if not months:
        return {}
    data = api.get({
        "ranges": [f"{quote(t)}!{TAB_RANGE}" for t in months],
        "includeGridData": "true",
        "fields": "sheets(properties.title,data.rowData.values(effectiveValue,userEnteredFormat(backgroundColor,backgroundColorStyle)))",
    })
    return {s["properties"]["title"]: to_grid(s) for s in data.get("sheets", [])}
