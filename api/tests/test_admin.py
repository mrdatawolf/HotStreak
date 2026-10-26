from datetime import datetime

from app import models

from .conftest import PASSWORD, make_user, sign_in


def test_create_user_and_duplicate_email(admin_client):
    body = {"name": "Pat", "email": "Pat@Example.com", "role": "user", "password": "long enough pw"}
    res = admin_client.post("/api/users", json=body)
    assert res.status_code == 201
    assert res.json()["email"] == "pat@example.com"
    assert "password_hash" not in res.json()
    assert admin_client.post("/api/users", json=body).status_code == 409


def test_user_validation(admin_client):
    assert admin_client.post("/api/users", json={"name": "Pat", "email": "pat@example.com",
                                                 "password": "short"}).status_code == 422
    assert admin_client.post("/api/users", json={"name": "Pat", "email": "not-an-email",
                                                 "password": "long enough pw"}).status_code == 422


def test_cannot_remove_last_admin(admin_client, session):
    admin = session.query(models.User).filter_by(email="admin@example.com").one()
    assert admin_client.patch(f"/api/users/{admin.id}", json={"role": "user"}).status_code == 409
    assert admin_client.patch(f"/api/users/{admin.id}", json={"active": False}).status_code == 409
    assert admin_client.delete(f"/api/users/{admin.id}").status_code == 409

    make_user(session, "second@example.com", role="admin")
    assert admin_client.patch(f"/api/users/{admin.id}", json={"role": "user"}).status_code == 200


def test_deactivate_signs_user_out(admin_client, client, session):
    user = make_user(session, "pat@example.com")
    pat = client.__class__(client.app)
    sign_in(pat, "pat@example.com")
    assert admin_client.patch(f"/api/users/{user.id}", json={"active": False}).status_code == 200
    assert pat.get("/api/auth/me").status_code == 401


def test_admin_reset_password(admin_client, client, session):
    user = make_user(session, "pat@example.com")
    assert admin_client.post(f"/api/users/{user.id}/password", json={"password": "brand new pass"}).status_code == 204
    other = client.__class__(client.app)
    assert other.post("/api/auth/login", json={"username": "pat@example.com", "password": PASSWORD}).status_code == 401
    sign_in(other, "pat@example.com", "brand new pass")


def test_user_with_history_cannot_be_deleted(admin_client, session):
    user = make_user(session, "pat@example.com")
    session.add(models.Period(year=2026, month=8, locked_at=datetime(2026, 8, 31), locked_by_id=user.id))
    session.commit()
    assert admin_client.delete(f"/api/users/{user.id}").status_code == 409


def test_rep_crud(admin_client, session):
    rep = admin_client.post("/api/reps", json={"name": "ALEX"}).json()
    assert admin_client.post("/api/reps", json={"name": "ALEX"}).status_code == 409
    res = admin_client.patch(f"/api/reps/{rep['id']}", json={"counts_toward_total": False, "active": False})
    assert res.json() == {"id": rep["id"], "name": "ALEX", "active": False, "counts_toward_total": False}
    assert admin_client.delete(f"/api/reps/{rep['id']}").status_code == 204


def test_in_use_records_cannot_be_deleted(admin_client, session):
    period = models.Period(year=2026, month=9)
    rep = models.Rep(name="ALEX")
    client = models.Client(name="Pine Ridge School")
    item = models.Item(model="XC2335", brand="Lexmark", category="mfp")
    session.add(models.Deal(period=period, rep=rep, client=client, total_cents=100,
                            lines=[models.DealLine(item=item, qty=1)]))
    session.commit()

    assert admin_client.delete(f"/api/reps/{rep.id}").status_code == 409
    assert admin_client.delete(f"/api/clients/{client.id}").status_code == 409
    assert admin_client.delete(f"/api/items/{item.id}").status_code == 409


