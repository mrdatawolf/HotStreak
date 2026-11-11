"""Google Sheet sync status and the client/item name fixes that sync applies."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from .. import auth, models, name_fixes, schemas, sheet_sync
from ..config import settings
from ..db import get_session
from ..google_sheet import SheetError, service_account_email, spreadsheet_id
from ..names import name_key
from .common import get_or_404

router = APIRouter(prefix="/sheet", tags=["sheet"], dependencies=[Depends(auth.require_admin)])


def status_out(db: Session) -> schemas.SheetSyncStatus:
    creds = settings.google_credentials_path
    try:
        url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id(settings.google_sheet)}/edit" if settings.google_sheet else None
    except SheetError:
        url = None
    return schemas.SheetSyncStatus(
        configured=sheet_sync.configured(),
        sheet_url=url,
        service_account=service_account_email(creds) if creds else None,
        interval_minutes=settings.google_sync_minutes,
        last=sheet_sync.get_status(db),
    )


def fix_out(fix: models.NameFix) -> schemas.NameFixOut:
    return schemas.NameFixOut(
        id=fix.id,
        source_name=fix.source_name,
        target_name=fix.target_name,
        checked=name_key(fix.target_name) == fix.source_key,
        created_by_name=fix.created_by.name if fix.created_by else None,
        created_at=fix.created_at,
    )


@router.get("/sync", response_model=schemas.SheetSyncStatus)
def get_sync(db: Session = Depends(get_session)):
    return status_out(db)


@router.post("/sync", response_model=schemas.SheetSyncStatus)
def sync_now(db: Session = Depends(get_session)):
    sheet_sync.run()
    db.expire_all()
    return status_out(db)


@router.get("/names/{kind}", response_model=list[schemas.SheetName])
def list_names(kind: schemas.NameKind, db: Session = Depends(get_session)):
    rows = name_fixes.sheet_names(db, kind)
    return [schemas.SheetName(**{**r, "fix": fix_out(r["fix"]) if r["fix"] else None}) for r in rows]


@router.post("/names/{kind}/apply-suggestions", response_model=list[schemas.AppliedFix])
def apply_suggestions(kind: schemas.NameKind, principal: auth.Principal = Depends(auth.require_admin),
                      db: Session = Depends(get_session)):
    """Fix every suggested match at once; each name goes under the most-used spelling in its group."""
    done = name_fixes.apply_suggestions(db, kind, principal.user_id)
    db.commit()
    return [schemas.AppliedFix(source_name=s, target_name=t) for s, t in done]


@router.post("/name-fixes", response_model=schemas.NameFixOut, status_code=status.HTTP_201_CREATED)
def save_fix(body: schemas.NameFixIn, principal: auth.Principal = Depends(auth.require_admin),
             db: Session = Depends(get_session)):
    fix = name_fixes.save_fix(db, body.kind, body.source_name, body.target_name, principal.user_id)
    db.commit()
    return fix_out(fix)


@router.delete("/name-fixes/{fix_id}", status_code=status.HTTP_204_NO_CONTENT)
def undo_fix(fix_id: int, db: Session = Depends(get_session)):
    name_fixes.undo_fix(db, get_or_404(db, models.NameFix, fix_id, "Name fix"))
    db.commit()
