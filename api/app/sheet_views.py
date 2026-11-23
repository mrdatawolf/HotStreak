"""The sheet's view tabs, built by formula from the data tabs (Deals, Quotas, Reps):

- Board: one month in the old month-tab layout. A month picker (B1, blank = the current month) replaces the
  tab-per-month copies of "Monthly Template". Each rep gets a 3-row block (clients, items, amounts across 12
  columns), then QUOTA and SALES; a MONTHLY TOTAL row closes it.
- Overview: every month's sales by year, growing by itself as months are added.

Both are pure formulas, so they're rebuilt freely (setup_sheet_tabs --views) and locked against edits,
except the Board's month picker. Note the picker is shared: choosing a month changes it for everyone.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .board import build_board
from .google_sheet import SheetError, SheetsApi, quote
from .sheet_import import col_letter
from .sheet_tabs import DEALS, DEALS_HEADERS, QUOTAS, QUOTAS_HEADERS, REPS, REPS_HEADERS, Tables

BOARD = "Board"
OVERVIEW = "Overview"
VIEW_TABS = (BOARD, OVERVIEW)
# Marks our view tabs (in their protection's description), so a rebuild knows what it may replace.
MARKER = "HotStreak view"

SLOTS = 15  # rep blocks on the Board; the most reps any month has had is 9
DEAL_COLUMNS = 12  # B..M, as on the month tabs
TOTAL_ROW = 2 + 3 * SLOTS  # 1-based
LEGEND_ROW = TOTAL_ROW + 1
# Hidden helper columns: Q = the month shown, R = every month (the picker's list), S = that month's reps in order.
HELPER_MONTH, HELPER_MONTHS, HELPER_REPS = "Q", "R", "S"
BOARD_COLUMNS = 19  # A..S

NEW_COLOR = {"red": 0xB6 / 255, "green": 0xD7 / 255, "blue": 0xA8 / 255}  # the sheet's "*" green
PLUS_COLOR = {"red": 0xF9 / 255, "green": 0xCB / 255, "blue": 0x9C / 255}  # orange


def _col(tab: str, headers: tuple, name: str) -> str:
    """'Deals!$J$2:$J' for a data tab column, by header name."""
    letter = col_letter(headers.index(name))
    return f"{quote(tab)}!${letter}$2:${letter}"


D = {h: _col(DEALS, DEALS_HEADERS, h) for h in DEALS_HEADERS}
Q = {h: _col(QUOTAS, QUOTAS_HEADERS, h) for h in QUOTAS_HEADERS}
R = {h: _col(REPS, REPS_HEADERS, h) for h in REPS_HEADERS}
MONTH = f"${HELPER_MONTH}$2"
COUNTED_REPS = f'FILTER({R["Rep"]},{R["Counts toward total"]}=TRUE)'
# 1 for each Deals row whose rep counts toward the team total. (SUMIFS with a list of reps doesn't expand
# inside SUMPRODUCT in Google Sheets, so totals multiply these out instead.)
COUNTED_ROWS = f'ISNUMBER(MATCH({D["Rep"]},{COUNTED_REPS},0))'


def slot_row(k: int) -> int:
    """First (client) row of rep block k (0-based), 1-based like the sheet."""
    return 2 + 3 * k


def board_formulas() -> list[list[str]]:
    """The Board's cells, A1:S{LEGEND_ROW}, as typed (formulas start with '=')."""
    rows = [[""] * BOARD_COLUMNS for _ in range(LEGEND_ROW)]
    put = lambda r, c, v: rows[r - 1].__setitem__(c, v)  # noqa: E731  (1-based row, 0-based column)

    total = f"$O${TOTAL_ROW}"
    put(1, 0, "MONTH")
    put(1, 2, f'=IF({MONTH}="","No months yet",UPPER(TEXT(DATE(VALUE(LEFT({MONTH},4)),VALUE(RIGHT({MONTH},2)),1),'
              f'"mmmm yyyy"))&IF($B$1="","  (current month)","")&"   ·   Monthly total "&TEXT({total},"$#,##0.00"))')
    put(1, 13, "QUOTA")
    put(1, 14, "SALES")

    # Helpers: the month shown (the picker, else the newest month that isn't in the future), the picker's list,
    # and that month's reps in Quotas order, then any rep with deals but no Quotas row.
    months = f'VSTACK({Q["Month"]},{D["Month"]})'
    put(1, 16, "Month shown")
    put(2, 16, f'=IF($B$1<>"",TO_TEXT($B$1),IFERROR(INDEX(SORT(UNIQUE(FILTER({months},{months}<>"",'
               f'{months}<=TEXT(TODAY(),"yyyy-mm"))),1,FALSE),1),""))')
    put(1, 17, "Months")
    put(2, 17, f'=SORT(UNIQUE(FILTER({months},{months}<>"")),1,FALSE)')
    put(1, 18, "Reps shown")
    put(2, 18, f'=LET(m,{MONTH},'
               f'qr,IFERROR(SORT(FILTER({Q["Rep"]},{Q["Month"]}=m),FILTER({Q["Order"]},{Q["Month"]}=m),TRUE),""),'
               f'd,IFERROR(UNIQUE(FILTER({D["Rep"]},{D["Month"]}=m)),""),'
               f'extra,IFERROR(FILTER(d,ISNA(MATCH(d,qr,0))),""),'
               f'all,VSTACK(qr,extra),IFERROR(FILTER(all,all<>""),""))')

    in_block = lambda rep: f'{D["Month"]}={MONTH},{D["Rep"]}={rep}'  # noqa: E731
    clients = (f'{D["Client"]}&IF({D["New customer"]}=TRUE,"*","")&IF({D["Plus"]}=TRUE,"+","")')
    for k in range(SLOTS):
        r = slot_row(k)
        rep = f"$A{r}"
        put(r, 0, f'=IFERROR(INDEX(${HELPER_REPS}$2:${HELPER_REPS},{k + 1}),"")')
        put(r + 1, 0, f'=IF({rep}="","",LET(n,COUNTIFS({D["Month"]},{MONTH},{D["Rep"]},{rep}),'
                      f'IF(n>{DEAL_COLUMNS},"+"&(n-{DEAL_COLUMNS})&" more","")))')
        for offset, values in ((0, clients), (1, D["Items"]), (2, D["Amount"])):
            put(r + offset, 1, f'=IF({rep}="","",IFERROR(ARRAY_CONSTRAIN(TRANSPOSE(FILTER({values},{in_block(rep)})),'
                               f'1,{DEAL_COLUMNS}),""))')
        put(r, 13, f'=IF({rep}="","",LET(q,IFERROR(INDEX(FILTER({Q["Quota"]},{Q["Month"]}={MONTH},'
                   f'{Q["Rep"]}={rep}),1),""),IF(q="","~",q)))')
        put(r, 14, f'=IF({rep}="","",SUMIFS({D["Amount"]},{D["Month"]},{MONTH},{D["Rep"]},{rep}))')

    put(TOTAL_ROW, 0, "MONTHLY TOTAL")
    put(TOTAL_ROW, 14, f'=SUMPRODUCT(({D["Month"]}={MONTH})*{COUNTED_ROWS},{D["Amount"]})')
    put(LEGEND_ROW, 0, "Clients with * are new customers (green); + is the + marker (orange). Pick a month in B1, "
                       "or clear it to follow the current month. Deals are entered on the Deals tab or in the app.")
    return rows


