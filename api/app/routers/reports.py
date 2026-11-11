import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..db import get_session
from ..reports import build_report, month_index
from ..trends import build_trends, current_month

# Read-only, so TV displays (board key) can show it too.
router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(auth.require_viewer)])

MAX_MONTHS = 120
MONTH = re.compile(r"^(\d{4})-(\d{2})$")


def parse_month(value: str, name: str) -> int:
    m = MONTH.match(value)
    if not m or not 1 <= int(m[2]) <= 12:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{name} must look like 2026-09")
    return month_index(int(m[1]), int(m[2]))


def require_current(db: Session) -> int:
    cur = current_month(db)
    if cur is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No months exist yet")
    return cur


def check_filters(db: Session, rep_id: int | None, item_id: int | None) -> None:
    if rep_id is not None and not db.get(models.Rep, rep_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown rep")
    if item_id is not None and not db.get(models.Item, item_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown item")


@router.get("", response_model=schemas.Report)
def report(
    start: str | None = Query(None, description="First month, YYYY-MM (default: 11 months before end)"),
    end: str | None = Query(None, description="Last month, YYYY-MM (default: the current month)"),
    rep_id: int | None = None,
    brand: str | None = Query(None, description='Only this brand\'s items ("(no brand)" for items without one)'),
    item_id: int | None = Query(None, description="Only this catalog item (model)"),
    db: Session = Depends(get_session),
):
    if end:
        end_i = parse_month(end, "end")
    else:
        end_i = require_current(db)
    start_i = parse_month(start, "start") if start else end_i - 11
    if start_i > end_i:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "start must be on or before end")
    if end_i - start_i + 1 > MAX_MONTHS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Pick at most {MAX_MONTHS} months")
    check_filters(db, rep_id, item_id)
    return build_report(db, start_i, end_i, rep_id, brand or None, item_id)


@router.get("/trends", response_model=schemas.Trends)
def trends(
    rep_id: int | None = None,
    brand: str | None = Query(None, description='Only this brand\'s items ("(no brand)" for items without one)'),
    item_id: int | None = Query(None, description="Only this catalog item (model)"),
    db: Session = Depends(get_session),
):
    """Whole-history trends and quarter/year forecasts, up to the current month."""
    cur = require_current(db)
    check_filters(db, rep_id, item_id)
    return build_trends(db, cur, rep_id, brand or None, item_id)
