# Demo script — Verity (target under 2:50)

Written for: judges watching a public video with no prior context.
Say "simulated" whenever a provider, device, or the Alexa+ surface appears.
No music. Do not show provider logos or third-party brand names on screen.

Setup before recording: MCP server running (`-m server.http_server`), simulator
running (`-m simulator.app`), browser at `http://127.0.0.1:8770`, active speaker
set to **Son**, the MCP trace panel visible.

## Beats

| Time | On screen | Narration | Shows |
| --- | --- | --- | --- |
| 0:00–0:12 | Title card, then the simulator floor plan | "This is Verity, a context agent for a household. The Alexa+ experience here is simulated; it calls a real MCP server." | Disclosure, floor plan |
| 0:12–0:35 | Type: "Turn off the lights in empty rooms." | "Verity checks live occupancy first, then proposes switching off lights and fans in rooms with nobody in them." | `get_home_state`, `get_energy_saving_opportunities`, `create_energy_saving_proposal` |
| 0:35–0:50 | Type: "Yes, do it." | "The proposal changes nothing until a separate approval. Then Verity applies it and reports each confirmed state." | `list_pending_actions`, approve, execute |
| 0:50–1:12 | Type: "Get me a ride to the office." | "It compares simulated ride options and makes a booking proposal with the destination you asked for. It books nothing yet." | `compare_ride_options`, `create_ride_booking_proposal` |
| 1:12–1:24 | Type: "Yes, book it." Then: "Book that same ride again." | "The first approval books once. The repeat is refused with the reason. Verity does not pick a different ride." | `approve_ride_booking`, `book_ride`, then a `proposal_executed` refusal |
| 1:24–2:10 | Click **Simulate Mon 10:15 at PG**. Agent suggests a hedge with evidence. Type: "Yes." Agent proposes the hedge and asks to approve. Type: "Yes, approve it." Agent starts the hedge. Show the status updates and the CityCab driver cancel, then the recovery. | "It is 10:15 on a Monday. Son usually takes a ride to the office around now: seven of the last eight Mondays. It asks before doing anything. The hedge requests two platforms and commits to the faster driver only after both accept. When that driver cancels, it re-requests and explains the fee it paid." | `get_routines`, `create_ride_hedge_proposal`, `approve_ride_hedge`, `start_ride_hedge`, `get_ride_hedge_status` ×N, explanation |
| 2:10–2:30 | Open the trace panel and point at one `result` block. | "Every step is in the trace. The rules live in the agent's skill file, and the model only picks tools." | Trace, `skills/verity/SKILL.md` |
| 2:30–2:45 | Closing card. | "Verity is a real MCP server with a simulated Alexa+ host. The code is open source under MIT." | Repo URL, license |

## Failure cases (must be shown)

- **1:12–1:24:** the repeat booking is refused. Verity must not book a different ride, approve anything, or change its story.
- **2:00–2:10:** the committed driver cancels. Verity must say so, re-request, and report the cancellation fee. It must not claim the first ride is still on.

## Recording notes

- The hedge timeline runs in real time: accepts at 3 s and 8 s, the driver cancel at 20 s, and the recovery accept at 28 s. Cut the waiting between status checks in the edit. Do not speed up the trace or fake the timestamps.
- If a step fails in recording, re-record that step. Do not edit a failure into a success.
- The simulated clock is real time. Scenario values are in `server/state/ride_scenarios.json`.

## Narration rules

- Say "simulated" when a provider, device, or the Alexa+ surface appears.
- Do not say "live", "real booking", or "connected to Alexa".
- Do not name AWS services in the video; the default demo does not call them.
