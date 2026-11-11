#!/usr/bin/env python3
"""Check the setup, then run HotStreak. Works the same on Windows, Linux and macOS.

    python start.py            development: checks, installs anything missing, migrates the database, then runs
                               the API (auto-reload) and the Vite dev server together. Ctrl+C stops both.
    python start.py --check    checks only; installs and starts nothing
    python start.py --setup    installs, migrates and builds the web app, then exits (the Windows service installer
                               and updates use this)
    python start.py --serve    setup, then runs the built app as one process, exactly as the Windows service does

On Windows, start.cmd runs this; on Linux/macOS, ./start.sh does.
Settings come from .env (see .env.example), the same as the API and the web dev server.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = ROOT / "api"
WEB = ROOT / "web"
WINDOWS = os.name == "nt"
VENV_PY = API / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")

MODES = {"--check", "--setup", "--serve"}
args = sys.argv[1:]
if any(a not in MODES for a in args) or len(args) > 1:
    sys.exit(__doc__)
MODE = args[0] if args else "--dev"
CHECK_ONLY = MODE == "--check"

# --- Output ---

if WINDOWS:
    os.system("")  # turns on ANSI colours in the Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace", line_buffering=True)
COLOR = sys.stdout.isatty()


def c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def ok(msg): print(f"  {c('32', '✓')} {msg}")
def warn(msg): print(f"  {c('33', '!')} {msg}")
def note(msg): print(f"  {c('2', msg)}")
def step(msg): print(c("1", msg))


def fail(msg):
    print(f"  {c('31', '✗')} {msg}")
    sys.exit(1)


def run(cmd, cwd=None, quiet=False, check=True) -> subprocess.CompletedProcess:
    out = subprocess.DEVNULL if quiet else None
    return subprocess.run([str(x) for x in cmd], cwd=cwd, stdout=out, stderr=out, check=check)


def capture(cmd, cwd=None) -> str:
    res = subprocess.run([str(x) for x in cmd], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                         errors="replace")
    return res.stdout if res.returncode == 0 else ""


VENV_CMD = "api\\.venv\\Scripts\\python.exe" if WINDOWS else ".venv/bin/python"
API_CMD = "cd api && " + VENV_CMD

# --- Tools ---

step("Tools")
if sys.version_info < (3, 12):
    fail(f"Python 3.12+ needed (found {sys.version.split()[0]} at {sys.executable})")
ok(f"Python {sys.version.split()[0]}")
NODE = shutil.which("node")
NPM = shutil.which("npm")
if not NODE:
    fail("node not found (install Node.js 20+ from https://nodejs.org)")
node_version = capture([NODE, "--version"]).strip()
if int(node_version.lstrip("v").split(".")[0] or 0) < 20:
    fail(f"Node.js 20+ needed (found {node_version})")
if not NPM:
    fail("npm not found")
ok(f"Node.js {node_version}")

# --- Settings ---

step("Settings")
if not (ROOT / ".env").is_file():
    fail(".env missing — copy .env.example to .env and set TRACKER_BREAKGLASS_PASSWORD")
ok(".env found")

# --- API dependencies ---

step("API")
if not VENV_PY.is_file():
    if CHECK_ONLY:
        fail("api/.venv missing (run without --check to create it)")
    note("creating api/.venv…")
    run([sys.executable, "-m", "venv", API / ".venv"])
requirements = API / "requirements-dev.txt"
# pip's dry run lists anything missing or at the wrong version.
if "Would install" in capture([VENV_PY, "-m", "pip", "install", "--dry-run", "-r", requirements]):
    if CHECK_ONLY:
        fail("Python packages out of date (run without --check to install)")
    note("installing Python packages…")
    run([VENV_PY, "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", requirements])
ok("Python packages installed")

# Every value below is read the way the app reads it (.env, overridden by the environment).
CONFIG_SCRIPT = """
import json
from app.config import settings
creds = settings.google_credentials_path
print(json.dumps({
    "api_host": settings.api_host, "api_port": settings.api_port,
    "web_ip": settings.web_ip, "web_port": settings.web_port,
    "breakglass_set": bool(settings.breakglass_password),
    "google_sheet": settings.google_sheet, "google_creds": str(creds) if creds else "",
    "sync_minutes": settings.google_sync_minutes,
}))
"""
try:
    cfg = json.loads(capture([VENV_PY, "-c", CONFIG_SCRIPT], cwd=API))
except json.JSONDecodeError:
    run([VENV_PY, "-c", CONFIG_SCRIPT], cwd=API, check=False)  # shows the error
    fail("Couldn't read the settings; check .env")

# Database: create or migrate to the latest schema.
if CHECK_ONLY:
    if "(head)" in capture([VENV_PY, "-m", "alembic", "current"], cwd=API):
        ok("Database schema is up to date")
    else:
        warn(f"Database needs migrating (run without --check, or: {API_CMD} -m alembic upgrade head)")
else:
    if run([VENV_PY, "-m", "alembic", "upgrade", "head"], cwd=API, quiet=True, check=False).returncode:
        fail(f"Database migration failed (to see why: {API_CMD} -m alembic upgrade head)")
    ok("Database schema is up to date")

COUNTS_SCRIPT = """
from sqlalchemy import func, select
from app import models
from app.db import SessionLocal
with SessionLocal() as db:
    deals = db.scalar(select(func.count()).select_from(models.Deal))
    admins = db.scalar(select(func.count()).select_from(models.User).where(models.User.role == "admin", models.User.active))
