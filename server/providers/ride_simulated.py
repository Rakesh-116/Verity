"""Explicitly simulated ride provider adapters for the Verity controlled demo world."""

import hashlib
import time
from typing import Any

from services.provenance import simulated_provenance


def _varies(*parts: object, spread: int) -> int:
    """A stable number from 0 to spread-1 for these parts, so one minute's quote does not change within the minute."""
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode()).digest()
    return int.from_bytes(digest[:4], "big") % spread


class SimulatedRideProvider:
    """Return simulated quotes that differ by platform and move a little each minute."""

    def __init__(self, provider_id: str, price_inr: int, eta_minutes: int) -> None:
        self.provider_id = provider_id
        self._price_inr = price_inr
        self._eta_minutes = eta_minutes

    def quote(self, person_id: str, destination: str, ride_type: str) -> dict[str, Any]:
        minute = int(time.time() // 60)
        price = self._price_inr + _varies(self.provider_id, minute, "price", spread=21) - 10
        eta = max(2, self._eta_minutes + _varies(self.provider_id, minute, "eta", spread=3) - 1)
        pickup_km = round(0.4 + _varies(self.provider_id, minute, "pickup", spread=30) / 10, 1)
        return {
            "ride_id": f"ride.{self.provider_id}.{person_id}.1",
            "provider": self.provider_id,
            "ride_type": ride_type,
            "destination": destination,
            "price_inr": price,
            "eta_minutes": eta,
            "pickup_km": pickup_km,
            **simulated_provenance(self.provider_id, "ride_quote"),
        }
