# Wargame Simulation Framework

## Project Overview

Multi-agent wargaming framework simulating a 4-day conventional military conflict between India and Pakistan. Features full-spectrum warfare including missiles, air force, air defense, drones (including swarm operations), helicopters, artillery, ground forces, special forces, electronic warfare (jamming/cyber/SIGINT/GPS denial), and logistics. LLM-based strategic agents (GPT-4o) command each side.

## Scenario Parameters

- **Theater**: Full India-Pakistan land border (LOC Kashmir to Rajasthan), no naval
- **Duration**: 4 days (16 turns at 6-hour intervals)
- **Start State**: Hot start - forces mobilized, conflict begins turn 1
- **Escalation**: Conventional only, no nuclear
- **Forces**: 93 units total (48 India, 45 Pakistan) across all domains

## Project Structure

```
wargame/
├── data/
│   ├── schema/              # 18 YAML schema definitions
│   │   ├── aircraft.yaml, airbases.yaml, squadrons.yaml
│   │   ├── missiles.yaml, air_defense.yaml, drones.yaml
│   │   ├── helicopters.yaml, artillery.yaml, ground_forces.yaml
│   │   ├── special_forces.yaml, electronic_warfare.yaml, isr.yaml
│   │   ├── awacs.yaml, loadouts.yaml, command_control.yaml
│   │   ├── logistics.yaml, map.yaml, scenario.yaml
│   ├── india/               # 10 India OOB files (including loadouts)
│   ├── pakistan/             # 10 Pakistan OOB files (including loadouts)
│   ├── map/                 # Terrain and location data
│   │   └── terrain.yaml
│   └── scenarios/
│       └── hot_start_4day.yaml   # Main scenario (deployments, weather, VP conditions)
├── engine/                  # Core simulation engine
│   ├── map.py               # Hex grid (10km), terrain, movement, LOS
│   ├── units.py             # Unit state management, OOB loading
│   ├── turn.py              # Turn sequencing, phase orchestration (~1350 LOC)
│   ├── logistics.py         # Supply nodes, routes, consumption, attrition
│   ├── fog_of_war.py        # Intel reports, detection, sensor coverage
│   └── combat/              # 8 domain-specific combat resolvers
│       ├── base.py          # CombatResolver base class, hit/damage calcs
│       ├── missiles.py      # Cruise/ballistic, BMD intercept, accuracy
│       ├── air.py           # BVR/WVR combat, SEAD, air-to-ground
│       ├── drones.py        # Swarm ops (YAML-driven), ISR, loitering munitions
│       ├── artillery.py     # Direct/area fire, counter-battery
│       ├── helicopters.py   # Attack helo, CAS, air assault, scout
│       ├── ground.py        # Lanchester model, terrain/urban modifiers
│       ├── ew.py            # Radar/comms jam, cyber, SIGINT, GPS denial
│       └── special_forces.py # Raids, recon, sabotage, DA, SR missions
├── agents/                  # LLM-based strategic agents
│   ├── base.py              # Abstract StrategicAgent, orders schema, OpenAI integration
│   ├── india.py             # India agent - Cold Start doctrine, system prompt
│   └── pakistan.py           # Pakistan agent - defensive attrition doctrine
├── game.py                  # Main game loop & orchestration
├── battle_log.py            # Live console battle logging
├── replay_export.py         # Self-contained HTML replay generator (~75KB)
├── gen_test_replay.py       # Scripted 16-turn narrative replay generator
├── test_engine.py           # Engine test (loads real data, runs 1 turn with LLM)
├── show_turn1.py            # Debug script for turn 1 state inspection
├── requirements.txt         # Python dependencies
├── .env                     # OPENAI_API_KEY
├── tasks.md                 # Original task tracker (historical)
└── pending_tasks            # Feature backlog
```

## Tech Stack

- **Engine**: Python 3.11+
- **Agents**: OpenAI API (GPT-4o via structured outputs / json_schema mode)
- **Data**: YAML for human-editable configs, JSON at runtime
- **Visualization**: Self-contained HTML replay (Leaflet maps, CSS animations, Web Audio SFX)
- **Dependencies**: openai, pyyaml, python-dotenv

## Turn Sequence

Each turn (6 hours game time) resolves in this order:

1. **Intel Phase**: ISR updates, AWACS positioning, fog of war refresh
2. **Missile Phase**: Launch decisions, BMD intercepts, damage assessment
3. **EW Phase**: Jamming, cyber attacks, SIGINT collection, GPS denial
4. **Air Phase**: CAP/OCA/CAS/SEAD/Interdiction, air combat (AWACS bonuses applied), strikes
5. **Drone Phase**: ISR orbits, armed strikes, SEAD swarms (YAML-driven saturation mechanics)
6. **Artillery Phase**: Fire missions, counter-battery
7. **Helicopter Phase**: Attack helo CAS, air assault, scout
8. **Ground Phase**: Movement, ground combat resolution
9. **SF Phase**: Special operations (recon, sabotage, raids)
10. **Logistics Phase**: Supply consumption, reinforcement, repair

