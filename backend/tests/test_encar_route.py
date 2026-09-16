"""The Encar route is an ORDERED CHAIN: direct, then the Mac mini, then the paid proxy.

Each tier has its own circuit breaker, so a tier Encar has blocked does not shut out the tier
that works — that was the whole failing of the single breaker on 14/09: one 403 from Hetzner
and nothing went anywhere for three minutes with a perfectly good Mac exit sitting next to it.
"""
import asyncio
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import encar as encar_mod  # noqa: E402
from encar import EncarClient, EncarUnavailable  # noqa: E402

MAC = "http://10.99.0.3:8888"
IPROYAL = "http://user:secret@geo.iproyal.com:12321"


@pytest.fixture(autouse=True)
def clean_route():
    os.environ["ENCAR_HOME_EXIT_URL"] = MAC
    os.environ["ENCAR_RESIDENTIAL_PROXY_URL"] = IPROYAL
    os.environ.pop("ENCAR_ROUTES", None)
    os.environ.pop("ENCAR_PROXY_URL", None)
    encar_mod.set_route("auto")
    encar_mod.set_persist(None)
    yield
    encar_mod.set_route("auto")
    encar_mod.set_persist(None)
    for key in ("ENCAR_HOME_EXIT_URL", "ENCAR_RESIDENTIAL_PROXY_URL", "ENCAR_ROUTES",
                "ENCAR_PROXY_URL"):
        os.environ.pop(key, None)


def test_the_chain_is_ordered_cheapest_first():
    assert encar_mod.chain() == ("direct", "home_exit", "residential_proxy")
    assert encar_mod.route() == "direct"
    assert encar_mod.proxy_url() is None
    assert encar_mod.other_route() == "home_exit"
    assert encar_mod.other_route("home_exit") == "residential_proxy"
    assert encar_mod.other_route("residential_proxy") is None


def test_a_tier_with_no_url_is_not_in_the_chain():
    os.environ.pop("ENCAR_HOME_EXIT_URL")
    assert encar_mod.chain() == ("direct", "residential_proxy")
    os.environ.pop("ENCAR_RESIDENTIAL_PROXY_URL")
    # Direct needs nothing configured and must never be the tier that does not exist.
    assert encar_mod.chain() == ("direct",)
    assert encar_mod.other_route() is None
    assert encar_mod.proxy_configured() is False


def test_the_order_can_be_changed_without_a_code_change():
    os.environ["ENCAR_ROUTES"] = "home_exit,direct"
    assert encar_mod.chain() == ("home_exit", "direct")
    assert encar_mod.route() == "home_exit"
    assert encar_mod.proxy_url() == MAC


def test_the_single_slot_variable_still_reads_as_the_paid_tier():
    """A server that has not had the new backend.env yet must keep the exit it has, not go
    direct into a 403."""
    os.environ.pop("ENCAR_HOME_EXIT_URL")
    os.environ.pop("ENCAR_RESIDENTIAL_PROXY_URL")
    os.environ["ENCAR_PROXY_URL"] = IPROYAL
    assert encar_mod.chain() == ("direct", "residential_proxy")
    assert encar_mod.tier_url("residential_proxy") == IPROYAL


def test_a_mode_pins_one_tier_and_the_old_name_still_works():
    assert encar_mod.set_route("home_exit") == "home_exit"
    assert encar_mod.route() == "home_exit" and encar_mod.proxy_url() == MAC
    # "proxy" is what the single-slot era called the one proxy there was; stored settings
    # and old bookmarks still say it, and a 400 is not the way to find that out.
    assert encar_mod.set_route("proxy") == "residential_proxy"
    assert encar_mod.route() == "residential_proxy"
    assert encar_mod.set_route("sideways") == "residential_proxy"      # ignored
    assert encar_mod.set_route("direct") == "direct"
    assert encar_mod.proxy_url() is None


def test_choosing_a_mode_by_hand_clears_every_breaker():
    c = EncarClient(min_interval=0)
    c._trip("boom", 999, tier="direct")
    c._trip("boom", 999, tier="home_exit")
    assert encar_mod.route() == "residential_proxy"
    encar_mod.set_route("auto")                    # "try them all again, now"
    assert encar_mod.route() == "direct"
    assert c.breaker("direct")["open"] is False


