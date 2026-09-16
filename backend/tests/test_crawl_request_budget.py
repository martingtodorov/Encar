"""Fewer upstream requests per sync, with the crawl unchanged in what it indexes.

Three savings are measured here, all of them about ASKING LESS rather than crawling less:

1. The bisection used to halve the RANGE, not the cars. Price is bounded 0..100,000 万원 and
   almost the whole catalogue sits under 5,000, so probe after probe was spent discovering
   that the upper half is empty, and the leaves that finally fit came back holding a few
   dozen rows instead of ~500. The split point now comes from our OWN index (quantiles, no
   upstream request), which is both fewer probes and fuller leaves.
2. The tree measured by a sync is saved. A node whose real count has not changed lets the
   walk read its children's counts from the saved tree instead of asking Encar the same
   question a day later — with a safety net: a trusted leaf that comes back with a FULL page
   is re-probed for the truth and split properly, so a count that happens to match while the
   contents moved cannot lose cars.
3. Counts probed by a run that was interrupted are reused when it resumes, so a stall
   restart does not re-ask them (a run of requests right after a restart is exactly what
   escalates Encar's cooldown).

Plus `ENCAR_LEAF_MAX`, the knob for a bigger page — measured on production by
`probe_page_size.py`, never assumed here.
"""

import asyncio
import os
import random
import re
import sys
from collections import defaultdict

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sync as sync_mod  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

RANGE = re.compile(r"(Price|Year|Mileage)\.range\((\d*)\.\.(\d*)\)")


class FakeUpstream:
    """A catalogue with a REALISTIC shape, answering counts and pages from it.

    The point of the exercise is the shape: prices bunched low with a long tail, which is
    what makes blind bisection of a 0..100,000 range wasteful.
    """

    def __init__(self, n=4000, seed=7):
        rnd = random.Random(seed)
        self.cars = []
        for i in range(n):
            self.cars.append({
                "Id": f"car-{i}",
                # 만원: a long-tailed distribution, most cars between 500 and 4,000
                "Price": int(min(99_000, max(50, rnd.lognormvariate(7.3, 0.55) / 10))),
                "Year": rnd.choice([2010, 2014, 2017, 2019, 2020, 2021, 2022]) * 100
                        + rnd.randint(1, 12),
                "Mileage": int(rnd.triangular(0, 300_000, 70_000)),
            })
        self.counts = 0
        self.pages = 0

    def _match(self, q):
        bands = {n: (int(lo or 0), int(hi or 10 ** 9)) for n, lo, hi in RANGE.findall(q)}
        out = []
        for c in self.cars:
            if all(bands[k][0] <= c[k] <= bands[k][1] for k in bands):
                out.append(c)
        return out

    async def count(self, q=None, interactive=False):
        self.counts += 1
        return len(self._match(q or ""))

    async def search(self, offset=0, limit=500, q=None, sort="ModifiedDate",
                     interactive=False):
        self.pages += 1
        rows = self._match(q or "")[offset:offset + limit]
        return {"Count": len(rows), "SearchResults": [dict(r) for r in rows]}


def _dist_from(up):
    vals = {"Price": sorted(c["Price"] for c in up.cars),
            "Year": sorted(c["Year"] for c in up.cars),
            "Mileage": sorted(c["Mileage"] for c in up.cars)}
    return vals


def _walk(up, dist=None, prior=None):
    """Run one crawl of the whole fake catalogue and report what it cost."""
    seen = set()
    real_count, real_search = sync_mod.encar.count, sync_mod.encar.search
    sync_mod.encar.count, sync_mod.encar.search = up.count, up.search

    async def sink(rows):
        for r in rows:
            seen.add(r["Id"])

    async def nothing():
        return None

    st = defaultdict(int)
    st["retry_leaves"] = []
    ctx = {"plan": {}, "done": set(), "flush": nothing, "beat": nothing,
           "dist": dist, "prior": prior or {}}

    async def go():
        total = await up.count(sync_mod._q([]))
        await sync_mod._crawl_node([], sync_mod._fresh_dims(), total, sink, st, ctx)

    try:
        asyncio.run(go())
    finally:
        sync_mod.encar.count, sync_mod.encar.search = real_count, real_search
    return {"seen": seen, "st": st, "plan": ctx["plan"],
            "counts": up.counts, "pages": up.pages}


