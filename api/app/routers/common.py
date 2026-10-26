from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import Base


def get_or_404[T: Base](db: Session, model: type[T], obj_id: int, label: str) -> T:
    obj = db.get(model, obj_id)
    if not obj:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found")
    return obj


def commit(db: Session, conflict: str) -> None:
    """Commit, turning unique/foreign-key violations into a 409 with the given message."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, conflict) from None


def blank_to_none(value: str | None) -> str | None:
    return value or None
