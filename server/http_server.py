"""Local Streamable HTTP entry point used by the Verity simulator."""

import os
import sys
from pathlib import Path

# The domain modules use the original ``tools.*`` import layout. Make that
# layout available whether this entry point is run as a file or as a module.
SERVER_DIRECTORY = Path(__file__).resolve().parent
if str(SERVER_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SERVER_DIRECTORY))

from app import mcp


if __name__ == "__main__":
    # FastMCP defaults to 127.0.0.1:8000 and /mcp. Keep this local-only until
    # the dedicated transport-hardening checkpoint.
    # VERITY_MCP_PORT lets a second copy run beside another instance (default 8000).
    mcp.settings.port = int(os.getenv("VERITY_MCP_PORT", "8000"))
    # WARNING hides uvicorn per-request access lines; the simulator opens one MCP session per call.
    mcp.settings.log_level = "WARNING"
    mcp.run(transport="streamable-http")
