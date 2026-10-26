"""Database schema.

Money is stored as integer cents to avoid floating point rounding.
A rep appears on a month's board when they have a PeriodRep row for that month;
"start new month" (phase 4) will clone those rows forward, like cloning the sheet tab.
"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

ITEM_CATEGORIES = ("printer", "mfp", "software", "accessory", "service", "other")

deal_flags = Table(
    "deal_flags",
    Base.metadata,
    Column("deal_id", ForeignKey("deals.id", ondelete="CASCADE"), primary_key=True),
    Column("flag_id", ForeignKey("flags.id", ondelete="CASCADE"), primary_key=True),
)


USER_ROLES = ("admin", "user")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    # Stored lowercase; used to sign in.
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="user", server_default="user")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuthSession(Base):
    """A signed-in device. Only a hash of the token is stored."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Null for break-glass sessions, which have no user row.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    is_breakglass: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)

    user: Mapped[User | None] = relationship()


class Rep(Base):
    __tablename__ = "reps"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # False for accounts like HOUSE that shouldn't roll into the grand total.
    counts_toward_total: Mapped[bool] = mapped_column(Boolean, default=True)


class Period(Base):
    __tablename__ = "periods"
    __table_args__ = (UniqueConstraint("year", "month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime)
    locked_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    period_reps: Mapped[list["PeriodRep"]] = relationship(
        back_populates="period", order_by="PeriodRep.display_order", cascade="all, delete-orphan"
    )


class PeriodRep(Base):
    """A rep's slot on one month's board: their quota and row order."""

    __tablename__ = "period_reps"
    __table_args__ = (UniqueConstraint("period_id", "rep_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id", ondelete="CASCADE"))
    rep_id: Mapped[int] = mapped_column(ForeignKey("reps.id"))
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    # Null means no quota (shown as "~" on the sheet, e.g. HOUSE).
    quota: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))

    period: Mapped[Period] = relationship(back_populates="period_reps")
    rep: Mapped[Rep] = relationship()


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("name", "location"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # Branch/site for clients with several locations.
    location: Mapped[str | None] = mapped_column(String(200))


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("brand", "model"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(20), default="other")


class Flag(Base):
    __tablename__ = "flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    color: Mapped[str] = mapped_column(String(20))


class Deal(Base):
    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), index=True)
    rep_id: Mapped[int] = mapped_column(ForeignKey("reps.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    deal_date: Mapped[date | None] = mapped_column(Date)
    total_cents: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    # Set on deals synced from the client's Google Sheet: the cell ("926!C5") and the client
    # name as spelled there (markers stripped). Deals entered in the app leave both null.
    sheet_ref: Mapped[str | None] = mapped_column(String(20))
    sheet_client: Mapped[str | None] = mapped_column(String(200))
    # The client was marked "+" on the sheet that month (a notation; meaning kept by the client).
    sheet_plus: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    period: Mapped[Period] = relationship()
    client: Mapped[Client] = relationship()
    rep: Mapped[Rep] = relationship()
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    updated_by: Mapped[User | None] = relationship(foreign_keys=[updated_by_id])
    lines: Mapped[list["DealLine"]] = relationship(
        back_populates="deal", order_by="DealLine.id", cascade="all, delete-orphan"
    )
    flags: Mapped[list[Flag]] = relationship(secondary=deal_flags, order_by="Flag.id")


class DealLine(Base):
    __tablename__ = "deal_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), index=True)
    # Either a catalog item or free text (e.g. "Various").
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"))
    description: Mapped[str | None] = mapped_column(String(200))
    # For lines synced from the sheet: the item text as typed there (description may be a fixed name).
    sheet_description: Mapped[str | None] = mapped_column(String(200))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    amount_cents: Mapped[int | None] = mapped_column(Integer)

    deal: Mapped[Deal] = relationship(back_populates="lines")
    item: Mapped[Item | None] = relationship()


NAME_FIX_KINDS = ("client", "item")


class NameFix(Base):
    """A correction for a name typed on the sheet: a client or item spelled `source_name` is `target_name`.

    Kept across sheet syncs, so a typo fixed once stays fixed. A fix whose target is its own source
    marks the name as checked ("not a typo").
    """

    __tablename__ = "name_fixes"
    __table_args__ = (UniqueConstraint("kind", "source_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="client")
    # Normalized source spelling (see sheet_import.name_key).
    source_key: Mapped[str] = mapped_column(String(200))
    source_name: Mapped[str] = mapped_column(String(200))
    target_name: Mapped[str] = mapped_column(String(200))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    created_by: Mapped[User | None] = relationship()


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
