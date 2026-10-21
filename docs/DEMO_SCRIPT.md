# Demo script — Verity (target under 2:45)

Written for: judges watching a public video with no prior context.
Say "simulated" whenever a provider, device, or the Alexa+ surface appears.
No music. Do not show provider logos or third-party brand names on screen.

Setup before recording: MCP server running (`-m server.http_server`), simulator
running (`-m simulator.app`), browser at `http://127.0.0.1:8770`, active speaker
set to **Papa**, the MCP trace panel visible.

## Beats

| Time | On screen | Narration | Shows |
| --- | --- | --- | --- |
| 0:00–0:15 | Title card, then the simulator floor plan | "This is Verity, a context agent for a household. The Alexa+ experience here is simulated; it calls a real MCP server." | Disclosure, floor plan |
| 0:15–0:35 | Type: "Turn off the lights in empty rooms." | "Verity checks live occupancy first, then finds lights still on in rooms with nobody in them." | `get_home_state`, `get_energy_saving_opportunities` in the trace |
| 0:35–1:00 | Agent proposes switching them off; it does not do it. Say "Yes, do it." | "It made a proposal and needs an explicit confirmation before it changes any device." | `create_energy_saving_proposal`, then `list_pending_actions`, approval, execute, with confirmed states |
| 1:00–1:25 | Type: "Get me a ride to the office." | "It compares simulated ride options with the saved destination. It makes a proposal and books nothing yet." | `get_person_context`, `compare_ride_options`, `create_ride_booking_proposal` |
| 1:25–1:40 | Type: "Yes, book it." | "The approval is a separate step. Only after it does Verity book, and it reports the confirmed booking ID." | `list_pending_actions`, `approve_ride_booking`, `book_ride` |
| 1:40–2:05 | Type: "Book that same ride again." | "Verity refuses to book the same approved proposal twice. It reports the reason. It does not pick a different ride." | `book_ride` returns a `proposal_executed`-style refusal, no new booking |
| 2:05–2:25 | Open the trace panel, point at one `result` block. | "Every step is in the trace. The answer comes from tool results, and the rules live in the agent's skill file." | Trace, SKILL.md rules |
| 2:25–2:40 | Closing card. | "Verity is a real MCP server with a simulated Alexa+ host. The code is open source under MIT." | Repo URL, license |

## Failure case (must be shown)

The beat at 1:40 is the failure case. Verity must report the refusal truthfully.
It must not book a different ride, approve anything, or change its story.

## Narration rules

- Say "simulated" when a provider, device, or the Alexa+ surface appears.
- Do not say "live", "real booking", or "connected to Alexa".
- Do not name AWS services in the video; the default demo does not call them.
- If a step fails in recording, re-record the step. Do not edit a failure into a success.
