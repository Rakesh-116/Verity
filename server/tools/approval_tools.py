"""Read-only MCP tools for resolving an explicit confirmation to stored state."""

from typing import Any

from services.approval_store import list_pending_proposals
from state.store import load_json


def list_pending_actions(person_id: str, domain: str | None = None) -> dict[str, Any]:
    """List one person's proposals awaiting explicit approval; this never executes an action."""
    memory = load_json("memory.json")
    if person_id not in memory["people"]:
        return {"person_id": person_id, "success": False, "reason": "person_not_found"}

    proposals = list_pending_proposals(person_id, domain)
    return {
        "person_id": person_id,
        "domain": domain,
        "pending_actions": proposals,
        "count": len(proposals),
    }
