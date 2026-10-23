// Developer details (trace, steps, mode and time controls) only show with ?debug=1.
document.body.classList.toggle("debug", new URLSearchParams(location.search).get("debug") === "1");
let presenceAway = new Set();
let householdMembers = [];
let ridesLoaded = false;
const seenHedges = new Set();

const ROOMS = {
  living_room: { x: 13, y: 18 }, kitchen: { x: 66, y: 18 },
  bedroom: { x: 13, y: 66 }, tv_room: { x: 66, y: 66 }, away: { x: 48, y: 48 }
};
const CONNECTIONS = { living_room: ["kitchen", "bedroom"], kitchen: ["living_room", "tv_room"], bedroom: ["living_room", "tv_room"], tv_room: ["kitchen", "bedroom"] };
const PEOPLE = { son: { label: "Son", color: "#7bdff2" }, amma: { label: "Amma", color: "#ffb86c" }, papa: { label: "Papa", color: "#b8f2a0" }, housebot: { label: "Housebot", color: "#9de5ff" } };
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
      // Someone marked away is outside, even if the last room record still lists them.
      if (presenceAway.has(person)) return;
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
    presenceAway = new Set((data.household?.members || []).filter((m) => m.presence === "away").map((m) => m.person_id));
    // Seconds until each rider is back, turned into a deadline so the countdown can tick smoothly on this page.
    returnsDue = Object.fromEntries(Object.entries(data.returns || {}).map(([person, seconds]) => [person, Date.now() + seconds * 1000]));
    // The pill is only for the labelled scripted demo. Which model answers is a developer detail.
    const pill = document.querySelector("#mode-pill");
    const scripted = data.mode === "scripted";
    const fallback = String(data.mode || "").startsWith("fallback:");
    pill.hidden = !scripted && !fallback && !document.body.classList.contains("debug");
    pill.textContent = scripted ? "Scripted demo · no AI key" : fallback ? `Fallback model: ${String(data.mode).replace("fallback:", "").replace("ollama:", "Ollama · ")}` : `Debug: AI answers ${String(data.mode || "").replace("ai:", "")}`;
    pill.className = `mode-pill ${scripted ? "scripted" : "ai"}`;
    if (data.clock?.sim_time) {
      document.querySelector("#sim-clock").textContent = `SIM TIME ${data.clock.sim_time}`;
      const timeInput = document.querySelector("#sim-time");
      if (document.activeElement !== timeInput) timeInput.value = data.clock.sim_time;
    }
    const departed = Object.keys(data.scene || {}).filter((id) => data.scene[id].stage === "departed");
    renderHousehold(data.household?.members || [], new Set([...presenceAway, ...departed]));
    renderDevices(data.home, data.robot, data.proactive); speaker.value = data.active_speaker.person_id;
    const lights = {}; let tvOn = false;
    Object.entries(data.home || {}).forEach(([room, value]) => (value.devices || []).forEach((device) => {
      if (device.type === "light") lights[room] = device.state === "on";
      if (device.type === "tv") tvOn = device.state === "on";
    }));
    window.pixelHouse.setScene(data.scene || {}, { tvOn, lights });
    // When nothing is in progress, the status line says what each person is doing.
    if (!isProcessingTurn && data.scene_lines?.length) document.querySelector("#agent-now").textContent = data.scene_lines.join(" · ");
    status.textContent = `Active speaker: ${data.active_speaker.display_name}`;
  } catch (error) { status.textContent = "MCP state unavailable"; }
}

const AVATAR_SPRITES = { son: "char_0", amma: "char_1", papa: "char_3" };
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

// A reply that ends in a question shows that question in the question popup, not in the reply line.
function splitQuestion(text) {
  const sentences = text.match(/[^.!?]+[.!?]+|[^.!?]+$/g) || [text];
  const last = sentences[sentences.length - 1].trim();
  if (!last.endsWith("?")) return { statement: text, question: null };
  return { statement: sentences.slice(0, -1).join(" ").trim(), question: last };
}
// Only a question that asks permission to act gets Yes and No. Any other question is answered by typing.
const CONFIRMATION_QUESTION = /^(shall i|should i|do you want (me )?to|would you like (me )?to|want me to|may i|can i|is that (ok|right|correct)|okay to|ok to)\b/i;

