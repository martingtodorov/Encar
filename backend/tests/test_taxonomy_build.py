"""Building the taxonomy: once per node, and always with slugs.

Two bugs lived here, both found by the owner's audit of the live site:

1. `sitemap-models.xml` carried 2 630 entries for 1 315 landings — an exact 2x across the
   whole file. The nightly sync calls `build_taxonomy` directly while a request can fire it
   through `refresh_taxonomy_if_stale`; both staged into one fixed collection, so overlapping
   builds interleaved their inserts and every node was stored twice.
2. A rebuild recreates every document from the aggregation, so the tree comes out with NO
   slug — and the on-demand path never re-assigned them. Every /bg/bmw landing 404'd until
   the next full sync got round to its separate "slugs" step.
"""
import asyncio
import os

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

import sync

MAKES = [("BMW", "M2 (G87)"), ("BMW", "M4 (G82)"), ("Hyundai", "Ioniq 5"),
         ("Volvo", "XC90"), ("Volkswagen", "Touareg")]


@pytest.fixture
def db():
    name = f"{os.environ['DB_NAME']}_test_tax_{os.getpid()}"
    loop = asyncio.new_event_loop()

    # Motor binds its client to the loop that is RUNNING when the client is created, so it
    # has to be built inside this loop or concurrent operations land on the wrong one.
    async def connect():
        return AsyncIOMotorClient(os.environ["MONGO_URL"])

    client = loop.run_until_complete(connect())
    handle = client[name]

    async def seed():
        rows = []
        for i, (make, model) in enumerate(MAKES):
            rows.append({"_id": f"ad-{i}", "active": True, "manufacturer": make,
                         "model": model, "badge": "Base", "badge_detail": "",
                         "mileage": 1000 + i, "recency": i})
        await handle.listings.insert_many(rows)

    loop.run_until_complete(seed())
    yield loop, handle

    loop.run_until_complete(client.drop_database(name))
    loop.close()


def _nodes(loop, handle, level):
    async def read():
        return [d async for d in handle.taxonomy.find({"level": level})]
    return loop.run_until_complete(read())


def test_overlapping_builds_do_not_double_the_tree(db):
    loop, handle = db
    # Exactly the race that produced the doubled sitemap. `gather` has to be created inside
    # the loop, or it attaches itself to the default one.
    async def race():
        return await asyncio.gather(sync.build_taxonomy(handle),
                                    sync.build_taxonomy(handle))

    a, b = loop.run_until_complete(race())
    assert a["nodes"] == b["nodes"]

    makes = _nodes(loop, handle, 1)
    models = _nodes(loop, handle, 2)
    assert len(makes) == len({m["value"] for m in makes}) == 4
    assert len(models) == len({(m["make"], m["value"]) for m in models}) == 5


def test_a_build_leaves_every_node_slugged(db):
    loop, handle = db
    out = loop.run_until_complete(sync.build_taxonomy(handle))
    assert out["slugs"] >= out["nodes"] > 0

    for level in (1, 2):
        for node in _nodes(loop, handle, level):
            assert node.get("slug"), f"level {level} node {node['value']} has no slug"

    slugs = {n["slug"] for n in _nodes(loop, handle, 1)}
    assert slugs == {"bmw", "hyundai", "volvo", "volkswagen"}


def test_a_rebuild_keeps_the_landings_addressable(db):
    """The on-demand refresh used to wipe the slugs and break every landing page."""
    loop, handle = db
    loop.run_until_complete(sync.build_taxonomy(handle))
    before = {(n["level"], n["value"]): n["slug"] for n in _nodes(loop, handle, 1)}

    loop.run_until_complete(sync.build_taxonomy(handle))
    after = {(n["level"], n["value"]): n["slug"] for n in _nodes(loop, handle, 1)}
    assert after == before


def test_staging_collections_do_not_pile_up(db):
    loop, handle = db
    loop.run_until_complete(sync.build_taxonomy(handle))
    loop.run_until_complete(sync.build_taxonomy(handle))
    names = loop.run_until_complete(handle.list_collection_names())
    assert [n for n in names if n.startswith("taxonomy_build_")] == []
