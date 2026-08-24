"""The vocabulary a transaction's category is drawn from.

One list, read by the API, the ledger's filter chips and — later — whatever
reads a receipt. Free text would let the same spending land under "Food",
"food" and "Makan", which no filter can put back together.
"""

from __future__ import annotations

from dataclasses import dataclass

UNCATEGORISED = "uncategorised"


@dataclass(frozen=True, slots=True)
class Category:
    slug: str
    label: str


CATEGORIES: tuple[Category, ...] = (
    Category("food", "Food & drink"),
    Category("groceries", "Groceries"),
    Category("transport", "Transport"),
    Category("bills", "Bills & utilities"),
    Category("home", "Home"),
    Category("health", "Health"),
    Category("shopping", "Shopping"),
    Category("fun", "Fun"),
    Category("family", "Family & gifts"),
    Category("education", "Education"),
    Category("charity", "Charity"),
    Category("fees", "Fees & charges"),
    Category(UNCATEGORISED, "Uncategorised"),
)

_BY_SLUG = {category.slug: category for category in CATEGORIES}


def slugs() -> tuple[str, ...]:
    return tuple(_BY_SLUG)


def label_for(slug: str) -> str:
    """The human label, or a readable fallback for a slug written before this list."""
    known = _BY_SLUG.get(slug)
    if known is not None:
        return known.label
    return slug.replace("-", " ").replace("_", " ").capitalize()
