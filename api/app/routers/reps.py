from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..db import get_session
from .common import commit, get_or_404

router = APIRouter(prefix="/reps", tags=["reps"])

DUPLICATE = "A rep with that name already exists"


# Viewable with the board key: names are already on the board, and Reports needs them for its rep filter.
@router.get("", response_model=list[schemas.RepOut], dependencies=[Depends(auth.require_viewer)])
def list_reps(db: Session = Depends(get_session)):
    return db.scalars(select(models.Rep).order_by(models.Rep.name)).all()


@router.post("", response_model=schemas.RepOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(auth.require_admin)])
def create_rep(body: schemas.RepCreate, db: Session = Depends(get_session)):
    rep = models.Rep(**body.model_dump())
    db.add(rep)
    commit(db, DUPLICATE)
    return rep


@router.patch("/{rep_id}", response_model=schemas.RepOut, dependencies=[Depends(auth.require_admin)])
def update_rep(rep_id: int, body: schemas.RepUpdate, db: Session = Depends(get_session)):
    rep = get_or_404(db, models.Rep, rep_id, "Rep")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(rep, field, value)
    commit(db, DUPLICATE)
    return rep


@router.delete("/{rep_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(auth.require_admin)])
def delete_rep(rep_id: int, db: Session = Depends(get_session)):
    rep = get_or_404(db, models.Rep, rep_id, "Rep")
    if db.scalar(select(func.count()).select_from(models.Deal).where(models.Deal.rep_id == rep.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This rep has deals; mark them inactive instead")
    db.execute(delete(models.PeriodRep).where(models.PeriodRep.rep_id == rep.id))
    db.delete(rep)
    db.commit()
