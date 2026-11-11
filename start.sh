#!/usr/bin/env bash
# Linux/macOS launcher; the work is done by start.py (the same on Windows, via start.cmd).
#
#   ./start.sh            checks, installs anything missing, migrates the database, starts the API and web dev server
#   ./start.sh --check    checks only; starts nothing
#   ./start.sh --setup    installs, migrates and builds the web app; starts nothing
#   ./start.sh --serve    runs the built app as one process, the way the Windows service does
exec python3 "$(dirname "${BASH_SOURCE[0]}")/start.py" "$@"