## Agent Design

Each strategic agent receives:
- Current visible game state (fog of war applied)
- Own force status (units, ammo, fuel, damage)
- Known enemy positions and strength estimates
- Strategic objectives and priorities
- Previous turn results and reasoning history

Each agent outputs structured JSON orders covering:
- Missile targets, air missions, drone tasking, artillery fire plans
- Ground movement, helicopter missions, SF operations, EW allocation
- Priority allocations and reasoning log

**India doctrine**: Air superiority first, offensive Cold Start with shallow thrusts (50-80km), non-contact warfare priority (BrahMos/SCALP), combined arms coordination

**Pakistan doctrine**: Defense-in-depth, force preservation for counterattack, drone swarm saturation, asymmetric options, Lahore defense as hard constraint

## Combat Resolution

- **Missiles**: Accuracy vs target hardness, BMD intercept probability
- **Air-to-Air**: BVR detection (radar vs stealth), AWACS cooperative engagement bonus (1.5x radar when available, degraded by EW), WVR dogfight
- **Air-to-Ground**: Strike effectiveness vs target type and air defense umbrella
- **Drones/Swarms**: YAML-driven saturation mechanics - per-system Pk and intercept capacity from drones.yaml
- **Ground**: Modified Lanchester model with terrain/fortification/urban factors
- **Artillery**: Area effect, counter-battery duels
- **EW**: Type-dispatched (jam_radar, jam_comms, cyber, sigint, gps_denial) with cascading effects on other phases
- **Helicopters**: Attack CAS, air assault with LZ mechanics
- **Special Forces**: Mission-type resolution (recon, sabotage, raid, DA, SR)

## Key Platforms

**India**: Rafale, Su-30MKI, MiG-29, Mirage 2000, Tejas, Apache, LCH, Heron, Harop, MQ-9B, S-400, Phalcon/Netra AWACS, BrahMos, Para SF
**Pakistan**: JF-17, F-16, J-10C, Mirage III/V, AH-1Z, Z-10, TB2, Akinci, Yihaa-III swarms, HQ-9, Erieye/ZDK-03 AWACS, Babur, SSG

## Replay Visualization

The replay system (`replay_export.py`) generates a self-contained HTML file with:
- Leaflet map with unit positions and terrain
- Phase-by-phase animated combat events (missile trails, air engagements, drone swarms, helicopter rotors, SF infiltration pings, artillery impacts, ground advances)
- Web Audio API sound effects per event type
- Turn timeline with scrubber and auto-play
- Narrative panel with per-faction summaries
- VP tracking and order breakdowns

Animation types: missile (arc + detonation), air (BVR/WVR flight paths), drone (swarm buzz + strike flash), artillery (barrage impacts), helicopter (rotor spin + strafe flash), SF (stealth ping + mission-specific effects), ground (advance arrows)

## Commands

```bash
# Run full simulation (requires OPENAI_API_KEY in .env)
python game.py --scenario hot_start_4day

# Run engine test (1 turn with real LLM agents)
python test_engine.py

# Generate scripted narrative replay (no LLM needed)
python gen_test_replay.py
# Opens: test_replay.html in current directory

# Debug turn 1 state
python show_turn1.py
```

## Known Gaps / TODO

### Wiring Issues
- `game.py:113` — Scenario initial deployments not applied from hot_start_4day.yaml (units load from OOB only)
- VP calculation not wired during game execution (schema defined but not tracked)

### Missing Features
- **Full game execution**: Never tested beyond 1 turn with real LLM agents
- **Weather effects**: Weather data exists for all 16 turns but not applied as combat modifiers
- **Naval combat**: Not in scope (no naval units or combat module)
- **API backend / live frontend**: Not implemented (HTML replay is the visualization)

### Data Gaps
- Turkish weapon definitions (MAM-L, MAM-C, SOM, TEBER, Cirit) not in loadouts
- Operation Sindoor-specific scenario variants not created
- No data validation/collector scripts

## Key Design Principles

1. **Modularity**: Each combat domain is independent, can be tested separately
2. **Data-Driven**: Unit stats, terrain effects, swarm mechanics in YAML configs, not hardcoded
3. **Observable**: Every decision and resolution logged for replay/analysis
4. **Balanced**: Realistic asymmetry, not perfect balance
5. **Extensible**: Easy to add new unit types, domains, or scenarios
