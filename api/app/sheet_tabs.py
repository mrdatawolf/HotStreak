"""The sheet's data tabs: Deals, Quotas and Reps, one row per record.

They replace the hand-laid-out month tabs as the place the data lives. People and the app both edit the
Deals rows; view tabs (Board, Overview) are built from them with formulas. This module builds the rows
from the database and sets the tabs up on the sheet (scripts.setup_sheet_tabs runs it once, at the switch).

Deals columns are fixed by DEALS_HEADERS; the ID column ("D00001") is how the app finds a deal's row.
People leave it blank on new rows and the next sync fills it in.
"""

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import models
from .board import line_label
from .google_sheet import SheetError, SheetsApi, quote
from .sheet_import import (FLAG_NEW, ParseResult, RepInfo, SheetDeal, SheetMonth, SheetRep, split_client,
                           split_items, text, to_number)

DEALS = "Deals"
QUOTAS = "Quotas"
REPS = "Reps"
DATA_TABS = (DEALS, QUOTAS, REPS)

# Tuples, so nothing can change them by accident; list() them where a row is needed.
DEALS_HEADERS = ("ID", "Month", "Date", "Rep", "Client", "Location", "New customer", "Plus", "Items", "Amount",
                 "Notes", "Entered by", "Updated")
QUOTAS_HEADERS = ("Month", "Rep", "Quota", "Order")
REPS_HEADERS = ("Rep", "Active", "Counts toward total")
HEADERS = {DEALS: DEALS_HEADERS, QUOTAS: QUOTAS_HEADERS, REPS: REPS_HEADERS}

# Blank rows left below the data for people to type into (validation covers them too).
SPARE_ROWS = 2000

MONTH_RULE = r'^\d{4}-(0[1-9]|1[0-2])$'
ID_PATTERN = re.compile(r"^D(\d+)$")
_SHEETS_EPOCH = date(1899, 12, 30)


def deal_id(n: int) -> str:
    return f"D{n:05d}"


def month_text(period: models.Period) -> str:
    return f"{period.year}-{period.month:02d}"


def serial(value: date | datetime) -> float:
    """A date as a Sheets serial number, so the cell is a real date (formatted by the column)."""
    if isinstance(value, datetime):
        return (value - datetime(1899, 12, 30)).total_seconds() / 86400
    return float((value - _SHEETS_EPOCH).days)


def items_text(deal: models.Deal) -> str:
    """'(2) Sharp BP-71C31  Lexmark XM3250': the sheet's own notation, which the sync reads back as the same lines."""
    return "  ".join(f"({line.qty}) {line_label(line)}" if line.qty > 1 else line_label(line) for line in deal.lines)


def deal_values(d: models.Deal, id_text: str, month: str, entered_by: str = "", updated=None) -> list:
    """A deal as a Deals row, in DEALS_HEADERS order. `updated` is a date/time for the Updated column."""
    return [
        id_text,
        month,
        serial(d.deal_date) if d.deal_date else "",
        d.rep.name,
        d.client.name,
        d.client.location or "",
        any(f.name == FLAG_NEW[0] for f in d.flags),
        bool(d.sheet_plus),
        items_text(d),
        d.total_cents / 100,
        d.notes or "",
        entered_by,
        serial(updated) if updated else "",
    ]


def row_version(values: list) -> str:
    """A fingerprint of a Deals row's values (DEALS_HEADERS order, as read UNFORMATTED)."""
    norm = ["" if v is None else v for v in values]
    return hashlib.sha1(json.dumps(norm, default=str).encode()).hexdigest()[:16]


@dataclass
class Tables:
    rows: dict[str, list[list]] = field(default_factory=dict)
    # Month ("2026-09") -> total of the Deals rows for it, in dollars.
    month_totals: dict[str, float] = field(default_factory=dict)


