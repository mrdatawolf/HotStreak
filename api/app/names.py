import re


def name_key(name: str) -> str:
    """Spellings that differ only by case, spaces or punctuation are the same name
    ("Barton's Pools" = "Bartons Pools", "XM-3250" = "XM3250")."""
    return re.sub(r"[^0-9a-z]", "", name.casefold()) or name
