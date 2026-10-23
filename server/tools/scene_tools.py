"""Household activities that move people and devices: watching TV, robot massage, ending a task.

Each tool reuses the existing home, device and robot state, so the house and the
state agree. Presence is checked here in Python before anything moves.
"""

from typing import Any

from services.household import get_presence
from state import people_db
from state.store import append_action_log, load_json
from tools.home_tools import move_person, set_device_state
from tools.robot_tools import send_robot_to_room


MASSAGE_TASK = "massage (simulated, non-medical)"


def _occupants(room: str) -> list[str]:
    return list(load_json("home_state.json")[room].get("occupants", []))


def _room_of(person_id: str) -> str | None:
    home = load_json("home_state.json")
    for room, state in home.items():
        if person_id in state.get("occupants", []):
            return room
    return None


def _device_of_type(room: str, device_type: str) -> str | None:
    for device in load_json("home_state.json")[room]["devices"]:
        if device["type"] == device_type:
            return device["id"]
    return None


def start_watch(person_id: str, duration_min: int = 45) -> dict[str, Any]:
    """Walk a person to the TV room, switch the TV on, and set the light by the household rule."""
    if not people_db.person_exists(person_id):
        return {"person_id": person_id, "success": False, "reason": "person_not_found"}
    presence = get_presence(person_id)
    if presence.get("presence") == "away":
        return {"person_id": person_id, "success": False, "reason": "person_away", "return_at": presence.get("return_at")}
    tv = _device_of_type("tv_room", "tv")
    light = _device_of_type("tv_room", "light")
    if tv is None:
        return {"person_id": person_id, "success": False, "reason": "no_tv_in_room"}

    moved = move_person(person_id, "tv_room")
    if not moved.get("success"):
        return {"person_id": person_id, "success": False, "reason": moved.get("reason", "move_failed")}

    # The household rule from the skill: lights stay on only when the watcher is alone and has asked for it.
    alone = _occupants("tv_room") == [person_id]
    wants_light_on = alone and people_db.get_person(person_id)["preferences"].get("movie_light_preference") == "on_when_alone"
    light_state = None
    if light is not None:
        light_result = set_device_state(light, "on" if wants_light_on else "off")
        light_state = light_result.get("confirmed_state")
    tv_result = set_device_state(tv, "on")
    result = {
        "person_id": person_id,
        "success": True,
        "room": "tv_room",
        "tv_device": tv,
        "tv_state": tv_result.get("confirmed_state"),
        "light_device": light,
        "light_state": light_state,
        "duration_min": duration_min,
        "availability": "simulated",
    }
    append_action_log(person_id, "scene", f"Started watching TV for {duration_min} min.", result)
    return result


def start_robot_massage(target_person_id: str, duration_min: int = 20) -> dict[str, Any]:
    """Send Housebot to sit beside a member who is home, for a simulated, non-medical massage."""
    if not people_db.person_exists(target_person_id):
        return {"target_person_id": target_person_id, "success": False, "reason": "person_not_found"}
    if get_presence(target_person_id).get("presence") == "away":
        return {"target_person_id": target_person_id, "success": False, "reason": "target_away"}
    room = _room_of(target_person_id)
    if room is None:
        return {"target_person_id": target_person_id, "success": False, "reason": "target_not_in_room"}
    sent = send_robot_to_room(room, MASSAGE_TASK)
    if not sent.get("success"):
        return {"target_person_id": target_person_id, "success": False, "reason": sent.get("reason", "robot_failed")}
    result = {
        "target_person_id": target_person_id,
        "success": True,
        "room": room,
        "task": MASSAGE_TASK,
        "duration_min": duration_min,
        "availability": "simulated",
    }
    append_action_log(target_person_id, "scene", f"Housebot massage started for {duration_min} min (simulated).", result)
    return result


def end_household_task(person_id: str) -> dict[str, Any]:
    """Stop the on-screen activity for one person. It does not cancel bookings or change devices."""
    if not people_db.person_exists(person_id):
        return {"person_id": person_id, "success": False, "reason": "person_not_found"}
    return {"person_id": person_id, "success": True, "ended": True, "also_ends_robot": False}
