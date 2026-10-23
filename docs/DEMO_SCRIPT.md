# Demo script — Verity (target under 2:50)

Written for: judges watching a public video with no prior context.
Say "simulated" whenever a provider, device, or the Alexa+ surface appears.
No music. Do not show provider logos or third-party brand names on screen.

## Setup before recording

- MCP server running: `python server/http_server.py` (port 8000).
- Simulator running: `python -m uvicorn simulator.app:app --host 127.0.0.1 --port 8770`.
- Browser at `http://localhost:8770/?debug=1`, with the **Manual** mode and the
  "Scripted demo · no AI key" label visible. Recording on the scripted path means
  no model quota is used, and the label says so on screen.
- Before recording: reload the page, set **Papa**'s ride preference to **fastest**
  or **cheapest** only by asking on screen, and make sure Amma is away on her ride
  (the house timer shows "back in" time).
- Start each take with a fresh page, so an old popup does not appear in the take.

## Beats

| Time | On screen | Narration | Shows |
| --- | --- | --- | --- |
| 0:00–0:12 | Title card, then the house | "This is Verity, a household agent. The Alexa+ experience here is simulated; it talks to a real MCP server." | Disclosure, floor plan |
| 0:12–0:35 | Type: "Book Papa a ride to the office." Papa's question appears in its own popup: cheapest or fastest. Answer it. | "It asks once and saves the answer for Papa. It compares simulated rides with price, time and distance." | Question popup, saved preference |
| 0:35–0:55 | The approval card: the chosen ride, why it was chosen, and the distance. Press **Accept**. | "Nothing is booked until I accept. Accept books it, and the house shows the driver's countdown." | Approval card, booking countdown |
| 0:55–1:10 | The house: Amma's chip shows "back in" with a countdown. | "Amma is on her ride. The server counts her return, and she comes home when the time is up." | Return countdown |
| 1:10–1:25 | Type: "Papa wants to watch TV." Son's card asks to join: **Join** or **Not now**. Press **Join**. | "Everyone at home is asked separately. Joining moves them to the TV room." | Invitation card, room change |
| 1:25–1:40 | Type: "order milk and bread." Accept the order card. | "Food and groceries follow the same rule: propose, show the price, then order only after Accept." | Order card, order reply |
| 1:40–1:55 | Type: "Help Amma with a massage" (Amma is still away). | "Housebot cannot help someone who is out. Verity says when she is back and does nothing else." | Refusal with return time |
| 1:55–2:15 | Type: "Book Amma a ride to the market," then press **Decline** on that card. | "A decline names the ride it declined and leaves the others alone." | Decline reply |
| 2:15–2:35 | Point at "What Verity did": one plain sentence per step. Open Technical details once. | "Every step is listed in plain words, and the raw result is one click away. The model only picks tools; the rules are in code." | Step list, raw result |
| 2:35–2:48 | Closing card. | "Verity is a real MCP server with a simulated Alexa+ host. The code is open source under MIT." | Repo URL, license |

## Failure cases (must be shown)

- **1:40–1:55:** Housebot is refused for an absent person. Verity must not start a
  massage, must not guess, and must give the return time it was given.
- **1:55–2:15:** a declined ride is not booked, and the reply names that ride. It must
  not say "nothing was booked" when another ride was booked.

## Recording notes

- Do not show IDs, codes or account numbers on screen.
- If a step fails while recording, re-record that step. Do not edit a failure into a success.
- The house clock and the ride countdowns run in real time; cut the waiting in the edit, and do not fake timestamps.
- The Bedrock path is optional. If it is used, say "a model answers these turns through AWS Bedrock" and show the saved trace in `docs/aws-bedrock-live-trace.md`. Do not claim AWS for turns that ran on the scripted path.

## Narration rules

- Say "simulated" when a provider, device, or the Alexa+ surface appears.
- Do not say "live", "real booking", or "connected to Alexa".
- Say "Scripted demo" when the no-key path runs. Do not call it the AI model.
