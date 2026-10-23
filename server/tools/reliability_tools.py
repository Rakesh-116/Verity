"""MCP tools for escalation and the audit check. Escalations are opened by the app, never by the model's words."""

from typing import Any

from services.reliability import list_escalations as _list, open_escalation as _open, verify_audit_chain as _verify


def open_escalation(person_id: str | None, reason: str, context: dict[str, Any]) -> dict[str, Any]:
    """Hand a case to a named owner with its full context. Nothing is retried or guessed after this."""
    return _open(person_id, reason, context)


def list_escalations(status: str | None = None) -> dict[str, Any]:
    """Open cases for the household owner to review."""
    return _list(status)


def verify_audit_trail() -> dict[str, Any]:
    """Check that the audit trail has not been edited, removed or reordered."""
    return _verify()
