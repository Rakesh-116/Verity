# Verity architecture

## Product boundary

Verity is an MCP capability server. It provides independent home, work,
mobility, and personal-context primitives. It does not contain an
`im_leaving()` routine or any server-side decision sequence. The agent decides
which tools to call using the tool descriptions and live results.

```text
User voice → Alexa+ → Alexa+ reasoning/Agent Skill → MCP (HTTP) → Verity
                                                              ├─ home tools
                                                              ├─ work tools
                                                              ├─ mobility tools
                                                              └─ context tools
```

Alexa+ owns the real Alexa+ voice interaction. Verity never needs to reproduce
or impersonate Alexa's voice for production integration.

## Local demo path

For a browser demo before Alexa+ integration, use a chained and inspectable
voice pipeline:

```text
Browser microphone → speech-to-text → local agent/simulator → Verity MCP
                  → final text response → text-to-speech → browser speaker
```

The simulator's assistant voice must be a clearly disclosed synthetic voice
with its own identity, such as “Verity,” not an imitation of Alexa. This
chained design makes the transcript, exact tool calls, tool results, and final
spoken confirmation visible in the hackathon recording.

The simulator implementation is intentionally separated into four parts:

```text
simulator/static/       browser UI, Web Speech API, screen trace
simulator/app.py        /api/chat web host
simulator/agent_host.py LLM tool-selection loop using skills/verity/SKILL.md
simulator/mcp_gateway.py Streamable HTTP MCP discovery and tool calls
```

The LLM receives tool schemas discovered from the MCP server rather than a
handwritten list. It may select only the tools currently exposed by Verity.

## Why the local agent is optional

The Alexa+ integration is the product proof that Alexa+ chooses tools. A local
simulator is only a fallback and presentation/testing aid. It must use the same
MCP transport and tool schemas; it must not gain hidden scenario tools or
server-side orchestration.

## Build order

1. Finish Inspector verification for each Phase 2 tool.
2. Add context tools and action logging (Phase 3).
3. Add mocked mobility tools (Phase 4).
4. Build the virtual home and read-only HTTP endpoint (Phase 5).
5. Add GitHub tools (Phase 6), then Streamable HTTP (Phase 7).
6. Add the Alexa+ Agent Skill and simulator integration (Phase 8).
7. Add microphone capture and a distinct synthetic Verity voice only if Alexa+
   itself is not the demo voice surface.

## Trust invariant

Every state-changing tool returns what it confirmed changed or a specific
failure reason. A local voice simulator must speak that result faithfully and
never turn an unconfirmed action into a success claim.
