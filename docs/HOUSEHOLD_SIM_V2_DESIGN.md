# Household simulation v2 — design

Status: **design, saved for reference.** Branch `household-v2`. The
`submission-candidate` tag is not touched. See section 15 for what is built now.

Written for: the coding agent and the owner. This is a spec, not a schedule.

## 0. Why the current demo can't do this

1. **No task concept.** The house only knows who is in which room right now.
   "Amma is waiting for a ride" is not state, so nothing can animate it.
2. **No door, no outside, no presence.** The map has four rooms and an
   invisible `away`. Amma has nowhere to stand while she waits.
3. **The UI reacts after the fact.** It polls and refreshes once the AI
   finishes, so the walk, the wait and the arrival are never seen as they happen.
4. **The agent is told not to move people.** `move_person` is only for explicit
   requests, so a ride command never walks Amma anywhere.
5. **The model can skip tools.** The last command made zero tool calls because
   nothing forced name → ID resolution.
6. **No clock.** Time of day changes nothing.

## 1. Principles

1. **The house is the product.** Chat and tool traces are secondary and live in a
   debug drawer (`?debug=1`).
2. **Python owns the world; the LLM picks tools.** Movement, presence,
   permissions and approvals are deterministic code.
3. **Every action is a task with phases.** One phase stream drives the walk, the
   device changes and the popups, so they cannot drift apart.
4. **Nothing is faked.** If the model skips tools or a task fails, the UI says
   so. Everything is labelled "Simulated Alexa+".

## 2. Architecture

```
Browser (renderer only) ←SSE─ Simulator host ──MCP session──► MCP server (state authority)
  click-to-speak, modals       context + LLM loop              tools + choreographer + clock
  plays scene events           routine scheduler               world store (single writer)
```

- **One state authority:** the MCP server owns the world store. Several processes
  writing JSON files can corrupt state, so tasks, events and members move to a
  single-writer store (SQLite in WAL mode). JSON stays for seed data.
- **Choreographer:** a tick loop inside the server (about 4 times a second). It
  advances tasks from the simulated clock and timers and appends events.
- **Simulator host:** streams events to the browser over one SSE connection and
  keeps one long-lived MCP session. That also removes the polling and the log flood.
- **The clock belongs to the host and server.** The agent can read the time, but
  it never advances it.

## 3. World model

```json
{
  "clock": {"sim_time": "10:15", "speed": 30, "paused": false, "daypart": "morning"},
  "members": {
    "amma": {"role": "mother", "presence": "home", "location": "kitchen", "facing": "s",
             "task": null, "return_at": null,
             "prefs": {"tv_lights": "dim", "ride": "balanced", "snack": "fruit"}},
    "papa": {"presence": "home", "location": "tv_room", "prefs": {"tv_lights": "off"}},
    "son":  {"presence": "away", "location": "outside", "task": "t12", "return_at": "18:30"},
    "housebot": {"kind": "robot", "location": "living_room", "battery": 86, "task": null}
  },
  "devices": {"tv_room.tv": {"state": "off"}, "tv_room.light.01": {"state": "on"},
              "echo.living_room": {"state": "idle"}}
}
```

**Map graph.** Each node has anchor points. Pathing is breadth-first over the graph.

| Node | Anchors |
| --- | --- |
| living_room | echo, sofa, robot_dock |
| kitchen | table, counter |
| bedroom | bed, wardrobe |
| tv_room | tv_seat_1, tv_seat_2 |
| hall | junction between rooms |
| front_door | door_slot_1..3 (several people can wait) |
| porch → street | vehicle_spot; `outside` for away members |

## 4. Task engine

```python
@dataclass
class Phase:
    name: str
    actor: str | None = None        # defaults to the task owner
    goto: str | None = None         # anchor, e.g. "front_door.slot_1"
    anim: str = "idle"
    device: dict | None = None      # {"tv_room.tv": "on"}
    overlay: str | None = None      # modal to open
    presence: str | None = None     # "away" / "home"
    until: str = "now"              # "ride.committed", "clock>=return_at", "duration:45m", "user.confirm"

Task(id, type, owner, target, params, phases, phase_idx, status)
# status: proposed → active → completed | cancelled | failed
```

- Every phase transition writes one event. Restarting the server resumes active
  tasks from the store.
- A member has at most one **physical** task at a time. Non-physical tasks, such as an
  order placed while waiting at the door, can overlap. The robot takes one task at a
  time and refuses with `robot_busy`.
- `cancel_task` unwinds the phases. A character walking to the door walks back.
  Any fee is recorded.
- A driver cancel moves a ride task from `waiting` back to `searching`. Exhausted
  retries move it to `failed` with a specific reason and a visible bubble. There is no
  silent substitution.

## 5. Task catalogue

