"""Explicit, simulated household-robot controls; the robot makes no health inferences."""

from typing import Any

from state.store import append_action_log, load_json, save_json


def get_robot_status() -> dict[str, Any]:
    """Return Housebot's current virtual room, battery, and task."""
    return load_json("robot_state.json")


def send_robot_to_room(room: str, task: str) -> dict[str, Any]:
    """Send the simulated robot to an explicit room for an explicit non-medical task."""
    home = load_json("home_state.json")
    if room not in home:
        return {"requested_room": room, "task": task, "success": False, "reason": "room_not_found"}
    if not task.strip():
        return {"requested_room": room, "task": task, "success": False, "reason": "task_required"}

    robot = load_json("robot_state.json")
    previous_room = robot["room"]
    robot.update({"room": room, "status": "working", "task": task})
    save_json("robot_state.json", robot)
    result = {
        "robot_id": robot["robot_id"],
        "requested_room": room,
        "task": task,
        "success": True,
        "previous_room": previous_room,
        "confirmed_room": room,
        "confirmed_status": "working",
        "availability": "simulated",
        "source": robot["source"],
    }
    append_action_log(None, "robot", f"Sent simulated Housebot to {room} for {task}.", result)
    return result
