"""Verification for plain-English steps and live progress in the simulator.

Part 1 is pure: sentences for tool results and in-progress lines.
Part 2 runs the real AgentHost loop with a scripted fake model. It needs the
MCP endpoint running (default http://127.0.0.1:8000/mcp, or VERITY_MCP_URL).
It needs no AI key, and it never uses hidden fallbacks.
"""

import asyncio
import os
import sys
from pathlib import Path


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIRECTORY))
os.environ.setdefault("AI_PROVIDER", "groq")

from simulator.narration import describe_call, describe_doing  # noqa: E402


def test_narration_for_success_and_refusal() -> None:
    ok = describe_call("set_device_state", {"device_id": "home.kitchen.fan.01", "state": "on"}, {"is_error": False, "output": {"success": True, "confirmed_state": "on"}})
    assert ok == {"text": "Set home.kitchen.fan.01 to on.", "ok": True}, ok

    refused = describe_call("book_ride", {}, {"is_error": False, "output": {"success": False, "reason": "proposal_executed"}})
    assert refused["ok"] is False and "already done once" in refused["text"], refused

    stale = describe_call("execute_energy_saving_proposal", {}, {"is_error": False, "output": {"success": False, "reason": "stale_proposal"}})
    assert stale["ok"] is False and "house changed" in stale["text"], stale

    booked = describe_call("book_ride", {}, {"is_error": False, "output": {"success": True, "provider": "citycab", "confirmed_booking_id": "booking.citycab.son.1"}})
    assert booked["ok"] is True and "citycab" in booked["text"], booked


def test_narration_for_ride_hedge_uses_plain_status() -> None:
    result = describe_call("get_ride_hedge_status", {"hedge_id": "h"}, {"is_error": False, "output": {"success": True, "plain_status": "Ride chosen with CityCab."}})
    assert result == {"text": "Checked the ride: Ride chosen with CityCab.", "ok": True}, result


def test_unknown_tool_and_tool_error_are_still_readable() -> None:
    unknown = describe_call("some_new_tool", {}, {"is_error": False, "output": {}})
    assert unknown["text"] == "Used some new tool.", unknown
    failed = describe_call("get_home_state", {}, {"is_error": True, "output": []})
    assert failed == {"text": "Could not finish get home state.", "ok": False}, failed


def test_in_progress_lines_are_plain() -> None:
    assert describe_doing("start_ride_hedge", {}) == "Asking both ride apps for a driver…"
    assert describe_doing("compare_ride_options", {"destination": "office"}) == "Comparing ride prices to Office…"
    assert describe_doing("some_thing", {}) == "Working: some thing…", describe_doing("some_thing", {})


class _Function:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _Call:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.function = _Function(name, arguments)


class _Message:
    def __init__(self, content: str | None = None, tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, message: _Message) -> None:
        self.message = message


class _Response:
    def __init__(self, message: _Message) -> None:
        self.choices = [_Choice(message)]


class _Completions:
    def __init__(self, script: list[_Message]) -> None:
        self._script = script

    def create(self, **_: object) -> _Response:
        return _Response(self._script.pop(0))


class _FakeClient:
    def __init__(self, script: list[_Message]) -> None:
        self.chat = type("Chat", (), {"completions": _Completions(script)})()


async def _run_scripted_turn() -> dict:
    from simulator.agent_host import AgentHost

    script = [
        _Message(tool_calls=[_Call("c1", "list_ride_hedges", "{}")]),
        _Message(content="You have no ride requests right now."),
    ]
    fake = _FakeClient(script)
    AgentHost._client_for = staticmethod(lambda settings: (fake, "scripted-model"))
    host = AgentHost(os.getenv("VERITY_MCP_URL", "http://127.0.0.1:8000/mcp"))
    result = await host.run_turn("Any ride requests?", "son", "phase6-session")
    return {"result": result, "progress": host.progress("phase6-session")}


def test_agent_loop_records_plain_steps_and_idle_progress() -> None:
    outcome = asyncio.run(_run_scripted_turn())
    result, progress = outcome["result"], outcome["progress"]
    tool_events = [event for event in result["trace"] if event["kind"] == "tool"]
    assert tool_events, result["trace"]
    assert tool_events[0]["say"] == "Checked the ride requests." and tool_events[0]["ok"] is True, tool_events[0]
    assert progress["busy"] is False and progress["current"] == "", progress
    assert progress["steps"] == [{"text": "Checked the ride requests.", "ok": True}], progress
    assert result["speech"] == "You have no ride requests right now.", result


if __name__ == "__main__":
    test_narration_for_success_and_refusal()
    test_narration_for_ride_hedge_uses_plain_status()
    test_unknown_tool_and_tool_error_are_still_readable()
    test_in_progress_lines_are_plain()
    test_agent_loop_records_plain_steps_and_idle_progress()
    print("Phase 6 narration and progress verification passed.")
