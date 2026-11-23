from datetime import datetime

import pytest

from app import models

from .conftest import BREAKGLASS_PASSWORD, make_user, sign_in


@pytest.fixture
def ref(session):
    """A month with one rep, a client, an item, and a flag."""
    period = models.Period(year=2026, month=9)
    rep = models.Rep(name="ALEX")
    client = models.Client(name="Pine Ridge School")
    item = models.Item(brand="Sharp", model="BP-70M75", category="mfp")
    flag = models.Flag(name="Highlight", color="#22c55e")
    session.add_all([period, rep, client, item, flag])
    session.flush()
    period.period_reps = [models.PeriodRep(rep=rep, display_order=0, quota=40)]
    session.commit()
    return {"period": period, "rep": rep, "client": client, "item": item, "flag": flag}


def deal_body(ref, **overrides):
    body = {
        "period_id": ref["period"].id,
        "rep_id": ref["rep"].id,
        "client_id": ref["client"].id,
        "deal_date": "2026-09-15",
        "lines": [{"item_id": ref["item"].id, "qty": 2, "amount_cents": 2_886_100}],
    }
    return body | overrides


def test_create_deal_totals_and_audit(admin_client, ref):
    res = admin_client.post("/api/deals", json=deal_body(ref, flag_ids=[ref["flag"].id], notes="  PO 123  "))
    assert res.status_code == 201, res.text
    deal = res.json()
    assert deal["total_cents"] == 2_886_100  # summed from lines
    assert deal["lines"][0] | {"id": 0} == {"id": 0, "item_id": ref["item"].id, "description": None,
                                            "label": "Sharp BP-70M75", "category": "mfp", "qty": 2,
                                            "amount_cents": 2_886_100}
    assert deal["notes"] == "PO 123"
    assert deal["created_by_name"] == deal["updated_by_name"] == "admin"
    assert deal["flags"][0]["name"] == "Highlight"
    assert not deal["period_locked"]

    board = admin_client.get(f"/api/periods/{ref['period'].id}/board").json()
    assert board["total_sales_cents"] == 2_886_100


def test_explicit_total_and_free_text_line(admin_client, ref):
    body = deal_body(ref, total_cents=1_000_00, lines=[{"description": "Various"}, {"item_id": ref["item"].id}])
    deal = admin_client.post("/api/deals", json=body).json()
    assert deal["total_cents"] == 100_000
    assert [line["label"] for line in deal["lines"]] == ["Various", "Sharp BP-70M75"]


def test_total_required_when_lines_lack_amounts(admin_client, ref):
    res = admin_client.post("/api/deals", json=deal_body(ref, lines=[{"description": "Papercut"}]))
    assert res.status_code == 422
    assert "total" in res.json()["detail"]


@pytest.mark.parametrize("change, message", [
    ({"lines": []}, None),
    ({"lines": [{"qty": 1}]}, "catalog item or a description"),
    ({"client_id": None}, "client_id or new_client"),
    ({"new_client": {"name": "X"}}, "client_id or new_client"),
    ({"deal_date": "2026-10-01"}, "September 2026"),
    ({"rep_id": 999}, "Unknown rep"),
    ({"client_id": 999}, "Unknown client"),
    ({"flag_ids": [999]}, "Unknown flag"),
    ({"lines": [{"item_id": 999, "amount_cents": 1}]}, "Unknown item"),
    ({"lines": [{"description": "x", "qty": 0, "amount_cents": 1}]}, None),
    ({"lines": [{"description": "x", "amount_cents": -5}]}, None),
])
def test_validation(admin_client, ref, change, message):
    res = admin_client.post("/api/deals", json=deal_body(ref, **change))
    assert res.status_code == 422, res.text
    if message:
        assert message in str(res.json()["detail"])


def test_new_client_is_created_once_and_reused(admin_client, ref, session):
    body = deal_body(ref, client_id=None, new_client={"name": "Coastal Valley Bank", "location": "Westside"})
    a = admin_client.post("/api/deals", json=body).json()
    b = admin_client.post("/api/deals", json=body).json()
    assert a["client"]["id"] == b["client"]["id"]
    assert a["client"]["location"] == "Westside"
    blank = deal_body(ref, client_id=None, new_client={"name": "Coastal Valley Bank", "location": ""})
    c = admin_client.post("/api/deals", json=blank).json()
    assert c["client"]["location"] is None and c["client"]["id"] != a["client"]["id"]
    assert session.query(models.Client).filter_by(name="Coastal Valley Bank").count() == 2


