# Wargame — Full Game Architecture Ideas

## Goal

Turn the simulation into a playable game supporting three modes:
- **AI vs AI**: Fully automated, watch replay (current mode)
- **Human vs AI**: Human gives orders via browser UI, AI responds
- **Human vs Human**: Both submit orders via browser UI, simultaneous resolution

All three modes funnel through the same engine — the only difference is where the orders come from.

## What We Already Have (Reusable)

- **Engine** — turn-based, phase-resolved, takes orders as JSON blob, returns results. Core doesn't need to change much.
- **Agent interface** — `base.py` defines clean contract: game state in, orders JSON out. A human player just needs a UI that produces the same JSON.
- **Replay viewer** — rich Leaflet map, CSS animations, Web Audio SFX, unit rendering, turn timeline. Can evolve into game client rather than building from scratch.

## Architecture Options

### Option A: Full Web App (FastAPI + React)
- Dedicated React frontend with order-building UI
- WebSocket server for real-time state
- Most polished, most work (~2-3 weeks)
- Shareable — host it and anyone can play

### Option B: Extend Replay Viewer into Game Client (Recommended)
- Existing 190KB HTML already has maps, animations, unit rendering
- Add orders panel (clickable units, drag missions, submit button)
- Thin WebSocket connection to Python game server
- Leverages 90% of existing visualization code
- Less work, single HTML file stays self-contained-ish

### Option C: Simple Web UI with Server-Rendered Pages
- Flask/FastAPI serving HTML pages
- Each turn: show map + state, form for orders, submit, see results
- No real-time, just request/response
- Simplest to build, least flashy
- Good enough for Human vs AI

## Recommended Architecture (Option B)

```
┌─────────────────────────────────────────────┐
│  Game Server (Python)                       │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐ │
│  │ Engine   │  │ AI Agent │  │ WebSocket │ │
│  │ (turn.py)│  │ (GPT-4o) │  │ Server    │ │
│  └──────────┘  └──────────┘  └───────────┘ │
│        ▲              ▲            ▲  │     │
│        └──────────────┴────────────┘  │     │
│              orders JSON              │     │
└───────────────────────────────────────┼─────┘
                                        │ WebSocket
┌───────────────────────────────────────┼─────┐
│  Browser Client (evolved replay.html) │     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ Leaflet  │  │ Orders   │  │ Anim     │  │
│  │ Map      │  │ Panel    │  │ Engine   │  │
│  └──────────┘  └──────────┘  └──────────┘  │
└─────────────────────────────────────────────┘
```

## Orders Panel — The Big New Piece

The human player needs to:

1. **See their units** — filtered by domain (air, ground, missiles, drones, heli, SF, EW)
2. **Assign missions** — click a unit, pick mission type, click target on map
3. **Review orders** — see all queued orders before submitting
4. **Submit turn** — send orders JSON, wait for opponent (AI or human)
5. **Watch resolution** — existing animation system plays back turn results
6. **Fog of war** — only see what your side knows

### Mission Assignment UX Per Domain

| Domain | Select | Assign | Target |
|--------|--------|--------|--------|
| Missiles | Pick launcher | Choose missile type | Click map target |
| Air | Pick squadron | Choose mission (CAP/OCA/CAS/SEAD) | Click patrol area or strike target |
| Drones | Pick drone unit | Choose mission (ISR/strike/SEAD swarm) | Click orbit area or target |
| Artillery | Pick battery | Choose fire mission | Click target hex |
| Helicopters | Pick heli unit | Choose mission (attack/air assault/scout) | Click target or LZ |
| Ground | Pick formation | Choose action (advance/defend/withdraw) | Click destination hex |
| SF | Pick SF unit | Choose mission (recon/sabotage/raid) | Click target area |
| EW | Pick EW asset | Choose type (jam/cyber/sigint/gps denial) | Click target or area |

## Turn Flow

### Human vs AI
```
1. Server sends game state to browser (fog-of-war filtered)
2. Human builds orders in the Orders Panel
3. Human clicks "Submit Turn"
4. Server receives human orders
5. Server calls AI agent for opponent orders
6. Engine resolves all phases
7. Server sends turn results + animations to browser
8. Browser plays combat animations
9. Goto 1
```

### Human vs Human
```
1. Server sends game state to both browsers (fog-of-war filtered per side)
2. Both humans build orders simultaneously
3. Both click "Submit Turn"
4. Server waits for both (with optional timer)
5. Engine resolves all phases
6. Server sends turn results to both
7. Both browsers play combat animations
8. Goto 1
```

### AI vs AI (existing mode, enhanced)
```
1. Server calls both AI agents
2. Engine resolves all phases
3. Server pushes turn results to spectator browser(s)
4. Browser plays combat animations
5. Goto 1 (with configurable delay between turns)
```

## Game Server Components

### WebSocket API

```
Client → Server:
  { type: "join", faction: "india"|"pakistan", mode: "human"|"ai" }
  { type: "orders", turn: N, orders: { ...orders JSON... } }
  { type: "ready" }  // spectator ready for next turn

Server → Client:
  { type: "state", turn: N, game_state: { ...fog-filtered state... } }
  { type: "waiting", message: "Waiting for opponent..." }
  { type: "resolution", turn: N, events: [...], animations: [...] }
  { type: "game_over", winner: "india"|"pakistan"|"draw", final_vp: {...} }
```

