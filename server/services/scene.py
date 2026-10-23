"""What each household member is doing on screen, derived from confirmed tool results.

Pure functions. The simulator host keeps the scene for the session and the
renderer draws it. A tool result changes the scene only when it succeeded, so a
refused booking never moves anyone.
"""

import time
from copy import deepcopy
from typing import Any


FRONT_DOOR = "front_door"
TV_SEAT = "tv_seat"


def _set(scene: dict[str, Any], person: str, kind: str, spot: str, bubble: str, stage: str) -> None:
    scene[person] = {"kind": kind, "spot": spot, "bubble": bubble, "stage": stage}


def apply_tool_result(scene: dict[str, Any], name: str, arguments: dict[str, Any], output: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """Return the scene after one tool call. Unknown or failed calls leave it unchanged."""
    updated = deepcopy(scene)
    if not isinstance(output, dict) or output.get("success") is False:
        return updated
    person = output.get("person_id") or arguments.get("person_id")

    if name in {"create_ride_booking_proposal", "create_ride_hedge_proposal"} and person:
        _set(updated, person, "ride", FRONT_DOOR, "Getting ready for a ride…", "preparing")
    elif name == "start_ride_hedge" and person:
        _set(updated, person, "ride", FRONT_DOOR, "Waiting at the door. Finding a driver…", "searching")
    elif name == "book_ride" and person:
        _set(updated, person, "ride", FRONT_DOOR, "Ride booked. Waiting at the door.", "waiting")
        pickup = output.get("pickup_seconds_demo", 20)
        updated[person]["ready_at"] = (time.time() if now is None else now) + pickup
    elif name == "cancel_ride_hedge" and person:
        updated.pop(person, None)
    elif name == "start_watch" and person:
        _set(updated, person, "watch", TV_SEAT, "Watching TV", "watching")
    elif name == "start_robot_massage" and output.get("target_person_id"):
        target = output["target_person_id"]
        _set(updated, "housebot", "massage", f"beside:{target}", "Assisting (simulated, not medical)", "assisting")
    elif name == "place_order" and person:
        _set(updated, person, "order", FRONT_DOOR, "Waiting at the door for the delivery", "delivering")
    elif name == "end_household_task" and person:
        updated.pop(person, None)
        if output.get("also_ends_robot"):
            updated.pop("housebot", None)
    elif name == "set_member_presence" and output.get("confirmed_presence") == "away" and person:
        updated.pop(person, None)
    return updated


def advance_scene(scene: dict[str, Any], now: float) -> dict[str, Any]:
    """Once the driver has arrived, the person leaves through the door: the ride is under way."""
    updated = deepcopy(scene)
    for task in updated.values():
        if task.get("stage") == "waiting" and task.get("ready_at") is not None and now >= task["ready_at"]:
            task.update({"stage": "departed", "spot": "street", "bubble": "On the way. The ride is under way."})
    return updated


def scene_summary(scene: dict[str, Any], names: dict[str, str]) -> list[str]:
    """Plain sentences for the status line, one per active task."""
    lines = []
    for person, task in scene.items():
        label = names.get(person, person.title())
        lines.append(f"{label}: {task['bubble']}")
    return lines
