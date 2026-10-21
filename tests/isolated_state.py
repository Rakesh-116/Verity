"""Shared helper: run tests against a temp copy of the seeded state directory."""

import os
import shutil
import tempfile
from pathlib import Path


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
SEED_STATE_DIRECTORY = PROJECT_DIRECTORY / "server" / "state"


def make_isolated_state() -> Path:
    """Copy the seeded JSON state to a fresh temp directory and return it."""
    state_dir = Path(tempfile.mkdtemp(prefix="verity-test-state-"))
    for seed_file in SEED_STATE_DIRECTORY.glob("*.json"):
        shutil.copy(seed_file, state_dir / seed_file.name)
    return state_dir


def server_environment(state_dir: Path) -> dict[str, str]:
    """Environment for the spawned MCP server so it reads and writes the temp state."""
    return {**os.environ, "VERITY_STATE_DIR": str(state_dir)}
