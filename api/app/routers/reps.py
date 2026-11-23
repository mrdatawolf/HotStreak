from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import auth, models, schemas, sheet_sync, sheet_write
from ..db import get_session
from .common import commit, get_or_404

router = APIRouter(prefix="/reps", tags=["reps"])

DUPLICATE = "A rep with that name already exists"


# Any signed-in user: Reports needs the names for its rep filter.
@router.get("", response_model=list[schemas.RepOut], dependencies=[Depends(auth.require_user)])
def list_reps(db: Session = Depends(get_session)):
    return db.scalars(select(models.Rep).order_by(models.Rep.name)).all()


@router.post("", response_model=schemas.RepOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(auth.require_admin)])
def create_rep(body: schemas.RepCreate, db: Session = Depends(get_session)):
    if sheet_sync.writes_to_sheet(db):
        # The sheet keeps rep names in capitals (the sync reads them that way).
        name = body.name.upper()
        if find_rep(db, name):
            raise HTTPException(status.HTTP_409_CONFLICT, DUPLICATE)
        sheet_write.write_then_sync(
            db, lambda api: sheet_write.save_rep(api, None, name, body.active, body.counts_toward_total))
        rep = find_rep(db, name)
        if rep is None:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Added to the sheet, but the sync didn't bring the rep in")
        return rep
    rep = models.Rep(**body.model_dump())
    db.add(rep)
    commit(db, DUPLICATE)
    return rep


@router.patch("/{rep_id}", response_model=schemas.RepOut, dependencies=[Depends(auth.require_admin)])
def update_rep(rep_id: int, body: schemas.RepUpdate, db: Session = Depends(get_session)):
    rep = get_or_404(db, models.Rep, rep_id, "Rep")
    if sheet_sync.writes_to_sheet(db):
        old = rep.name
        changes = body.model_dump(exclude_unset=True)
        name = (changes.get("name") or old).upper()
        active = changes.get("active", rep.active)
        counts = changes.get("counts_toward_total", rep.counts_toward_total)
        other = find_rep(db, name)
        if other and other.id != rep.id:
            raise HTTPException(status.HTTP_409_CONFLICT, DUPLICATE)

        def rename_here(_):
            # Before the sync, so it finds this rep (and the users linked to it) under the new name.
            db.get(models.Rep, rep_id).name = name
            db.commit()

        sheet_write.write_then_sync(db, lambda api: sheet_write.save_rep(api, old, name, active, counts), then=rename_here)
        return get_or_404(db, models.Rep, rep_id, "Rep")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(rep, field, value)
    commit(db, DUPLICATE)
    return rep


@router.delete("/{rep_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(auth.require_admin)])
def delete_rep(rep_id: int, db: Session = Depends(get_session)):
    rep = get_or_404(db, models.Rep, rep_id, "Rep")
    if db.scalar(select(func.count()).select_from(models.Deal).where(models.Deal.rep_id == rep.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This rep has deals; mark them inactive instead")
    if db.scalar(select(func.count()).select_from(models.User).where(models.User.rep_id == rep.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Users are linked to this rep; link them to another rep first")
    if sheet_sync.writes_to_sheet(db):
        name = rep.name

        def delete_here(_):
            db.execute(delete(models.PeriodRep).where(models.PeriodRep.rep_id == rep_id))
            db.delete(db.get(models.Rep, rep_id))
            db.commit()

        sheet_write.write_then_sync(db, lambda api: sheet_write.delete_rep(api, name), then=delete_here)
        return
    db.execute(delete(models.PeriodRep).where(models.PeriodRep.rep_id == rep.id))
    db.delete(rep)
    db.commit()


def find_rep(db: Session, name: str) -> models.Rep | None:
    return db.scalars(select(models.Rep).where(func.upper(models.Rep.name) == name.upper())).first()
