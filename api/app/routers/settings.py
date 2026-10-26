import secrets

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..board import get_quota_unit
from ..db import get_session

router = APIRouter(prefix="/settings", tags=["settings"])


def settings_out(db: Session, principal: auth.Principal) -> schemas.AppSettings:
    return schemas.AppSettings(
        quota_unit=get_quota_unit(db),
        board_key=auth.get_board_key(db) if principal.is_admin else None,
    )


@router.get("", response_model=schemas.AppSettings)
def get_settings(principal: auth.Principal = Depends(auth.require_user), db: Session = Depends(get_session)):
    return settings_out(db, principal)


@router.patch("", response_model=schemas.AppSettings)
def update_settings(
    body: schemas.AppSettingsUpdate,
    principal: auth.Principal = Depends(auth.require_admin),
    db: Session = Depends(get_session),
):
    db.merge(models.Setting(key="quota_unit", value=body.quota_unit))
    db.commit()
    return settings_out(db, principal)


@router.post("/board-key", response_model=schemas.AppSettings)
def rotate_board_key(principal: auth.Principal = Depends(auth.require_admin), db: Session = Depends(get_session)):
    """Create or replace the read-only key for TV displays. Displays using the old key stop working."""
    db.merge(models.Setting(key=auth.BOARD_KEY_SETTING, value=secrets.token_urlsafe(18)))
    db.commit()
    return settings_out(db, principal)


@router.delete("/board-key", response_model=schemas.AppSettings)
def remove_board_key(principal: auth.Principal = Depends(auth.require_admin), db: Session = Depends(get_session)):
    setting = db.get(models.Setting, auth.BOARD_KEY_SETTING)
    if setting:
        db.delete(setting)
        db.commit()
    return settings_out(db, principal)