def test_one_warm_client_per_tier_reused_across_requests(monkeypatch):
    """A fresh connection through the tunnel is TCP + CONNECT + TLS, 150-180ms paid before
    the request is even sent. So each tier keeps ONE client, and falling through to the next
    tier must not throw away the pool of the tier we came from."""
    c = EncarClient(min_interval=0)
    built = []
    real = encar_mod.httpx.AsyncClient

    def spy(**kw):
        built.append(kw.get("proxy"))
        return real(**kw)

    monkeypatch.setattr(encar_mod.httpx, "AsyncClient", spy)

    async def run():
        first = await c.client()
        assert await c.client() is first            # reused, not rebuilt
        assert built == [None]                      # direct
        c._trip("HTTP 403 from upstream", 60, tier="direct", stick=True)
        mac = await c.client()
        assert mac is not first and built == [None, MAC]
        # ...and the direct pool is still there for when the probe hands traffic back.
        encar_mod.reset_breakers()
        assert await c.client() is first
        assert built == [None, MAC]
        await c.close()

    asyncio.run(run())


def test_the_pool_survives_a_route_switch():
    c = EncarClient(min_interval=0)

    async def run():
        direct = await c.client()
        await c.switch_route("home_exit")
        mac = await c.client()
        assert mac is not direct
        await c.switch_route("direct")
        assert await c.client() is direct, "switching must not cost a new TLS handshake"
        await c.close()
        assert c._clients == {}                    # shutdown does close them
    asyncio.run(run())


def test_connections_are_kept_alive_longer_than_the_sweep_waits():
    """httpx's default keepalive_expiry is 5s while the paced catalogue sweep leaves ~17s
    between pages — every page was paying for a new handshake."""
    import sync

    assert encar_mod.KEEPALIVE.keepalive_expiry > sync.SYNC_PAGE_GAP_MAX
    assert encar_mod.KEEPALIVE.max_keepalive_connections == 10


def test_switch_clears_the_breaker_of_the_route_we_move_to():
    c = EncarClient(min_interval=0)

    async def run():
        c._trip("boom", 999)
        assert c.breaker("direct")["open"] is True
        await c.switch_route("direct")
        # The new route must not sit out the cooldown the old one earned, or it looks just
        # as broken. The warm pool, on the other hand, is kept — see the tests above.
        assert c.breaker()["open"] is False
        assert encar_mod.route() == "direct"
        await c.close()

    asyncio.run(run())


def _dead_client(monkeypatch, exc=None, status=None):
    """Every request through whatever tier is in force fails the same way."""
    seen = []

    class Dead:
        async def get(self, url):
            seen.append(encar_mod.route())
            if exc:
                raise exc
            return encar_mod.httpx.Response(status, text="")

        async def aclose(self):
            pass

    async def fake_client(self):
        self._route = encar_mod.route()
        return Dead()

    monkeypatch.setattr(EncarClient, "client", fake_client)
    return seen


def test_a_dead_tier_hands_traffic_to_the_next_one(monkeypatch):
    """Direct times out: the Mac takes over by itself, before anybody's phone rings."""
    c = EncarClient(min_interval=0)
    monkeypatch.setattr(encar_mod, "BREAKER_FAILS", 1)
    seen = _dead_client(monkeypatch, exc=encar_mod.httpx.ReadTimeout(""))

    async def run():
        with pytest.raises(EncarUnavailable):
            await c.get_json("/v1/readside/vehicle/1")
        assert seen[0] == "direct"
        assert encar_mod.route() == "home_exit"
        # The MODE is a standing instruction and does not move: "auto" is still "auto",
        # which is what lets the fifteen-minute probe climb back to direct.
        assert encar_mod.route_mode() == "auto"
        assert encar_mod.auto_on_proxy() is True
        st = c.status()
        assert st["last_failover"]["from"] == "direct" and st["last_failover"]["to"] == "home_exit"
        assert st["probe_in_s"] > 0
        assert st["breaker"]["open"] is False       # the NEW tier gets its own clean chance
        # The Mac dies too, and only then is the metered proxy asked.
        with pytest.raises(EncarUnavailable):
            await c.get_json("/v1/readside/vehicle/2")
        assert encar_mod.route() == "residential_proxy"
        # Nothing left: the last tier keeps its short cooldown and the chain says so once.
        with pytest.raises(EncarUnavailable):
            await c.get_json("/v1/readside/vehicle/3")
        assert encar_mod.route() == "residential_proxy"
        with pytest.raises(EncarUnavailable) as e:
            await c.get_json("/v1/readside/vehicle/4")
        assert "on every route" in str(e.value)

    asyncio.run(run())


