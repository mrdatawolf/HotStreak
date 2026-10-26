"""Sales reports over a range of months.

Team figures follow the board's rule: reps not marked "counts toward total" (e.g. HOUSE) are left out,
unless the report is filtered to that one rep. Per-rep rows always include everyone.

Item and category figures split each deal's total across its lines: by the line amounts when every line
has one (scaled so they add up to the deal total), otherwise by quantity.

Filtering by brand and/or model (catalog item) keeps only the matching lines' share of each deal, so every
figure (sales, deals, units, reps, clients…) answers "how much of this did we sell". Quota attainment is left
out then, since a brand's sales against the whole quota would mislead.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import models, schemas
from .board import get_quota_unit, line_label, pct_of_quota

DEAL_SIZE_BUCKETS = [  # (label, min dollars, max dollars exclusive)
    ("<$1K", 0, 1_000),
    ("$1–2.5K", 1_000, 2_500),
    ("$2.5–5K", 2_500, 5_000),
    ("$5–10K", 5_000, 10_000),
    ("$10–25K", 10_000, 25_000),
    ("$25K+", 25_000, None),
]
CATEGORY_ORDER = ["mfp", "printer", "software", "accessory", "service", "other"]
TOP_N = 10
# The brand filter value for items without a brand.
NO_BRAND = "(no brand)"
# Series in the month-by-month mix chart; the rest are lumped together.
MIX_SERIES = 5
MIX_REST = "Everything else"


def month_index(year: int, month: int) -> int:
    return year * 12 + month - 1


def month_key(index: int) -> schemas.MonthKey:
    return schemas.MonthKey(year=index // 12, month=index % 12 + 1)


class LineFacts(NamedTuple):
    key: str  # item:<id>, or text:<label> for free text
    label: str
    category: str
    qty: int
    cents: float  # this line's share of the deal total
    brand: str  # NO_BRAND when there isn't one
    item_id: int | None


@dataclass
class DealFacts:
    period_index: int
    rep_id: int
    client_id: int
    total_cents: int
    units: int
    lines: list[LineFacts]


def allocate(deal: models.Deal) -> list[LineFacts]:
    lines = deal.lines or []
    if not lines:
        return [LineFacts("(none)", "(no items)", "other", 0, float(deal.total_cents), NO_BRAND, None)]
    amounts = [line.amount_cents for line in lines]
    if all(a is not None for a in amounts) and sum(amounts) > 0:  # type: ignore[arg-type]
        weights = [float(a) for a in amounts]  # type: ignore[arg-type]
    else:
        weights = [float(max(line.qty, 1)) for line in lines]
    scale = deal.total_cents / sum(weights)
    out = []
    for line, weight in zip(lines, weights):
        label = line_label(line) or "(blank)"
        key = f"item:{line.item_id}" if line.item_id else f"text:{label.strip().lower()}"
        category = line.item.category if line.item else "other"
        brand = line.item.brand if line.item and line.item.brand else NO_BRAND
        out.append(LineFacts(key, label, category, line.qty, weight * scale, brand, line.item_id))
    return out


def only_matching(deal: DealFacts, brand: str | None, item_id: int | None) -> DealFacts | None:
    """The deal cut down to the lines of this brand/item, or None if it has none."""
    lines = [line for line in deal.lines
             if (brand is None or line.brand == brand) and (item_id is None or line.item_id == item_id)]
    if not lines:
        return None
    return DealFacts(deal.period_index, deal.rep_id, deal.client_id, round(sum(line.cents for line in lines)),
                     sum(line.qty for line in lines), lines)


def ranked(rows: dict[str, list], limit: int | None = None) -> list[schemas.RankedRow]:
    """{key: [label, detail, cents, count]} → rows by sales, biggest first."""
    out = sorted(rows.values(), key=lambda r: r[2], reverse=True)[:limit]
    return [schemas.RankedRow(label=r[0], detail=r[1], sales_cents=round(r[2]), count=r[3]) for r in out]


def kpis(
    deals: list[DealFacts], first_seen: dict[int, int], range_start: int, quota_total: float | None,
    unit: schemas.QuotaUnit,
) -> schemas.KpiSet:
    sales = sum(d.total_cents for d in deals)
    units = sum(d.units for d in deals)
    per_client: dict[int, int] = defaultdict(int)
    for d in deals:
        per_client[d.client_id] += 1
    return schemas.KpiSet(
        sales_cents=sales,
        deal_count=len(deals),
        avg_deal_cents=round(sales / len(deals)) if deals else None,
        units=units,
        active_clients=len(per_client),
        new_clients=sum(1 for c in per_client if first_seen.get(c, -1) >= range_start),
        repeat_client_rate=sum(1 for n in per_client.values() if n > 1) / len(per_client) if per_client else None,
        quota_attainment=pct_of_quota(quota_total, sales, units, unit),
    )


def load_deals(db: Session, period_ids: list[int], periods: dict[int, int], brand: str | None, item_id: int | None,
               ) -> tuple[list[DealFacts], dict[int, models.Client]]:
    """Deals in these periods as DealFacts (cut down to the brand/item when filtered), plus their clients."""
    filtered = brand is not None or item_id is not None
    out: list[DealFacts] = []
    clients: dict[int, models.Client] = {}
    for deal in db.scalars(
        select(models.Deal)
        .where(models.Deal.period_id.in_(period_ids))
        .options(selectinload(models.Deal.lines).selectinload(models.DealLine.item), selectinload(models.Deal.client))
    ):
        clients[deal.client_id] = deal.client
        facts = DealFacts(
            period_index=periods[deal.period_id],
            rep_id=deal.rep_id,
            client_id=deal.client_id,
            total_cents=deal.total_cents,
            units=sum(line.qty for line in deal.lines),
            lines=allocate(deal),
        )
        if filtered:
            facts = only_matching(facts, brand, item_id)
        if facts:
            out.append(facts)
    return out, clients


def build_report(db: Session, start: int, end: int, rep_id: int | None,
                 brand: str | None = None, item_id: int | None = None) -> schemas.Report:
    unit = get_quota_unit(db)
    span = end - start + 1
    prior_start = start - span
    load_from = min(prior_start, start - 12)

    periods = {p.id: month_index(p.year, p.month) for p in db.scalars(select(models.Period))}
    existing_months = set(periods.values())
    reps = {r.id: r for r in db.scalars(select(models.Rep))}

    def counted(rid: int) -> bool:
        return rid == rep_id if rep_id is not None else reps[rid].counts_toward_total

    filtered = brand is not None or item_id is not None
    # Quotas: period_index -> rep_id -> quota (none when filtered to a brand/item)
    quotas: dict[int, dict[int, float]] = defaultdict(dict)
    for pr in ([] if filtered else db.scalars(select(models.PeriodRep))):
        if pr.quota is not None:
            quotas[periods[pr.period_id]][pr.rep_id] = pr.quota

    def team_quota(months: range) -> float | None:
        values = [q for m in months for rid, q in quotas.get(m, {}).items() if counted(rid)]
        return sum(values) if values else None

    # First month each client ever bought (for "new clients").
    first_seen = {
        client_id: first
        for client_id, first in db.execute(
            select(models.Deal.client_id, func.min(models.Period.year * 12 + models.Period.month - 1))
            .join(models.Period, models.Deal.period_id == models.Period.id)
            .group_by(models.Deal.client_id)
        )
    }

    window_ids = [pid for pid, idx in periods.items() if load_from <= idx <= end]
    all_deals, clients = load_deals(db, window_ids, periods, brand, item_id)

    def in_range(lo: int, hi: int, team: bool = True) -> list[DealFacts]:
        return [d for d in all_deals if lo <= d.period_index <= hi and (not team or counted(d.rep_id))]

    current = in_range(start, end)
    months = list(range(start, end + 1))

    # Month by month, with the same month a year earlier.
    by_month: dict[int, list[DealFacts]] = defaultdict(list)
    for d in in_range(start - 12, end):
        by_month[d.period_index].append(d)
    monthly = []
    for m in months:
        ds = by_month.get(m, [])
        sales = sum(d.total_cents for d in ds)
        prior = m - 12
        monthly.append(schemas.MonthPoint(
            **month_key(m).model_dump(),
            sales_cents=sales,
            deal_count=len(ds),
            prior_year_sales_cents=sum(d.total_cents for d in by_month.get(prior, [])) if prior in existing_months else None,
            attainment=pct_of_quota(team_quota(range(m, m + 1)), sales, sum(d.units for d in ds), unit),
        ))

    # Per rep (everyone who had a deal or a quota in the range).
    rep_rows = []
    rep_deals: dict[int, list[DealFacts]] = defaultdict(list)
    for d in in_range(start, end, team=False):
        rep_deals[d.rep_id].append(d)
    rep_ids = set(rep_deals) | {rid for m in months for rid in quotas.get(m, {})}
    if rep_id is not None:
        rep_ids &= {rep_id}
    for rid in rep_ids:
        ds = rep_deals.get(rid, [])
        sales = sum(d.total_cents for d in ds)
        rep_quota = [quotas.get(m, {}).get(rid) for m in months]
        monthly_att = []
        for m, q in zip(months, rep_quota):
            md = [d for d in ds if d.period_index == m]
            monthly_att.append(pct_of_quota(q, sum(d.total_cents for d in md), sum(d.units for d in md), unit))
        quota_sum = sum(q for q in rep_quota if q is not None) or None
        rep_rows.append(schemas.RepRow(
            rep_id=rid,
            name=reps[rid].name,
            sales_cents=sales,
            deal_count=len(ds),
            avg_deal_cents=round(sales / len(ds)) if ds else None,
            attainment=pct_of_quota(quota_sum, sales, sum(d.units for d in ds), unit),
            monthly_attainment=monthly_att,
        ))
    rep_rows.sort(key=lambda r: r.sales_cents, reverse=True)

    # Categories by month; items and brands overall.
    cat_month: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    items: dict[str, list] = {}
    brands: dict[str, list] = {}
    for d in current:
        for line in d.lines:
            cat_month[d.period_index][line.category] += line.cents
            for rows, key, label, detail in ((items, line.key, line.label, line.category),
                                             (brands, line.brand, line.brand, None)):
                row = rows.setdefault(key, [label, detail, 0.0, 0])
                row[2] += line.cents
                row[3] += line.qty
    used = {c for per in cat_month.values() for c in per}
    categories = [c for c in CATEGORY_ORDER if c in used]
    category_monthly = [
        schemas.CategoryMonth(**month_key(m).model_dump(),
                              sales_cents={c: round(cat_month.get(m, {}).get(c, 0.0)) for c in categories})
        for m in months
    ]

    # Month-by-month mix: by brand, or by model once a brand is picked.
    mix_by = "model" if brand is not None else "brand"
    mix_key = (lambda line: line.label) if mix_by == "model" else (lambda line: line.brand)
    mix_month: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    mix_total: dict[str, float] = defaultdict(float)
    for d in current:
        for line in d.lines:
            mix_month[d.period_index][mix_key(line)] += line.cents
            mix_total[mix_key(line)] += line.cents
    ranked_mix = sorted(mix_total, key=lambda k: mix_total[k], reverse=True)
    mix_series = ranked_mix[:MIX_SERIES]
    if len(ranked_mix) > MIX_SERIES:
        mix_series.append(MIX_REST)

    def mix_values(m: int) -> dict[str, int]:
        per = mix_month.get(m, {})
        out = {s: round(per.get(s, 0.0)) for s in mix_series if s != MIX_REST}
        if MIX_REST in mix_series:
            out[MIX_REST] = round(sum(v for k, v in per.items() if k not in out))
        return out

    client_sales: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for d in current:
        client_sales[d.client_id][0] += d.total_cents
        client_sales[d.client_id][1] += 1
    top_clients = sorted(client_sales.items(), key=lambda kv: kv[1][0], reverse=True)[:TOP_N]
    total_sales = sum(d.total_cents for d in current)

    buckets = []
    for label, lo, hi in DEAL_SIZE_BUCKETS:
        ds = [d for d in current if d.total_cents >= lo * 100 and (hi is None or d.total_cents < hi * 100)]
        buckets.append(schemas.Bucket(label=label, min_cents=lo * 100, max_cents=hi * 100 if hi else None,
                                      deal_count=len(ds), sales_cents=sum(d.total_cents for d in ds)))

    return schemas.Report(
        start=month_key(start),
        end=month_key(end),
        months=[month_key(m) for m in months],
        quota_unit=unit,
        kpis=kpis(current, first_seen, start, team_quota(range(start, end + 1)), unit),
        prior_kpis=kpis(in_range(prior_start, start - 1), first_seen, prior_start, team_quota(range(prior_start, start)), unit),
        monthly=monthly,
        reps=rep_rows,
        categories=categories,
        category_monthly=category_monthly,
        items=ranked(items),
        brands=ranked(brands),
        mix_by=mix_by,
        mix_series=mix_series,
        mix_monthly=[schemas.CategoryMonth(**month_key(m).model_dump(), sales_cents=mix_values(m)) for m in months],
        filtered=filtered,
        top_clients=[
            schemas.RankedRow(label=clients[cid].name, detail=clients[cid].location, sales_cents=s, count=n)
            for cid, (s, n) in top_clients
        ],
        top_clients_share=sum(s for _, (s, _) in top_clients) / total_sales if total_sales else None,
        deal_sizes=buckets,
    )
