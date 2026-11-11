from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..db import get_session
from .common import commit, get_or_404

router = APIRouter(prefix="/flags", tags=["flags"])

DUPLICATE = "A flag with that name already exists"


@router.get("", response_model=list[schemas.FlagOut], dependencies=[Depends(auth.require_user)])
def list_flags(db: Session = Depends(get_session)):
    return db.scalars(select(models.Flag).order_by(models.Flag.id)).all()


@router.post("", response_model=schemas.FlagOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(auth.require_admin)])
def create_flag(body: schemas.FlagIn, db: Session = Depends(get_session)):
    flag = models.Flag(name=body.name, color=body.color.lower())
    db.add(flag)
    commit(db, DUPLICATE)
    return flag


@router.put("/{flag_id}", response_model=schemas.FlagOut, dependencies=[Depends(auth.require_admin)])
def update_flag(flag_id: int, body: schemas.FlagIn, db: Session = Depends(get_session)):
    flag = get_or_404(db, models.Flag, flag_id, "Flag")
    flag.name = body.name
    flag.color = body.color.lower()
    commit(db, DUPLICATE)
    return flag


@router.delete("/{flag_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(auth.require_admin)])
def delete_flag(flag_id: int, db: Session = Depends(get_session)):
    """Also removes the flag from any deals that have it."""
    flag = get_or_404(db, models.Flag, flag_id, "Flag")
    db.delete(flag)
    db.commit()
