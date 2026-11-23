"""The app writing to the sheet's data tabs, against a fake sheet that behaves like a grid."""

import re
from datetime import date

import pytest
from sqlalchemy import select

from app import models, sheet_sync, sheet_tabs, sheet_write
from app.config import settings
from app.google_sheet import SheetsApi

from .conftest import make_user, sign_in

SHEET_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
RANGE = re.compile(r"^'(.+)'!([A-Z]+)(\d+)?(?::([A-Z]+)(\d+)?)?$")


def col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


class GridSheets:
    """A spreadsheet as grids of values: reads trim trailing blanks like Google; writes, row inserts and deletes,
    and find/replace change the grid."""

    def __init__(self, grids: dict[str, list[list]], spare: int = 20):
        self.grids = {t: [list(r) for r in rows] for t, rows in grids.items()}
        self.ids = {t: i for i, t in enumerate(grids)}
        self.row_count = {t: len(rows) + spare for t, rows in grids.items()}
        self.posts: list[dict] = []

    def _res(self, body):
        return type("Res", (), {"status_code": 200, "json": lambda _self: body, "text": ""})()

    def _tab(self, sheet_id: int) -> str:
        return next(t for t, i in self.ids.items() if i == sheet_id)

    def get(self, url, params, timeout):
        if url.endswith("/values:batchGet"):
            out = []
            for r in params["ranges"]:
                tab, c0, r0, c1, r1 = RANGE.match(r).groups()
                grid = self.grids[tab]
                r0, c0 = int(r0 or 1) - 1, col_index(c0)
                r1 = int(r1) if r1 else len(grid)
                c1 = col_index(c1) + 1 if c1 else 10_000
                rows = [[v for v in row[c0:c1]] for row in grid[r0:r1]]
                rows = [row[:max((i + 1 for i, v in enumerate(row) if v != ""), default=0)] for row in rows]
                while rows and not rows[-1]:
                    rows.pop()
                out.append({"values": rows} if rows else {})
            return self._res({"valueRanges": out})
        return self._res({"properties": {"title": "Test sheet"}, "sheets": [
            {"properties": {"title": t, "sheetId": i, "gridProperties": {"rowCount": self.row_count[t]}}}
            for t, i in self.ids.items()]})

    def _set(self, tab, row, col, value):
        assert row < self.row_count[tab], f"wrote {tab} row {row + 1}, past the grid's {self.row_count[tab]} rows"
        grid = self.grids[tab]
        while len(grid) <= row:
            grid.append([])
        while len(grid[row]) <= col:
            grid[row].append("")
        grid[row][col] = value

    def post(self, url, json, timeout):
        self.posts.append(json)
        if url.endswith("/values:batchUpdate"):
            assert json["valueInputOption"] == "RAW"
            for d in json["data"]:
                tab, c, r, *_ = RANGE.match(d["range"]).groups()
                for i, row in enumerate(d["values"]):
                    for j, v in enumerate(row):
                        self._set(tab, int(r) - 1 + i, col_index(c) + j, v)
            return self._res({})
        for req in json["requests"]:
            if "appendDimension" in req:
                self.row_count[self._tab(req["appendDimension"]["sheetId"])] += req["appendDimension"]["length"]
            elif "deleteDimension" in req:
                rng = req["deleteDimension"]["range"]
                tab = self._tab(rng["sheetId"])
                del self.grids[tab][rng["startIndex"]:rng["endIndex"]]
                self.row_count[tab] -= rng["endIndex"] - rng["startIndex"]
            elif "findReplace" in req:
                f = req["findReplace"]
                tab, c = self._tab(f["range"]["sheetId"]), f["range"]["startColumnIndex"]
                for row in self.grids[tab][f["range"]["startRowIndex"]:]:
                    if c < len(row) and str(row[c]).lower() == f["find"].lower():
                        row[c] = f["replacement"]
        return self._res({"replies": [{} for _ in json["requests"]]})

    # Helpers for the tests.
    def rows(self, tab: str) -> list[dict]:
        header = self.grids[tab][0]
        return [dict(zip(header, r)) for r in self.grids[tab][1:] if sheet_tabs.is_record(r)]

    def deal(self, ref: str) -> dict:
        return next(r for r in self.rows("Deals") if r["ID"] == ref)

    def edit(self, ref: str, column: str, value) -> None:
        """Someone typing on the sheet."""
        header = self.grids["Deals"][0]
        row = next(r for r in self.grids["Deals"][1:] if r and r[0] == ref)
        row[header.index(column)] = value


