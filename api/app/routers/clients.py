from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..db import get_session
from .common import blank_to_none, commit, get_or_404

router = APIRouter(prefix="/clients", tags=["clients"])

DUPLICATE = "That client and location already exist"


@router.get("", response_model=list[schemas.ClientOut], dependencies=[Depends(auth.require_user)])
def list_clients(q: str | None = None, limit: int = 500, db: Session = Depends(get_session)):
    query = select(models.Client).order_by(models.Client.name, models.Client.location)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(models.Client.name.ilike(like), models.Client.location.ilike(like)))
    return db.scalars(query.limit(min(limit, 1000))).all()


@router.post("", response_model=schemas.ClientOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(auth.require_admin)])
def create_client(body: schemas.ClientIn, db: Session = Depends(get_session)):
    client = models.Client(name=body.name, location=blank_to_none(body.location))
    db.add(client)
    commit(db, DUPLICATE)
    return client


@router.put("/{client_id}", response_model=schemas.ClientOut, dependencies=[Depends(auth.require_admin)])
def update_client(client_id: int, body: schemas.ClientIn, db: Session = Depends(get_session)):
    client = get_or_404(db, models.Client, client_id, "Client")
    client.name = body.name
    client.location = blank_to_none(body.location)
    commit(db, DUPLICATE)
    return client


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(auth.require_admin)])
def delete_client(client_id: int, db: Session = Depends(get_session)):
    client = get_or_404(db, models.Client, client_id, "Client")
    if db.scalar(select(func.count()).select_from(models.Deal).where(models.Deal.client_id == client.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This client has deals and can't be deleted")
    db.delete(client)
    db.commit()
