"""Verification for household activities: waiting at the door, watching TV, robot massage, delivery.

In-process against a temp copy of the seeded state. No sleeps, no API keys.
"""

import json
import os
import sys
from pathlib import Path

from isolated_state import make_isolated_state


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
STATE_DIRECTORY = make_isolated_state()
os.environ["VERITY_STATE_DIR"] = str(STATE_DIRECTORY)
sys.path.insert(0, str(PROJECT_DIRECTORY / "server"))

from services.household import set_presence  # noqa: E402
from services.scene import apply_tool_result, scene_summary  # noqa: E402
from tools.scene_tools import end_household_task, start_robot_massage, start_watch  # noqa: E402


def _home() -> dict:
    return json.loads((STATE_DIRECTORY / "home_state.json").read_text(encoding="utf-8"))


def _reset() -> None:
    seed_home = json.loads((PROJECT_DIRECTORY / "server/state/home_state.json").read_text(encoding="utf-8"))
    seed_memory = json.loads((PROJECT_DIRECTORY / "server/state/memory.json").read_text(encoding="utf-8"))
    seed_robot = json.loads((PROJECT_DIRECTORY / "server/state/robot_state.json").read_text(encoding="utf-8"))
    seed_presence = json.loads((PROJECT_DIRECTORY / "server/state/presence.json").read_text(encoding="utf-8"))
    seed_presence["amma"] = {"presence": "home", "return_at": None}  # these tests need Amma home
    (STATE_DIRECTORY / "home_state.json").write_text(json.dumps(seed_home), encoding="utf-8")
    (STATE_DIRECTORY / "memory.json").write_text(json.dumps(seed_memory), encoding="utf-8")
    (STATE_DIRECTORY / "robot_state.json").write_text(json.dumps(seed_robot), encoding="utf-8")
    (STATE_DIRECTORY / "presence.json").write_text(json.dumps(seed_presence), encoding="utf-8")


def test_ride_makes_the_person_wait_at_the_door_until_booked() -> None:
    scene = apply_tool_result({}, "create_ride_booking_proposal", {"person_id": "amma"}, {"success": True, "person_id": "amma"})
    assert scene["amma"]["spot"] == "front_door" and scene["amma"]["stage"] == "preparing", scene
    booked = apply_tool_result(scene, "book_ride", {"person_id": "amma"}, {"success": True, "person_id": "amma", "provider": "citycab"})
    assert booked["amma"]["stage"] == "waiting" and booked["amma"]["bubble"] == "Ride booked. Waiting at the door.", booked
    cancelled = apply_tool_result(booked, "cancel_ride_hedge", {"person_id": "amma"}, {"success": True, "person_id": "amma"})
    assert "amma" not in cancelled, cancelled


def test_failed_or_unknown_calls_never_move_anyone() -> None:
    before = {"son": {"kind": "ride", "spot": "front_door", "bubble": "x", "stage": "waiting"}}
    refused = apply_tool_result(before, "book_ride", {"person_id": "son"}, {"success": False, "reason": "proposal_executed"})
    assert refused == before, refused
    unknown = apply_tool_result(before, "some_other_tool", {"person_id": "amma"}, {"success": True})
    assert unknown == before, unknown


def test_activity_lines_for_the_status_strip() -> None:
    scene = apply_tool_result({}, "start_watch", {}, {"success": True, "person_id": "papa"})
    assert scene_summary(scene, {"papa": "Papa"}) == ["Papa: Watching TV"], scene_summary(scene, {"papa": "Papa"})


def test_presence_away_clears_the_activity() -> None:
    scene = apply_tool_result({}, "start_watch", {}, {"success": True, "person_id": "papa"})
    cleared = apply_tool_result(scene, "set_member_presence", {}, {"success": True, "person_id": "papa", "confirmed_presence": "away"})
    assert "papa" not in cleared, cleared


def test_watch_tv_moves_papa_turns_the_tv_on_and_turns_the_light_off() -> None:
    _reset()
    result = start_watch("papa", duration_min=45)
    assert result["success"] and result["room"] == "tv_room" and result["tv_state"] == "on", result
    home = _home()
    assert "papa" in home["tv_room"]["occupants"], home["tv_room"]["occupants"]
    assert result["light_state"] == "off", result  # Amma is also in the TV room, so the 'alone' rule keeps it off
    tv = next(d for d in home["tv_room"]["devices"] if d["type"] == "tv")
    assert tv["state"] == "on", tv


def test_watch_tv_refused_for_someone_away() -> None:
    _reset()
    set_presence("papa", "away", "19:00")
    refused = start_watch("papa")
    assert refused == {"person_id": "papa", "success": False, "reason": "person_away", "return_at": "19:00"}, refused
    set_presence("papa", "home")


def test_massage_sends_housebot_to_the_members_room_and_labels_it() -> None:
    _reset()
    result = start_robot_massage("amma", duration_min=20)
    assert result["success"] and result["target_person_id"] == "amma", result
    robot = json.loads((STATE_DIRECTORY / "robot_state.json").read_text(encoding="utf-8"))
    assert robot["room"] == result["room"], (robot, result)
    assert "simulated, non-medical" in robot["task"], robot
    scene = apply_tool_result({}, "start_robot_massage", {}, result)
    assert scene["housebot"]["spot"] == "beside:amma" and scene["housebot"]["stage"] == "assisting", scene


def test_massage_refused_for_someone_away() -> None:
    _reset()
    set_presence("amma", "away", "11:30")
    assert start_robot_massage("amma")["reason"] == "target_away"
    set_presence("amma", "home")


def test_end_task_only_clears_the_screen() -> None:
    assert end_household_task("papa") == {"person_id": "papa", "success": True, "ended": True, "also_ends_robot": False}
    assert end_household_task("nobody")["reason"] == "person_not_found"


if __name__ == "__main__":
    test_ride_makes_the_person_wait_at_the_door_until_booked()
    test_failed_or_unknown_calls_never_move_anyone()
    test_activity_lines_for_the_status_strip()
    test_presence_away_clears_the_activity()
    test_watch_tv_moves_papa_turns_the_tv_on_and_turns_the_light_off()
    test_watch_tv_refused_for_someone_away()
    test_massage_sends_housebot_to_the_members_room_and_labels_it()
    test_massage_refused_for_someone_away()
    test_end_task_only_clears_the_screen()
    print("Phase 10 household scenes verification passed.")
