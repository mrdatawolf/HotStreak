# HotStreak

Web replacement for the client's monthly Google Sheet sales board.

- `api/` — FastAPI + SQLite backend (SQLAlchemy models, Alembic migrations)
- `web/` — React + Vite frontend; talks to the API only through `/api`
- `.env` — shared settings for both (copy from `.env.example`; not committed)

## First-time setup

Needs Python 3.12+ and Node.js 20+. On Windows, install both from python.org and nodejs.org (not the Microsoft
Store Python, which a service can't run) and tick *Add to PATH*.

```bash
cp .env.example .env               # Windows: copy .env.example .env
# Set TRACKER_BREAKGLASS_PASSWORD in .env to a long random value:
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```

Then run the launcher (below). The first run creates `api/.venv`, installs the Python and npm packages, and creates
the database. For fake sales data from 01/2023 to the current month, run the seed script once afterwards:

```bash
cd api && .venv/bin/python -m scripts.seed           # Windows: cd api && .venv\Scripts\python -m scripts.seed
```

Open http://localhost:5190 and sign in with the break-glass username and password from `.env`. Go to
**Admin → Users** and create a personal admin account; use that from then on.

Commands below are written for Linux/macOS. On Windows, use `.venv\Scripts\python` for `.venv/bin/python`, and
`.venv\Scripts\python -m alembic` for `.venv/bin/alembic`.

## Running

`start.py` does the work on every OS. `./start.sh` (Linux/macOS) and `start` / `start.cmd` (Windows) are shortcuts
for it.

```bash
./start.sh            # development: checks, then runs the API and the Vite dev server together; Ctrl+C stops both
./start.sh --check    # checks only
./start.sh --setup    # installs packages, migrates the database, builds the web app; starts nothing
./start.sh --serve    # runs the built app as one process, exactly as the Windows service does
```

The launcher checks Python 3.12+, Node 20+ and `.env`. It creates `api/.venv` and installs the Python and npm
packages when they're missing or out of date, migrates the database, and warns when there are no deals or sheet
sync isn't set up. It refuses to start when there's no way to sign in or a port is taken. Output is prefixed
`[api]` / `[web]`, or `[app]` for `--serve`.

There are two ways to run the app:

- **Development** (`start` with no option): the API on `TRACKER_API_HOST:TRACKER_API_PORT` with auto-reload,
  behind the Vite dev server on `TRACKER_WEB_IP:TRACKER_WEB_PORT`, which proxies `/api` to it.
- **Built** (`--serve`, and the Windows service): `npm run build` output in `web/dist`, served by the API itself on
  `TRACKER_WEB_IP:TRACKER_WEB_PORT`. It's one process and doesn't need Node once built. The address people open
  is the same in both, so TV links keep working.

Or run the development servers separately:

```bash
cd api && .venv/bin/python -m app --reload   # listens on TRACKER_API_HOST:TRACKER_API_PORT; docs at /docs
cd web && npm run dev                        # http://localhost:5190 (TRACKER_WEB_PORT); proxies /api to the API
```

## Windows service

On the client's PC, HotStreak runs as a Windows service through [NSSM](https://nssm.cc). It starts with Windows,
runs without anyone signed in, and restarts itself if it crashes. Install NSSM (`winget install NSSM.NSSM`), or put
`nssm.exe` in `windows\`.

The easy way is to double-click `install.cmd` in the repo folder. It checks for Python 3.12+ (python.org, not the
Store version), Node.js 20+, NSSM, `.env` (and offers to create one with a random break-glass password), and a free
web port, and says how to fix anything missing. When everything passes, it asks whether to install the service (or
update it, if it's already installed) and runs `service.ps1` with Administrator rights.

To do it by hand, from an **Administrator** PowerShell in the repo folder:

```powershell
powershell -ExecutionPolicy Bypass -File windows\service.ps1 install    # set up, register, start
powershell -ExecutionPolicy Bypass -File windows\service.ps1 status
powershell -ExecutionPolicy Bypass -File windows\service.ps1 update     # after git pull or editing .env
powershell -ExecutionPolicy Bypass -File windows\service.ps1 stop       # also: start, restart, uninstall
```

- `install` and `update` run `start.py --setup`, then start the service and wait until it answers. `update` stops
  the service first, because Windows won't replace packages or migrate the database while the service has them
  open.
- The service runs `api\.venv\Scripts\python.exe -m app --serve` as LocalSystem, from `api\`.
- When `TRACKER_WEB_IP` isn't local-only, the script adds a firewall rule for `TRACKER_WEB_PORT` on private and
  domain networks. Set `TRACKER_WEB_IP=0.0.0.0` so the TVs and other PCs can reach it.
- The log is `logs\hotstreak.log`, rotated at 10 MB.
- To debug, stop the service and run `start` (development, auto-reload) or `start --serve` (exactly what the service
  runs) in a terminal. Both use the same port as the service. Run `service.ps1 start` when you're done.
- `uninstall` removes the service and its firewall rule. The database, `.env` and logs are kept.

## Settings (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `TRACKER_API_HOST` / `TRACKER_API_PORT` | `127.0.0.1` / `8000` | Where the API listens; the web dev server proxies `/api` here, so it can stay local-only even when the web app is on the network |
| `TRACKER_WEB_IP` | `127.0.0.1` | Where people open the app (the Vite dev server, or the built app with `--serve` / the service); `0.0.0.0` makes it reachable from other machines |
| `TRACKER_WEB_PORT` | `5190` | Port for the same |
| `TRACKER_WEB_ALLOWED_HOSTS` | *(none)* | Comma-separated hostnames allowed to open the app; IP addresses always work |
| `TRACKER_BREAKGLASS_USER` | `breakglass` | Break-glass sign-in name |
| `TRACKER_BREAKGLASS_PASSWORD` | *(empty = off)* | Break-glass password |
| `TRACKER_DATABASE_URL` | `sqlite:///api/tracker.db` | Database |
| `TRACKER_CORS_ORIGINS` | the web dev server | Only needed if a browser calls the API directly, not via the proxy |
| `TRACKER_SESSION_DAYS` | `14` | How long a sign-in lasts |
| `TRACKER_GOOGLE_SHEET` | *(empty)* | The client's Google Sheet URL; sync is off until this and the key are set |
| `TRACKER_GOOGLE_CREDENTIALS` | *(empty)* | Path to the service-account JSON key, or a user token from `scripts.google_login` (relative to the repo root) |
| `TRACKER_GOOGLE_SYNC_MINUTES` | `5` | Minutes between syncs; `0` = only *Sync now* |

## Accounts and access

- **Admin** — everything, including the Admin screens (sheet sync, users, reps, quotas, items, clients, client
  names, flags, settings).
- **User** — views the board and enters, edits, and deletes deals in unlocked months.
- **Break-glass** — the super admin defined in `.env`, for first-time setup and recovery if every admin is
  locked out. It has no database row, so it can't be deleted, disabled, or locked out, and always has full access.
  Failed attempts are slowed down and logged. Blank the password in `.env` to turn it off (existing break-glass
  sign-ins stop working immediately). Changing it takes effect when the API restarts.
- **TV display** — Admin → Settings → *Create TV link*. Opening that link once on a TV saves a read-only key on
  that device; it can view the board and Reports (read-only) and nothing else. *New link* disconnects every display
  using the old one.

Accounts lock for 15 minutes after 5 wrong passwords; an admin can unlock early or reset the password.
The API refuses to demote, deactivate, or delete the last active admin. Passwords are hashed with scrypt;
only a hash of each session token is stored. Sign-in tokens are kept in the browser's `localStorage`.

## Deals and months

- **Deals** (any signed-in user): *Add deal* on the board or the Deals page. Pick a rep and client (type to search,
  or choose *+ New client* to add one with an optional branch), then one or more item lines — pick from the catalog
  or type free text like "Various". The total adds up the line amounts unless you type your own. Click a deal card
  on the board, or a row on the Deals page, to edit or delete it. Each deal records who entered and last changed it.
- **Months** (admins, Admin → Months): *Start <next month>* copies the reps, their order, and quotas from the month
  before (inactive reps are left off), like cloning the sheet tab. *Lock* makes a month's deals and quotas read-only;
  *Unlock* reverses it. The board's current month is the newest unlocked one, so start the new month and lock the
  old one when you're ready to roll over.

## Reports

Any signed-in user, and TV displays; refreshes every 5 minutes. One page per header button, sharing the filters
(range, rep, **brand** and/or **model**; they carry over between pages). Every chart has a table view.

- **Overview** (`/reports`) — total sales, deals, average deal, quota attainment, units, active/new/repeat clients
  (each vs the prior period of the same length); monthly sales vs the year before.
- **Reps** (`/reports/reps`) — sales and attainment by rep; an attainment heatmap by rep and month.
- **Products** (`/reports/products`) — brand/model breakdowns (below) and product mix by category.
- **Clients** (`/reports/clients`) — top clients and deal-size distribution.
- **Trends** (`/reports/trends`) — uses the whole history, so the range filter is hidden. Quarter and year
  forecasts, year-to-date vs the same months last year, 3/6/12-month averages, the rolling 12-month total (the
  trend line that works on noisy sales), monthly sales with a 3-month average, quarter by quarter vs the same quarter
  last year, average monthly sales by year, an average for each calendar month, and growth by rep and brand (last
  12 months vs the 12 before). The open month is left out of trends and averages.

Forecasting (`api/app/trends.py`): one month's sales miss any simple estimate by ~40–45% on the client's data, so
there's no monthly forecast and no straight trend line through monthly sales (the noise swamps the slope). A
forecast is the finished months so far plus the remaining months at the last-12-month average (the open month counts
its sales so far if higher). Its "likely" range is how far that same estimate missed on this tracker's own history,
over the same number of months ahead (about ±20% for a quarter). Blending in the same months last year tested no
better. Compared with last year and with the team quota (months not started yet assume the open month's quota).

Brand/model breakdowns: *Sales by brand* (click a brand to filter), *Sales by model* (top 10; the table view lists
every model with brand, category, sales and units), and a month-by-month mix by brand — or by model once a brand is
picked. With a brand or model filter, every figure counts only those items' share of each deal ("how much Sharp
did we sell", by rep, client, month…); quota attainment is hidden then. Items without a brand show as "(no brand)".

Team figures follow the board's rule (reps not counted toward the total, like HOUSE, are left out unless you filter
to them). Item/category figures split each deal total across its lines — by line amounts when all lines have one,
otherwise by quantity. Chart colors are colorblind-checked for both themes (`web/src/components/charts.tsx`).

## The board

`/board` always shows the current month (newest unlocked), so it's the URL to put on the office TV.
`/board/<id>` pins a specific month. The page refreshes every 30 seconds.
Left/right arrow keys step back/forward a month; stepping onto the current month returns to `/board`.
The System/Light/Dark switch and the font menu are saved per device in `localStorage` (`tracker-theme`,
`tracker-font`). Fonts are bundled with the app, so displays don't need internet access.

## The client's Google Sheet

The client keeps entering deals on their Google Sheet; the API copies it into the database every
`TRACKER_GOOGLE_SYNC_MINUTES` (default 5), and **Admin → Sheet** shows the last sync and has *Sync now*.

**Setup** (once): in Google Cloud, enable the Google Sheets API, create a service account, and download a JSON key
to `api/secrets/` (not committed). Share the sheet with the service account's email as **Viewer**. In `.env` set
`TRACKER_GOOGLE_SHEET` (the sheet's URL) and `TRACKER_GOOGLE_CREDENTIALS` (the key's path), then restart the API.

**Stopgap without a service account:** sign in as a Google account that can view the sheet. Create an OAuth client
ID (Desktop app) in Google Cloud, save its JSON as `api/secrets/google-oauth-client.json`, run
`.venv/bin/python -m scripts.google_login` from `api/`, and set `TRACKER_GOOGLE_CREDENTIALS` to the token it saves.
While the OAuth consent screen is in Testing, the sign-in lasts about 7 days; run the script again when
**Admin → Sheet** says it expired. Full steps are in `api/scripts/google_login.py`.

**What a sync does** (safe to repeat):
- Every month tab (named like `0124`, `926`, `11/26` or `03/24`) is a month; other tabs (summaries, templates)
  are skipped. The newest tab that isn't for a future month is open; the rest are locked.
- Deals from the sheet are replaced with the sheet's current contents and are read-only in the app (each records
  its cell, e.g. `926!C5`). Deals entered in the app are kept. Each month's reps and quotas come from the sheet.
