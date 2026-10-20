"""LLM host that chooses MCP tools; it contains no scenario-specific routing."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIRECTORY / "server"))

from groq import Groq
from openai import OpenAI
from services.ai.settings import AISettings

from simulator.mcp_gateway import MCPGateway, as_bedrock_tools, as_openai_tools, json_text


SKILL_PATH = PROJECT_DIRECTORY / "skills" / "verity" / "SKILL.md"


class AgentHost:
    """Runs a bounded tool-calling loop for one simulated Alexa+ turn."""

    def __init__(self, mcp_url: str) -> None:
        self._gateway = MCPGateway(mcp_url)
        self._skill = SKILL_PATH.read_text(encoding="utf-8")
        # This is deliberately short-lived simulator conversation context, not
        # persistent user memory. Durable preferences remain MCP-owned JSON state.
        self._session_history: dict[str, list[dict[str, str]]] = {}

    async def dashboard_state(self) -> dict[str, Any]:
        """Read render-only household state through the same MCP client."""
        home = await self._gateway.call_tool("get_home_state", {})
        speaker = await self._gateway.call_tool("get_active_speaker", {})
        robot = await self._gateway.call_tool("get_robot_status", {})
        opportunities = await self._gateway.call_tool("get_energy_saving_opportunities", {})
        return {
            "home": home["output"],
            "active_speaker": speaker["output"],
            "robot": robot["output"],
            "proactive": opportunities["output"],
        }

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

        history_key = self._history_key(session_id, active_speaker_id)
        history = list(self._session_history.get(history_key, []))
        try:
            result = await asyncio.to_thread(
                self._run_llm_loop, text, mcp_tools, active_speaker_id, trace, history
            )
            self._remember_exchange(history_key, text, result["speech"])
            return result
        except ValueError as error:
            return {
                "speech": "The simulator needs an AI provider key before it can choose tools.",
                "trace": [{"kind": "configuration_error", "detail": str(error)}],
            }
        except Exception as error:
            return {
                "speech": "The simulator could not complete that request.",
                "trace": [{"kind": "agent_error", "detail": str(error)}],
            }

    def _run_llm_loop(
        self,
        text: str,
        mcp_tools: list[dict[str, Any]],
        active_speaker_id: str | None,
        trace: list[dict[str, Any]],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        settings = AISettings.from_environment()
        if settings.provider == "bedrock":
            return self._run_bedrock_loop(
                settings, text, mcp_tools, active_speaker_id, trace, history
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

        for _ in range(6):
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
                result = asyncio.run(self._gateway.call_tool(call.function.name, arguments))
                trace.append(
                    {
                        "kind": "tool",
                        "name": call.function.name,
                        "arguments": arguments,
                        "result": result,
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

        for _ in range(6):
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
                    result = asyncio.run(self._gateway.call_tool(name, arguments))
                trace.append(
                    {"kind": "tool", "name": name, "arguments": arguments, "result": result}
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

    @staticmethod
    def _client_for(settings: AISettings) -> tuple[Any, str]:
        if settings.provider == "groq":
            if not settings.groq_api_key:
                raise ValueError("GROQ_API_KEY is required when AI_PROVIDER=groq.")
            return Groq(api_key=settings.groq_api_key), settings.groq_model
        if settings.provider == "openai":
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required when AI_PROVIDER=openai.")
            return OpenAI(api_key=settings.openai_api_key), settings.openai_model
        raise ValueError("AI_PROVIDER must be 'openai', 'groq', or 'bedrock'.")