def overview_formulas() -> list[list[str]]:
    """The Overview's header row and the one formula that fills Year · Month · Sales · Year total below it."""
    months = f'VSTACK({Q["Month"]},{D["Month"]})'
    formula = (
        # ARRAYFORMULA so IF/TEXT/DATE below work on the whole column of months, not just the first.
        f'=ARRAYFORMULA(LET(ms,UNIQUE(FILTER({months},{months}<>"")),'
        # (Names like y1 would read as cell addresses, hence first_year/last_year.)
        f'first_year,VALUE(LEFT(INDEX(SORT(ms),1),4)),last_year,VALUE(LEFT(INDEX(SORT(ms,1,FALSE),1),4)),'
        f's,SEQUENCE((last_year-first_year+1)*12,1,0),yr,first_year+INT(s/12),mo,MOD(s,12)+1,'
        f'counted,{COUNTED_ROWS},'
        f'sales,MAP(yr,mo,LAMBDA(y,m,LET(k,y&"-"&TEXT(m,"00"),IF(SUM(--(ms=k))=0,"",'
        f'SUMPRODUCT(({D["Month"]}=k)*counted,{D["Amount"]}))))),'
        f'yeartotal,MAP(yr,mo,LAMBDA(y,m,IF(m=1,SUMPRODUCT((LEFT({D["Month"]},4)=TEXT(y,"0"))*counted,{D["Amount"]}),""))),'
        f'HSTACK(IF(mo=1,yr,""),UPPER(TEXT(DATE(yr,mo,1),"mmm")),sales,yeartotal)))'
    )
    return [["Year", "Month", "Sales", "Year total"], [formula, "", "", ""]]