### Session/Lobby

- Create game: choose scenario, set player modes (human/AI per side)
- Join game: pick faction
- Spectate: watch AI vs AI or other players' game
- Optional: turn timer (e.g., 5 min per turn for human players)

## Implementation Order

### Phase 1: Localhost Human vs AI
1. WebSocket game server (FastAPI + websockets)
2. Serve the game client HTML
3. Orders panel UI (basic — dropdowns and map clicks)
4. Wire: human orders → engine → results → animation playback
5. AI opponent responds automatically

### Phase 2: Polish
6. Better orders UX (drag-and-drop, unit cards, mission previews)
7. Fog of war filtering in the client
8. Turn timer
9. Sound/visual feedback for order assignment

### Phase 3: Multiplayer
10. Lobby system (create/join game)
11. Human vs Human support
12. Spectator mode for AI vs AI
13. Optional: deploy to a server for remote play

## Battle Feed UX — War Room Aesthetic

The current replay shows events in a static narrative dialog box. No tension, no drama. Real war games stream status text with color coding and pacing.

### Design

```
┌─────────────────────────────────────────────────────────────┐
│                    MAP (full screen, dark theme)             │
│                                                             │
│              [animations play on map]                       │
│                                                             │
│         "2x JF-17 DESTROYED" ← floating combat text        │
│                        ↑ red glow, fades up                 │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  BATTLE FEED  (monospace, streams line by line)             │
│  ▸ MISSILE LAUNCH — BrahMos III from Suratgarh    [INDIA]  │
│  ▸ TARGET: Sargodha AB                                     │
│  ▸ BMD INTERCEPT — HQ-9 engaging...              [PAKISTAN] │
│  ▸ ✗ INTERCEPT FAILED                               [RED]  │
│  ▸ ⚡ IMPACT — 2x JF-17 destroyed on ground         [RED]  │
│  ▸ ─────────────────────────────────                        │
│  ▸ EW: Cyber attack on Pakistani C2              [AMBER]   │
│  ▸   Comms degraded 34%                          [AMBER]   │
│  ▸ ─────────────────────────────────                        │
│  ▸ AIR: 2x Rafale SEAD — Lahore corridor         [CYAN]   │
│  ▸   SPYDER site engaged... DESTROYED            [GREEN]   │
│  ▸   F-16 scramble — BVR engagement               [RED]    │
│  ▸   1x Rafale damaged, RTB                       [RED]    │
│  ▸ █                                    ← cursor blinks    │
└─────────────────────────────────────────────────────────────┘
```

### Color Scheme
- **Red** — damage, kills, failed intercepts, enemy strikes
- **Green** — successful defense, mission success, objectives taken
- **Amber/Yellow** — EW, intel, warnings, detection
- **Cyan/Blue** — air ops, drone launches, movement
- **White** — neutral status, phase headers
- **Orange** — artillery, explosions

### Streaming Mechanics
- Each line types out with 50-100ms delay (faster for less important events)
- Phase separators (dashed lines) with a slight pause to build tension
- Map animations play simultaneously as corresponding feed lines appear
- Sound per line: soft tick for each line, louder impact for kills, static buzz for EW

### Floating Combat Text (on map)
- Event results appear at the event's map location
- Rise upward and fade out over 2-3 seconds
- Color matches the feed line color
- Font size proportional to event importance (kill > damage > movement)

### Dark/CRT Aesthetic
- Dark background (#0a0a0a), subtle green/amber tint
- Monospace font (JetBrains Mono or similar)
- Optional subtle CRT scanline overlay
- Radar sweep animation on map background
- Grid lines on map with military-style coordinates

### Data Requirements
Each combat event needs a `feed_lines` array:
```json
{
  "phase": "missile_strike",
  "feed_lines": [
    { "text": "MISSILE LAUNCH — BrahMos III from Suratgarh", "color": "cyan", "sfx": "launch" },
    { "text": "TARGET: Sargodha AB", "color": "white" },
    { "text": "BMD INTERCEPT — HQ-9 engaging...", "color": "amber", "delay": 800 },
    { "text": "INTERCEPT FAILED", "color": "red", "sfx": "boom" },
    { "text": "IMPACT — 2x JF-17 destroyed on ground", "color": "red", "sfx": "explosion" }
  ]
}
```

Alternatively, generate feed_lines client-side from existing event data (no data format change needed).

## Open Questions

- **Turn timer**: Should human turns be timed? How long? (5 min suggested)
- **Partial orders**: Can a human skip domains? (e.g., submit with no SF orders)
- **Order validation**: Should the UI enforce valid orders or let the engine reject bad ones?
- **Replay save**: Auto-save every game as a replayable HTML file?
- **Difficulty levels**: Multiple AI personalities? (aggressive/defensive/balanced)
- **Undo**: Allow order changes before submit? (yes, obviously)
- **Chat**: Allow player-to-player chat? (flavor, not essential)