def build_tables(db: Session) -> Tables:
    """Every rep, quota and deal in the database, as rows for the data tabs (headers not included)."""
    reps = db.scalars(select(models.Rep).order_by(models.Rep.name)).all()
    periods = db.scalars(
        select(models.Period).order_by(models.Period.year, models.Period.month)
        .options(selectinload(models.Period.period_reps).selectinload(models.PeriodRep.rep))
    ).all()
    deals = db.scalars(
        select(models.Deal).options(
            selectinload(models.Deal.rep), selectinload(models.Deal.client), selectinload(models.Deal.flags),
            selectinload(models.Deal.created_by),
            selectinload(models.Deal.lines).selectinload(models.DealLine.item),
        )
    ).all()

    t = Tables()
    t.rows[REPS] = [[r.name, r.active, r.counts_toward_total] for r in reps]

    quotas = []
    order: dict[tuple[int, int], int] = {}  # (period_id, rep_id) -> position on that month's board
    for p in periods:
        for i, pr in enumerate(p.period_reps, start=1):
            quotas.append([month_text(p), pr.rep.name, pr.quota if pr.quota is not None else "", i])
            order[(p.id, pr.rep_id)] = i
    t.rows[QUOTAS] = quotas

    # Month by month, reps in board order, deals in the order they were entered (left to right on the sheet).
    period_of = {p.id: p for p in periods}
    deals = sorted(deals, key=lambda d: (period_of[d.period_id].year, period_of[d.period_id].month,
                                         order.get((d.period_id, d.rep_id), 999), d.id))
    totals: dict[str, float] = defaultdict(float)
    rows = []
    for n, d in enumerate(deals, start=1):
        month = month_text(period_of[d.period_id])
        totals[month] += d.total_cents / 100
        rows.append(deal_values(d, deal_id(n), month, d.created_by.name if d.created_by else "",
                                d.updated_at if d.created_by else None))
    t.rows[DEALS] = rows
    t.month_totals = {m: round(v, 2) for m, v in totals.items()}
    return t


# --- Setting the tabs up on the sheet ---


def _grid(sheet_id: int, col: int, end_col: int | None = None, start_row: int = 1) -> dict:
    return {"sheetId": sheet_id, "startRowIndex": start_row, "startColumnIndex": col,
            "endColumnIndex": (end_col if end_col is not None else col + 1)}


def _validation(sheet_id: int, col: int, condition: dict, message: str, strict: bool = True) -> dict:
    return {"setDataValidation": {
        "range": _grid(sheet_id, col),
        "rule": {"condition": condition, "inputMessage": message, "strict": strict, "showCustomUi": True},
    }}


def _formula(formula: str) -> dict:
    return {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]}


def _number_format(sheet_id: int, col: int, kind: str, pattern: str) -> dict:
    return {"repeatCell": {
        "range": _grid(sheet_id, col),
        "cell": {"userEnteredFormat": {"numberFormat": {"type": kind, "pattern": pattern}}},
        "fields": "userEnteredFormat.numberFormat",
    }}


def _protect(sheet_id: int, description: str, rng: dict) -> dict:
    # Editors: nobody listed, so only the sheet's owner and the account the app signs in with can change it.
    return {"addProtectedRange": {"protectedRange": {
        "range": rng, "description": description, "warningOnly": False, "editors": {"users": []},
    }}}


