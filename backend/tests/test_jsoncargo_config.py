"""The deploy bug that killed tracking on the Hetzner host, and its two guards.

Ansible writes EVERY variable from group_vars whether it was filled in or not, so a
`jsoncargo_shipping_line: ""` copied from the example reached the server as
`JSONCARGO_SHIPPING_LINE=`. `os.environ.get(name, "MAERSK")` returns the empty string in that
case - the default never fires - and JSONCargo answers 400 "Missing required parameter
`shipping_line`" to every container lookup. The preview box happened to have the value spelled
out, so the failure existed only in production.

These tests are offline: they exercise the config reader and the cache policy, not the provider.
"""
import asyncio
import os
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

import jsoncargo


def _db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client, client[os.environ["DB_NAME"]]


@pytest.fixture
def env():
    """Restore whatever the real .env had: these tests move the carrier around."""
    keep = {k: os.environ.get(k) for k in
            ("JSONCARGO_SHIPPING_LINE", "JSONCARGO_API_KEY", "JSONCARGO_BASE_URL")}
    yield os.environ
    for k, v in keep.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_empty_carrier_falls_back_to_maersk(env):
    """THE BUG. An empty value must not beat the default."""
    env["JSONCARGO_SHIPPING_LINE"] = ""
    assert jsoncargo.config()["line"] == "MAERSK"


def test_whitespace_carrier_falls_back_too(env):
    env["JSONCARGO_SHIPPING_LINE"] = "   "
    assert jsoncargo.config()["line"] == "MAERSK"


def test_an_explicit_carrier_is_still_honoured(env):
    """The fallback must not become a hardcoding: a second carrier has to remain possible."""
    env["JSONCARGO_SHIPPING_LINE"] = "MSC"
    assert jsoncargo.config()["line"] == "MSC"


def test_a_key_with_stray_whitespace_still_counts_as_configured(env):
    """A key pasted into YAML with a trailing newline read as "no tracking at all"."""
    env["JSONCARGO_API_KEY"] = "  some-key  \n"
    assert jsoncargo.config()["key"] == "some-key"
    assert jsoncargo.configured() is True


def test_an_empty_key_reads_as_not_configured(env):
    env["JSONCARGO_API_KEY"] = ""
    assert jsoncargo.configured() is False


def test_base_url_default_survives_an_empty_value(env):
    env["JSONCARGO_BASE_URL"] = ""
    assert jsoncargo.config()["base"] == "https://api.jsoncargo.com/api/v1"


def test_a_config_failure_is_never_cached():
    """Otherwise a corrected deployment keeps failing for fifteen minutes and looks unfixed."""
    key = f"cargo:test:{uuid.uuid4().hex}"

    async def go():
        client, db = _db()
        try:
            async def boom():
                raise jsoncargo.ConfigError("Missing required parameter `shipping_line`")

            with pytest.raises(jsoncargo.ConfigError):
                await jsoncargo._cached(db, key, 60, boom)
            assert await db.cargo_cache.find_one({"_id": key}) is None

            # And a row cached BEFORE anyone noticed the misconfiguration is cleared, so the
            # first lookup after the fix goes out for real.
            await db.cargo_cache.insert_one({"_id": key, "stored_at": jsoncargo._now(),
                                             "payload": None, "error": "old",
                                             "error_ttl": 900})
            with pytest.raises(jsoncargo.ConfigError):
                await jsoncargo._cached(db, key, 60, boom, refresh=True)
            assert await db.cargo_cache.find_one({"_id": key}) is None
        finally:
            await db.cargo_cache.delete_one({"_id": key})
            client.close()

    asyncio.run(go())


def test_an_ordinary_failure_is_still_cached():
    """The metered plan is the whole reason this cache exists: a bad number must cost ONE call."""
    key = f"cargo:test:{uuid.uuid4().hex}"

    async def go():
        client, db = _db()
        try:
            async def quota():
                raise RuntimeError("the tracking plan has no requests left this month")

            with pytest.raises(RuntimeError):
                await jsoncargo._cached(db, key, 60, quota)
            row = await db.cargo_cache.find_one({"_id": key})
            assert row and row["error"] and row["error_ttl"] == 900

            # The second look never reaches the provider - it replays the cached error.
            async def must_not_run():
                raise AssertionError("the provider was called again inside the TTL")

            with pytest.raises(RuntimeError):
                await jsoncargo._cached(db, key, 60, must_not_run)
        finally:
            await db.cargo_cache.delete_one({"_id": key})
            client.close()

    asyncio.run(go())
