from datetime import date

import pytest

from app import models, sheet_tabs
from app.google_sheet import SheetError, SheetsApi
from app.sheet_import import split_items

SHEET_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


@pytest.fixture
def history(session):
    """Two months; ALEX above BOB on the board; one new customer, one '+', a split item line."""
    alex, bob, gone = models.Rep(name="ALEX"), models.Rep(name="BOB"), models.Rep(name="OLD", active=False)
    sharp = models.Item(brand="Sharp", model="BP-71C31", category="mfp")
    lex = models.Item(brand="Lexmark", model="XM3250", category="mfp")
    acme, beta = models.Client(name="Acme"), models.Client(name="Beta", location="North")
    new = models.Flag(name="New customer", color="#b6d7a8")
    aug, sep = models.Period(year=2026, month=8), models.Period(year=2026, month=9)
    session.add_all([alex, bob, gone, sharp, lex, acme, beta, new, aug, sep])
    session.flush()
    aug.period_reps = [models.PeriodRep(rep=alex, display_order=0, quota=40)]
    sep.period_reps = [models.PeriodRep(rep=bob, display_order=0, quota=None),
                       models.PeriodRep(rep=alex, display_order=1, quota=44)]
    session.add_all([
        # Added first but BOB is first on September's board, so BOB's deal comes first.
        models.Deal(period=sep, rep=alex, client=acme, total_cents=1_000_050, sheet_ref="926!B5",
                    lines=[models.DealLine(item=sharp, qty=2), models.DealLine(item=lex, qty=1)]),
        models.Deal(period=sep, rep=bob, client=beta, total_cents=250_000, sheet_ref="926!B2", sheet_plus=True,
                    flags=[new], deal_date=date(2026, 9, 15), notes="PO 7",
                    lines=[models.DealLine(description="Various", qty=1)]),
        models.Deal(period=aug, rep=alex, client=acme, total_cents=500_000, sheet_ref="826!B2",
                    lines=[models.DealLine(item=lex, qty=1)]),
    ])
    session.commit()


def test_build_tables(session, history):
    t = sheet_tabs.build_tables(session)
    assert t.rows["Reps"] == [["ALEX", True, True], ["BOB", True, True], ["OLD", False, True]]
    assert t.rows["Quotas"] == [["2026-08", "ALEX", 40, 1], ["2026-09", "BOB", "", 1], ["2026-09", "ALEX", 44, 2]]

    deals = t.rows["Deals"]
    assert [r[:2] + [r[3]] for r in deals] == [["D00001", "2026-08", "ALEX"], ["D00002", "2026-09", "BOB"],
                                                ["D00003", "2026-09", "ALEX"]]
    header = sheet_tabs.DEALS_HEADERS
    bob = dict(zip(header, deals[1]))
    assert bob["Date"] == 46280.0  # 2026-09-15 as a Sheets date
    assert (bob["Client"], bob["Location"], bob["New customer"], bob["Plus"]) == ("Beta", "North", True, True)
    assert (bob["Items"], bob["Amount"], bob["Notes"], bob["Entered by"]) == ("Various", 2500.0, "PO 7", "")
    alex = dict(zip(header, deals[2]))
    assert alex["Items"] == "(2) Sharp BP-71C31  Lexmark XM3250"
    # The sync reads the items text back as the same lines.
    assert split_items(alex["Items"]) == [(2, "Sharp BP-71C31"), (1, "Lexmark XM3250")]
    assert t.month_totals == {"2026-08": 5000.0, "2026-09": 12500.5}


def test_compare_totals(session, history):
    t = sheet_tabs.build_tables(session)
    assert sheet_tabs.compare_totals(t, {"2026-08": 5000.0, "2026-09": 12500.5}) == []
    assert sheet_tabs.compare_totals(t, {"2026-08": 5000.0, "2026-09": None, "2026-07": 10.0}) == [
        ("2026-07", 10.0, 0.0), ("2026-09", None, 12500.5)]


