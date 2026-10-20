"""Primitive tools for explicit household identity and persistent context."""

from typing import Any

from state.store import append_action_log, load_json, save_json


def get_active_speaker() -> dict[str, Any]:
    """Return the person currently selected by the simulator UI."""
    memory = load_json("memory.json")
    person_id = memory["active_speaker_id"]
    person = memory["people"][person_id]
    return {"person_id": person_id, "display_name": person["display_name"]}


def set_active_speaker(person_id: str) -> dict[str, Any]:
    """Set the explicitly selected household speaker for the current simulator turn."""
    memory = load_json("memory.json")
    person = memory["people"].get(person_id)
    if person is None:
        return {
            "person_id": person_id,
            "success": False,
            "reason": "person_not_found",
            "confirmed_person_id": memory["active_speaker_id"],
        }
    previous_person_id = memory["active_speaker_id"]
    memory["active_speaker_id"] = person_id
    save_json("memory.json", memory)
    result = {
        "person_id": person_id,
        "success": True,
        "previous_person_id": previous_person_id,
        "confirmed_person_id": person_id,
    }
    append_action_log(person_id, "context", f"Selected active speaker {person_id}.", result)
    return result


def get_person_context(person_id: str) -> dict[str, Any]:
    """Return one person's saved preferences without guessing any omitted values."""
    memory = load_json("memory.json")
    person = memory["people"].get(person_id)
    if person is None:
        return {"person_id": person_id, "success": False, "reason": "person_not_found"}
    return {"person_id": person_id, "display_name": person["display_name"], "preferences": person["preferences"]}


def remember_preference(person_id: str, key: str, value: str) -> dict[str, Any]:
    """Persist one explicit preference and return its confirmed before/after values."""
    memory = load_json("memory.json")
    person = memory["people"].get(person_id)
    if person is None:
        return {"person_id": person_id, "key": key, "success": False, "reason": "person_not_found"}
    previous_value = person["preferences"].get(key)
    person["preferences"][key] = value
    save_json("memory.json", memory)
    result = {
        "person_id": person_id,
        "key": key,
        "requested_value": value,
        "success": True,
        "previous_value": previous_value,
        "confirmed_value": person["preferences"][key],
    }
    append_action_log(person_id, "context", f"Updated preference {key}.", result)
    return result


def get_last_session_summary(person_id: str) -> dict[str, Any]:
    """Return the latest recorded state-changing action for one person."""
    memory = load_json("memory.json")
    if person_id not in memory["people"]:
        return {"person_id": person_id, "success": False, "reason": "person_not_found"}
    entries = [entry for entry in memory["session_log"] if entry["person_id"] == person_id]
    if not entries:
        return {"person_id": person_id, "summary": None, "message": "No recorded actions yet."}
    return {"person_id": person_id, "summary": entries[-1]}


def remember_scene(name: str, description: str) -> dict[str, Any]:
    """Store a user-defined scene description; this tool performs no device actions."""
    memory = load_json("memory.json")
    previous_description = memory["scenes"].get(name)
    memory["scenes"][name] = description
    save_json("memory.json", memory)
    result = {
        "name": name,
        "requested_description": description,
        "success": True,
        "previous_description": previous_description,
        "confirmed_description": memory["scenes"][name],
    }
    append_action_log(
        memory["active_speaker_id"], "context", f"Saved scene {name}.", result
    )
    return result


def get_scene(name: str) -> dict[str, Any]:
    """Return a saved scene description without applying its actions."""
    memory = load_json("memory.json")
    description = memory["scenes"].get(name)
    if description is None:
        return {"name": name, "success": False, "reason": "scene_not_found"}
    return {"name": name, "description": description}
