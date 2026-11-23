from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..board import get_quota_unit
from ..db import get_session

router = APIRouter(prefix="/settings", tags=["settings"])


def settings_out(db: Session) -> schemas.AppSettings:
    return schemas.AppSettings(quota_unit=get_quota_unit(db))


@router.get("", response_model=schemas.AppSettings, dependencies=[Depends(auth.require_user)])
def get_settings(db: Session = Depends(get_session)):
    return settings_out(db)


@router.patch("", response_model=schemas.AppSettings, dependencies=[Depends(auth.require_admin)])
def update_settings(
    body: schemas.AppSettingsUpdate,
    db: Session = Depends(get_session),
):
    db.merge(models.Setting(key="quota_unit", value=body.quota_unit))
    db.commit()
    return settings_out(db)