class FakeSheets:
    """Just enough of the Sheets API: tabs, batchUpdate (add/delete sheets) and values written then read back."""

    def __init__(self, tabs=("926", "Overview")):
        self.tabs = {t: i for i, t in enumerate(tabs)}
        self.values: dict[str, list] = {}
        self.requests: list[dict] = []
        self.next_id = 100

    def _res(self, body):
        return type("Res", (), {"status_code": 200, "json": lambda _self: body, "text": ""})()

    def get(self, url, params, timeout):
        if url.endswith("/values:batchGet"):
            return self._res({"valueRanges": [{"values": self.values.get(r.split("!")[0].strip("'"), [])}
                                              for r in params["ranges"]]})
        return self._res({"properties": {"title": "Test sheet"},
                          "sheets": [{"properties": {"title": t, "sheetId": i}} for t, i in self.tabs.items()]})

    def post(self, url, json, timeout):
        if url.endswith("/values:batchUpdate"):
            # Data is written RAW (text stays text); only the view tabs' formulas are USER_ENTERED.
            ranges = [d["range"] for d in json["data"]]
            assert json["valueInputOption"] == ("USER_ENTERED" if ranges[0].startswith("'Board'") else "RAW")
            for d in json["data"]:
                self.values[d["range"].split("!")[0].strip("'")] = d["values"]
            return self._res({})
        replies = []
        for r in json["requests"]:
            self.requests.append(r)
            if "deleteSheet" in r:
                self.tabs = {t: i for t, i in self.tabs.items() if i != r["deleteSheet"]["sheetId"]}
                replies.append({})
            elif "addSheet" in r:
                title = r["addSheet"]["properties"]["title"]
                self.tabs[title] = self.next_id
                replies.append({"addSheet": {"properties": {"title": title, "sheetId": self.next_id}}})
                self.next_id += 1
            else:
                replies.append({})
        return self._res({"replies": replies})