@pytest.fixture
def sheet(session, tmp_path, monkeypatch):
    """A sheet with data tabs for Aug and Sep 2026 (ALEX, BOB), synced into the app; app writes go to it."""
    alex, bob = models.Rep(name="ALEX"), models.Rep(name="BOB")
    sharp = models.Item(brand="Sharp", model="BP-71C31", category="mfp")
    acme = models.Client(name="Acme")
    aug, sep = models.Period(year=2026, month=8), models.Period(year=2026, month=9)
    session.add_all([alex, bob, sharp, acme, aug, sep])
    session.flush()
    aug.period_reps = [models.PeriodRep(rep=alex, display_order=0, quota=40)]
    sep.period_reps = [models.PeriodRep(rep=alex, display_order=0, quota=44), models.PeriodRep(rep=bob, display_order=1)]
    session.add_all([
        models.Deal(period=aug, rep=alex, client=acme, total_cents=500_000, lines=[models.DealLine(item=sharp, qty=1)]),
        models.Deal(period=sep, rep=alex, client=acme, total_cents=100_000, lines=[models.DealLine(item=sharp, qty=2)]),
        models.Deal(period=sep, rep=bob, client=acme, total_cents=250_000, lines=[models.DealLine(description="Various")]),
    ])
    session.commit()
    tables = sheet_tabs.build_tables(session)
    # The app's own copies go; the sheet is now the source.
    for d in session.scalars(select(models.Deal)):
        session.delete(d)
    session.commit()

    fake = GridSheets({t: [list(sheet_tabs.HEADERS[t]), *tables.rows[t]] for t in sheet_tabs.DATA_TABS})
    key = tmp_path / "key.json"
    key.write_text("{}")
    monkeypatch.setattr(settings, "google_sheet", SHEET_ID)
    monkeypatch.setattr(settings, "google_credentials", str(key))
    api = SheetsApi(SHEET_ID, key, session=fake)
    monkeypatch.setattr(sheet_write, "open_api", lambda: api)
    status = sheet_sync.run(api=api, db=session, read=None)
    assert status["ok"] and status["source"] == "data tabs", status
    fake.api = api
    return fake


def deal_body(session, **change):
    sep = session.scalars(select(models.Period).where(models.Period.month == 9)).one()
    rep = session.scalars(select(models.Rep).where(models.Rep.name == "BOB")).one()
    item = session.scalars(select(models.Item)).first()
    body = {"period_id": sep.id, "rep_id": rep.id, "new_client": {"name": "Zeta Corp", "location": "South"},
            "deal_date": "2026-09-20", "total_cents": 123_456, "notes": "PO 9", "plus": True,
            "lines": [{"item_id": item.id, "qty": 3}, {"description": "Toner", "qty": 1}]}
    return {**body, **change}


def by_ref(session, ref):
    return session.scalars(select(models.Deal).where(models.Deal.sheet_ref == ref)).one()


