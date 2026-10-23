# Pending tasks — status

Updated 2026-10-23, before the 12:00 PT submission deadline.

## Done in this round

| Task | Where | Evidence |
| --- | --- | --- |
| Several rides or orders waiting at once. Each is its own card with its own Accept and Decline. | `simulator/agent_host.py` (`_open_approvals`, `_track_ride_confirmation`, `decide`), `simulator/app.py` (`POST /api/approval`), `simulator/static/app.js` (`renderApprovals`) | `tests/phase13_multi_approval_test.py` |
| Accept or decline acts only on its own proposal, not on the text "yes" | `decide()`; a plain "yes" is used only when exactly one approval is waiting | phase13 test |
| Decline for rides and orders cancels the proposal. Nothing is booked or ordered. | `decline_ride_booking`, `decline_order` (MCP tools), `decline_proposal` in `approval_store.py` | phase13 test |
| Food and grocery ordering: "order milk and bread" compares prices, proposes the cheapest provider, and waits for approval | `simulator/scripted_demo.py` (`ORDER`), `decide()` for orders | phase13 test |
| Order chip on the page | `simulator/static/index.html` | visual |
| Booking question creates the approval | `_finish_turn` in `agent_host.py` | commit `4e0f64a` |
| People and preferences in SQLite | `server/state/people_db.py`, `server/state/household.db` (ignored by git) | commit `647b745`, all tests |
| Ride choice weighs price against time; distance shown | `server/services/ride_value.py` (`choose_ride`) | commit `0a8949e` |

## Blocked on someone else

| Task | Blocker | What is needed |
| --- | --- | --- |
| Test AWS Bedrock | This machine has no AWS credentials. The `verity-dev` profile in `.env` does not exist here. | You run `aws configure sso --profile verity-dev` in your own terminal, then tell me. I then run the Converse test. |
| Live model answers | Groq daily token limit on this account | Wait for the reset, use a key from a different account, or set up Ollama (`AI_FALLBACK_PROVIDER=ollama`). |
| Video | Recording is yours | Follow `docs/DEMO_SCRIPT.md`; under 3 minutes. |
| Devpost form and public repo | Your account actions | Submit the draft in `docs/DEVPOST_DRAFT.md`; make the repo public with its MIT licence. |

## Needs a restart to take effect

- The MCP server on port 8000 must restart to register the new decline tools.
- The simulator on port 8770 must restart for the server-side changes. Reload the page for the front-end changes.

## Known limits

- Scripted demo: a new ride or order in the scripted path is tracked as an approval, so several can wait at once. The scripted "yes" still refers to the single pending ride when only one is waiting.
- Orders have no booking popup; the reply line shows the result.
- Distances and provider prices are simulated.
