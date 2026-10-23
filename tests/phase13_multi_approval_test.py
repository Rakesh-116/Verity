"""Verification for several waiting approvals at once, and for ordering food and groceries.

Each ride or order waits as its own approval. Accept or decline acts only on its own proposal.
In-process with a fake MCP gateway, so no server, no model key, and no sleeps.
"""

import asyncio
import os
import sys
from pathlib import Path

from isolated_state import make_isolated_state


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
STATE_DIRECTORY = make_isolated_state()
os.environ["VERITY_STATE_DIR"] = str(STATE_DIRECTORY)
os.environ["GROQ_API_KEY"] = ""
sys.path.insert(0, str(PROJECT_DIRECTORY / "server"))
sys.path.insert(0, str(PROJECT_DIRECTORY))

from simulator.agent_host import AgentHost  # noqa: E402


class FakeGateway:
    """Answers each household tool the way the real simulated tools do, and records the calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.counter = 0

    async def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        person = arguments.get("person_id")
        if name == "create_ride_booking_proposal":
            self.counter += 1
            proposal_id = f"proposal.ride_booking.{self.counter}"
            quote = {"provider": arguments["provider"], "ride_id": arguments["ride_id"], "destination": arguments.get("destination", "market"), "price_inr": 95, "eta_minutes": 5}
            return {"is_error": False, "output": {"success": True, "proposal_id": proposal_id, "person_id": person, "quote": quote}}
        if name == "create_order_proposal":
            self.counter += 1
            return {"is_error": False, "output": {"success": True, "proposal_id": f"proposal.delivery_order.{self.counter}", "person_id": person, "provider": arguments["provider"], "items": arguments["items"]}}
        if name == "get_household":
            return {"is_error": False, "output": {"members": [{"person_id": "papa", "presence": "home"}, {"person_id": "amma", "presence": "home"}, {"person_id": "son", "presence": "home"}, {"person_id": "housebot", "presence": "home"}]}}
        if name == "get_home_state":
            return {"is_error": False, "output": {"tv_room": {"occupants": ["amma", "papa"]}, "bedroom": {"occupants": ["son"]}}}
        if name == "move_person":
            return {"is_error": False, "output": {"success": True, "person_id": person, "confirmed_room": arguments["room"]}}
        if name == "compare_item_prices":
            return {"is_error": False, "output": {"person_id": person, "item": arguments["item"], "quotes": [{"provider": "dashmart", "price_inr": 40, "item": arguments["item"]}, {"provider": "quickmart", "price_inr": 45, "item": arguments["item"]}]}}
        if name == "book_ride":
            return {"is_error": False, "output": {"success": True, "proposal_id": arguments["proposal_id"], "confirmed_booking_id": f"booking.{arguments['proposal_id']}", "pickup_seconds_demo": 16}}
        if name == "place_order":
            return {"is_error": False, "output": {"success": True, "proposal_id": arguments["proposal_id"], "confirmed_order_id": f"order.{arguments['proposal_id']}"}}
        return {"is_error": False, "output": {"success": True, "proposal_id": arguments.get("proposal_id")}}


def _host(gateway: FakeGateway) -> AgentHost:
    host = AgentHost("http://127.0.0.1:1/mcp")
    host._gateway = gateway
    return host


def _ride_trace(ride_id: str, destination: str) -> list[dict]:
    created = {"kind": "tool", "name": "create_ride_booking_proposal", "arguments": {"person_id": "papa", "provider": "quickride", "ride_id": ride_id, "destination": destination}, "result": {"is_error": False, "output": {"success": True, "proposal_id": None, "person_id": "papa", "quote": {"provider": "quickride", "ride_id": ride_id, "destination": destination, "price_inr": 95, "eta_minutes": 5}}}, "ok": True}
    return [created]


def test_two_rides_wait_as_two_approvals_and_each_is_decided_alone() -> None:
    gateway = FakeGateway()
    host = _host(gateway)
    session = "multi-1"
    first = {"kind": "tool", "name": "create_ride_booking_proposal", "arguments": {"person_id": "papa", "provider": "quickride", "ride_id": "ride.a", "destination": "office"}, "result": {"is_error": False, "output": {"success": True, "proposal_id": "proposal.ride_booking.a", "person_id": "papa", "quote": {"provider": "quickride", "ride_id": "ride.a", "destination": "office", "price_inr": 95, "eta_minutes": 5}}}, "ok": True}
    second = {"kind": "tool", "name": "create_ride_booking_proposal", "arguments": {"person_id": "son", "provider": "citycab", "ride_id": "ride.b", "destination": "college"}, "result": {"is_error": False, "output": {"success": True, "proposal_id": "proposal.ride_booking.b", "person_id": "son", "quote": {"provider": "citycab", "ride_id": "ride.b", "destination": "college", "price_inr": 125, "eta_minutes": 4}}}, "ok": True}
    host._track_ride_confirmation(session, [first])
    host._track_ride_confirmation(session, [second])
    waiting = host.progress(session)["approvals"]
    assert [item["proposal_id"] for item in waiting] == ["proposal.ride_booking.a", "proposal.ride_booking.b"], waiting

    decided = asyncio.run(host.decide(session, "proposal.ride_booking.a", "accept"))
    assert decided["success"], decided
    assert [item["proposal_id"] for item in host.progress(session)["approvals"]] == ["proposal.ride_booking.b"]
    assert host.progress(session)["booking"]["name"] == "Papa", host.progress(session)["booking"]
    booked_ids = [args["proposal_id"] for name, args in gateway.calls if name == "book_ride"]
    assert booked_ids == ["proposal.ride_booking.a"], booked_ids

    declined = asyncio.run(host.decide(session, "proposal.ride_booking.b", "decline"))
    assert declined["success"], declined
    assert host.progress(session)["approvals"] == []
    assert ("decline_ride_booking", {"person_id": "son", "proposal_id": "proposal.ride_booking.b"}) in gateway.calls


def test_a_decision_for_a_proposal_that_is_not_waiting_is_refused() -> None:
    host = _host(FakeGateway())
    result = asyncio.run(host.decide("multi-2", "proposal.ride_booking.none", "accept"))
    assert result["success"] is False and "no longer waiting" in result["speech"], result


def test_ordering_groceries_waits_for_approval_then_places_the_order() -> None:
    gateway = FakeGateway()
    host = _host(gateway)
    session = "order-1"
    trace: list[dict] = []
    speech = asyncio.run(host._scripted_turn("order milk and bread", "amma", session, trace))["speech"]
    assert "for your approval" in speech and "DashMart" in speech, speech
    host._track_ride_confirmation(session, trace)
    waiting = host.progress(session)["approvals"]
    assert len(waiting) == 1 and waiting[0]["kind"] == "order" and waiting[0]["items"] == ["milk and bread"], waiting

    decided = asyncio.run(host.decide(session, waiting[0]["proposal_id"], "accept"))
    assert decided["success"] and "Ordered milk and bread" in decided["speech"], decided
    assert [name for name, _ in gateway.calls if name in {"approve_order", "place_order"}] == ["approve_order", "place_order"]
    assert host.progress(session)["approvals"] == []


def test_watching_tv_asks_others_at_home_to_join_and_declining_sends_them_to_their_room() -> None:
    gateway = FakeGateway()
    host = _host(gateway)
    session = "watch-1"
    asyncio.run(host._offer_watch_invites(session, "request-7", "papa"))
    invites = [item for item in host.progress(session)["approvals"] if item["kind"] == "invite"]
    # Amma is already in the TV room and Papa is the one watching, so only Son is asked.
    assert [item["person_id"] for item in invites] == ["son"], invites
    assert invites[0]["request_id"] == "request-7" and invites[0]["alternatives"][0] == "bedroom"

    joined = asyncio.run(host.decide(session, invites[0]["proposal_id"], "accept"))
    assert joined["success"] and "joined Papa in the TV room" in joined["speech"], joined
    assert ("move_person", {"person_id": "son", "room": "tv_room"}) in gateway.calls

    asyncio.run(host._offer_watch_invites(session, "request-8", "papa"))
    declined_item = next(item for item in host.progress(session)["approvals"] if item["kind"] == "invite")
    declined = asyncio.run(host.decide(session, declined_item["proposal_id"], "decline"))
    assert declined["success"] and "staying in the bedroom" in declined["speech"], declined
    assert ("move_person", {"person_id": "son", "room": "bedroom"}) in gateway.calls


if __name__ == "__main__":
    test_two_rides_wait_as_two_approvals_and_each_is_decided_alone()
    test_a_decision_for_a_proposal_that_is_not_waiting_is_refused()
    test_ordering_groceries_waits_for_approval_then_places_the_order()
    test_watching_tv_asks_others_at_home_to_join_and_declining_sends_them_to_their_room()
    print("Phase 13 multi-approval and ordering verification passed.")
