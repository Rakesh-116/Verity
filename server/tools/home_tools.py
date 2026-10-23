"""Primitive MCP tools for reading and controlling the virtual home."""

from typing import Any

from state import people_db
from state.store import append_action_log, load_json, save_json


VALID_STATES_BY_DEVICE_TYPE = {
    "light": {"on", "off"},
    "fan": {"on", "off"},
    "tv": {"on", "off"},
}

def get_home_state() -> dict[str, Any]:
    """Return the current state of every room in the virtual home."""
    return load_json("home_state.json")


def get_occupancy(room: str | None = None) -> dict[str, Any]:
    """Return occupancy for one room, or every room when room is omitted."""
    home_state = load_json("home_state.json")

    if room is not None:
        room_state = home_state.get(room)
        if room_state is None:
            return {"room": room, "success": False, "reason": "room_not_found"}
        return {
            "room": room,
            "occupied": room_state["occupied"],
            "person_count": room_state["person_count"],
        }

    return {
        room_name: {
            "occupied": room_state["occupied"],
            "person_count": room_state["person_count"],
        }
        for room_name, room_state in home_state.items()
    }


def list_devices(room: str | None = None) -> dict[str, Any]:
    """List explicit-ID devices in one room, or every room when room is omitted."""
    home_state = load_json("home_state.json")
    rooms = {room: home_state.get(room)} if room is not None else home_state

    if room is not None and rooms[room] is None:
        return {"room": room, "success": False, "reason": "room_not_found"}

    devices: list[dict[str, str]] = []
    for room_name, room_state in rooms.items():
        for device in room_state["devices"]:
            devices.append(
                {
                    "id": device["id"],
                    "type": device["type"],
                    "room": room_name,
                    "state": device["state"],
                }
            )
    return {"devices": devices}


def set_device_state(device_id: str, state: str) -> dict[str, Any]:
    """Set one explicit-ID device state and report the confirmed outcome exactly."""
    home_state = load_json("home_state.json")

    for room_state in home_state.values():
        for device in room_state["devices"]:
            if device["id"] != device_id:
                continue

            previous_state = device["state"]
            valid_states = VALID_STATES_BY_DEVICE_TYPE.get(device["type"], set())
            if state not in valid_states:
                return {
                    "device_id": device_id,
                    "requested_state": state,
                    "success": False,
                    "reason": "invalid_state_for_device_type",
                    "confirmed_state": previous_state,
                }

            device["state"] = state
            save_json("home_state.json", home_state)
            result = {
                "device_id": device_id,
                "requested_state": state,
                "success": True,
                "previous_state": previous_state,
                "confirmed_state": device["state"],
            }
            active_speaker_id = load_json("memory.json")["active_speaker_id"]
            append_action_log(
                active_speaker_id,
                "home",
                f"Set {device_id} from {previous_state} to {device['state']}.",
                result,
            )
            return result

    return {
        "device_id": device_id,
        "requested_state": state,
        "success": False,
        "reason": "device_not_found",
        "confirmed_state": None,
    }


def move_person(person_id: str, room: str) -> dict[str, Any]:
    """Move one explicit household person to one explicit room and confirm both locations."""
    home_state = load_json("home_state.json")

    if not people_db.person_exists(person_id):
        return {
            "person_id": person_id,
            "requested_room": room,
            "success": False,
            "reason": "person_not_found",
            "confirmed_room": None,
        }
    if room not in home_state:
        return {
            "person_id": person_id,
            "requested_room": room,
            "success": False,
            "reason": "room_not_found",
            "confirmed_room": None,
        }

    previous_room = None
    for room_name, room_state in home_state.items():
        occupants = room_state.setdefault("occupants", [])
        if person_id in occupants:
            previous_room = room_name
            occupants.remove(person_id)
        room_state["person_count"] = len(occupants)
        room_state["occupied"] = bool(occupants)

    destination = home_state[room]
    destination.setdefault("occupants", []).append(person_id)
    destination["person_count"] = len(destination["occupants"])
    destination["occupied"] = True
    save_json("home_state.json", home_state)

    result = {
        "person_id": person_id,
        "requested_room": room,
        "success": True,
        "previous_room": previous_room,
        "confirmed_room": room,
    }
    append_action_log(person_id, "home", f"Moved {person_id} to {room}.", result)
    return result
