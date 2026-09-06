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
