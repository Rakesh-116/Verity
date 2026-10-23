"""Household roster, name resolution, presence and authorisation, decided in Python.

Nothing here calls a model. The host uses these functions before a model turn,
so a spoken name like "Amma" always resolves to the person ID `amma`, and an
away member's command is refused before any tool runs.
"""

import re
from typing import Any

from state.store import load_json, save_json


HOUSEHOLD_FILE = "household.json"
PRESENCE_FILE = "presence.json"
PRESENCE_VALUES = {"home", "away"}
# Words that mean a request changes something. A reply without a tool call to such a request is a failure.
ACTION_PATTERN = re.compile(
    r"\b(book|order|send|watch|massage|cancel|turn|switch|play|buy|help|ask|call|start|set|get|go|take)\b",
    re.IGNORECASE,
)


def roster() -> dict[str, dict[str, Any]]:
    """Every household member with a display name and the spoken names that refer to them."""
    return load_json(HOUSEHOLD_FILE)["members"]


def _alias_table() -> dict[str, str]:
    table: dict[str, str] = {}
    for person_id, member in roster().items():
        table[person_id.lower()] = person_id
        table[member["display_name"].lower()] = person_id
        for alias in member.get("aliases", []):
            table[alias.lower()] = person_id
    return table


def resolve_mentions(text: str) -> list[dict[str, str]]:
    """Find household members named in a request, in order of appearance, without duplicates."""
    table = _alias_table()
    found: list[tuple[int, str, str]] = []
    for alias, person_id in table.items():
        for match in re.finditer(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE):
            found.append((match.start(), match.group(0), person_id))
    found.sort()
    seen: set[str] = set()
    mentions: list[dict[str, str]] = []
    for _, spoken, person_id in found:
        if person_id not in seen:
            seen.add(person_id)
            mentions.append({"spoken": spoken, "person_id": person_id})
    return mentions


def is_action_request(text: str) -> bool:
    return bool(ACTION_PATTERN.search(text))


CLOCK_FILE = "sim_clock.json"
HHMM = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def sim_now() -> str:
    """The simulated house time, HH:MM. Only set through set_sim_time, never by the model."""
    return load_json(CLOCK_FILE)["sim_time"]


def set_sim_time(sim_time: str) -> dict[str, Any]:
    if not HHMM.fullmatch(sim_time):
        return {"success": False, "reason": "invalid_time", "confirmed_sim_time": sim_now()}
    save_json(CLOCK_FILE, {"sim_time": sim_time})
    return {"success": True, "confirmed_sim_time": sim_time}


def get_presence(person_id: str) -> dict[str, Any]:
    """Presence now. An away member returns home by the clock once their return time has passed."""
    entry = load_json(PRESENCE_FILE).get(person_id)
    if entry is None:
        return {"person_id": person_id, "success": False, "reason": "person_not_found"}
    if entry["presence"] == "away" and entry.get("return_at") and sim_now() >= entry["return_at"]:
        return {"person_id": person_id, "presence": "home", "return_at": None}
    return {"person_id": person_id, "presence": entry["presence"], "return_at": entry.get("return_at")}


def set_presence(person_id: str, presence: str, return_at: str | None = None) -> dict[str, Any]:
    """Mark someone home or away. Away needs a return time, HH:MM, so the house can show when they are back."""
    if person_id not in roster():
        return {"person_id": person_id, "success": False, "reason": "person_not_found", "confirmed_presence": None}
    if presence not in PRESENCE_VALUES:
        return {"person_id": person_id, "success": False, "reason": "invalid_presence", "confirmed_presence": None}
    if presence == "away" and not (return_at and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", return_at)):
        return {"person_id": person_id, "success": False, "reason": "return_time_required", "confirmed_presence": None}
    data = load_json(PRESENCE_FILE)
    data[person_id] = {"presence": presence, "return_at": return_at if presence == "away" else None}
    save_json(PRESENCE_FILE, data)
    return {"person_id": person_id, "success": True, "confirmed_presence": presence, "return_at": data[person_id]["return_at"]}


def authorize(speaker: str | None, text: str) -> dict[str, Any]:
    """Decide before any model call whether this request may run at all.

    - An away speaker cannot command the house.
    - An action that names an away member is refused, because a ride, TV or
      massage needs that person at home.
    """
    if speaker is None:
        return {"allowed": True}
    members = roster()
    speaker_state = get_presence(speaker)
    if speaker_state.get("presence") == "away":
        name = members[speaker]["display_name"]
        return {
            "allowed": False,
            "reason": "speaker_away",
            "speech": f"{name} is away until {speaker_state['return_at']}, so I can't act for {name} right now.",
        }
    if is_action_request(text):
        for mention in resolve_mentions(text):
            if mention["person_id"] == speaker:
                continue
            target = get_presence(mention["person_id"])
            if target.get("presence") == "away":
                name = members[mention["person_id"]]["display_name"]
                return {
                    "allowed": False,
                    "reason": "target_away",
                    "speech": f"{name} is away until {target['return_at']}, so I can't do that for {name} now.",
                }
    return {"allowed": True}
