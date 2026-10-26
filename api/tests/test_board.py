from datetime import date, datetime

from app import models


def make_deal(period, rep, client, cents, lines=None, deal_date=None):
    return models.Deal(
        period_id=period.id,
        rep=rep,
        client=client,
        total_cents=cents,
        deal_date=deal_date,
        lines=lines or [models.DealLine(description="Item", qty=1, amount_cents=cents)],
    )


def setup_month(session):
    period = models.Period(year=2026, month=9)
    alex = models.Rep(name="ALEX")
    house = models.Rep(name="HOUSE")
    client = models.Client(name="Pine Ridge School")
    session.add_all([period, alex, house, client])
    session.flush()
    period.period_reps += [
        models.PeriodRep(rep=alex, display_order=0, quota=44),
        models.PeriodRep(rep=house, display_order=1, quota=None),
    ]
    session.flush()
    return period, alex, house, client


def test_board_sums_match_sheet(admin_client, session):
    # Numbers from rep 1 in the client's screenshot.
    period, alex, house, acme = setup_month(session)
    session.add_all([
        make_deal(period, alex, acme, 2_886_100),
        make_deal(period, alex, acme, 1_269_947),
        make_deal(period, house, acme, 1_000_000),
    ])
    session.commit()

    board = admin_client.get(f"/api/periods/{period.id}/board").json()

    assert [r["name"] for r in board["reps"]] == ["ALEX", "HOUSE"]
    alex_row, house_row = board["reps"]
    assert alex_row["sales_cents"] == 4_156_047
    assert round(alex_row["pct_of_quota"], 4) == round(41_560.47 / 44_000, 4)
    assert house_row["quota"] is None and house_row["pct_of_quota"] is None
    assert board["total_sales_cents"] == 5_156_047


def test_rep_excluded_from_total(admin_client, session):
    period, alex, house, acme = setup_month(session)
    house.counts_toward_total = False
    session.add_all([make_deal(period, alex, acme, 500), make_deal(period, house, acme, 700)])
    session.commit()

    board = admin_client.get(f"/api/periods/{period.id}/board").json()

    assert board["total_sales_cents"] == 500
    assert board["reps"][1]["sales_cents"] == 700


def test_deal_for_rep_missing_from_month_still_shown(admin_client, session):
    period, _, _, acme = setup_month(session)
    stray = models.Rep(name="NEWBIE")
    session.add(make_deal(period, stray, acme, 1234))
    session.commit()

    board = admin_client.get(f"/api/periods/{period.id}/board").json()

    assert board["reps"][-1]["name"] == "NEWBIE"
    assert board["total_sales_cents"] == 1234


def test_deal_details_and_order(admin_client, session):
    period, alex, _, acme = setup_month(session)
    item = models.Item(brand="Sharp", model="BP-70M75", category="mfp")
    flag = models.Flag(name="Highlight", color="#22c55e")
    acme.location = "Eureka"
    late = make_deal(period, alex, acme, 100, deal_date=date(2026, 9, 20))
    early = make_deal(
        period, alex, acme, 200,
        lines=[models.DealLine(item=item, qty=2, amount_cents=200)], deal_date=date(2026, 9, 2),
    )
    early.flags = [flag]
    session.add_all([late, early])
    session.commit()

    deals = admin_client.get(f"/api/periods/{period.id}/board").json()["reps"][0]["deals"]

    assert [d["total_cents"] for d in deals] == [200, 100]
    assert deals[0]["lines"] == [{"label": "Sharp BP-70M75", "qty": 2, "category": "mfp"}]
    assert deals[0]["flags"][0]["name"] == "Highlight"
    assert deals[0]["client_location"] == "Eureka"


def test_quota_in_units(admin_client, session):
    period, alex, _, acme = setup_month(session)
    session.add(models.Setting(key="quota_unit", value="units"))
    session.add(make_deal(period, alex, acme, 999, lines=[models.DealLine(description="x", qty=11)]))
    session.commit()

    row = admin_client.get(f"/api/periods/{period.id}/board").json()["reps"][0]

    assert row["units"] == 11
    assert row["pct_of_quota"] == 11 / 44


def test_current_period_prefers_newest_unlocked(admin_client, session):
    session.add_all([
        models.Period(year=2026, month=8),
        models.Period(year=2026, month=9, locked_at=datetime(2026, 9, 30)),
        models.Period(year=2026, month=7),
    ])
    session.commit()

    assert admin_client.get("/api/periods/current").json()["month"] == 8
    assert [p["month"] for p in admin_client.get("/api/periods").json()] == [9, 8, 7]


def test_missing_period(admin_client):
    assert admin_client.get("/api/periods/current").status_code == 404
    assert admin_client.get("/api/periods/99/board").status_code == 404
