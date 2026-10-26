"""Builds the month board: the same numbers the sheet computes in its QUOTA/SALES columns."""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import models, schemas

DEFAULT_QUOTA_UNIT: schemas.QuotaUnit = "usd_thousands"


def get_quota_unit(session: Session) -> schemas.QuotaUnit:
    setting = session.get(models.Setting, "quota_unit")
    return setting.value if setting else DEFAULT_QUOTA_UNIT  # type: ignore[return-value]


def pct_of_quota(quota: float | None, sales_cents: int, units: int, unit: schemas.QuotaUnit) -> float | None:
    if not quota:
        return None
    if unit == "units":
        achieved = units
    elif unit == "usd":
        achieved = sales_cents / 100
    else:
        achieved = sales_cents / 100_000
    return achieved / quota


def line_label(line: models.DealLine) -> str:
    if line.item:
        return f"{line.item.brand} {line.item.model}" if line.item.brand else line.item.model
    return line.description or ""


def build_board(session: Session, period: models.Period) -> schemas.Board:
    unit = get_quota_unit(session)
    deals = session.scalars(
        select(models.Deal)
        .where(models.Deal.period_id == period.id)
        .options(
            selectinload(models.Deal.client),
            selectinload(models.Deal.rep),
            selectinload(models.Deal.flags),
            selectinload(models.Deal.lines).selectinload(models.DealLine.item),
        )
        .order_by(models.Deal.deal_date.is_(None), models.Deal.deal_date, models.Deal.id)
    ).all()

    deals_by_rep: dict[int, list[models.Deal]] = {}
    for deal in deals:
        deals_by_rep.setdefault(deal.rep_id, []).append(deal)

    slots: list[tuple[models.Rep, float | None]] = [(pr.rep, pr.quota) for pr in period.period_reps]
    # A deal logged for a rep who isn't on this month's board must still be counted.
    on_board = {rep.id for rep, _ in slots}
    for deal in deals:
        if deal.rep_id not in on_board:
            slots.append((deal.rep, None))
            on_board.add(deal.rep_id)

    reps: list[schemas.BoardRep] = []
    total = 0
    for rep, quota in slots:
        rep_deals = deals_by_rep.get(rep.id, [])
        sales = sum(d.total_cents for d in rep_deals)
        units = sum(line.qty for d in rep_deals for line in d.lines)
        if rep.counts_toward_total:
            total += sales
        reps.append(
            schemas.BoardRep(
                rep_id=rep.id,
                name=rep.name,
                counts_toward_total=rep.counts_toward_total,
                quota=quota,
                sales_cents=sales,
                units=units,
                pct_of_quota=pct_of_quota(quota, sales, units, unit),
                deals=[
                    schemas.BoardDeal(
                        id=d.id,
                        client_name=d.client.name,
                        client_location=d.client.location,
                        deal_date=d.deal_date,
                        total_cents=d.total_cents,
                        lines=[
                            schemas.BoardLine(
                                label=line_label(line),
                                qty=line.qty,
                                category=line.item.category if line.item else None,
                            )
                            for line in d.lines
                        ],
                        flags=[schemas.FlagOut.model_validate(f) for f in d.flags],
                    )
                    for d in rep_deals
                ],
            )
        )

    return schemas.Board(
        period=schemas.PeriodOut.model_validate(period),
        quota_unit=unit,
        reps=reps,
        total_sales_cents=total,
    )
