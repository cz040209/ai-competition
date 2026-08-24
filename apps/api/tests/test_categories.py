import pytest

from kira.categories import CATEGORIES, UNCATEGORISED, label_for, slugs


class TestVocabulary:
    def test_every_category_has_a_unique_slug(self):
        assert len(slugs()) == len(CATEGORIES)

    def test_slugs_are_lowercase_and_terse(self):
        assert all(slug.islower() and " " not in slug for slug in slugs())

    def test_covers_the_money_a_malaysian_household_moves(self):
        assert {"food", "groceries", "transport", "bills", "family", "charity"} <= set(slugs())

    def test_uncategorised_is_one_of_them(self):
        assert UNCATEGORISED in slugs()


class TestLabels:
    @pytest.mark.parametrize(
        ("slug", "expected"),
        [("food", "Food & drink"), ("family", "Family & gifts"), ("fees", "Fees & charges")],
    )
    def test_reads_the_way_a_person_would_say_it(self, slug, expected):
        assert label_for(slug) == expected

    def test_an_unknown_slug_still_reads_as_something(self):
        assert label_for("pet-grooming") == "Pet grooming"
