#!/usr/bin/env bash
# Renew the Google sign-in the API uses to read (and write) the client's sheet.
#
#   ./renew_api.sh            checks the setup, signs in again in a browser, then checks the new sign-in works
#   ./renew_api.sh --check    checks only: shows whether the current sign-in can read and write the sheet
#
# Only for the stopgap user sign-in (TRACKER_GOOGLE_CREDENTIALS pointing at a token saved by
# scripts.google_login). A service-account key never expires, so there's nothing to renew.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API="$ROOT/api"
PY="$API/.venv/bin/python"
CHECK_ONLY=0
case "${1:-}" in
  --check) CHECK_ONLY=1 ;;
  "") ;;
  -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "Unknown option: $1 (try --help)"; exit 2 ;;
esac

if [ -t 1 ]; then G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; B=$'\e[1m'; N=$'\e[0m'; else G= Y= R= B= N=; fi
ok()   { echo "  ${G}✓${N} $*"; }
warn() { echo "  ${Y}!${N} $*"; }
fail() { echo "  ${R}✗${N} $*"; echo; echo "${R}Stopped.${N} Fix the above and run this again."; exit 1; }
step() { echo; echo "${B}$*${N}"; }

# Runs Python inside api/ with the project's packages; prints one line per finding.
check_sheet() {
  (cd "$API" && "$PY" - <<'EOF'
from app.config import settings
from app.google_sheet import (SheetError, is_user_token, load_credentials, service_account_email,
                              spreadsheet_id, token_scopes, write_access, API)

creds = settings.google_credentials_path
print(f"KIND={'user' if creds and creds.is_file() and is_user_token(creds) else 'service' if creds and service_account_email(creds) else 'unknown'}")
print(f"WRITE={write_access(creds)}")
if creds and creds.is_file() and is_user_token(creds):
    print("SCOPES=" + ", ".join(s.rsplit('/', 1)[-1] for s in token_scopes(creds)))
try:
    from google.auth.transport.requests import AuthorizedSession
    session = AuthorizedSession(load_credentials(creds))
    res = session.get(f"{API}/{spreadsheet_id(settings.google_sheet)}", params={"fields": "properties.title"}, timeout=30)
    if res.status_code == 200:
        print("READ=ok " + res.json()["properties"]["title"])
    else:
        print(f"READ=fail Google answered {res.status_code}: {res.text[:150]}")
except SheetError as e:
    print(f"READ=fail {e}")
except Exception as e:  # expired or revoked sign-in, network
    msg = str(e)
    print("READ=fail " + ("the sign-in has expired or was revoked" if "invalid_grant" in msg else msg[:200]))
EOF
  )
}

report() {
  local out kind write scopes read
  out="$(check_sheet 2>&1)"
  kind="$(sed -n 's/^KIND=//p' <<<"$out")"
  write="$(sed -n 's/^WRITE=//p' <<<"$out")"
  scopes="$(sed -n 's/^SCOPES=//p' <<<"$out")"
  read="$(sed -n 's/^READ=//p' <<<"$out")"
  if [ -z "$kind" ]; then warn "Couldn't run the check:"; echo "$out" | tail -5 | sed 's/^/      /'; return 1; fi
  case "$kind" in
    user) ok "Sign-in type: Google user sign-in${scopes:+ (granted: $scopes)}" ;;
    service) ok "Sign-in type: service account (doesn't expire; nothing to renew)" ;;
    *) warn "Sign-in type: unrecognized credentials file" ;;
  esac
  if [[ "$read" == ok* ]]; then ok "Can read the sheet: \"${read#ok }\""; else warn "Can't read the sheet: ${read#fail }"; fi
  case "$write" in
    ready) ok "Can write: yes (has edit access to spreadsheets)" ;;
    read_only) warn "Can write: no — this sign-in is read-only" ;;
    *) warn "Can write: unknown until the first write (a service account needs the sheet shared as Editor)" ;;
  esac
  [[ "$read" == ok* && "$write" == ready ]]
}

echo "${B}HotStreak — renew the Google sheet sign-in${N}"

