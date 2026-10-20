"""Provider contracts for normalized Verity comparison results."""

from typing import Any, Protocol


class RideProvider(Protocol):
    """One provider capable of returning a normalized ride quote."""

    provider_id: str

    def quote(self, person_id: str, destination: str, ride_type: str) -> dict[str, Any]: ...


class DeliveryProvider(Protocol):
    """One provider capable of returning a normalized product quote."""

    provider_id: str

    def quote(self, person_id: str, item: str) -> dict[str, Any]: ...
