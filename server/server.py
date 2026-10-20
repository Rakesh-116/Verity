"""Stdio entry point for the Phase 1 MCP server."""

from app import mcp


if __name__ == "__main__":
    mcp.run(transport="stdio")