def test_edit_and_delete(admin_client, ref, session):
    deal = admin_client.post("/api/deals", json=deal_body(ref)).json()
    other = models.Rep(name="BRENDA")
    session.add(other)
    session.commit()

    res = admin_client.put(f"/api/deals/{deal['id']}", json=deal_body(
        ref, rep_id=other.id, lines=[{"description": "Stand", "amount_cents": 44_200}], deal_date=None))
    assert res.status_code == 200, res.text
    updated = res.json()
    assert updated["rep_name"] == "BRENDA"
    assert updated["total_cents"] == 44_200
    assert [line["label"] for line in updated["lines"]] == ["Stand"]
    assert session.query(models.DealLine).count() == 1  # old lines removed

    assert admin_client.delete(f"/api/deals/{deal['id']}").status_code == 204
    assert admin_client.get(f"/api/deals/{deal['id']}").status_code == 404


def test_list_filters(admin_client, ref, session):
    admin_client.post("/api/deals", json=deal_body(ref, deal_date="2026-09-01"))
    admin_client.post("/api/deals", json=deal_body(ref, deal_date="2026-09-20"))
    deals = admin_client.get(f"/api/deals?period_id={ref['period'].id}").json()
    assert [d["deal_date"] for d in deals] == ["2026-09-20", "2026-09-01"]  # newest first
    assert admin_client.get(f"/api/deals?rep_id={ref['rep'].id + 1}").json() == []


def test_locked_month_is_read_only(admin_client, ref, session):
    deal = admin_client.post("/api/deals", json=deal_body(ref)).json()
    open_month = models.Period(year=2026, month=10)
    session.add(open_month)
    ref["period"].locked_at = datetime(2026, 9, 30)
    session.commit()

    assert admin_client.post("/api/deals", json=deal_body(ref)).status_code == 409
    assert admin_client.put(f"/api/deals/{deal['id']}", json=deal_body(ref)).status_code == 409
    # Can't move it out of the locked month either.
    moved = deal_body(ref, period_id=open_month.id, deal_date=None)
    assert admin_client.put(f"/api/deals/{deal['id']}", json=moved).status_code == 409
    assert admin_client.delete(f"/api/deals/{deal['id']}").status_code == 409
    assert admin_client.get(f"/api/deals/{deal['id']}").json()["period_locked"] is True


def test_deals_need_sign_in(client, ref):
    anon = client.__class__(client.app)
    assert anon.get("/api/deals").status_code == 401
    assert anon.post("/api/deals", json=deal_body(ref)).status_code == 401


def test_users_can_view_but_not_change_deals(admin_client, client, session, ref):
    deal = admin_client.post("/api/deals", json=deal_body(ref)).json()
    make_user(session, "viewer@example.com", rep=ref["rep"])
    viewer = sign_in(client.__class__(client.app), "viewer@example.com")
    assert viewer.get("/api/deals").status_code == 200
    assert viewer.get(f"/api/deals/{deal['id']}").status_code == 200
    assert viewer.post("/api/deals", json=deal_body(ref)).status_code == 403
    assert viewer.put(f"/api/deals/{deal['id']}", json=deal_body(ref)).status_code == 403
    assert viewer.delete(f"/api/deals/{deal['id']}").status_code == 403


def test_users_only_see_their_reps_deals(admin_client, client, session, ref):
    other = models.Rep(name="BOB")
    session.add(other)
    session.commit()
    mine = admin_client.post("/api/deals", json=deal_body(ref)).json()
    theirs = admin_client.post("/api/deals", json=deal_body(ref, rep_id=other.id)).json()

    make_user(session, "alex@example.com", rep=ref["rep"])
    alex = sign_in(client.__class__(client.app), "alex@example.com")
    assert [d["id"] for d in alex.get("/api/deals").json()] == [mine["id"]]
    # Asking for another rep still returns only their own.
    assert [d["id"] for d in alex.get(f"/api/deals?rep_id={other.id}").json()] == [mine["id"]]
    assert alex.get(f"/api/deals/{theirs['id']}").status_code == 404

    make_user(session, "new@example.com")
    unlinked = sign_in(client.__class__(client.app), "new@example.com")
    res = unlinked.get("/api/deals")
    assert res.status_code == 403 and "isn't linked to a rep" in res.json()["detail"]


def test_breakglass_can_enter_deals(client, ref):
    sign_in(client, "breakglass", BREAKGLASS_PASSWORD)
    deal = client.post("/api/deals", json=deal_body(ref)).json()
    assert deal["created_by_name"] is None