def test_write_tabs_and_read_back(session, history, tmp_path):
    fake = FakeSheets()
    api = SheetsApi(SHEET_ID, tmp_path / "key.json", session=fake)
    t = sheet_tabs.build_tables(session)

    ids = sheet_tabs.write_tabs(api, t)
    assert set(ids) == {"Deals", "Quotas", "Reps"} and fake.values["Deals"][0] == list(sheet_tabs.DEALS_HEADERS)
    assert sheet_tabs.read_back(api, t) == []

    kinds = [next(iter(r)) for r in fake.requests]
    assert kinds.count("addProtectedRange") == 4  # three header rows + the Deals ID column
    reps_rule = next(r["setDataValidation"]["rule"] for r in fake.requests
                     if "setDataValidation" in r and r["setDataValidation"]["range"]["sheetId"] == ids["Deals"]
                     and r["setDataValidation"]["range"]["startColumnIndex"] == 3)
    assert reps_rule["condition"] == {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": "='Reps'!$A$2:$A"}]}

    # Running again refuses, unless asked to replace.
    with pytest.raises(SheetError, match="--replace"):
        sheet_tabs.write_tabs(api, t)
    sheet_tabs.write_tabs(api, t, replace=True)
    assert sorted(fake.tabs) == ["926", "Deals", "Overview", "Quotas", "Reps"]

    # Spare rows with unticked checkboxes aren't records.
    fake.values["Reps"] = fake.values["Reps"] + [["", False, False]] * 5
    assert sheet_tabs.read_back(api, t) == []

    # Read-back notices rows that went missing or a month that doesn't add up.
    fake.values["Deals"] = fake.values["Deals"][:-1]
    problems = sheet_tabs.read_back(api, t)
    assert any("2 rows on the sheet, expected 3" in p for p in problems)
    assert any("2026-09 adds up to 2,500.00" in p for p in problems)


# --- Reading the data tabs (the sync) ---

def data_values():
    h = sheet_tabs.DEALS_HEADERS
    deal = lambda **kw: [kw.get(k, "") for k in h]  # noqa: E731
    return {
        "Reps": [list(sheet_tabs.REPS_HEADERS), ["ALEX", True, True], ["House", True, False], ["OLD", False, True],
                 ["", False, False]],
        "Quotas": [list(sheet_tabs.QUOTAS_HEADERS), ["2026-09", "HOUSE", "", 2], ["2026-09", "ALEX", 44, 1],
                   ["2026-09", "ALEX", 50, 3], ["Sept", "ALEX", 1, 1]],
        "Deals": [
            list(h),
            deal(ID="D00007", Month="2026-09", Rep="ALEX", Client="Acme*", Items="(2) Sharp BP-71C31  XM3250", Amount=1000.5),
            deal(Month="2026-09", Date=46280, Rep="house", Client="Beta", Location="North", Plus=True, Amount=250,
                 Notes="PO 7", **{"Entered by": "Pat"}),
            deal(ID="D00007", Month="2026-09", Rep="ALEX", Client="Copy", Amount=1),  # pasted copy of a row
            deal(Month="2026-10", Rep="NEWBIE", Client="Gamma", Amount="lots"),
            deal(Month="2026-13", Rep="ALEX", Client="Bad month", Amount=5),
            deal(Month="2026-09", Rep="ALEX", Client="", Amount=""),  # only month/rep picked
            ["", "", "", "", "", "", False, False],  # spare row: unticked boxes
        ],
    }


def test_parse_data_tabs():
    data = sheet_tabs.parse_data_tabs(data_values())
    sep, oct_ = data.result.months
    assert [r.name for r in sep.reps] == ["ALEX", "HOUSE"]  # Quotas order
    assert [r.quota for r in sep.reps] == [44, None]
    alex = sep.reps[0].deals
    assert (alex[0].client, alex[0].new_customer, alex[0].where) == ("Acme", True, "D00007")
    assert alex[0].items == [(2, "Sharp BP-71C31"), (1, "XM3250")]
    assert alex[1].client == "Copy" and alex[1].where == "D00009"  # duplicate ID replaced
    beta = sep.reps[1].deals[0]
    assert (beta.where, beta.deal_date, beta.location, beta.plus, beta.notes, beta.entered_by) == (
        "D00008", date(2026, 9, 15), "North", True, "PO 7", "Pat")
    # A rep with deals but no Quotas row is added at the bottom, and to the reps.
    assert [r.name for r in oct_.reps] == ["NEWBIE"] and oct_.reps[0].deals[0].amount == 0
    assert data.rep_info["HOUSE"].counts_toward_total is False and data.rep_info["OLD"].active is False
    assert data.rep_info["NEWBIE"].active is True

    assert [(x.row, x.id) for x in data.new_ids] == [(3, "D00008"), (4, "D00009"), (5, "D00010")]
    w = "\n".join(data.result.warnings)
    assert "Quotas row 4: ALEX already has a quota" in w
    assert "Quotas row 5: month 'Sept'" in w
    assert "Deals row 4: ID D00007 is used twice" in w
    assert "Deals row 5: NEWBIE isn't on the Reps tab" in w and "amount 'lots' isn't a number" in w
    assert "Deals row 6: month '2026-13'" in w
    assert "Deals row 7: no client or amount; skipped" in w
    assert "row 8" not in w


def test_missing_column_is_reported():
    values = data_values()
    values["Deals"][0] = [c for c in values["Deals"][0] if c != "Amount"]
    with pytest.raises(SheetError, match="Deals tab is missing the column Amount"):
        sheet_tabs.parse_data_tabs(values)


def test_columns_found_by_name():
    values = data_values()
    for row in values["Reps"]:  # swap the checkbox columns
        row[1], row[2] = row[2], row[1]
    data = sheet_tabs.parse_data_tabs(values)
    assert data.rep_info["HOUSE"].counts_toward_total is False


def test_fill_ids_skips_rows_that_moved(tmp_path):
    fake = FakeSheets()
    fake.values["Deals"] = data_values()["Deals"]
    data = sheet_tabs.parse_data_tabs(data_values())

    class Moved(FakeSheets):
        pass

    def get(url, params, timeout):
        # Row 4 now holds something else (someone sorted the tab).
        rows = {int(r.split("!A")[1].split(":")[0]): r for r in params["ranges"]}
        current = {n: fake.values["Deals"][n - 1] for n in rows}
        current[4] = ["", "2026-09", "", "ALEX", "Someone else"]
        return fake._res({"valueRanges": [{"values": [current[n]]} for n in rows]})

    fake.get = get
    writes = []
    fake.post = lambda url, json, timeout: writes.append(json) or fake._res({})
    api = SheetsApi(SHEET_ID, tmp_path / "key.json", session=fake)
    warnings = sheet_tabs.fill_ids(api, data.new_ids, data.id_column)
    assert warnings == ["Deals row 4 changed while syncing; its ID is filled in next sync"]
    assert [d["range"] for d in writes[0]["data"]] == ["'Deals'!A3", "'Deals'!A5"]
    assert writes[0]["valueInputOption"] == "RAW"


def test_sync_from_data_tabs(session, tmp_path):
    from sqlalchemy.orm import sessionmaker

    from app import sheet_sync

    fake = FakeSheets(tabs=("926", "Deals", "Quotas", "Reps"))
    fake.values = data_values()
    fake.get_orig = fake.get

    def get(url, params, timeout):
        if url.endswith("/values:batchGet") and params["ranges"][0].endswith(":Z"):
            return fake._res({"valueRanges": [{"values": fake.values[t]} for t in ("Deals", "Quotas", "Reps")]})
        if url.endswith("/values:batchGet"):  # re-reading rows before writing IDs
            return fake._res({"valueRanges": [{"values": [fake.values["Deals"][int(r.split("!A")[1].split(":")[0]) - 1]]}
                                              for r in params["ranges"]]})
        return fake.get_orig(url, params, timeout)

    fake.get = get
    written = []
    fake.post = lambda url, json, timeout: written.append(json) or fake._res({})
    from .conftest import make_user
    make_user(session, "pat@example.com", name="Pat")

    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    status = sheet_sync.run(session_factory=factory, api=SheetsApi(SHEET_ID, tmp_path / "k.json", session=fake))
    assert status["ok"], status["message"]
    assert status["source"] == "data tabs"
    assert status["counts"]["deals"] == 4 and status["counts"]["months"] == 2
    assert len(written[0]["data"]) == 3  # IDs filled in on the sheet

    session.expire_all()
    beta = session.query(models.Deal).filter_by(sheet_ref="D00008").one()
    assert (beta.client.name, beta.client.location, beta.notes, beta.deal_date) == ("Beta", "North", "PO 7", date(2026, 9, 15))
    assert beta.created_by.name == "Pat" and beta.sheet_plus
    house = session.query(models.Rep).filter_by(name="HOUSE").one()
    assert house.counts_toward_total is False
    assert session.query(models.Rep).filter_by(name="OLD").one().active is False


# --- View tabs (Board, Overview) ---

def test_board_formulas_layout():
    from app import sheet_views as v

    f = v.board_formulas()
    assert len(f) == v.LEGEND_ROW and all(len(r) == v.BOARD_COLUMNS for r in f)
    assert f[0][13:15] == ["QUOTA", "SALES"] and f[v.TOTAL_ROW - 1][0] == "MONTHLY TOTAL"
    for k in range(v.SLOTS):
        r = v.slot_row(k)
        assert f[r - 1][0] == f'=IFERROR(INDEX($S$2:$S,{k + 1}),"")'
        # Clients, items and amounts all filter on this block's rep.
        for offset in range(3):
            assert f"=$A{r})),1,12)" in f[r - 1 + offset][1]
        assert f"$A{r}" in f[r][0] and f"$A{r}" in f[r - 1][13] and f"$A{r}" in f[r - 1][14]
    # Data columns are referenced by header, so these follow DEALS_HEADERS.
    assert "'Deals'!$J$2:$J" in f[1][14] and "'Deals'!$E$2:$E" in f[1][1]


def test_write_views_keeps_an_overview_it_did_not_build(tmp_path):
    from app import sheet_views as v

    fake = FakeSheets(tabs=("926", "Overview", "Deals"))
    fake.get_orig = fake.get

    def get(url, params, timeout):
        if params.get("fields", "").startswith("sheets(properties(title,sheetId),protectedRanges"):
            return fake._res({"sheets": [{"properties": {"title": t, "sheetId": i},
                                          "protectedRanges": [{"description": d} for d in fake.protection.get(t, [])]}
                                         for t, i in fake.tabs.items()]})
        return fake.get_orig(url, params, timeout)

    fake.protection = {}
    fake.get = get
    post = fake.post

    def post_tracking(url, json, timeout):
        for r in json.get("requests", []):
            if "updateSheetProperties" in r and "title" in r["updateSheetProperties"]["properties"]:
                sid, title = r["updateSheetProperties"]["properties"]["sheetId"], r["updateSheetProperties"]["properties"]["title"]
                fake.tabs = {(title if i == sid else t): i for t, i in fake.tabs.items()}
        res = post(url, json, timeout)
        if "requests" in json:
            for r in json["requests"]:
                if "addProtectedRange" in r:
                    sid = r["addProtectedRange"]["protectedRange"]["range"]["sheetId"]
                    title = next(t for t, i in fake.tabs.items() if i == sid)
                    fake.protection.setdefault(title, []).append(r["addProtectedRange"]["protectedRange"]["description"])
        return res

    fake.post = post_tracking
    api = SheetsApi(SHEET_ID, tmp_path / "key.json", session=fake)
    notes = v.write_views(api)
    assert 'Renamed the existing Overview tab to "Overview (old)" (kept as it was)' in notes
    assert {"Board", "Overview", "Overview (old)"} <= set(fake.tabs)
    assert fake.values["Board"][0][13] == "QUOTA"

    # Our own tabs are rebuilt in place, and the old one is left alone.
    notes = v.write_views(api)
    assert notes[:2] == ["Rebuilt Board", "Rebuilt Overview"]
    assert sorted(t for t in fake.tabs if "Overview" in t) == ["Overview", "Overview (old)"]
