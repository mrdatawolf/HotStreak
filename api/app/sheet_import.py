"""Read the client's monthly sales sheet (one tab per month) and sync it into the database.

Each month tab looks like:
    row 1:  marker legend | MONTH NAME ...           | QUOTA | SALES
    then a 3-row block per rep: client names / items / deal totals, one deal per column,
    with the rep's name in column A and quota + sales total on the right,
    ending at a "MONTHLY TOTAL" row.

Tabs are named MMYY or MYY ("0124", "926"); other tabs (Overview, Monthly Template,
Billboard Mirror) are skipped. The QUOTA/SALES columns aren't always N/O, so they're
found from the header row.

Markers on a client: a trailing "*" (or, on older tabs, a blue fill) means a new customer and
becomes a flag on the deal; a trailing "+" (the sheet's orange highlight) is a notation recorded in
deals.sheet_plus. Markers are stripped from the client name. (Yellow fills on some 2023 tabs were an
old rule; ignored.)

The parser works on a plain grid of (value, fill) cells: read_workbook() builds one from an .xlsx
export, google_sheet.read_spreadsheet() from the live sheet.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import models
from .item_parse import Catalog
from .names import name_key

TAB_NAME = re.compile(r"^(\d{1,2})(\d{2})$")

# Fill colors (RGB hex, no alpha) the sheet has used to mark a new customer:
# blues on older tabs, and the "*" rule's green when painted on by hand.
NEW_CUSTOMER_FILLS = {"A4C2F4", "9FC5E8", "86C3DC", "C9DAF8", "B6D7A8"}
# Grays used for plain amount cells and headers, and yellow (an old rule no longer used); not markers.
PLAIN_FILLS = {"FFFFFF", "D9D9D9", "B7B7B7", "999999", "FFFF00"}

# (name, color) of the new-customer flag; created by the first sync.
FLAG_NEW = ("New customer", "#b6d7a8")


@dataclass
class Cell:
    value: object = None
    fill: str | None = None


Grid = list[list[Cell]]


@dataclass
class SheetDeal:
    client: str
    items: list[tuple[int, str]]
    amount: float
    new_customer: bool
    plus: bool
    where: str


@dataclass
class SheetRep:
    name: str
    quota: float | None
    sheet_sales: float | None
    deals: list[SheetDeal] = field(default_factory=list)


@dataclass
class SheetMonth:
    tab: str
    year: int
    month: int
    reps: list[SheetRep]
    sheet_total: float | None


@dataclass
class ParseResult:
    months: list[SheetMonth]
    warnings: list[str]


def col_letter(index: int) -> str:
    """0-based column index → A, B, ..., AA."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip() if value is not None else ""


