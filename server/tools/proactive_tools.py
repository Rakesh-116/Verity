"""Explainable proactive checks over the controlled virtual-home state."""

from typing import Any

from services.approval_store import approve_proposal, consume_approved_proposal, create_proposal
from state.store import append_action_log, load_json, save_json


def _opportunities() -> list[dict[str, str]]:
    home = load_json("home_state.json")
    opportunities: list[dict[str, str]] = []
    for room_name, room in home.items():
        if room["occupied"]:
            continue
        for device in room["devices"]:
            if device["type"] in {"light", "fan"} and device["state"] == "on":
                opportunities.append({
                    "room": room_name,
                    "device_id": device["id"],
                    "device_type": device["type"],
                    "current_state": device["state"],
                    "recommended_state": "off",
                    "reason": "room_is_currently_unoccupied",
                })
    return opportunities


def get_energy_saving_opportunities() -> dict[str, Any]:
    """Find lights or fans on in currently unoccupied rooms; this never changes devices."""
    opportunities = _opportunities()
    return {
        "opportunities": opportunities,
        "count": len(opportunities),
        "availability": "local",
        "source": "verity.virtual_home",
        "message": "These are suggestions only; a later confirmation is required to change devices.",
    }


def create_energy_saving_proposal(person_id: str, device_ids: list[str]) -> dict[str, Any]:
    """Create a confirmation-required proposal to switch eligible empty-room devices off."""
    memory = load_json("memory.json")
    if person_id not in memory["people"]:
        return {"person_id": person_id, "success": False, "reason": "person_not_found"}
    eligible = {item["device_id"]: item for item in _opportunities()}
    requested = list(dict.fromkeys(device_ids))
    invalid = [device_id for device_id in requested if device_id not in eligible]
    if not requested:
        return {"person_id": person_id, "success": False, "reason": "device_ids_required"}
    if invalid:
        return {"person_id": person_id, "success": False, "reason": "device_not_currently_eligible", "ineligible_device_ids": invalid}
    proposal = create_proposal(person_id, "energy_saving", {"device_ids": requested})
    result = {
        "person_id": person_id,
        "proposal_id": proposal["proposal_id"],
        "status": proposal["status"],
        "devices": [eligible[device_id] for device_id in requested],
        "requires_confirmation": True,
    }
    append_action_log(person_id, "proactive", "Created energy-saving proposal.", result)
    return result


def approve_energy_saving_proposal(person_id: str, proposal_id: str) -> dict[str, Any]:
    """Record explicit approval of an energy-saving proposal without changing a device yet."""
    result = approve_proposal(person_id, proposal_id, "energy_saving")
    if result.get("success"):
        append_action_log(person_id, "proactive", f"Approved energy-saving proposal {proposal_id}.", result)
    return result


def execute_energy_saving_proposal(person_id: str, proposal_id: str) -> dict[str, Any]:
    """Apply an approved proposal only if every device is still on in an empty room."""
    # Validate current state before consuming approval; a stale proposal remains
    # inspectable instead of being falsely recorded as an executed action.
    proposal = load_json("pending_actions.json").get("proposals", {}).get(proposal_id)
    if proposal is None or proposal.get("domain") != "energy_saving":
        return {"proposal_id": proposal_id, "success": False, "reason": "proposal_not_found"}
    if proposal.get("person_id") != person_id:
        return {"proposal_id": proposal_id, "success": False, "reason": "proposal_owner_mismatch"}
    if proposal.get("status") != "approved":
        return {"proposal_id": proposal_id, "success": False, "reason": f"proposal_{proposal.get('status', 'unknown')}"}

    requested = set(proposal["payload"]["device_ids"])
    eligible = {item["device_id"]: item for item in _opportunities()}
    stale = sorted(requested - set(eligible))
    if stale:
        # The proposal stays "approved" (never consumed as executed), so it remains
        # inspectable; home state is not mutated once staleness is detected.
        result = {"person_id": person_id, "proposal_id": proposal_id, "success": False, "reason": "stale_proposal", "stale_device_ids": stale}
        append_action_log(person_id, "proactive", "Refused stale energy-saving proposal.", result)
        return result

    proposal, error = consume_approved_proposal(person_id, proposal_id, "energy_saving")
    if error is not None:
        return error

    home = load_json("home_state.json")
    confirmed: list[dict[str, str]] = []
    for room in home.values():
        for device in room["devices"]:
            if device["id"] in requested:
                previous_state = device["state"]
                device["state"] = "off"
                confirmed.append({"device_id": device["id"], "previous_state": previous_state, "confirmed_state": "off"})
    save_json("home_state.json", home)
    result = {"person_id": person_id, "proposal_id": proposal_id, "success": True, "confirmed_devices": confirmed, "availability": "local", "source": "verity.virtual_home"}
    append_action_log(person_id, "proactive", "Applied confirmed energy-saving proposal.", result)
    return result
