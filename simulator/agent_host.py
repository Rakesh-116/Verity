"""LLM host that chooses MCP tools; it contains no scenario-specific routing."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace
import time
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIRECTORY / "server"))

from groq import Groq
from openai import OpenAI
from services.ai.settings import AISettings

from simulator.mcp_gateway import READ_ONLY_PREFIXES, MCPGateway, as_bedrock_tools, as_openai_tools, json_text
from services.claims import check_claims
from services.reliability import PERMISSION, UNKNOWN, classify_error
from simulator.narration import describe_call, describe_doing
from services.household import authorize, is_action_request, resolve_mentions, roster as household_roster
from services.scene import advance_scene, apply_tool_result, scene_summary
from simulator.scripted_demo import PROVIDER_NAMES, is_confirmation, is_preference_answer, run_scripted


SKILL_PATH = PROJECT_DIRECTORY / "skills" / "verity" / "SKILL.md"


NO_TOOL_NOTE = (
    "\n[Simulator note: this is an action request. You must call the matching tool now. "
    "Do not answer without a tool call.]"
)


GOING_OUT = re.compile(r"\b(going out|going outside|heading out|leaving the house|i'?m leaving|i am leaving|step out)\b", re.I)
COMING_BACK = re.compile(r"\b(i'?m back|i am back|i'?m home|i am home|got back)\b", re.I)


def _activity_lines(scene: dict[str, Any]) -> list[str]:
    """What is happening in the house right now, so the model does not have to guess: a massage in progress, and anyone out on a ride."""
    names = {pid: member["display_name"] for pid, member in household_roster().items()}
    lines = []
    for person, task in scene.items():
        if task.get("kind") == "massage" and str(task.get("spot", "")).startswith("beside:"):
            target = task["spot"].split(":", 1)[1]
            lines.append(f"Housebot is giving {names.get(target, target)} a massage (person_id {target}). end_household_task with person_id {target} stops it.")
        elif task.get("kind") == "ride" and task.get("stage") == "departed":
            lines.append(f"{names.get(person, person)} (person_id {person}) has left on a ride and is out of the house.")
    return lines


def household_context(text: str, speaker: str | None, waiting: bool = False, extra: list[str] | None = None) -> str:
    """Per-turn context the model cannot recall by itself: IDs, the speaker, resolved names, and a ride awaiting a yes."""
    lines = [f"{pid}={member['display_name']} ({member['role']})" for pid, member in household_roster().items()]
    parts = [f"[Household IDs: {', '.join(lines)}.]"]
    if speaker:
        parts.append(f"[Speaker person_id: {speaker}.]")
    if waiting:
        parts.append("[A ride is waiting for the person's confirmation on screen. Do not ask for approval in text; the app handles the yes or no.]")
    for line in extra or []:
        parts.append(f"[{line}]")
    for mention in resolve_mentions(text):
        parts.append(
            f"['{mention['spoken']}' in the request means person_id {mention['person_id']}. "
            "Use that exact ID in tool calls.]"
        )
    return text + "\n" + " ".join(parts)


def _is_rate_limit(error: Exception) -> bool:
    text = str(error).lower()
    return "429" in text or "rate limit" in text or type(error).__name__ == "RateLimitError"


def _is_daily_limit(error: Exception) -> bool:
    text = str(error).lower()
    return "per day" in text or "tokens per day" in text or "(tpd)" in text


def _retry_after(error: Exception) -> float | None:
    """Groq says how long to wait in the message: 'Please try again in 3.26s'."""
    match = re.search(r"try again in ([0-9.]+)s", str(error))
    return float(match.group(1)) if match else None


# Each keyword group adds the tools it needs. Every request also gets the core set. A short or unclear
# request gets every tool, so a tool is only left out when the wording clearly points away from it.
CORE_TOOLS = {
    "get_person_context", "get_household", "get_home_state", "get_active_speaker", "set_active_speaker",
    "resolve_household_names", "list_pending_actions", "get_last_session_summary", "get_assessment_status",
}
TOOL_GROUPS = [
    (r"ride|cab|taxi|car\b|airport|market|hedge|book|meeting|deadline|travel|bus|train|late|school|\bpg\b",
     {"compare_ride_options", "compare_travel_options", "create_ride_booking_proposal", "approve_ride_booking",
      "book_ride", "start_ride_hedge", "get_ride_hedge_status", "list_ride_hedges", "cancel_ride_hedge",
      "create_ride_hedge_proposal", "approve_ride_hedge", "find_meeting_deadline"}),
    (r"order|buy|grocer|price|shop|cart|milk|food|deliver", {"compare_item_prices", "create_order_proposal", "approve_order", "place_order"}),
    (r"watch|tv|massage|robot|housebot|clean|help|relax|stop|finish", {"start_watch", "start_robot_massage", "end_household_task", "send_robot_to_room", "get_robot_status", "get_scene", "remember_scene"}),
    (r"light|fan|device|plug|energy|power|\bac\b|heater|turn|switch|lamp|\bon\b|\boff\b", {"list_devices", "set_device_state", "get_energy_saving_opportunities", "create_energy_saving_proposal", "approve_energy_saving_proposal", "execute_energy_saving_proposal", "get_occupancy"}),
    (r"\b(away|home|leave|left|back|out|move|going|room|where|clock|time|tomorrow|am|pm)\b|\d:\d\d",{"set_member_presence", "move_person", "set_sim_clock", "get_occupancy", "get_sim_time", "get_routines"}),
    (r"prefer|remember|usual|routine|always|save|style|default|favou?rite|policy", {"remember_preference", "get_routines", "remember_scene"}),
    (r"escalat|audit|verify|log|history|proof|review|case", {"open_escalation", "list_escalations", "verify_audit_trail"}),
]


def tools_for_request(text: str, mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(text.split()) < 4:
        return mcp_tools
    wanted = set(CORE_TOOLS)
    matched = False
    for pattern, names in TOOL_GROUPS:
        if re.search(pattern, text.lower()):
            wanted |= names
            matched = True
    if not matched:
        return mcp_tools
    return [tool for tool in mcp_tools if tool["name"] in wanted]


def _tool_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [event for event in result.get("trace", []) if event.get("kind") == "tool"]


# Bounded execution: a model turn stops after this many seconds, whatever else is happening.
RUN_TIME_LIMIT_S = 60
# A rider who has left on a ride comes back after this many real seconds (the page shows the countdown).
RIDER_RETURN_AFTER_S = 180
# Each round is one model call plus its tool calls. A ride needs about five rounds (preferences, compare, prepare, reply).
MAX_TOOL_ROUNDS = 10


class AgentHost:
    """Runs a bounded tool-calling loop for one simulated Alexa+ turn."""

    def __init__(self, mcp_url: str) -> None:
        self._gateway = MCPGateway(mcp_url)
        self._skill = SKILL_PATH.read_text(encoding="utf-8")
        # This is deliberately short-lived simulator conversation context, not
        # persistent user memory. Durable preferences remain MCP-owned JSON state.
        self._session_history: dict[str, list[dict[str, str]]] = {}
        # Live, plain-English progress per browser session; the UI polls it while a turn runs.
        self._progress: dict[str, dict[str, Any]] = {}
        # What each member is doing on screen, derived from confirmed tool results.
        self._scene: dict[str, Any] = {}
        # Riders who have left on a ride, and when each comes back (epoch seconds).
        self._returns: dict[str, float] = {}
        # A ride waiting for the person's "yes", per session (scripted demo only).
        self._pending: dict[str, dict[str, Any]] = {}
        # Set when the last model answer came from the fallback provider, so the page can say so.
        self._last_fallback: str | None = None

    def progress(self, session_id: str | None) -> dict[str, Any]:
        """What Verity is doing right now for this session, in plain words, and any ride waiting for a yes."""
        state = self._progress.get(session_id or "local", {"busy": False, "current": "", "steps": []})
        pending = self._pending.get(session_id or "local") or {}
        waiting = pending if "proposal_id" in pending else None
        booking = pending.get("booking")
        return {
            "busy": state["busy"],
            "current": state["current"],
            "steps": list(state["steps"]),
            "pending": waiting and {"person_id": waiting["person_id"], "name": waiting["name"], "provider": waiting["provider"], "provider_name": waiting.get("provider_name"), "destination": waiting["destination"], "pickup_seconds": waiting.get("pickup_seconds"), "price_inr": waiting.get("price_inr"), "eta_min": waiting.get("eta_min"), "ride_priority": waiting.get("ride_priority")},
            "booking": booking,
        }

    async def rides(self) -> dict[str, Any]:
        """Ride request cards, read through MCP like the rest of the dashboard."""
        result = await self._gateway.call_tool("list_ride_hedges", {})
        if result["is_error"]:
            raise RuntimeError(f"list_ride_hedges failed: {result['output']}")
        return result["output"]

    async def _finish_turn(self, result: dict[str, Any], text: str, speaker: str | None, session_id: str | None = None) -> dict[str, Any]:
        """The last step of every turn: classify each failure, check tool outputs are structured,
        check the reply's claims, and escalate what a person must decide."""
        trace = result.get("trace", [])
        reasons: list[str] = []
        for event in trace:
            if event.get("kind") != "tool":
                continue
            output = event["result"].get("output")
            reason = None
            if event["result"].get("is_error"):
                reason = "tool_error"
            elif not event["name"].startswith(READ_ONLY_PREFIXES) and (not isinstance(output, dict) or "success" not in output):
                reason = "invalid_output"  # an action must return a structured confirmation, never a bare text
            elif isinstance(output, dict) and output.get("success") is False:
                reason = output.get("reason") or "unknown_refusal"
            if reason:
                event["ok"] = False
                event["reason"] = reason
                event["error_class"] = classify_error(reason)
                if event["error_class"] in {PERMISSION, UNKNOWN}:
                    reasons.append(f"{event['name']}: {reason}")
        # A question the app needs answered is shown as buttons in the reply, and the answer is routed back here.
        for event in trace:
            if event.get("kind") == "tool" and event["name"] == "compare_ride_options":
                output = event["result"].get("output")
                if isinstance(output, dict) and output.get("needs_preference"):
                    result["question"] = {"key": "ride_priority", "text": output["needs_preference"]["question"], "options": output["needs_preference"]["options"], "person_id": output.get("person_id")}
                    self._pending.setdefault(session_id or "local", {})["awaiting"] = {"person_id": output.get("person_id"), "ride_text": text}
        checked = check_claims(result.get("speech", ""), trace)
        if checked["overridden"]:
            result["speech"] = checked["speech"]
            result["claim_check"] = {"overridden": True, "claim": checked["claim"]}
            reasons.append(f"unconfirmed claim: {checked['claim']}")
        if any(event.get("kind") == "no_tool_call" for event in trace):
            reasons.append("no tool call for an action request")
        if result.get("speech", "").startswith("I reached the tool-call limit") or result.get("speech", "").startswith("I ran out of time"):
            reasons.append("run limit reached")
        if reasons:
            try:
                case = await self._gateway.call_tool("open_escalation", {
                    "person_id": speaker,
                    "reason": "; ".join(reasons),
                    "context": {"request": text, "speech": result.get("speech", ""), "trace": [e.get("name", e.get("kind")) for e in trace]},
                })
                if not case["is_error"]:
                    result["escalation"] = case["output"].get("id")
            except Exception:
                result["escalation"] = None  # the reply still goes out; the failure is in the trace
        return result

    async def cancel_ride(self, person_id: str, hedge_id: str) -> dict[str, Any]:
        """Cancel a ride request the person asked to cancel; the result is what MCP confirmed."""
        result = await self._gateway.call_tool("cancel_ride_hedge", {"person_id": person_id, "hedge_id": hedge_id})
        if result["is_error"]:
            return {"success": False, "reason": "tool_error", "detail": str(result["output"])}
        return result["output"]

    @staticmethod
    def _add_step(progress: dict[str, Any], text: str, ok: bool) -> None:
        progress["steps"].append({"text": text, "ok": ok})

    async def dashboard_state(self) -> dict[str, Any]:
        """Read render-only household state through the same MCP client."""
        await self._tick_household()
        home = await self._gateway.call_tool("get_home_state", {})
        speaker = await self._gateway.call_tool("get_active_speaker", {})
        robot = await self._gateway.call_tool("get_robot_status", {})
        opportunities = await self._gateway.call_tool("get_energy_saving_opportunities", {})
        household = await self._gateway.call_tool("get_household", {})
        # Someone who is away (by the clock or by a change) has no activity on screen.
        away = {m["person_id"] for m in (household["output"] or {}).get("members", []) if m.get("presence") == "away"}
        self._scene = advance_scene(self._scene, time.time())
        scene = {person: task for person, task in self._scene.items() if person not in away}
        return {
            "home": home["output"],
            "active_speaker": speaker["output"],
            "robot": robot["output"],
            "proactive": opportunities["output"],
            "household": household["output"],
            "scene": scene,
            "mode": await self.mode(),
            "clock": await self.clock(),
            "returns": self.returns_in_seconds(),
            "scene_lines": scene_summary(scene, {p: m["display_name"] for p, m in household_roster().items()}),
        }

    def _track_ride_confirmation(self, session_id: str | None, trace: list[dict[str, Any]]) -> None:
        """A ride the model proposed waits for a yes, the same as the scripted demo: the page shows it as a popup."""
        pending = self._pending.setdefault(session_id or "local", {})
        roster = household_roster()
        for event in trace:
            if event.get("kind") != "tool" or event["result"].get("is_error"):
                continue
            output = event["result"].get("output")
            if not isinstance(output, dict) or output.get("success") is False:
                continue
            if event["name"] == "create_ride_booking_proposal":
                quote = output.get("quote") or {}
                person = output.get("person_id") or event["arguments"].get("person_id")
                provider = quote.get("provider") or event["arguments"].get("provider", "")
                # The saved preference this ride was chosen by, from the comparison in the same turn (None if not saved).
                priority = next((e["result"]["output"].get("ride_priority") for e in trace if e.get("kind") == "tool" and e["name"] == "compare_ride_options" and isinstance(e["result"].get("output"), dict)), None)
                pending.clear()
                pending.update({
                    "ride_priority": priority,
                    "proposal_id": output["proposal_id"],
                    "person_id": person,
                    "name": roster.get(person, {}).get("display_name", person),
                    "provider": provider,
                    "provider_name": PROVIDER_NAMES.get(provider, provider),
                    "destination": quote.get("destination") or event["arguments"].get("destination", ""),
                    "eta_min": quote.get("eta_minutes"),
                    "price_inr": quote.get("price_inr"),
                })
            elif event["name"] in {"approve_ride_booking", "book_ride"} and output.get("proposal_id") == pending.get("proposal_id"):
                pending.clear()

    @staticmethod
    def llm_configured() -> bool:
        """True when a model key or provider is configured. Without one, the scripted demo runs, labelled as such."""
        settings = AISettings.from_environment()
        if settings.provider == "groq":
            return bool(settings.groq_api_key)
        if settings.provider == "openai":
            return bool(settings.openai_api_key)
        if settings.provider == "ollama":
            return True
        return settings.provider == "bedrock"

    async def mode(self) -> str:
        if self._last_fallback:
            return f"fallback:{self._last_fallback}"
        if not self.llm_configured():
            return "scripted"
        return f"ai:{AISettings.from_environment().provider}"

    async def clock(self) -> dict[str, Any]:
        result = await self._gateway.call_tool("get_sim_time", {})
        return result["output"] if not result["is_error"] else {"sim_time": None}

    async def set_clock(self, sim_time: str) -> dict[str, Any]:
        result = await self._gateway.call_tool("set_sim_clock", {"sim_time": sim_time})
        return result["output"] if not result["is_error"] else {"success": False, "reason": "tool_error"}

    async def _scripted_turn(self, text: str, speaker: str | None, session_id: str | None, trace: list[dict[str, Any]]) -> dict[str, Any]:
        """Run the labelled no-key demo through the same MCP tools, recording each call like a model turn."""
        pending = self._pending.setdefault(session_id or "local", {})
        roster = household_roster()

        def record(name: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
            narrated = describe_call(name, arguments, result)
            trace.append({"kind": "tool", "name": name, "arguments": arguments, "result": result, "say": narrated["text"], "ok": narrated["ok"]})
            if not result.get("is_error"):
                self._scene = apply_tool_result(self._scene, name, arguments, result.get("output"))

        async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            result = await self._gateway.call_tool(name, arguments)
            record(name, arguments, result)
            return result["output"] if not result["is_error"] and isinstance(result["output"], dict) else {"success": False, "reason": "tool_error"}

        trace.append({"kind": "user", "text": text})
        speech = await run_scripted(text, speaker, pending, roster, call)
        return {"speech": speech, "trace": trace, "mode": "scripted"}

    async def _tick_household(self) -> None:
        """Keeps the house true as time passes. Someone who has left on a ride is out of the house in the server's
        state, with a return time; when that time passes they come back home. The model never reports them in a room."""
        now = time.time()
        self._scene = advance_scene(self._scene, now)
        household = await self._gateway.call_tool("get_household", {})
        presence = {m["person_id"]: m.get("presence") for m in (household["output"] or {}).get("members", [])}
        for person, task in self._scene.items():
            if task.get("stage") == "departed" and presence.get(person) == "home":
                await self._gateway.call_tool("set_member_presence", {"person_id": person, "presence": "away"})
                self._returns[person] = now + RIDER_RETURN_AFTER_S
        for person, due in list(self._returns.items()):
            if now >= due:
                await self._gateway.call_tool("set_member_presence", {"person_id": person, "presence": "home"})
                self._returns.pop(person, None)
                self._scene.pop(person, None)

    def returns_in_seconds(self) -> dict[str, int]:
        now = time.time()
        return {person: max(0, round(due - now)) for person, due in self._returns.items()}

    async def _presence_from_speech(self, text: str, speaker: str | None, trace: list[dict[str, Any]]) -> str | None:
        """Someone who says they are leaving or back changes their own presence in the server. The model is told what changed."""
        if not speaker:
            return None
        if GOING_OUT.search(text):
            presence, say = "away", "is out of the house"
        elif COMING_BACK.search(text):
            presence, say = "home", "is back home"
        else:
            return None
        name = household_roster().get(speaker, {}).get("display_name", speaker)
        output = await self.set_presence(speaker, presence, None)
        if presence == "home" and output.get("success"):
            self._scene.pop(speaker, None)
            self._returns.pop(speaker, None)
        ok = output.get("success") is True
        trace.append({"kind": "tool", "name": "set_member_presence", "arguments": {"person_id": speaker, "presence": presence}, "result": {"is_error": False, "output": output}, "say": f"{name} {say}." if ok else "Could not change presence.", "ok": ok})
        return f"{name} has just been marked as {presence}: {say}." if ok else None

    async def set_presence(self, person_id: str, presence: str, return_at: str | None) -> dict[str, Any]:
        """Mark someone home or away through MCP, so the house and the guard agree."""
        arguments: dict[str, Any] = {"person_id": person_id, "presence": presence}
        if return_at:
            arguments["return_at"] = return_at
        result = await self._gateway.call_tool("set_member_presence", arguments)
        if result["is_error"]:
            return {"success": False, "reason": "tool_error"}
        if result["output"].get("success") and presence == "away":
            # Someone who has left is not shown doing anything in the house.
            self._scene.pop(person_id, None)
        return result["output"]

    async def run_turn(
        self,
        text: str,
        active_speaker_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            mcp_tools = await self._gateway.list_tools()
        except Exception as error:
            return {
                "speech": "I can't reach the local Verity MCP server yet.",
                "trace": [{"kind": "connection_error", "detail": str(error)}],
            }

        trace: list[dict[str, Any]] = []
        if active_speaker_id is not None:
            selection = await self._gateway.call_tool(
                "set_active_speaker", {"person_id": active_speaker_id}
            )
            trace.append({"kind": "speaker_selection", "result": selection})
            if selection["is_error"] or not selection["output"].get("success"):
                return {
                    "speech": "I could not select that household member.",
                    "trace": trace,
                }

        # Presence is decided in Python before any model call: an away speaker cannot command the house.
        auth = authorize(active_speaker_id, text)
        if not auth["allowed"]:
            trace.append({"kind": "authorization", "reason": auth["reason"]})
            return {"speech": auth["speech"], "trace": trace}

        await self._tick_household()
        presence_note = await self._presence_from_speech(text, active_speaker_id, trace)
        pending = self._pending.get(session_id or "local", {})
        waiting = "proposal_id" in pending
        # A plain yes or no answers the ride on screen. The app handles it, the same way with or without a model.
        awaiting = "awaiting" in pending
        if (waiting and is_confirmation(text)) or (awaiting and is_preference_answer(text)) or not self.llm_configured():
            return await self._finish_turn(await self._scripted_turn(text, active_speaker_id, session_id, trace), text, active_speaker_id, session_id)

        history_key = self._history_key(session_id, active_speaker_id)
        history = list(self._session_history.get(history_key, []))
        model_text = household_context(text, active_speaker_id, waiting, _activity_lines(self._scene) + ([presence_note] if presence_note else []))
        progress_key = session_id or "local"
        progress = {"busy": True, "current": "Thinking about what you asked…", "steps": []}
        self._progress[progress_key] = progress
        # Only the tools this request needs are sent: fewer tokens per call, so the per-minute limit is hit less.
        turn_tools = tools_for_request(text, mcp_tools)
        try:
            base_trace = list(trace)
            result = await self._llm_turn(model_text, turn_tools, active_speaker_id, trace, history, progress)
            if not _tool_events(result) and is_action_request(text):
                # Forced tool use: an action with no tool call gets one retry, then an explicit failure.
                trace[:] = base_trace
                result = await self._llm_turn(model_text + NO_TOOL_NOTE, turn_tools, active_speaker_id, trace, history, progress)
                if not _tool_events(result):
                    result = {
                        "speech": "I couldn't act on that, so nothing was booked or changed. Please try again.",
                        "trace": trace + [{"kind": "no_tool_call", "detail": "The model answered without calling a tool, twice."}],
                    }
            for event in _tool_events(result):
                if not event["result"].get("is_error"):
                    self._scene = apply_tool_result(self._scene, event["name"], event.get("arguments", {}), event["result"].get("output"))
            result = await self._finish_turn(result, text, active_speaker_id, session_id)
            self._track_ride_confirmation(session_id, result["trace"])
            self._remember_exchange(history_key, text, result["speech"])
            return result
        except ValueError as error:
            return {
                "speech": "The simulator needs an AI provider key before it can choose tools.",
                "trace": [{"kind": "configuration_error", "detail": str(error)}],
            }
        except Exception as error:
            # Show the real cause: the page used to hide it behind a generic sentence.
            import traceback

            traceback.print_exc()
            if _is_rate_limit(error):
                # Not a fault in the app. A daily limit needs a wait of hours; a per-minute limit clears in seconds.
                if _is_daily_limit(error):
                    speech = "The AI model has reached its usage limit for today, so I can't answer with it. Use the scripted demo commands, which need no AI key, or try again later."
                else:
                    wait = _retry_after(error)
                    hint = f" Try again in about {max(1, round(wait))} seconds." if wait else " Try again in a moment."
                    speech = "The AI model is handling too many requests right now." + hint
                return {
                    "speech": speech,
                    "trace": [{"kind": "provider_limit", "detail": str(error)[:300]}],
                }
            return {
                "speech": f"The simulator could not complete that request ({type(error).__name__}: {error}).",
                "trace": [{"kind": "agent_error", "detail": f"{type(error).__name__}: {error}"}],
            }
        finally:
            progress["busy"] = False
            progress["current"] = ""

    def _run_llm_loop(
        self,
        text: str,
        mcp_tools: list[dict[str, Any]],
        active_speaker_id: str | None,
        trace: list[dict[str, Any]],
        history: list[dict[str, str]],
        progress: dict[str, Any],
        settings: AISettings | None = None,
    ) -> dict[str, Any]:
        settings = settings or AISettings.from_environment()
        if settings.provider == "bedrock":
            return self._run_bedrock_loop(
                settings, text, mcp_tools, active_speaker_id, trace, history, progress
            )

        client, model = self._client_for(settings)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self._skill
                + (
                    f"\nThe simulator UI explicitly selected person_id={active_speaker_id}. "
                    "Call get_person_context before using saved preferences."
                    if active_speaker_id
                    else ""
                ),
            },
            *history,
            {"role": "user", "content": text},
        ]
        trace.append({"kind": "user", "text": text})

        started_at = time.time()
        for _ in range(MAX_TOOL_ROUNDS):
            if time.time() - started_at > RUN_TIME_LIMIT_S:
                break
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=as_openai_tools(mcp_tools),
                tool_choice="auto",
            )
            message = response.choices[0].message
            tool_calls = message.tool_calls or []
            if not tool_calls:
                return {"speech": message.content or "I have no response.", "trace": trace}

            messages.append(self._assistant_message(message))
            for call in tool_calls:
                arguments = json.loads(call.function.arguments or "{}")
                progress["current"] = describe_doing(call.function.name, arguments)
                result = asyncio.run(self._gateway.call_tool(call.function.name, arguments))
                narrated = describe_call(call.function.name, arguments, result)
                self._add_step(progress, narrated["text"], narrated["ok"])
                trace.append(
                    {
                        "kind": "tool",
                        "name": call.function.name,
                        "arguments": arguments,
                        "result": result,
                        "say": narrated["text"],
                        "ok": narrated["ok"],
                    }
                )
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": json_text(result)}
                )

        return {
            "speech": "I reached the tool-call limit before completing that request.",
            "trace": trace,
        }

    def _run_bedrock_loop(
        self,
        settings: AISettings,
        text: str,
        mcp_tools: list[dict[str, Any]],
        active_speaker_id: str | None,
        trace: list[dict[str, Any]],
        history: list[dict[str, str]],
        progress: dict[str, Any],
    ) -> dict[str, Any]:
        """Run Verity's existing MCP loop through Bedrock Converse tool use."""
        import boto3
        from botocore.config import Config

        session = boto3.Session(
            profile_name=settings.aws_profile,
            region_name=settings.aws_region,
        )
        client = session.client(
            "bedrock-runtime",
            config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
        )
        system_prompt = self._skill + (
            f"\nThe simulator UI explicitly selected person_id={active_speaker_id}. "
            "Call get_person_context before using saved preferences."
            if active_speaker_id
            else ""
        )
        messages: list[dict[str, Any]] = [
            *[
                {"role": item["role"], "content": [{"text": item["content"]}]}
                for item in history
            ],
            {"role": "user", "content": [{"text": text}]},
        ]
        tool_names = {tool["name"] for tool in mcp_tools}
        trace.append({"kind": "user", "text": text})

        started_at = time.time()
        for _ in range(MAX_TOOL_ROUNDS):
            if time.time() - started_at > RUN_TIME_LIMIT_S:
                break
            response = client.converse(
                modelId=settings.bedrock_model_id,
                system=[{"text": system_prompt}],
                messages=messages,
                inferenceConfig={"maxTokens": 1024, "temperature": 0.2},
                toolConfig={"tools": as_bedrock_tools(mcp_tools)},
            )
            assistant_message = response["output"]["message"]
            tool_uses = [
                block["toolUse"]
                for block in assistant_message.get("content", [])
                if "toolUse" in block
            ]
            if not tool_uses:
                speech = "".join(
                    block.get("text", "") for block in assistant_message.get("content", [])
                ).strip()
                return {"speech": speech or "I have no response.", "trace": trace}

            messages.append(assistant_message)
            tool_results: list[dict[str, Any]] = []
            for tool_use in tool_uses:
                name = tool_use["name"]
                arguments = tool_use.get("input", {})
                if name not in tool_names or not isinstance(arguments, dict):
                    result = {
                        "is_error": True,
                        "output": {"reason": "invalid_tool_request"},
                    }
                else:
                    progress["current"] = describe_doing(name, arguments)
                    result = asyncio.run(self._gateway.call_tool(name, arguments))
                narrated = describe_call(name, arguments, result)
                self._add_step(progress, narrated["text"], narrated["ok"])
                trace.append(
                    {"kind": "tool", "name": name, "arguments": arguments, "result": result, "say": narrated["text"], "ok": narrated["ok"]}
                )
                tool_result: dict[str, Any] = {
                    "toolUseId": tool_use["toolUseId"],
                    "content": [{"text": json_text(result)}],
                }
                if result["is_error"]:
                    tool_result["status"] = "error"
                tool_results.append({"toolResult": tool_result})
            messages.append({"role": "user", "content": tool_results})

        return {
            "speech": "I reached the tool-call limit before completing that request.",
            "trace": trace,
        }

    @staticmethod
    def _history_key(session_id: str | None, person_id: str | None) -> str:
        """Keep speakers separate: one person's follow-up never leaks to another."""
        return f"{session_id or 'local'}:{person_id or 'household'}"

    def _remember_exchange(self, history_key: str, user_text: str, speech: str) -> None:
        """Retain only a few natural-language turns; tool results are always re-read."""
        history = self._session_history.setdefault(history_key, [])
        history.extend(
            [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": speech},
            ]
        )
        self._session_history[history_key] = history[-8:]

    @staticmethod
    def _assistant_message(message: Any) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in message.tool_calls or []
            ],
        }

    async def _llm_turn(self, model_text: str, mcp_tools: list[dict[str, Any]], speaker: str | None,
                        trace: list[dict[str, Any]], history: list[dict[str, str]], progress: dict[str, Any]) -> dict[str, Any]:
        """One model call. If the primary provider is rate-limited and a fallback is configured, the same
        turn is answered by the fallback, and the answer says which model gave it."""
        self._last_fallback = None
        base = list(trace)
        settings = AISettings.from_environment()
        try:
            return await asyncio.to_thread(self._run_llm_loop, model_text, mcp_tools, speaker, trace, history, progress)
        except Exception as error:
            if not _is_rate_limit(error):
                raise
            trace[:] = base
            wait = _retry_after(error)
            if not _is_daily_limit(error) and wait is not None and wait <= 10:
                # A per-minute limit clears in seconds: wait as the provider asks, then try once more.
                await asyncio.sleep(wait + 0.5)
                try:
                    return await asyncio.to_thread(self._run_llm_loop, model_text, mcp_tools, speaker, trace, history, progress)
                except Exception as retry_error:
                    if not _is_rate_limit(retry_error):
                        raise
                    trace[:] = base
            if not settings.fallback_provider:
                raise
            fallback = replace(settings, provider=settings.fallback_provider)
            name = fallback.ollama_model if fallback.provider == "ollama" else fallback.provider
            self._last_fallback = f"{fallback.provider}:{name}"
            return await asyncio.to_thread(self._run_llm_loop, model_text, mcp_tools, speaker, trace, history, progress, fallback)

    @staticmethod
    def _client_for(settings: AISettings) -> tuple[Any, str]:
        if settings.provider == "ollama":
            # Ollama's OpenAI-compatible endpoint; the key is a placeholder it does not check.
            return OpenAI(base_url=settings.ollama_base_url, api_key="ollama"), settings.ollama_model
        if settings.provider == "groq":
            if not settings.groq_api_key:
                raise ValueError("GROQ_API_KEY is required when AI_PROVIDER=groq.")
            return Groq(api_key=settings.groq_api_key), settings.groq_model
        if settings.provider == "openai":
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required when AI_PROVIDER=openai.")
            return OpenAI(api_key=settings.openai_api_key), settings.openai_model
        raise ValueError("AI_PROVIDER must be 'openai', 'groq', or 'bedrock'.")
