from datetime import datetime

import pytest

from app import models


@pytest.fixture
def history(session):
    """Jan 2024 – Feb 2026 finished, Mar 2026 open. ALEX sells $1,000 a month in 2024 and $2,000 a month after
    (quota 10 = $10K); HOUSE (left out of team totals) sells $9,999 in Feb 2026; Mar 2026 has $500 so far."""
    alex, house = models.Rep(name="ALEX"), models.Rep(name="HOUSE", counts_toward_total=False)
    acme = models.Client(name="Acme")
    sharp = models.Item(brand="Sharp", model="BP-70M75", category="mfp")
    session.add_all([alex, house, acme, sharp])
    for i in range(2024 * 12, 2026 * 12 + 3):
        y, m = divmod(i, 12)
        p = models.Period(year=y, month=m + 1, locked_at=None if i == 2026 * 12 + 2 else datetime(y, m + 1, 28))
        p.period_reps = [models.PeriodRep(rep=alex, quota=10), models.PeriodRep(rep=house, quota=None)]
        session.add(p)
        session.flush()
        total = 50_000 if i == 2026 * 12 + 2 else 100_000 if y == 2024 else 200_000
        session.add(models.Deal(period_id=p.id, rep=alex, client=acme, total_cents=total,
                                lines=[models.DealLine(item=sharp, qty=1, amount_cents=total)]))
        if i == 2026 * 12 + 1:
            session.add(models.Deal(period_id=p.id, rep=house, client=acme, total_cents=999_900, lines=[]))
    session.commit()
    return {"alex": alex, "house": house}


def test_trend_figures(user_client, history):
    t = user_client.get("/api/reports/trends").json()
    assert (t["current"], t["last_complete"]) == ({"year": 2026, "month": 3}, {"year": 2026, "month": 2})

    months = {(m["year"], m["month"]): m for m in t["months"]}
    assert months[(2026, 3)]["complete"] is False and months[(2026, 3)]["avg3_cents"] is None
    assert months[(2024, 12)]["ttm_cents"] == 1_200_000 and months[(2024, 11)]["ttm_cents"] is None
    assert months[(2026, 2)]["ttm_cents"] == 2_400_000  # HOUSE left out
    assert months[(2025, 2)]["avg3_cents"] == round((100_000 + 200_000 + 200_000) / 3)

    q = {(x["year"], x["quarter"]): x for x in t["quarters"]}
    assert q[(2025, 4)] == {"year": 2025, "quarter": 4, "sales_cents": 600_000, "deal_count": 3, "complete": True,
                            "prior_quarter_sales_cents": 600_000, "prior_year_sales_cents": 300_000}
    assert q[(2026, 1)]["complete"] is False

    assert [(y["year"], y["sales_cents"], y["months"]) for y in t["years"]] == [
        (2024, 1_200_000, 12), (2025, 2_400_000, 12), (2026, 400_000, 2)]
    jan = next(c for c in t["calendar"] if c["month"] == 1)
    assert (jan["avg_sales_cents"], jan["years"]) == (round((100_000 + 200_000 + 200_000) / 3), 3)

    a = t["averages"]
    assert (a["monthly_3_cents"], a["monthly_12_cents"], a["deals_per_month_12"], a["avg_deal_12_cents"]) == (
        200_000, 200_000, 1, 200_000)
    assert t["ytd"] == {"through": {"year": 2026, "month": 2}, "sales_cents": 400_000, "deal_count": 2,
                        "prior_sales_cents": 400_000, "prior_deal_count": 2}


def test_forecasts(user_client, history):
    f = {x["label"]: x for x in user_client.get("/api/reports/trends").json()["forecasts"]}
    assert list(f) == ["This quarter (Q1 2026)", "Next quarter (Q2 2026)", "This year (2026)"]

    quarter = f["This quarter (Q1 2026)"]
    # Jan + Feb, plus March at the 12-month average ($2,000; more than the $500 so far).
    assert (quarter["actual_cents"], quarter["estimate_cents"], quarter["months_actual"]) == (400_000, 600_000, 2)
    assert quarter["last_year_cents"] == 600_000
    assert quarter["quota_cents"] == 3 * 1_000_000 and quarter["includes_open_month"] is True
    assert f["Next quarter (Q2 2026)"]["includes_open_month"] is False
    # The range comes from past misses, and never drops below what's already in.
    assert quarter["typical_miss"] > 0 and 450_000 <= quarter["low_cents"] < 600_000 < quarter["high_cents"]

    year = f["This year (2026)"]
    assert (year["estimate_cents"], year["last_year_cents"], year["quota_cents"]) == (2_400_000, 2_400_000, 12_000_000)


def test_growth(user_client, history):
    t = user_client.get("/api/reports/trends").json()
    reps = {r["label"]: r for r in t["rep_growth"]}
    # Mar 2025–Feb 2026 vs Mar 2024–Feb 2025.
    assert (reps["ALEX"]["sales_cents"], reps["ALEX"]["prior_sales_cents"]) == (2_400_000, 1_400_000)
    assert reps["ALEX"]["change"] == pytest.approx(1 / 1.4)
    assert reps["HOUSE"]["change"] is None  # nothing the year before
    assert [b["label"] for b in t["brand_growth"]] == ["Sharp"]  # HOUSE's lineless deal isn't team sales


def test_filters(user_client, history):
    t = user_client.get("/api/reports/trends", params={"rep_id": history["house"].id}).json()
    assert t["averages"]["monthly_12_cents"] == round(999_900 / 12)
    assert [r["label"] for r in t["rep_growth"]] == ["HOUSE"]

    t = user_client.get("/api/reports/trends", params={"brand": "Lexmark"}).json()
    assert t["filtered"] is True and t["averages"]["monthly_12_cents"] == 0
    assert all(f["quota_cents"] is None and f["low_cents"] is None for f in t["forecasts"])


def test_short_history(user_client, session):
    for m in (1, 2):
        session.add(models.Period(year=2026, month=m, locked_at=datetime(2026, m, 28) if m == 1 else None))
    session.commit()
    t = user_client.get("/api/reports/trends").json()
    assert t["forecasts"] == [] and t["rep_growth"] == [] and t["averages"]["monthly_12_cents"] is None


def test_trends_errors(client, user_client, session):
    assert user_client.get("/api/reports/trends").status_code == 404  # no months yet
    assert user_client.get("/api/reports/trends", params={"rep_id": 999}).status_code in (404, 422)
    client.headers.pop("Authorization")
    assert client.get("/api/reports/trends").status_code == 401
