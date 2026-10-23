"""Streamable-HTTP MCP client used by the simulator host."""

from __future__ import annotations

import asyncio
import json
from typing import Any

READ_ONLY_PREFIXES = ("get_", "list_", "compare_", "find_", "resolve_", "verify_")

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class MCPGateway:
    """Discovers and invokes Verity tools through its public MCP boundary."""

    def __init__(self, url: str) -> None:
        self._url = url

    async def list_tools(self) -> list[dict[str, Any]]:
        async with streamablehttp_client(self._url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [tool.model_dump(by_alias=True) for tool in result.tools]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Read-only tools are retried on a transport failure with a short backoff. Anything that changes
        state is never retried here: the first attempt may already have happened."""
        # A model sometimes sends an empty argument name; it is not a real argument, so it is dropped.
        arguments = {key: value for key, value in arguments.items() if key}
        if not name.startswith(READ_ONLY_PREFIXES):
            return await self._call_once(name, arguments)
        delays = [0.2, 0.5]
        for attempt in range(len(delays) + 1):
            try:
                return await self._call_once(name, arguments)
            except Exception:
                if attempt == len(delays):
                    raise
                await asyncio.sleep(delays[attempt])
        raise RuntimeError("unreachable")

    async def _call_once(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with streamablehttp_client(self._url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments=arguments)
                if result.structuredContent is not None:
                    output: Any = result.structuredContent
                else:
                    output = [content.model_dump() for content in result.content]
                return {"is_error": result.isError, "output": output}


def as_openai_tools(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate MCP tool discovery output into OpenAI-compatible functions."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
            },
        }
        for tool in mcp_tools
    ]


def as_bedrock_tools(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate MCP discovery output into Amazon Bedrock Converse tool specs."""
    return [
        {
            "toolSpec": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "inputSchema": {
                    "json": tool.get("inputSchema", {"type": "object", "properties": {}})
                },
            }
        }
        for tool in mcp_tools
    ]


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
