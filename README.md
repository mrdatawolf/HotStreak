# HotStreak

Web replacement for the client's monthly Google Sheet sales board ("2026 Sales Sheet"; photo in `Samples/`).

- `api/` — FastAPI + SQLite backend (SQLAlchemy models, Alembic migrations)
- `web/` — React + Vite frontend; talks to the API only through `/api`
- `.env` — shared settings for both (copy from `.env.example`; not committed)

## First-time setup

```bash
cp .env.example .env
# Set TRACKER_BREAKGLASS_PASSWORD in .env to a long random value:
python3 -c "import secrets; print(secrets.token_urlsafe(24))"

# API
cd api
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head       # create tracker.db
.venv/bin/python -m scripts.seed     # fake sales data, 02/2023 → current month

# Web
cd ../web
npm install
```

Then start both (below), open http://localhost:5190, and sign in with the break-glass username and password
from `.env`. Go to **Admin → Users** and create a personal admin account; use that from then on.

## Running

```bash
./start.sh            # checks the setup, then runs the API and the web app together; Ctrl+C stops both
./start.sh --check    # checks only
```

`start.sh` checks Python 3.12+, Node 20+ and `.env`; creates `api/.venv` and installs Python/npm packages when
they're missing or out of date; migrates the database; warns when there are no deals or sheet sync isn't set up;
refuses to start without a way to sign in or when a port is taken. Output is prefixed `[api]` / `[web]`.

Or run them separately:

```bash
cd api && .venv/bin/python -m app --reload   # listens on TRACKER_API_HOST:TRACKER_API_PORT; docs at /docs
cd web && npm run dev                        # http://localhost:5190 (TRACKER_WEB_PORT); proxies /api to the API
```

## Settings (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `TRACKER_API_HOST` / `TRACKER_API_PORT` | `127.0.0.1` / `8000` | Where the API listens; the web dev server proxies `/api` here, so it can stay local-only even when the web app is on the network |
| `TRACKER_WEB_IP` | `127.0.0.1` | Web dev server address; `0.0.0.0` makes it reachable from other machines |
| `TRACKER_WEB_PORT` | `5190` | Web dev server port |
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
- Every month tab (named `MMYY` or `MYY`, e.g. `0124`, `926`) is a month; other tabs (Overview, Monthly Template,
  Billboard Mirror) are skipped. The newest tab that isn't for a future month is open; the rest are locked.
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
punctuation are grouped automatically ("BEAR RIVER" = "Bear River", "XM-3250" = "XM3250"). Likely matches are
suggested — for clients, close spellings ("Coast Central Crediit Union"); for items, only the same model under
different brands ("Lexmark C407F" vs "Sharp C407F"), since near-identical model numbers are different machines.
Item names show as their catalog item, so brand/no-brand spellings are already merged and need no fix. Per
name: *Use “…”*, *Fix…* (autocomplete over existing names and earlier fixes) or *Not a typo*; or *Fix all
suggestions*, which keeps each group's most-used spelling. Fixes are stored in `name_fixes`, applied right away and
on every sync; *Undo* puts things back as typed.

**From the command line** (from `api/`), e.g. to load an .xlsx export (File → Download → Microsoft Excel):

```bash
.venv/bin/python -m scripts.import_sheet "../Samples/2026 Sales Sheet.xlsx" [--dry-run] [--reset]
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