def format_requests(ids: dict[str, int]) -> list[dict]:
    """Header styling, validation, number formats and protection for the three data tabs."""
    col = {tab: {h: i for i, h in enumerate(HEADERS[tab])} for tab in HEADERS}
    deals, quotas, reps = ids[DEALS], ids[QUOTAS], ids[REPS]
    month_rule = lambda letter: _formula(f'=REGEXMATCH(TO_TEXT({letter}2),"{MONTH_RULE}")')  # noqa: E731
    rep_list = {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": f"={quote(REPS)}!$A$2:$A"}]}
    checkbox = {"type": "BOOLEAN"}
    reqs: list[dict] = []
    for tab, sid in ids.items():
        reqs.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True},
                                           "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85}}},
            "fields": "userEnteredFormat(textFormat,backgroundColor)",
        }})
        reqs.append(_protect(sid, f"{tab} headers: the app reads these columns by name",
                             {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1}))

    # Month as plain text, so Sheets doesn't turn a typed "2026-11" into a date.
    reqs += [_number_format(deals, col[DEALS]["Month"], "TEXT", "@"), _number_format(quotas, col[QUOTAS]["Month"], "TEXT", "@")]
    c = col[DEALS]
    reqs += [
        _validation(deals, c["Month"], month_rule("B"), "Month as YYYY-MM, e.g. 2026-11"),
        _validation(deals, c["Date"], {"type": "DATE_IS_VALID"}, "Optional: the deal's date"),
        _validation(deals, c["Rep"], rep_list, "Pick a rep (from the Reps tab)"),
        _validation(deals, c["New customer"], checkbox, "Tick for a new customer"),
        _validation(deals, c["Plus"], checkbox, "Tick for the + marker"),
        _validation(deals, c["Amount"], _formula("=ISNUMBER(J2)"), "The deal total, as a number"),
        _number_format(deals, c["Date"], "DATE", "yyyy-mm-dd"),
        _number_format(deals, c["Amount"], "CURRENCY", "$#,##0.00"),
        _number_format(deals, c["Updated"], "DATE_TIME", "yyyy-mm-dd hh:mm"),
        _protect(deals, "Deal IDs: filled in by the app; leave blank on new rows", _grid(deals, c["ID"])),
    ]
    c = col[QUOTAS]
    reqs += [
        _validation(quotas, c["Month"], month_rule("A"), "Month as YYYY-MM, e.g. 2026-11"),
        _validation(quotas, c["Rep"], rep_list, "Pick a rep (from the Reps tab)"),
        _validation(quotas, c["Quota"], _formula("=OR(ISBLANK(C2),ISNUMBER(C2))"), "A number, or blank for no quota"),
        _validation(quotas, c["Order"], {"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "0"}]},
                    "Position on that month's board (1 = top)"),
    ]
    c = col[REPS]
    reqs += [
        _validation(reps, c["Active"], checkbox, "Untick when the rep leaves"),
        _validation(reps, c["Counts toward total"], checkbox, "Untick for accounts left out of the team total"),
    ]
    return reqs


@dataclass
class SetupReport:
    title: str
    counts: dict[str, int]
    # Months where the old tab's MONTHLY TOTAL and the new Deals rows disagree: (month, old, new).
    differences: list[tuple[str, float | None, float]]
    # Problems found reading the tabs back after writing.
    readback_problems: list[str]


def existing_tabs(api: SheetsApi) -> tuple[str, dict[str, int]]:
    info = api.get({"fields": "properties.title,sheets.properties(title,sheetId)"})
    return info["properties"]["title"], {s["properties"]["title"]: s["properties"]["sheetId"] for s in info.get("sheets", [])}


def compare_totals(tables: Tables, old_totals: dict[str, float | None]) -> list[tuple[str, float | None, float]]:
    """Months whose total from the new rows differs from the old month tab's MONTHLY TOTAL by a cent or more."""
    out = []
    for month in sorted(set(tables.month_totals) | set(old_totals)):
        new, old = tables.month_totals.get(month, 0.0), old_totals.get(month)
        if old is None or abs(old - new) >= 0.01:
            out.append((month, old, new))
    return out


def write_tabs(api: SheetsApi, tables: Tables, replace: bool = False) -> dict[str, int]:
    """Create the three data tabs and fill them. Returns {tab: sheetId}.

    With replace, existing data tabs are deleted first (their rows, validation and protection go with them).
    """
    _, tabs = existing_tabs(api)
    there = [t for t in DATA_TABS if t in tabs]
    if there and not replace:
        raise SheetError(f"The sheet already has {', '.join(there)}; run with --replace to rebuild them")
    reqs: list[dict] = [{"deleteSheet": {"sheetId": tabs[t]}} for t in there]
    for tab in DATA_TABS:
        reqs.append({"addSheet": {"properties": {"title": tab, "gridProperties": {
            "rowCount": len(tables.rows[tab]) + 1 + SPARE_ROWS,
            "columnCount": len(HEADERS[tab]),
            "frozenRowCount": 1,
        }}}})
    replies = api.post(":batchUpdate", {"requests": reqs}).get("replies", [])
    ids = {r["addSheet"]["properties"]["title"]: r["addSheet"]["properties"]["sheetId"] for r in replies if "addSheet" in r}

    # RAW keeps text as typed: item text like "3/4" or a client starting with "+" isn't reinterpreted.
    api.post("/values:batchUpdate", {"valueInputOption": "RAW", "data": [
        {"range": f"{quote(tab)}!A1", "values": [list(HEADERS[tab]), *tables.rows[tab]]} for tab in DATA_TABS
    ]})
    api.post(":batchUpdate", {"requests": format_requests(ids) + [
        {"autoResizeDimensions": {"dimensions": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0,
                                                 "endIndex": len(HEADERS[tab])}}}
        for tab, sid in ids.items()
    ]})
    return ids