def test_a_block_walks_the_chain_within_the_same_request(monkeypatch):
    """A 403 says THIS address is refused — which is an argument for the next tier, not for
    giving up on the call.

    It used to only move the tier for the NEXT request, and that is not good enough for the
    caller that gets blocked. The catalogue sync's first upstream call is a single count
    probe: one 403 on the datacentre address killed the whole two-hour job on the spot, and
    every retry of the job earned another block until the long cooldown kicked in. That is
    what "as soon as we start the catalogue sync we get the rate limit" was.
    """
    c = EncarClient(min_interval=0)
    seen = _dead_client(monkeypatch, status=403)

    async def run():
        with pytest.raises(EncarUnavailable) as e:
            await c.get_json("/v1/readside/vehicle/1")
        # Every door was tried, once each, before the caller was told no.
        assert e.value.status == 403
        assert seen == ["direct", "home_exit", "residential_proxy"]
        assert len(seen) == len(set(seen)), "no tier may be knocked on twice"
        assert c.breaker("direct")["open"] is True
        # ...and a blocked tier that has somewhere to fall through to is left alone for the
        # full probe gap, instead of being stepped on again half a minute later.
        assert c.breaker("direct")["retry_in_s"] > encar_mod.AUTO_PROBE_GAP - 5

    asyncio.run(run())


def test_a_working_tier_further_down_the_chain_answers_the_same_request(monkeypatch):
    """The point of the fallthrough: the CALLER gets data, not an error, when any door opens.
    Encar blocks the datacentre address and allows the residential one — that is the whole
    reason the chain exists."""
    c = EncarClient(min_interval=0)
    seen = []

    def handler(request):
        tier = encar_mod.route()
        seen.append(tier)
        if tier == "residential_proxy":
            return httpx.Response(200, json={"Count": 244996})
        return httpx.Response(403, text="blocked")

    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                  headers=encar_mod.HEADERS)

    async def run():
        got = await c.get_json("/search/car/list/general?count=true")
        assert got == {"Count": 244996}
        assert seen == ["direct", "home_exit", "residential_proxy"]
        assert encar_mod.route() == "residential_proxy"

    asyncio.run(run())


def test_the_last_tier_keeps_the_short_cooldown(monkeypatch):
    """With nowhere to fall through to, a one-off block must not lock us out for a quarter of
    an hour: 0.3% of blocks were buying three-minute outages before, which was already too
    much."""
    os.environ["ENCAR_ROUTES"] = "direct"
    c = EncarClient(min_interval=0)
    _dead_client(monkeypatch, status=403)

    async def run():
        with pytest.raises(EncarUnavailable):
            await c.get_json("/v1/readside/vehicle/1")
        b = c.breaker("direct")
        assert b["open"] and b["retry_in_s"] <= encar_mod.BLOCK_COOLDOWN_FIRST

    asyncio.run(run())


