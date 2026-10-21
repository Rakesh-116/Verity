# Ride booking UI — requirements (draft for review)

Status: **requirements only, nothing built yet.** Order of work:
1. Local end-to-end with a real LLM works (the demo script runs three times).
2. This UI (must-haves first).
3. Freeze and record.
4. AWS connection (after the local demo is stable; see the last section).

## 1. Problem

A judge watching the video cannot see the agent booking anything. The simulator
shows the house, a raw JSON tool trace, and a chat log. A ride hedge across
platforms happens inside tool results that nobody can read at a glance.

The video must show, in real time: which platforms were asked, what each one
answered, which ride was committed and why, what was cancelled and what it cost,
and what happened when a driver cancelled.

## 2. Data that exists today

`get_ride_hedge_status(hedge_id)` already returns everything the panel needs:

| Field | Use on screen |
| --- | --- |
| `status` (`searching`, `committed`, `failed`) | Hedge header badge |
| `round` | "Round 2 of 2" |
| `rides[]` (`platform`, `state`, `driver`, `eta_minutes`, `fare_inr`, `cancellation_fee_inr`, `by`) | One card per platform |
| `committed` | Which card is committed |
| `fees_inr` | Fee total |
| `events[]` | Timeline markers, event log |
| `explanation[]` | Plain-English reasons, shown as the decision log |
| `failure_reason` | Failure banner |
| `availability` / `source` | "SIMULATED" badge |

**Missing:** the UI has no way to find a hedge. `/api/state` only returns home,
robot, and energy data. Per the project's rule that dashboards read through
MCP, add one read-only tool, `list_ride_hedges(person_id=None)`, returning
hedge IDs, statuses, and the latest view. The simulator then polls it.

## 3. Requirements

### Must have (for the video)

**M1. Ride panel card per hedge.** Appears when a hedge starts. Shows the
origin, destination, status badge, round, and the fee total.

**M2. One card per platform in the hedge.** The hedge has two platforms today
(QuickRide, CityCab). The layout must handle three without rework. Each card
shows:
- platform name and a `SIMULATED` badge
- state: searching / accepted / committed / cancelled
- when cancelled: who cancelled (driver or us) and the fee charged
- driver name, ETA, fare, once accepted
- the request round and attempt number

**M3. Real-time updates.** The panel polls `list_ride_hedges` about every
second while any hedge is not `failed`. A state change on the server must show
within about 1.5 seconds. Polling is enough. No WebSocket or SSE needed.

**M4. Decision log.** A visible list of `explanation[]`, newest at the bottom,
so a judge can read why the agent committed, cancelled, or re-requested.

**M5. Honest labels.**
- Never show "booked" for a ride that is not committed.
- Say "committed (simulated)", not "booked by the platform."
- Every platform card and the panel header carry `SIMULATED`.

**M6. Failure states are visible.** Both failure reasons need a clear banner:
`no_driver_accepted` and `all_drivers_cancelled`. The banner names the reason
in plain words and states that nothing else was booked.

**M7. Readable trace.** Replace the raw JSON dump with one line per tool call:
tool name, the key argument, and a one-line result such as
"`start_ride_hedge` → hedge started, 2 platforms" or "`book_ride` → refused:
proposal already executed." Raw JSON stays available behind a "Details"
toggle. This is the single biggest readability win for judges.

**M8. Deterministic demo path.** The default scenario in
`server/state/ride_scenarios.json` produces the same sequence every run:
QuickRide accepts at 3 s, CityCab at 8 s and is committed, CityCab's driver
cancels at 20 s, and the hedge re-requests and commits again at 28 s.

### Should have

**S1. Timeline strip per hedge.** A horizontal bar from 0 to about 35 s. Each
platform gets a row with markers for request, accept, commit, cancel. This
makes the race visible at a glance.

**S2. Fee callout.** When a loser is cancelled after accept, show
"Cancelled after accept: 15 INR fee" on that card, in the total.

**S3. Chat-to-panel link.** The hedge appears in the panel the moment the
agent calls `start_ride_hedge`, without a manual refresh.

### Could have (only if time remains)

**C1. Character status tie-in.** The existing pixel characters (Son, Amma,
Papa, Sister) get a "waiting for ride" state while a hedge is searching, and an
"in ride" state once committed. They already have idle/busy/alert/away states.
Map the hedge states onto them. This is the agent-as-character idea. It is
decorative, so it is cut first.

**C2. Show the ride panel in Demo mode** as well as Manual mode.

## 4. Non-goals

- No real rides, payments, maps, or live driver location.
- No login or account screens. Judges must reach the UI with no credentials.
- No mobile layout. Target the 1920×1080 recording.
- No change to hedge rules or approvals. The UI is read-only. Only the
  existing chat turns and approval tools change state.

## 5. Acceptance criteria

1. Starting the demo hedge shows a panel with two platform cards within 1 s.
2. The QuickRide card goes to "accepted" before the CityCab card, and no card
   is marked committed until both are accepted or the window ends.
3. The commit appears in the decision log with the lowest-ETA reason.
4. Cancellation of the loser shows the 15 INR fee on its card and in the total.
5. The CityCab driver cancel shows within 1.5 s and the round 2 cards appear.
6. Both failure reasons render as banners in a test run with those scenarios.
7. The trace shows one readable line per tool call, and "Details" expands the JSON.
8. Every card and the header show `SIMULATED`. No text says "booked" for an
   uncommitted ride.
9. The panel works with the MCP server running and no AWS credentials.
10. A fresh browser load mid-hedge shows the current state, not a blank panel.

## 6. Visual polish already spotted (from the current screenshot)

- "LIVING ROOM" and "KITCHEN" room labels are partly covered by plants and
  the energy badge.
- The "ENERGY CHECK: 3 SUGGESTIONS" badge overlaps the kitchen room. Move it
  into the event panel.
- The conversation panel is empty until the first turn. Add a short
  "Try: Turn off the lights in empty rooms" hint.

## 7. Connecting to AWS later (after local is stable)

The UI reads only through MCP, so nothing in the panel changes when the
backend moves. What AWS would actually back:

| Piece | Local | AWS option | Shows as |
| --- | --- | --- | --- |
| Hedge records | `ride_hedges.json` | DynamoDB table | `source: dynamodb`, `availability: live` |
| Narration/explanations | fixed text | Bedrock Converse | only if actually called |

The rides themselves stay simulated. AWS would store the hedge state and,
optionally, generate the explanation text. It would not make the rides real.
The panel must show the source of each value, as the project's provenance rule
requires. Do not claim AWS usage unless a live call is captured.

## 8. Decisions needed from you

1. **Platform count:** keep two (QuickRide, CityCab) for the video, or add a
   third platform so the three-card layout is shown?
2. **Characters:** include C1 (character status tie-in) in this round, or
   leave it for after the submission?
3. **Trace default:** readable lines by default with JSON behind "Details"
   (recommended), or the current raw JSON?

## 9. Time risk

Must-haves M1–M8 plus the `list_ride_hedges` tool are a day of work,
alongside the LLM runs and the recording. Build M1–M4 and M7 first, which
covers the core judge story. S1 and C1 are cuts if time runs short.
