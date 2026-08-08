"""BL 272520178 said it was arriving in Shanghai. Rotterdam was in the data all along.

Three separate faults stacked up on one booking, and each gets a test here:

1. `route()` read only `shipped_from`/`shipped_to`. JSONCargo left those null and put the answer
   in `loading_port`/`discharging_port`, so the destination came back empty.
2. With no destination, `_last_leg` fell back to the last arrival-ish event to date the customs
   and delivery steps. Mid-voyage that is the TRANSSHIPMENT port, so the page announced
   "Customs cleared Shanghai" — a port the box only passes through.
3. The provider answers 200 with a hollow shell, or None, minutes after giving real data.
   Caching that wiped the good snapshot and flipped the whole page to "not found".
"""
import jsoncargo
import tracking

# Exactly what the provider returned for MRKU3210827: the dated fields are null, the port pair
# is not. This is the shape that used to lose Rotterdam.
SNAP = {
    "container_id": "MRKU3210827",
    "container_type": "40' Dry High",
    "container_status": "Vessel departure (WILHELMSHAVEN EXPRESS / 630W)",
    "shipped_from": None,
    "shipped_to": "",
    "shipped_to_terminal": None,
    "atd_origin": "2026-07-08 23:50",
    "eta_final_destination": "2026-09-10 19:00",
    "last_location": "SHANGHAI",
    "timestamp_of_last_location": "2026-07-27 20:03",
    "loading_port": "INCHON",
    "discharging_port": "ROTTERDAM",
    "shipped_from_terminal": "HANJIN INCHON CONTAINER TERMINAL",
    "current_vessel_name": "WILHELMSHAVEN EXPRESS",
    "current_voyage_number": "630W",
    "last_updated": "2026-08-08 19:35",
}


def test_the_destination_comes_from_the_port_pair_when_shipped_to_is_null():
    route = jsoncargo.route(SNAP)
    assert route["to"] == "ROTTERDAM", route
    assert route["from"] == "INCHON", route


def test_the_forecast_names_rotterdam_not_the_transshipment_port():
    stones = jsoncargo.to_events(SNAP)
    forecasts = [s for s in stones if s["estimated"]]
    assert forecasts, "no expected arrival was produced"
    assert all("shanghai" not in s["location"].lower() for s in forecasts), forecasts
    arrival = forecasts[-1]
    assert arrival["location"].lower() == "rotterdam"
    assert arrival["when"].startswith("2026-09-10")
    assert arrival["vessel_name"] == "WILHELMSHAVEN EXPRESS"
    assert arrival["voyage"] == "630W"
    # Shanghai still belongs in the history — as a departure, which is what it was.
    assert any(not s["estimated"] and "shanghai" in s["location"].lower() for s in stones)


async def test_customs_is_never_invented_at_a_port_in_passing():
    """`_last_leg` may only date things off a real discharge (`UV`)."""
    sailing = [
        {"code": "VD", "text": "Departed", "when": "2026-07-08T23:50:00",
         "location": "Inchon", "estimated": False},
        {"code": "VA", "text": "Last movement", "when": "2026-07-27T20:03:00",
         "location": "Shanghai", "estimated": False},
    ]
    assert await tracking._last_leg(None, sailing, None) == []

    landed = sailing + [{"code": "UV", "text": "Discharged", "when": "2026-09-10T19:00:00",
                         "location": "Rotterdam", "estimated": False}]
    tail = await tracking._last_leg(None, landed, None)
    assert tail, "a real discharge must still produce the customs and delivery steps"
    assert all("shanghai" not in (s.get("location") or "").lower() for s in tail), tail
    assert "rotterdam" in (tail[0].get("location") or "").lower()


def test_a_snapshot_holding_only_the_port_pair_is_not_thrown_away():
    """The port pair alone is how we know it is bound for Rotterdam, so it is NOT hollow."""
    assert jsoncargo._hollow({"container_id": "MRKU3210827", "loading_port": "INCHON",
                              "discharging_port": "ROTTERDAM"}) is False
    assert jsoncargo._hollow(SNAP) is False
    # An id and a carrier name and nothing else is the provider having no answer yet.
    assert jsoncargo._hollow({"container_id": "MRKU3210827", "shipping_line_id": "0010",
                              "last_updated": "2026-08-08 19:32"}) is True
