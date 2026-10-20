"""Truthful source metadata included in all provider results."""

from datetime import UTC, datetime


def simulated_provenance(provider: str, operation: str) -> dict[str, object]:
    """Describe the controlled local adapter without presenting it as a live service."""
    return {
        "operation": operation,
        "availability": "simulated",
        "source": f"verity.simulated.{provider}",
        "timestamp": datetime.now(UTC).isoformat(),
        "simulated": True,
    }