# --- Formatting ---


def _range(sid: int, r0: int, r1: int, c0: int, c1: int) -> dict:
    """0-based, end-exclusive."""
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": c0, "endColumnIndex": c1}


def _fmt(rng: dict, fmt: dict, fields: str) -> dict:
    return {"repeatCell": {"range": rng, "cell": {"userEnteredFormat": fmt}, "fields": f"userEnteredFormat({fields})"}}


def _width(sid: int, c0: int, c1: int, px: int) -> dict:
    return {"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c0, "endIndex": c1},
        "properties": {"pixelSize": px}, "fields": "pixelSize"}}


def _protect_all(sid: int, unprotected: list[dict] | None = None) -> dict:
    return {"addProtectedRange": {"protectedRange": {
        "range": {"sheetId": sid}, "unprotectedRanges": unprotected or [], "warningOnly": False,
        "editors": {"users": []},
        "description": f"{MARKER}: built from the Deals, Quotas and Reps tabs; edit those instead",
    }}}


def board_format(sid: int, months_list: str) -> list[dict]:
    money = {"numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}}
    last = LEGEND_ROW
    reqs = [
        {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {
            "frozenRowCount": 1, "frozenColumnCount": 1}}, "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 16, "endIndex": 19},
                                       "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}},
        _width(sid, 0, 1, 120), _width(sid, 1, 13, 135), _width(sid, 13, 14, 70), _width(sid, 14, 15, 110),
        _fmt(_range(sid, 0, 1, 0, 15), {"textFormat": {"bold": True}, "backgroundColor": {"red": .85, "green": .85, "blue": .85}},
             "textFormat,backgroundColor"),
        _fmt(_range(sid, 0, 1, 1, 2), {"backgroundColor": {"red": 1, "green": 0.95, "blue": 0.6}}, "backgroundColor"),
        {"mergeCells": {"range": _range(sid, 0, 1, 2, 13), "mergeType": "MERGE_ALL"}},
        _fmt(_range(sid, 1, last, 1, 13), {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}, "wrapStrategy,verticalAlignment"),
        _fmt(_range(sid, TOTAL_ROW - 1, TOTAL_ROW, 0, 15), {"textFormat": {"bold": True}}, "textFormat"),
        _fmt(_range(sid, TOTAL_ROW - 1, TOTAL_ROW, 14, 15), money, "numberFormat"),
        _fmt(_range(sid, LEGEND_ROW - 1, LEGEND_ROW, 0, 1), {"textFormat": {"italic": True}}, "textFormat"),
        {"setDataValidation": {"range": _range(sid, 0, 1, 1, 2), "rule": {
            "condition": {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": months_list}]},
            "inputMessage": "Pick a month to show. Clear it to follow the current month. (Everyone sees the same choice.)",
            "strict": True, "showCustomUi": True}}},
        _fmt(_range(sid, 0, 1, 1, 2), {"numberFormat": {"type": "TEXT", "pattern": "@"}}, "numberFormat"),
    ]
    client_rows = []
    for k in range(SLOTS):
        r0 = slot_row(k) - 1  # 0-based client row
        reqs += [
            _fmt(_range(sid, r0, r0 + 1, 0, 1), {"textFormat": {"bold": True}}, "textFormat"),
            _fmt(_range(sid, r0 + 1, r0 + 2, 0, 1), {"textFormat": {"italic": True, "fontSize": 9}}, "textFormat"),
            _fmt(_range(sid, r0 + 1, r0 + 2, 1, 13), {"textFormat": {"fontSize": 9}}, "textFormat"),
            _fmt(_range(sid, r0 + 2, r0 + 3, 1, 13), money, "numberFormat"),
            _fmt(_range(sid, r0, r0 + 1, 14, 15), {**money, "textFormat": {"bold": True}}, "numberFormat,textFormat"),
            _fmt(_range(sid, r0, r0 + 1, 13, 14), {"horizontalAlignment": "CENTER"}, "horizontalAlignment"),
            {"updateBorders": {"range": _range(sid, r0 + 2, r0 + 3, 0, 15),
                               "bottom": {"style": "SOLID", "color": {"red": .6, "green": .6, "blue": .6}}}},
        ]
        client_rows.append(_range(sid, r0, r0 + 1, 1, 13))
    # Plus first, so a client marked both ("Acme*+") shows orange.
    for i, (pattern, color) in enumerate(((r"\+$", PLUS_COLOR), (r"\*$", NEW_COLOR))):
        reqs.append({"addConditionalFormatRule": {"index": i, "rule": {
            "ranges": client_rows,
            "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [
                {"userEnteredValue": f'=REGEXMATCH(TO_TEXT(B{slot_row(0)}),"{pattern}")'}]},
                "format": {"backgroundColor": color}}}}})
    reqs.append(_protect_all(sid, [_range(sid, 0, 1, 1, 2)]))
    return reqs


