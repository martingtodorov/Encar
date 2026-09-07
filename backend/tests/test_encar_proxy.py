"""The Encar client behind a sticky residential proxy: what may return None, what must raise.

Unit-level, against a mock transport — no network. Plus one live check that an upstream
failure never retires a listing.
"""
import asyncio
import json
import logging
import os

import httpx
import pytest
import requests

import encar
from encar import EncarClient, EncarUnavailable

PROXY = "http://alice:s3cr%40t@geo.iproyal.com:12321"


def _client(handler, proxy=PROXY, monkeypatch=None):
    if monkeypatch is not None:
        if proxy:
            monkeypatch.setenv(encar.PROXY_ENV, proxy)
        else:
            monkeypatch.delenv(encar.PROXY_ENV, raising=False)
    c = EncarClient(min_interval=0)
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=encar.HEADERS)
    return c


def _run(coro):
    return asyncio.run(coro)


def _resp(status, body=None, headers=None, text=None):
    def handler(request):
        if text is not None:
            return httpx.Response(status, text=text, headers=headers)
        return httpx.Response(status, json=body if body is not None else {}, headers=headers)
    return handler


def test_proxy_200_returns_full_body(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"vehicleId": 42207598, "photos": [{"path": "/a.jpg"}]})

    c = _client(handler, monkeypatch=monkeypatch)
    # "auto" leaves from the server now; the proxy is what this test is about, so ask for it.
    encar.set_route("proxy")
    body = _run(c.detail("42207598"))
    assert body["vehicleId"] == 42207598 and body["photos"]
    assert calls == ["https://api.encar.com/v1/readside/vehicle/42207598"]
    assert encar.route() == "residential_proxy"
    encar.set_route("auto")


def test_404_is_the_only_none_and_is_not_retried(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404, text="")

    c = _client(handler, monkeypatch=monkeypatch)
    assert _run(c.detail("1")) is None
    assert len(calls) == 1
    assert c.breaker()["open"] is False


@pytest.mark.parametrize("status", [407, 403, 429, 500, 502, 503])
def test_blocked_rate_limited_and_5xx_raise(monkeypatch, status):
    c = _client(_resp(status), monkeypatch=monkeypatch)
    with pytest.raises(EncarUnavailable) as e:
        _run(c.detail("1"))
    assert e.value.status == status
    if status in encar.BLOCK_STATUSES:
        assert c.breaker()["open"], "a block opens the circuit immediately"


def test_timeout_and_transport_errors_raise_after_one_retry(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectTimeout("timed out", request=request)

    c = _client(handler, monkeypatch=monkeypatch)
    with pytest.raises(EncarUnavailable):
        _run(c.detail("1"))
    assert len(calls) == encar.ATTEMPTS == 2


def test_empty_or_non_json_200_raises_not_none(monkeypatch):
    c = _client(_resp(200, text="<html>blocked</html>"), monkeypatch=monkeypatch)
    with pytest.raises(EncarUnavailable):
        _run(c.detail("1"))
    c = _client(_resp(200, text="   "), monkeypatch=monkeypatch)
    with pytest.raises(EncarUnavailable):
        _run(c.detail("1"))


def test_429_retry_after_is_honoured(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, text="")
        return httpx.Response(200, json={"ok": 1})

    c = _client(handler, monkeypatch=monkeypatch)
    assert _run(c.detail("1")) == {"ok": 1}
    assert len(calls) == 2

    # A long Retry-After is not slept through: the circuit opens for that long instead.
    c = _client(_resp(429, headers={"Retry-After": "120"}, text=""), monkeypatch=monkeypatch)
    with pytest.raises(EncarUnavailable) as e:
        _run(c.detail("1"))
    assert e.value.status == 429
    b = c.breaker()
    assert b["open"] and 100 <= b["retry_in_s"] <= 120


def test_credentials_never_reach_logs_or_exceptions(monkeypatch, caplog):
    def handler(request):
        raise httpx.ProxyError(f"503 from {PROXY} via geo.iproyal.com", request=request)

    c = _client(handler, monkeypatch=monkeypatch)
    with caplog.at_level(logging.DEBUG, logger="encar"):
        with pytest.raises(EncarUnavailable) as e:
            _run(c.detail("1"))
    for text in (str(e.value), caplog.text, json.dumps(c.breaker())):
        assert "s3cr" not in text and "alice" not in text and "iproyal" not in text
    assert "<proxy>" in str(e.value)
    assert encar._scrub("x http://u:p@h:1/ y") == "x http://<redacted>@h:1/ y"


def test_client_timeouts_are_bounded(monkeypatch):
    monkeypatch.setenv(encar.PROXY_ENV, PROXY)
    c = EncarClient()
    client = _run(c.client())
    assert client.timeout.connect == 8 and client.timeout.read == 15
    _run(c.close())


def test_without_proxy_url_route_is_direct(monkeypatch):
    monkeypatch.delenv(encar.PROXY_ENV, raising=False)
    assert encar.proxy_url() is None and encar.route() == "direct"
    c = _client(_resp(200, body={"ok": 1}), proxy=None, monkeypatch=monkeypatch)
    assert _run(c.detail("1")) == {"ok": 1}


def test_verify_cli_reports_without_secrets(monkeypatch, capsys):
    monkeypatch.setenv(encar.PROXY_ENV, PROXY)
    encar.set_route("proxy")

    def fake_client(min_interval=0):
        return _client(_resp(407), monkeypatch=None)

    monkeypatch.setattr(encar, "EncarClient", fake_client)
    assert _run(encar.verify()) == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL route=residential_proxy status=407") and "s3cr" not in out
    encar.set_route("auto")


# ── live: an upstream failure must never retire an advert ────────────────────
BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


@pytest.mark.skipif(not BASE, reason="needs the preview URL")
def test_upstream_failure_never_marks_a_listing_sold():
    """`refresh=1` forces the upstream call. Whatever Encar or the proxy does (200, 407,
    timeout), the listing must still be active in the index afterwards — only a genuine 404
    may retire it, and the preview cannot produce one on demand."""
    s = requests.Session()                      # conftest adds the CSRF token to POSTs
    rows = s.post(f"{BASE}/api/search", json={"limit": 3, "lang": "bg"}, timeout=30).json()
    items = rows.get("items") or rows.get("results") or []
    assert items, "search returned nothing to test with"
    car = items[0]
    cid = str(car.get("id") or car.get("_id"))
    r = s.get(f"{BASE}/api/car/{cid}", params={"refresh": 1, "lang": "bg"}, timeout=60)
    assert r.status_code in (200, 502, 503), r.text[:200]
    again = s.post(f"{BASE}/api/search", json={"limit": 50, "lang": "bg"}, timeout=30).json()
    ids = {str(x.get("id") or x.get("_id"))
           for x in (again.get("items") or again.get("results") or [])}
    assert cid in ids, "listing vanished from the active index after an upstream call"
