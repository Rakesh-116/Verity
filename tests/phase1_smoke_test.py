"""End-to-end MCP stdio verification for the Phase 1 checkpoint."""

import asyncio
import json
import sys
from pathlib import Path

from isolated_state import make_isolated_state, server_environment
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
SERVER_PATH = PROJECT_DIRECTORY / "server" / "server.py"
STATE_DIRECTORY = make_isolated_state()
HOME_STATE_PATH = STATE_DIRECTORY / "home_state.json"


async def verify() -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_PATH)],
        cwd=str(PROJECT_DIRECTORY), env=server_environment(STATE_DIRECTORY),
    )

    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert "get_home_state" in [tool.name for tool in tools.tools]

            result = await session.call_tool("get_home_state", arguments={})
            assert not result.isError
            assert json.loads(result.content[0].text) == json.loads(
                HOME_STATE_PATH.read_text(encoding="utf-8")
            )


if __name__ == "__main__":
    asyncio.run(verify())
    print("Phase 1 end-to-end MCP stdio verification passed.")
