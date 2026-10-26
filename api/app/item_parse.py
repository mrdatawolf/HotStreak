"""Split item text from the sheet into brand + model and link it to the item catalog.

"Sharp BP-71C31" → (Sharp, BP-71C31); "SH - C507F" → (Sharp, C507F); "Lex M3250" → (Lexmark, M3250).
Text without a brand gets one when the model makes it unambiguous (BP-/MX- → Sharp, XM/XC → Lexmark),
or when the sheet only ever names one brand for that model. Otherwise the brand stays empty and the
whole text is the model ("Refi", "Various").

Catalog items are matched by brand + model ignoring case, spaces and punctuation ("XM-3250" = "XM3250"),
so an admin can rename an item or set its category on Admin → Items and later syncs keep using it.
"""

import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .names import name_key

# Brand words typed in front of a model → the brand's name.
BRANDS = {
    "sharp": "Sharp", "sh": "Sharp", "lexmark": "Lexmark", "lex": "Lexmark", "kyocera": "Kyocera",
    "epson": "Epson", "toshiba": "Toshiba", "hp": "HP", "canon": "Canon", "ricoh": "Ricoh",
    "xerox": "Xerox", "brother": "Brother", "papercut": "PaperCut",
}
# Model prefixes only one brand uses.
MODEL_BRANDS = [
    (re.compile(r"^(BP|MX)-", re.IGNORECASE), "Sharp"),
    (re.compile(r"^X[MC]-?\d", re.IGNORECASE), "Lexmark"),
]
LEADING_BRAND = re.compile(r"^([A-Za-z]+)\s*(?:-\s*|\s)\s*(\S.*)$")


def split_brand(text: str) -> tuple[str | None, str]:
    """'Sharp BP-71C31' → ('Sharp', 'BP-71C31'); 'Refi' → (None, 'Refi')."""
    text = text.strip()
    match = LEADING_BRAND.match(text)
    if match and match[1].casefold() in BRANDS:
        brand, model = BRANDS[match[1].casefold()], match[2].strip()
    else:
        brand, model = None, text
    if brand is None:
        brand = next((b for rx, b in MODEL_BRANDS if rx.match(model)), None)
    return brand, model


def item_key(brand: str | None, model: str) -> tuple[str, str]:
    return (name_key(brand) if brand else "", name_key(model))


class Catalog:
    """Finds or creates the catalog item for each piece of item text."""

    def __init__(self, db: Session, texts: list[str] = ()):
        self.db = db
        self.items: dict[tuple[str, str], models.Item] = {}
        # Brands named for each model, from the catalog and from this batch of text.
        self.brands: dict[str, dict[str, str]] = defaultdict(dict)
        for item in db.scalars(select(models.Item).order_by(models.Item.id)):
            self._remember(item)
        for text in texts:
            brand, model = split_brand(text)
            if brand:
                self.brands[name_key(model)].setdefault(name_key(brand), brand)

    def _remember(self, item: models.Item) -> None:
        self.items.setdefault(item_key(item.brand, item.model), item)
        if item.brand:
            self.brands[name_key(item.model)].setdefault(name_key(item.brand), item.brand)

    def item_for(self, text: str) -> models.Item:
        brand, model = split_brand(text)
        if brand is None:
            # "C2240" when the sheet only ever says "Lexmark C2240".
            known = self.brands.get(name_key(model), {})
            if len(known) == 1:
                brand = next(iter(known.values()))
        item = self.items.get(item_key(brand, model))
        if item is None:
            item = models.Item(brand=brand[:100] if brand else None, model=model[:100], category="other")
            self.db.add(item)
            self._remember(item)
        return item
