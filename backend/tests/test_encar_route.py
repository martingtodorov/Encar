"""The Encar route is a setting, and a dead route fails over on its own."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import encar as encar_mod  # noqa: E402
from encar import EncarClient, EncarUnavailable  # noqa: E402


@pytest.fixture(autouse=True)
def clean_route():
    encar_mod.set_route("auto")
    encar_mod.set_persist(None)
    os.environ["ENCAR_PROXY_URL"] = "http://user:secret@proxy.example:8080"
    yield
    encar_mod.set_route("auto")
    encar_mod.set_persist(None)
    os.environ.pop("ENCAR_PROXY_URL", None)


def test_mode_decides_the_route():
    assert encar_mod.route() == "residential_proxy"
    encar_mod.set_route("direct")
    assert encar_mod.route() == "direct"
    assert encar_mod.proxy_url() is None
    assert encar_mod.proxy_configured() is True
    assert encar_mod.other_route() == "proxy"


def test_bad_mode_is_ignored():
    assert encar_mod.set_route("sideways") == "auto"


def test_switch_rebuilds_the_client_and_clears_the_breaker():
    c = EncarClient(min_interval=0)

    async def run():
        first = await c.client()
        c._trip("boom", 999)
        assert c.breaker()["open"] is True
        await c.switch_route("direct")
        second = await c.client()
        assert second is not first          # the old client held the old proxy
        assert c.breaker()["open"] is False  # the new route does not serve the old cooldown
        assert encar_mod.route() == "direct"
        await c.close()

    asyncio.run(run())


def test_transport_failure_fails_over_to_the_other_route(monkeypatch):
    """Every request through the proxy dies; the client must try direct before alerting."""
    c = EncarClient(min_interval=0)
    saved = []

    async def persist(mode, reason=""):
        saved.append((mode, reason))

    encar_mod.set_persist(persist)
    monkeypatch.setattr(encar_mod, "BREAKER_FAILS", 1)

    class Dead:
        async def get(self, url):
            raise encar_mod.httpx.ReadTimeout("")

        async def aclose(self):
            pass

    async def fake_client(self):
        self._route = encar_mod.route()
        return Dead()

    monkeypatch.setattr(EncarClient, "client", fake_client)

    async def run():
        with pytest.raises(EncarUnavailable):
            await c.get_json("/v1/readside/vehicle/1")
        assert encar_mod.route() == "direct"
        assert encar_mod.route_mode() == "direct"
        assert saved and saved[0][0] == "direct"
        st = c.status()
        assert st["last_failover"]["to"] == "direct"
        assert st["breaker"]["open"] is False   # cleared so the new route gets its chance
        # and it does not flap back on the next failure
        with pytest.raises(EncarUnavailable):
            await c.get_json("/v1/readside/vehicle/2")
        assert encar_mod.route() == "direct"

    asyncio.run(run())


def test_no_alternate_route_means_no_failover(monkeypatch):
    os.environ.pop("ENCAR_PROXY_URL", None)
    c = EncarClient(min_interval=0)
    assert encar_mod.other_route() is None
    c._trip("boom", 60)

    async def run():
        assert await c._failover_if_pending() is None
        assert c.breaker()["open"] is True

    asyncio.run(run())


def test_status_never_leaks_the_proxy():
    c = EncarClient(min_interval=0)
    c._trip("ProxyError at http://user:secret@proxy.example:8080", 60)
    blob = repr(c.status())
    assert "secret" not in blob and "proxy.example" not in blob


# ── the deploy-time check must not depend on one car staying for sale ────────
def test_verify_asks_the_catalogue_not_a_single_car(monkeypatch, capsys):
    """`assert encar_verify.rc == 0` in the playbook blocks the release when this fails, so
    the check must not be able to fail for a reason unrelated to the release. It used to
    fetch one hardcoded listing: the day that car sold, a good deploy would have stopped."""
    asked = {}

    async def fake_count(self, q=None):
        asked["count"] = True
        return 244996

    async def fake_get_json(self, path, **kw):
        raise AssertionError(f"verify must not need a car: {path}")

    monkeypatch.setattr(EncarClient, "count", fake_count)
    monkeypatch.setattr(EncarClient, "get_json", fake_get_json)
    monkeypatch.setattr(EncarClient, "close", lambda self: asyncio.sleep(0))

    assert asyncio.run(encar_mod.verify()) == 0
    assert asked["count"]
    assert "catalogue=244996" in capsys.readouterr().out


def test_verify_passes_when_the_named_car_is_already_sold(monkeypatch, capsys):
    """A 404 is Encar ANSWERING us, which is the whole question. A blocked route 407s."""
    async def fake_count(self, q=None):
        return 100

    async def sold(self, path, **kw):
        return None                      # authoritative 404

    monkeypatch.setattr(EncarClient, "count", fake_count)
    monkeypatch.setattr(EncarClient, "get_json", sold)
    monkeypatch.setattr(EncarClient, "close", lambda self: asyncio.sleep(0))

    assert asyncio.run(encar_mod.verify("42679754")) == 0
    out = capsys.readouterr().out
    assert out.startswith("OK") and "route is still proven" in out


def test_verify_fails_when_the_route_is_blocked(monkeypatch, capsys):
    async def blocked(self, q=None):
        raise EncarUnavailable("upstream refused the request (HTTP 407)", 407)

    monkeypatch.setattr(EncarClient, "count", blocked)
    monkeypatch.setattr(EncarClient, "close", lambda self: asyncio.sleep(0))

    assert asyncio.run(encar_mod.verify()) == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL") and "407" in out


def test_verify_fails_when_the_count_comes_back_empty_handed(monkeypatch, capsys):
    """`count()` returns None when the REQUEST failed - never treat that as a zero."""
    async def nothing(self, q=None):
        return None

    monkeypatch.setattr(EncarClient, "count", nothing)
    monkeypatch.setattr(EncarClient, "close", lambda self: asyncio.sleep(0))

    assert asyncio.run(encar_mod.verify()) == 1
    assert capsys.readouterr().out.startswith("FAIL")


def test_a_block_does_not_fail_over(monkeypatch):
    """403/407 means the route WORKS and Encar refused us.

    Switching then is worse than useless: if CloudFront blocks the residential address it
    blocks the datacentre one harder, and going direct puts the server's own IP in front of
    the blocklist that started the problem. Only a transport fault moves traffic.
    """
    c = EncarClient(min_interval=0)

    class Blocked:
        async def get(self, url):
            return encar_mod.httpx.Response(407, text="")

        async def aclose(self):
            pass

    async def fake_client(self):
        self._route = encar_mod.route()
        return Blocked()

    monkeypatch.setattr(EncarClient, "client", fake_client)

    async def run():
        with pytest.raises(EncarUnavailable) as e:
            await c.get_json("/v1/readside/vehicle/1")
        assert e.value.status == 407
        assert encar_mod.route() == "residential_proxy"    # unmoved
        assert c.breaker()["open"] is True                 # and asked politely to stop
        assert c.status()["last_failover"] is None

    asyncio.run(run())
