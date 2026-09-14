"""The catalogue sweep is paced so a full run takes two hours, not nine minutes.

The 403s from Encar arrived in runs, right after a sweep: ~436 requests at the client's 1.2s
floor is a burst, and a burst is what a WAF is built to answer. One knob does it — the sweep
raises the client's own minimum gap for its duration — so the leaf pages, the bisection
probes and the facet passes are all paced by the same number, and a visitor opening an
uncached car is not slowed at all.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sync as sync_mod  # noqa: E402
from encar import encar  # noqa: E402


def test_a_full_sweep_is_spread_over_two_hours(monkeypatch):
    monkeypatch.delenv("SYNC_TARGET_SECONDS", raising=False)
    assert sync_mod.SYNC_TARGET_SECONDS == 7200
    gap = sync_mod._sweep_gap(420)                  # ~210k listings at 500 a page
    assert 16 < gap < 18
    assert 7000 < gap * 420 < 7400                  # two hours, give or take a page


def test_the_gap_is_clamped_at_both_ends(monkeypatch):
    monkeypatch.delenv("SYNC_TARGET_SECONDS", raising=False)
    # A tiny catalogue must not sit for half an hour between two pages...
    assert sync_mod._sweep_gap(1) == sync_mod.SYNC_PAGE_GAP_MAX
    # ...and a huge one must not be paced faster than the client's own floor.
    assert sync_mod._sweep_gap(100000) == sync_mod.ENCAR_MIN_GAP
    assert sync_mod._sweep_gap(0) == sync_mod.SYNC_PAGE_GAP_MAX      # never divides by zero


def test_the_owner_can_change_it_from_the_environment(monkeypatch):
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "14400")
    assert 33 < sync_mod._sweep_gap(420) < 35       # four hours
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")
    assert sync_mod._sweep_gap(420) == sync_mod.ENCAR_MIN_GAP        # off, back to the floor


def test_the_sweep_slows_the_client_down_and_puts_it_back(monkeypatch):
    monkeypatch.delenv("SYNC_TARGET_SECONDS", raising=False)
    before = encar.min_interval

    async def run():
        async with sync_mod.paced_sweep(420) as gap:
            assert encar.min_interval == gap > before
        assert encar.min_interval == before

    asyncio.run(run())
    assert encar.min_interval == before


def test_the_gap_is_restored_even_when_the_sweep_blows_up(monkeypatch):
    """A crawl aborted by an upstream failure must not leave every later request paced at
    seventeen seconds — including the detail fetches a visitor's page waits on."""
    monkeypatch.delenv("SYNC_TARGET_SECONDS", raising=False)
    before = encar.min_interval

    async def run():
        with __import__("pytest").raises(RuntimeError):
            async with sync_mod.paced_sweep(420):
                raise RuntimeError("upstream count request failed")

    asyncio.run(run())
    assert encar.min_interval == before


def test_visitors_are_not_slowed_by_a_running_sweep():
    """Interactive calls take the concurrency semaphore and skip the throttle entirely, so a
    two-hour sweep must not put seventeen seconds in front of somebody's car page."""
    import inspect

    src = inspect.getsource(type(encar).get_json)
    interactive = src.split("if interactive:", 1)[1].split("else:", 1)
    assert "_sem.acquire" in interactive[0]
    assert "_throttle" in interactive[1]            # the paced path, for the sweep only