def _probe_client(monkeypatch, ok):
    class Probe:
        async def get(self, url):
            assert url.endswith(encar_mod.PROBE_PATH)
            if ok:
                return encar_mod.httpx.Response(200, json={"ok": 1})
            raise encar_mod.httpx.ConnectError("")

        async def aclose(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(encar_mod.httpx, "AsyncClient", lambda **kw: Probe())


def test_the_probe_climbs_back_to_the_cheapest_tier(monkeypatch):
    """Being off `direct` is temporary: every quarter of an hour it gets asked again."""
    c = EncarClient(min_interval=0)
    saved = []

    async def persist(mode, reason=""):
        saved.append((mode, reason))

    encar_mod.set_persist(persist)
    c._trip("HTTP 403 from upstream", 60, tier="direct")
    assert encar_mod.route() == "home_exit"
    _probe_client(monkeypatch, ok=True)

    async def run():
        assert await c._probe_preferred() is True
        assert encar_mod.route() == "direct"
        assert encar_mod.auto_on_proxy() is False
        assert saved and saved[0][0] == "auto"
        st = c.status()
        assert st["last_probe"]["ok"] is True and st["last_probe"]["tier"] == "direct"

    asyncio.run(run())


def test_the_probe_leaves_traffic_where_it_is_while_direct_is_still_down(monkeypatch):
    c = EncarClient(min_interval=0)
    c._trip("HTTP 403 from upstream", 60, tier="direct")
    _probe_client(monkeypatch, ok=False)

    async def run():
        assert await c._probe_preferred() is False
        assert encar_mod.route() == "home_exit"
        assert c.status()["last_probe"]["ok"] is False
        assert c.status()["probe_in_s"] > encar_mod.AUTO_PROBE_GAP - 5

    asyncio.run(run())


def test_the_probe_is_not_due_before_its_time(monkeypatch):
    """Nothing is probed while the first choice is carrying traffic, or twice in a window."""
    c = EncarClient(min_interval=0)
    started = []
    monkeypatch.setattr(encar_mod.asyncio, "create_task",
                        lambda coro: (coro.close(), started.append(1)))

    c._maybe_probe_preferred()
    assert not started                      # on direct: there is nothing better to probe

    c._trip("boom", 60, tier="direct")
    c._maybe_probe_preferred()
    assert not started                      # fifteen minutes have not passed

    encar_mod._auto["probe_at"] = encar_mod.time.monotonic() - 1
    c._maybe_probe_preferred()
    assert started == [1]
    c._maybe_probe_preferred()
    assert started == [1]                   # and probes do not stack


def test_status_shows_every_tier_and_leaks_no_credential():
    c = EncarClient(min_interval=0)
    c._trip(f"ProxyError at {IPROYAL}", 60, tier="direct")
    st = c.status()
    assert st["chain"] == ["direct", "home_exit", "residential_proxy"]
    assert [t["tier"] for t in st["tiers"]] == list(encar_mod.DEFAULT_CHAIN)
    assert [t["active"] for t in st["tiers"]] == [False, True, False]
    assert st["tiers"][0]["breaker"]["open"] is True
    blob = repr(st)
    assert "secret" not in blob and "iproyal" not in blob


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


def test_verify_succeeds_through_a_later_tier(monkeypatch, capsys):
    """A Hetzner 403 used to fail EVERY deploy while the Mac answered perfectly — a release
    blocked for a reason that has nothing to do with the release."""
    async def count(self, q=None):
        if encar_mod.route() == "direct":
            raise EncarUnavailable("upstream refused the request (HTTP 403)", 403)
        return 244996

    monkeypatch.setattr(EncarClient, "count", count)
    monkeypatch.setattr(EncarClient, "close", lambda self: asyncio.sleep(0))

    assert asyncio.run(encar_mod.verify()) == 0
    out = capsys.readouterr().out
    assert out.startswith("OK route=home_exit") and "skipped: direct" in out


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


def test_verify_fails_when_no_tier_answers(monkeypatch, capsys):
    async def blocked(self, q=None):
        raise EncarUnavailable("upstream refused the request (HTTP 407)", 407)

    monkeypatch.setattr(EncarClient, "count", blocked)
    monkeypatch.setattr(EncarClient, "close", lambda self: asyncio.sleep(0))

    assert asyncio.run(encar_mod.verify()) == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL no route answered")
    for tier in ("direct", "home_exit", "residential_proxy"):
        assert f"{tier}: status=407" in out


def test_verify_fails_when_the_count_comes_back_empty_handed(monkeypatch, capsys):
    """`count()` returns None when the REQUEST failed - never treat that as a zero."""
    async def nothing(self, q=None):
        return None

    monkeypatch.setattr(EncarClient, "count", nothing)
    monkeypatch.setattr(EncarClient, "close", lambda self: asyncio.sleep(0))

    assert asyncio.run(encar_mod.verify()) == 1
    assert capsys.readouterr().out.startswith("FAIL")
