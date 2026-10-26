#!/usr/bin/env bash
# Check the setup, then run the API and the web dev server together. Ctrl+C stops both.
#
#   ./start.sh            checks, installs anything missing, migrates the database, starts both
#   ./start.sh --check    checks only; starts nothing
#
# Settings come from .env (see .env.example), the same as the API and the web dev server.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API="$ROOT/api"
WEB="$ROOT/web"
PY="$API/.venv/bin/python"
CHECK_ONLY=false
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=true

if [[ -t 1 ]]; then
  BOLD=$'\e[1m'; RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; DIM=$'\e[2m'; RESET=$'\e[0m'
else
  BOLD=''; RED=''; GREEN=''; YELLOW=''; DIM=''; RESET=''
fi
ok()   { echo "  ${GREEN}✓${RESET} $*"; }
warn() { echo "  ${YELLOW}!${RESET} $*"; }
fail() { echo "  ${RED}✗${RESET} $*"; exit 1; }
step() { echo "${BOLD}$*${RESET}"; }

# --- Tools ---

step "Tools"
command -v python3 >/dev/null || fail "python3 not found"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' \
  || fail "Python 3.12+ needed (found $(python3 --version 2>&1))"
ok "$(python3 --version)"
command -v node >/dev/null || fail "node not found (install Node.js 20+)"
node -e 'process.exit(Number(process.versions.node.split(".")[0]) < 20 ? 1 : 0)' \
  || fail "Node.js 20+ needed (found $(node --version))"
command -v npm >/dev/null || fail "npm not found"
ok "Node.js $(node --version)"

# --- Settings ---

step "Settings"
[[ -f "$ROOT/.env" ]] || fail ".env missing — copy .env.example to .env and set TRACKER_BREAKGLASS_PASSWORD"
ok ".env found"

# --- API dependencies ---

step "API"
if [[ ! -x "$PY" ]]; then
  $CHECK_ONLY && fail "api/.venv missing (run without --check to create it)"
  echo "  ${DIM}creating api/.venv…${RESET}"
  python3 -m venv "$API/.venv"
fi
# pip's dry run lists anything missing or at the wrong version.
if "$PY" -m pip install --dry-run -r "$API/requirements-dev.txt" 2>/dev/null | grep -q '^Would install'; then
  $CHECK_ONLY && fail "Python packages out of date (run without --check to install)"
  echo "  ${DIM}installing Python packages…${RESET}"
  "$PY" -m pip install -q -r "$API/requirements-dev.txt"
fi
ok "Python packages installed"

# Every value below is read the way the app reads it (.env, overridden by the environment).
# Prints shell assignments; values are quoted with shlex.
eval "$(cd "$API" && "$PY" - <<'EOF'
import os, shlex
from dotenv import dotenv_values
from app.config import ROOT_DIR, settings
env = {**dotenv_values(ROOT_DIR / ".env"), **os.environ}
creds = settings.google_credentials_path
values = {
    "API_HOST": settings.api_host,
    "API_PORT": settings.api_port,
    "WEB_IP": env.get("TRACKER_WEB_IP") or "127.0.0.1",
    "WEB_PORT": env.get("TRACKER_WEB_PORT") or "5190",
    "BREAKGLASS_SET": "1" if settings.breakglass_password else "",
    "GOOGLE_SHEET": settings.google_sheet,
    "GOOGLE_CREDS": str(creds) if creds else "",
    "SYNC_MINUTES": settings.google_sync_minutes,
}
for k, v in values.items():
    print(f"{k}={shlex.quote(str(v))}")
EOF
)"

# Database: create or migrate to the latest schema.
if $CHECK_ONLY; then
  (cd "$API" && .venv/bin/alembic current 2>/dev/null | grep -q '(head)') && ok "Database schema is up to date" \
    || warn "Database needs migrating (run without --check, or: cd api && .venv/bin/alembic upgrade head)"
else
  (cd "$API" && .venv/bin/alembic upgrade head >/dev/null 2>&1) || fail "Database migration failed (cd api && .venv/bin/alembic upgrade head)"
  ok "Database schema is up to date"
fi

COUNTS="$(cd "$API" && "$PY" - 2>/dev/null <<'EOF'
from sqlalchemy import func, select
from app import models
from app.db import SessionLocal
with SessionLocal() as db:
    deals = db.scalar(select(func.count()).select_from(models.Deal))
    admins = db.scalar(select(func.count()).select_from(models.User).where(models.User.role == "admin", models.User.active))
