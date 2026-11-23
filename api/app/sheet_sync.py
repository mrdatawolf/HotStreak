"""Run a sheet sync and remember how it went; plus the background timer that runs it."""

import json
import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import models, sheet_import, sheet_tabs
from .config import settings
from .db import SessionLocal
from .google_sheet import SheetError, SheetsApi, read_spreadsheet

log = logging.getLogger(__name__)

STATUS_SETTING = "sheet_sync_status"
# The layout the last successful sync read: "data tabs" or "month tabs".
LAYOUT_SETTING = "sheet_layout"
DATA_TABS = "data tabs"
# One sync or app write at a time (the timer, "Sync now" and saves can overlap). Re-entrant: a write
# holds it while it changes the sheet and then syncs.
lock = threading.RLock()


def configured() -> bool:
    return bool(settings.google_sheet and settings.google_credentials_path)


def writes_to_sheet(db: Session) -> bool:
    """True once the sheet has the data tabs: app changes then go to the sheet first, and come back by sync."""
    if not configured():
        return False
    setting = db.get(models.Setting, LAYOUT_SETTING)
    if setting:
        return setting.value == DATA_TABS
    return (get_status(db) or {}).get("source") == DATA_TABS


def get_status(db: Session) -> dict | None:
    setting = db.get(models.Setting, STATUS_SETTING)
    return json.loads(setting.value) if setting else None


def read_sheet(api: SheetsApi) -> tuple[sheet_import.ParseResult, dict | None, str]:
    """Read whichever layout the sheet has: the data tabs (Deals, Quotas, Reps) once they exist, else the month tabs.

    Returns (parsed months, rep info from the Reps tab or None, source). New Deals rows get their IDs filled in.
    """
    _, titles = sheet_tabs.existing_tabs(api)
    if sheet_tabs.DEALS not in titles:
        tabs = read_spreadsheet(settings.google_sheet, settings.google_credentials_path, session=api.session)
        return sheet_import.parse_tabs(tabs), None, "month tabs"
    data = sheet_tabs.parse_data_tabs(sheet_tabs.read_values(api))
    try:
        data.result.warnings += sheet_tabs.fill_ids(api, data.new_ids, data.id_column)
    except SheetError as e:
        data.result.warnings.append(f"Couldn't fill in IDs on {len(data.new_ids)} new Deals row(s): {e}. "
                                    "They're imported anyway and retried next sync.")
    return data.result, data.rep_info, DATA_TABS


def run(read: Callable[[], dict] | None = None, session_factory=SessionLocal, api: SheetsApi | None = None,
        db: Session | None = None) -> dict:
    """Pull the sheet and sync it. Returns (and saves) a status dict; never raises for sheet problems.

    `read` returns month-tab grids (the setup script and tests); `api` is a SheetsApi to use; `db` a session
    to sync into (it's committed), else one from session_factory.
    """
    with lock:
        if db is not None:
            return _run(db, read, api)
        with session_factory() as session:
            return _run(session, read, api)


def _run(db: Session, read, api) -> dict:
    started = datetime.now(timezone.utc)
    try:
        rep_info, source = None, "month tabs"
        if read is not None:
            result = sheet_import.parse_tabs(read())
        else:
            if api is None:
                if not configured():
                    raise SheetError("Set TRACKER_GOOGLE_SHEET and TRACKER_GOOGLE_CREDENTIALS in .env")
                api = SheetsApi(settings.google_sheet, settings.google_credentials_path)
            result, rep_info, source = read_sheet(api)
        if not result.months:
            raise SheetError("No months found in the sheet" if source == DATA_TABS else "No month tabs found in the sheet")
        mismatches = sheet_import.check_totals(result)
        counts = sheet_import.sync(db, result, rep_info=rep_info)
        status = {"ok": True, "message": None, "counts": counts, "source": source,
                  "mismatches": mismatches, "warnings": result.warnings}
        db.merge(models.Setting(key=LAYOUT_SETTING, value=source))
    except SheetError as e:
        db.rollback()
        status = {"ok": False, "message": str(e), "counts": None, "mismatches": [], "warnings": []}
    except Exception:
        db.rollback()
        log.exception("Sheet sync failed")
        status = {"ok": False, "message": "Sync failed unexpectedly; see the API log",
                  "counts": None, "mismatches": [], "warnings": []}
    status["at"] = started.isoformat()
    db.merge(models.Setting(key=STATUS_SETTING, value=json.dumps(status)))
    db.commit()
    return status


def start_timer() -> threading.Event | None:
    """Sync every TRACKER_GOOGLE_SYNC_MINUTES in a background thread. Returns the stop event."""
    if not configured() or settings.google_sync_minutes <= 0:
        return None
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            status = run()
            if not status["ok"]:
                log.warning("Sheet sync: %s", status["message"])
            stop.wait(settings.google_sync_minutes * 60)

    threading.Thread(target=loop, name="sheet-sync", daemon=True).start()
    return stop
