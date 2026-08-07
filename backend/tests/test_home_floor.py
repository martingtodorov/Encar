"""The landing view is a shop window: nothing under EUR 18 000, unless the visitor asks.

Someone who sorts by cheapest first is hunting a bargain — pushing 18k cars at them is the
opposite of helpful — and the counter must still advertise the whole library, not the slice
the floor leaves behind.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: E402


def test_the_bare_landing_view_is_floored():
    assert server.unfiltered({}) is True
    q = server.build_query({})
    server.apply_home_floor(q)
    assert q["sale_eur"]["$gte"] == server.HOME_MIN_EUR


def test_anything_the_visitor_narrows_lifts_the_floor():
    for narrowing in ({"q": "grandeur"}, {"makes": ["현대"]}, {"models": ["G80"]},
                      {"fuels": ["가솔린"]}, {"regions": ["서울"]}, {"year_min": 2020},
                      {"mileage_max": 50000}, {"price_min": 5000}, {"price_max": 9000},
                      {"only_inspection": True}, {"only_record": True},
                      {"only_diagnosed": True}, {"badges": ["3.5"]},
                      {"transmissions": ["오토"]}):
        assert server.unfiltered(narrowing) is False, narrowing


def test_sorting_and_paging_are_not_narrowing():
    # A sort or a page is not a filter: the landing view is still the landing view.
    assert server.unfiltered({"page": 3}) is True
    assert server.unfiltered({"lang": "ro"}) is True


def test_the_floor_only_ever_raises_a_price_window():
    # A visitor's own EUR 30 000 floor must survive.
    q = {"sale_eur": {"$gte": 30000, "$lte": 90000}}
    server.apply_home_floor(q)
    assert q["sale_eur"] == {"$gte": 30000, "$lte": 90000}
    # And a lower one is raised, keeping the ceiling.
    q = {"sale_eur": {"$gte": 2000, "$lte": 90000}}
    server.apply_home_floor(q)
    assert q["sale_eur"] == {"$gte": server.HOME_MIN_EUR, "$lte": 90000}


def test_an_empty_price_window_is_not_invented():
    q = {}
    server.apply_home_floor(q)
    assert q["sale_eur"] == {"$gte": server.HOME_MIN_EUR}
