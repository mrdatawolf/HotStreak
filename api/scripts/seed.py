"""Fill the database with fake but realistic history for development.

Usage (from api/):  python -m scripts.seed [--reset]
(--reset replaces the sales data but keeps users, settings and name fixes.)

Creates reps, clients, an item catalog, and deals for every month from
02/2023 through the current month. Past months are locked, like the sheet tabs.
All names and clients are invented.
"""

import argparse
import random
import sys
from datetime import date, datetime

from sqlalchemy import delete, func, select

from app import models
from app.db import Base, SessionLocal

FIRST_MONTH = (2023, 2)

# (name, quota in $K); HOUSE has no quota.
REPS = [
    ("ALEX", 44), ("BRENDA", 44), ("CARLOS", 44), ("DANA", 30),
    ("ELI", 10), ("FIONA", 20), ("GREG", 10), ("HANA", 10), ("HOUSE", None),
]

# (brand, model, category, min unit price, max unit price)
ITEMS = [
    ("Sharp", "BP-70M75", "mfp", 12000, 15500),
    ("Sharp", "BP-71M45", "mfp", 9500, 13500),
    ("Sharp", "BP-50C26", "mfp", 6000, 9000),
    ("Sharp", "MX-B468F", "mfp", 2600, 3600),
    ("Lexmark", "XC2335", "mfp", 1200, 1800),
    ("Lexmark", "XC4342", "mfp", 2500, 3600),
    ("Lexmark", "XM3250", "mfp", 1600, 2200),
    ("Lexmark", "MX532adwe", "mfp", 900, 1400),
    ("Lexmark", "MS631dw", "printer", 450, 900),
    ("Lexmark", "CS531dw", "printer", 500, 950),
    ("PaperCut", "MF", "software", 2000, 20000),
    (None, "Printer Stand", "accessory", 200, 600),
    ("Sharp", "Finisher", "accessory", 800, 1600),
    (None, "Managed Print Service", "service", 3000, 12000),
]

CLIENTS = [
    "Pine Ridge School", "Harbor Light Credit Union", "Elk River Tribal Office", "Mill Creek Clinic",
    "Fogline Brewing", "Six Rivers Title", "Bayview Dental", "North Coast Surveyors", "Trinity Feed & Supply",
    "Lighthouse Church", "Cedar Grove Accounting", "Ferndale Chamber", "Sequoia Law Group",
    "Blue Heron Realty", "Madrone Insurance", "Salmon Creek Water District", "Arcadia Pediatrics",
    "Headwaters Library", "Old Town Hotel", "Kingfisher Auto", "Shoreline Veterinary", "Fir Street Pharmacy",
    "Summit Engineering", "Willow Valley Winery", "Driftwood Property Mgmt", "Glacier County Office of Ed",
]
# Clients with several branches, each sold to separately.
MULTI_SITE = {"Coastal Valley Bank": ["Eureka", "Arcata", "Fortuna"], "Redcrest Health": ["Main", "Annex"]}

FLAGS = [("Highlight", "#22c55e")]


def months_through(end: tuple[int, int]):
    year, month = FIRST_MONTH
    while (year, month) <= end:
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


# Accounts, sign-ins, settings (like the TV board key) and sheet name fixes survive a reseed.
KEEP_ON_RESET = {"users", "sessions", "settings", "name_fixes"}


def reset(session) -> None:
    for table in reversed(Base.metadata.sorted_tables):
        if table.name not in KEEP_ON_RESET:
            session.execute(delete(table))


def random_line(rng: random.Random, items: list[models.Item], prices: dict[int, tuple[int, int]]):
    item = rng.choice(items)
    low, high = prices[item.id]
    qty = rng.choices([1, 2, 3], weights=[80, 15, 5])[0] if item.category in ("mfp", "printer") else 1
    unit_cents = rng.randint(low * 100, high * 100)
    return models.DealLine(item=item, qty=qty, amount_cents=unit_cents * qty)


def seed(session, rng: random.Random, today: date) -> dict[str, int]:
    reps = [models.Rep(name=name, counts_toward_total=True) for name, _ in REPS]
    quotas = {name: quota for name, quota in REPS}
    items = [models.Item(brand=b, model=m, category=c) for b, m, c, _, _ in ITEMS]
    clients = [models.Client(name=n) for n in CLIENTS] + [
        models.Client(name=n, location=loc) for n, locs in MULTI_SITE.items() for loc in locs
    ]
    flags = [models.Flag(name=n, color=c) for n, c in FLAGS]
    session.add_all([*reps, *items, *clients, *flags])
    session.merge(models.Setting(key="quota_unit", value="usd_thousands"))
    session.flush()

    prices = {item.id: (low, high) for item, (_, _, _, low, high) in zip(items, ITEMS)}
    deal_count = 0
    current = (today.year, today.month)

    for year, month in months_through(current):
        period = models.Period(
            year=year, month=month, locked_at=None if (year, month) == current else datetime(year, month, 28)
        )
        session.add(period)
        for order, rep in enumerate(reps):
            period.period_reps.append(models.PeriodRep(rep=rep, display_order=order, quota=quotas[rep.name]))
        session.flush()

        last_day = today.day if (year, month) == current else 28
        for rep in reps:
            quota = quotas[rep.name]
            # Bigger quotas close more deals; HOUSE gets an occasional one.
            expected = quota / 12 if quota else 0.6
            for _ in range(min(8, max(0, round(rng.gauss(expected, expected / 2 + 0.5))))):
                lines = [random_line(rng, items, prices)]
                if rng.random() < 0.1:
                    lines.append(random_line(rng, items, prices))
                if rep.name == "HOUSE" and rng.random() < 0.5:
                    lines = [models.DealLine(description="Various", qty=1, amount_cents=rng.randint(200_000, 2_000_000))]
                deal = models.Deal(
                    period_id=period.id,
                    rep=rep,
                    client=rng.choice(clients),
                    deal_date=date(year, month, rng.randint(1, last_day)),
                    total_cents=sum(line.amount_cents for line in lines),
                    lines=lines,
                    flags=[flags[0]] if rng.random() < 0.1 else [],
                )
                session.add(deal)
                deal_count += 1

    return {"reps": len(reps), "items": len(items), "clients": len(clients), "deals": deal_count}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="delete all existing data first")
    parser.add_argument("--seed", type=int, default=2026, help="random seed")
    args = parser.parse_args()

    with SessionLocal() as session:
        if session.scalar(select(func.count()).select_from(models.Rep)) and not args.reset:
            sys.exit("Database already has data; pass --reset to replace it.")
        if args.reset:
            reset(session)
        counts = seed(session, random.Random(args.seed), date.today())
        session.commit()
    print("Seeded: " + ", ".join(f"{v} {k}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
