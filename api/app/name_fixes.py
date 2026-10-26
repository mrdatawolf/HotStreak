"""Fixes for client and item names typed on the sheet.

"Coast Central Crediit Union" → "Coast Central Credit Union"; "Sharp MX-C428F" → "MX-C428F".
A fix is stored by the normalized spelling (names.name_key), applied to the database right
away, and re-applied by every sheet sync. A fix whose target is its own spelling marks the name as
checked, so it stops being suggested.

Suggestions: clients are matched loosely (typos); items only when they're the same model under a
different brand ("Lexmark C407F", "Sharp C407F"), since near-identical model numbers ("BP-70C31",
"BP-70C36") are different machines. Item text is already merged by brand + model in the catalog
(item_parse.py), so "Sharp MX-C428F" and "MX-C428F" need no fix.
"""

import re
from collections import Counter
from difflib import get_close_matches

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models
from .item_parse import Catalog, split_brand
from .names import name_key

CLIENT_CUTOFF = 0.85
MAX_SUGGESTIONS = 3


def model_key(name: str) -> str:
    """An item's model with any leading brand dropped: "Sharp MX-C428F" and "MX-C428F" → "mxc428f"."""
    return name_key(split_brand(name)[1])


# --- Clients ---


def get_or_create_client(db: Session, name: str) -> models.Client:
    key = name_key(name)
    for c in db.scalars(select(models.Client).where(models.Client.location.is_(None)).order_by(models.Client.id)):
        if name_key(c.name) == key:
            return c
    client = models.Client(name=name)
    db.add(client)
    return client


def delete_unused_clients(db: Session, keys: set[str]) -> None:
    """Remove clients with one of these spellings that no deal uses any more."""
    used = select(models.Deal.client_id)
    for c in db.scalars(select(models.Client).where(models.Client.location.is_(None), models.Client.id.not_in(used))):
        if name_key(c.name) in keys:
            db.delete(c)


def deals_spelled(db: Session, keys: set[str]) -> list[models.Deal]:
    """Sheet deals whose client was typed with one of these spellings."""
    deals = db.scalars(select(models.Deal).where(models.Deal.sheet_client.is_not(None))).all()
    return [d for d in deals if name_key(d.sheet_client) in keys]


def lines_spelled(db: Session, keys: set[str]) -> list[models.DealLine]:
    """Sheet deal lines whose item was typed with one of these spellings."""
    lines = db.scalars(select(models.DealLine).where(models.DealLine.sheet_description.is_not(None))).all()
    return [line for line in lines if name_key(line.sheet_description) in keys]


def rename(db: Session, kind: str, keys: set[str], target_name: str) -> None:
    """Put everything typed with these spellings under `target_name`."""
    if kind == "item":
        item = Catalog(db).item_for(target_name)
        for line in lines_spelled(db, keys):
            line.description = target_name
            line.item = item
        return
    target = get_or_create_client(db, target_name)
    moved_from = set()
    for deal in deals_spelled(db, keys):
        moved_from.add(name_key(deal.client.name))
        deal.client = target
    db.flush()
    delete_unused_clients(db, moved_from - {name_key(target_name)})


# --- Fixes ---


def save_fix(db: Session, kind: str, source_name: str, target_name: str, user_id: int | None) -> models.NameFix:
    """Treat `source_name` (as typed on the sheet) as `target_name`, which may be a new name. Doesn't commit."""
    key, target_key = name_key(source_name), name_key(target_name)
    keys = {key}
    # Point earlier fixes at the new target instead of chaining through this one.
    for earlier in db.scalars(select(models.NameFix).where(models.NameFix.kind == kind)):
        if name_key(earlier.target_name) == key and earlier.source_key != key and target_key != key:
            earlier.target_name = target_name
            keys.add(earlier.source_key)

    fix = db.scalar(select(models.NameFix).where(models.NameFix.kind == kind, models.NameFix.source_key == key))
    if fix is None:
        fix = models.NameFix(kind=kind, source_key=key)
        db.add(fix)
    fix.source_name, fix.target_name, fix.created_by_id = source_name, target_name, user_id
    rename(db, kind, keys, target_name)
    db.flush()
    return fix


def undo_fix(db: Session, fix: models.NameFix) -> None:
    """Put things back under the name as typed on the sheet. Doesn't commit."""
    if fix.kind == "item":
        typed = [line.sheet_description for line in lines_spelled(db, {fix.source_key})]
    else:
        typed = [d.sheet_client for d in deals_spelled(db, {fix.source_key})]
    db.delete(fix)
    db.flush()
    if typed:
        rename(db, fix.kind, {fix.source_key}, Counter(typed).most_common(1)[0][0])
    if fix.kind == "client":
        delete_unused_clients(db, {name_key(fix.target_name)})
    db.flush()


# --- The list for the fix screens ---


