"""Verify a running local Verity Streamable HTTP endpoint."""

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def verify() -> None:
    async with streamablehttp_client("http://127.0.0.1:8000/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            # Alexa+ track requires spec 2025-11-25 or later over Streamable HTTP.
            # ISO dates compare correctly as strings.
            assert init.protocolVersion >= "2025-11-25", init.protocolVersion
            print(f"negotiated protocolVersion over HTTP: {init.protocolVersion}")
            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            assert {
                "get_home_state", "get_occupancy", "list_devices", "set_device_state"
            }.issubset(tool_names)
            result = await session.call_tool("get_occupancy", {"room": "bedroom"})
            assert result.structuredContent == {
                "room": "bedroom", "occupied": True, "person_count": 1
            }


if __name__ == "__main__":
    asyncio.run(verify())
    print("Verity Streamable HTTP smoke test passed.")
