"""Explicitly simulated ride provider adapters for the Verity controlled demo world."""

from typing import Any

from services.provenance import simulated_provenance


class SimulatedRideProvider:
    """Return deterministic mock quotes while preserving a production-like contract."""

    def __init__(self, provider_id: str, price_inr: int, eta_minutes: int) -> None:
        self.provider_id = provider_id
        self._price_inr = price_inr
        self._eta_minutes = eta_minutes

    def quote(self, person_id: str, destination: str, ride_type: str) -> dict[str, Any]:
        return {
            "ride_id": f"ride.{self.provider_id}.{person_id}.1",
            "provider": self.provider_id,
            "ride_type": ride_type,
            "destination": destination,
            "price_inr": self._price_inr,
            "eta_minutes": self._eta_minutes,
            **simulated_provenance(self.provider_id, "ride_quote"),
        }