| Task | Phases | Approval |
| --- | --- | --- |
| Ride / commute | proposed (walk to door starts now) → confirm → searching (ride modal) → waiting at door, facing the camera → vehicle arrives → exit → **away** until `return_at` → return, walk to home spot | Yes (spending) |
| Watch TV or film | walk to `tv_seat` → TV on with a glowing animated screen, lights per prefs → watching for the duration → TV off, lights restored | No |
| Robot massage | housebot walks beside the target → `assisting` animation for the duration, labelled "simulated, non-medical" → housebot returns to its dock | No |
| Order food or groceries | confirm → placed → preparing → out for delivery (marker on the street) → delivered at the door; someone at home receives it and it moves to the kitchen | Yes (spending) |
| Goodnight | lights off, devices idle, everyone to the bedroom | No |

Who walks to the door is the person the ride is **for**. If Papa books it for Amma,
Amma goes to the door and a bubble says "Papa booked a ride for Amma".

## 6. Presence and authority

Enforced in code at the tool boundary, not in the prompt:

```python
def authorize(speaker, intent, target=None):
    w = world.load()
    if w.members[speaker].presence != "home":
        return deny("speaker_away", f"{speaker} is away until {w.members[speaker].return_at}")
    if intent.physical and target and w.members[target].presence != "home":
        return deny("target_away", f"{target} isn't home")
    if intent.physical and intent.actor_busy(target):
        return deny("target_busy")
    return allow()
```

| Intent | Speaker home | Target home | Result |
| --- | --- | --- | --- |
| Ride, TV, massage | required | required | allowed |
| Order (remote) | required | not required | allowed |
| Question about an away person | required | not required | allowed |
| Anything from an away member | no | n/a | denied: `speaker_away` |

- **Who's home modal:** avatar chips in the top bar (green = home, grey = away). The
  modal lists each person's status, location, "back at" time (editable in 15-minute
  steps) and a "back now" button.
- **Speaking as someone:** click a character to speak as them. Away members cannot be
  selected.
- **Return times:** the ride tool takes `expected_return`, defaulting by destination
  (market about 90 min, office about 9 h, college about 8 h). The confirmation states
  it. At `return_at` the character re-enters through the door.

## 7. Clock, dayparts and routines

- **Dayparts:** morning 5–11, afternoon 11–16, evening 16–21, night 21–5. They change
  the window light and house tint, and they choose the routine table.
- **Routine table** (seeded; the same history feeds `get_routines`):

```json
{
 "morning":   {"amma": [{"say": "Book me a ride to the market", "weight": 0.7, "away_min": 90}],
               "son":  [{"say": "Send me to the office", "weight": 0.9, "away_min": 540}]},
 "afternoon": {"amma+papa": [{"say": "Play a movie", "then": "housebot.massage", "min": 45}]},
 "evening":   {"amma": [{"say": "Order snacks", "weight": 0.6}]},
 "night":     {"*": [{"say": "Goodnight", "scene": "lights_off"}]}
}
```

- **Scheduler:** at jittered simulated times it picks a routine for a member who is
  home and idle, then sends the line through the **real agent path** as that speaker,
  with `source: "routine"`. Between routines, characters idle and wander locally with
  no agent calls.
- **Standing approvals** let routines run unattended without breaking confirmation:
  `{member: "amma", intent: "ride", max_amount: 150, destinations: ["market"]}`.
  Anything outside the policy shows a confirmation bubble over the character and
  the scene waits.
- The agent can explain a proposal with its evidence ("6 of the last 7 mornings").

## 8. Preferences and decisions

- **Member preferences** in `prefs`: TV lighting, ride preference (cheapest, fastest,
  nearest, balanced), snacks. A `get_member_prefs` tool returns them. Papa's lights go
  off for TV; Amma's go dim.
- **Deadlines** are convert-to-cost, with a learned value of time:
  `cost = fare + vot × eta_min + late_penalty × late_minutes`. `vot` is the median of
  past trade-offs from the member's choice history, and it defaults to 2 when there is
  no history. Python ranks the options and returns the breakdown. The agent explains it.
- **Hedging:** the two-platform race, the 15-second decision window, fallback on driver
  cancel and fee recording, as already built on the approval store.

## 9. Accounts and integrations

- `accounts[member] = [{platform, account_ref, linked, wallet_limit}]`. Tools only
  receive an `account_ref` such as `amma.citycab.primary`, never credentials.
- **Simulated mode:** each member has simulated accounts with fake wallets and ride
  history. Standing approvals draw against the wallet limit.
- **Real mode** is a swappable adapter behind the same four tool contracts (`quote`,
  `request`, `status`, `cancel`):

| Adapter | Notes |
| --- | --- |
| Deep-link handoff | Prefill pickup and drop-off; the user taps confirm. The safest real path |
| Official or partner API | OAuth, best behaved, needs partner approval |
| Browser or computer-use agent | Last resort. Fragile and likely against platform terms. Own session only |

- **Credentials:** an executor resolves `account_ref` from the OS keychain or a
  secrets manager. Nothing goes in the repo, the state, the logs or the LLM context.
- **Notifications:** a booking creates a notification with a status link. In the
  simulator that is a toast plus a status page with a **Cancel** button. In real mode
  it is a push that deep-links to the real app, where cancel already exists.

## 10. Agent layer

