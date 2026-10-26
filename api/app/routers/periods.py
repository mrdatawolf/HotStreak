from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import auth, models, schemas
from ..board import build_board
from ..db import get_session

router = APIRouter(prefix="/periods", tags=["periods"], dependencies=[Depends(auth.require_viewer)])


def load_period(db: Session, period_id: int) -> models.Period:
    period = db.scalars(
        select(models.Period)
        .where(models.Period.id == period_id)
        .options(selectinload(models.Period.period_reps).selectinload(models.PeriodRep.rep))
    ).first()
    if not period:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Month not found")
    return period


def period_reps_out(period: models.Period) -> list[schemas.PeriodRepOut]:
    return [schemas.PeriodRepOut(rep_id=pr.rep_id, name=pr.rep.name, quota=pr.quota) for pr in period.period_reps]


@router.get("", response_model=list[schemas.PeriodOut])
def list_periods(session: Session = Depends(get_session)):
    return session.scalars(
        select(models.Period).order_by(models.Period.year.desc(), models.Period.month.desc())
    ).all()


@router.get("/summary", response_model=list[schemas.PeriodSummary], dependencies=[Depends(auth.require_user)])
def period_summaries(db: Session = Depends(get_session)):
    """Every month, newest first, with deal counts and totals (for the Months screen)."""
    deals = dict(db.execute(select(models.Deal.period_id, func.count()).group_by(models.Deal.period_id)).all())
    reps = dict(db.execute(select(models.PeriodRep.period_id, func.count()).group_by(models.PeriodRep.period_id)).all())
    totals = dict(db.execute(
        select(models.Deal.period_id, func.sum(models.Deal.total_cents))
        .join(models.Rep, models.Deal.rep_id == models.Rep.id)
        .where(models.Rep.counts_toward_total.is_(True))
        .group_by(models.Deal.period_id)
    ).all())
    users = dict(db.execute(select(models.User.id, models.User.name)).all())
    periods = db.scalars(select(models.Period).order_by(models.Period.year.desc(), models.Period.month.desc()))
    return [
        schemas.PeriodSummary(
            id=p.id,
            year=p.year,
            month=p.month,
            locked_at=p.locked_at,
            locked_by_name=users.get(p.locked_by_id),
            rep_count=reps.get(p.id, 0),
            deal_count=deals.get(p.id, 0),
            total_sales_cents=totals.get(p.id) or 0,
        )
        for p in periods
    ]


@router.post("", response_model=schemas.PeriodOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(auth.require_admin)])
def start_period(body: schemas.PeriodCreate | None = None, db: Session = Depends(get_session)):
    """Start a month, copying reps, order, and quotas from the newest earlier month (like cloning the sheet tab)."""
    body = body or schemas.PeriodCreate()
    newest = db.scalars(select(models.Period).order_by(models.Period.year.desc(), models.Period.month.desc())).first()
    if body.year is not None:
        year, month = body.year, body.month
    elif newest:
        year, month = (newest.year + 1, 1) if newest.month == 12 else (newest.year, newest.month + 1)
    else:
        today = auth.utcnow().date()
        year, month = today.year, today.month
    if db.scalars(select(models.Period).where(models.Period.year == year, models.Period.month == month)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"{month:02d}/{year} already exists")

    template = db.scalars(
        select(models.Period)
        .where((models.Period.year < year) | ((models.Period.year == year) & (models.Period.month < month)))
        .order_by(models.Period.year.desc(), models.Period.month.desc())
        .options(selectinload(models.Period.period_reps).selectinload(models.PeriodRep.rep))
    ).first()
    period = models.Period(year=year, month=month)
    if template:
        # Inactive reps are left off; re-add them on the Quotas screen if needed.
        active = [pr for pr in template.period_reps if pr.rep.active]
        period.period_reps = [
            models.PeriodRep(rep_id=pr.rep_id, display_order=i, quota=pr.quota) for i, pr in enumerate(active)
        ]
    db.add(period)
    db.commit()
    return period


@router.post("/{period_id}/lock", response_model=schemas.PeriodOut)
def lock_period(
    period_id: int, principal: auth.Principal = Depends(auth.require_admin), db: Session = Depends(get_session)
):
    """Close a month: its deals and quotas become read-only."""
    period = load_period(db, period_id)
    if not period.locked_at:
        period.locked_at = auth.utcnow()
        period.locked_by_id = principal.user_id
        db.commit()
    return period


@router.post("/{period_id}/unlock", response_model=schemas.PeriodOut, dependencies=[Depends(auth.require_admin)])
def unlock_period(period_id: int, db: Session = Depends(get_session)):
    period = load_period(db, period_id)
    period.locked_at = None
    period.locked_by_id = None
    db.commit()
    return period


@router.get("/current", response_model=schemas.PeriodOut)
def current_period(session: Session = Depends(get_session)):
    """The newest unlocked month, falling back to the newest month."""
    newest_first = select(models.Period).order_by(models.Period.year.desc(), models.Period.month.desc())
    period = session.scalars(newest_first.where(models.Period.locked_at.is_(None))).first()
    period = period or session.scalars(newest_first).first()
    if not period:
        raise HTTPException(404, "No months exist yet")
    return period


@router.get("/{period_id}/board", response_model=schemas.Board)
def period_board(period_id: int, session: Session = Depends(get_session)):
    return build_board(session, load_period(session, period_id))


@router.get("/{period_id}/reps", response_model=list[schemas.PeriodRepOut])
def get_period_reps(period_id: int, db: Session = Depends(get_session)):
    return period_reps_out(load_period(db, period_id))


@router.put("/{period_id}/reps", response_model=list[schemas.PeriodRepOut], dependencies=[Depends(auth.require_admin)])
def set_period_reps(period_id: int, body: list[schemas.PeriodRepIn], db: Session = Depends(get_session)):
    """Replace which reps are on this month's board, their quotas, and their order (list order)."""
    period = load_period(db, period_id)
    if period.locked_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This month is locked")
    rep_ids = [row.rep_id for row in body]
    if len(set(rep_ids)) != len(rep_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A rep is listed twice")
    reps = {r.id: r for r in db.scalars(select(models.Rep).where(models.Rep.id.in_(rep_ids)))}
    if missing := [i for i in rep_ids if i not in reps]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown rep id(s): {missing}")

    existing = {pr.rep_id: pr for pr in period.period_reps}
    for pr in period.period_reps:
        if pr.rep_id not in reps:
            db.delete(pr)
    for order, row in enumerate(body):
        pr = existing.get(row.rep_id) or models.PeriodRep(period_id=period.id, rep_id=row.rep_id)
        pr.display_order = order
        pr.quota = row.quota
        db.add(pr)
    db.commit()
    # Reload so the collection comes back in the new order.
    db.expire(period)
    return period_reps_out(load_period(db, period_id))
