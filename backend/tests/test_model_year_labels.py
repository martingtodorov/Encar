"""A renamed model must keep its production span.

The owner renamed Encar's `카이엔 (PO536)` to plain "Cayenne", and `display()` returned the
manual label and went home — so the one Cayenne with 530 cars behind it showed no years at all
while the other two generations did. A rename replaces the NAME, not the years.
"""
import os

import requests

import curate

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
PORSCHE = "포르쉐"


def _with_spans(**labels):
    curate._cache["years"] = {"카이엔 (PO536)": (2019, 2026), "카이엔": (2004, 2010),
                              "뉴 카이엔": (2011, 2018), "911": (2000, 2019)}
    curate._cache["label"] = {(2, v): l for v, l in labels.items()}


def test_a_renamed_model_keeps_its_years():
    _with_spans(**{"카이엔 (PO536)": "Cayenne"})
    assert curate.display(2, "카이엔 (PO536)", "Cayenne (PO536)") == "Cayenne (2019-)"
    # and the ones nobody renamed are untouched
    assert curate.display(2, "카이엔", "Cayenne") == "Cayenne (2004-2010)"
    assert curate.display(2, "뉴 카이엔", "New Cayenne") == "Cayenne (2011-2018)"


def test_a_rename_still_wins_over_the_crawled_name():
    _with_spans(**{"911": "Nine Eleven"})
    assert curate.display(2, "911", "911") == "Nine Eleven (2000-2019)"


def test_makes_and_trims_are_not_given_years():
    """Only models carry a span: a marque has no production years, and a trim's would be the
    model's and read as noise."""
    _with_spans(**{"포르쉐": "Porsche AG"})
    assert curate.display(1, "포르쉐", "Porsche") == "Porsche"
    assert curate.display(3, "카이엔", "Cayenne S") == "Cayenne S"


def test_a_model_with_no_span_is_left_alone():
    _with_spans()
    assert curate.display(2, "알 수 없음", "Unknown") == "Unknown"
    assert curate.display(2, "카이엔", "") == "Cayenne (2004-2010)".replace(
        "Cayenne", "카이엔")  # no translation available: the raw value keeps the span


def test_every_porsche_generation_shows_years_over_the_api():
    r = requests.get(f"{BASE_URL}/api/meta/taxonomy",
                     params={"level": 2, "make": PORSCHE, "lang": "en"}, timeout=60)
    assert r.status_code == 200, r.text
    cayennes = [i for i in r.json()["items"] if "Cayenne" in i["label"]]
    assert len(cayennes) >= 3, cayennes
    for item in cayennes:
        assert "(" in item["label"] and ")" in item["label"], item["label"]
