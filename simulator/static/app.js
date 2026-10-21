const ROOMS = {
  living_room: { x: 13, y: 18 }, kitchen: { x: 66, y: 18 },
  bedroom: { x: 13, y: 66 }, tv_room: { x: 66, y: 66 }, away: { x: 48, y: 48 }
};
const CONNECTIONS = { living_room: ["kitchen", "bedroom"], kitchen: ["living_room", "tv_room"], bedroom: ["living_room", "tv_room"], tv_room: ["kitchen", "bedroom"] };
const PEOPLE = { son: { label: "Son", color: "#7bdff2" }, amma: { label: "Amma", color: "#ffb86c" }, papa: { label: "Papa", color: "#b8f2a0" }, sister: { label: "Sister", color: "#e4b7ff" }, housebot: { label: "Housebot", color: "#9de5ff" } };
const characters = Object.fromEntries(Object.keys(PEOPLE).map((id) => [id, { room: "away", status: "away" }]));
const demoScript = [
  { time: "07:00", person: "son", text: "Remember that my response style is brief." },
  { time: "09:00", person: "amma", text: "What are my saved preferences?" },
  { time: "20:00", person: "papa", text: "Show the current home state." }
];
let demoTimer = null, simMinutes = 6 * 60;
let isProcessingTurn = false;
const queuedTurns = [];
const sessionId = sessionStorage.getItem("verity-session-id") || crypto.randomUUID();
sessionStorage.setItem("verity-session-id", sessionId);

const conversation = document.querySelector("#conversation"), trace = document.querySelector("#trace");
const traceStatus = document.querySelector("#trace-status");
const status = document.querySelector("#status"), form = document.querySelector("#chat-form");
const speaker = document.querySelector("#speaker"), prompt = document.querySelector("#prompt"), send = document.querySelector("#send"), mic = document.querySelector("#mic");

function renderCharacters() {
  window.pixelHouse.sync(characters, PEOPLE);
}

function moveCharacter(personId, room) {
  const state = characters[personId];
  if (!state || state.room === room) return;
  // The canvas owns tile-level BFS animation. The app only reconciles real
  // occupancy state from MCP into one room destination per person.
  state.room = room;
  state.status = room === "away" ? "away" : "walking";
  renderCharacters();
  if (room !== "away") {
    window.setTimeout(() => {
      if (characters[personId].room === room && characters[personId].status === "walking") {
        characters[personId].status = "idle";
        renderCharacters();
      }
    }, 1800);
  }
}

function renderDevices(home, robot, proactive) {
  const seenPeople = new Set();
  Object.entries(home).forEach(([room, value]) => {
    const holder = document.querySelector(`[data-room="${room}"]`); if (!holder) return;
    holder.textContent = value.devices.map((device) => `${device.type.toUpperCase()} ${device.state.toUpperCase()}`).join("  ");
    (value.occupants || []).forEach((person) => {
      seenPeople.add(person);
      moveCharacter(person, room);
    });
  });
  Object.keys(characters).forEach((person) => {
    if (person !== "housebot" && !seenPeople.has(person)) moveCharacter(person, "away");
  });
  if (robot) {
    characters.housebot.room = robot.room || "away";
    characters.housebot.status = robot.status === "working" ? "busy" : "idle";
    document.querySelector("#robot-status").textContent = `HOUSEBOT: ${String(robot.status || "unknown").toUpperCase()} | ${robot.battery_percent ?? "?"}% | SIMULATED`;
  }
  const count = proactive?.count ?? 0;
  document.querySelector("#proactive-status").textContent = count
    ? `ENERGY CHECK: ${count} SUGGESTION${count === 1 ? "" : "S"}`
    : "ENERGY CHECK: ALL CLEAR";
  renderCharacters();
}

async function refreshState() {
  try {
    const response = await fetch("/api/state"), data = await response.json(); if (!response.ok) throw new Error(data.error);
    renderDevices(data.home, data.robot, data.proactive); speaker.value = data.active_speaker.person_id;
    status.textContent = `Active speaker: ${data.active_speaker.display_name}`;
  } catch (error) { status.textContent = "MCP state unavailable"; }
}

