"""A car Encar has put under contract must not be sellable or even visible.

`fem.encar.com` shows such an ad as normal, but `advertisement.salesStatus` reads CONTRACT and
the sale is already pending — reserving it would take a deposit for a car nobody can buy.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import encar  # noqa: E402
import sync  # noqa: E402


def test_a_contract_row_is_never_imported():
    row = {"Id": "1", "Price": 5590, "Mileage": 12000, "SalesStatus": "CONTRACT"}
    assert sync.contracted(row) is True
    assert sync.skip_row(row) is True


def test_an_ordinary_row_still_passes():
    row = {"Id": "2", "Price": 5590, "Mileage": 12000, "SalesStatus": "ADVERTISE"}
    assert sync.contracted(row) is False
    assert sync.skip_row(row) is False


def test_the_detail_payload_is_read_the_same_way():
    assert encar.under_contract({"advertisement": {"salesStatus": "CONTRACT"}}) is True
    assert encar.under_contract({"advertisement": {"salesStatus": "ADVERTISE"}}) is False
    # A payload without the block at all must not raise or read as contracted.
    assert encar.under_contract({}) is False
    assert encar.under_contract(None) is False
    assert encar.sales_status({"advertisement": {"salesStatus": "CONTRACT"}}) == "CONTRACT"


def test_search_can_never_return_one():
    import server

    assert server.build_query({})["under_contract"] == {"$ne": True}


def test_retiring_takes_it_out_of_the_catalogue():
    from motor.motor_asyncio import AsyncIOMotorClient

    if not os.environ.get("MONGO_URL"):
        pytest.skip("MONGO_URL is not set")

    async def go():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        cid = "test-contract-0001"
        try:
            await db.listings.insert_one({"_id": cid, "active": True})
            assert await sync.retire_contracted(db, {cid}) == 1
            doc = await db.listings.find_one({"_id": cid})
            assert doc["active"] is False
            assert doc["under_contract"] is True
            assert doc["sales_status"] == "CONTRACT"
            # And the query the search uses no longer matches it.
            import server

            q = server.build_query({})
            q["_id"] = cid
            assert await db.listings.count_documents(q) == 0
        finally:
            await db.listings.delete_one({"_id": cid})
            client.close()

    asyncio.run(go())