async function ask(rawText, personId = speaker.value) {
  const text = rawText.replace(/^alexa[, ]*/i, "").trim(); if (!text) return;
  setTaskBlock("#question-block", false); addMessage("user", PEOPLE[personId].label, text, personId); startProgress(); characters[personId].status = "busy"; renderCharacters(); status.textContent = "Agent is choosing tools…";
  try {
    const response = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, person_id: personId, text }) });
    const result = await response.json(); if (!response.ok) throw new Error(result.error || "Request failed");
    const failed = result.trace.some((event) => event.kind === "tool" && event.result.output && event.result.output.success === false);
    const spokenResponse = plainSpeech(result.speech);
    const { statement, question } = splitQuestion(spokenResponse);
    const options = CONFIRMATION_QUESTION.test(question || "") ? ["Yes", "No"] : [];
    renderQuestion(result.question || (question ? { text: question, options } : null));
    const replyText = result.question || !question ? spokenResponse : statement;
    characters[personId].status = failed ? "alert" : "idle"; renderCharacters(); addMessage("assistant", "Verity", spokenResponse); document.querySelector("#reply").textContent = replyText; trace.textContent = JSON.stringify(result.trace, null, 2); renderSteps(result.trace); traceStatus.textContent = `${result.trace.length} event${result.trace.length === 1 ? "" : "s"}`; speak(spokenResponse); await refreshState();
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

