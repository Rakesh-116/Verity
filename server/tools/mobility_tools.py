"""Primitive mobility tools with adapters, deterministic ranking, and explicit approval."""

import re
from typing import Any

from providers.ride_simulated import SimulatedRideProvider
from services.approval_store import approve_proposal, consume_approved_proposal, create_proposal, decline_proposal
from services.comparison_engine import rank_quotes
from services.ride_value import choose_ride
from services.provenance import simulated_provenance
from state import people_db
from state.store import append_action_log, load_json


RIDE_PROVIDERS = {
    provider.provider_id: provider
    for provider in (
        SimulatedRideProvider("quickride", price_inr=95, eta_minutes=5),
        SimulatedRideProvider("rideco", price_inr=110, eta_minutes=7),
        SimulatedRideProvider("citycab", price_inr=125, eta_minutes=4),
    )
}


DEMO_SECONDS_PER_SIMULATED_MINUTE = 4

# Simulated trip distance from the house, in km. Demo data for the comparison, not a map.
DISTANCE_KM = {"market": 2.4, "office": 6.8, "airport": 14.5, "pg": 1.2}
DEFAULT_DISTANCE_KM = 5.0
# Rupees a person accepts paying per minute saved, from their saved ride preference. Cheapest never pays for speed.
TOLERANCE_INR_PER_MIN = {"cheapest": 0.0, "fastest": 60.0}
DEFAULT_TOLERANCE_INR_PER_MIN = 15.0
PROVIDER_LABELS = {"quickride": "QuickRide", "rideco": "RideCo", "citycab": "CityCab"}


def _person_preferences(person_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    person = people_db.get_person(person_id)
    if person is None:
        return None, {"person_id": person_id, "success": False, "reason": "person_not_found"}
    return person["preferences"], None


def compare_ride_options(person_id: str, destination: str | None = None, ride_type: str | None = None) -> dict[str, Any]:
    """Compare provider quotes and rank them deterministically; no booking is made."""
    preferences, error = _person_preferences(person_id)
    if error is not None:
        return error
    resolved_destination = destination or preferences.get("usual_destination")
    resolved_ride_type = ride_type or preferences.get("usual_ride_type") or "auto"
    if not resolved_destination:
        return {"person_id": person_id, "success": False, "reason": "needs_clarification", "field": "destination", "message": "Where should the ride go?"}
    quotes = rank_quotes([provider.quote(person_id, resolved_destination, resolved_ride_type) for provider in RIDE_PROVIDERS.values()])
    # Demo timing: one simulated minute of driver wait is shown as 4 seconds, so pickups stay under 30 s.
    distance_km = DISTANCE_KM.get(resolved_destination, DEFAULT_DISTANCE_KM)
    quotes = [{**quote, "pickup_seconds_demo": quote["eta_minutes"] * DEMO_SECONDS_PER_SIMULATED_MINUTE, "distance_km": distance_km} for quote in quotes]
    priority = preferences.get("ride_priority")
    tolerance = TOLERANCE_INR_PER_MIN.get(priority, DEFAULT_TOLERANCE_INR_PER_MIN)
    chosen, reason = choose_ride(quotes, tolerance, PROVIDER_LABELS)
    # The chosen ride is listed first; the rest keep their price order.
    quotes = sorted(quotes, key=lambda quote: quote["ride_id"] != chosen["ride_id"])
    result = {"person_id": person_id, "destination": resolved_destination, "ride_type": resolved_ride_type, "quotes": quotes, "recommended_ride_id": chosen["ride_id"], "recommendation_reason": reason, "distance_km": distance_km, "ride_priority": priority if priority in {"cheapest", "fastest"} else None}
    if priority not in {"cheapest", "fastest"}:
        # Never guess a preference: the caller must ask the person and save the answer first.
        result["needs_preference"] = {"key": "ride_priority", "question": "Do you want the cheapest ride or the fastest one?", "options": ["cheapest", "fastest"]}
    return result


def _place(name: str | None) -> str | None:
    cleaned = re.sub(r"^the\s+", "", (name or "").strip().lower()).rstrip(".!? ").strip()
    return cleaned or None


def create_ride_booking_proposal(person_id: str, provider: str, ride_id: str, destination: str | None = None) -> dict[str, Any]:
    """Create a pending ride proposal; a later explicit approval is required to book it."""
    preferences, error = _person_preferences(person_id)
    if error is not None:
        return error
    adapter = RIDE_PROVIDERS.get(provider)
    if adapter is None or not ride_id.startswith(f"ride.{provider}.{person_id}."):
        return {"person_id": person_id, "provider": provider, "ride_id": ride_id, "success": False, "reason": "ride_quote_not_found"}
    # Use the destination the person asked for; fall back to the saved one only when none was given.
    # "the market", "Market." and "market" are the same place, so they must make the same proposal.
    resolved_destination = _place(destination) or preferences.get("usual_destination")
    if not resolved_destination:
        return {"person_id": person_id, "provider": provider, "ride_id": ride_id, "success": False, "reason": "needs_clarification", "field": "destination", "message": "Where should the ride go?"}
    quote = adapter.quote(person_id, resolved_destination, preferences.get("usual_ride_type") or "auto")
    proposal = create_proposal(person_id, "ride_booking", quote)
    result = {"person_id": person_id, "success": True, "proposal_id": proposal["proposal_id"], "status": proposal["status"], "quote": quote}
    append_action_log(person_id, "mobility", f"Created pending {provider} ride proposal.", result)
    return result


def approve_ride_booking(person_id: str, proposal_id: str) -> dict[str, Any]:
    """Record explicit approval of a pending ride proposal; no booking is made yet."""
    result = approve_proposal(person_id, proposal_id, "ride_booking")
    if result.get("success"):
        append_action_log(person_id, "mobility", f"Approved ride proposal {proposal_id}.", result)
    return result


def decline_ride_booking(person_id: str, proposal_id: str) -> dict[str, Any]:
    """The person declined this ride proposal. Nothing is booked, and the proposal is cancelled."""
    result = decline_proposal(person_id, proposal_id, "ride_booking")
    if result.get("success"):
        append_action_log(person_id, "mobility", f"Declined ride proposal {proposal_id}.", result)
    return result


def book_ride(person_id: str, proposal_id: str) -> dict[str, Any]:
    """Execute exactly one approved simulated ride proposal and confirm the booking."""
    proposal, error = consume_approved_proposal(person_id, proposal_id, "ride_booking")
    if error is not None:
        return error
    quote = proposal["payload"]
    result = {"person_id": person_id, "proposal_id": proposal_id, "provider": quote["provider"], "ride_id": quote["ride_id"], "success": True, "confirmed_booking_id": f"booking.{quote['provider']}.{person_id}.{proposal_id.rsplit('.', 1)[-1]}", "confirmed_eta_minutes": quote["eta_minutes"], "pickup_seconds_demo": quote["eta_minutes"] * DEMO_SECONDS_PER_SIMULATED_MINUTE, **simulated_provenance(quote["provider"], "ride_booking")}
    append_action_log(person_id, "mobility", f"Created simulated {quote['provider']} ride booking.", result)
    return result
