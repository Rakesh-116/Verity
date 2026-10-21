"""Primitive delivery tools with adapters, deterministic ranking, and explicit approval."""

from typing import Any

from providers.delivery_simulated import SimulatedDeliveryProvider
from services.approval_store import approve_proposal, consume_approved_proposal, create_proposal
from services.comparison_engine import rank_quotes
from services.provenance import simulated_provenance
from state.store import append_action_log, load_json


DELIVERY_PROVIDERS = {
    provider.provider_id: provider
    for provider in (
        SimulatedDeliveryProvider("dashmart", base_price_inr=40, eta_minutes=10),
        SimulatedDeliveryProvider("quickmart", base_price_inr=45, eta_minutes=15),
        SimulatedDeliveryProvider("fooddash", base_price_inr=50, eta_minutes=20),
        SimulatedDeliveryProvider("shopnest", base_price_inr=55, eta_minutes=25),
        SimulatedDeliveryProvider("megashop", base_price_inr=60, eta_minutes=30),
    )
}


def _person_preferences(person_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    person = load_json("memory.json")["people"].get(person_id)
    if person is None:
        return None, {"person_id": person_id, "success": False, "reason": "person_not_found"}
    return person["preferences"], None


def compare_item_prices(person_id: str, item: str, providers: list[str] | None = None) -> dict[str, Any]:
    """Compare supported provider prices and rank them; no order is made."""
    preferences, error = _person_preferences(person_id)
    if error is not None:
        return error
    requested = providers or preferences.get("preferred_shopping_providers") or list(DELIVERY_PROVIDERS)
    invalid = [provider for provider in requested if provider not in DELIVERY_PROVIDERS]
    if invalid:
        return {"person_id": person_id, "item": item, "success": False, "reason": "provider_not_supported", "unsupported_providers": invalid}
    quotes = rank_quotes([DELIVERY_PROVIDERS[provider].quote(person_id, item) for provider in requested])
    return {"person_id": person_id, "item": item, "quotes": quotes, "recommended_item_id": quotes[0]["item_id"], "recommendation_reason": "lowest_price_then_fastest_eta"}


def create_order_proposal(person_id: str, provider: str, items: list[str]) -> dict[str, Any]:
    """Create a pending order proposal; explicit approval is required before ordering."""
    _, error = _person_preferences(person_id)
    if error is not None:
        return error
    if provider not in DELIVERY_PROVIDERS:
        return {"person_id": person_id, "provider": provider, "success": False, "reason": "provider_not_supported"}
    if not items or any(not item.strip() for item in items):
        return {"person_id": person_id, "provider": provider, "items": items, "success": False, "reason": "items_required"}
    proposal = create_proposal(person_id, "delivery_order", {"provider": provider, "items": items})
    result = {"person_id": person_id, "success": True, "proposal_id": proposal["proposal_id"], "status": proposal["status"], "provider": provider, "items": items}
    append_action_log(person_id, "delivery", f"Created pending {provider} order proposal.", result)
    return result


def approve_order(person_id: str, proposal_id: str) -> dict[str, Any]:
    """Record explicit approval of a pending order; no order is made yet."""
    result = approve_proposal(person_id, proposal_id, "delivery_order")
    if result.get("success"):
        append_action_log(person_id, "delivery", f"Approved order proposal {proposal_id}.", result)
    return result


def place_order(person_id: str, proposal_id: str) -> dict[str, Any]:
    """Execute exactly one approved simulated order and return the confirmed outcome."""
    proposal, error = consume_approved_proposal(person_id, proposal_id, "delivery_order")
    if error is not None:
        return error
    payload = proposal["payload"]
    provider = payload["provider"]
    result = {"person_id": person_id, "proposal_id": proposal_id, "provider": provider, "items": payload["items"], "success": True, "confirmed_order_id": f"order.{provider}.{person_id}.{proposal_id.rsplit('.', 1)[-1]}", "confirmed_eta_minutes": DELIVERY_PROVIDERS[provider]._eta_minutes, **simulated_provenance(provider, "delivery_order")}
    append_action_log(person_id, "delivery", f"Created simulated {provider} order.", result)
    return result
