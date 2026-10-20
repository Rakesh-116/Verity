"""End-to-end MCP stdio verification for Verity's household context tools."""

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
    original_home = HOME_STATE_PATH.read_text(encoding="utf-8")
    original_memory = MEMORY_PATH.read_text(encoding="utf-8")
    initial_memory = json.loads(original_memory)
    parameters = StdioServerParameters(
        command=sys.executable, args=[str(SERVER_PATH)], cwd=str(PROJECT_DIRECTORY)
    )
    try:
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                active = response_json(await session.call_tool("get_active_speaker", {}))
                initial_person_id = initial_memory["active_speaker_id"]
                assert active == {
                    "person_id": initial_person_id,
                    "display_name": initial_memory["people"][initial_person_id]["display_name"],
                }
                changed = response_json(await session.call_tool("set_active_speaker", {"person_id": "amma"}))
                assert changed["success"] is True and changed["confirmed_person_id"] == "amma"
                context = response_json(await session.call_tool("get_person_context", {"person_id": "amma"}))
                assert context["preferences"]["usual_ride_type"] == "auto"
                previous_destination = context["preferences"]["usual_destination"]
                preference = response_json(await session.call_tool("remember_preference", {
                    "person_id": "amma", "key": "usual_destination", "value": "Airport"
                }))
                assert preference["previous_value"] == previous_destination
                assert preference["confirmed_value"] == "Airport"
                home_result = response_json(await session.call_tool("set_device_state", {
                    "device_id": "home.living_room.light.01", "state": "off"
                }))
                assert home_result["success"] is True
                summary = response_json(await session.call_tool("get_last_session_summary", {"person_id": "amma"}))
                assert summary["summary"]["domain"] == "home"
                assert summary["summary"]["result"] == home_result
    finally:
        HOME_STATE_PATH.write_text(original_home, encoding="utf-8")
        MEMORY_PATH.write_text(original_memory, encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(verify())
    print("Phase 3 context-tool MCP verification passed.")
