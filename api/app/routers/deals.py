"""Deal entry. Only admins add, edit, or delete deals; users view their own rep's deals.

Once the Google Sheet has the Deals tab (sheet_sync.writes_to_sheet), a save goes to the sheet first and comes
back by sync, so the sheet stays the source of truth; admins can then change deals in any month. Before that,
deals entered here live in the app only, in unlocked months, and sheet deals are changed on the sheet.
"""

import calendar

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import auth, models, schemas, sheet_sync, sheet_write
from ..board import line_label
from ..db import get_session
from ..sheet_import import FLAG_NEW
from ..sheet_tabs import DEALS_HEADERS, ID_PATTERN, deal_values
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
        version=deal.sheet_version,
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
    # Without the Deals tab, the next sync would overwrite the change.
    if deal.sheet_ref:
        raise HTTPException(status.HTTP_409_CONFLICT, f"This deal comes from the Google Sheet ({deal.sheet_ref}); change it there")


def unprocessable(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)


def apply(db: Session, deal: models.Deal, body: schemas.DealIn, principal: auth.Principal, any_month: bool = False) -> None:
    """Validate references and copy the request onto the deal. any_month: locked months are allowed too."""
    period = get_or_404(db, models.Period, body.period_id, "Month") if any_month else unlocked_period(db, body.period_id)
    rep = db.get(models.Rep, body.rep_id)
    if not rep:
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
    if any_month:  # a draft for the sheet (never added to the session) needs the objects to build its row
        deal.period, deal.rep = period, rep
    deal.client = client
    deal.deal_date = body.deal_date
    deal.total_cents = total
    deal.notes = blank_to_none(body.notes)
    deal.sheet_plus = body.plus
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


# Declared before /{deal_id}, which would otherwise match "mode".
@router.get("/mode", response_model=schemas.DealMode)
def deal_mode(db: Session = Depends(get_session)):
    return schemas.DealMode(sheet=sheet_sync.writes_to_sheet(db))


@router.get("", response_model=list[schemas.DealOut])
def list_deals(
    period_id: int | None = None,
    rep_id: int | None = None,
    principal: auth.Principal = Depends(auth.require_user),
    db: Session = Depends(get_session),
):
    rep_id = auth.scoped_rep_id(principal, rep_id)
    query = select(models.Deal).options(*LOAD_OPTIONS).order_by(
        models.Deal.deal_date.desc().nulls_last(), models.Deal.id.desc()
    )
    if period_id is not None:
        query = query.where(models.Deal.period_id == period_id)
    if rep_id is not None:
        query = query.where(models.Deal.rep_id == rep_id)
    return [deal_out(d) for d in db.scalars(query)]


@router.get("/{deal_id}", response_model=schemas.DealOut)
def get_deal(deal_id: int, principal: auth.Principal = Depends(auth.require_user), db: Session = Depends(get_session)):
    deal = load_deal(db, deal_id)
    rep_id = auth.scoped_rep_id(principal, deal.rep_id)
    if rep_id != deal.rep_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal not found")
    return deal_out(deal)


def sheet_draft(db: Session, body: schemas.DealIn, principal: auth.Principal) -> dict:
    """Validate the request and turn it into Deals-tab values (without ID, Entered by and Updated)."""
    draft = models.Deal()
    apply(db, draft, body, principal, any_month=True)
    if other := [f.name for f in draft.flags if f.name != FLAG_NEW[0]]:
        raise unprocessable(f"The Google Sheet only records the {FLAG_NEW[0]} flag; untick {', '.join(other)}")
    values = dict(zip(DEALS_HEADERS, deal_values(draft, "", f"{draft.period.year}-{draft.period.month:02d}")))
    for name in ("ID", "Entered by", "Updated"):
        del values[name]
    values["Updated"] = sheet_write.now_serial()
    return values


def synced_deal(db: Session, ref: str, principal: auth.Principal) -> schemas.DealOut:
    """The deal the sync brought back for this sheet ID, marked as changed by this admin."""
    deal = db.scalars(select(models.Deal).where(models.Deal.sheet_ref == ref)).first()
    if deal is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"Saved to the sheet as {ref}, but the sync skipped that row; see Admin → Sheet")
    deal.updated_by_id = principal.user_id
    db.commit()
    db.expire(deal)
    return deal_out(load_deal(db, deal.id))


def on_deals_tab(deal: models.Deal) -> bool:
    return bool(deal.sheet_ref and ID_PATTERN.match(deal.sheet_ref))


@router.post("", response_model=schemas.DealOut, status_code=status.HTTP_201_CREATED)
def create_deal(
    body: schemas.DealIn, principal: auth.Principal = Depends(auth.require_admin), db: Session = Depends(get_session)
):
    if sheet_sync.writes_to_sheet(db):
        values = {**sheet_draft(db, body, principal), "Entered by": principal.name}
        ref = sheet_write.write_then_sync(db, lambda api: sheet_write.add_deal(api, values))
        return synced_deal(db, ref, principal)
    deal = models.Deal(created_by_id=principal.user_id)
    apply(db, deal, body, principal)
    db.add(deal)
    db.commit()
    return deal_out(load_deal(db, deal.id))


def stale(deal: models.Deal, version: str | None) -> None:
    if version and deal.sheet_version and version != deal.sheet_version:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This deal was changed on the sheet after you opened it; reload to see the change")


@router.put("/{deal_id}", response_model=schemas.DealOut)
def update_deal(
    deal_id: int,
    body: schemas.DealIn,
    principal: auth.Principal = Depends(auth.require_admin),
    db: Session = Depends(get_session),
):
    deal = load_deal(db, deal_id)
    if sheet_sync.writes_to_sheet(db):
        stale(deal, body.version)
        values = sheet_draft(db, body, principal)
        if on_deals_tab(deal):
            ref, version = deal.sheet_ref, deal.sheet_version
            sheet_write.write_then_sync(db, lambda api: sheet_write.update_deal(api, ref, version, values))
        else:
            # Entered in the app before the sheet took over: it moves to the sheet as a new row.
            values["Entered by"] = deal.created_by.name if deal.created_by else principal.name
            local_id = deal.id

            def drop_local(_ref):
                db.delete(db.get(models.Deal, local_id))
                db.commit()

            ref = sheet_write.write_then_sync(db, lambda api: sheet_write.add_deal(api, values), then=drop_local)
        return synced_deal(db, ref, principal)
    not_from_sheet(deal)
    # Can't edit a deal out of (or into) a locked month.
    unlocked_period(db, deal.period_id)
    apply(db, deal, body, principal)
    db.commit()
    db.expire(deal)
    return deal_out(load_deal(db, deal.id))


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(auth.require_admin)])
def delete_deal(deal_id: int, version: str | None = None, db: Session = Depends(get_session)):
    """`version`: the deal's version when it was opened, so a change made on the sheet since isn't deleted unseen."""
    deal = load_deal(db, deal_id)
    if sheet_sync.writes_to_sheet(db) and on_deals_tab(deal):
        stale(deal, version)
        ref, current = deal.sheet_ref, deal.sheet_version
        sheet_write.write_then_sync(db, lambda api: sheet_write.delete_deal(api, ref, current))
        return
    if not sheet_sync.writes_to_sheet(db):
        not_from_sheet(deal)
        unlocked_period(db, deal.period_id)
    db.delete(deal)
    db.commit()
