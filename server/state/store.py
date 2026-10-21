"""Small, shared JSON persistence helpers for the hackathon prototype."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


# VERITY_STATE_DIR lets tests run against a temp copy so tracked JSON is never dirtied.
STATE_DIRECTORY = Path(os.getenv("VERITY_STATE_DIR") or Path(__file__).resolve().parent)


def load_json(filename: str) -> dict[str, Any]:
    """Load a JSON object from the project's state directory."""
    with (STATE_DIRECTORY / filename).open("r", encoding="utf-8") as state_file:
        return json.load(state_file)


def save_json(filename: str, data: dict[str, Any]) -> None:
    """Persist a JSON object to the project's state directory."""
    with (STATE_DIRECTORY / filename).open("w", encoding="utf-8") as state_file:
        json.dump(data, state_file, indent=2)
        state_file.write("\n")


def append_action_log(person_id: str | None, domain: str, description: str, result: dict[str, Any]) -> None:
    """Persist an immutable, truthful record of one state-changing tool call."""
    memory = load_json("memory.json")
    memory["session_log"].append(
        {
            "timestamp": datetime.now(UTC).isoformat(),
            "person_id": person_id,
            "domain": domain,
            "description": description,
            "result": result,
        }
    )
    save_json("memory.json", memory)
