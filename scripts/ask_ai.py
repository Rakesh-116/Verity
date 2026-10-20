"""Manual check for the configured AI provider; not an MCP tool."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from services.ai.orchestrator import AIOrchestrator


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) or "Say that the AI provider is connected."
    ai = AIOrchestrator.from_environment()
    print(ai.respond("You are a concise smart-home assistant.", prompt))