# ── 1. where to cut ──────────────────────────────────────────────────────────

def test_the_split_point_cuts_the_cars_in_half_not_the_range():
    dist = {"Price": sorted([800] * 500 + [1500] * 500 + [40_000] * 20)}
    mid = sync_mod.split_at(dist, "Price", 0, 100_000)
    assert mid is not None
    # The local median is ~1,500 万원. Blind bisection would have said 50,000.
    assert 1000 <= mid <= 2000, mid
    assert mid % sync_mod.DIM_ROUND["Price"] == 0, "split points sit on a coarse grid so a "\
                                                   "saved tree still matches tomorrow"


def test_a_band_with_too_few_local_cars_falls_back_to_blind_bisection():
    dist = {"Price": [900, 950, 1000]}
    assert sync_mod.split_at(dist, "Price", 0, 100_000) is None
    assert sync_mod.split_at(None, "Price", 0, 100_000) is None


def test_the_split_point_always_leaves_two_non_empty_halves():
    dist = {"Mileage": sorted([60_000] * 200)}
    mid = sync_mod.split_at(dist, "Mileage", 50_000, 70_000)
    assert mid is None or 50_000 < mid < 70_000


def test_smart_splits_cost_fewer_requests_than_halving_the_range(monkeypatch):
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")
    blind = _walk(FakeUpstream())
    up = FakeUpstream()
    smart = _walk(up, dist=_dist_from(up))

    assert smart["seen"] == blind["seen"], "the same cars must be indexed either way"
    total = lambda r: r["counts"] + r["pages"]                            # noqa: E731
    assert total(smart) < total(blind) * 0.8, (total(smart), total(blind))
    assert smart["st"]["smart_splits"] > 0
    # Fuller leaves as well: fewer pages for the same cars.
    assert smart["pages"] <= blind["pages"]


# ── 2. the tree the last sync measured ───────────────────────────────────────

def test_an_unchanged_node_is_not_measured_again(monkeypatch):
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")
    up = FakeUpstream()
    first = _walk(up, dist=_dist_from(up))

    again = FakeUpstream()                      # the same catalogue, a day later
    second = _walk(again, dist=_dist_from(again), prior=first["plan"])

    assert second["seen"] == first["seen"]
    assert second["st"]["reused_probes"] > 0
    # One count for the scope, and nothing else asked twice.
    assert again.counts <= 1, again.counts


def test_a_count_that_matches_while_the_contents_moved_cannot_lose_cars(monkeypatch):
    """The dangerous case: same count, different cars, so a leaf is bigger than promised."""
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")
    up = FakeUpstream(n=1200)
    first = _walk(up, dist=_dist_from(up))

    # A prior that lies about one leaf: it claims a slice holds 5 cars when upstream will
    # fill the whole page. That is exactly what a stale tree looks like.
    lying = dict(first["plan"])
    victim = max(lying, key=lambda k: lying[k] if lying[k] <= sync_mod.leaf_max() else -1)
    lying[victim] = 5

    again = FakeUpstream(n=1200)
    second = _walk(again, dist=_dist_from(again), prior=lying)
    assert second["seen"] == first["seen"], "no car may be lost to a stale count"


