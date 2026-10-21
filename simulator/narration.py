"""Plain-English narration of MCP tool calls for the simulator screen.

The raw JSON stays available behind "Details"; these sentences are what a
judge reads. Nothing here decides anything: it only describes a call and its
confirmed result, and falls back to a generic sentence for unknown tools.
"""

from __future__ import annotations

from typing import Any


REASON_TEXT = {
    "person_not_found": "that person is not in this household",
    "room_not_found": "that room is not in the house",
    "device_not_found": "that device is not in the house",
    "invalid_state_for_device_type": "that device cannot be set to that state",
    "proposal_not_found": "that approval request does not exist",
    "proposal_owner_mismatch": "that approval belongs to someone else",
    "proposal_executed": "it was already done once, so it was not repeated",
    "proposal_pending_approval": "it still needs your approval",
    "proposal_approved": "it was already approved",
    "stale_proposal": "the house changed since it was proposed, so it was not applied",
    "ride_quote_not_found": "that ride quote is no longer available",
    "needs_clarification": "I need to know where the ride is going",
    "device_ids_required": "no devices were chosen",
    "device_not_currently_eligible": "those devices are no longer eligible",
    "hedge_not_found": "that ride request does not exist",
    "origin_and_destination_required": "a pickup and a destination are needed",
    "not_enough_quotes_within_fare_cap": "no ride platform is within the fare limit",
    "member_not_found": "no routine history for that person",
}

PLACE_NAMES = {"pg": "PG", "office": "Office"}


def _place(name: Any) -> str:
    text = str(name or "")
    return PLACE_NAMES.get(text.lower(), text.replace("_", " ")) or "the destination"


def _reason(result: dict[str, Any]) -> str:
    code = result.get("reason")
    if code in REASON_TEXT:
        return REASON_TEXT[code]
    return str(code or "it could not be completed").replace("_", " ")


def _output(result: dict[str, Any]) -> dict[str, Any]:
    output = result.get("output")
    return output if isinstance(output, dict) else {}


