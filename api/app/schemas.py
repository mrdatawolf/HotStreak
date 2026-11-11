from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

QuotaUnit = Literal["usd_thousands", "usd", "units"]


class PeriodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    year: int
    month: int
    locked_at: datetime | None


class FlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: str


class BoardLine(BaseModel):
    label: str
    qty: int
    category: str | None


class BoardDeal(BaseModel):
    id: int
    client_name: str
    client_location: str | None
    deal_date: date | None
    total_cents: int
    lines: list[BoardLine]
    flags: list[FlagOut]


class BoardRep(BaseModel):
    rep_id: int
    name: str
    counts_toward_total: bool
    quota: float | None
    sales_cents: int
    units: int
    # Fraction (0.5 = 50%); null when the rep has no quota.
    pct_of_quota: float | None
    deals: list[BoardDeal]


class Board(BaseModel):
    period: PeriodOut
    quota_unit: QuotaUnit
    reps: list[BoardRep]
    total_sales_cents: int


# --- Auth ---

Role = Literal["admin", "user"]
Category = Literal["printer", "mfp", "software", "accessory", "service", "other"]

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Email = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=255, pattern=r"^[^@\s]+@[^@\s]+$")
]
Password = Annotated[str, StringConstraints(min_length=10, max_length=200)]
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