print(deals, admins)
EOF
)" || COUNTS="? ?"
read -r DEALS ADMINS <<<"$COUNTS"
if [[ "$DEALS" == "0" ]]; then
  warn "No deals yet — load the sheet: cd api && .venv/bin/python -m scripts.import_sheet \"../Samples/2026 Sales Sheet.xlsx\""
elif [[ "$DEALS" != "?" ]]; then
  ok "$DEALS deals in the database"
fi
if [[ -z "$BREAKGLASS_SET" && "$ADMINS" == "0" ]]; then
  fail "No admin accounts and TRACKER_BREAKGLASS_PASSWORD is empty — set it in .env so you can sign in"
elif [[ -n "$BREAKGLASS_SET" ]]; then
  ok "Break-glass sign-in is on"
fi

if [[ -n "$GOOGLE_SHEET" && -n "$GOOGLE_CREDS" ]]; then
  if [[ -f "$GOOGLE_CREDS" ]]; then
    ok "Google Sheet sync on (every $SYNC_MINUTES min)"
  else
    warn "TRACKER_GOOGLE_CREDENTIALS points to a missing file ($GOOGLE_CREDS); sheet sync will fail"
  fi
else
  warn "Google Sheet sync off (set TRACKER_GOOGLE_SHEET and TRACKER_GOOGLE_CREDENTIALS; see Admin → Sheet)"
fi

# --- Web dependencies ---

step "Web"
if [[ ! -d "$WEB/node_modules" || "$WEB/package-lock.json" -nt "$WEB/node_modules/.package-lock.json" ]]; then
  $CHECK_ONLY && fail "web/node_modules missing or out of date (run without --check to install)"
  echo "  ${DIM}installing npm packages…${RESET}"
  (cd "$WEB" && npm install --no-fund --no-audit --loglevel=error)
fi
ok "npm packages installed"

# --- Ports ---

step "Ports"
port_free() {  # host port
  python3 - "$1" "$2" <<'EOF'
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
s = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind((host, port))
except OSError:
    sys.exit(1)
EOF
}
port_free "$API_HOST" "$API_PORT" || fail "API port $API_HOST:$API_PORT is in use (another ./start.sh running?)"
ok "API port $API_HOST:$API_PORT is free"
port_free "$WEB_IP" "$WEB_PORT" || fail "Web port $WEB_IP:$WEB_PORT is in use"
ok "Web port $WEB_IP:$WEB_PORT is free"

$CHECK_ONLY && { echo "${GREEN}All checks passed.${RESET}"; exit 0; }

# --- Run ---

step "Starting"
PIDS=()
kill_tree() {  # a server and everything it started (uvicorn's reloader, npm → vite)
  local child
  for child in $(pgrep -P "$1" 2>/dev/null); do kill_tree "$child"; done
  kill "$1" 2>/dev/null || true
}
cleanup() {
  trap - INT TERM EXIT
  echo
  echo "${DIM}Stopping…${RESET}"
  for pid in "${PIDS[@]}"; do kill_tree "$pid"; done
  wait 2>/dev/null || true
}
api_up() {
  python3 -c "import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2)" \
    "http://$API_HOST:$API_PORT/api/health" 2>/dev/null
}
trap cleanup INT TERM EXIT

# Each server's output is prefixed so the two logs can be told apart.
(cd "$API" && exec "$PY" -m app --reload 2>&1 | sed -u "s/^/${YELLOW}[api]${RESET} /") &
PIDS+=($!)

for _ in $(seq 1 60); do
  api_up && break
  sleep 0.5
done
api_up || fail "API didn't start; see the [api] log above"
ok "API running on http://$API_HOST:$API_PORT (docs at /docs)"

(cd "$WEB" && exec npm run dev -- --clearScreen false 2>&1 | sed -u "s/^/${GREEN}[web]${RESET} /") &
PIDS+=($!)

BROWSE_HOST="$WEB_IP"
[[ "$WEB_IP" == "0.0.0.0" ]] && BROWSE_HOST="localhost"
echo "  ${GREEN}✓${RESET} Open ${BOLD}http://$BROWSE_HOST:$WEB_PORT${RESET}   ${DIM}(Ctrl+C stops both)${RESET}"

# Stop everything if either server exits.
wait -n "${PIDS[@]}" || true