step "1. Checking the setup"
[ -x "$PY" ] || fail "No Python environment at api/.venv. Run ./start.sh --setup first."
ok "Project Python: api/.venv"
(cd "$API" && "$PY" -c "import google_auth_oauthlib, google.auth, pydantic_settings" 2>/dev/null) \
  || fail "Python packages are missing. Run ./start.sh --setup."
ok "Google packages installed"
[ -f "$ROOT/.env" ] || fail "No .env file. Copy .env.example to .env and fill it in."
ok ".env found"

CONFIG="$(cd "$API" && "$PY" -c "
from app.config import settings
c = settings.google_credentials_path
print(settings.google_sheet and 'yes' or '')
print(c or '')" 2>&1)" || fail "Couldn't read the settings in .env: $CONFIG"
SHEET_SET="$(sed -n 1p <<<"$CONFIG")"
CREDS="$(sed -n 2p <<<"$CONFIG")"
[ -n "$SHEET_SET" ] || fail "TRACKER_GOOGLE_SHEET isn't set in .env (the sheet's URL)."
ok "TRACKER_GOOGLE_SHEET is set"
[ -n "$CREDS" ] || fail "TRACKER_GOOGLE_CREDENTIALS isn't set in .env. Set it to api/secrets/google-user-token.json."
ok "TRACKER_GOOGLE_CREDENTIALS: ${CREDS#"$ROOT/"}"

step "2. Current sign-in"
if [ -f "$CREDS" ]; then
  report && BEFORE_OK=1 || BEFORE_OK=0
else
  warn "No sign-in saved yet at ${CREDS#"$ROOT/"}"
  BEFORE_OK=0
fi

if [ "$CHECK_ONLY" = 1 ]; then
  echo
  if [ "$BEFORE_OK" = 1 ]; then echo "${G}All good:${N} the API can read and write the sheet."
  else echo "Run ${B}./renew_api.sh${N} (without --check) to sign in again."; fi
  exit 0
fi

if [ -f "$CREDS" ] && (cd "$API" && "$PY" -c "
import sys
from pathlib import Path
from app.google_sheet import is_user_token, service_account_email
p = Path(sys.argv[1])
sys.exit(0 if service_account_email(p) and not is_user_token(p) else 1)" "$CREDS"); then
  echo
  echo "TRACKER_GOOGLE_CREDENTIALS is a service-account key, which doesn't expire — nothing to renew."
  echo "If it can't write, share the sheet with the service account's email as Editor."
  exit 0
fi

CLIENT="$API/secrets/google-oauth-client.json"
[ -f "$CLIENT" ] || fail "OAuth client file missing: api/secrets/google-oauth-client.json (setup steps: api/scripts/google_login.py)."
ok "OAuth client file found"

step "3. Signing in"
BACKUP=""
if [ -f "$CREDS" ]; then
  BACKUP="$CREDS.$(date +%Y%m%d-%H%M%S).bak"
  cp -p "$CREDS" "$BACKUP" && ok "Backed up the old sign-in to ${BACKUP#"$ROOT/"}"
fi
echo "  A browser window opens. Sign in with the Google account that has ${B}Editor${N} access to the sheet,"
echo "  and approve ${B}\"See, edit, create, and delete your spreadsheets\"${N}."
echo
if ! (cd "$API" && "$PY" -m scripts.google_login --client-secret "$CLIENT" --out "$CREDS"); then
  if [ -n "$BACKUP" ]; then cp -p "$BACKUP" "$CREDS" && warn "Sign-in didn't finish; put the old sign-in back."; fi
  fail "The Google sign-in didn't complete."
fi

step "4. Checking the new sign-in"
if report; then
  echo
  echo "${G}Done.${N} Restart the API so it picks up the new sign-in:"
  echo "  - development: stop ./start.sh (Ctrl+C) and start it again"
  echo "  - Windows service: powershell -ExecutionPolicy Bypass -File windows\\service.ps1 restart"
  echo "Then Admin → Sheet should say the sign-in can write to the sheet."
else
  echo
  echo "${Y}Signed in, but not everything checks out${N} (see above)."
  echo "  - Can't read: make sure that Google account can open the sheet."
  echo "  - Read-only: you may have unticked the edit permission; run this again and approve it."
  echo "  - Google refused the scope: in Google Cloud → OAuth consent screen → Data access, add .../auth/spreadsheets."
  exit 1
fi