const AVATAR_SPRITES = { son: "char_0", amma: "char_1", papa: "char_3", sister: "char_4" };
function avatarFor(personId) {
  const avatar = document.createElement("span");
  if (personId && AVATAR_SPRITES[personId]) {
    avatar.className = "avatar";
    avatar.style.backgroundImage = `url(/assets/pixel-agents/characters/${AVATAR_SPRITES[personId]}.png)`;
  } else {
    avatar.className = "avatar verity-mark";
    avatar.textContent = "V";
  }
  avatar.setAttribute("aria-hidden", "true");
  return avatar;
}
function addMessage(kind, who, text, personId = null) {
  const item = document.createElement("div"); item.className = `message ${kind}`;
  const body = document.createElement("div"); const name = document.createElement("b"); name.textContent = who;
  const span = document.createElement("span"); span.textContent = text; body.append(name, span);
  item.append(avatarFor(personId), body); conversation.appendChild(item); conversation.scrollTop = conversation.scrollHeight;
}
function speak(text) { if (!window.speechSynthesis) return; window.speechSynthesis.cancel(); window.speechSynthesis.speak(new SpeechSynthesisUtterance(text)); }

function plainSpeech(text) {
  return text
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[`*_#>|]/g, "")
    .replace(/^\s*[-+]\s*/gm, "")
    .replace(/^\s*\d+[.)]\s*/gm, "")
    .replace(/\s{2,}/g, " ")
    .replace(/\n+/g, ". ")
    .trim();
}

function updateComposerState() {
  // Preserve ordered household state while still letting the user type and send
  // their next message during a slower agent/tool round trip.
  send.disabled = false;
  if (!isProcessingTurn) {
    send.textContent = "Send";
    return;
  }
  send.textContent = queuedTurns.length ? `Queued (${queuedTurns.length})` : "Working…";
}

function enqueueAsk(rawText, personId = speaker.value) {
  const text = rawText.replace(/^alexa[, ]*/i, "").trim();
  if (!text) return;
  queuedTurns.push({ text, personId });
  updateComposerState();
  if (!isProcessingTurn) void processNextTurn();
}

async function processNextTurn() {
  const next = queuedTurns.shift();
  if (!next) {
    isProcessingTurn = false;
    updateComposerState();
    prompt.focus();
    return;
  }
  isProcessingTurn = true;
  updateComposerState();
  try {
    await ask(next.text, next.personId);
  } finally {
    await processNextTurn();
  }
}

async function ask(rawText, personId = speaker.value) {
  const text = rawText.replace(/^alexa[, ]*/i, "").trim(); if (!text) return;
  addMessage("user", PEOPLE[personId].label, text, personId); startProgress(); characters[personId].status = "busy"; renderCharacters(); status.textContent = "Agent is choosing tools…";
  try {
    const response = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, person_id: personId, text }) });
    const result = await response.json(); if (!response.ok) throw new Error(result.error || "Request failed");
    const failed = result.trace.some((event) => event.kind === "tool" && event.result.output && event.result.output.success === false);
    const spokenResponse = plainSpeech(result.speech);
    characters[personId].status = failed ? "alert" : "idle"; renderCharacters(); addMessage("assistant", "Verity", spokenResponse); trace.textContent = JSON.stringify(result.trace, null, 2); renderSteps(result.trace); traceStatus.textContent = `${result.trace.length} event${result.trace.length === 1 ? "" : "s"}`; speak(spokenResponse); await refreshState();
  } catch (error) { characters[personId].status = "alert"; renderCharacters(); addMessage("assistant", "Verity", "The simulated host could not complete that request."); trace.textContent = String(error); traceStatus.textContent = "Error"; status.textContent = "Error"; }
  finally { stopProgress(); prompt.focus(); }
}

form.addEventListener("submit", (event) => { event.preventDefault(); enqueueAsk(prompt.value); prompt.value = ""; });
// Simulated time tick: a context event, not a user request. The agent may suggest or stay quiet.
document.querySelector("#tick").addEventListener("click", () => enqueueAsk("[context event] Monday 10:15. Son is at the PG. No user request. Decide whether to suggest anything.", "son"));
function tickDemoClock() {
  simMinutes = (simMinutes + 10) % (24 * 60);
  const now = `${String(Math.floor(simMinutes / 60)).padStart(2, "0")}:${String(simMinutes % 60).padStart(2, "0")}`;
  document.querySelector("#sim-clock").textContent = `SIM TIME ${now}`;
  demoScript.filter((item) => item.time === now).forEach((item) => enqueueAsk(item.text, item.person));
}

document.querySelectorAll(".mode").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".mode").forEach((item) => item.classList.remove("active")); button.classList.add("active");
  clearInterval(demoTimer); if (button.dataset.mode === "demo") { status.textContent = "Demo mode: sending real commands"; demoTimer = setInterval(tickDemoClock, 1000); }
}));

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!SpeechRecognition) mic.disabled = true;
else { const recognition = new SpeechRecognition(); recognition.lang = "en-IN"; recognition.interimResults = true; recognition.onresult = (event) => { const text = Array.from(event.results).map((result) => result[0].transcript).join(""); prompt.value = text; if (event.results[event.results.length - 1].isFinal) { enqueueAsk(text); prompt.value = ""; } }; mic.addEventListener("click", () => recognition.start()); }

// Live status line: polls what Verity is doing right now, in plain words.
let progressTimer = null;
const IDLE_AGENT_TEXT = "Ready. Ask for something, or try the time tick.";
function startProgress() {
  document.querySelector("#agent-now").textContent = "Thinking about what you asked…";
  clearInterval(progressTimer); progressTimer = setInterval(pollProgress, 500);
}
async function pollProgress() {
  try {
    const response = await fetch(`/api/progress?session_id=${encodeURIComponent(sessionId)}`);
    const data = await response.json();
    if (data.current) document.querySelector("#agent-now").textContent = data.current;
  } catch (error) { /* the next poll will try again */ }
}
function stopProgress() {
  clearInterval(progressTimer); progressTimer = null;
  document.querySelector("#agent-now").textContent = IDLE_AGENT_TEXT;
}

// "What Verity did": one plain sentence per tool call, from the finished turn.
function renderSteps(traceEvents) {
  const list = document.querySelector("#steps"); list.replaceChildren();
  const steps = traceEvents.filter((event) => event.kind === "tool" && event.say);
  if (!steps.length) {
    const item = document.createElement("li"); item.className = "muted"; item.textContent = "No tool steps in this request."; list.append(item); return;
  }
  steps.forEach((step) => {
    const item = document.createElement("li"); item.className = step.ok ? "ok" : "fail";
    item.textContent = (step.ok ? "" : "✗ ") + step.say; list.append(item);
  });
  document.querySelector("#trace-status").textContent = `${steps.length} step${steps.length === 1 ? "" : "s"}`;
}

// Ride desk: one card per ride request, polled once a second. Text is set with textContent only.
function el(tag, className, text) {
  const node = document.createElement(tag); if (className) node.className = className;
  if (text !== undefined) node.textContent = text; return node;
}
function rideCard(hedge) {
  const card = el("article", "ride-card");
  const head = el("header"); head.append(el("span", "ride-title", hedge.headline), el("span", "badge", "SIMULATED"));
  card.append(head);
  if (hedge.status === "failed") card.append(el("div", "banner failed", hedge.plain_status));
  else card.append(el("p", "ride-status", hedge.plain_status));

  const list = el("ul", "platforms");
  // Show the current round only; earlier rounds are described in "What happened".
  hedge.rides.filter((ride) => ride.round === hedge.round).forEach((ride) => {
    const chosen = hedge.committed && hedge.committed.ride_id === ride.ride_id;
    const kind = chosen ? "chosen" : ride.state === "cancelled" ? "cancelled" : ride.state === "searching" ? "searching" : "";
    const label = chosen ? "Chosen" : ride.state === "cancelled" ? "Cancelled" : ride.state === "accepted" ? "Driver found" : "Waiting";
    const item = el("li", `platform ${kind}`.trim());
    item.append(el("b", null, ride.label), el("em", null, label), el("span", "line", ride.line));
    list.append(item);
  });
  card.append(list);

  if (hedge.explanation && hedge.explanation.length) {
    const why = el("details", "why"); why.open = true; why.append(el("summary", null, "What happened"));
    const steps = el("ol"); hedge.explanation.forEach((line) => steps.append(el("li", null, line)));
    why.append(steps); card.append(why);
  }
  card.append(el("div", "ride-foot", `Cancellation fees so far: ₹${hedge.fees_inr} (simulated)`));
  return card;
}
function renderRides(hedges) {
  const box = document.querySelector("#rides");
  document.querySelector("#ride-count").textContent = hedges.length ? `${hedges.length} request${hedges.length === 1 ? "" : "s"}` : "None yet";
  if (!hedges.length) { box.replaceChildren(el("p", "empty-hint", "No ride requests yet. Try “Get me a ride to the office.”")); return; }
  box.replaceChildren(...hedges.map(rideCard));
}
async function refreshRides() {
  try {
    const response = await fetch("/api/rides"); const data = await response.json();
    if (response.ok) renderRides(data.hedges || []);
  } catch (error) { /* keep the last view; the status line shows connection problems */ }
}

// Each MCP read opens its own session on the server, so polling is kept slow and pauses in background tabs.
const POLL_MS = { state: 5000, rides: 2000 };
function whenVisible(fn) { if (!document.hidden) fn(); }
renderCharacters(); refreshState(); setInterval(() => whenVisible(refreshState), POLL_MS.state);
refreshRides(); setInterval(() => whenVisible(refreshRides), POLL_MS.rides);
