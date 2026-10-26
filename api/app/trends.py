"""Trends and forecasts over the whole history.

Single months swing too much to forecast (on the client's data any simple estimate of one month misses by ~40–45%
on average), so forecasts are for the quarter and year, where the swings mostly cancel out. Each one is the average
of the last 12 finished months times the months still to come; its range is how far that same estimate missed on
this tracker's own history, over the same number of months ahead. (Blending in the same months last year tested no
better, so it's shown for comparison only.)

The open month (newest unlocked) is still being filled in, so it is never a finished month: averages, trends and
year-to-date use finished months only, and a forecast counts the open month as max(sales so far, the estimate).

Team figures and the rep/brand/item filters follow app/reports.py.
"""

from collections import defaultdict
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, schemas
from .board import get_quota_unit
from .reports import load_deals, month_index, month_key

# Fewest past cases before a forecast gets a range.
MIN_BACKTEST = 6
QUARTER_NAMES = ["Q1", "Q2", "Q3", "Q4"]


def current_month(db: Session) -> int | None:
    """The open month: the newest unlocked one, else the newest."""
    newest_first = select(models.Period).order_by(models.Period.year.desc(), models.Period.month.desc())
    period = db.scalars(newest_first.where(models.Period.locked_at.is_(None))).first() or db.scalars(newest_first).first()
    return month_index(period.year, period.month) if period else None


def change(cur: float, prior: float | None) -> float | None:
    return (cur - prior) / prior if prior else None