def test_sync_keeps_deal_ids_and_versions(session, sheet):
    first = {d.sheet_ref: (d.id, d.sheet_version) for d in session.scalars(select(models.Deal))}
    assert sorted(first) == ["D00001", "D00002", "D00003"] and all(v for _, v in first.values())
    sheet.edit("D00002", "Amount", 1500)
    sheet_sync.run(api=sheet.api, db=session)
    again = {d.sheet_ref: (d.id, d.sheet_version) for d in session.scalars(select(models.Deal))}
    # Same app IDs; only the edited row's version moved.
    assert {r: i for r, (i, _) in again.items()} == {r: i for r, (i, _) in first.items()}
    assert [r for r in again if again[r][1] != first[r][1]] == ["D00002"]
    assert by_ref(session, "D00002").total_cents == 150_000

    # A row removed on the sheet is removed from the app.
    sheet.grids["Deals"] = [r for r in sheet.grids["Deals"] if not r or r[0] != "D00003"]
    sheet_sync.run(api=sheet.api, db=session)
    assert sorted(d.sheet_ref for d in session.scalars(select(models.Deal))) == ["D00001", "D00002"]


def test_mode(admin_client, sheet):
    assert admin_client.get("/api/deals/mode").json() == {"sheet": True}


def test_mode_without_data_tabs(admin_client):
    assert admin_client.get("/api/deals/mode").json() == {"sheet": False}


def test_add_deal_writes_a_row(admin_client, session, sheet):
    res = admin_client.post("/api/deals", json=deal_body(session))
    assert res.status_code == 201, res.text
    out = res.json()
    assert out["sheet_ref"] == "D00004" and out["version"]
    assert out["client"] == {"id": out["client"]["id"], "name": "Zeta Corp", "location": "South"}
    assert out["created_by_name"] == "admin" and out["updated_by_name"] == "admin" and out["sheet_plus"] is True

    row = sheet.deal("D00004")
    assert (row["Month"], row["Rep"], row["Client"], row["Location"]) == ("2026-09", "BOB", "Zeta Corp", "South")
    assert (row["Items"], row["Amount"], row["Notes"], row["Entered by"]) == ("(3) Sharp BP-71C31  Toner", 1234.56, "PO 9", "admin")
    assert row["Date"] == sheet_tabs.serial(date(2026, 9, 20)) and row["Plus"] is True and row["New customer"] is False
    assert isinstance(row["Updated"], float)
    # The row went right below the last one, not after the blank rows.
    assert sheet.grids["Deals"][4][0] == "D00004"
    assert [(line["label"], line["qty"]) for line in out["lines"]] == [("Sharp BP-71C31", 3), ("Toner", 1)]


def test_add_deal_grows_a_full_tab(admin_client, session, sheet):
    sheet.row_count["Deals"] = len(sheet.grids["Deals"])  # no spare rows left
    assert admin_client.post("/api/deals", json=deal_body(session)).status_code == 201
    assert any("appendDimension" in r for p in sheet.posts for r in p.get("requests", []))


def test_edit_deal_rewrites_its_row(admin_client, session, sheet):
    deal = by_ref(session, "D00003")
    deal_id, version = deal.id, deal.sheet_version
    body = deal_body(session, client_id=deal.client_id, new_client=None, total_cents=999_900, plus=False, version=version)
    res = admin_client.put(f"/api/deals/{deal_id}", json=body)
    assert res.status_code == 200, res.text
    assert res.json()["id"] == deal_id and res.json()["total_cents"] == 999_900 and res.json()["version"] != version
    row = sheet.deal("D00003")
    assert (row["Amount"], row["Client"], row["Entered by"]) == (9999.0, "Acme", "")  # Entered by left alone
    assert len(sheet.rows("Deals")) == 3


def test_edit_refused_when_the_sheet_changed(admin_client, session, sheet):
    deal = by_ref(session, "D00003")
    deal_id, version = deal.id, deal.sheet_version
    sheet.edit("D00003", "Notes", "typed on the sheet")
    body = deal_body(session, client_id=deal.client_id, new_client=None, version=version)
    res = admin_client.put(f"/api/deals/{deal_id}", json=body)
    assert res.status_code == 409 and "changed on the sheet" in res.json()["detail"]
    # The sheet's change survived and the app picked it up.
    assert sheet.deal("D00003")["Notes"] == "typed on the sheet"
    assert session.get(models.Deal, deal_id).notes == "typed on the sheet"

    # A form opened before that sync is refused too.
    res = admin_client.put(f"/api/deals/{deal_id}", json=body)
    assert res.status_code == 409 and "after you opened it" in res.json()["detail"]
    fresh = admin_client.get(f"/api/deals/{deal_id}").json()["version"]
    assert admin_client.put(f"/api/deals/{deal_id}", json={**body, "version": fresh}).status_code == 200


