from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..db import get_session

router = APIRouter(prefix="/auth", tags=["auth"])


def me_out(p: auth.Principal) -> schemas.Me:
    return schemas.Me(
        user_id=p.user_id, name=p.name, email=p.email, role=p.role, is_admin=p.is_admin, is_breakglass=p.is_breakglass
    )


@router.post("/login", response_model=schemas.LoginOut)
def login(body: schemas.LoginIn, db: Session = Depends(get_session)):
    try:
        token, principal = auth.login(db, body.username, body.password)
    except auth.LoginError as e:
        raise HTTPException(e.status_code, e.detail) from None
    return schemas.LoginOut(token=token, user=me_out(principal))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(principal: auth.Principal = Depends(auth.require_user), db: Session = Depends(get_session)):
    db.execute(delete(models.AuthSession).where(models.AuthSession.id == principal.session_id))
    db.commit()


@router.get("/me", response_model=schemas.Me)
def me(principal: auth.Principal = Depends(auth.require_viewer)):
    return me_out(principal)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: schemas.ChangePasswordIn,
    principal: auth.Principal = Depends(auth.require_user),
    db: Session = Depends(get_session),
):
    if principal.is_breakglass:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The break-glass password is set in the .env file")
    user = db.get(models.User, principal.user_id)
    if not user or not auth.verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = auth.hash_password(body.new_password)
    # Sign out other devices; keep this one.
    db.execute(
        delete(models.AuthSession).where(
            models.AuthSession.user_id == user.id, models.AuthSession.id != principal.session_id
        )
    )
    db.commit()