// Who is home: one chip per member. Away members cannot be chosen as the speaker.
function renderHousehold(members, outside = new Set()) {
  householdMembers = members;
  const chips = document.querySelector("#household");
  chips.replaceChildren(...members.map((m) => {
    const isOutside = outside.has(m.person_id);
    const chip = el("button", `chip ${isOutside ? "away" : "home"}`, `${m.display_name}`);
    chip.type = "button";
    chip.dataset.person = m.person_id;
    chip.title = isOutside ? (m.presence === "away" ? `Away until ${m.return_at}` : "Out of the house") : "Home";
    chip.addEventListener("click", () => { renderHouseholdList(); showOverlay("household-modal"); });
    return chip;
  }));
  if (!document.querySelector("#household-modal").hidden) renderHouseholdList();
  // Away members cannot be chosen as the speaker.
  [...speaker.options].forEach((option) => { option.disabled = presenceAway.has(option.value); });
}
// Riders who left on a ride show a countdown to their return, on their chip: "Amma · back in 2:41".
let returnsDue = {};
function updateReturnTimers() {
  document.querySelectorAll("#household .chip[data-person]").forEach((chip) => {
    const due = returnsDue[chip.dataset.person];
    const name = chip.dataset.name || (chip.dataset.name = chip.textContent);
    if (!due) { chip.textContent = name; return; }
    const seconds = Math.max(0, Math.ceil((due - Date.now()) / 1000));
    chip.textContent = `${name} · back in ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  });
}
setInterval(updateReturnTimers, 250);

function renderHouseholdList() {
  const list = document.querySelector("#household-list");
  list.replaceChildren(...householdMembers.map((m) => {
    const row = el("div", `household-row ${m.presence}`);
    const text = el("div", "household-text");
    text.append(el("b", null, m.display_name), el("span", null, m.presence === "away" ? `Away · back at ${m.return_at || "unknown time"}` : "Home"));
    // Saved preferences are visible: a value, or 'not set yet' so it is clear nothing has been guessed.
    text.append(el("span", "pref", `Ride: ${m.ride_priority || "not set yet"} · usual destination: ${m.usual_destination || "none"}`));
    row.append(text);
    const actions = el("div", "household-actions");
    if (m.presence === "away") {
      const back = el("button", "secondary", "Back now");
      back.type = "button";
      back.addEventListener("click", async () => {
        await fetch("/api/presence", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ person_id: m.person_id, presence: "home" }) });
        refreshState();
      });
      actions.append(back);
    } else {
      const pick = el("button", "secondary", "Speak as");
      pick.type = "button";
      pick.addEventListener("click", () => { speaker.value = m.person_id; hideOverlay("household-modal"); });
      actions.append(pick);
    }
    row.append(actions);
    return row;
  }));
}

document.querySelector("#close-rides").addEventListener("click", () => hideOverlay("ride-overlay"));
document.querySelector("#ride-open").addEventListener("click", () => showOverlay("ride-overlay"));
document.querySelector("#close-household").addEventListener("click", () => hideOverlay("household-modal"));

// A ride waiting for a yes shows as a popup on top of the house, with Confirm and Not now.
let confirmShownFor = null;
// The booking popup counts the driver's wait down, second by second, and then says the driver has arrived.
let bookingCountdown = null;
function bookingLine(booking, remaining) {
  const when = remaining > 0 ? `Driver arrives in ${remaining} second${remaining === 1 ? "" : "s"} (simulated).` : "Driver has arrived (simulated).";
  return `${booking.provider} ride for ${booking.name} to ${booking.destination}. ${when} ₹${booking.price_inr}. Reference ${booking.reference}.`;
}
function startBookingCountdown(booking) {
  bookingCountdown = { booking, startedAt: Date.now() };
  document.querySelector("#booking-text").textContent = bookingLine(booking, booking.pickup_seconds);
}
setInterval(() => {
  if (!bookingCountdown) return;
  const { booking, startedAt } = bookingCountdown;
  const remaining = Math.max(0, booking.pickup_seconds - Math.floor((Date.now() - startedAt) / 1000));
  if (!document.querySelector("#booking-block").hidden) document.querySelector("#booking-text").textContent = bookingLine(booking, remaining);
  if (remaining === 0) bookingCountdown = null;
}, 250); // a quarter-second check keeps the number within a quarter-second of the real time

async function checkPending() {
  try {
    const response = await fetch(`/api/progress?session_id=${encodeURIComponent(sessionId)}`);
    const data = await response.json();
    const pending = data.pending;
    const booking = data.booking;
    // Every ride or order waiting for a decision is its own card in the "Verity is working" popup.
    renderApprovals(data.approvals || []);
    // A booked ride shows its details in the same popup, once per booking. Only the person closes it.
    const bookedKey = booking ? `booked:${booking.reference}` : null;
    if (booking && bookedKey !== confirmShownFor) {
      startBookingCountdown(booking);
      setTaskBlock("#booking-block", true);
    }
    confirmShownFor = bookedKey;
  } catch (error) { /* the next check will try again */ }
}
document.querySelector("#booking-done").addEventListener("click", () => setTaskBlock("#booking-block", false));
setInterval(checkPending, 1500);

// Suggested tasks: one click asks Verity as the person currently selected.
// Each suggestion names who says it, so "Book Amma a ride" is said by Son, not by whoever was selected last.
document.querySelectorAll(".suggest").forEach((button) => button.addEventListener("click", () => {
  speaker.value = button.dataset.speaker;
  enqueueAsk(button.dataset.say, button.dataset.speaker);
}));

// Popups can be dragged by their header and resized from the corner.
function makeMovable(card) {
  const head = card.querySelector(".overlay-head, .thinking-head");
  if (!head) return;
  head.style.cursor = "move";
  head.addEventListener("pointerdown", (event) => {
    if (event.target.closest("button")) return;
    const rect = card.getBoundingClientRect();
    const offsetX = event.clientX - rect.left, offsetY = event.clientY - rect.top;
    card.style.position = "fixed"; card.style.transform = "none";
    card.style.left = `${rect.left}px`; card.style.top = `${rect.top}px`;
    const move = (e) => {
      card.style.left = `${Math.min(Math.max(0, e.clientX - offsetX), window.innerWidth - 80)}px`;
      card.style.top = `${Math.min(Math.max(0, e.clientY - offsetY), window.innerHeight - 40)}px`;
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  });
}
["#thinking-card", "#ride-overlay .overlay-card", "#household-modal .overlay-card"].forEach((selector) => {
  const card = document.querySelector(selector);
  if (card) makeMovable(card);
});

// Developer control for the simulated house time. Members who are away return home when it reaches their time.
document.querySelector("#sim-time").addEventListener("change", async (event) => {
  await fetch("/api/clock", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sim_time: event.target.value }) });
  refreshState();
});

// Live status line: polls what Verity is doing right now, in plain words.
let progressTimer = null;
const IDLE_AGENT_TEXT = "Ready. Ask for something, or try the time tick.";
// A question from Verity is asked inside the "Verity is working" popup, with its answers as buttons.
// Each button sends the answer as a message. Typing an answer in the box also works.
function renderQuestion(question) {
  const choices = document.querySelector("#question-choices");
  choices.replaceChildren();
  if (!question) { setTaskBlock("#question-block", false); return; }
  document.querySelector("#question-text").textContent = question.text;
  question.options.forEach((option, index) => {
    const button = el("button", index === 0 ? "primary" : "secondary", option === "cheapest" ? "Cheapest" : option === "fastest" ? "Fastest" : option === "Yes" ? "Yes" : option === "No" ? "No" : option);
    button.type = "button";
    button.addEventListener("click", () => { setTaskBlock("#question-block", false); enqueueAsk(option, speaker.value); });
    choices.append(button);
  });
  setTaskBlock("#question-block", true);
}

// Blocks inside the progress popup. The popup cannot be closed while the person still has to answer.
function setTaskBlock(selector, visible) {
  document.querySelector(selector).hidden = !visible;
  const answerNeeded = !document.querySelector("#question-block").hidden || !document.querySelector("#approval-list").hidden;
  document.querySelector("#thinking-close").hidden = answerNeeded;
  if (visible) document.querySelector("#thinking-card").hidden = false;
}

// One card per waiting ride or order. Accept and Decline send that card's proposal id, and only that proposal changes.
const approvalCards = new Map();
function approvalText(approval) {
  if (approval.kind === "order") return `Order for ${approval.name} from ${approval.provider_name}: ${(approval.items || []).join(", ")}.`;
  const preference = approval.ride_priority ? `${approval.name}'s saved preference: ${approval.ride_priority}. ` : "";
  const trip = approval.distance_km ? `, ${approval.distance_km} km from the house` : "";
  const why = approval.choice_reason ? ` ${approval.choice_reason}` : "";
  return `${approval.name}'s ride. ${preference}Chosen: ${approval.provider_name || approval.provider}, ₹${approval.price_inr}, ${approval.eta_min} min${trip}.${why}`;
}
function renderApprovals(approvals) {
  const list = document.querySelector("#approval-list");
  const waiting = new Set(approvals.map((approval) => approval.proposal_id));
  approvalCards.forEach((card, proposalId) => {
    if (!waiting.has(proposalId)) { card.remove(); approvalCards.delete(proposalId); }
  });
  approvals.forEach((approval) => {
    if (approvalCards.has(approval.proposal_id)) return;
    const card = el("div", "task-block approval-card");
    card.dataset.proposal = approval.proposal_id;
    card.append(el("p", "task-text", approvalText(approval)));
    const actions = el("div", "task-actions");
    const decline = el("button", "secondary", "Decline");
    const accept = el("button", "primary", "Accept");
    decline.type = accept.type = "button";
    decline.addEventListener("click", () => decideApproval(approval.proposal_id, "decline"));
    accept.addEventListener("click", () => decideApproval(approval.proposal_id, "accept"));
    actions.append(decline, accept);
    card.append(actions);
    approvalCards.set(approval.proposal_id, card);
    list.append(card);
  });
  list.hidden = approvals.length === 0;
  if (approvals.length) document.querySelector("#thinking-card").hidden = false;
  document.querySelector("#thinking-close").hidden = approvals.length > 0 || !document.querySelector("#question-block").hidden;
}
async function decideApproval(proposalId, decision) {
  approvalCards.get(proposalId)?.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  try {
    const response = await fetch("/api/approval", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, proposal_id: proposalId, decision }) });
    const result = await response.json();
    if (result.speech) { addMessage("assistant", "Verity", result.speech); document.querySelector("#reply").textContent = result.speech; }
  } catch (error) {
    // The card stays, so the person can try again.
    approvalCards.get(proposalId)?.querySelectorAll("button").forEach((button) => { button.disabled = false; });
  }
  await checkPending();
}