def build_trends(db: Session, cur: int, rep_id: int | None,
                 brand: str | None = None, item_id: int | None = None) -> schemas.Trends:
    unit = get_quota_unit(db)
    filtered = brand is not None or item_id is not None
    periods = {p.id: month_index(p.year, p.month) for p in db.scalars(select(models.Period))}
    reps = {r.id: r for r in db.scalars(select(models.Rep))}

    def counted(rid: int) -> bool:
        return rid == rep_id if rep_id is not None else reps[rid].counts_toward_total

    deals, _ = load_deals(db, [pid for pid, i in periods.items() if i <= cur], periods, brand, item_id)
    team = [d for d in deals if counted(d.rep_id)]
    sales: dict[int, int] = defaultdict(int)
    counts: dict[int, int] = defaultdict(int)
    for d in team:
        sales[d.period_index] += d.total_cents
        counts[d.period_index] += 1

    existing = sorted(i for i in periods.values() if i <= cur)
    done = [i for i in existing if i < cur]
    done_set = set(done)
    last = done[-1] if done else None

    def total(months: range) -> int | None:
        """Sales over these months, or None unless every one is in the tracker and finished."""
        return sum(sales[m] for m in months) if all(m in done_set for m in months) else None

    def window(end: int, n: int) -> range:
        return range(end - n + 1, end + 1)

    def average(end: int | None, n: int) -> float | None:
        t = total(window(end, n)) if end is not None else None
        return t / n if t is not None else None

    months = []
    for m in existing:
        avg3 = average(m, 3)
        months.append(schemas.TrendMonth(
            **month_key(m).model_dump(), sales_cents=sales[m], deal_count=counts[m],
            avg3_cents=round(avg3) if avg3 is not None else None, ttm_cents=total(window(m, 12)), complete=m < cur,
        ))

    def quarter_months(q: int) -> range:
        return range(q * 3, q * 3 + 3)

    quarters = []
    for q in sorted({m // 3 for m in existing}):
        ms = quarter_months(q)
        quarters.append(schemas.QuarterRow(
            year=q // 4, quarter=q % 4 + 1, sales_cents=sum(sales[m] for m in ms), deal_count=sum(counts[m] for m in ms),
            complete=total(ms) is not None,
            prior_quarter_sales_cents=total(quarter_months(q - 1)), prior_year_sales_cents=total(quarter_months(q - 4)),
        ))

    years = []
    for y in sorted({m // 12 for m in done}):
        ms = [m for m in done if m // 12 == y]
        years.append(schemas.YearRow(year=y, sales_cents=sum(sales[m] for m in ms),
                                     deal_count=sum(counts[m] for m in ms), months=len(ms)))

    calendar = []
    for mo in range(12):
        values = [sales[m] for m in done if m % 12 == mo]
        if values:
            calendar.append(schemas.CalendarMonthAvg(month=mo + 1, avg_sales_cents=round(mean(values)), years=len(values)))

    def rounded(v: float | None) -> int | None:
        return round(v) if v is not None else None

    deals_12 = sum(counts[m] for m in window(last, 12)) if average(last, 12) is not None else None
    averages = schemas.Averages(
        monthly_3_cents=rounded(average(last, 3)),
        monthly_6_cents=rounded(average(last, 6)),
        monthly_12_cents=rounded(average(last, 12)),
        deals_per_month_12=deals_12 / 12 if deals_12 is not None else None,
        avg_deal_12_cents=round(total(window(last, 12)) / deals_12) if deals_12 else None,  # type: ignore[operator]
    )

    ytd = None
    if last is not None and last // 12 == cur // 12:
        ytd_months = range(last // 12 * 12, last + 1)
        prior = range(ytd_months.start - 12, ytd_months.stop - 12)
        prior_sales = total(prior)
        ytd = schemas.YearToDate(
            through=month_key(last), sales_cents=total(ytd_months) or 0, deal_count=sum(counts[m] for m in ytd_months),
            prior_sales_cents=prior_sales,
            prior_deal_count=sum(counts[m] for m in prior) if prior_sales is not None else None,
        )

    def typical_miss(ahead: int, count: int) -> float | None:
        """Average miss of "12-month average × months" for the `count` months starting `ahead` months after
        each past finished month."""
        misses = []
        for t in done:
            rate = average(t, 12)
            actual = total(range(t + ahead, t + ahead + count))
            if rate is not None and actual:
                misses.append(abs(rate * count - actual) / actual)
        return mean(misses) if len(misses) >= MIN_BACKTEST else None

    def quota_cents(ms: range) -> int | None:
        """Team quota for these months in cents; months not started yet reuse the open month's quota."""
        if filtered or unit == "units":
            return None
        per_month: dict[int, float] = defaultdict(float)
        has: set[int] = set()
        for pr in db.scalars(select(models.PeriodRep)):
            idx = periods[pr.period_id]
            if pr.quota is not None and counted(pr.rep_id) and (idx in ms or idx == cur):
                per_month[idx] += pr.quota
                has.add(idx)
        if cur not in has:
            return None
        values = [per_month[m] if m in has else per_month[cur] for m in ms]
        return round(sum(values) * (100_000 if unit == "usd_thousands" else 100))

    rate = average(last, 12)

    def forecast(label: str, ms: range) -> schemas.Forecast | None:
        open_months = [m for m in ms if m not in done_set]
        if rate is None or last is None or not open_months:
            return None
        actual = sum(sales[m] for m in ms if m in done_set)
        so_far = sales[cur] if cur in ms else 0
        rest = sum(max(sales[m], rate) if m == cur else rate for m in open_months)
        estimate = actual + rest
        miss = typical_miss(open_months[0] - last, len(open_months))
        spread = rate * len(open_months) * miss if miss is not None else None
        same_last_year = range(ms.start - 12, ms.stop - 12)
        return schemas.Forecast(
            label=label,
            estimate_cents=round(estimate),
            low_cents=round(max(estimate - spread, actual + so_far)) if spread is not None else None,
            high_cents=round(estimate + spread) if spread is not None else None,
            typical_miss=miss,
            actual_cents=actual,
            months_actual=len(ms) - len(open_months),
            months_total=len(ms),
            includes_open_month=cur in ms,
            last_year_cents=total(same_last_year),
            quota_cents=quota_cents(ms),
        )

    q = cur // 3
    forecasts = [f for f in (
        forecast(f"This quarter ({QUARTER_NAMES[q % 4]} {q // 4})", quarter_months(q)),
        forecast(f"Next quarter ({QUARTER_NAMES[(q + 1) % 4]} {(q + 1) // 4})", quarter_months(q + 1)),
        forecast(f"This year ({cur // 12})", range(cur // 12 * 12, cur // 12 * 12 + 12)),
    ) if f]

    # Last 12 finished months vs the 12 before, by rep (everyone, like Sales by rep) and by brand.
    rep_growth: list[schemas.GrowthRow] = []
    brand_growth: list[schemas.GrowthRow] = []
    if last is not None and total(window(last, 24)) is not None:
        recent, before = window(last, 12), window(last - 12, 12)
        by_rep: dict[int, list[float]] = defaultdict(lambda: [0, 0])
        by_brand: dict[str, list[float]] = defaultdict(lambda: [0, 0])
        for d in deals:
            slot = 0 if d.period_index in recent else 1 if d.period_index in before else None
            if slot is None:
                continue
            if rep_id is None or d.rep_id == rep_id:
                by_rep[d.rep_id][slot] += d.total_cents
            if counted(d.rep_id):
                for line in d.lines:
                    by_brand[line.brand][slot] += line.cents

        def rows(values: dict, label) -> list[schemas.GrowthRow]:
            out = [schemas.GrowthRow(label=label(k), sales_cents=round(v[0]), prior_sales_cents=round(v[1]),
                                     change=change(v[0], v[1])) for k, v in values.items()]
            return sorted(out, key=lambda r: r.sales_cents, reverse=True)

        rep_growth = rows(by_rep, lambda rid: reps[rid].name)
        brand_growth = rows(by_brand, lambda b: b)

    return schemas.Trends(
        current=month_key(cur),
        last_complete=month_key(last) if last is not None else None,
        filtered=filtered,
        months=months,
        quarters=quarters,
        years=years,
        calendar=calendar,
        averages=averages,
        ytd=ytd,
        forecasts=forecasts,
        rep_growth=rep_growth,
        brand_growth=brand_growth,
    )
