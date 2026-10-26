"""Run a sheet sync and remember how it went; plus the background timer that runs it."""

import json
import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import models, sheet_import
from .config import settings
from .db import SessionLocal
from .google_sheet import SheetError, read_spreadsheet

log = logging.getLogger(__name__)

STATUS_SETTING = "sheet_sync_status"
# One sync at a time (the timer and "Sync now" can overlap).
_running = threading.Lock()


def configured() -> bool:
    return bool(settings.google_sheet and settings.google_credentials_path)


def get_status(db: Session) -> dict | None:
    setting = db.get(models.Setting, STATUS_SETTING)
    return json.loads(setting.value) if setting else None


def run(read: Callable[[], dict] | None = None, session_factory=SessionLocal) -> dict:
    """Pull the sheet and sync it. Returns (and saves) a status dict; never raises for sheet problems."""
    started = datetime.now(timezone.utc)
    with _running:
        with session_factory() as db:
            try:
                if read is None:
                    if not configured():
                        raise SheetError("Set TRACKER_GOOGLE_SHEET and TRACKER_GOOGLE_CREDENTIALS in .env")
                    tabs = read_spreadsheet(settings.google_sheet, settings.google_credentials_path)
                else:
                    tabs = read()
                result = sheet_import.parse_tabs(tabs)
                if not result.months:
                    raise SheetError("No month tabs found in the sheet")
                mismatches = sheet_import.check_totals(result)
                counts = sheet_import.sync(db, result)
                status = {"ok": True, "message": None, "counts": counts,
                          "mismatches": mismatches, "warnings": result.warnings}
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
