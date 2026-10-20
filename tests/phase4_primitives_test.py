"""MCP verification for Verity's movement, mobility, delivery, travel, and college primitives."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
SERVER_PATH = PROJECT_DIRECTORY / "server" / "server.py"
HOME_STATE_PATH = PROJECT_DIRECTORY / "server" / "state" / "home_state.json"
MEMORY_PATH = PROJECT_DIRECTORY / "server" / "state" / "memory.json"
PENDING_ACTIONS_PATH = PROJECT_DIRECTORY / "server" / "state" / "pending_actions.json"
ROBOT_STATE_PATH = PROJECT_DIRECTORY / "server" / "state" / "robot_state.json"


def output(result: object) -> object:
    return json.loads(result.content[0].text)  # type: ignore[attr-defined]


async def verify() -> None:
    original_home = HOME_STATE_PATH.read_text(encoding="utf-8")
    original_memory = MEMORY_PATH.read_text(encoding="utf-8")
    original_pending_actions = PENDING_ACTIONS_PATH.read_text(encoding="utf-8")
    original_robot_state = ROBOT_STATE_PATH.read_text(encoding="utf-8")
    parameters = StdioServerParameters(command=sys.executable, args=[str(SERVER_PATH)], cwd=str(PROJECT_DIRECTORY))
    try:
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert {"move_person", "get_person_context", "remember_preference", "get_home_state", "list_devices", "set_device_state", "compare_ride_options", "create_ride_booking_proposal", "approve_ride_booking", "book_ride", "compare_item_prices", "create_order_proposal", "approve_order", "place_order", "list_pending_actions", "compare_travel_options", "get_assessment_status", "get_energy_saving_opportunities", "create_energy_saving_proposal", "approve_energy_saving_proposal", "execute_energy_saving_proposal", "get_robot_status", "send_robot_to_room"}.issubset(names)
                moved = output(await session.call_tool("move_person", {"person_id": "son", "room": "living_room"}))
                assert moved["success"] is True and moved["previous_room"] == "bedroom" and moved["confirmed_room"] == "living_room"
                home = output(await session.call_tool("get_home_state", {}))
                assert home["living_room"]["occupants"] == ["son"]
                papa_context = output(await session.call_tool("get_person_context", {"person_id": "papa"}))
                assert papa_context["person_id"] == "papa"
                movie_preference = output(await session.call_tool("remember_preference", {"person_id": "papa", "key": "movie_light_preference", "value": "on_when_alone"}))
                assert movie_preference["confirmed_value"] == "on_when_alone"
                tv_devices = output(await session.call_tool("list_devices", {"room": "tv_room"}))
                assert {device["id"] for device in tv_devices["devices"]} == {"home.tv_room.light.01", "home.tv_room.tv.01"}
                light_change = output(await session.call_tool("set_device_state", {"device_id": "home.tv_room.light.01", "state": "on"}))
                tv_change = output(await session.call_tool("set_device_state", {"device_id": "home.tv_room.tv.01", "state": "on"}))
                assert light_change["success"] is True and tv_change["success"] is True
                quotes = output(await session.call_tool("compare_ride_options", {"person_id": "amma"}))
                quote = quotes["quotes"][0]
                proposal = output(await session.call_tool("create_ride_booking_proposal", {"person_id": "amma", "provider": quote["provider"], "ride_id": quote["ride_id"]}))
                assert proposal["status"] == "pending_approval"
                pending = output(await session.call_tool("list_pending_actions", {"person_id": "amma", "domain": "ride_booking"}))
                assert pending["count"] == 1 and pending["pending_actions"][0]["proposal_id"] == proposal["proposal_id"]
                approval = output(await session.call_tool("approve_ride_booking", {"person_id": "amma", "proposal_id": proposal["proposal_id"]}))
                assert approval["confirmed_status"] == "approved"
                booked = output(await session.call_tool("book_ride", {"person_id": "amma", "proposal_id": proposal["proposal_id"]}))
                assert booked["success"] is True and booked["confirmed_booking_id"]
                items = output(await session.call_tool("compare_item_prices", {"person_id": "amma", "item": "milk"}))
                assert items["quotes"][0]["provider"] == "zepto"
                order_proposal = output(await session.call_tool("create_order_proposal", {"person_id": "amma", "provider": "zepto", "items": ["milk"]}))
                order_approval = output(await session.call_tool("approve_order", {"person_id": "amma", "proposal_id": order_proposal["proposal_id"]}))
                assert order_approval["confirmed_status"] == "approved"
                ordered = output(await session.call_tool("place_order", {"person_id": "amma", "proposal_id": order_proposal["proposal_id"]}))
                assert ordered["success"] is True
                opportunities = output(await session.call_tool("get_energy_saving_opportunities", {}))
                assert opportunities["count"] > 0
                energy_proposal = output(await session.call_tool("create_energy_saving_proposal", {"person_id": "son", "device_ids": [opportunities["opportunities"][0]["device_id"]]}))
                assert energy_proposal["status"] == "pending_approval"
                energy_approval = output(await session.call_tool("approve_energy_saving_proposal", {"person_id": "son", "proposal_id": energy_proposal["proposal_id"]}))
                assert energy_approval["confirmed_status"] == "approved"
                energy_execution = output(await session.call_tool("execute_energy_saving_proposal", {"person_id": "son", "proposal_id": energy_proposal["proposal_id"]}))
                assert energy_execution["success"] is True and energy_execution["confirmed_devices"][0]["confirmed_state"] == "off"
                robot = output(await session.call_tool("send_robot_to_room", {"room": "kitchen", "task": "inspect the counter"}))
                assert robot["success"] is True and robot["confirmed_room"] == "kitchen" and robot["availability"] == "simulated"
                robot_status = output(await session.call_tool("get_robot_status", {}))
                assert robot_status["room"] == "kitchen" and robot_status["status"] == "working"
                travel = output(await session.call_tool("compare_travel_options", {"origin": "Hyderabad", "destination": "Vijayawada", "date": "2026-10-01"}))
                assert {option["mode"] for option in travel["options"]} == {"train", "flight"}
                assessment = output(await session.call_tool("get_assessment_status", {"course": "Machine Learning"}))
                assert assessment["success"] is True and assessment["assessments"]
    finally:
        HOME_STATE_PATH.write_text(original_home, encoding="utf-8")
        MEMORY_PATH.write_text(original_memory, encoding="utf-8")
        PENDING_ACTIONS_PATH.write_text(original_pending_actions, encoding="utf-8")
        ROBOT_STATE_PATH.write_text(original_robot_state, encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(verify())
    print("Phase 4 primitive MCP verification passed.")