def test_clients_items_search_and_blank_fields(admin_client):
    a = admin_client.post("/api/clients", json={"name": "Coastal Valley Bank", "location": "Eureka"}).json()
    admin_client.post("/api/clients", json={"name": "Coastal Valley Bank", "location": ""})
    assert admin_client.post("/api/clients", json={"name": "Coastal Valley Bank", "location": "Eureka"}).status_code == 409
    assert [c["location"] for c in admin_client.get("/api/clients?q=eureka").json()] == ["Eureka"]
    assert admin_client.put(f"/api/clients/{a['id']}", json={"name": "CVB", "location": "  "}).json()["location"] is None

    item = admin_client.post("/api/items", json={"brand": "", "model": "Printer Stand", "category": "accessory"}).json()
    assert item["brand"] is None
    assert admin_client.post("/api/items", json={"model": "X", "category": "spaceship"}).status_code == 422
    assert len(admin_client.get("/api/items?q=stand").json()) == 1


def test_flag_delete_removes_from_deals(admin_client, session):
    flag = admin_client.post("/api/flags", json={"name": "Highlight", "color": "#22C55E"}).json()
    assert flag["color"] == "#22c55e"
    assert admin_client.post("/api/flags", json={"name": "Bad", "color": "green"}).status_code == 422
    deal = models.Deal(period=models.Period(year=2026, month=9), rep=models.Rep(name="A"),
                       client=models.Client(name="C"), total_cents=1)
    deal.flags = [session.get(models.Flag, flag["id"])]
    session.add(deal)
    session.commit()

    assert admin_client.delete(f"/api/flags/{flag['id']}").status_code == 204
    session.expire_all()
    assert session.get(models.Deal, deal.id).flags == []


def test_period_reps_set_quota_and_order(admin_client, session):
    period = models.Period(year=2026, month=9)
    a, b, c = models.Rep(name="A"), models.Rep(name="B"), models.Rep(name="C")
    session.add_all([period, a, b, c])
    session.flush()
    period.period_reps = [models.PeriodRep(rep=a, display_order=0, quota=10),
                          models.PeriodRep(rep=b, display_order=1, quota=20)]
    session.commit()

    body = [{"rep_id": c.id, "quota": 5}, {"rep_id": a.id, "quota": None}]
    res = admin_client.put(f"/api/periods/{period.id}/reps", json=body)
    assert res.status_code == 200
    assert res.json() == [{"rep_id": c.id, "name": "C", "quota": 5}, {"rep_id": a.id, "name": "A", "quota": None}]
    board = admin_client.get(f"/api/periods/{period.id}/board").json()
    assert [r["name"] for r in board["reps"]] == ["C", "A"]

    assert admin_client.put(f"/api/periods/{period.id}/reps", json=[{"rep_id": a.id}, {"rep_id": a.id}]).status_code == 422
    assert admin_client.put(f"/api/periods/{period.id}/reps", json=[{"rep_id": 999}]).status_code == 422
    assert admin_client.put(f"/api/periods/{period.id}/reps", json=[{"rep_id": a.id, "quota": -1}]).status_code == 422


def test_locked_period_quotas_read_only(admin_client, session):
    period = models.Period(year=2026, month=8, locked_at=datetime(2026, 8, 31))
    session.add(period)
    session.commit()
    assert admin_client.put(f"/api/periods/{period.id}/reps", json=[]).status_code == 409


def test_settings(admin_client):
    s = admin_client.get("/api/settings").json()
    assert s == {"quota_unit": "usd_thousands", "board_key": None}
    assert admin_client.patch("/api/settings", json={"quota_unit": "units"}).json()["quota_unit"] == "units"
    assert admin_client.patch("/api/settings", json={"quota_unit": "bananas"}).status_code == 422
    key = admin_client.post("/api/settings/board-key").json()["board_key"]
    assert len(key) >= 20
    assert admin_client.delete("/api/settings/board-key").json()["board_key"] is None
