from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import models, sheet_sync
from app.google_sheet import SheetError, read_spreadsheet, spreadsheet_id, to_grid
from app.sheet_import import parse_tabs

import pytest

SHEET_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


def api_tab(title, rows):
    """A Sheets API grid response for one tab: rows of (value, rgb) or value."""
    def cell(v):
        if v is None:
            return {}
        v, rgb = v if isinstance(v, tuple) else (v, None)
        out = {"effectiveValue": {"numberValue": v} if isinstance(v, (int, float)) else {"stringValue": v}}
        if rgb:
            out["userEnteredFormat"] = {"backgroundColor": dict(zip(("red", "green", "blue"), rgb))}
        return out
    return {"properties": {"title": title}, "data": [{"rowData": [{"values": [cell(v) for v in row]} for row in rows]}]}


SEPT = api_tab("926", [
    [None, "SEPTEMBER", None, "QUOTA", "SALES"],
    ["KANDIS", "Aquaterra*", ("HM Development", (164 / 255, 194 / 255, 244 / 255)), 44, 300],
    [None, "(2) XC4342", "Rental"],
    [None, 100, 200],
    ["MONTHLY TOTAL", 300],
])


class FakeSession:
    def __init__(self, status=200):
        self.status = status
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append(params)
        body = ({"sheets": [{"properties": {"title": t}} for t in ("926", "Overview")]}
                if params["fields"] == "sheets.properties.title" else {"sheets": [SEPT]})
        return type("Res", (), {"status_code": self.status, "json": lambda _self: body, "text": ""})()


def test_spreadsheet_id():
    assert spreadsheet_id(f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit?gid=1") == SHEET_ID
    assert spreadsheet_id(SHEET_ID) == SHEET_ID
    with pytest.raises(SheetError):
        spreadsheet_id("not a sheet")


def test_read_spreadsheet_only_month_tabs(tmp_path):
    fake = FakeSession()
    tabs = read_spreadsheet(SHEET_ID, tmp_path / "key.json", session=fake)
    assert list(tabs) == ["926"]
    assert fake.calls[1]["ranges"] == ["'926'!A1:AZ300"]
    [month] = parse_tabs(tabs).months
    new, rental = month.reps[0].deals
    assert (new.client, new.new_customer, new.items) == ("Aquaterra", True, [(2, "XC4342")])
    assert rental.new_customer  # blue fill
    assert month.sheet_total == 300


def test_read_spreadsheet_not_shared(tmp_path):
    key = tmp_path / "key.json"
    key.write_text('{"client_email": "tracker@proj.iam.gserviceaccount.com"}')
    with pytest.raises(SheetError, match="tracker@proj.iam.gserviceaccount.com"):
        read_spreadsheet(SHEET_ID, key, session=FakeSession(403))


def test_to_grid_handles_empty_tab():
    assert to_grid({"properties": {"title": "926"}}) == []


def test_run_saves_status(session):
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    status = sheet_sync.run(read=lambda: {"926": to_grid(SEPT)}, session_factory=factory)
    assert status["ok"] and status["counts"]["deals"] == 2 and status["mismatches"] == []
    assert len(session.scalars(select(models.Deal)).all()) == 2

    def broken():
        raise SheetError("nope")
    status = sheet_sync.run(read=broken, session_factory=factory)
    assert (status["ok"], status["message"]) == (False, "nope")
    assert sheet_sync.get_status(session)["message"] == "nope"
    assert len(session.scalars(select(models.Deal)).all()) == 2


def test_sheet_endpoints(admin_client, session):
    res = admin_client.get("/api/sheet/sync")
    assert res.status_code == 200
    assert res.json()["configured"] is False and res.json()["last"] is None

    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    sheet_sync.run(read=lambda: {"926": to_grid(SEPT)}, session_factory=factory)
    names = admin_client.get("/api/sheet/names/client").json()
    assert [n["spellings"] for n in names] == [["Aquaterra"], ["HM Development"]]
    assert [n["spellings"] for n in admin_client.get("/api/sheet/names/item").json()] == [["Rental"], ["XC4342"]]
    assert admin_client.get("/api/sheet/names/nope").status_code == 422

    res = admin_client.post("/api/sheet/name-fixes",
                            json={"kind": "client", "source_name": "HM Development", "target_name": "HM Dev Inc"})
    assert res.status_code == 201
    fix = res.json()
    assert fix["checked"] is False and fix["created_by_name"] == "admin"
    names = {n["spellings"][0]: n for n in admin_client.get("/api/sheet/names/client").json()}
    assert names["HM Development"]["current_name"] == "HM Dev Inc"
    assert admin_client.delete(f"/api/sheet/name-fixes/{fix['id']}").status_code == 204
    assert admin_client.post("/api/sheet/names/client/apply-suggestions").json() == []


def test_sheet_endpoints_admin_only(user_client):
    assert user_client.get("/api/sheet/sync").status_code == 403
    assert user_client.get("/api/sheet/names/client").status_code == 403
    assert user_client.post("/api/sheet/names/item/apply-suggestions").status_code == 403


def test_sheet_deals_are_read_only(user_client, session):
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    sheet_sync.run(read=lambda: {"926": to_grid(SEPT)}, session_factory=factory)
    deal = session.scalar(select(models.Deal))
    got = user_client.get(f"/api/deals/{deal.id}").json()
    assert got["sheet_ref"] == "926!B2" and got["sheet_plus"] is False
    res = user_client.delete(f"/api/deals/{deal.id}")
    assert res.status_code == 409 and "Google Sheet" in res.json()["detail"]
