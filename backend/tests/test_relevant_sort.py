"""The 'relevant' sort must RANK the results, never shrink them."""
import re

import requests


def _base():
    env = open("/app/frontend/.env").read()
    return re.search(r"REACT_APP_BACKEND_URL=(\S+)", env).group(1).rstrip("/") + "/api"


BASE = _base()
TASTE = {
    "makes": {"벤츠": 9}, "models": {"E-Class W213": 5}, "fuels": {"디젤": 3},
    "samples": [[30000, 50000, 2]], "lang": "en",
}


def search(**extra):
    body = {"lang": "en", "page": 1, "page_size": 24, **extra}
    r = requests.post(f"{BASE}/search", json=body, timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


def test_relevant_returns_the_same_total_as_any_other_sort():
    plain = search(sort="newest")
    ranked = search(sort="relevant", taste=TASTE)
    guest = search(sort="relevant")
    assert ranked["total"] == plain["total"], "ranking must not shrink the result set"
    assert guest["total"] == plain["total"]

    narrowed = {"makes": [plain["items"][0]["manufacturer"]]}
    a = search(sort="price_asc", **narrowed)
    b = search(sort="relevant", taste=TASTE, **narrowed)
    assert a["total"] == b["total"], "ranking must not shrink a filtered result set either"


def test_the_shop_window_floor_only_applies_to_the_bare_landing_view():
    """The landing view hides cars under HOME_MIN_EUR, but a bargain hunter is not fenced in.

    `price_asc` says "cheapest first", so pushing the floor at that visitor would be the
    opposite of helpful — and the counter still advertises the whole library either way.
    """
    window = search(sort="newest")
    hunter = search(sort="price_asc")
    assert hunter["total"] > window["total"], "sorting by price must lift the floor"
    assert window["total_all"] == hunter["total"], "the counter must show the whole library"
    assert min(i["sale_eur"] for i in window["items"]) >= 18000
    assert min(i["sale_eur"] for i in hunter["items"]) < 18000


def test_pages_walk_the_whole_pool_without_gaps_or_repeats():
    seen, pages = [], 12
    for page in range(1, pages + 1):
        data = search(sort="relevant", taste=TASTE, page=page, page_size=24)
        ids = [i["id"] for i in data["items"]]
        assert len(ids) == 24, f"page {page} came back short: {len(ids)}"
        seen += ids
    assert len(seen) == len(set(seen)), "the same car appeared on two pages"


def test_a_deep_page_still_works():
    deep = search(sort="relevant", taste=TASTE, page=60, page_size=24)
    assert len(deep["items"]) == 24
    assert deep["total"] > 1000


def test_one_brand_never_floods_a_page_and_never_repeats_back_to_back():
    data = search(sort="relevant", taste=TASTE, page=1, page_size=24)
    makes = [i.get("manufacturer_t") or i.get("manufacturer") for i in data["items"]]
    for a, b in zip(makes, makes[1:]):
        assert a != b, f"two {a} in a row"
    top = max(makes.count(m) for m in set(makes))
    assert top <= 6, f"one brand took {top} of 24"
