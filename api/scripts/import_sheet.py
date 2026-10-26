"""Sync the client's sales sheet into the database, from an .xlsx export or the live Google Sheet.

Usage (from api/):
    python -m scripts.import_sheet "../Samples/2026 Sales Sheet.xlsx"   # from an export
    python -m scripts.import_sheet --google                             # from TRACKER_GOOGLE_SHEET
Options: --dry-run only reports what it found; --reset first deletes all sales data, including deals
entered in the app (users, settings and name fixes are kept).

Safe to run repeatedly: deals from the sheet are replaced, deals entered in the app are kept, and
saved client-name fixes are applied. The newest month is open and the rest are locked. Deal totals are
checked against the sheet's own SALES and MONTHLY TOTAL figures, and anything odd is listed.
"""

import argparse
import sys

from sqlalchemy.orm import Session

from app import sheet_import
from app.config import settings
from app.db import Base, SessionLocal, make_engine
from app.google_sheet import SheetError, read_spreadsheet
from scripts.seed import reset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("xlsx", nargs="?", help="path to an .xlsx export")
    source.add_argument("--google", action="store_true", help="read the live sheet (TRACKER_GOOGLE_SHEET)")
    parser.add_argument("--reset", action="store_true", help="delete all sales data first")
    parser.add_argument("--dry-run", action="store_true", help="parse and report without writing")
    args = parser.parse_args()

    if args.google:
        if not settings.google_sheet or not settings.google_credentials_path:
            sys.exit("Set TRACKER_GOOGLE_SHEET and TRACKER_GOOGLE_CREDENTIALS in .env first.")
        try:
            tabs = read_spreadsheet(settings.google_sheet, settings.google_credentials_path)
        except SheetError as e:
            sys.exit(str(e))
    else:
        tabs = sheet_import.read_workbook(args.xlsx)
    result = sheet_import.parse_tabs(tabs)
    if not result.months:
        sys.exit("No month tabs found.")
    mismatches = sheet_import.check_totals(result)

    if args.dry_run:
        # Load into a throwaway in-memory database so the schema's constraints still get checked.
        engine = make_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            counts = sheet_import.sync(session, result)
    else:
        with SessionLocal() as session:
            if args.reset:
                reset(session)
            counts = sheet_import.sync(session, result)
            session.commit()

    first, last = result.months[0], result.months[-1]
    print(f"{'Would sync' if args.dry_run else 'Synced'} {first.month:02}/{first.year} → {last.month:02}/{last.year}: "
          + ", ".join(f"{v} {k}" for k, v in counts.items()))
    print(f"Totals: {'all match the sheet' if not mismatches else f'{len(mismatches)} differ from the sheet'}")
    for line in mismatches:
        print("  " + line)
    if result.warnings:
        print(f"Warnings ({len(result.warnings)}):")
        for line in result.warnings:
            print("  " + line)


if __name__ == "__main__":
    main()