def overview_format(sid: int) -> list[dict]:
    money = {"numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}}
    return [
        {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
                                   "fields": "gridProperties.frozenRowCount"}},
        _fmt(_range(sid, 0, 1, 0, 4), {"textFormat": {"bold": True}, "backgroundColor": {"red": .85, "green": .85, "blue": .85}},
             "textFormat,backgroundColor"),
        _fmt({"sheetId": sid, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 1}, {"textFormat": {"bold": True}},
             "textFormat"),
        _fmt({"sheetId": sid, "startRowIndex": 1, "startColumnIndex": 2, "endColumnIndex": 4}, money, "numberFormat"),
        _width(sid, 0, 2, 80), _width(sid, 2, 4, 130),
        _protect_all(sid),
    ]


# --- Building them on the sheet ---


def _tabs_with_protection(api: SheetsApi) -> dict[str, tuple[int, list[str]]]:
    info = api.get({"fields": "sheets(properties(title,sheetId),protectedRanges(description))"})
    return {s["properties"]["title"]: (s["properties"]["sheetId"], [p.get("description", "") for p in s.get("protectedRanges", [])])
            for s in info.get("sheets", [])}


def write_views(api: SheetsApi) -> list[str]:
    """Create (or rebuild) the Board and Overview tabs. Returns notes on what was done.

    A tab with one of those names that we didn't build (like the old hand-linked Overview) is renamed
    "<name> (old)" and kept.
    """
    tabs = _tabs_with_protection(api)
    notes, reqs = [], []
    for name in VIEW_TABS:
        if name not in tabs:
            continue
        sid, descriptions = tabs[name]
        if any(d.startswith(MARKER) for d in descriptions):
            reqs.append({"deleteSheet": {"sheetId": sid}})
            notes.append(f"Rebuilt {name}")
        else:
            old, n = f"{name} (old)", 2
            while old in tabs:
                old, n = f"{name} (old {n})", n + 1
            reqs.append({"updateSheetProperties": {"properties": {"sheetId": sid, "title": old}, "fields": "title"}})
            notes.append(f"Renamed the existing {name} tab to \"{old}\" (kept as it was)")
    for index, name in enumerate(VIEW_TABS):
        # The Board's hidden month list (column R) grows a row a month; 600 rows lasts about 45 years.
        rows = 600 if name == BOARD else 1000
        cols = BOARD_COLUMNS if name == BOARD else 4
        reqs.append({"addSheet": {"properties": {"title": name, "index": index,
                                                 "gridProperties": {"rowCount": rows, "columnCount": cols}}}})
    replies = api.post(":batchUpdate", {"requests": reqs}).get("replies", [])
    ids = {r["addSheet"]["properties"]["title"]: r["addSheet"]["properties"]["sheetId"] for r in replies if "addSheet" in r}

    api.post("/values:batchUpdate", {"valueInputOption": "USER_ENTERED", "data": [
        {"range": f"{quote(BOARD)}!A1", "values": board_formulas()},
        {"range": f"{quote(OVERVIEW)}!A1", "values": overview_formulas()},
    ]})
    api.post(":batchUpdate", {"requests": board_format(ids[BOARD], f"={quote(BOARD)}!${HELPER_MONTHS}$2:${HELPER_MONTHS}")
                              + overview_format(ids[OVERVIEW])})
    return notes + [f"Added {', '.join(VIEW_TABS)}"]


# --- Checking them against the app ---


@dataclass
class BoardShown:
    title: str
    reps: list[tuple[str, float | None, int]]  # (rep, sales, clients shown)
    total: float | None
    errors: list[str]


