"""The app's changes, written to the sheet's data tabs (Deals, Quotas, Reps).

Once the sheet has the data tabs it is the source of truth, so an admin's change in the app goes to the sheet
first and is then pulled back by a sync: the app always shows what the sheet holds. Each write runs under the
sync lock (write_then_sync).

Rows are found by what's in them, never by a remembered row number, since people insert, sort and delete rows:
- a deal by its ID ("D00042"); its row is only rewritten or deleted while it still matches the version the app
  last synced, so a change typed on the sheet in the meantime isn't lost (the admin reloads instead);
- quotas by month and rep; reps by name.
Values are written RAW, so text stays exactly as typed (an item like "3/4" isn't read as a date).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import sheet_sync
from .config import settings
from .google_sheet import SheetError, SheetsApi, quote
from .sheet_import import col_letter, text
from .sheet_tabs import (DEALS, DEALS_HEADERS, ID_PATTERN, QUOTAS, REPS, Columns, deal_id, is_record,
                         parse_month_cell, row_version, serial)

# Rows added at the bottom when a tab runs out (the setup leaves 2,000 spare, so this is rare).
GROW_BY = 500


class Conflict(SheetError):
    """The sheet changed since the app last synced; the admin should reload and try again."""


@dataclass
class Tab:
    title: str
    sheet_id: int
    row_count: int
    rows: list[list]  # as stored, header first
    cols: dict[str, int]

    def cell(self, row: list, name: str):
        i = self.cols[name]
        return row[i] if i < len(row) else ""

    def records(self) -> list[tuple[int, list]]:
        """(1-based sheet row, values) for each row with something in it, below the header."""
        return [(n, row) for n, row in enumerate(self.rows[1:], start=2) if is_record(row)]

    def next_row(self) -> int:
        """The row just below the last record."""
        filled = self.records()
        return (filled[-1][0] if filled else 1) + 1


def load(api: SheetsApi, *titles: str) -> dict[str, Tab]:
    """Read these data tabs whole (UNFORMATTED, like the sync), with their columns found by header name."""
    info = api.get({"fields": "sheets.properties(title,sheetId,gridProperties.rowCount)"})
    props = {s["properties"]["title"]: s["properties"] for s in info.get("sheets", [])}
    if missing := [t for t in titles if t not in props]:
        raise SheetError(f"The sheet has no {', '.join(missing)} tab")
    data = api.get({"ranges": [f"{quote(t)}!A1:Z" for t in titles], "valueRenderOption": "UNFORMATTED_VALUE"},
                   path="/values:batchGet")
    tabs = {}
    for title, vr in zip(titles, data.get("valueRanges", [])):
        rows = vr.get("values", [])
        p = props[title]
        tabs[title] = Tab(title=title, sheet_id=p["sheetId"], row_count=p.get("gridProperties", {}).get("rowCount", 0),
                          rows=rows, cols=Columns(title, rows).index)
    return tabs


@dataclass
class Changes:
    """Cell writes and row deletions for one save, sent together by send()."""

    api: SheetsApi
    cells: list[dict] = field(default_factory=list)
    grow: dict[int, int] = field(default_factory=dict)  # sheetId -> rows to add
    deletes: list[tuple[int, int]] = field(default_factory=list)  # (sheetId, 1-based row)
    requests: list[dict] = field(default_factory=list)  # other batchUpdate requests (find/replace)

    def set_row(self, tab: Tab, row: int, values: dict) -> None:
        """Write these columns of one row; other columns (including ones people added) are left alone."""
        if row > tab.row_count + self.grow.get(tab.sheet_id, 0):
            self.grow[tab.sheet_id] = max(GROW_BY, row - tab.row_count)
        for name, value in values.items():
            self.cells.append({"range": f"{quote(tab.title)}!{col_letter(tab.cols[name])}{row}", "values": [[value]]})

    def delete_row(self, tab: Tab, row: int) -> None:
        self.deletes.append((tab.sheet_id, row))

    def send(self) -> None:
        if self.grow:
            self.api.post(":batchUpdate", {"requests": [
                {"appendDimension": {"sheetId": sid, "dimension": "ROWS", "length": n}} for sid, n in self.grow.items()
            ]})
        if self.cells:
            self.api.post("/values:batchUpdate", {"valueInputOption": "RAW", "data": self.cells})
        # Deletes last and bottom-up, so the rows above (just written) don't move.
        reqs = self.requests + [
            {"deleteDimension": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": row - 1, "endIndex": row}}}
            for sid, row in sorted(self.deletes, key=lambda x: -x[1])
        ]
        if reqs:
            self.api.post(":batchUpdate", {"requests": reqs})


# --- Deals ---


def now_serial() -> float:
    """This moment as a Sheets date-time, in the server's local time (what people reading the sheet expect)."""
    return serial(datetime.now())


def _find_deal(tab: Tab, ref: str) -> tuple[int, list]:
    found = [(n, row) for n, row in tab.records() if text(tab.cell(row, "ID")) == ref]
    if not found:
        raise Conflict(f"Deal {ref} isn't on the Deals tab any more (deleted, or its ID was changed). "
                       "The app has been brought up to date; reload.")
    if len(found) > 1:
        raise Conflict(f"Deal {ref} is on the Deals tab twice (rows {', '.join(str(n) for n, _ in found)}). "
                       "Fix it on the sheet; the next sync gives the copy a new ID.")
    return found[0]


