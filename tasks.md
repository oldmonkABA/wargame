# Wargame Simulation - Task Tracker

## Project Overview
Multi-agent wargaming framework simulating a 4-day conventional military conflict between India and Pakistan.

**Scope:** Missiles → EW/Cyber → Air → Drones → Artillery → Helicopters → Ground + SF + Logistics

---

## Completed Tasks

### ✅ Task #1: Define data schema for all military assets
- Created 16 schema files in `data/schema/`
- Covers: aircraft, airbases, squadrons, missiles, air_defense, drones, helicopters, artillery, ground_forces, special_forces, command_control, logistics, electronic_warfare, isr, map, scenario

### ✅ Task #2: Collect India Order of Battle data
- Created 9 data files in `data/india/`
- Airbases (17 bases, ~200 aircraft including Rafale, Su-30MKI, MiG-29)
- Missiles (BrahMos, Nirbhay, Pralay, Prithvi-II)
- Air Defense (S-400, Akash, SPYDER, MRSAM)
- Drones (Heron, Harop, MQ-9)
- Helicopters (Apache, Rudra, LCH, Chinook)
- Artillery (Pinaka, Smerch, K9 Vajra, M777, Dhanush)
- Ground Forces (2 strike corps, 7 holding corps)
- Special Forces (Para SF, Garud, MARCOS)
- ISR (Phalcon, Netra AWACS, satellites)

