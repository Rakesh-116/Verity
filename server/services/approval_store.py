"""Persistent proposal and approval state for consequential simulated actions."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from services.reliability import PROPOSAL_TRANSITIONS, check_transition
from state.store import load_json, save_json


PENDING_ACTIONS_FILE = "pending_actions.json"


def list_pending_proposals(person_id: str, domain: str | None = None) -> list[dict[str, Any]]:
    """Return this person's unapproved proposals, optionally narrowed to one domain."""
    store = load_json(PENDING_ACTIONS_FILE)
    proposals = store.get("proposals", {}).values()
    return [
        proposal
        for proposal in proposals
        if proposal["person_id"] == person_id
        and proposal["status"] == "pending_approval"
        and (domain is None or proposal["domain"] == domain)
    ]


def _same_request(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Two requests are the same if they ask for the same thing; timestamps and expiry are ignored."""
    strip = lambda value: {k: v for k, v in value.items() if k not in {"expires_at", "meeting_at"}}
    return strip(a) == strip(b)


def create_proposal(person_id: str, domain: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a pending proposal; this does not execute an action.

    Idempotent: the same request while one is already pending returns that proposal instead of a second one.
    """
    store = load_json(PENDING_ACTIONS_FILE)
    for existing in store["proposals"].values():
        if existing["person_id"] == person_id and existing["domain"] == domain and existing["status"] == "pending_approval" and _same_request(existing["payload"], payload):
            return existing
    proposal_id = f"proposal.{domain}.{uuid4().hex[:12]}"
    proposal = {
        "proposal_id": proposal_id,
        "person_id": person_id,
        "domain": domain,
        "status": "pending_approval",
        "created_at": datetime.now(UTC).isoformat(),
        "payload": payload,
    }
    store["proposals"][proposal_id] = proposal
    save_json(PENDING_ACTIONS_FILE, store)
    return proposal


def approve_proposal(person_id: str, proposal_id: str, domain: str) -> dict[str, Any]:
    """Record explicit user approval for one pending proposal without executing it."""
    store = load_json(PENDING_ACTIONS_FILE)
    proposal = store["proposals"].get(proposal_id)
    if proposal is None or proposal["domain"] != domain:
        return {"proposal_id": proposal_id, "success": False, "reason": "proposal_not_found"}
    if proposal["person_id"] != person_id:
        return {"proposal_id": proposal_id, "success": False, "reason": "proposal_owner_mismatch"}
    if proposal["status"] != "pending_approval":
        return {"proposal_id": proposal_id, "success": False, "reason": f"proposal_{proposal['status']}"}
    check_transition(PROPOSAL_TRANSITIONS, proposal["status"], "approved")
    proposal["status"] = "approved"
    proposal["approved_at"] = datetime.now(UTC).isoformat()
    save_json(PENDING_ACTIONS_FILE, store)
    return {"proposal_id": proposal_id, "success": True, "confirmed_status": "approved", "payload": proposal["payload"]}


def consume_approved_proposal(person_id: str, proposal_id: str, domain: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Atomically mark one approved proposal executed, or report why it cannot execute."""
    store = load_json(PENDING_ACTIONS_FILE)
    proposal = store["proposals"].get(proposal_id)
    if proposal is None or proposal["domain"] != domain:
        return None, {"proposal_id": proposal_id, "success": False, "reason": "proposal_not_found"}
    if proposal["person_id"] != person_id:
        return None, {"proposal_id": proposal_id, "success": False, "reason": "proposal_owner_mismatch"}
    if proposal["status"] != "approved":
        return None, {"proposal_id": proposal_id, "success": False, "reason": f"proposal_{proposal['status']}"}
    check_transition(PROPOSAL_TRANSITIONS, proposal["status"], "executed")
    proposal["status"] = "executed"
    proposal["executed_at"] = datetime.now(UTC).isoformat()
    save_json(PENDING_ACTIONS_FILE, store)
    return proposal, None


def decline_proposal(person_id: str, proposal_id: str, domain: str) -> dict[str, Any]:
    """Record that the person declined one pending proposal. Nothing is executed; the proposal is cancelled."""
    store = load_json(PENDING_ACTIONS_FILE)
    proposal = store["proposals"].get(proposal_id)
    if proposal is None or proposal["domain"] != domain:
        return {"proposal_id": proposal_id, "success": False, "reason": "proposal_not_found"}
    if proposal["person_id"] != person_id:
        return {"proposal_id": proposal_id, "success": False, "reason": "proposal_owner_mismatch"}
    if proposal["status"] != "pending_approval":
        return {"proposal_id": proposal_id, "success": False, "reason": f"proposal_{proposal['status']}"}
    check_transition(PROPOSAL_TRANSITIONS, proposal["status"], "cancelled")
    proposal["status"] = "cancelled"
    proposal["cancelled_at"] = datetime.now(UTC).isoformat()
    save_json(PENDING_ACTIONS_FILE, store)
    return {"proposal_id": proposal_id, "success": True, "confirmed_status": "cancelled"}
