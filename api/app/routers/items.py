from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..db import get_session
from .common import blank_to_none, commit, get_or_404

router = APIRouter(prefix="/items", tags=["items"])

DUPLICATE = "That brand and model already exist"


@router.get("", response_model=list[schemas.ItemOut], dependencies=[Depends(auth.require_user)])
def list_items(q: str | None = None, limit: int = 500, db: Session = Depends(get_session)):
    query = select(models.Item).order_by(models.Item.brand, models.Item.model)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(models.Item.brand.ilike(like), models.Item.model.ilike(like)))
    return db.scalars(query.limit(min(limit, 1000))).all()


@router.post("", response_model=schemas.ItemOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(auth.require_admin)])
def create_item(body: schemas.ItemIn, db: Session = Depends(get_session)):
    item = models.Item(brand=blank_to_none(body.brand), model=body.model, category=body.category)
    db.add(item)
    commit(db, DUPLICATE)
    return item


@router.put("/{item_id}", response_model=schemas.ItemOut, dependencies=[Depends(auth.require_admin)])
def update_item(item_id: int, body: schemas.ItemIn, db: Session = Depends(get_session)):
    item = get_or_404(db, models.Item, item_id, "Item")
    item.brand = blank_to_none(body.brand)
    item.model = body.model
    item.category = body.category
    commit(db, DUPLICATE)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(auth.require_admin)])
def delete_item(item_id: int, db: Session = Depends(get_session)):
    item = get_or_404(db, models.Item, item_id, "Item")
    if db.scalar(select(func.count()).select_from(models.DealLine).where(models.DealLine.item_id == item.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This item is on existing deals and can't be deleted")
    db.delete(item)
    db.commit()
