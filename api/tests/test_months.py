from datetime import datetime

from app import models


def make_month(session, year, month, reps, locked=False):
    period = models.Period(year=year, month=month, locked_at=datetime(year, month, 28) if locked else None)
    session.add(period)
    session.flush()
    period.period_reps = [models.PeriodRep(rep=r, display_order=i, quota=q) for i, (r, q) in enumerate(reps)]
    session.commit()
    return period


def test_start_next_month_copies_reps_and_quotas(admin_client, session):
    alex, bob, gone, house = (models.Rep(name=n) for n in ("ALEX", "BOB", "GONE", "HOUSE"))
    gone.active = False
    session.add_all([alex, bob, gone, house])
    make_month(session, 2026, 11, [(alex, 44)])
    make_month(session, 2026, 12, [(bob, 30), (gone, 10), (alex, 44), (house, None)])

    res = admin_client.post("/api/periods")
    assert res.status_code == 201
    new = res.json()
    assert (new["year"], new["month"]) == (2027, 1)  # rolls over the year
    reps = admin_client.get(f"/api/periods/{new['id']}/reps").json()
    assert reps == [{"rep_id": bob.id, "name": "BOB", "quota": 30},
                    {"rep_id": alex.id, "name": "ALEX", "quota": 44},
                    {"rep_id": house.id, "name": "HOUSE", "quota": None}]
    assert admin_client.post("/api/periods", json={"year": 2027, "month": 1}).status_code == 409


def test_start_specific_month_uses_previous_month_as_template(admin_client, session):
    a, b = models.Rep(name="A"), models.Rep(name="B")
    session.add_all([a, b])
    make_month(session, 2026, 1, [(a, 1)])
    make_month(session, 2026, 5, [(b, 5)])
    new = admin_client.post("/api/periods", json={"year": 2026, "month": 3}).json()
    assert [r["name"] for r in admin_client.get(f"/api/periods/{new['id']}/reps").json()] == ["A"]
    assert admin_client.post("/api/periods", json={"year": 2026}).status_code == 422


def test_first_month_ever(admin_client):
    res = admin_client.post("/api/periods")
    assert res.status_code == 201


def test_lock_unlock_and_current(admin_client, session):
    aug = make_month(session, 2026, 8, [])
    sep = make_month(session, 2026, 9, [])
    assert admin_client.get("/api/periods/current").json()["id"] == sep.id

    res = admin_client.post(f"/api/periods/{sep.id}/lock")
    assert res.json()["locked_at"] is not None
    assert admin_client.get("/api/periods/current").json()["id"] == aug.id
    summary = {s["id"]: s for s in admin_client.get("/api/periods/summary").json()}
    assert summary[sep.id]["locked_by_name"] == "admin"

    assert admin_client.post(f"/api/periods/{sep.id}/unlock").json()["locked_at"] is None
    assert admin_client.get("/api/periods/current").json()["id"] == sep.id


def test_month_admin_only(user_client, session):
    sep = make_month(session, 2026, 9, [])
    assert user_client.post("/api/periods").status_code == 403
    assert user_client.post(f"/api/periods/{sep.id}/lock").status_code == 403
    assert user_client.post(f"/api/periods/{sep.id}/unlock").status_code == 403
    assert user_client.get("/api/periods/summary").status_code == 200


def test_summary_counts(admin_client, session):
    alex, house = models.Rep(name="ALEX"), models.Rep(name="HOUSE", counts_toward_total=False)
    client = models.Client(name="C")
    sep = make_month(session, 2026, 9, [(alex, 44), (house, None)])
    session.add_all([
        models.Deal(period_id=sep.id, rep=alex, client=client, total_cents=100),
        models.Deal(period_id=sep.id, rep=alex, client=client, total_cents=250),
        models.Deal(period_id=sep.id, rep=house, client=client, total_cents=999),
    ])
    session.commit()
    s = admin_client.get("/api/periods/summary").json()[0]
    assert (s["rep_count"], s["deal_count"], s["total_sales_cents"]) == (2, 3, 350)
