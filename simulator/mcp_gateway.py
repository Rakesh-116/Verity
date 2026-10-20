"""Streamable-HTTP MCP client used by the simulator host."""

from __future__ import annotations

import json
from typing import Any

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