def to_number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = text(value).replace("$", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_tab_name(name: str) -> tuple[int, int] | None:
    match = TAB_NAME.match(name.strip())
    if not match:
        return None
    month, year = int(match[1]), 2000 + int(match[2])
    return (year, month) if 1 <= month <= 12 else None


ITEM_SPLIT = re.compile(r"\s*\n\s*|\s{2,}|\s+&\s+|(?<=\S)\s+(?=\(\d+\)\s*\S)")
QTY_PREFIX = re.compile(r"^\((\d+)\)\s*(.+)$")
QTY_SUFFIX = re.compile(r"^(.+?)\s*\((\d+)\)$")


def split_items(raw: object) -> list[tuple[int, str]]:
    """'(2) BP-71M45  XM3250' → [(2, 'BP-71M45'), (1, 'XM3250')].

    Pieces are separated by newlines, 2+ spaces, ' & ', or a new '(n)' count.
    Only parenthesized counts are read as quantities ('48 Mo. Rental' stays as text).
    """
    if raw is None:
        return []
    out = []
    pending = ""  # a lone "(n)" spaced away from its item
    for piece in ITEM_SPLIT.split(str(raw).strip()):
        piece = f"{pending} {piece}".strip() if pending else piece.strip()
        pending = ""
        if not piece:
            continue
        if re.fullmatch(r"\(\d+\)", piece):
            pending = piece
            continue
        qty = 1
        if m := QTY_PREFIX.match(piece):
            qty, piece = int(m[1]), m[2]
        elif m := QTY_SUFFIX.match(piece):
            piece, qty = m[1], int(m[2])
        out.append((max(qty, 1), text(piece)))
    return out


def split_client(raw: object) -> tuple[str, bool, bool]:
    """'Aquaterra*' → ('Aquaterra', new=True, plus=False)."""
    name = text(raw)
    new = plus = False
    while name and name[-1] in "*+":
        new |= name[-1] == "*"
        plus |= name[-1] == "+"
        name = name[:-1].rstrip()
    return name, new, plus


def parse_month(tab: str, year: int, month: int, grid: Grid, warnings: list[str]) -> SheetMonth | None:
    def cell(r: int, c: int) -> Cell:
        return grid[r][c] if r < len(grid) and c < len(grid[r]) else Cell()

    header = [text(c.value).upper() for c in grid[0]] if grid else []
    if "QUOTA" not in header:
        warnings.append(f"{tab}: no QUOTA header in row 1; skipped")
        return None
    quota_col = header.index("QUOTA")
    sales_col = quota_col + 1

    reps: list[SheetRep] = []
    sheet_total = None
    r = 1
    while r < len(grid):
        label = text(cell(r, 0).value)
        if label.upper() == "MONTHLY TOTAL":
            sheet_total = next(
                (n for c in range(1, sales_col + 1) if (n := to_number(cell(r, c).value)) is not None), None
            )
            break
        if not label:
            # Blank row between blocks or a missing rep name; a block with deals but no name is reported.
            if any(cell(r + 2, c).value is not None for c in range(1, quota_col)):
                warnings.append(f"{tab}: row {r + 1} has deals but no rep name; skipped")
            r += 1
            continue

        quota_raw = cell(r, quota_col).value
        quota = to_number(quota_raw)
        if quota is None and text(quota_raw) not in ("", "~"):
            warnings.append(f"{tab}: {label} quota {quota_raw!r} isn't a number; left blank")
        rep = SheetRep(name=label.upper(), quota=quota, sheet_sales=to_number(cell(r, sales_col).value))

        for c in range(1, quota_col):
            client_cell, items_cell, amount_cell = cell(r, c), cell(r + 1, c), cell(r + 2, c)
            if client_cell.value is None and items_cell.value is None and amount_cell.value is None:
                continue
            where = f"{tab}!{col_letter(c)}{r + 1}"
            client, new, plus = split_client(client_cell.value)
            amount = to_number(amount_cell.value)
            if amount is None:
                if amount_cell.value is not None:
                    warnings.append(f"{where}: amount {amount_cell.value!r} isn't a number; imported as $0")
                elif client:
                    warnings.append(f"{where}: {client!r} has no amount; imported as $0")
                amount = 0.0
            if not client:
                if not amount:
                    continue
                warnings.append(f"{where}: amount with no client; imported as '(no client)'")
                client = "(no client)"
            fills = {x.fill for x in (client_cell, items_cell, amount_cell) if x.fill}
            for unknown in fills - NEW_CUSTOMER_FILLS - PLAIN_FILLS:
                warnings.append(f"{where}: unrecognized fill #{unknown} ignored")
            rep.deals.append(
                SheetDeal(
                    client=client,
                    items=split_items(items_cell.value),
                    amount=amount,
                    new_customer=new or bool(fills & NEW_CUSTOMER_FILLS),
                    plus=plus,
                    where=where,
                )
            )

        if rep.name == "EMPTY" and not rep.deals:
            pass  # an unfilled slot on the sheet
        else:
            reps.append(rep)
        r += 3
    else:
        warnings.append(f"{tab}: no MONTHLY TOTAL row found")

    return SheetMonth(tab=tab, year=year, month=month, reps=reps, sheet_total=sheet_total)


def parse_tabs(tabs: dict[str, Grid]) -> ParseResult:
    warnings: list[str] = []
    by_month: dict[tuple[int, int], SheetMonth] = {}
    for tab, grid in tabs.items():
        ym = parse_tab_name(tab)
        if ym is None:
            continue
        if ym in by_month:
            warnings.append(f"{tab}: same month as tab {by_month[ym].tab}; skipped")
            continue
        if parsed := parse_month(tab, *ym, grid, warnings):
            by_month[ym] = parsed
    return ParseResult(months=[by_month[k] for k in sorted(by_month)], warnings=warnings)


def read_workbook(path: str | Path) -> dict[str, Grid]:
    """Cached cell values and solid fill colors for every tab of an .xlsx export."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    tabs = {}
    for ws in wb.worksheets:
        grid = []
        for row in ws.iter_rows():
            cells = []
            for c in row:
                fill = None
                if c.fill is not None and c.fill.fill_type == "solid" and isinstance(c.fill.fgColor.rgb, str):
                    fill = c.fill.fgColor.rgb[-6:].upper()
                value = c.value.strip() or None if isinstance(c.value, str) else c.value
                cells.append(Cell(value, fill))
            grid.append(cells)
        tabs[ws.title] = grid
    return tabs


def check_totals(result: ParseResult) -> list[str]:
    """Compare what we parsed with the sheet's own SALES and MONTHLY TOTAL figures."""
    problems = []
    for m in result.months:
        for rep in m.reps:
            ours = sum(d.amount for d in rep.deals)
            if rep.sheet_sales is not None and abs(ours - rep.sheet_sales) > 0.005:
                problems.append(f"{m.tab}: {rep.name} deals add up to {ours:,.2f}, sheet SALES says {rep.sheet_sales:,.2f}")
        ours = sum(d.amount for rep in m.reps for d in rep.deals)
        if m.sheet_total is not None and abs(ours - m.sheet_total) > 0.005:
            problems.append(f"{m.tab}: deals add up to {ours:,.2f}, sheet MONTHLY TOTAL says {m.sheet_total:,.2f}")
    return problems


def resolve_names(spellings: list[str], fixes: dict[str, str]) -> dict[str, str]:
    """Name key → the name to use for that spelling.

    A name fix wins; otherwise the most-used spelling on the sheet (first seen wins a tie).
    """
    counts: dict[str, Counter[str]] = {}
    for spelling in spellings:
        counts.setdefault(name_key(spelling), Counter())[spelling] += 1
    return {key: fixes.get(key) or c.most_common(1)[0][0] for key, c in counts.items()}


def current_month(result: ParseResult, today: date) -> SheetMonth | None:
    """The newest tab that isn't for a future month (a tab set up early doesn't take over the board)."""
    eligible = [m for m in result.months if (m.year, m.month) <= (today.year, today.month)]
    return eligible[-1] if eligible else None


def sync(session: Session, result: ParseResult, today: date | None = None) -> dict[str, int]:
    """Bring the database in line with the parsed sheet. Safe to run again and again.

    - Months, reps, clients and flags are matched by name and created when new.
    - Each sheet month's rep rows and quotas are replaced with the sheet's.
    - Deals from the sheet are re-created from scratch; deals entered in the app are left alone.
    - Client and item names go through the saved name fixes (see name_fixes.py); spellings that differ
      only by case or punctuation use the sheet's most-used one.
    - Item text is split into brand + model and linked to the item catalog (see item_parse.py).
    - The current month (newest tab, not in the future) is unlocked and every other sheet month is
      locked, like the sheet's locked tabs.
    - The sheet's MONTHLY TOTAL includes HOUSE, so new reps count toward the total.
    Doesn't commit.
    """
    today = today or date.today()
    current = current_month(result, today)
    current_reps = {rep.name for rep in current.reps} if current else set()

    flags = {f.name: f for f in session.scalars(select(models.Flag))}
    if FLAG_NEW[0] not in flags:
        flags[FLAG_NEW[0]] = models.Flag(name=FLAG_NEW[0], color=FLAG_NEW[1])
        session.add(flags[FLAG_NEW[0]])
    session.merge(models.Setting(key="quota_unit", value="usd_thousands"))

    fixes: dict[str, dict[str, str]] = {"client": {}, "item": {}}
    for kind, key, target in session.execute(select(models.NameFix.kind, models.NameFix.source_key, models.NameFix.target_name)):
        fixes.setdefault(kind, {})[key] = target
    sheet_deals = [d for m in result.months for rep in m.reps for d in rep.deals]
    names = resolve_names([d.client for d in sheet_deals], fixes["client"])
    item_names = resolve_names([desc for d in sheet_deals for _, desc in d.items], fixes["item"])
    catalog = Catalog(session, list(item_names.values()))
    reps = {r.name.upper(): r for r in session.scalars(select(models.Rep))}
    clients: dict[str, models.Client] = {}
    for c in session.scalars(select(models.Client).where(models.Client.location.is_(None)).order_by(models.Client.id)):
        clients.setdefault(name_key(c.name), c)
    periods = {(p.year, p.month): p for p in session.scalars(select(models.Period))}

    # Lines first, with "fetch" so the session forgets the deleted rows (their ids get reused).
    sheet_deal_ids = select(models.Deal.id).where(models.Deal.sheet_ref.is_not(None))
    fetch = {"synchronize_session": "fetch"}
    session.execute(delete(models.DealLine).where(models.DealLine.deal_id.in_(sheet_deal_ids)), execution_options=fetch)
    session.execute(delete(models.Deal).where(models.Deal.sheet_ref.is_not(None)), execution_options=fetch)
    session.flush()

    used_clients: set[str] = set()
    deal_count = 0
    for m in result.months:
        period = periods.get((m.year, m.month))
        if period is None:
            period = periods[(m.year, m.month)] = models.Period(year=m.year, month=m.month)
            session.add(period)
        should_lock = m is not current
        if should_lock and period.locked_at is None:
            period.locked_at = datetime(m.year, m.month, 28) if (m.year, m.month) < (today.year, today.month) else datetime.now()
        elif not should_lock and period.locked_at is not None:
            period.locked_at = period.locked_by_id = None

        period.period_reps.clear()
        session.flush()
        slots: dict[str, models.PeriodRep] = {}
        for rep_data in m.reps:
            rep = reps.get(rep_data.name)
            if rep is None:
                rep = reps[rep_data.name] = models.Rep(name=rep_data.name, counts_toward_total=True)
                session.add(rep)
            rep.active = rep_data.name in current_reps
            if rep_data.name in slots:
                result.warnings.append(f"{m.tab}: {rep_data.name} appears twice; deals merged under one rep, first quota kept")
            else:
                slots[rep_data.name] = models.PeriodRep(rep=rep, display_order=len(slots), quota=rep_data.quota)
                period.period_reps.append(slots[rep_data.name])

            for d in rep_data.deals:
                name = names[name_key(d.client)]
                client = clients.get(name_key(name))
                if client is None:
                    client = clients[name_key(name)] = models.Client(name=name)
                    session.add(client)
                used_clients.add(name_key(name))
                session.add(models.Deal(
                    period=period,
                    rep=rep,
                    client=client,
                    total_cents=round(d.amount * 100),
                    sheet_ref=d.where,
                    sheet_client=d.client[:200],
                    sheet_plus=d.plus,
                    lines=[models.DealLine(item=catalog.item_for(item_names[name_key(desc)]),
                                           description=item_names[name_key(desc)][:200], sheet_description=desc[:200], qty=qty)
                           for qty, desc in d.items],
                    flags=[flags[FLAG_NEW[0]]] if d.new_customer else [],
                ))
                deal_count += 1

    session.flush()
    return {"months": len(result.months), "reps": len({r.name for m in result.months for r in m.reps}),
            "clients": len(used_clients), "deals": deal_count}
