"""End-to-end MCP stdio verification for the Phase 2 home primitives."""

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


def response_json(result: object) -> object:
    return json.loads(result.content[0].text)  # type: ignore[attr-defined]


async def verify() -> None:
    original_state = HOME_STATE_PATH.read_text(encoding="utf-8")
    original_memory = MEMORY_PATH.read_text(encoding="utf-8")
    parameters = StdioServerParameters(
        command=sys.executable, args=[str(SERVER_PATH)], cwd=str(PROJECT_DIRECTORY)
    )
    try:
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                tool_names = {tool.name for tool in tools.tools}
                assert {
                    "get_home_state", "get_occupancy", "list_devices", "set_device_state"
                }.issubset(tool_names)
                occupancy = response_json(await session.call_tool("get_occupancy", {"room": "bedroom"}))
                assert occupancy == {"room": "bedroom", "occupied": True, "person_count": 1}
                devices = response_json(await session.call_tool("list_devices", {"room": "living_room"}))
                assert devices["devices"][0]["id"] == "home.living_room.light.01"
                changed = response_json(await session.call_tool("set_device_state", {
                    "device_id": "home.living_room.light.01", "state": "off"
                }))
                assert changed == {
                    "device_id": "home.living_room.light.01", "requested_state": "off",
                    "success": True, "previous_state": "on", "confirmed_state": "off"
                }
                home_state = response_json(await session.call_tool("get_home_state", {}))
                assert home_state["living_room"]["devices"][0]["state"] == "off"
                failed = response_json(await session.call_tool("set_device_state", {
                    "device_id": "home.unknown.light.01", "state": "off"
                }))
                assert failed == {
                    "device_id": "home.unknown.light.01", "requested_state": "off",
                    "success": False, "reason": "device_not_found", "confirmed_state": None
                }
    finally:
        HOME_STATE_PATH.write_text(original_state, encoding="utf-8")
        MEMORY_PATH.write_text(original_memory, encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(verify())
    print("Phase 2 home-tool MCP verification passed.")