def read_board(api: SheetsApi) -> BoardShown:
    data = api.get({"ranges": [f"{quote(BOARD)}!A1:O{LEGEND_ROW}"], "valueRenderOption": "UNFORMATTED_VALUE"},
                   path="/values:batchGet")
    grid = data["valueRanges"][0].get("values", [])
    cell = lambda r, c: grid[r - 1][c] if r - 1 < len(grid) and c < len(grid[r - 1]) else ""  # noqa: E731
    errors = [f"{col_letter(c)}{r}: {grid[r - 1][c]}" for r in range(1, len(grid) + 1) for c in range(len(grid[r - 1]))
              if isinstance(grid[r - 1][c], str) and grid[r - 1][c].startswith("#")]
    reps = []
    for k in range(SLOTS):
        r = slot_row(k)
        if cell(r, 0):
            shown = sum(1 for c in range(1, 13) if cell(r, c) not in ("", None))
            sales = cell(r, 14)
            reps.append((str(cell(r, 0)), sales if isinstance(sales, (int, float)) else None, shown))
    total = cell(TOTAL_ROW, 14)
    return BoardShown(title=str(cell(1, 2)), reps=reps, total=total if isinstance(total, (int, float)) else None, errors=errors)


def set_month(api: SheetsApi, month: str) -> None:
    api.post("/values:batchUpdate", {"valueInputOption": "RAW", "data": [{"range": f"{quote(BOARD)}!B1", "values": [[month]]}]})


def check_board(api: SheetsApi, db: Session, months: list[models.Period]) -> list[str]:
    """Show each month on the Board and compare it with the app's board. Leaves the picker blank."""
    problems = []
    try:
        for p in months:
            label = f"{p.year}-{p.month:02d}"
            set_month(api, label)
            shown = read_board(api)
            want = build_board(db, p)
            problems += [f"Board {label}: formula error at {e}" for e in shown.errors]
            want_reps = [(r.name, r.sales_cents / 100, min(len(r.deals), DEAL_COLUMNS)) for r in want.reps]
            if [r[0] for r in shown.reps] != [r[0] for r in want_reps]:
                problems.append(f"Board {label}: reps {[r[0] for r in shown.reps]}, app has {[r[0] for r in want_reps]}")
                continue
            for (name, sales, n), (_, want_sales, want_n) in zip(shown.reps, want_reps):
                if sales is None or abs(sales - want_sales) >= 0.01:
                    problems.append(f"Board {label}: {name} sales {sales}, app has {want_sales:,.2f}")
                if n != want_n:
                    problems.append(f"Board {label}: {name} shows {n} clients, expected {want_n}")
            if shown.total is None or abs(shown.total - want.total_sales_cents / 100) >= 0.01:
                problems.append(f"Board {label}: total {shown.total}, app has {want.total_sales_cents / 100:,.2f}")
    finally:
        set_month(api, "")
    return problems


def check_overview(api: SheetsApi, tables: Tables) -> list[str]:
    data = api.get({"ranges": [f"{quote(OVERVIEW)}!A2:D"], "valueRenderOption": "UNFORMATTED_VALUE"}, path="/values:batchGet")
    rows = data["valueRanges"][0].get("values", [])
    names = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    shown, year, problems = {}, None, []
    for row in rows:
        row = list(row) + [""] * 4
        if isinstance(row[0], str) and row[0].startswith("#"):
            return [f"Overview: formula error {row[0]}"]
        if row[0] not in ("", None):
            year = int(row[0])
        if year is None or row[1] not in names:
            continue
        if isinstance(row[2], (int, float)):
            shown[f"{year}-{names.index(row[1]) + 1:02d}"] = row[2]
    for month in sorted(set(tables.month_totals) | set(shown)):
        want, got = tables.month_totals.get(month, 0.0), shown.get(month)
        if got is None or abs(got - want) >= 0.01:
            problems.append(f"Overview {month}: shows {got}, app has {want:,.2f}")
    return problems


def months_to_check(db: Session) -> list[models.Period]:
    """A spread of months: the first, the last three, and the busiest."""
    periods = db.scalars(select(models.Period).order_by(models.Period.year, models.Period.month)).all()
    if not periods:
        raise SheetError("No months in the app to check against")
    busiest = max(periods, key=lambda p: len(p.period_reps))
    picked = [periods[0], busiest, *periods[-3:]]
    return list({p.id: p for p in picked}.values())
