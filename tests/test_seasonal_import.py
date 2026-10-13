"""`import_calendar` loads the seizoenskalender into Seasonal Produce, tagged fresh or stored.

The page is a made-up fixture in the shape of the Voedingscentrum page: the real calendar is
never committed (ADR 0003).
"""

from pathlib import Path

import pytest

from pickled.ingredients import Aisle, Ingredient, find_ingredient
from pickled.seasonal import CalendarError, Freshness, import_calendar, seasonal_for

FIXTURE = Path(__file__).parent / "fixtures" / "seasonal_calendar_made_up.html"

# Fresh-harvest months for the fixture's storage crops; outside them they're sold from storage.
STORAGE_CROPS = {"wortel": {7, 8, 9, 10}, "appel": {8, 9, 10}}


@pytest.fixture(scope="module")
def page():
    return FIXTURE.read_text()


def produce(session, month) -> dict[str, Freshness]:
    return {item.ingredient.name: item.freshness for item in seasonal_for(session, month)}


def test_a_month_lists_its_seasonal_vegetables_and_fruit(db_session, page):
    import_calendar(db_session, page, storage_crops=STORAGE_CROPS)

    assert produce(db_session, 5) == {
        "asperge": Freshness.FRESH,
        "spinazie": Freshness.FRESH,
        "aardbei": Freshness.FRESH,
    }


def test_a_storage_crop_is_fresh_in_its_harvest_months_and_stored_outside_them(db_session, page):
    import_calendar(db_session, page, storage_crops=STORAGE_CROPS)

    assert produce(db_session, 9)["wortel"] is Freshness.FRESH
    assert produce(db_session, 9)["appel"] is Freshness.FRESH
    assert produce(db_session, 1)["wortel"] is Freshness.STORED
    assert produce(db_session, 4)["appel"] is Freshness.STORED
    assert produce(db_session, 1)["boerenkool"] is Freshness.FRESH


def test_the_committed_storage_crops_tag_winter_apples_as_stored(db_session, page):
    import_calendar(db_session, page)

    assert produce(db_session, 1)["appel"] is Freshness.STORED
    assert produce(db_session, 9)["appel"] is Freshness.FRESH


def test_a_name_the_catalogue_knows_points_to_its_ingredient(db_session, page):
    rode_kool = Ingredient(name="rode kool", aisle=Aisle.GROENTE_FRUIT)
    db_session.add(rode_kool)
    db_session.flush()

    import_calendar(db_session, page, storage_crops=STORAGE_CROPS)

    [rodekool] = [
        item for item in seasonal_for(db_session, 11) if item.ingredient.name == "rode kool"
    ]
    assert rodekool.ingredient_id == rode_kool.id


def test_a_name_the_catalogue_lacks_becomes_a_new_produce_ingredient(db_session, page):
    assert find_ingredient(db_session, "pruim") is None

    import_calendar(db_session, page, storage_crops=STORAGE_CROPS)

    pruim = find_ingredient(db_session, "pruim")
    assert pruim is not None
    assert pruim.aisle is Aisle.GROENTE_FRUIT
    assert "pruim" in produce(db_session, 8)


def test_importing_again_replaces_the_seasonal_produce(db_session, page):
    import_calendar(db_session, page, storage_crops=STORAGE_CROPS)
    import_calendar(db_session, page.replace("Spinazie", "Snijbiet"), storage_crops=STORAGE_CROPS)

    assert produce(db_session, 5) == {
        "asperge": Freshness.FRESH,
        "snijbiet": Freshness.FRESH,
        "aardbei": Freshness.FRESH,
    }


BROKEN_PAGES = {
    "no calendar on the page": lambda page: page.replace('"FAQPage"', '"WebPage"'),
    "a month missing": lambda page: page.replace('"name": "Mei"', '"name": "Juni"'),
    "a month name it doesn't know": lambda page: page.replace('"name": "Mei"', '"name": "Mai"'),
    "a list it doesn't know": lambda page: page.replace("Seizoensfruit", "Seizoenskruiden", 1),
    "a month without its fruit": lambda page: page.replace("<h3>Seizoensfruit</h3>", "", 1),
    "an empty item": lambda page: page.replace("<li> Peer</li>", "<li> </li>", 1),
    "JSON that doesn't parse": lambda page: page.replace('"mainEntity": [', '"mainEntity": [[', 1),
}


@pytest.mark.parametrize("breaking", BROKEN_PAGES.values(), ids=BROKEN_PAGES.keys())
def test_a_page_it_cannot_read_fails_and_keeps_the_old_seasonal_produce(db_session, page, breaking):
    import_calendar(db_session, page, storage_crops=STORAGE_CROPS)
    before = produce(db_session, 5)

    with pytest.raises(CalendarError):
        import_calendar(db_session, breaking(page), storage_crops=STORAGE_CROPS)

    assert produce(db_session, 5) == before


def test_a_year_round_staple_the_calendar_lists_is_left_out(db_session, page):
    page = page.replace("<li> Peer</li>", "<li> Peer</li><li> Aardappelen</li>", 1)

    import_calendar(db_session, page, storage_crops=STORAGE_CROPS)

    assert "aardappelen" not in produce(db_session, 10)
    assert "peer" in produce(db_session, 10)


def test_two_names_for_one_ingredient_in_a_month_are_one_seasonal_produce(db_session, page):
    db_session.add(Ingredient(name="peer", aliases=["peren"], aisle=Aisle.GROENTE_FRUIT))
    db_session.flush()
    page = page.replace("<li> Peer</li>", "<li> Peer</li><li> Peren</li>", 1)

    import_calendar(db_session, page, storage_crops=STORAGE_CROPS)

    assert [item.ingredient.name for item in seasonal_for(db_session, 10)].count("peer") == 1


def test_a_month_lists_fresh_produce_before_stored_then_by_name(db_session, page):
    import_calendar(db_session, page, storage_crops=STORAGE_CROPS)

    assert [(item.ingredient.name, item.freshness) for item in seasonal_for(db_session, 1)] == [
        ("boerenkool", Freshness.FRESH),
        ("prei", Freshness.FRESH),
        ("appel", Freshness.STORED),
        ("wortel", Freshness.STORED),
    ]


def test_before_any_import_a_month_has_no_seasonal_produce(db_session):
    assert seasonal_for(db_session, 1) == []