def is_record(row: list) -> bool:
    """A row with something in it. Spare rows aren't empty: their checkbox cells read as FALSE."""
    return any(c not in ("", None, False) for c in row)


def read_back(api: SheetsApi, tables: Tables) -> list[str]:
    """Read the tabs as Google stored them and check they match what was written."""
    data = api.get({"ranges": [f"{quote(t)}!A1:{chr(64 + len(HEADERS[t]))}" for t in DATA_TABS],
                    "valueRenderOption": "UNFORMATTED_VALUE"}, path="/values:batchGet")
    problems = []
    for tab, vr in zip(DATA_TABS, data.get("valueRanges", [])):
        values = vr.get("values", [])
        if not values or values[0] != list(HEADERS[tab]):
            problems.append(f"{tab}: header row isn't {list(HEADERS[tab])}")
        got = [r for r in values[1:] if is_record(r)]
        if len(got) != len(tables.rows[tab]):
            problems.append(f"{tab}: {len(got)} rows on the sheet, expected {len(tables.rows[tab])}")
        if tab == DEALS:
            amount, month = DEALS_HEADERS.index("Amount"), DEALS_HEADERS.index("Month")
            totals: dict[str, float] = defaultdict(float)
            for r in got:
                if len(r) > amount and isinstance(r[amount], (int, float)):
                    totals[str(r[month])] += r[amount]
            for m, want in tables.month_totals.items():
                if abs(totals.get(m, 0.0) - want) >= 0.01:
                    problems.append(f"{DEALS}: {m} adds up to {totals.get(m, 0.0):,.2f} on the sheet, expected {want:,.2f}")
    return problems


# --- Reading the tabs (the sync) ---


def read_values(api: SheetsApi) -> dict[str, list[list]]:
    """Every row of the data tabs, header first, as stored (numbers as numbers, checkboxes as booleans)."""
    data = api.get({"ranges": [f"{quote(t)}!A1:Z" for t in DATA_TABS], "valueRenderOption": "UNFORMATTED_VALUE"},
                   path="/values:batchGet")
    return {tab: vr.get("values", []) for tab, vr in zip(DATA_TABS, data.get("valueRanges", []))}


@dataclass
class NewId:
    row: int  # 1-based sheet row
    id: str
    values: list  # the row as read, to check it hasn't moved before writing the ID


@dataclass
class DataTabs:
    result: ParseResult
    rep_info: dict[str, RepInfo]
    new_ids: list[NewId]
    # Where the Deals tab's ID column is (0-based), for writing new IDs.
    id_column: int = 0


class Columns:
    """A tab's columns found by header name, so a moved column doesn't break the sync."""

    def __init__(self, tab: str, rows: list[list]):
        header = [text(h) for h in rows[0]] if rows else []
        missing = [h for h in HEADERS[tab] if h not in header]
        if missing:
            raise SheetError(f"The {tab} tab is missing the column{'s' if len(missing) > 1 else ''} "
                             f"{', '.join(missing)} in its header row")
        self.index = {h: header.index(h) for h in HEADERS[tab]}

    def __call__(self, row: list, name: str):
        i = self.index[name]
        return row[i] if i < len(row) else ""


def sheet_date(value) -> date | None:
    """A Sheets date serial number or an ISO date string, else None."""
    if isinstance(value, bool) or value in ("", None):
        return None
    if isinstance(value, (int, float)):
        return _SHEETS_EPOCH + timedelta(days=int(value))
    try:
        return date.fromisoformat(text(value))
    except ValueError:
        return None


