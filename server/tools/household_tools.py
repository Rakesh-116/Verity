"""MCP tools for the household roster, who is home, and name resolution."""

from typing import Any

from services.household import get_presence, resolve_mentions, roster, set_presence
from state.store import append_action_log


def get_household() -> dict[str, Any]:
    """Every household member with role, spoken aliases, and whether they are home or away."""
    members = []
    for person_id, member in roster().items():
        presence = get_presence(person_id)
        members.append({
            "person_id": person_id,
            "display_name": member["display_name"],
            "role": member["role"],
            "aliases": member.get("aliases", []),
            "presence": presence.get("presence"),
            "return_at": presence.get("return_at"),
        })
    return {"members": members, "count": len(members)}


def resolve_household_names(text: str) -> dict[str, Any]:
    """Map spoken names in a request to person IDs, for example 'Amma' to 'amma'."""
    mentions = resolve_mentions(text)
    return {"text": text, "mentions": mentions, "count": len(mentions)}


def set_member_presence(person_id: str, presence: str, return_at: str | None = None) -> dict[str, Any]:
    """Mark a member home or away. Away needs a return time (HH:MM) so the house can show when they are back."""
    result = set_presence(person_id, presence, return_at)
    if result.get("success"):
        append_action_log(person_id, "presence", f"Marked {person_id} {presence}.", result)
    return result