def test_edit_a_deal_deleted_on_the_sheet(admin_client, session, sheet):
    deal = by_ref(session, "D00003")
    deal_id = deal.id
    body = deal_body(session, client_id=deal.client_id, new_client=None)
    sheet.grids["Deals"] = [r for r in sheet.grids["Deals"] if not r or r[0] != "D00003"]
    res = admin_client.put(f"/api/deals/{deal_id}", json=body)
    assert res.status_code == 409 and "isn't on the Deals tab" in res.json()["detail"]
    assert session.get(models.Deal, deal_id) is None


def test_delete_deal_removes_its_row(admin_client, session, sheet):
    deal = by_ref(session, "D00002")
    res = admin_client.delete(f"/api/deals/{deal.id}", params={"version": deal.sheet_version})
    assert res.status_code == 204, res.text
    assert [r["ID"] for r in sheet.rows("Deals")] == ["D00001", "D00003"]
    assert sorted(d.sheet_ref for d in session.scalars(select(models.Deal))) == ["D00001", "D00003"]


def test_locked_months_can_be_changed(admin_client, session, sheet):
    aug = session.scalars(select(models.Period).where(models.Period.month == 8)).one()
    assert aug.locked_at is not None  # the sync locks months before the current one
    deal = by_ref(session, "D00001")
    body = deal_body(session, period_id=aug.id, client_id=deal.client_id, new_client=None, deal_date=None,
                     rep_id=deal.rep_id, total_cents=10)
    assert admin_client.put(f"/api/deals/{deal.id}", json=body).status_code == 200
    assert sheet.deal("D00001")["Amount"] == 0.1


def test_only_the_new_customer_flag(admin_client, session, sheet):
    session.add(models.Flag(name="Rush", color="#f00"))
    session.commit()
    flags = {f.name: f.id for f in session.scalars(select(models.Flag))}
    res = admin_client.post("/api/deals", json=deal_body(session, flag_ids=[flags["Rush"]]))
    assert res.status_code == 422 and "Rush" in res.json()["detail"]
    res = admin_client.post("/api/deals", json=deal_body(session, flag_ids=[flags["New customer"]]))
    assert res.status_code == 201 and sheet.deal("D00004")["New customer"] is True


def test_app_only_deal_moves_to_the_sheet(admin_client, session, sheet):
    sep = session.scalars(select(models.Period).where(models.Period.month == 9)).one()
    alex = session.scalars(select(models.Rep).where(models.Rep.name == "ALEX")).one()
    acme = session.scalars(select(models.Client)).first()
    local = models.Deal(period=sep, rep=alex, client=acme, total_cents=100, lines=[models.DealLine(description="X")])
    session.add(local)
    session.commit()
    res = admin_client.put(f"/api/deals/{local.id}", json=deal_body(session, client_id=acme.id, new_client=None))
    assert res.status_code == 200, res.text
    assert res.json()["sheet_ref"] == "D00004"
    assert session.scalars(select(models.Deal).where(models.Deal.sheet_ref.is_(None))).first() is None
    assert sheet.deal("D00004")["Entered by"] == "admin"


def test_sheet_errors_are_reported(admin_client, session, sheet, monkeypatch):
    def broken(*_a, **_k):
        raise sheet_write.SheetError("Google Sheets returned 500")
    monkeypatch.setattr(sheet_write, "add_deal", broken)
    res = admin_client.post("/api/deals", json=deal_body(session))
    assert res.status_code == 502 and "Couldn't save to the Google Sheet" in res.json()["detail"]
    assert session.scalars(select(models.Client).where(models.Client.name == "Zeta Corp")).first() is None


