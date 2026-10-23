/*
 * Verity pixel-house renderer.
 * Architecture inspired by Pixel Agents by Pablo De Lucca (MIT): Canvas 2D,
 * tile positions, BFS movement, separated state sync, and a render loop.
 */
(() => {
  const TILE = 16, COLS = 32, ROWS = 24; // rows 22-23 are the porch outside the front door
  const TARGETS = {
    living_room: { col: 7, row: 7 }, kitchen: { col: 24, row: 7 },
    bedroom: { col: 7, row: 17 }, tv_room: { col: 24, row: 17 }, away: { col: -3, row: 11 },
  };
  const ROOM_SLOT_OFFSETS = [
    { col: 0, row: 0 }, { col: 3, row: 0 }, { col: -3, row: 0 }, { col: 0, row: 2 },
  ];
  const ROOMS = [
    { id: "living_room", label: "LIVING ROOM", x: 1, y: 1, w: 13, h: 9, floor: "wood" },
    { id: "kitchen", label: "KITCHEN", x: 18, y: 1, w: 13, h: 9, floor: "tile" },
    { id: "bedroom", label: "BEDROOM", x: 1, y: 13, w: 13, h: 8, floor: "wood" },
    { id: "tv_room", label: "TV ROOM", x: 18, y: 13, w: 13, h: 8, floor: "blue" },
  ];
  // Each pair is a narrow walkable doorway joining a room interior to a hall.
  const DOOR_PATHS = [
    [{ col: 7, row: 9 }, { col: 7, row: 10 }],       // living → horizontal hall
    [{ col: 24, row: 9 }, { col: 24, row: 10 }],     // kitchen → horizontal hall
    [{ col: 7, row: 12 }, { col: 7, row: 13 }],      // bedroom → horizontal hall
    [{ col: 24, row: 12 }, { col: 24, row: 13 }],    // TV room → horizontal hall
    [{ col: 13, row: 5 }, { col: 14, row: 5 }],      // living → vertical hall
    [{ col: 17, row: 5 }, { col: 18, row: 5 }],      // kitchen → vertical hall
    [{ col: 13, row: 17 }, { col: 14, row: 17 }],    // bedroom → vertical hall
    [{ col: 17, row: 17 }, { col: 18, row: 17 }],    // TV room → vertical hall
    [{ col: 15, row: 21 }, { col: 16, row: 21 }],    // front door: hall → porch
  ];
  // Waiting spots. Several people can wait at the door or sit at the TV at once.
  const DOOR_SLOTS = [{ col: 15, row: 22 }, { col: 16, row: 22 }, { col: 14, row: 22 }, { col: 17, row: 22 }];
  const SEAT_SLOTS = [{ col: 24, row: 19 }, { col: 26, row: 19 }];
  const PORCH = { x0: 11, x1: 20, row0: 22, row1: 23 };
  const CHARACTER_SHEETS = {
    son: "/assets/pixel-agents/characters/char_0.png",
    amma: "/assets/pixel-agents/characters/char_1.png",
    papa: "/assets/pixel-agents/characters/char_3.png",
  };
  const tileKey = (col, row) => `${col},${row}`;
  const walkable = new Set();
  for (const room of ROOMS) for (let row = room.y + 1; row < room.y + room.h - 1; row++) for (let col = room.x + 1; col < room.x + room.w - 1; col++) walkable.add(tileKey(col, row));
  for (let col = 1; col < COLS - 1; col++) walkable.add(tileKey(col, 11));
  for (let row = 1; row < ROWS - 1; row++) { walkable.add(tileKey(15, row)); walkable.add(tileKey(16, row)); }
  for (let col = PORCH.x0; col <= PORCH.x1; col++) for (let row = PORCH.row0; row <= PORCH.row1; row++) walkable.add(tileKey(col, row));
  for (const doorway of DOOR_PATHS) for (const tile of doorway) walkable.add(tileKey(tile.col, tile.row));

  function findPath(start, end) {
    if (start.col === end.col && start.row === end.row) return [];
    const queue = [start], visited = new Set([tileKey(start.col, start.row)]), parent = new Map();
    const steps = [{ col: 0, row: -1 }, { col: 0, row: 1 }, { col: -1, row: 0 }, { col: 1, row: 0 }];
    while (queue.length) {
      const current = queue.shift();
      if (current.col === end.col && current.row === end.row) {
        const path = [];
        for (let here = tileKey(end.col, end.row); here !== tileKey(start.col, start.row); here = parent.get(here)) {
          const [col, row] = here.split(",").map(Number); path.unshift({ col, row });
        }
        return path;
      }
      for (const step of steps) {
        const next = { col: current.col + step.col, row: current.row + step.row }, nextKey = tileKey(next.col, next.row);
        if (!visited.has(nextKey) && walkable.has(nextKey)) { visited.add(nextKey); parent.set(nextKey, tileKey(current.col, current.row)); queue.push(next); }
      }
    }
    return [];
  }

  class PixelHouse {
    constructor(canvas) {
      this.canvas = canvas; this.ctx = canvas.getContext("2d"); this.ctx.imageSmoothingEnabled = false;
      this.people = new Map(); this.sheets = new Map(); this.lastFrame = performance.now();
      this.scene = {}; this.tvOn = false; this.lights = {}; this.lastStates = null; this.lastRoster = null;
      Object.entries(CHARACTER_SHEETS).forEach(([id, source]) => {
        const image = new Image(); image.src = source; image.onload = () => this.sheets.set(id, image);
      });
      requestAnimationFrame((now) => this.frame(now));
    }

    sync(states, roster) {
      this.lastStates = states; this.lastRoster = roster;
      const occupantsByRoom = new Map();
      for (const [id, state] of Object.entries(states)) {
        if (id === "housebot") continue;
        if (state.room === "away") continue;
        const occupants = occupantsByRoom.get(state.room) || [];
        occupants.push(id);
        occupantsByRoom.set(state.room, occupants);
      }
      for (const occupants of occupantsByRoom.values()) occupants.sort();

      for (const [id, state] of Object.entries(states)) {
        const base = TARGETS[state.room] || TARGETS.away;
        const occupants = occupantsByRoom.get(state.room) || [];
        const slot = id === "housebot"
          ? { col: 4, row: 2 }
          : (ROOM_SLOT_OFFSETS[Math.max(occupants.indexOf(id), 0)] || ROOM_SLOT_OFFSETS[0]);
        let target = state.room === "away"
          ? base
          : { col: base.col + slot.col, row: base.row + slot.row };
        // An activity (ride, TV, massage, delivery) overrides the room spot with its own place.
        const spot = this.spotFor(id);
        if (spot) target = spot;
        let actor = this.people.get(id);
        if (!actor) {
          actor = { id, col: target.col, row: target.row, x: target.col, y: target.row, path: [], room: state.room, targetCol: target.col, targetRow: target.row, status: state.status, color: roster[id].color, label: roster[id].label, frame: 0, clock: 0, offset: [...id].reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % 18, pose: "wait" };
          this.people.set(id, actor);
        }
        actor.status = state.status; actor.color = roster[id].color; actor.label = roster[id].label;
        actor.bubble = this.scene[id]?.bubble || null;
        // Someone who has gone out through the door is not drawn once they have arrived outside.
        actor.gone = this.scene[id]?.spot === "street";
        if (actor.room !== state.room || actor.targetCol !== target.col || actor.targetRow !== target.row) {
          actor.room = state.room;
          actor.targetCol = target.col;
          actor.targetRow = target.row;
          if (state.room === "away") { actor.path = []; actor.x = -3; actor.y = 11; actor.col = -3; actor.row = 11; continue; }
          const start = { col: Math.round(actor.x), row: Math.round(actor.y) };
          if (!walkable.has(tileKey(start.col, start.row))) {
            // A person entering from "away" has no on-map starting tile, so
            // they appear at the destination. All room-to-room moves use BFS.
            actor.x = target.col; actor.y = target.row; actor.col = target.col; actor.row = target.row;
            actor.path = [];
          } else {
            actor.path = findPath(start, target);
          }
        }
      }
    }

    frame(now) { const dt = Math.min((now - this.lastFrame) / 1000, .1); this.lastFrame = now; this.update(dt); this.draw(); requestAnimationFrame((time) => this.frame(time)); }
    update(dt) {
      for (const actor of this.people.values()) {
        actor.clock = (actor.clock || 0) + dt;
        if (!actor.path.length) { actor.pose = this.poseFor(actor); continue; }
        actor.pose = "walk";
        const target = actor.path[0], speed = 5.7, dx = target.col - actor.x, dy = target.row - actor.y, distance = Math.hypot(dx, dy), amount = speed * dt;
        actor.frame += dt * 10;
        if (distance <= amount) { actor.x = target.col; actor.y = target.row; actor.col = target.col; actor.row = target.row; actor.path.shift(); }
        else { actor.x += dx / distance * amount; actor.y += dy / distance * amount; }
      }
    }

    // Standing still, a person is reading, waiting or staring. An activity sets the pose; with none,
    // people rotate through the three every few seconds, each starting at a different point.
    poseFor(actor) {
      const task = this.scene[actor.id];
      if (task?.spot === "tv_seat") return "stare";
      if (task) return "wait";
      const step = Math.floor((actor.clock + actor.offset) / 6) % 3;
      return ["read", "wait", "stare"][step];
    }

    draw() {
      const c = this.ctx; c.clearRect(0, 0, this.canvas.width, this.canvas.height); c.fillStyle = "#131c29"; c.fillRect(0, 0, this.canvas.width, this.canvas.height);
      this.drawPorch(c); this.drawHallways(c); ROOMS.forEach((room) => this.drawRoom(c, room)); this.drawDoors(c); this.drawFurniture(c); this.drawLights(c); this.drawTv(c);
      [...this.people.values()].filter((person) => person.room !== "away" && (!person.gone || person.path.length > 0)).sort((a, b) => a.y - b.y).forEach((person) => this.drawPerson(c, person));
      this.drawBubbles(c);
    }

    drawHallways(c) {
      c.fillStyle = "#1d2938"; c.fillRect(0, 11 * TILE, COLS * TILE, TILE); c.fillRect(15 * TILE, 0, 2 * TILE, ROWS * TILE);
      c.fillStyle = "#080d13"; c.fillRect(0, 11 * TILE, COLS * TILE, 2); c.fillRect(0, 12 * TILE - 2, COLS * TILE, 2); c.fillRect(15 * TILE, 0, 2, ROWS * TILE); c.fillRect(17 * TILE - 2, 0, 2, ROWS * TILE);
    }

    drawRoom(c, room) {
      const x = room.x * TILE, y = room.y * TILE, width = room.w * TILE, height = room.h * TILE;
      c.fillStyle = "#070b10"; c.fillRect(x - 3, y - 3, width + 6, height + 6);
      for (let row = 0; row < room.h; row++) for (let col = 0; col < room.w; col++) {
        const tx = x + col * TILE, ty = y + row * TILE;
        if (room.floor === "tile") { c.fillStyle = (col + row) % 2 ? "#303941" : "#d9dcdf"; }
        else if (room.floor === "blue") c.fillStyle = (col + row) % 2 ? "#3b668a" : "#46749a";
        else c.fillStyle = row % 2 ? "#6b381c" : "#804622";
        c.fillRect(tx, ty, TILE, TILE);
        if (room.floor === "wood") { c.fillStyle = "#4f2816"; c.fillRect(tx, ty + 13, TILE, 2); }
      }
      c.fillStyle = "#0c131c"; c.fillRect(x, y, width, 6); c.fillStyle = "#e2e9f0"; c.font = "bold 8px monospace"; c.fillText(room.label, x + 8, y + 14);
    }

    drawDoors(c) {
      for (const doorway of DOOR_PATHS) {
        const first = doorway[0], second = doorway[1];
        const horizontal = first.row === second.row;
        const x = Math.min(first.col, second.col) * TILE;
        const y = Math.min(first.row, second.row) * TILE;
        const width = horizontal ? TILE * 2 : TILE;
        const height = horizontal ? TILE : TILE * 2;
        c.fillStyle = "#0a0e14"; c.fillRect(x - 1, y - 1, width + 2, height + 2);
        c.fillStyle = "#a9784b"; c.fillRect(x + 2, y + 2, width - 4, height - 4);
        c.fillStyle = "#d2a56b";
        if (horizontal) c.fillRect(x + width / 2 - 1, y + 3, 2, height - 6);
        else c.fillRect(x + 3, y + height / 2 - 1, width - 6, 2);
      }
    }

    block(c, x, y, w, h, fill, edge = "#19212b") { c.fillStyle = edge; c.fillRect(x, y, w, h); c.fillStyle = fill; c.fillRect(x + 3, y + 3, w - 6, h - 6); }
    plant(c, x, y) { this.block(c, x, y + 18, 17, 14, "#a47a48"); c.fillStyle = "#286446"; c.fillRect(x + 6, y, 5, 22); c.fillRect(x + 1, y + 7, 5, 11); c.fillRect(x + 12, y + 5, 4, 13); }
    drawFurniture(c) {
      this.block(c, 27, 48, 65, 19, "#b34169"); this.block(c, 43, 75, 38, 22, "#c08e55"); this.block(c, 145, 31, 51, 22, "#64334a"); this.plant(c, 29, 20);
      this.block(c, 338, 43, 42, 47, "#dbe0e4"); this.block(c, 398, 74, 69, 24, "#b98752"); this.block(c, 433, 37, 44, 23, "#d6dce1"); this.plant(c, 472, 21);
      this.block(c, 38, 256, 79, 45, "#7499b4"); this.block(c, 42, 227, 54, 23, "#bb8955"); this.block(c, 61, 231, 23, 15, "#1c2d37"); this.block(c, 126, 271, 21, 24, "#9f7044");
      this.block(c, 373, 242, 73, 41, "#0c1218"); this.block(c, 382, 286, 58, 17, "#a9784b"); this.block(c, 305, 274, 38, 39, "#b34169"); this.block(c, 340, 309, 42, 19, "#c08e55"); this.plant(c, 468, 230);
    }

    drawPerson(c, person) {
      const x = Math.round(person.x * TILE + TILE / 2), y = Math.round(person.y * TILE + TILE / 2), walking = person.path.length > 0;
      // Sprite sheet: 7 frames of 16px across (0-2 walk, 1 stand, 5-6 read), 3 facing rows (0 down, 1 up, 2 side).
      const breathing = person.pose === "wait" ? Math.round(Math.sin(person.clock * 2.5) * .8) : 0;
      const bob = walking ? Math.round(Math.sin(person.frame) * 1.5) : breathing;
      if (person.id === "housebot") {
        this.drawRobot(c, person, x, y, bob);
        return;
      }
      const sheet = this.sheets.get(person.id);
      if (sheet) {
        const next = person.path[0], dx = next ? next.col - person.x : 0, dy = next ? next.row - person.y : 1;
        let row = 0, frame = 1;
        if (walking) {
          row = Math.abs(dx) > Math.abs(dy) ? 2 : dy < 0 ? 1 : 0;
          frame = [0, 1, 2, 1][Math.floor(person.frame) % 4];
        } else if (person.pose === "read") {
          // Head down over a book: the two reading frames flip slowly.
          frame = 5 + Math.floor(person.clock / .8) % 2;
        } else if (person.pose === "stare") {
          // Facing away, toward the TV or the wall.
          row = 1;
        }
        c.drawImage(sheet, frame * 16, row * 32, 16, 32, x - 16, y - 32 + bob, 32, 64);
      } else {
      c.fillStyle = "#0a0e14"; c.fillRect(x - 7, y + 8 + bob, 5, 7); c.fillRect(x + 2, y + 8 - bob, 5, 7);
      c.fillStyle = "#f0c5a4"; c.fillRect(x - 5, y - 10 + bob, 11, 10); c.fillStyle = "#25272f"; c.fillRect(x - 6, y - 13 + bob, 12, 5); c.fillRect(x - 7, y - 9 + bob, 3, 5);
      c.fillStyle = person.color; c.fillRect(x - 7, y + bob, 14, 11); c.fillRect(x - 10, y + 3 + bob, 4, 6); c.fillRect(x + 7, y + 3 + bob, 4, 6);
      }
      c.fillStyle = person.status === "alert" ? "#e85e58" : person.status === "busy" ? "#65db83" : person.status === "walking" ? "#e9c46a" : "#9d7bd8"; c.fillRect(x + 8, y - 15, 5, 5);
      c.fillStyle = "#070b10"; c.font = "bold 7px monospace"; const width = c.measureText(person.label.toUpperCase()).width; c.fillText(person.label.toUpperCase(), x - width / 2 + 1, y + 25); c.fillStyle = "#f3f6f8"; c.fillText(person.label.toUpperCase(), x - width / 2, y + 24);
    }

    // Activities from the server: { person: { kind, spot, bubble, stage } }. Lights and TV from the house state.
    setScene(scene, environment = {}) {
      this.scene = scene || {};
      this.tvOn = !!environment.tvOn;
      this.lights = environment.lights || {};
      if (this.lastStates) this.sync(this.lastStates, this.lastRoster);
    }

    spotFor(id) {
      const task = this.scene[id];
      if (!task) return null;
      if (task.spot === "front_door") {
        const waiting = Object.keys(this.scene).filter((other) => this.scene[other].spot === "front_door").sort();
        return DOOR_SLOTS[Math.min(waiting.indexOf(id), DOOR_SLOTS.length - 1)];
      }
      if (task.spot === "tv_seat") {
        const seated = Object.keys(this.scene).filter((other) => this.scene[other].spot === "tv_seat").sort();
        return SEAT_SLOTS[Math.min(seated.indexOf(id), SEAT_SLOTS.length - 1)];
      }
      if (task.spot === "street") return { col: 20, row: 23 };
      if (task.spot.startsWith("beside:")) {
        const other = this.people.get(task.spot.slice("beside:".length));
        if (!other) return null;
        const col = Math.round(other.targetCol ?? other.col), row = Math.round(other.targetRow ?? other.row);
        // Two tiles away, so a 2-tile-wide sprite does not stand on top of the person.
        const options = [{ col: col + 2, row }, { col: col - 2, row }, { col: col + 2, row: row + 1 }, { col, row: row - 1 }];
        return options.find((tile) => walkable.has(tileKey(tile.col, tile.row))) || null;
      }
      return null;
    }

    drawPorch(c) {
      c.fillStyle = "#1c3a2a"; c.fillRect(0, (PORCH.row0) * TILE, COLS * TILE, (PORCH.row1 - PORCH.row0 + 1) * TILE);
      c.fillStyle = "#3b4149"; c.fillRect(PORCH.x0 * TILE, PORCH.row0 * TILE, (PORCH.x1 - PORCH.x0 + 1) * TILE, (PORCH.row1 - PORCH.row0 + 1) * TILE);
      c.fillStyle = "#e2e9f0"; c.font = "bold 8px monospace"; c.fillText("FRONT DOOR", 11 * TILE, 23 * TILE + 10);
    }

    drawLights(c) {
      for (const room of ROOMS) {
        if (this.lights[room.id] === false) {
          c.fillStyle = "rgba(0, 0, 0, 0.42)";
          c.fillRect(room.x * TILE, room.y * TILE, room.w * TILE, room.h * TILE);
        }
      }
      if (this.tvOn) {
        const tvRoom = ROOMS.find((room) => room.id === "tv_room");
        c.fillStyle = "rgba(70, 120, 255, 0.10)";
        c.fillRect(tvRoom.x * TILE, tvRoom.y * TILE, tvRoom.w * TILE, tvRoom.h * TILE);
      }
    }

    // A blurred, moving colour screen when the TV is on; the off screen stays dark.
    drawTv(c) {
      if (!this.tvOn) return;
      const x = 376, y = 245, w = 67, h = 35, t = performance.now() / 1000;
      const gradient = c.createLinearGradient(x, y, x + w, y + h);
      gradient.addColorStop(0, `hsl(${(200 + 40 * Math.sin(t * 0.6)).toFixed(0)}, 70%, 45%)`);
      gradient.addColorStop(0.5, `hsl(${(260 + 30 * Math.sin(t * 0.4 + 1)).toFixed(0)}, 60%, 40%)`);
      gradient.addColorStop(1, `hsl(${(170 + 25 * Math.sin(t * 0.5 + 2)).toFixed(0)}, 65%, 42%)`);
      c.fillStyle = gradient; c.fillRect(x, y, w, h);
      c.fillStyle = "rgba(255, 255, 255, 0.10)"; c.fillRect(x + ((t * 18) % (w + 20)) - 10, y, 6, h);
      c.fillStyle = "rgba(120, 170, 255, 0.22)"; c.fillRect(x - 4, y - 4, w + 8, h + 8);
    }

    drawBubbles(c) {
      for (const person of this.people.values()) {
        if (!person.bubble || person.room === "away" || (person.gone && person.path.length === 0)) continue;
        // The robot's note sits higher so it never covers the person it is helping.
        const x = Math.round(person.x * TILE + TILE / 2), y = Math.round(person.y * TILE + TILE / 2) - (person.id === "housebot" ? 66 : 40);
        c.font = "bold 8px monospace";
        const width = Math.min(c.measureText(person.bubble).width + 12, 320);
        c.fillStyle = "#f4f7fb"; c.fillRect(x - width / 2, y - 11, width, 14);
        c.fillStyle = "#15202e"; c.fillText(person.bubble, x - width / 2 + 6, y - 1);
      }
    }

    // Test and debug hook: where every person stands and what they are doing.
    positions() {
      const out = {};
      for (const [id, actor] of this.people) {
        out[id] = { room: actor.room, col: Math.round(actor.x), row: Math.round(actor.y), target: { col: actor.targetCol, row: actor.targetRow }, moving: actor.path.length > 0, bubble: actor.bubble || null };
      }
      return out;
    }

    drawRobot(c, robot, x, y, bob) {
      c.fillStyle = "#081018"; c.fillRect(x - 12, y - 15 + bob, 24, 25);
      c.fillStyle = "#9de5ff"; c.fillRect(x - 9, y - 12 + bob, 18, 16);
      c.fillStyle = "#273a4d"; c.fillRect(x - 6, y - 9 + bob, 12, 7);
      c.fillStyle = robot.status === "busy" ? "#65db83" : "#65c7ee"; c.fillRect(x - 3, y - 7 + bob, 6, 3);
      c.fillStyle = "#33475b"; c.fillRect(x - 10, y + 5 + bob, 20, 5);
      c.fillStyle = "#0a0e14"; c.fillRect(x - 8, y + 10 + bob, 5, 4); c.fillRect(x + 3, y + 10 + bob, 5, 4);
      c.fillStyle = "#65db83"; c.fillRect(x + 9, y - 15, 5, 5);
      c.fillStyle = "#070b10"; c.font = "bold 7px monospace"; const width = c.measureText(robot.label.toUpperCase()).width; c.fillText(robot.label.toUpperCase(), x - width / 2 + 1, y + 25); c.fillStyle = "#f3f6f8"; c.fillText(robot.label.toUpperCase(), x - width / 2, y + 24);
    }
  }
  window.pixelHouse = new PixelHouse(document.querySelector("#pixel-house"));
})();
