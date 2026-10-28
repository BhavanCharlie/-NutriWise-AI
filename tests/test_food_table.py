import pytest

from app.food_table import estimate_from_table, lookup_food, parse_meal


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2 rotis and a bowl of dal", [(2, "serving", "rotis"), (1, "bowl", "dal")]),
        ("half a plate of poha", [(0.5, "plate", "poha")]),
        ("200g rice", [(200, "g", "rice")]),
        ("1/2 bowl fried rice", [(0.5, "bowl", "fried rice")]),
        ("three slices of bread", [(3, "slice", "bread")]),
        ("an apple", [(1, "serving", "apple")]),       # 'an' is a quantity...
        ("apple", [(1, "serving", "apple")]),          # ...but the 'a' in 'apple' is not
        ("dal + rice & curd", [(1, "serving", "dal"), (1, "serving", "rice"), (1, "serving", "curd")]),
        ("extra butter", [(1, "serving", "butter")]),  # filler words removed
        ("2 Cups of Chai.", [(2, "cup", "chai")]),     # case and punctuation
    ],
)
def test_parse_meal(text, expected):
    assert [(i.quantity, i.unit, i.name) for i in parse_meal(text)] == expected


@pytest.mark.parametrize(
    "name, key",
    [
        ("roti", "roti"),
        ("rotis", "roti"),                 # plural
        ("chapati", "roti"),               # alias
        ("chai", "tea"),
        ("fried rice", "fried rice"),      # longest key wins over 'rice'
        ("masala dosa", "dosa"),           # whole-word match inside the name
        ("peanut butter", "peanut butter"),
    ],
)
def test_lookup_food(name, key):
    assert lookup_food(name)[0] == key


def test_unknown_food_is_not_matched():
    assert lookup_food("pizza") is None
    assert lookup_food("eggplant") is None  # 'egg' must match a whole word only


def test_estimate_sums_items():
    e = estimate_from_table("2 rotis and a bowl of dal")
    assert e.calories == 2 * 120 + 180
    assert e.source == "local_table"


def test_estimate_scales_by_grams():
    assert estimate_from_table("300g rice").calories == 195 * 2  # one bowl is 150 g


def test_fuzzy_matches_are_explained_in_the_note():
    assert "approximated as 'dosa'" in estimate_from_table("masala dosa").note


def test_one_unknown_food_means_no_table_estimate():
    assert estimate_from_table("2 rotis and pizza") is None
    assert estimate_from_table("") is None
