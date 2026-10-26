from datetime import datetime

import pytest

from app import models


@pytest.fixture
def data(session):
    """Aug and Sep 2026 (plus Sep 2025 for year-over-year), two reps + HOUSE (excluded from team totals)."""
    alex, bob = models.Rep(name="ALEX"), models.Rep(name="BOB")
    house = models.Rep(name="HOUSE", counts_toward_total=False)
    acme, beta = models.Client(name="Acme"), models.Client(name="Beta", location="Eureka")
    mfp = models.Item(brand="Sharp", model="BP-70M75", category="mfp")
    sw = models.Item(brand="PaperCut", model="MF", category="software")
    session.add_all([alex, bob, house, acme, beta, mfp, sw])
    months = {}
    for y, m in [(2025, 9), (2026, 8), (2026, 9)]:
        p = models.Period(year=y, month=m, locked_at=None if (y, m) == (2026, 9) else datetime(y, m, 28))
        session.add(p)
        session.flush()
        p.period_reps = [models.PeriodRep(rep=alex, display_order=0, quota=10),
                         models.PeriodRep(rep=bob, display_order=1, quota=20),
                         models.PeriodRep(rep=house, display_order=2, quota=None)]
        months[(y, m)] = p

    def deal(ym, rep, client, total, lines):
        session.add(models.Deal(period_id=months[ym].id, rep=rep, client=client, total_cents=total, lines=lines))

    deal((2025, 9), alex, acme, 500_000, [models.DealLine(item=mfp, qty=1, amount_cents=500_000)])
    deal((2026, 8), alex, acme, 1_000_000, [models.DealLine(item=mfp, qty=1, amount_cents=1_000_000)])
    # Line amounts 3:1 scaled up to a hand-typed total of 2,000,000.
    deal((2026, 9), alex, beta, 2_000_000, [models.DealLine(item=mfp, qty=2, amount_cents=900_000),
                                            models.DealLine(item=sw, qty=1, amount_cents=300_000)])
    # No line amounts: split by quantity.
    deal((2026, 9), bob, acme, 300_000, [models.DealLine(description="Various", qty=1),
                                         models.DealLine(item=sw, qty=2)])
    deal((2026, 9), house, acme, 999_900, [models.DealLine(description="Various", qty=1, amount_cents=999_900)])
    session.commit()
    return {"alex": alex, "bob": bob, "house": house}


def test_report_numbers(user_client, data):
    r = user_client.get("/api/reports?start=2026-08&end=2026-09").json()

    k = r["kpis"]
    assert k["sales_cents"] == 3_300_000  # HOUSE left out
    assert k["deal_count"] == 3
    assert k["avg_deal_cents"] == 1_100_000
    assert k["units"] == 1 + 3 + 3
    assert k["active_clients"] == 2
    assert k["new_clients"] == 1  # Beta; Acme first bought in 2025
    assert k["repeat_client_rate"] == 0.5
    # $33,000 against quota 30 + 30 ($60K)
    assert k["quota_attainment"] == pytest.approx(33 / 60)

    assert r["prior_kpis"]["sales_cents"] == 0  # Jun–Jul 2026 don't exist
    sep = r["monthly"][1]
    assert (sep["sales_cents"], sep["prior_year_sales_cents"]) == (2_300_000, 500_000)
    assert r["monthly"][0]["prior_year_sales_cents"] is None  # Aug 2025 not in the tracker

    reps = {x["name"]: x for x in r["reps"]}
    assert reps["HOUSE"]["sales_cents"] == 999_900 and reps["HOUSE"]["attainment"] is None
    assert reps["ALEX"]["monthly_attainment"] == [pytest.approx(1.0), pytest.approx(2.0)]
    assert [x["name"] for x in r["reps"]][0] == "ALEX"  # sorted by sales

    assert r["categories"] == ["mfp", "software", "other"]
    sep_cats = r["category_monthly"][1]["sales_cents"]
    assert sep_cats == {"mfp": 1_500_000, "software": 500_000 + 200_000, "other": 100_000}

    items = {i["label"]: i for i in r["items"]}
    assert items["Sharp BP-70M75"]["count"] == 3 and items["Sharp BP-70M75"]["sales_cents"] == 2_500_000
    assert items["Various"]["detail"] == "other"

    assert r["top_clients"][0] == {"label": "Beta", "detail": "Eureka", "sales_cents": 2_000_000, "count": 1}
    assert r["top_clients_share"] == 1.0
    sizes = {b["label"]: b["deal_count"] for b in r["deal_sizes"]}
    assert sizes["$10–25K"] == 2 and sizes["$2.5–5K"] == 1 and sizes["$25K+"] == 0