def test_quotas_rewrite_the_months_rows(admin_client, session, sheet):
    sep = session.scalars(select(models.Period).where(models.Period.month == 9)).one()
    reps = {r.name: r.id for r in session.scalars(select(models.Rep))}
    res = admin_client.put(f"/api/periods/{sep.id}/reps", json=[{"rep_id": reps["BOB"], "quota": 50}])
    assert res.status_code == 200, res.text
    # ALEX still has September deals, so the board keeps him, at the bottom without a quota (as the sheet does).
    assert res.json() == [{"rep_id": reps["BOB"], "name": "BOB", "quota": 50.0},
                          {"rep_id": reps["ALEX"], "name": "ALEX", "quota": None}]
    assert [(r["Month"], r["Rep"], r["Quota"], r["Order"]) for r in sheet.rows("Quotas")] == [
        ("2026-08", "ALEX", 40, 1), ("2026-09", "BOB", 50, 1)]

    res = admin_client.put(f"/api/periods/{sep.id}/reps", json=[
        {"rep_id": reps["ALEX"], "quota": 1}, {"rep_id": reps["BOB"]}])
    assert [r["name"] for r in res.json()] == ["ALEX", "BOB"]
    assert [(r["Month"], r["Rep"], r["Quota"], r["Order"]) for r in sheet.rows("Quotas")] == [
        ("2026-08", "ALEX", 40, 1), ("2026-09", "ALEX", 1, 1), ("2026-09", "BOB", "", 2)]


def test_starting_a_month_adds_its_quota_rows(admin_client, session, sheet):
    res = admin_client.post("/api/periods", json={"year": 2026, "month": 10})
    assert res.status_code == 201, res.text
    assert [(r["Month"], r["Rep"], r["Order"]) for r in sheet.rows("Quotas")][-2:] == [
        ("2026-10", "ALEX", 1), ("2026-10", "BOB", 2)]
    assert res.json()["year"] == 2026 and res.json()["month"] == 10


def test_reps_add_rename_delete(admin_client, session, sheet):
    res = admin_client.post("/api/reps", json={"name": "Cara", "counts_toward_total": False})
    assert res.status_code == 201, res.text
    assert res.json()["name"] == "CARA"
    assert sheet.rows("Reps")[-1] == {"Rep": "CARA", "Active": True, "Counts toward total": False}
    assert admin_client.post("/api/reps", json={"name": "cara"}).status_code == 409

    bob = session.scalars(select(models.Rep).where(models.Rep.name == "BOB")).one()
    bob_id = bob.id
    user = make_user(session, "bob@example.com", rep=bob)
    res = admin_client.patch(f"/api/reps/{bob_id}", json={"name": "Robert", "active": False})
    assert res.status_code == 200, res.text
    assert res.json() == {"id": bob_id, "name": "ROBERT", "active": False, "counts_toward_total": True}
    assert {r["Rep"] for r in sheet.rows("Deals")} == {"ALEX", "ROBERT"}
    assert [r["Rep"] for r in sheet.rows("Quotas")] == ["ALEX", "ALEX", "ROBERT"]
    session.refresh(user)
    assert user.rep_id == bob_id  # still linked: the same rep, renamed
    assert session.scalars(select(models.Rep).where(models.Rep.name == "BOB")).first() is None

    cara = session.scalars(select(models.Rep).where(models.Rep.name == "CARA")).one()
    assert admin_client.delete(f"/api/reps/{cara.id}").status_code == 204
    assert [r["Rep"] for r in sheet.rows("Reps")] == ["ALEX", "ROBERT"]
    assert session.get(models.Rep, cara.id) is None


def test_users_still_cannot_write(client, session, sheet):
    make_user(session, "viewer@example.com")
    sign_in(client, "viewer@example.com")
    assert client.post("/api/deals", json=deal_body(session)).status_code == 403
    assert len(sheet.rows("Deals")) == 3