def sheet_names(db: Session, kind: str) -> list[dict]:
    """One row per spelling on the sheet (case/punctuation differences grouped): how it's typed, the
    name it goes under now, its fix, and likely matches (for spellings not yet fixed or checked)."""
    if kind == "item":
        # Items show as their catalog item ("Sharp MX-C428F"), so spellings already merged there match.
        q = (select(models.DealLine.sheet_description, models.Item.brand, models.Item.model, func.count())
             .join(models.Item).where(models.DealLine.sheet_description.is_not(None))
             .group_by(models.DealLine.sheet_description, models.Item.id))
        found = [(spelling, f"{brand} {model}" if brand else model, count) for spelling, brand, model, count in db.execute(q)]
    else:
        q = (select(models.Deal.sheet_client, models.Client.name, func.count())
             .join(models.Client).where(models.Deal.sheet_client.is_not(None))
             .group_by(models.Deal.sheet_client, models.Client.name))
        found = db.execute(q).all()

    rows: dict[str, dict] = {}
    for spelling, current, count in found:
        row = rows.setdefault(name_key(spelling), {
            "key": name_key(spelling), "spellings": Counter(), "count": 0,
            "current_name": current, "fix": None, "suggestions": [],
        })
        row["spellings"][spelling] += count
        row["count"] += count

    for fix in db.scalars(select(models.NameFix).where(models.NameFix.kind == kind)):
        if fix.source_key in rows:
            rows[fix.source_key]["fix"] = fix

    # Usage of each current name, to offer the most-used match first.
    usage: Counter[str] = Counter()
    for row in rows.values():
        usage[row["current_name"]] += row["count"]
    by_key = {name_key(n): n for n in usage}
    by_model: dict[str, list[str]] = {}
    for n in sorted(usage, key=lambda n: -usage[n]):
        by_model.setdefault(model_key(n), []).append(n)

    for row in rows.values():
        if row["fix"] is not None:
            continue
        own = row["current_name"]
        if kind == "item":
            matches = by_model.get(model_key(own), [])
        else:
            matches = [by_key[k] for k in get_close_matches(name_key(own), list(by_key), n=MAX_SUGGESTIONS + 1,
                                                              cutoff=CLIENT_CUTOFF)]
        row["suggestions"] = [m for m in matches if name_key(m) != name_key(own)][:MAX_SUGGESTIONS]

    out = []
    for row in rows.values():
        row["spellings"] = [s for s, _ in row["spellings"].most_common()]
        out.append(row)
    return sorted(out, key=lambda r: r["spellings"][0].casefold())


def suggestion_groups(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Group unfixed names linked by suggestions, each with the name the group should go under: the
    most-used, then the one with the fewest words found nowhere else (typos are rare words), then the longest.
    Each group lists only the names that directly match that name."""
    parent: dict[str, str] = {}

    def find(k: str) -> str:
        while parent.setdefault(k, k) != k:
            k = parent[k]
        return k

    for r in rows:
        if r["fix"] is None:
            for s in r["suggestions"]:
                parent[find(name_key(s))] = find(name_key(r["current_name"]))

    by_current: dict[str, list[dict]] = {}
    for r in rows:
        by_current.setdefault(name_key(r["current_name"]), []).append(r)
    word_use = Counter(w for n in {r["current_name"] for r in rows} for w in set(re.findall(r"[0-9a-z]+", n.casefold())))

    groups: dict[str, list[str]] = {}
    for k in list(parent):
        groups.setdefault(find(k), []).append(k)
    out = []
    for keys in groups.values():
        members = [r for k in keys for r in by_current.get(k, [])]
        names = {r["current_name"] for r in members}
        if len(names) < 2:
            continue

        def rank(name: str):
            used = sum(r["count"] for r in members if r["current_name"] == name)
            rare = sum(word_use[w] == 1 for w in set(re.findall(r"[0-9a-z]+", name.casefold())))
            return (used, -rare, len(name))

        target = max(names, key=rank)
        target_key = name_key(target)
        target_suggests = {name_key(x) for r in members if name_key(r["current_name"]) == target_key for x in r["suggestions"]}
        # Only names that match the target itself, not via a chain ("Corning School District" ~
        # "Redding School District" through a third name).
        direct = [r for r in members if name_key(r["current_name"]) == target_key
                  or name_key(r["current_name"]) in target_suggests
                  or target_key in {name_key(x) for x in r["suggestions"]}]
        out.append((target, direct))
    return sorted(out, key=lambda g: g[0].casefold())


def apply_suggestions(db: Session, kind: str, user_id: int | None) -> list[tuple[str, str]]:
    """Fix every suggested match at once (see suggestion_groups). Returns (typed, now) pairs. Doesn't commit."""
    done = []
    for target, members in suggestion_groups(sheet_names(db, kind)):
        for r in members:
            if r["fix"] is None and r["current_name"] != target:
                save_fix(db, kind, r["spellings"][0], target, user_id)
                done.append((r["spellings"][0], target))
    return done
