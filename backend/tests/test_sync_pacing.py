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


def test_the_whole_sweep_lands_on_two_hours_however_many_slices_it_takes(monkeypatch):
    """The number that matters. The crawl bisects: 200k ads came out as ~1000 slices, not the
    400 leaf pages the arithmetic predicts, and each partition used to get its OWN budget —
    which is how a two-hour design took four. The gap is recomputed against the remaining
    budget before every request, so the sweep lands on the deadline either way."""
    monkeypatch.delenv("SYNC_TARGET_SECONDS", raising=False)
    for real_requests in (400, 1000, 2000):
        sweep = sync_mod.Sweep(expected=400 * 2.5, target=7200)      # the estimate
        clock = [0.0]
        monkeypatch.setattr(sync_mod.time, "monotonic", lambda: clock[0])
        sweep.deadline = 7200.0
        for i in range(real_requests):
            # The crawl reports how far through the catalogue it is; that is what keeps a
            # sweep whose request count is double the estimate on the two-hour budget.
            sweep.progress((i + 1) / real_requests)
            clock[0] += sweep.gap()
        # Never past the budget by more than the last request's own floor, and never a
        # fraction of it either.
        assert clock[0] <= 7200 + sync_mod.ENCAR_MIN_GAP, (real_requests, clock[0])
        assert clock[0] > 6800, (real_requests, clock[0])


def test_a_sweep_that_runs_long_speeds_up_instead_of_doubling(monkeypatch):
    """Past the deadline the gap drops to the client's own floor: 1000 leftover requests cost
    twenty minutes, not another two hours."""
    monkeypatch.delenv("SYNC_TARGET_SECONDS", raising=False)
    sweep = sync_mod.Sweep(expected=10, target=7200)
    clock = [7300.0]                                                 # already over
    monkeypatch.setattr(sync_mod.time, "monotonic", lambda: clock[0])
    sweep.deadline = 7200.0
    assert sweep.gap() == sync_mod.ENCAR_MIN_GAP


def test_the_estimate_can_be_refined_while_the_crawl_runs():
    sweep = sync_mod.Sweep(expected=100, target=7200)
    first = sweep.gap()
    sweep.expect(1000)                                               # a partition reported in
    assert sweep.gap() < first                                       # more requests, tighter gaps
    sweep.expect(1)                                                  # never below what is done
    assert sweep.expected > sweep.done


def test_a_nested_pass_shares_the_budget_it_is_inside_of():
    """A facet pass inside a crawl must not start a second two-hour budget of its own."""
    async def run():
        async with sync_mod.paced_sweep(100) as outer:
            async with sync_mod.paced_sweep(100) as inner:
                assert inner is outer
            assert encar.pacer is not None      # and the outer one is still installed
        assert encar.pacer is None

    asyncio.run(run())


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


def test_the_sweep_installs_a_pacer_and_puts_the_client_back(monkeypatch):
    monkeypatch.delenv("SYNC_TARGET_SECONDS", raising=False)
    before = encar.min_interval

    async def run():
        async with sync_mod.paced_sweep(420):
            assert encar.pacer is not None
            assert encar.min_interval == before     # the floor itself is left alone
        assert encar.pacer is None

    asyncio.run(run())
    assert encar.min_interval == before


def test_the_pacer_is_removed_even_when_the_sweep_blows_up(monkeypatch):
    """A crawl aborted by an upstream failure must not leave every later request paced at
    seventeen seconds — including the detail fetches a visitor's page waits on."""
    monkeypatch.delenv("SYNC_TARGET_SECONDS", raising=False)

    async def run():
        with __import__("pytest").raises(RuntimeError):
            async with sync_mod.paced_sweep(420):
                raise RuntimeError("upstream count request failed")

    asyncio.run(run())
    assert encar.pacer is None


def test_visitors_are_not_slowed_by_a_running_sweep():
    """Interactive calls take the concurrency semaphore and skip the throttle entirely, so a
    two-hour sweep must not put seventeen seconds in front of somebody's car page."""
    import inspect

    src = inspect.getsource(type(encar).get_json)
    interactive = src.split("if interactive:", 1)[1].split("else:", 1)
    assert "_sem.acquire" in interactive[0]
    assert "_throttle" in interactive[1]            # the paced path, for the sweep only