function showThinking() {
  document.querySelector("#thinking-card").hidden = false;
  document.querySelector("#thinking-steps").replaceChildren();
  document.querySelector("#thinking-now").textContent = "Thinking about what you asked…";
}
function renderThinking(steps, current) {
  if (current) document.querySelector("#thinking-now").textContent = current;
  const list = document.querySelector("#thinking-steps");
  list.replaceChildren(...steps.map((step) => {
    const item = document.createElement("li");
    item.className = step.ok ? "ok" : "fail";
    item.textContent = (step.ok ? "✓ " : "✗ ") + step.text;
    return item;
  }));
}
document.querySelector("#thinking-close").addEventListener("click", () => { document.querySelector("#thinking-card").hidden = true; });

function startProgress() {
  showThinking();
  document.querySelector("#agent-now").textContent = "Thinking about what you asked…";
  document.querySelector(".echo").classList.add("thinking");
  clearInterval(progressTimer); progressTimer = setInterval(pollProgress, 500);
}
async function pollProgress() {
  try {
    const response = await fetch(`/api/progress?session_id=${encodeURIComponent(sessionId)}`);
    const data = await response.json();
    if (data.current) document.querySelector("#agent-now").textContent = data.current;
    renderThinking(data.steps || [], data.current);
  } catch (error) { /* the next poll will try again */ }
}
function stopProgress() {
  clearInterval(progressTimer); progressTimer = null;
  // The working card stays open until the person closes it or the next request replaces it.
  document.querySelector(".echo").classList.remove("thinking");
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
// Notification for a committed ride: details, a way to open it, and a manual cancel.
function notificationCard(hedge) {
  const c = hedge.committed;
  const box = el("div", "notice-card");
  box.append(el("b", null, "Your ride is set (simulated)"));
  box.append(el("span", null, `${c.label}: driver ${c.driver}, arrives in about ${c.eta_minutes * 4} seconds (simulated), ₹${c.fare_inr}.`));
  const row = el("div", "notice-actions");
  const open = el("button", "secondary", "Open ride");
  open.type = "button";
  open.addEventListener("click", () => { const why = box.closest(".ride-card").querySelector("details.why"); if (why) why.open = true; box.closest(".ride-card").scrollIntoView({ block: "nearest" }); });
  const cancel = el("button", "danger", "Cancel ride");
  cancel.type = "button";
  cancel.addEventListener("click", () => cancelRide(hedge, cancel));
  row.append(open, cancel); box.append(row);
  return box;
}
async function cancelRide(hedge, button) {
  button.disabled = true;
  try {
    const response = await fetch("/api/rides/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ person_id: hedge.person_id, hedge_id: hedge.hedge_id }) });
    const result = await response.json();
    const message = result.success
      ? `Cancelled. Fee for this cancel: ₹${result.fee_charged_inr ?? 0}; fees so far ₹${result.fees_inr ?? 0} (simulated).`
      : `Not cancelled: ${result.reason || result.error || "unknown reason"}.`;
    document.querySelector("#agent-now").textContent = message;
  } catch (error) {
    document.querySelector("#agent-now").textContent = "Could not reach the simulator to cancel.";
  } finally { refreshRides(); }
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

  if (hedge.deadline) {
    const d = hedge.deadline;
    const where = d.source === "calendar" && d.title ? `${d.title} (calendar)` : "the time you gave";
    card.append(el("div", "deadline", `Deadline: ${where}, in ${d.minutes_until_meeting} min · time valued at ₹${d.value_of_time_inr_per_min}/min (${d.value_of_time_basis}) · lateness ₹${d.late_penalty_inr_per_min}/min`));
  }
  if (hedge.status === "committed" && hedge.committed) card.append(notificationCard(hedge));
  if (hedge.explanation && hedge.explanation.length) {
    const why = el("details", "why"); why.open = true; why.append(el("summary", null, "What happened"));
    const steps = el("ol"); hedge.explanation.forEach((line) => steps.append(el("li", null, line)));
    why.append(steps); card.append(why);
  }
  card.append(el("div", "ride-foot", `Cancellation fees so far: ₹${hedge.fees_inr} (simulated)`));
  return card;
}
function showOverlay(id) { document.getElementById(id).hidden = false; }
function hideOverlay(id) { document.getElementById(id).hidden = true; }
function renderRides(hedges) {
  const box = document.querySelector("#rides");
  document.querySelector("#ride-count").textContent = hedges.length ? `${hedges.length} request${hedges.length === 1 ? "" : "s"}` : "";
  document.querySelector("#ride-open").hidden = hedges.length === 0;
  box.replaceChildren(...(hedges.length ? hedges.map(rideCard) : [el("p", "empty-hint", "No ride requests yet.")]));
  // A new ride request opens the large popup on top of the house. Requests already seen on page load do not.
  const fresh = hedges.filter((h) => !seenHedges.has(h.hedge_id));
  hedges.forEach((h) => seenHedges.add(h.hedge_id));
  if (ridesLoaded && fresh.length) showOverlay("ride-overlay");
  ridesLoaded = true;
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
