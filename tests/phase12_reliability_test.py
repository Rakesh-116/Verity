"""Verification for the reliability rules: explicit transitions, error classes, claims that must be
confirmed, a tamper-evident audit chain, idempotent proposals, escalation, bounded and retried calls.

In-process against a temp copy of the seeded state. No server, no API keys, no sleeps.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from isolated_state import make_isolated_state


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
STATE_DIRECTORY = make_isolated_state()
os.environ["VERITY_STATE_DIR"] = str(STATE_DIRECTORY)
os.environ["GROQ_API_KEY"] = ""
sys.path.insert(0, str(PROJECT_DIRECTORY / "server"))
sys.path.insert(0, str(PROJECT_DIRECTORY))

from services import reliability  # noqa: E402
from services.approval_store import create_proposal  # noqa: E402
from services.claims import check_claims  # noqa: E402
from services.reliability import (  # noqa: E402
    HEDGE_TRANSITIONS,
    PERMISSION,
    PROPOSAL_TRANSITIONS,
    STATE_CONFLICT,
    TRANSIENT,
    UNKNOWN,
    IllegalTransition,
    append_audit,
    check_transition,
    classify_error,
    list_escalations,
    open_escalation,
    verify_audit_chain,
)
from simulator.mcp_gateway import MCPGateway  # noqa: E402
from state.store import append_action_log  # noqa: E402


def test_illegal_transitions_are_refused() -> None:
    check_transition(PROPOSAL_TRANSITIONS, "pending_approval", "approved")
    for current, target in [("approved", "pending_approval"), ("executed", "approved"), ("cancelled", "executed")]:
        try:
            check_transition(PROPOSAL_TRANSITIONS, current, target)
        except IllegalTransition:
            continue
        raise AssertionError(f"{current} -> {target} should be refused")
    check_transition(HEDGE_TRANSITIONS, "committed", "searching")  # fallback re-request is allowed
    try:
        check_transition(HEDGE_TRANSITIONS, "failed", "committed")
    except IllegalTransition:
        pass
    else:
        raise AssertionError("a failed hedge must not be committed")


def test_errors_are_classified_and_unknown_is_never_success() -> None:
    assert classify_error("person_away") == PERMISSION
    assert classify_error("proposal_executed") == STATE_CONFLICT
    assert classify_error("tool_error") == TRANSIENT
    assert classify_error("something_new") == UNKNOWN


def test_a_claim_needs_a_confirmed_tool_result() -> None:
    no_tool = check_claims("Booked. Your ride is on its way.", [])
    assert no_tool["overridden"] and "nothing was changed" in no_tool["speech"], no_tool
    confirmed = check_claims("Booked. Your ride is on its way.", [{"kind": "tool", "name": "book_ride", "ok": True}])
    assert not confirmed["overridden"], confirmed
    denial = check_claims("I haven't booked anything yet.", [])
    assert not denial["overridden"], denial
    failed = check_claims("Booked.", [{"kind": "tool", "name": "book_ride", "ok": False}])
    assert failed["overridden"], failed


def test_the_audit_chain_detects_an_edit() -> None:
    audit_file = STATE_DIRECTORY / "audit_log.jsonl"
    if audit_file.exists():
        audit_file.unlink()
    for number in range(3):
        append_audit({"step": number})
    assert verify_audit_chain() == {"ok": True, "broken_at": None, "records": 3}
    lines = audit_file.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace('"step": 1', '"step": 99')
    audit_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    broken = verify_audit_chain()
    assert broken["ok"] is False and broken["broken_at"] == 1, broken
    audit_file.unlink()  # leave a clean chain for the other tests


def test_logged_actions_are_on_the_audit_chain() -> None:
    before = verify_audit_chain()["records"]
    append_action_log("son", "test", "A logged action.", {"success": True})
    after = verify_audit_chain()
    assert after["ok"] and after["records"] == before + 1, after


def test_the_same_request_returns_the_same_pending_proposal() -> None:
    payload = {"provider": "citycab", "ride_id": "ride.citycab.amma.1", "destination": "market", "expires_at": 1.0}
    first = create_proposal("amma", "ride_booking", payload)
    second = create_proposal("amma", "ride_booking", {**payload, "expires_at": 999.0})
    assert first["proposal_id"] == second["proposal_id"], (first, second)
    other = create_proposal("amma", "ride_booking", {**payload, "destination": "airport"})
    assert other["proposal_id"] != first["proposal_id"]


def test_escalations_go_to_a_named_owner_with_context() -> None:
    case = open_escalation("son", "unconfirmed claim: booked", {"request": "book a ride"})
    assert case["owner"] == "household_admin" and case["status"] == "open", case
    listed = list_escalations("open")
    assert listed["count"] >= 1 and any(item["id"] == case["id"] for item in listed["cases"]), listed


class _FakeGateway:
    def __init__(self, outputs: dict[str, dict]) -> None:
        self.outputs = outputs
        self.calls: list[str] = []

    async def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append(name)
        return {"is_error": False, "output": self.outputs.get(name, {"success": True})}


def test_a_reply_that_claims_booking_without_a_tool_is_overridden_and_escalated() -> None:
    from simulator.agent_host import AgentHost

    host = AgentHost("http://127.0.0.1:1/mcp")
    fake = _FakeGateway({"open_escalation": {"id": "case.0001"}})
    host._gateway = fake
    result = asyncio.run(host._finish_turn({
        "speech": "Booked! Your ride is confirmed.",
        "trace": [{"kind": "tool", "name": "set_device_state", "arguments": {}, "ok": False,
                   "result": {"is_error": False, "output": {"success": False, "reason": "device_not_found"}}}],
    }, "book Amma a ride", "son"))
    assert result["speech"].startswith("I haven't done that yet"), result["speech"]
    assert result["claim_check"]["overridden"] and result["escalation"] == "case.0001", result
    assert "open_escalation" in fake.calls


def test_an_action_that_returns_text_instead_of_a_structured_result_is_unknown_and_escalated() -> None:
    from simulator.agent_host import AgentHost

    host = AgentHost("http://127.0.0.1:1/mcp")
    fake = _FakeGateway({"open_escalation": {"id": "case.0002"}})
    host._gateway = fake
    result = asyncio.run(host._finish_turn({
        "speech": "Done.",
        "trace": [{"kind": "tool", "name": "place_order", "arguments": {}, "ok": True,
                   "result": {"is_error": False, "output": "order placed"}}],
    }, "order groceries", "amma"))
    event = result["trace"][0]
    assert event["ok"] is False and event["error_class"] == UNKNOWN and event["reason"] == "invalid_output", event
    assert result["escalation"] == "case.0002", result


def test_reads_are_retried_on_a_transport_failure_but_changes_are_not() -> None:
    gateway = MCPGateway("http://127.0.0.1:1/mcp")
    attempts = {"read": 0, "write": 0}

    async def flaky(name, arguments):
        attempts["read" if name.startswith("get_") else "write"] += 1
        if attempts["read" if name.startswith("get_") else "write"] < 3 and name.startswith("get_"):
            raise ConnectionError("temporary")
        if name.startswith("book_"):
            raise ConnectionError("may already have booked")
        return {"is_error": False, "output": {"success": True}}

    gateway._call_once = flaky  # type: ignore[method-assign]
    read = asyncio.run(gateway.call_tool("get_home_state", {}))
    assert read["output"]["success"] and attempts["read"] == 3, attempts
    try:
        asyncio.run(gateway.call_tool("book_ride", {}))
    except ConnectionError:
        pass
    else:
        raise AssertionError("a booking failure must surface, not be retried")
    assert attempts["write"] == 1, attempts


if __name__ == "__main__":
    test_illegal_transitions_are_refused()
    test_errors_are_classified_and_unknown_is_never_success()
    test_a_claim_needs_a_confirmed_tool_result()
    test_the_audit_chain_detects_an_edit()
    test_logged_actions_are_on_the_audit_chain()
    test_the_same_request_returns_the_same_pending_proposal()
    test_escalations_go_to_a_named_owner_with_context()
    test_a_reply_that_claims_booking_without_a_tool_is_overridden_and_escalated()
    test_an_action_that_returns_text_instead_of_a_structured_result_is_unknown_and_escalated()
    test_reads_are_retried_on_a_transport_failure_but_changes_are_not()
    print("Phase 12 reliability verification passed.")
