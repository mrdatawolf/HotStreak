from datetime import date

from sqlalchemy import select

from app import models, name_fixes
from app.sheet_import import Cell, parse_tabs, sync

TODAY = date(2026, 10, 23)


def month(*deals):
    """A one-rep month tab: deals are (client, amount) or (client, amount, items)."""
    deals = [(d + (None,))[:3] for d in deals]
    return [[Cell("MONTH"), *[Cell() for _ in deals], Cell("QUOTA"), Cell("SALES")],
            [Cell("KELSEY"), *[Cell(c) for c, _, _ in deals], Cell(40)],
            [Cell(), *[Cell(i) for _, _, i in deals]],
            [Cell(), *[Cell(a) for _, a, _ in deals]],
            [Cell("MONTHLY TOTAL")]]


def deal(session, ref):
    return session.scalar(select(models.Deal).where(models.Deal.sheet_ref == ref))


TABS = {"926": month(("Copper Canyon Credit Union", 10.0, "MX-C428F"), ("Copper Canyon Crediit Union", 20.0, "Sharp MX-C428F"),
                     ("Greenfield County", 5.0, "BP-70C31"), ("Copper Canyon Credit Union", 1.0, "BP-70C36  mx-c428f"))}


def synced(session, tabs=TABS):
    sync(session, parse_tabs(tabs), TODAY)
    session.commit()


def rows_by_name(session, kind):
    return {r["spellings"][0]: r for r in name_fixes.sheet_names(session, kind)}


def test_model_key():
    assert name_fixes.model_key("Sharp MX-C428F") == name_fixes.model_key("MX-C428F") == "mxc428f"
    assert name_fixes.model_key("SH - C507F") == name_fixes.model_key("Sharp C507F")
    assert name_fixes.model_key("Sharp") == "sharp"


def test_suggests_close_client_spellings(session):
    synced(session)
    rows = rows_by_name(session, "client")
    assert rows["Copper Canyon Crediit Union"]["suggestions"] == ["Copper Canyon Credit Union"]
    assert rows["Copper Canyon Credit Union"]["suggestions"] == ["Copper Canyon Crediit Union"]
    assert rows["Greenfield County"]["suggestions"] == []


def test_items_merge_by_brand_and_model(session):
    synced(session)
    rows = rows_by_name(session, "item")
    # "MX-C428F" and "mx-c428f" are grouped automatically; most-used spelling wins.
    assert rows["MX-C428F"]["spellings"] == ["MX-C428F", "mx-c428f"] and rows["MX-C428F"]["count"] == 2
    assert deal(session, "926!E2").lines[1].description == "MX-C428F"
    # With or without the brand, it's the same catalog item, so there's nothing to fix.
    assert rows["MX-C428F"]["current_name"] == rows["Sharp MX-C428F"]["current_name"] == "Sharp MX-C428F"
    assert deal(session, "926!B2").lines[0].item is deal(session, "926!C2").lines[0].item
    assert rows["Sharp MX-C428F"]["suggestions"] == []
    # Different models aren't suggested, however close.
    assert rows["BP-70C31"]["suggestions"] == [] and rows["BP-70C36"]["suggestions"] == []


def test_items_suggest_same_model_under_another_brand(session):
    synced(session, {"926": month(("A", 1.0, "Sharp C407F"), ("B", 1.0, "Lexmark C407F"), ("C", 1.0, "Sharp C407F"))})
    rows = rows_by_name(session, "item")
    assert rows["Lexmark C407F"]["suggestions"] == ["Sharp C407F"]


def test_client_fix_moves_deals_and_survives_resync(session):
    synced(session)
    name_fixes.save_fix(session, "client", "Copper Canyon Crediit Union", "Copper Canyon Credit Union", None)
    session.commit()
    assert deal(session, "926!C2").client.name == "Copper Canyon Credit Union"
    names = {c.name for c in session.scalars(select(models.Client))}
    assert "Copper Canyon Crediit Union" not in names

    synced(session)
    assert deal(session, "926!C2").client.name == "Copper Canyon Credit Union"
    fixed = rows_by_name(session, "client")["Copper Canyon Crediit Union"]
    assert fixed["fix"].target_name == "Copper Canyon Credit Union" and fixed["suggestions"] == []


def test_item_fix_and_undo(session):
    synced(session)
    fix = name_fixes.save_fix(session, "item", "BP-70C36", "Sharp BP-70C31", None)
    session.commit()
    line = deal(session, "926!E2").lines[0]
    assert (line.description, line.sheet_description) == ("Sharp BP-70C31", "BP-70C36")
    assert line.item is deal(session, "926!D2").lines[0].item
    synced(session)
    assert deal(session, "926!E2").lines[0].item.model == "BP-70C31"

    name_fixes.undo_fix(session, fix)
    session.commit()
    line = deal(session, "926!E2").lines[0]
    assert (line.description, line.item.brand, line.item.model) == ("BP-70C36", "Sharp", "BP-70C36")


def test_fix_to_new_name_and_undo(session):
    synced(session)
    fix = name_fixes.save_fix(session, "client", "Greenfield County", "Greenfield County Office of Ed", None)
    session.commit()
    assert deal(session, "926!D2").client.name == "Greenfield County Office of Ed"

    name_fixes.undo_fix(session, fix)
    session.commit()
    assert deal(session, "926!D2").client.name == "Greenfield County"
    names = {c.name for c in session.scalars(select(models.Client))}
    assert "Greenfield County Office of Ed" not in names
    assert session.scalars(select(models.NameFix)).all() == []


def test_not_a_typo_stops_suggestions(session):
    synced(session)
    name_fixes.save_fix(session, "client", "Copper Canyon Credit Union", "Copper Canyon Credit Union", None)
    session.commit()
    assert rows_by_name(session, "client")["Copper Canyon Credit Union"]["suggestions"] == []
    assert deal(session, "926!B2").client.name == "Copper Canyon Credit Union"


def test_fixes_dont_chain(session):
    synced(session)
    name_fixes.save_fix(session, "client", "Copper Canyon Crediit Union", "Copper Canyon Credit Union", None)
    name_fixes.save_fix(session, "client", "Copper Canyon Credit Union", "Copper Canyon CU", None)
    session.commit()
    targets = {f.source_name: f.target_name for f in session.scalars(select(models.NameFix))}
    assert targets == {"Copper Canyon Crediit Union": "Copper Canyon CU", "Copper Canyon Credit Union": "Copper Canyon CU"}
    assert deal(session, "926!B2").client.name == deal(session, "926!C2").client.name == "Copper Canyon CU"


def test_apply_suggestions_uses_most_used_name(session):
    synced(session)
    done = name_fixes.apply_suggestions(session, "client", None)
    session.commit()
    assert done == [("Copper Canyon Crediit Union", "Copper Canyon Credit Union")]
    assert name_fixes.apply_suggestions(session, "item", None) == []


def test_suggestion_groups_pick_most_used_name(session):
    tabs = {"926": month(("Fairing School District", 3.0), ("Fairing School District", 1.0),
                         ("Fairin School District", 1.0), ("Holding School Districts", 1.0))}
    synced(session, tabs)
    groups = name_fixes.suggestion_groups(name_fixes.sheet_names(session, "client"))
    [(target, members)] = groups
    assert target == "Fairing School District"
    assert "Fairin School District" in {m["current_name"] for m in members}