- Every rep's SALES cell and each MONTHLY TOTAL are checked against the deals read; differences are listed.
- Client markers are stripped from the name: `*` or a blue fill (older tabs) → the *New customer* flag;
  `+` (a notation the client uses) → the deal's `sheet_plus` column, shown in the **+** column on Deals.
  Yellow fills (an old rule) are ignored.
- Item text is split into lines on newlines, double spaces, ` & ` and `(n)` counts; `(2) XC4342` is qty 2.
  Each line is split into **brand + model** and linked to the item catalog (Admin → Items):
  "Sharp BP-71C31" → Sharp / BP-71C31, "SH - C507F" → Sharp / C507F, "Lex M3250" → Lexmark / M3250. Text with
  no brand gets one when the model is unambiguous (`BP-`/`MX-` → Sharp, `XM`/`XC` → Lexmark) or the sheet only
  ever names one brand for it; otherwise the brand stays empty ("Refi", "Various"). Items match by brand + model
  ignoring case and punctuation, so "MX-C428F" and "Sharp MX-C428f" are one item. New items start as category
  *Other*; set categories (and tidy brand/model) on Admin → Items — later syncs keep using the edited item.
  Rules: `api/app/item_parse.py`.
- A deal listed under two reps (a split) is counted for both, as on the sheet. HOUSE counts toward the total.