def test_a_stale_trusted_leaf_is_re_probed_rather_than_believed(monkeypatch):
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")
    lm = sync_mod.leaf_max()
    probes = {"n": 0}

    async def count(q=None, interactive=False):
        probes["n"] += 1
        return 900 if probes["n"] == 1 else 300      # the truth: needs splitting

    async def search(offset=0, limit=500, q=None, sort="ModifiedDate", interactive=False):
        return {"SearchResults": [{"Id": f"{q[-30:]}-{i}"} for i in range(limit)]}

    async def sink(rows):
        return None

    async def nothing():
        return None

    monkeypatch.setattr(sync_mod.encar, "count", count)
    monkeypatch.setattr(sync_mod.encar, "search", search)

    st = defaultdict(int)
    st["retry_leaves"] = []
    root = sync_mod._q([])
    ctx = {"plan": {}, "done": set(), "flush": nothing, "beat": nothing,
           "prior": {root: 10}, "dist": None}
    # The prior says the whole catalogue is 10 cars and the node count agrees, so the walk
    # trusts it — and then upstream hands back a full page.
    asyncio.run(sync_mod._crawl_node([], sync_mod._fresh_dims(), 10, sink, st, ctx))
    assert st["trust_misses"] == 1, dict(st)
    assert probes["n"] >= 1, "a full page under a reused count must be re-measured"
    assert st["leaves"] >= 2, "and then split properly"


# ── 3. the knob for a bigger page ────────────────────────────────────────────

def test_the_page_size_is_a_knob_with_sane_bounds(monkeypatch):
    assert sync_mod.leaf_max() == 500
    monkeypatch.setenv("ENCAR_LEAF_MAX", "1000")
    assert sync_mod.leaf_max() == 1000
    assert sync_mod.walk_page() == 1000
    monkeypatch.setenv("ENCAR_LEAF_MAX", "5")
    assert sync_mod.leaf_max() == 100, "too small would multiply the requests instead"
    monkeypatch.setenv("ENCAR_LEAF_MAX", "999999")
    assert sync_mod.leaf_max() == 2000
    monkeypatch.setenv("ENCAR_LEAF_MAX", "nonsense")
    assert sync_mod.leaf_max() == 500


def test_a_bigger_page_halves_the_leaf_requests(monkeypatch):
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")
    up = FakeUpstream()
    at500 = _walk(up, dist=_dist_from(up))
    monkeypatch.setenv("ENCAR_LEAF_MAX", "1000")
    up2 = FakeUpstream()
    at1000 = _walk(up2, dist=_dist_from(up2))
    assert at1000["seen"] == at500["seen"]
    assert at1000["pages"] < at500["pages"], (at1000["pages"], at500["pages"])


# ── the whole crawl, against a real database ─────────────────────────────────

@pytest.fixture
def db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    name = f"{os.environ['DB_NAME']}_test_budget_{os.getpid()}"
    yield client[name]

    async def cleanup():
        await client.drop_database(name)
        client.close()

    asyncio.get_event_loop().run_until_complete(cleanup())


def _rows(up, ids):
    return [{"Id": c["Id"], "Manufacturer": "\ubca4\uce20", "Model": "C-Class",
             "Price": c["Price"], "Mileage": c["Mileage"], "Year": c["Year"],
             "FormYear": c["Year"] // 100,
             "Photos": [{"location": f"/carpicture01/pic{c['Id']}/x_001.jpg"}],
             "Condition": [], "SellType": "\uc77c\ubc18"}
            for c in up.cars if c["Id"] in ids]


def test_the_measured_tree_is_saved_and_reused_by_the_next_sync(db, monkeypatch):
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")

    async def go():
        up = FakeUpstream(n=1500)
        real_count, real_search = sync_mod.encar.count, sync_mod.encar.search

        async def count(q=None, interactive=False):
            return await up.count(q)

        async def search(offset=0, limit=500, q=None, sort="ModifiedDate",
                         interactive=False):
            data = await up.search(offset=offset, limit=limit, q=q)
            ids = {r["Id"] for r in data["SearchResults"]}
            return {"Count": len(ids), "SearchResults": _rows(up, ids)}

        try:
            sync_mod.encar.count, sync_mod.encar.search = count, search
            await sync_mod.crawl_partitioned(db, manufacturers=None, retire=False)
            saved = await db.sync_state.find_one({"_id": "catalogue_partition_plan"})
            assert saved and saved["nodes"] > 0, "the tree must outlive the sync"
            assert await db.sync_state.find_one({"_id": "catalogue_partition_resume"}) is None

            before = up.counts
            await sync_mod.crawl_partitioned(db, manufacturers=None, retire=False)
            spent = up.counts - before
        finally:
            sync_mod.encar.count, sync_mod.encar.search = real_count, real_search

        indexed = await db.listings.count_documents({"active": True})
        assert indexed == 1500, indexed
        # The second sync asks for the scope count and (at most) a handful of corrections,
        # instead of re-measuring the whole tree.
        assert spent <= 5, spent

    asyncio.get_event_loop().run_until_complete(go())