def parse_month_cell(value) -> tuple[int, int] | None:
    """'2026-11' (or a date, if Sheets turned the text into one) → (2026, 11)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        d = sheet_date(value)
        return (d.year, d.month) if d else None
    m = re.fullmatch(MONTH_RULE, text(value))
    return (int(text(value)[:4]), int(text(value)[5:])) if m else None


def parse_data_tabs(values: dict[str, list[list]]) -> DataTabs:
    """Turn the Deals, Quotas and Reps rows into what the sync needs. Problem rows are listed in the warnings.

    Deals rows without an ID (or with a copy of another row's ID) get the next free ID; new_ids says which.
    """
    warnings: list[str] = []

    col = Columns(REPS, values.get(REPS, []))
    rep_info: dict[str, RepInfo] = {}
    for n, row in enumerate(values.get(REPS, [])[1:], start=2):
        name = text(col(row, "Rep")).upper()
        if not name:
            continue
        if name in rep_info:
            warnings.append(f"Reps row {n}: {name} is listed twice; the first row is used")
            continue
        rep_info[name] = RepInfo(active=col(row, "Active") is True, counts_toward_total=col(row, "Counts toward total") is True)

    def known_rep(where: str, value) -> str | None:
        name = text(value).upper()
        if not name:
            warnings.append(f"{where}: no rep; skipped")
            return None
        if name not in rep_info:
            warnings.append(f"{where}: {name} isn't on the Reps tab; added as a new rep")
            rep_info[name] = RepInfo(active=True, counts_toward_total=True)
        return name

    # (year, month) -> rep -> (order, quota), in the Quotas tab's order.
    col = Columns(QUOTAS, values.get(QUOTAS, []))
    slots: dict[tuple[int, int], dict[str, tuple[float, float | None]]] = defaultdict(dict)
    for n, row in enumerate(values.get(QUOTAS, [])[1:], start=2):
        if not is_record(row):
            continue
        where = f"Quotas row {n}"
        ym = parse_month_cell(col(row, "Month"))
        if ym is None:
            warnings.append(f"{where}: month {col(row, 'Month')!r} isn't like 2026-11; skipped")
            continue
        rep = known_rep(where, col(row, "Rep"))
        if rep is None:
            continue
        if rep in slots[ym]:
            warnings.append(f"{where}: {rep} already has a quota for {ym[0]}-{ym[1]:02d}; skipped")
            continue
        quota_raw = col(row, "Quota")
        quota = to_number(quota_raw)
        if quota is None and text(quota_raw) not in ("", "~"):
            warnings.append(f"{where}: quota {quota_raw!r} isn't a number; left blank")
        order = to_number(col(row, "Order"))
        slots[ym][rep] = (order if order is not None else float("inf"), quota)

    col = Columns(DEALS, values.get(DEALS, []))
    deal_rows = [(n, row) for n, row in enumerate(values.get(DEALS, [])[1:], start=2) if is_record(row)]
    taken = {int(m[1]) for _, row in deal_rows if (m := ID_PATTERN.match(text(col(row, "ID"))))}
    next_id = max(taken, default=0) + 1
    seen: set[str] = set()
    new_ids: list[NewId] = []
    by_month: dict[tuple[int, int], dict[str, list[SheetDeal]]] = defaultdict(lambda: defaultdict(list))
    for n, row in deal_rows:
        where = f"Deals row {n}"
        ym = parse_month_cell(col(row, "Month"))
        if ym is None:
            warnings.append(f"{where}: month {col(row, 'Month')!r} isn't like 2026-11; skipped")
            continue
        rep = known_rep(where, col(row, "Rep"))
        if rep is None:
            continue
        client, new_mark, plus_mark = split_client(col(row, "Client"))
        amount = to_number(col(row, "Amount"))
        if amount is None:
            if text(col(row, "Amount")):
                warnings.append(f"{where}: amount {col(row, 'Amount')!r} isn't a number; counted as $0")
            elif client:
                warnings.append(f"{where}: {client!r} has no amount; counted as $0")
            amount = 0.0
        if not client:
            if not amount:
                warnings.append(f"{where}: no client or amount; skipped")
                continue
            warnings.append(f"{where}: amount with no client; shown as '(no client)'")
            client = "(no client)"
        raw_date = col(row, "Date")
        deal_date = sheet_date(raw_date)
        if raw_date not in ("", None) and deal_date is None:
            warnings.append(f"{where}: date {raw_date!r} isn't a date; left blank")
        elif deal_date and (deal_date.year, deal_date.month) != ym:
            warnings.append(f"{where}: date {deal_date} isn't in {ym[0]}-{ym[1]:02d}; kept anyway")

        deal_id_text = text(col(row, "ID"))
        if not ID_PATTERN.match(deal_id_text) or deal_id_text in seen:
            if deal_id_text:
                warnings.append(f"{where}: ID {deal_id_text} is {'used twice' if deal_id_text in seen else 'not like D00001'}; "
                                "given a new one")
            deal_id_text = deal_id(next_id)
            next_id += 1
            new_ids.append(NewId(row=n, id=deal_id_text, values=row))
        seen.add(deal_id_text)
        version = row_version([deal_id_text if h == "ID" else col(row, h) for h in DEALS_HEADERS])

        by_month[ym][rep].append(SheetDeal(
            client=client,
            items=split_items(col(row, "Items")),
            amount=amount,
            new_customer=col(row, "New customer") is True or new_mark,
            plus=col(row, "Plus") is True or plus_mark,
            where=deal_id_text,
            deal_date=deal_date,
            location=text(col(row, "Location")) or None,
            notes=text(col(row, "Notes")) or None,
            entered_by=text(col(row, "Entered by")) or None,
            version=version,
        ))

    months = []
    for ym in sorted(set(slots) | set(by_month)):
        ordered = sorted(slots[ym].items(), key=lambda kv: kv[1][0])
        reps = [SheetRep(name=rep, quota=quota, sheet_sales=None, deals=by_month[ym].pop(rep, []))
                for rep, (_, quota) in ordered]
        # Reps with deals that month but no Quotas row go at the bottom, without a quota.
        reps += [SheetRep(name=rep, quota=None, sheet_sales=None, deals=ds) for rep, ds in by_month[ym].items()]
        months.append(SheetMonth(tab=f"{ym[0]}-{ym[1]:02d}", year=ym[0], month=ym[1], reps=reps, sheet_total=None))
    return DataTabs(result=ParseResult(months=months, warnings=warnings), rep_info=rep_info, new_ids=new_ids,
                    id_column=col.index["ID"])


def fill_ids(api: SheetsApi, new_ids: list[NewId], id_column: int = 0) -> list[str]:
    """Write new IDs into the Deals rows that lacked one. Returns warnings.

    Each row is read again first and only written if it still holds what the sync read, so an ID can't
    land on the wrong row when someone inserts or sorts rows in the meantime (it's retried next sync).
    """
    if not new_ids:
        return []
    width = max(len(x.values) for x in new_ids) if new_ids else len(DEALS_HEADERS)
    width = max(width, len(DEALS_HEADERS))
    last = chr(64 + width)
    now = api.get({"ranges": [f"{quote(DEALS)}!A{x.row}:{last}{x.row}" for x in new_ids],
                   "valueRenderOption": "UNFORMATTED_VALUE"}, path="/values:batchGet")
    pad = lambda r: (list(r) + [""] * width)[:width]  # noqa: E731
    ready, warnings = [], []
    for x, vr in zip(new_ids, now.get("valueRanges", [])):
        current = (vr.get("values") or [[]])[0]
        if pad(current) == pad(x.values):
            ready.append(x)
        else:
            warnings.append(f"Deals row {x.row} changed while syncing; its ID is filled in next sync")
    if ready:
        id_col = chr(65 + id_column)
        api.post("/values:batchUpdate", {"valueInputOption": "RAW", "data": [
            {"range": f"{quote(DEALS)}!{id_col}{x.row}", "values": [[x.id]]} for x in ready
        ]})
    return warnings