def test_rep_filter_includes_house_when_asked(user_client, data):
    r = user_client.get(f"/api/reports?start=2026-09&end=2026-09&rep_id={data['house'].id}").json()
    assert r["kpis"]["sales_cents"] == 999_900
    assert [x["name"] for x in r["reps"]] == ["HOUSE"]


def test_default_range_is_12_months_to_current(user_client, data):
    r = user_client.get("/api/reports").json()
    assert (r["end"], r["start"]) == ({"year": 2026, "month": 9}, {"year": 2025, "month": 10})
    assert len(r["monthly"]) == 12


@pytest.mark.parametrize("query", ["start=2026-9", "start=2026-13", "start=2026-09&end=2026-08",
                                   "start=2000-01&end=2026-09", "rep_id=999"])
def test_bad_params(user_client, data, query):
    assert user_client.get(f"/api/reports?{query}").status_code == 422


def test_reports_need_sign_in(client, data):
    assert client.get("/api/reports").status_code == 401


def test_brand_breakdown(user_client, data):
    r = user_client.get("/api/reports?start=2026-08&end=2026-09").json()
    brands = {b["label"]: (b["sales_cents"], b["count"]) for b in r["brands"]}
    assert brands == {"Sharp": (2_500_000, 3), "PaperCut": (700_000, 3), "(no brand)": (100_000, 1)}
    assert r["mix_by"] == "brand" and r["mix_series"] == ["Sharp", "PaperCut", "(no brand)"]
    assert r["mix_monthly"][1]["sales_cents"] == {"Sharp": 1_500_000, "PaperCut": 700_000, "(no brand)": 100_000}
    assert r["filtered"] is False


def test_filter_by_brand(user_client, data):
    r = user_client.get("/api/reports", params={"start": "2026-08", "end": "2026-09", "brand": "PaperCut"}).json()
    k = r["kpis"]
    # PaperCut's share: 500,000 of Alex's Sep deal + 200,000 of Bob's.
    assert (k["sales_cents"], k["deal_count"], k["units"]) == (700_000, 2, 3)
    assert k["quota_attainment"] is None and r["filtered"] is True
    assert all(x["attainment"] is None for x in r["reps"])
    assert [i["label"] for i in r["items"]] == ["PaperCut MF"]
    # With a brand picked, the mix goes by model.
    assert r["mix_by"] == "model" and r["mix_series"] == ["PaperCut MF"]
    assert {x["name"]: x["sales_cents"] for x in r["reps"]} == {"ALEX": 500_000, "BOB": 200_000}


def test_filter_by_item_and_no_brand(user_client, data, session):
    mfp = session.query(models.Item).filter_by(model="BP-70M75").one()
    r = user_client.get("/api/reports", params={"start": "2026-08", "end": "2026-09", "item_id": mfp.id}).json()
    assert r["kpis"]["sales_cents"] == 2_500_000 and r["kpis"]["deal_count"] == 2
    r = user_client.get("/api/reports", params={"start": "2026-08", "end": "2026-09", "brand": "(no brand)"}).json()
    assert r["kpis"]["sales_cents"] == 100_000  # HOUSE's "Various" isn't in the team total
    assert user_client.get("/api/reports", params={"item_id": 9999}).status_code == 422
