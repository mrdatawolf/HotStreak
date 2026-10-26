from sqlalchemy import select

from app import models
from app.item_parse import Catalog, split_brand


def test_split_brand():
    assert split_brand("Sharp BP-71C31") == ("Sharp", "BP-71C31")
    assert split_brand("SH - C507F") == ("Sharp", "C507F")
    assert split_brand("Lex M3250") == ("Lexmark", "M3250")
    assert split_brand("LEX-XM3250") == ("Lexmark", "XM3250")
    assert split_brand("Sharp-70C55") == ("Sharp", "70C55")
    # Brand from an unambiguous model prefix.
    assert split_brand("BP-70C31") == ("Sharp", "BP-70C31")
    assert split_brand("MX-C428F") == ("Sharp", "MX-C428F")
    assert split_brand("XM-3250") == ("Lexmark", "XM-3250")
    # Not a brand / not a product.
    assert split_brand("Refi") == (None, "Refi")
    assert split_brand("Sharp") == (None, "Sharp")
    assert split_brand("Used MX-C407F") == (None, "Used MX-C407F")
    assert split_brand('86" Aquos Board') == (None, '86" Aquos Board')


def test_catalog_matches_and_creates(session):
    session.add(models.Item(brand="Lexmark", model="XC4342", category="mfp"))
    session.flush()
    catalog = Catalog(session, ["Lexmark C2240", "C2240", "Sharp C407F", "Lexmark C407F", "C407F"])
    existing = catalog.item_for("XC-4342")
    assert (existing.brand, existing.model, existing.category) == ("Lexmark", "XC4342", "mfp")
    # The sheet only ever says Lexmark for C2240, so the bare model gets it too.
    assert catalog.item_for("C2240") is catalog.item_for("Lexmark C2240")
    # Two brands named for C407F: the bare model stays brand-less.
    assert catalog.item_for("C407F").brand is None
    assert catalog.item_for("Sharp BP-70C31") is catalog.item_for("BP 70C31")
    session.flush()
    assert len(session.scalars(select(models.Item)).all()) == 4
