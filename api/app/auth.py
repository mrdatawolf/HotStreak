"""Passwords, sessions, and the permission checks used by the routers.

Three kinds of callers:
- a signed-in user (Authorization: Bearer <token>), role "admin" or "user"
- the break-glass super admin from .env, which has no user row and can always sign in
- a TV/display holding the read-only board key (X-Board-Key header), which can only view the board
"""

import base64
import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .db import get_session

log = logging.getLogger("tracker.auth")

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
MIN_PASSWORD_LENGTH = 10
BOARD_KEY_SETTING = "board_key"

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def utcnow() -> datetime:
    # Naive UTC, which is what SQLite stores.
    return datetime.now(UTC).replace(tzinfo=None)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


# Checked against when the email is unknown, so response time doesn't reveal which emails exist.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Principal:
    name: str
    role: str  # "admin", "user", or "board"
    user_id: int | None = None
    email: str | None = None
    is_breakglass: bool = False
    session_id: int | None = None

    @property
    def is_admin(self) -> bool:
        return self.is_breakglass or self.role == "admin"


def breakglass_principal(session_id: int | None = None) -> Principal:
    return Principal(name="Break-glass admin", role="admin", is_breakglass=True, session_id=session_id)


def create_session(db: Session, user: models.User | None) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        models.AuthSession(
            token_hash=_token_hash(token),
            user_id=user.id if user else None,
            is_breakglass=user is None,
            expires_at=utcnow() + timedelta(days=settings.session_days),
        )
    )
    return token


def revoke_user_sessions(db: Session, user_id: int) -> None:
    db.execute(delete(models.AuthSession).where(models.AuthSession.user_id == user_id))


class LoginError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


def login(db: Session, username: str, password: str) -> tuple[str, Principal]:
    """Returns (token, principal) or raises LoginError."""
    username = username.strip()
    bg_password = settings.breakglass_password
    if bg_password and hmac.compare_digest(username.lower().encode(), settings.breakglass_user.lower().encode()):
        if not hmac.compare_digest(password.encode(), bg_password.encode()):
            log.warning("Failed break-glass sign-in")
            # Break-glass never locks out, so slow down guessing instead.
            time.sleep(1)
            raise LoginError(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
        log.warning("Break-glass admin signed in")
        token = create_session(db, None)
        db.commit()
        return token, breakglass_principal()

    user = db.scalars(select(models.User).where(models.User.email == username.lower())).first()
    if not user or not user.active:
        verify_password(password, _DUMMY_HASH)
        raise LoginError(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    now = utcnow()
    if user.locked_until and user.locked_until > now:
        raise LoginError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed sign-ins. Try again later or ask an admin to unlock the account.",
        )

    if not verify_password(password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.failed_logins = 0
            user.locked_until = now + LOCKOUT
            log.warning("Locked account %s after repeated failed sign-ins", user.email)
        db.commit()
        raise LoginError(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    user.failed_logins = 0
    user.locked_until = None
    token = create_session(db, user)
    db.commit()
    return token, user_principal(user)


def user_principal(user: models.User, session_id: int | None = None) -> Principal:
    return Principal(name=user.name, role=user.role, user_id=user.id, email=user.email, session_id=session_id)


def get_board_key(db: Session) -> str | None:
    setting = db.get(models.Setting, BOARD_KEY_SETTING)
    return setting.value if setting else None


def get_principal(
    db: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
    x_board_key: str | None = Header(default=None),
) -> Principal | None:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        auth = db.scalars(
            select(models.AuthSession).where(models.AuthSession.token_hash == _token_hash(token))
        ).first()
        if not auth or auth.expires_at <= utcnow():
            return None
        if auth.is_breakglass:
            # A session outlives a password change in .env only if break-glass is still enabled.
            return breakglass_principal(auth.id) if settings.breakglass_password else None
        if auth.user and auth.user.active:
            return user_principal(auth.user, auth.id)
        return None

    if x_board_key:
        key = get_board_key(db)
        if key and hmac.compare_digest(x_board_key.encode(), key.encode()):
            return Principal(name="Board display", role="board")
    return None


def require_viewer(principal: Principal | None = Depends(get_principal)) -> Principal:
    """Anyone allowed to see the board, including a display with the board key."""
    if not principal:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    return principal


def require_user(principal: Principal = Depends(require_viewer)) -> Principal:
    if principal.role == "board":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    return principal


def require_admin(principal: Principal = Depends(require_user)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only")
    return principal
