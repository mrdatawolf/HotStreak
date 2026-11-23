"""Set up the sheet's data tabs (Deals, Quotas, Reps) and fill them with the full history, plus the view tabs.

Run once per sheet, at the switch from month tabs to data tabs; try it on a copy of the sheet first.
From api/:
    python -m scripts.setup_sheet_tabs --dry-run    # sync, then report what would be written; writes nothing
    python -m scripts.setup_sheet_tabs              # same, then asks before writing to the sheet
    python -m scripts.setup_sheet_tabs --replace    # delete and rebuild data tabs that already exist
    python -m scripts.setup_sheet_tabs --views      # only (re)build the Board and Overview tabs, then check them

Steps:
  1. Syncs the month tabs into the database, so the history is current (the same sync as Admin → Sheet).
  2. Builds one row per deal, per rep per month (quota and board order), and per rep.
  3. Compares each month's total with the old tab's MONTHLY TOTAL and lists any differences.
  4. Creates the tabs with dropdowns, checkboxes, validation and protected header/ID cells, and writes the rows.
  5. Reads the tabs back and checks the row counts and every month's total.
  6. Builds the Board (month picker) and Overview tabs from formulas; an existing Overview that isn't ours is
     renamed "Overview (old)". Then shows several months on the Board and checks every rep's sales and the
     totals against the app, and every month on the Overview.
The month tabs aren't changed.
"""

import argparse
import sys

from app import sheet_import, sheet_sync, sheet_tabs, sheet_views
from app.config import settings
from app.db import SessionLocal
from app.google_sheet import SheetError, SheetsApi, read_spreadsheet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report only; write nothing to the sheet")
    parser.add_argument("--replace", action="store_true", help="delete existing Deals/Quotas/Reps tabs and rebuild them")
    parser.add_argument("--views", action="store_true", help="only (re)build and check the Board and Overview tabs")
    parser.add_argument("--yes", action="store_true", help="don't ask before writing")
    args = parser.parse_args()

    if not sheet_sync.configured():
        sys.exit("Set TRACKER_GOOGLE_SHEET and TRACKER_GOOGLE_CREDENTIALS in .env first.")
    try:
        api = SheetsApi(settings.google_sheet, settings.google_credentials_path)
        title, tabs = sheet_tabs.existing_tabs(api)
        print(f'Sheet: "{title}"')
        if args.views:
            views(api, title, tabs, args)
            return

        print("\n1. Syncing the month tabs…")
        month_tabs = read_spreadsheet(settings.google_sheet, settings.google_credentials_path)
        status = sheet_sync.run(read=lambda: month_tabs)
        if not status["ok"]:
            sys.exit(f"   Sync failed: {status['message']}")
        c = status["counts"]
        print(f"   {c['months']} months, {c['reps']} reps, {c['clients']} clients, {c['deals']} deals")
        for w in status["warnings"]:
            print(f"   note: {w}")

        parsed = sheet_import.parse_tabs(month_tabs)
        old_totals = {f"{m.year}-{m.month:02d}": m.sheet_total for m in parsed.months}
        with SessionLocal() as db:
            tables = sheet_tabs.build_tables(db)

        print("\n2. Rows to write")
        for tab in sheet_tabs.DATA_TABS:
            print(f"   {tab}: {len(tables.rows[tab])} rows")

        print("\n3. Monthly totals vs the old month tabs")
        diffs = sheet_tabs.compare_totals(tables, old_totals)
        if not diffs:
            print(f"   All {len(tables.month_totals)} months match their tab's MONTHLY TOTAL.")
        for month, old, new in diffs:
            was = "no MONTHLY TOTAL found" if old is None else f"tab says {old:,.2f}"
            print(f"   {month}: {was}; deals add up to {new:,.2f}")

        if args.dry_run:
            print("\nDry run: nothing written.")
            return
        there = [t for t in sheet_tabs.DATA_TABS if t in tabs]
        if there and not args.replace:
            sys.exit(f"\nThe sheet already has {', '.join(there)}. Run with --replace to rebuild "
                     "(anything typed into them since is lost).")
        if not args.yes:
            action = f"replace {', '.join(there)} on" if there else "add Deals, Quotas and Reps to"
            answer = input(f'\nThis will {action} "{title}". Type the sheet\'s title to go ahead: ')
            if answer.strip() != title:
                sys.exit("Didn't match; nothing written.")

        print("\n4. Writing the tabs…")
        sheet_tabs.write_tabs(api, tables, replace=args.replace)
        print("   Done.")

        print("\n5. Reading them back…")
        problems = sheet_tabs.read_back(api, tables)
        for p in problems:
            print(f"   ✗ {p}")
        if problems:
            sys.exit(1)
        print(f"   ✓ Headers, {sum(len(r) for r in tables.rows.values())} rows and every month's total check out.")
        build_and_check_views(api, tables)
    except SheetError as e:
        sys.exit(f"\n{e}")


def views(api, title, tabs, args) -> None:
    """--views: rebuild the Board and Overview from data tabs that are already set up."""
    if sheet_tabs.DEALS not in tabs:
        sys.exit("The sheet has no Deals tab yet; run without --views first.")
    print("\nSyncing from the data tabs…")
    status = sheet_sync.run()
    if not status["ok"]:
        sys.exit(f"   Sync failed: {status['message']}")
    print(f"   {status['counts']['deals']} deals, {len(status['warnings'])} things to check")
    if args.dry_run:
        print("\nDry run: nothing written.")
        return
    if not args.yes:
        answer = input(f'\nThis will build the Board and Overview tabs on "{title}". Type the sheet\'s title to go ahead: ')
        if answer.strip() != title:
            sys.exit("Didn't match; nothing written.")
    with SessionLocal() as db:
        tables = sheet_tabs.build_tables(db)
    build_and_check_views(api, tables)


def build_and_check_views(api, tables) -> None:
    print("\n6. Building the Board and Overview tabs…")
    for note in sheet_views.write_views(api):
        print(f"   {note}")
    print("   Checking them against the app…")
    with SessionLocal() as db:
        months = sheet_views.months_to_check(db)
        problems = sheet_views.check_board(api, db, months) + sheet_views.check_overview(api, tables)
    for p in problems:
        print(f"   ✗ {p}")
    if problems:
        sys.exit(1)
    shown = ", ".join(f"{p.year}-{p.month:02d}" for p in months)
    print(f"   ✓ Board matches the app for {shown}; Overview matches for all {len(tables.month_totals)} months.")


if __name__ == "__main__":
    main()
