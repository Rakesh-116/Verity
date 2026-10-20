"""Explicitly simulated commerce provider adapters for the Verity demo world."""

from typing import Any

from services.provenance import simulated_provenance


class SimulatedDeliveryProvider:
    """Return deterministic mock prices while preserving a production-like contract."""

    def __init__(self, provider_id: str, base_price_inr: int, eta_minutes: int) -> None:
        self.provider_id = provider_id
        self._base_price_inr = base_price_inr
        self._eta_minutes = eta_minutes

    def quote(self, person_id: str, item: str) -> dict[str, Any]:
        return {
            "item_id": f"item.{self.provider_id}.{person_id}.1",
            "provider": self.provider_id,
            "item": item,
            "price_inr": self._base_price_inr,
            "eta_minutes": self._eta_minutes,
            **simulated_provenance(self.provider_id, "item_price"),
        }
