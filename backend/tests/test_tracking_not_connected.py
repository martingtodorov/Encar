"""The message that sent the owner hunting for keys he does not need.

`is_configured()` asked only "is there a MAERSK consumer key". This deployment tracks through
JSONCargo and has no Maersk enterprise arrangement, so that check was permanently False, and
every reference JSONCargo had no data for was reported to the buyer as
"Tracking is not connected - the Maersk Track & Trace keys are missing".

Two different facts had been collapsed into one flag: "we cannot track at all" and "we tracked
and found nothing". These tests keep them apart. They are offline - the metered plan must not be
charged for running the suite.
"""
import os

import pytest
import requests

import jsoncargo
import tracking

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
# The schema lives at the app root, which the ingress sends to the FRONTEND - only /api/* is
# routed to the backend. So this one read goes straight to the service.
SCHEMA_URL = "http://localhost:8001/openapi.json"


def test_the_tracking_endpoint_still_exposes_refresh():
    """A guard against a revert.

    `refresh` is the ONLY way to throw away an answer cached while the carrier was
    misconfigured, and a bill of lading is cached for 30 days - so one stale empty answer
    outlives the fix by a month. Reading the schema costs no provider request; calling the
    endpoint with refresh=true would cost two.
    """
    schema = requests.get(SCHEMA_URL, timeout=30).json()
    names = {p["name"]: p for p in schema["paths"]["/api/tracking"]["get"]["parameters"]}
    assert "refresh" in names, f"the refresh parameter is gone: {sorted(names)}"
    assert names["refresh"]["schema"]["type"] == "boolean"
    assert names["refresh"]["schema"].get("default") is False, "refresh must not default to on"
    for required in ("ref", "by"):
        assert required in names


@pytest.fixture
def env():
    keep = {k: os.environ.get(k) for k in ("JSONCARGO_API_KEY", "MAERSK_CONSUMER_KEY")}
    yield os.environ
    for k, v in keep.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_jsoncargo_alone_counts_as_configured(env):
    """THE BUG: this returned False and the page demanded Maersk keys."""
    env["JSONCARGO_API_KEY"] = "some-key"
    env["MAERSK_CONSUMER_KEY"] = ""
    assert jsoncargo.configured() is True
    assert tracking.is_configured() is True


def test_the_private_maersk_api_is_reported_separately(env):
    """`track()` must still know NOT to call the private REST API without a consumer key."""
    env["JSONCARGO_API_KEY"] = "some-key"
    env["MAERSK_CONSUMER_KEY"] = ""
    assert tracking.maersk_private_configured() is False


def test_a_maersk_key_alone_also_counts(env):
    env["JSONCARGO_API_KEY"] = ""
    env["MAERSK_CONSUMER_KEY"] = "maersk-key"
    assert tracking.is_configured() is True
    assert tracking.maersk_private_configured() is True


def test_nothing_configured_is_the_only_not_connected_case(env):
    """"Not connected" must mean exactly that, and nothing else."""
    env["JSONCARGO_API_KEY"] = ""
    env["MAERSK_CONSUMER_KEY"] = ""
    assert tracking.is_configured() is False


def test_cargo_reports_why_it_came_back_empty(env):
    """A bare None made "no key", "refused" and "no data" indistinguishable to the caller."""
    import asyncio

    env["JSONCARGO_API_KEY"] = ""
    problem = {}

    async def go():
        return await tracking._cargo(None, "MSKU1234567", "container", False, problem)

    assert asyncio.run(go()) is None
    assert problem["reason"] == "no_key"
