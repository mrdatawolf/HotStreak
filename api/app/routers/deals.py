"""Deal entry. Any signed-in user can add, edit, or delete deals in an unlocked month."""

import calendar

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import auth, models, schemas
from ..board import line_label
from ..db import get_session
from .common import blank_to_none, get_or_404

router = APIRouter(prefix="/deals", tags=["deals"], dependencies=[Depends(auth.require_user)])

LOAD_OPTIONS = (
    selectinload(models.Deal.period),
    selectinload(models.Deal.rep),
    selectinload(models.Deal.client),
    selectinload(models.Deal.flags),
    selectinload(models.Deal.lines).selectinload(models.DealLine.item),
    selectinload(models.Deal.created_by),
    selectinload(models.Deal.updated_by),
)


def deal_out(deal: models.Deal) -> schemas.DealOut:
    return schemas.DealOut(
        id=deal.id,
        period_id=deal.period_id,
        period_locked=deal.period.locked_at is not None,
        sheet_ref=deal.sheet_ref,
        sheet_plus=deal.sheet_plus,
        rep_id=deal.rep_id,
        rep_name=deal.rep.name,
        client=schemas.ClientOut.model_validate(deal.client),
        deal_date=deal.deal_date,
        total_cents=deal.total_cents,
        notes=deal.notes,
        lines=[
            schemas.DealLineOut(
                id=line.id,
                item_id=line.item_id,
                description=line.description,
                label=line_label(line),
                category=line.item.category if line.item else None,
                qty=line.qty,
                amount_cents=line.amount_cents,
            )
            for line in deal.lines
        ],
        flags=[schemas.FlagOut.model_validate(f) for f in deal.flags],
        created_by_name=deal.created_by.name if deal.created_by else None,
        updated_by_name=deal.updated_by.name if deal.updated_by else None,
        created_at=deal.created_at,
        updated_at=deal.updated_at,
    )


def load_deal(db: Session, deal_id: int) -> models.Deal:
    deal = db.scalars(select(models.Deal).where(models.Deal.id == deal_id).options(*LOAD_OPTIONS)).first()
    if not deal:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal not found")
    return deal


def unlocked_period(db: Session, period_id: int) -> models.Period:
    period = get_or_404(db, models.Period, period_id, "Month")
    if period.locked_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "That month is locked")
    return period


def not_from_sheet(deal: models.Deal) -> None:
    # The next sync would overwrite the change.
    if deal.sheet_ref:
        raise HTTPException(status.HTTP_409_CONFLICT, f"This deal comes from the Google Sheet ({deal.sheet_ref}); change it there")


def unprocessable(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)


def apply(db: Session, deal: models.Deal, body: schemas.DealIn, principal: auth.Principal) -> None:
    """Validate references and copy the request onto the deal."""
    period = unlocked_period(db, body.period_id)
    if not db.get(models.Rep, body.rep_id):
        raise unprocessable("Unknown rep")

    if body.deal_date and (body.deal_date.year, body.deal_date.month) != (period.year, period.month):
        raise unprocessable(f"Date must be in {calendar.month_name[period.month]} {period.year}")

    if body.new_client:
        name, location = body.new_client.name, blank_to_none(body.new_client.location)
        same_location = models.Client.location == location if location else models.Client.location.is_(None)
        client = db.scalars(select(models.Client).where(models.Client.name == name, same_location)).first()
        client = client or models.Client(name=name, location=location)
    else:
        client = db.get(models.Client, body.client_id)
        if not client:
            raise unprocessable("Unknown client")

    item_ids = {line.item_id for line in body.lines if line.item_id is not None}
    items = {i.id: i for i in db.scalars(select(models.Item).where(models.Item.id.in_(item_ids)))}
    if item_ids - items.keys():
        raise unprocessable("Unknown item")

    flags = list(db.scalars(select(models.Flag).where(models.Flag.id.in_(body.flag_ids))))
    if len(flags) != len(set(body.flag_ids)):
        raise unprocessable("Unknown flag")

    if body.total_cents is not None:
        total = body.total_cents
    elif all(line.amount_cents is not None for line in body.lines):
        total = sum(line.amount_cents for line in body.lines)  # type: ignore[misc]
    else:
        raise unprocessable("Enter a total, or an amount on every line")

    deal.period_id = period.id
    deal.rep_id = body.rep_id
    deal.client = client
    deal.deal_date = body.deal_date
    deal.total_cents = total
    deal.notes = blank_to_none(body.notes)
    deal.flags = flags
    deal.lines = [
        models.DealLine(
            item=items.get(line.item_id) if line.item_id is not None else None,
            description=blank_to_none(line.description),
            qty=line.qty,
            amount_cents=line.amount_cents,
        )
        for line in body.lines
    ]
    deal.updated_by_id = principal.user_id


@router.get("", response_model=list[schemas.DealOut])
def list_deals(period_id: int | None = None, rep_id: int | None = None, db: Session = Depends(get_session)):
    query = select(models.Deal).options(*LOAD_OPTIONS).order_by(
        models.Deal.deal_date.desc().nulls_last(), models.Deal.id.desc()
    )
    if period_id is not None:
        query = query.where(models.Deal.period_id == period_id)
    if rep_id is not None:
        query = query.where(models.Deal.rep_id == rep_id)
    return [deal_out(d) for d in db.scalars(query)]


@router.get("/{deal_id}", response_model=schemas.DealOut)
def get_deal(deal_id: int, db: Session = Depends(get_session)):
    return deal_out(load_deal(db, deal_id))


@router.post("", response_model=schemas.DealOut, status_code=status.HTTP_201_CREATED)
def create_deal(
    body: schemas.DealIn, principal: auth.Principal = Depends(auth.require_user), db: Session = Depends(get_session)
):
    deal = models.Deal(created_by_id=principal.user_id)
    apply(db, deal, body, principal)
    db.add(deal)
    db.commit()
    return deal_out(load_deal(db, deal.id))


@router.put("/{deal_id}", response_model=schemas.DealOut)
def update_deal(
    deal_id: int,
    body: schemas.DealIn,
    principal: auth.Principal = Depends(auth.require_user),
    db: Session = Depends(get_session),
):
    deal = load_deal(db, deal_id)
    not_from_sheet(deal)
    # Can't edit a deal out of (or into) a locked month.
    unlocked_period(db, deal.period_id)
    apply(db, deal, body, principal)
    db.commit()
    db.expire(deal)
    return deal_out(load_deal(db, deal.id))


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deal(deal_id: int, db: Session = Depends(get_session)):
    deal = load_deal(db, deal_id)
    not_from_sheet(deal)
    unlocked_period(db, deal.period_id)
    db.delete(deal)
    db.commit()