print(deals, admins)
"""
counts = capture([VENV_PY, "-c", COUNTS_SCRIPT], cwd=API).split()
deals, admins = counts if len(counts) == 2 else ("?", "?")
if deals == "0":
    warn(f'No deals yet — load the sheet: {API_CMD} -m scripts.import_sheet "path/to/sales-sheet.xlsx"')
elif deals != "?":
    ok(f"{deals} deals in the database")
if not cfg["breakglass_set"] and admins == "0":
    fail("No admin accounts and TRACKER_BREAKGLASS_PASSWORD is empty — set it in .env so you can sign in")
elif cfg["breakglass_set"]:
    ok("Break-glass sign-in is on")

if cfg["google_sheet"] and cfg["google_creds"]:
    if Path(cfg["google_creds"]).is_file():
        ok(f"Google Sheet sync on (every {cfg['sync_minutes']} min)")
    else:
        warn(f"TRACKER_GOOGLE_CREDENTIALS points to a missing file ({cfg['google_creds']}); sheet sync will fail")
else:
    warn("Google Sheet sync off (set TRACKER_GOOGLE_SHEET and TRACKER_GOOGLE_CREDENTIALS; see Admin → Sheet)")

# --- Web dependencies ---

step("Web")


def mtime(path: Path) -> float:
    return path.stat().st_mtime if path.exists() else 0


lock = WEB / "package-lock.json"
if mtime(lock) > mtime(WEB / "node_modules" / ".package-lock.json"):
    if CHECK_ONLY:
        fail("web/node_modules missing or out of date (run without --check to install)")
    note("installing npm packages…")
    run([NPM, "install", "--no-fund", "--no-audit", "--loglevel=error"], cwd=WEB)
ok("npm packages installed")


def newest_source() -> float:
    files = [WEB / n for n in ("index.html", "package-lock.json", "vite.config.ts", "tsconfig.json",
                                "tsconfig.app.json", "tsconfig.node.json")]
    for folder in ("src", "public"):
        files += [p for p in (WEB / folder).rglob("*") if p.is_file()]
    return max(mtime(p) for p in files)


built = WEB / "dist" / "index.html"
if MODE in ("--setup", "--serve"):
    if newest_source() > mtime(built):
        note("building the web app…")
        if run([NPM, "run", "build", "--silent"], cwd=WEB, check=False).returncode:
            fail("Web app build failed; see the errors above")
    ok("Web app built")
elif MODE == "--check":
    if not built.is_file():
        note("web app not built yet (only needed for --serve and the Windows service)")
    elif newest_source() > mtime(built):
        note("web app build is older than the source (--setup or --serve rebuilds it)")

if MODE == "--setup":
    print(c("32", "Setup complete."))
    sys.exit(0)

# --- Ports ---

step("Ports")


def port_free(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
    try:
        # On Linux/macOS this ignores sockets lingering from the last run; on Windows the same option would let us
        # bind on top of a live server, so ask for exclusive use there instead.
        if WINDOWS:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


web_addr = f"{cfg['web_ip']}:{cfg['web_port']}"
if MODE in ("--dev", "--check"):
    api_addr = f"{cfg['api_host']}:{cfg['api_port']}"
    if not port_free(cfg["api_host"], int(cfg["api_port"])):
        fail(f"API port {api_addr} is in use (another start.py running, or the HotStreak service?)")
    ok(f"API port {api_addr} is free")
if not port_free(cfg["web_ip"], int(cfg["web_port"])):
    fail(f"Web port {web_addr} is in use (another start.py running, or the HotStreak service?)")
ok(f"Web port {web_addr} is free")

if CHECK_ONLY:
    print(c("32", "All checks passed."))
    sys.exit(0)

# --- Run ---

step("Starting")
procs: list[tuple[str, subprocess.Popen]] = []
child_env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}


def start(name: str, color: str, cmd, cwd: Path) -> subprocess.Popen:
    """Start a server in its own process group, with its output prefixed so the two logs can be told apart."""
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
    proc = subprocess.Popen([str(x) for x in cmd], cwd=cwd, env=child_env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
    prefix = c(color, f"[{name}]")

    def pump():
        for line in iter(proc.stdout.readline, b""):
            print(f"{prefix} {line.decode('utf-8', 'replace').rstrip()}")

    threading.Thread(target=pump, daemon=True).start()
    procs.append((name, proc))
    return proc


def stop_all():
    print(c("2", "\nStopping…"))
    for _name, proc in procs:
        if proc.poll() is not None:
            continue
        # The whole tree: uvicorn's reloader and its worker, or node and vite.
        if WINDOWS:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            import signal
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for _name, proc in procs:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def up(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=2)
        return True
    except OSError:
        return False


def wait_until_up(proc: subprocess.Popen, url: str) -> bool:
    for _ in range(60):
        if proc.poll() is not None:
            return False
        if up(url):
            return True
        time.sleep(0.5)
    return False


if not WINDOWS:  # `kill` stops the servers too, the same as Ctrl+C
    import signal
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))

browse_host = "localhost" if cfg["web_ip"] in ("0.0.0.0", "::") else cfg["web_ip"]
browse = c("1", f"http://{browse_host}:{cfg['web_port']}")
try:
    if MODE == "--serve":
        server = start("app", "36", [VENV_PY, "-m", "app", "--serve"], API)
        if not wait_until_up(server, f"http://{browse_host}:{cfg['web_port']}/api/health"):
            fail("The app didn't start; see the [app] log above")
        ok(f"Open {browse}   {c('2', '(built app, as the service runs it; Ctrl+C stops it)')}")
    else:
        api = start("api", "33", [VENV_PY, "-m", "app", "--reload"], API)
        if not wait_until_up(api, f"http://{cfg['api_host']}:{cfg['api_port']}/api/health"):
            fail("API didn't start; see the [api] log above")
        ok(f"API running on http://{cfg['api_host']}:{cfg['api_port']} (docs at /docs)")
        # node + vite directly rather than `npm run dev`: one less process layer to stop on Windows.
        start("web", "32", [NODE, WEB / "node_modules" / "vite" / "bin" / "vite.js", "--clearScreen", "false"], WEB)
        ok(f"Open {browse}   {c('2', '(Ctrl+C stops both)')}")

    # Stop everything if either server exits.
    while all(proc.poll() is None for _name, proc in procs):
        time.sleep(0.5)
    for name, proc in procs:
        if proc.poll() is not None:
            warn(f"[{name}] exited (code {proc.returncode})")
except KeyboardInterrupt:
    pass
finally:
    stop_all()
