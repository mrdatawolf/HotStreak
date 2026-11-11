from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..db import get_session

IN_USE = "This user has history in the tracker; deactivate them instead"

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(auth.require_admin)])


def get_user(db: Session, user_id: int) -> models.User:
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


def other_active_admins(db: Session, user_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(models.User).where(
            models.User.role == "admin", models.User.active.is_(True), models.User.id != user_id
        )
    )


def commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with that email already exists") from None


@router.get("", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_session)):
    return db.scalars(select(models.User).order_by(models.User.name)).all()


@router.post("", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: schemas.UserCreate, db: Session = Depends(get_session)):
    user = models.User(name=body.name, email=body.email, role=body.role, password_hash=auth.hash_password(body.password))
    db.add(user)
    commit_or_conflict(db)
    return user


@router.patch("/{user_id}", response_model=schemas.UserOut)
def update_user(user_id: int, body: schemas.UserUpdate, db: Session = Depends(get_session)):
    user = get_user(db, user_id)
    changes = body.model_dump(exclude_unset=True)
    losing_admin = user.role == "admin" and user.active and (
        changes.get("role", "admin") != "admin" or changes.get("active", True) is False
    )
    if losing_admin and not other_active_admins(db, user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Can't remove the last active admin")
    for field, value in changes.items():
        setattr(user, field, value)
    if changes.get("active") is False:
        auth.revoke_user_sessions(db, user.id)
    commit_or_conflict(db)
    return user


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def set_password(user_id: int, body: schemas.SetPasswordIn, db: Session = Depends(get_session)):
    user = get_user(db, user_id)
    user.password_hash = auth.hash_password(body.password)
    user.failed_logins = 0
    user.locked_until = None
    auth.revoke_user_sessions(db, user.id)
    db.commit()


@router.post("/{user_id}/unlock", response_model=schemas.UserOut)
def unlock_user(user_id: int, db: Session = Depends(get_session)):
    user = get_user(db, user_id)
    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: Session = Depends(get_session)):
    user = get_user(db, user_id)
    if user.role == "admin" and user.active and not other_active_admins(db, user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Can't remove the last active admin")
    used = db.scalar(
        select(func.count()).select_from(models.Deal).where(
            or_(models.Deal.created_by_id == user.id, models.Deal.updated_by_id == user.id)
        )
    )
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, IN_USE)
    db.delete(user)
    try:
        db.commit()
    except IntegrityError:  # referenced elsewhere, e.g. locked a month
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, IN_USE) from None
