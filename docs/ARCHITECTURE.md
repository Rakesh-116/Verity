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

## Principal review: state, time, and requests (2026-10-23)

**Who owns what.** The MCP server is the only owner of household state: presence and return times, proposals
and their approval status, bookings, and the people and preferences in `server/state/household.db`. The
simulator host holds only what is about the screen: the scene (who is where on screen), the list of approvals
waiting on screen, and which riders it has already sent out. Nothing the host shows as a fact is kept
separately from the server, so a timer, a presence, or a booking cannot disagree with the house.

**Time.** Two clocks, used for different things. The house schedule (arrivals and departures by clock time)
uses the simulated clock, `sim_clock.json`. A rider's return from a ride uses a real-time deadline that the
server stores as `return_epoch` and counts down; the host never resets it. An "away" member needs a return
time: a clock time, a number of seconds, or an explicit "unknown" when they said they are going out without
saying when they will be back.

**Requests.** Each request has a `request_id`. Its progress, question, approvals and booking belong to that
request, and the page opens one popup per request. Approvals are keyed by proposal, so two requests can wait
at once. Accept and Decline send one proposal id to `POST /api/approval`; a typed "yes" is used only when
exactly one approval is waiting. A proposal that is the same ride, person and place as one already waiting
is one proposal, so a destination said two ways ("market", "the market") cannot create two.

**Refusals before the model.** A request for someone who is out (an away member asked for by name) is
answered directly with the time they are back. The model is not asked to guess, and nothing is changed.

**Tests.** Tests run against `tests/seed_state`, a committed copy of the seed JSON, so they never depend on the
live house. Phase 14 covers the presence rules and duplicate proposals; phase 13 covers approvals and invitations.

**Known gaps.** Ride declines cancel the proposal but do not tell the other riders; invitations do not time
out; the scripted path tracks approvals but does not yet run several requests at once with its own popups;
the model still has a round limit, and when it is hit the reply lists what was already done.