def test_a_tree_older_than_the_keep_window_is_measured_again(db, monkeypatch):
    from datetime import datetime, timedelta, timezone
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")
    monkeypatch.setenv("SYNC_PLAN_KEEP_H", "1")

    async def go():
        up = FakeUpstream(n=900)
        real_count, real_search = sync_mod.encar.count, sync_mod.encar.search

        async def count(q=None, interactive=False):
            return await up.count(q)

        async def search(offset=0, limit=500, q=None, sort="ModifiedDate",
                         interactive=False):
            data = await up.search(offset=offset, limit=limit, q=q)
            ids = {r["Id"] for r in data["SearchResults"]}
            return {"Count": len(ids), "SearchResults": _rows(up, ids)}

        try:
            sync_mod.encar.count, sync_mod.encar.search = count, search
            await sync_mod.crawl_partitioned(db, manufacturers=None, retire=False)
            await db.sync_state.update_one(
                {"_id": "catalogue_partition_plan"},
                {"$set": {"saved_at": datetime.now(timezone.utc) - timedelta(hours=48)}})
            before = up.counts
            await sync_mod.crawl_partitioned(db, manufacturers=None, retire=False)
            spent = up.counts - before
        finally:
            sync_mod.encar.count, sync_mod.encar.search = real_count, real_search

        assert spent > 1, "a stale tree must be re-measured, not trusted"
        assert await db.listings.count_documents({"active": True}) == 900

    asyncio.get_event_loop().run_until_complete(go())


def test_a_resumed_run_does_not_re_ask_the_counts_it_already_had(db, monkeypatch):
    """A stall restart used to repeat every count probe of the interrupted run."""
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")

    async def go():
        up = FakeUpstream(n=1200)
        real_count, real_search = sync_mod.encar.count, sync_mod.encar.search

        async def count(q=None, interactive=False):
            return await up.count(q)

        async def search(offset=0, limit=500, q=None, sort="ModifiedDate",
                         interactive=False):
            data = await up.search(offset=offset, limit=limit, q=q)
            ids = {r["Id"] for r in data["SearchResults"]}
            return {"Count": len(ids), "SearchResults": _rows(up, ids)}

        try:
            sync_mod.encar.count, sync_mod.encar.search = count, search
            res = await sync_mod.crawl_partitioned(db, manufacturers=None, retire=False,
                                                   run_id="run-1")
            # Put the checkpoint back as an interrupted run would have left it, with the
            # slices NOT yet marked done so the walk really runs again.
            plan = dict(res["stats"] and {})    # (stats carries no plan; read the saved one)
            saved = await db.sync_state.find_one({"_id": "catalogue_partition_plan"})
            await db.sync_state.update_one(
                {"_id": "catalogue_partition_resume"},
                {"$set": {"run_id": "run-1", "plan": saved["plan"],
                          "splits": saved["splits"], "done": []}},
                upsert=True)
            # No saved tree this time: the only thing that can spare the probes is the
            # resumed run's own count cache.
            await db.sync_state.delete_one({"_id": "catalogue_partition_plan"})
            before = up.counts
            await sync_mod.crawl_partitioned(db, manufacturers=None, retire=False,
                                             run_id="run-1", resume=True)
            spent = up.counts - before
            assert plan == {}
        finally:
            sync_mod.encar.count, sync_mod.encar.search = real_count, real_search

        assert spent == 0, f"{spent} counts re-asked on a resume"

    asyncio.get_event_loop().run_until_complete(go())