def _check_version(tab: Tab, ref: str, row: list, version: str | None) -> None:
    if version and row_version([ref if h == "ID" else tab.cell(row, h) for h in DEALS_HEADERS]) != version:
        raise Conflict(f"Deal {ref} was changed on the sheet since the app last synced. "
                       "The app has been brought up to date; reload to see the change, then edit again.")


def add_deal(api: SheetsApi, values: dict) -> str:
    """Add a Deals row below the last one, with the next ID. `values` maps header -> value. Returns the ID."""
    tab = load(api, DEALS)[DEALS]
    taken = [int(m[1]) for _, row in tab.records() if (m := ID_PATTERN.match(text(tab.cell(row, "ID"))))]
    ref = deal_id(max(taken, default=0) + 1)
    changes = Changes(api)
    changes.set_row(tab, tab.next_row(), {**values, "ID": ref})
    changes.send()
    return ref


def update_deal(api: SheetsApi, ref: str, version: str | None, values: dict) -> str:
    """Rewrite these columns of deal `ref`'s row, if it still matches `version`."""
    tab = load(api, DEALS)[DEALS]
    row_number, row = _find_deal(tab, ref)
    _check_version(tab, ref, row, version)
    changes = Changes(api)
    changes.set_row(tab, row_number, values)
    changes.send()
    return ref


def delete_deal(api: SheetsApi, ref: str, version: str | None) -> None:
    tab = load(api, DEALS)[DEALS]
    row_number, row = _find_deal(tab, ref)
    _check_version(tab, ref, row, version)
    changes = Changes(api)
    changes.delete_row(tab, row_number)
    changes.send()


# --- Quotas and reps ---


def set_quotas(api: SheetsApi, year: int, month: int, reps: list[tuple[str, float | None]]) -> None:
    """Make the Quotas rows for one month exactly `reps`: (rep name, quota or None), in board order.

    The month's existing rows are reused in place, extra ones are added at the bottom, leftovers deleted.
    """
    tab = load(api, QUOTAS)[QUOTAS]
    mine = [n for n, row in tab.records() if parse_month_cell(tab.cell(row, "Month")) == (year, month)]
    changes = Changes(api)
    bottom = tab.next_row()
    for order, (rep, quota) in enumerate(reps, start=1):
        if mine:
            row = mine.pop(0)
        else:
            row, bottom = bottom, bottom + 1
        changes.set_row(tab, row, {"Month": f"{year}-{month:02d}", "Rep": rep,
                                   "Quota": quota if quota is not None else "", "Order": order})
    for row in mine:
        changes.delete_row(tab, row)
    changes.send()


def _rep_rows(tab: Tab, name: str) -> list[int]:
    return [n for n, row in tab.records() if text(tab.cell(row, "Rep")).upper() == name.upper()]


def save_rep(api: SheetsApi, old_name: str | None, name: str, active: bool, counts_toward_total: bool) -> None:
    """Add or change a Reps row. Renaming also renames the rep on every Deals and Quotas row."""
    tabs = load(api, REPS, DEALS, QUOTAS)
    reps = tabs[REPS]
    rows = _rep_rows(reps, old_name or name)
    if old_name and old_name.upper() != name.upper() and _rep_rows(reps, name):
        raise Conflict(f"The Reps tab already has {name}")
    changes = Changes(api)
    changes.set_row(reps, rows[0] if rows else reps.next_row(),
                    {"Rep": name, "Active": active, "Counts toward total": counts_toward_total})
    if old_name and old_name != name:
        for tab in (tabs[DEALS], tabs[QUOTAS]):
            c = tab.cols["Rep"]
            changes.requests.append({"findReplace": {
                "find": old_name, "replacement": name, "matchCase": False, "matchEntireCell": True,
                "range": {"sheetId": tab.sheet_id, "startRowIndex": 1, "startColumnIndex": c, "endColumnIndex": c + 1},
            }})
    for extra in rows[1:]:
        changes.delete_row(reps, extra)
    changes.send()


def delete_rep(api: SheetsApi, name: str) -> None:
    """Remove the rep's Reps row and their Quotas rows (the app only deletes reps without deals)."""
    tabs = load(api, REPS, QUOTAS)
    changes = Changes(api)
    for tab in tabs.values():
        for row in _rep_rows(tab, name):
            changes.delete_row(tab, row)
    changes.send()


# --- Running a write ---


def open_api() -> SheetsApi:
    return SheetsApi(settings.google_sheet, settings.google_credentials_path)


def write_then_sync[T](db: Session, change: Callable[[SheetsApi], T], then: Callable[[T], None] | None = None) -> T:
    """Make one change on the sheet, then sync it back into the app. Returns what `change` returned.

    `then` runs after the sheet write and before the sync (for app-side steps the sync relies on, like a rename).
    Raises 409 when the sheet changed underneath (after syncing, so a reload shows the sheet's version), 502 when
    Google can't be reached or the write fails.
    """
    db.rollback()  # nothing half-made in this session may reach the database
    with sheet_sync.lock:
        api = None
        try:
            api = open_api()
            result = change(api)
        except Conflict as e:
            sheet_sync.run(api=api, db=db)
            raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
        except SheetError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Couldn't save to the Google Sheet: {e}") from None
        if then:
            then(result)
        outcome = sheet_sync.run(api=api, db=db)
        if not outcome["ok"]:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                f"Saved to the Google Sheet, but bringing it into the app failed: {outcome['message']}. "
                                "It shows up after the next sync.")
        return result