class LoginIn(BaseModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class Me(BaseModel):
    user_id: int | None
    name: str
    email: str | None
    role: str
    is_admin: bool
    is_breakglass: bool


class LoginOut(BaseModel):
    token: str
    user: Me


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: Password


# --- Users ---


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: Role
    active: bool
    locked_until: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    name: NonEmpty
    email: Email
    role: Role = "user"
    password: Password


class UserUpdate(BaseModel):
    name: NonEmpty | None = None
    email: Email | None = None
    role: Role | None = None
    active: bool | None = None


class SetPasswordIn(BaseModel):
    password: Password


# --- Reference data ---


class RepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    active: bool
    counts_toward_total: bool


class RepCreate(BaseModel):
    name: NonEmpty
    active: bool = True
    counts_toward_total: bool = True


class RepUpdate(BaseModel):
    name: NonEmpty | None = None
    active: bool | None = None
    counts_toward_total: bool | None = None


class PeriodRepOut(BaseModel):
    rep_id: int
    name: str
    quota: float | None


class PeriodRepIn(BaseModel):
    rep_id: int
    quota: Annotated[float, Field(ge=0)] | None = None


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    location: str | None


class ClientIn(BaseModel):
    name: NonEmpty
    location: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brand: str | None
    model: str
    category: Category


class ItemIn(BaseModel):
    brand: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    model: NonEmpty
    category: Category = "other"


class FlagIn(BaseModel):
    name: NonEmpty
    color: HexColor


class AppSettings(BaseModel):
    quota_unit: QuotaUnit
    # Only returned to admins.
    board_key: str | None


class AppSettingsUpdate(BaseModel):
    quota_unit: QuotaUnit


# --- Deals ---


class DealLineIn(BaseModel):
    # A catalog item, or free text (e.g. "Various") when it isn't in the catalog.
    item_id: int | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    qty: Annotated[int, Field(ge=1, le=100_000)] = 1
    amount_cents: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def item_or_description(self):
        if self.item_id is None and not self.description:
            raise ValueError("Each line needs a catalog item or a description")
        return self


class DealIn(BaseModel):
    period_id: int
    rep_id: int
    # An existing client, or a new one to create (reused if that name + location already exists).
    client_id: int | None = None
    new_client: ClientIn | None = None
    deal_date: date | None = None
    # Omit to use the sum of the line amounts.
    total_cents: Annotated[int, Field(ge=0)] | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    flag_ids: list[int] = []
    lines: Annotated[list[DealLineIn], Field(min_length=1, max_length=50)]

    @model_validator(mode="after")
    def one_client(self):
        if (self.client_id is None) == (self.new_client is None):
            raise ValueError("Give either client_id or new_client")
        return self


class DealLineOut(BaseModel):
    id: int
    item_id: int | None
    description: str | None
    label: str
    category: str | None
    qty: int
    amount_cents: int | None


class DealOut(BaseModel):
    id: int
    period_id: int
    period_locked: bool
    # The sheet cell ("926!C5") for deals synced from the Google Sheet; those are read-only here.
    sheet_ref: str | None
    # The client was marked "+" on the sheet that month.
    sheet_plus: bool
    rep_id: int
    rep_name: str
    client: ClientOut
    deal_date: date | None
    total_cents: int
    notes: str | None
    lines: list[DealLineOut]
    flags: list[FlagOut]
    created_by_name: str | None
    updated_by_name: str | None
    created_at: datetime
    updated_at: datetime


# --- Months ---


class PeriodCreate(BaseModel):
    """Omit both to start the month after the newest one."""

    year: Annotated[int, Field(ge=2000, le=2100)] | None = None
    month: Annotated[int, Field(ge=1, le=12)] | None = None

    @model_validator(mode="after")
    def both_or_neither(self):
        if (self.year is None) != (self.month is None):
            raise ValueError("Give both year and month, or neither")
        return self


class PeriodSummary(PeriodOut):
    locked_by_name: str | None
    rep_count: int
    deal_count: int
    total_sales_cents: int


# --- Reports ---


class MonthKey(BaseModel):
    year: int
    month: int


class KpiSet(BaseModel):
    sales_cents: int
    deal_count: int
    avg_deal_cents: int | None
    units: int
    active_clients: int
    new_clients: int
    # Share of active clients with 2+ deals in the range.
    repeat_client_rate: float | None
    # Team sales vs team quota (in the quota unit); null if no quotas.
    quota_attainment: float | None


class MonthPoint(BaseModel):
    year: int
    month: int
    sales_cents: int
    deal_count: int
    # Same month one year earlier (null if that month isn't in the tracker).
    prior_year_sales_cents: int | None
    attainment: float | None


class RepRow(BaseModel):
    rep_id: int
    name: str
    sales_cents: int
    deal_count: int
    avg_deal_cents: int | None
    attainment: float | None
    # One per month in the range; null when the rep had no quota that month.
    monthly_attainment: list[float | None]


class CategoryMonth(BaseModel):
    year: int
    month: int
    # category -> sales cents
    sales_cents: dict[str, int]


class RankedRow(BaseModel):
    label: str
    detail: str | None = None
    sales_cents: int
    count: int  # units for items, deals for clients


class Bucket(BaseModel):
    label: str
    min_cents: int
    max_cents: int | None
    deal_count: int
    sales_cents: int


class Report(BaseModel):
    start: MonthKey
    end: MonthKey
    months: list[MonthKey]
    quota_unit: QuotaUnit
    kpis: KpiSet
    # The same-length range just before this one, for deltas.
    prior_kpis: KpiSet
    monthly: list[MonthPoint]
    reps: list[RepRow]
    categories: list[str]
    category_monthly: list[CategoryMonth]
    # Every item (brand + model) sold in the range, by sales; detail is the category, count is units.
    items: list[RankedRow]
    # Sales by brand ("(no brand)" for items without one); count is units.
    brands: list[RankedRow]
    # Month-by-month mix: by brand, or by model when a brand filter is set. The last series may be
    # "Everything else".
    mix_by: Literal["brand", "model"]
    mix_series: list[str]
    mix_monthly: list[CategoryMonth]
    # Filtered to a brand and/or item: figures count only those items; no quota attainment.
    filtered: bool
    top_clients: list[RankedRow]
    top_clients_share: float | None
    deal_sizes: list[Bucket]


# --- Trends and forecast (whole history; see app/trends.py) ---


class TrendMonth(BaseModel):
    year: int
    month: int
    sales_cents: int
    deal_count: int
    # Average of this month and the two before (null without all three).
    avg3_cents: int | None
    # Total of the 12 months ending here (null without all twelve).
    ttm_cents: int | None
    # False for the open month, still being filled in.
    complete: bool


class QuarterRow(BaseModel):
    year: int
    quarter: int
    sales_cents: int
    deal_count: int
    # All three months are in the tracker and finished.
    complete: bool
    prior_quarter_sales_cents: int | None
    prior_year_sales_cents: int | None


class YearRow(BaseModel):
    year: int
    sales_cents: int
    deal_count: int
    # Finished months in the tracker for this year.
    months: int


class CalendarMonthAvg(BaseModel):
    month: int
    avg_sales_cents: int
    # How many years went into the average.
    years: int


class Averages(BaseModel):
    """Averages over the last finished months."""

    monthly_3_cents: int | None
    monthly_6_cents: int | None
    monthly_12_cents: int | None
    deals_per_month_12: float | None
    avg_deal_12_cents: int | None


class YearToDate(BaseModel):
    # Last finished month counted (the open month is left out on both sides).
    through: MonthKey
    sales_cents: int
    deal_count: int
    prior_sales_cents: int | None
    prior_deal_count: int | None


class Forecast(BaseModel):
    label: str
    estimate_cents: int
    # Range from how far this method has typically missed on past data (null without enough history).
    low_cents: int | None
    high_cents: int | None
    typical_miss: float | None
    # Sales already in from finished months of the period.
    actual_cents: int
    months_actual: int
    months_total: int
    # The open month is part of this period (counted as max(sales so far, the estimate)).
    includes_open_month: bool
    last_year_cents: int | None
    # Team quota for the period in cents (null when quotas are in units, missing, or the report is filtered).
    quota_cents: int | None


class GrowthRow(BaseModel):
    label: str
    sales_cents: int
    prior_sales_cents: int
    change: float | None


class Trends(BaseModel):
    # The open month (still being filled in) and the last finished month.
    current: MonthKey
    last_complete: MonthKey | None
    filtered: bool
    months: list[TrendMonth]
    quarters: list[QuarterRow]
    years: list[YearRow]
    calendar: list[CalendarMonthAvg]
    averages: Averages
    ytd: YearToDate | None
    forecasts: list[Forecast]
    # Last 12 finished months vs the 12 before.
    rep_growth: list[GrowthRow]
    brand_growth: list[GrowthRow]


# --- Google Sheet sync ---


class SyncCounts(BaseModel):
    months: int
    reps: int
    clients: int
    deals: int


class SyncRun(BaseModel):
    at: datetime
    ok: bool
    message: str | None
    counts: SyncCounts | None
    # Where our totals differ from the sheet's SALES / MONTHLY TOTAL cells, and anything guessed at.
    mismatches: list[str]
    warnings: list[str]


class SheetSyncStatus(BaseModel):
    configured: bool
    sheet_url: str | None
    # The email to share the sheet with.
    service_account: str | None
    interval_minutes: int
    last: SyncRun | None


class NameFixOut(BaseModel):
    id: int
    source_name: str
    target_name: str
    # Target is its own spelling: checked, not a typo.
    checked: bool
    created_by_name: str | None
    created_at: datetime


NameKind = Literal["client", "item"]


class SheetName(BaseModel):
    """A client or item name as typed on the sheet (spellings differing only by case/punctuation grouped)."""

    key: str
    spellings: list[str]
    # Deals (clients) or deal lines (items) typed this way.
    count: int
    # The name they go under now (after any fix).
    current_name: str
    fix: NameFixOut | None
    # Likely matches for a spelling that hasn't been fixed or checked yet.
    suggestions: list[str]


class NameFixIn(BaseModel):
    kind: NameKind
    source_name: NonEmpty
    # The name it should go under; the same as source_name to mark it "not a typo".
    target_name: NonEmpty


class AppliedFix(BaseModel):
    source_name: str
    target_name: str