### ✅ Task #3: Collect Pakistan Order of Battle data
- Created 9 data files in `data/pakistan/`
- Airbases (14 bases, ~180 aircraft including JF-17, F-16, J-10C)
- Missiles (Babur, Ra'ad, Ghaznavi, Shaheen)
- Air Defense (HQ-9, HQ-16, Spada, FM-90)
- Drones (Burraq, Shahpar, Wing Loong II)
- Helicopters (Cobra, T129, Z-10)
- Artillery (A-100, SH-15, M109, M198)
- Ground Forces (2 strike corps, 7+ holding corps)
- Special Forces (SSG, SSGN, Zarrar)
- ISR (Erieye, ZDK-03 AWACS)

### ✅ Task #4: Collect map and terrain data
- Created `data/map/terrain.yaml`
- Terrain sectors (Kashmir LOC, Jammu, Punjab North/Central/South, Thar, Sindh)
- Major rivers (Indus, Jhelum, Chenab, Ravi, Beas, Sutlej) with crossing points
- 15+ major cities with coordinates
- Strategic chokepoints and passes
- Line of Control path

---

## Pending Tasks

### 🔲 Task #5: Build data collector scripts
**Blocked by:** Nothing (can start anytime)
**Description:** Create Python scripts to help gather and structure OOB data. Validation scripts to check schema compliance.

### 🔲 Task #6: Build core simulation engine
**Blocked by:** Nothing (data complete)
**Description:** Core wargame engine:
- Map/terrain system with hex grid
- Unit state management
- Turn sequencing (16 turns x 6hr = 4 days)
- Phase ordering (missiles → EW → air → drones → artillery → helicopters → ground → SF → logistics)
- Combat resolution models for each domain
- Damage, attrition, supply consumption
- Fog of war / visibility rules

**Files to create:**
```
engine/
├── map.py           # Terrain, movement, LOS
├── units.py         # Unit state management
├── combat/
│   ├── missiles.py
│   ├── air.py
│   ├── ground.py
│   ├── artillery.py
│   ├── helicopters.py
│   ├── drones.py
│   ├── ew.py
│   └── special_forces.py
├── logistics.py     # Supply and attrition
├── fog_of_war.py    # Information/visibility
└── turn.py          # Turn sequencing
```

### 🔲 Task #7: Build India strategic agent
**Blocked by:** Task #6
**Description:** LLM-based agent representing Indian military command.
- Receives: current state, available units, objectives
- Outputs: orders for all domains
- Implements Indian doctrine (air superiority first, offensive conventional)

### 🔲 Task #8: Build Pakistan strategic agent
**Blocked by:** Task #6
**Description:** LLM-based agent representing Pakistani military command.
- Receives: current state, available units, objectives
- Outputs: orders for all domains
- Implements Pakistani doctrine (defensive depth, counter-attack focus)

### 🔲 Task #9: Build agent orchestration system
**Blocked by:** Tasks #6, #7, #8
**Description:** System to run the wargame:
- Initialize scenario
- Alternate turns between agents
- Feed state to each agent, collect orders
- Execute via simulation engine
- Resolve combat, update state
- Log everything for replay

### 🔲 Task #10: Build visualization frontend
**Blocked by:** Task #6
**Description:** Web-based visualization:
- Map of India-Pakistan border with terrain
- Unit icons by type/faction
- Movement arrows, engagement markers
- SAM coverage circles, airbase status
- Turn-by-turn playback with timeline scrubber
- Agent reasoning panel
- Tech: React + TypeScript + Vite + Canvas/SVG

### 🔲 Task #11: Build backend API for visualization
**Blocked by:** Task #6
**Description:** Backend API:
- REST or WebSocket endpoints
- Current state, turn history, unit details
- Agent reasoning logs
- Support live and replay modes

### 🔲 Task #12: Create scenario configuration
**Blocked by:** Tasks #2, #3, #4 (COMPLETE)
**Description:** Define the specific scenario:
- "4-Day Hot Start" - forces mobilized, shooting begins turn 1
- Objectives for each side
- Victory conditions
- Agent behavior parameters
- Initial unit positions

---

## File Structure Created

```
wargame/
├── claude.md                    # Project documentation
├── tasks.md                     # This file
├── data/
│   ├── schema/                  # 16 schema files
│   │   ├── aircraft.yaml
│   │   ├── airbases.yaml
│   │   ├── squadrons.yaml
│   │   ├── missiles.yaml
│   │   ├── air_defense.yaml
│   │   ├── drones.yaml
│   │   ├── helicopters.yaml
│   │   ├── artillery.yaml
│   │   ├── ground_forces.yaml
│   │   ├── special_forces.yaml
│   │   ├── command_control.yaml
│   │   ├── logistics.yaml
│   │   ├── electronic_warfare.yaml
│   │   ├── isr.yaml
│   │   ├── map.yaml
│   │   └── scenario.yaml
│   ├── india/                   # 9 OOB files
│   │   ├── airbases.yaml
│   │   ├── missiles.yaml
│   │   ├── air_defense.yaml
│   │   ├── drones.yaml
│   │   ├── helicopters.yaml
│   │   ├── artillery.yaml
│   │   ├── ground_forces.yaml
│   │   ├── special_forces.yaml
│   │   └── isr.yaml
│   ├── pakistan/                # 9 OOB files
│   │   ├── airbases.yaml
│   │   ├── missiles.yaml
│   │   ├── air_defense.yaml
│   │   ├── drones.yaml
│   │   ├── helicopters.yaml
│   │   ├── artillery.yaml
│   │   ├── ground_forces.yaml
│   │   ├── special_forces.yaml
│   │   └── isr.yaml
│   └── map/
│       └── terrain.yaml
```

---

## Next Steps (when resuming)

1. **Task #6: Build core simulation engine** - This is the foundation
   - Start with `engine/map.py` (hex grid, terrain)
   - Then `engine/units.py` (unit state)
   - Then combat resolution modules
   - Then `engine/turn.py` (orchestrate phases)

2. **Task #12: Create scenario config** - Can be done in parallel
   - Define initial positions
   - Set objectives and victory conditions

3. **Tasks #7, #8: Build agents** - After engine works
   - Design agent prompts
   - Implement decision-making loop

4. **Tasks #10, #11: Visualization** - Can start after engine basics work
   - Frontend for visual feedback
   - API to serve game state

---

## Stats
- **Total YAML files:** 35
- **Total lines of data:** 8,200+
- **Completed tasks:** 4/12
- **Pending tasks:** 8/12