**Name fixes** (Admin → Client names, Admin → Item names): spellings that differ only by case, spaces or
punctuation are grouped automatically ("BRAMBLE CREEK" = "Bramble Creek", "XM-3250" = "XM3250"). Likely matches are
suggested — for clients, close spellings ("Copper Canyon Crediit Union"); for items, only the same model under
different brands ("Lexmark C407F" vs "Sharp C407F"), since near-identical model numbers are different machines.
Item names show as their catalog item, so brand/no-brand spellings are already merged and need no fix. Per
name: *Use “…”*, *Fix…* (autocomplete over existing names and earlier fixes) or *Not a typo*; or *Fix all
suggestions*, which keeps each group's most-used spelling. Fixes are stored in `name_fixes`, applied right away and
on every sync; *Undo* puts things back as typed.

**From the command line** (from `api/`), e.g. to load an .xlsx export (File → Download → Microsoft Excel):

```bash
.venv/bin/python -m scripts.import_sheet "path/to/sales-sheet.xlsx" [--dry-run] [--reset]
.venv/bin/python -m scripts.import_sheet --google [--dry-run]
```

`--dry-run` only reports; `--reset` first deletes all sales data, including deals entered in the app (users,
settings and name fixes are kept). Code: `api/app/sheet_import.py` (parser + sync), `google_sheet.py` (Sheets API),
`sheet_sync.py` (timer + status), `name_fixes.py`.

## Changing the API

1. Edit `api/app/models.py`, then create a migration:
   `.venv/bin/alembic revision --autogenerate -m "describe change"` and `.venv/bin/alembic upgrade head`
2. After changing endpoints or schemas, regenerate the frontend types:
   `cd api && .venv/bin/python -m scripts.export_openapi && cd ../web && npm run gen:api`

`python -m scripts.seed --reset` replaces the sales data (reps, clients, items, deals, months) but keeps users,
settings and name fixes.

## Tests

```bash
cd api && .venv/bin/python -m pytest
cd web && npm run build && npm run lint
```

## Notes

- Money is stored as integer cents.
- A rep shows on a month's board via a `period_reps` row, which also holds that month's quota
  (null = no quota, shown as `~`). Quota unit is the `quota_unit` setting: `usd_thousands` (default), `usd`, or `units`;
  the board shows the quota as a plain number and uses the unit only for the percent bars.
- Flags (e.g. the sheet's green highlight) are configurable name + color; meaning still to be confirmed with the client.