- **Context injected per turn by the host** (the model does not have to recall it):
  speaker, roster with IDs and aliases, presence, return times, clock and daypart,
  active tasks.
- **Name resolution before the model:** Amma/Mom → `amma`, Papa/Dad → `papa`,
  Son → `son`, Housebot/robot → `housebot`. Nobody types IDs.
- **Tool surface** (extends the existing mobility and shopping tools):

| Tool | Purpose |
| --- | --- |
| `get_household()` | members, presence, clock, active tasks |
| `create_ride_booking_proposal(member, destination, expected_return?, deadline?)` | existing, extended |
| `create_order_proposal(member, items, provider)` | existing, extended |
| `start_watch(member, content?, duration_min?)` | TV task |
| `start_robot_assist(target, kind="massage", duration_min)` | robot task |
| `set_expected_return(member, time)` | edit away time |
| `get_task(task_id)` / `cancel_task(task_id)` | status and cancel |

- **Forced tool use:** action-style messages require a tool call. If the model returns
  none, retry once; if it still returns none, show an explicit "I couldn't act on that."
  Never a made-up result.
- **Skill change:** moving a person is allowed as a visible side effect of a confirmed
  task. The approval rules for rides and orders stay exactly as they are.

## 11. Events and API

Event types over SSE: `scene`, `clock`, `presence`, `device`, `task`, `notification`,
`utterance` (what a character said, as a speech bubble).

```json
{"type": "scene", "task": "t17", "actor": "amma", "phase": "waiting", "goto": "front_door.slot_1",
 "anim": "wait_facing_camera", "bubble": "Waiting for ride…",
 "overlay": {"type": "ride_modal", "state": "searching"}}
```

The renderer is a pure function of events. Refreshing the page replays the current
state from a `/snapshot` endpoint.

## 12. UI

```
[ Verity House ]     [☀ Morning 10:15]     [ Amma ● Papa ● Son ○ Housebot ● ]
┌──────────────────────────────────────────────────────────────┐
│  house + front door + street.  Echo icon with pulse ring.     │
│  "Simulated Alexa+"                                           │
└──────────────────────────────────────────────────────────────┘
  Amma is waiting for her ride · arriving in 5 min        ← one-line strip
  [ Speaking as Amma ▾   Ask Alexa…                     🎙 ➤ ]
```

- **Sprite states:** idle, walk (4 directions), sit, wait-facing-camera, assist, sleep.
- **Echo device** in the living room, with colours for listening, thinking and speaking.
- **TV:** an animated gradient screen with a soft glow that tints the room when on.
- **Overlays:** confirmation, ride (search → driver → ETA → cancel), order tracker,
  who's home. One open at a time, each dismissible. The ride overlay is a large popup
  on top of the screen, so it can use more space.
- **Removed from the main screen:** Manual/Demo toggle, simulated clock, "Simulate Mon
  10:15 at PG", the live-activity sidebar, "What Verity did", raw tool results, the
  character-state legend, and static device labels. All of these go in the debug drawer.
- **Accessibility:** reduced-motion option, keyboard-focusable overlays, text
  alternatives for the status strip.

## 13. Trust and disclosure

- The Echo and the whole host are labelled simulated. The massage is labelled simulated
  and non-medical.
- Neutral platform names and no logos in the UI.
- No real credentials and no real bookings in the demo build.

## 14. Testing

- **Deterministic clock**, injectable, so no test sleeps.
- **Golden event sequences** for each task, asserted as lists of events.
- **Authorisation tests** for each row of the matrix, including `speaker_away`,
  `target_away` and `robot_busy`.
- **Forced tool use** with a stub model that returns no tool calls.
- **Browser test** (Playwright): after "Book Amma a ride to the market", Amma's sprite
  reaches the `front_door` anchor and the ride popup opens. Anchors and states are
  exposed as data attributes so this is testable.
- **Concurrency:** two members acting at once, and a server restart mid-task.

## 15. Build phases (exit criteria, not dates)

1. **Foundation:** world store, graph and anchors, clock, tick loop, SSE, renderer
   that walks a character to any anchor. *Exit:* a scripted walk plays in the browser.
2. **Ride vertical slice:** walk to door, wait, popup, depart, away, return. *Exit:*
   golden event test and browser test pass.
3. **Presence and authority:** guard, who's-home modal, click-to-speak, return times.
   *Exit:* an away member's command is refused visibly.
4. **More tasks:** TV, massage, orders, goodnight. *Exit:* each has a golden test.
5. **Dayparts and routines:** clock tint, routine tables, scheduler, standing approvals.
   *Exit:* a simulated day runs with no manual input.
6. **Intelligence and accounts:** deadline scoring, preferences, simulated accounts and
   wallets, notifications with cancel. *Exit:* the 11:30 meeting case picks the nearer,
   pricier ride, and the explanation says why.
7. **Polish:** debug drawer, accessibility, README and demo script.

## 16. Honest limits

- Every routine runs through a real model call, so a full simulated day feels slower
  than the animation.
- Real Uber or Rapido control stays on the roadmap, because of platform terms. The
  adapter design leaves room for it.