def _describe(name: str, args: dict[str, Any], out: dict[str, Any]) -> tuple[str, bool]:
    """Return (sentence, ok) for one completed call. ok is False when it was refused."""
    failed = out.get("success") is False
    if name == "get_home_state":
        return "Checked the whole house.", True
    if name == "get_occupancy":
        return f"Checked who is in {args.get('room') or 'each room'}.", not failed
    if name == "list_devices":
        return "Listed the lights, fans and TVs.", True
    if name == "set_device_state":
        if failed:
            return f"Could not change {args.get('device_id')}: {_reason(out)}.", False
        return f"Set {args.get('device_id')} to {out.get('confirmed_state')}.", True
    if name == "move_person":
        if failed:
            return f"Could not move {args.get('person_id')}: {_reason(out)}.", False
        return f"Moved {args.get('person_id')} to {out.get('confirmed_room')}.", True
    if name == "get_person_context":
        return f"Loaded {out.get('display_name') or args.get('person_id')}'s saved preferences.", not failed
    if name == "set_active_speaker":
        return f"Heard {args.get('person_id')} as the speaker.", not failed
    if name == "remember_preference":
        if failed:
            return f"Could not save that preference: {_reason(out)}.", False
        return f"Saved '{args.get('key')}' as {out.get('confirmed_value')}.", True
    if name == "get_energy_saving_opportunities":
        count = out.get("count", 0)
        return f"Found {count} light{'s' if count != 1 else ''} or fan{'s' if count != 1 else ''} on in empty rooms.", True
    if name == "create_energy_saving_proposal":
        if failed:
            return f"Could not propose that change: {_reason(out)}.", False
        return "Proposed switching those off. Waiting for your approval.", True
    if name == "list_pending_actions":
        count = out.get("count", 0)
        return f"Checked pending approvals: {count} waiting.", True
    if name == "approve_energy_saving_proposal" or name == "approve_ride_booking" or name == "approve_order" or name == "approve_ride_hedge":
        if failed:
            return f"Approval refused: {_reason(out)}.", False
        return "Approved.", True
    if name == "execute_energy_saving_proposal":
        if failed:
            return f"Did not switch them off: {_reason(out)}.", False
        return f"Switched off {len(out.get('confirmed_devices', []))} device(s), confirmed.", True
    if name == "compare_ride_options":
        if failed:
            return f"Could not compare rides: {_reason(out)}.", False
        return f"Compared ride prices and driver times to {_place(out.get('destination'))}.", True
    if name == "create_ride_booking_proposal":
        if failed:
            return f"Could not prepare the ride: {_reason(out)}.", False
        return f"Prepared a ride to {_place((out.get('quote') or {}).get('destination'))}. Waiting for your approval.", True
    if name == "book_ride":
        if failed:
            return f"Refused to book the ride: {_reason(out)}.", False
        return f"Booked the ride with {out.get('provider')} (booking {out.get('confirmed_booking_id')}).", True
    if name == "create_ride_hedge_proposal":
        if failed:
            return f"Could not prepare a two-app ride: {_reason(out)}.", False
        return "Prepared a ride request to two apps. Waiting for your approval.", True
    if name == "start_ride_hedge":
        if failed:
            return f"Did not request rides: {_reason(out)}.", False
        return "Asked both ride apps for a driver.", True
    if name == "get_ride_hedge_status":
        if failed:
            return f"Could not read the ride: {_reason(out)}.", False
        return f"Checked the ride: {out.get('plain_status', 'updated')}", True
    if name == "list_ride_hedges":
        return "Checked the ride requests.", True
    if name == "get_routines":
        if failed:
            return f"No usual routine found: {_reason(out)}.", False
        top = (out.get("routines") or [None])[0]
        if top is None:
            return "No usual routine for this time.", True
        return f"Usual pattern found: {top['seen']} of the last {top['of']} times around this time.", True
    if name == "get_robot_status":
        return "Checked Housebot.", True
    if name == "send_robot_to_room":
        return f"Sent Housebot to {args.get('room')}.", not failed
    if name == "get_active_speaker":
        return "Checked who is speaking.", True
    if name == "get_last_session_summary":
        return "Looked up the last action.", True
    if name == "compare_item_prices":
        return "Compared prices for " + str(args.get("item", "that item")) + ".", not failed
    if name == "create_order_proposal":
        return "Prepared an order. Waiting for your approval.", not failed
    if name == "place_order":
        return "Placed the order.", not failed
    if name == "get_assessment_status":
        return f"Checked assessments for {args.get('course', 'that course')} (demo data).", not failed
    if name == "compare_travel_options":
        return "Compared travel options (demo data).", not failed
    return f"Used {name.replace('_', ' ')}.", not failed


def describe_call(name: str, arguments: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Plain sentence and pass/fail flag for one completed tool call."""
    out = _output(result)
    if result.get("is_error"):
        return {"text": f"Could not finish {name.replace('_', ' ')}.", "ok": False}
    text, ok = _describe(name, arguments or {}, out)
    return {"text": text, "ok": ok}


def describe_doing(name: str, arguments: dict[str, Any]) -> str:
    """Present-tense line shown while a call is in progress."""
    args = arguments or {}
    if name == "get_home_state" or name == "list_devices" or name == "get_occupancy":
        return "Checking the house…"
    if name == "set_device_state":
        return f"Switching {args.get('device_id', 'a device')}…"
    if name in {"get_energy_saving_opportunities", "create_energy_saving_proposal"}:
        return "Looking for lights and fans left on in empty rooms…"
    if name == "execute_energy_saving_proposal":
        return "Switching the approved devices off…"
    if name == "compare_ride_options":
        return f"Comparing ride prices to {_place(args.get('destination'))}…"
    if name == "create_ride_booking_proposal":
        return "Preparing the ride for approval…"
    if name == "book_ride":
        return "Booking the approved ride…"
    if name == "create_ride_hedge_proposal":
        return "Preparing a two-app ride request…"
    if name == "start_ride_hedge":
        return "Asking both ride apps for a driver…"
    if name == "get_ride_hedge_status" or name == "list_ride_hedges":
        return "Checking the ride requests…"
    if name == "get_routines":
        return "Checking the usual routine…"
    if name == "get_person_context":
        return "Loading saved preferences…"
    return f"Working: {name.replace('_', ' ')}…"
