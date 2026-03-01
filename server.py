"""
WebSocket game server for human vs AI wargame.

Serves game_client.html and manages game sessions over WebSocket.
"""

import os
import json
import yaml
import asyncio
import logging
from pathlib import Path

# Load API key from .env (same pattern as game.py)
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().strip().split("\n"):
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()

import websockets
from websockets.http11 import Response, Request
from websockets.http import Headers

from engine import (
    HexMap, UnitManager, LogisticsSystem, FogOfWar,
    TurnManager, Orders, Faction, UnitCategory, UnitStatus,
)
from agents import IndiaAgent, PakistanAgent
from replay_export import ReplayCollector, _sam_range

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_PATH = Path("data")
CLIENT_HTML = Path(__file__).parent / "game_client.html"


class GameSession:
    """Wraps the engine components for a single human vs AI game."""

    def __init__(self, data_path: Path = DATA_PATH):
        self.data_path = data_path
        self.hex_map = HexMap(data_path)
        self.units = UnitManager(data_path)
        self.logistics = LogisticsSystem()
        self.fog = FogOfWar()
        self.turn_manager = TurnManager(
            self.hex_map, self.units, self.logistics, self.fog, data_path
        )
        self.human_faction = None
        self.ai_agent = None
        self.replay_collector = None

    def initialize(self, faction: str, scenario: str = "hot_start_4day"):
        """Initialize game with human faction choice."""
        self.human_faction = faction
        self.ai_faction = "pakistan" if faction == "india" else "india"

        # Initialize engine
        self.turn_manager.initialize_game()

        # Load scenario
        scenario_path = self.data_path / "scenarios" / f"{scenario}.yaml"
        if scenario_path.exists():
            with open(scenario_path) as f:
                sc = yaml.safe_load(f)
            if "scenario" in sc:
                self.turn_manager.game_state.max_turns = sc["scenario"].get(
                    "duration_turns", 16
                )

        # Create AI agent for opponent
        if self.ai_faction == "india":
            self.ai_agent = IndiaAgent.create_default()
        else:
            self.ai_agent = PakistanAgent.create_default()

        logger.info(
            f"Game initialized: human={faction}, AI={self.ai_faction}, "
            f"max_turns={self.turn_manager.game_state.max_turns}"
        )

    def get_human_state(self) -> dict:
        """Get fog-filtered game state for the human player."""
        return self.turn_manager.get_game_state_for_agent(self.human_faction)

    def get_unit_roster(self) -> list:
        """Build detailed unit list for orders panel."""
        faction_enum = (
            Faction.INDIA if self.human_faction == "india" else Faction.PAKISTAN
        )
        units = self.units.get_units_by_faction(faction_enum)
        roster = []
        for unit in units:
            pos = self._resolve_unit_position(unit)
            roster.append({
                "id": unit.id,
                "name": unit.name,
                "category": unit.category.value,
                "type": unit.unit_type,
                "status": unit.status.value,
                "strength": round(
                    unit.state.strength_current
                    / max(1, unit.state.strength_max)
                    * 100
                ),
                "lat": round(pos[0], 4) if pos else None,
                "lon": round(pos[1], 4) if pos else None,
            })
        return roster

    def get_targets(self, game_state: dict) -> list:
        """Build targetable entity list from fog-of-war state + static data."""
        targets = []

        # Known enemies from fog of war
        for enemy in game_state.get("known_enemies", []):
            loc = enemy.get("location")
            lat = lon = None
            if isinstance(loc, dict):
                lat, lon = loc.get("lat"), loc.get("lon")
            elif isinstance(loc, (list, tuple)) and len(loc) == 2:
                try:
                    lat, lon = self.hex_map.hex_to_latlon(int(loc[0]), int(loc[1]))
                except Exception:
                    pass
            # Try unit lookup for position
            if lat is None:
                uid = enemy.get("id", "")
                u = self.units.get_unit(uid)
                if u:
                    pos = self._resolve_unit_position(u)
                    if pos:
                        lat, lon = pos
            targets.append({
                "id": enemy.get("id", ""),
                "name": enemy.get("type", "Unknown"),
                "type": "enemy_unit",
                "category": enemy.get("category", ""),
                "lat": round(lat, 4) if lat else None,
                "lon": round(lon, 4) if lon else None,
            })

        # Enemy airbases (from static data)
        for bid, base in self.units.airbases.items():
            if base.faction.value != self.human_faction and base.location.lat is not None:
                targets.append({
                    "id": bid,
                    "name": base.name,
                    "type": "airbase",
                    "category": "airbase",
                    "lat": base.location.lat,
                    "lon": base.location.lon,
                })

        # Enemy SAM sites
        for faction in ["india", "pakistan"]:
            if faction == self.human_faction:
                continue
            ad_path = self.data_path / faction / "air_defense.yaml"
            if not ad_path.exists():
                continue
            try:
                with open(ad_path) as f:
                    data = yaml.safe_load(f)
            except Exception:
                continue
            sites = (
                data.get("sam_sites")
                or data.get("air_defense_systems")
                or data.get("systems")
                or []
            )
            for site in sites:
                loc = site.get("location", {})
                if not isinstance(loc, dict) or not loc.get("lat"):
                    continue
                targets.append({
                    "id": site.get("id", site.get("name", "")),
                    "name": site.get("name", ""),
                    "type": "sam_site",
                    "category": "air_defense",
                    "lat": loc["lat"],
                    "lon": loc["lon"],
                })

        return targets

    def build_static_data(self) -> dict:
        """Build static map data (same as ReplayCollector._collect_static_data)."""
        hm = self.hex_map
        rivers = []
        for r in hm.rivers:
            path = [{"lat": p["lat"], "lon": p["lon"]} for p in r.get("path", [])]
            if len(path) >= 2:
                rivers.append({
                    "name": r.get("name", ""),
                    "path": path,
                    "width": r.get("width_avg_m", 100),
                })
        cities = []
        for c in hm.cities:
            if c.get("lat") and c.get("lon"):
                cities.append({
                    "name": c.get("name", ""),
                    "lat": c["lat"],
                    "lon": c["lon"],
                    "faction": c.get("faction", "neutral"),
                    "population": c.get("population", 0),
                    "type": c.get("type", "minor"),
                })
        airbases = []
        for bid, base in self.units.airbases.items():
            if base.location.lat is not None:
                airbases.append({
                    "id": bid,
                    "name": base.name,
                    "faction": base.faction.value,
                    "lat": base.location.lat,
                    "lon": base.location.lon,
                })
        sectors = []
        for s in hm.sectors:
            b = s.get("bounds", {})
            if b.get("north"):
                sectors.append({
                    "id": s.get("id", ""),
                    "name": s.get("name", ""),
                    "terrain": s.get("terrain_primary", "plains"),
                    "north": b["north"],
                    "south": b["south"],
                    "east": b["east"],
                    "west": b["west"],
                })
        loc_path = [{"lat": p["lat"], "lon": p["lon"]} for p in hm.loc_path]
        choke_points = [
            {
                "name": cp.get("name", ""),
                "lat": cp["lat"],
                "lon": cp["lon"],
                "type": cp.get("type", ""),
            }
            for cp in hm.choke_points
            if cp.get("lat")
        ]
        sam_sites = self._load_sam_sites()
        return {
            "rivers": rivers,
            "cities": cities,
            "airbases": airbases,
            "sectors": sectors,
            "loc_path": loc_path,
            "choke_points": choke_points,
            "sam_sites": sam_sites,
        }

    def _load_sam_sites(self) -> list:
        sam_sites = []
        for faction in ["india", "pakistan"]:
            ad_path = self.data_path / faction / "air_defense.yaml"
            if not ad_path.exists():
                continue
            try:
                with open(ad_path) as f:
                    data = yaml.safe_load(f)
            except Exception:
                continue
            sites = (
                data.get("sam_sites")
                or data.get("air_defense_systems")
                or data.get("systems")
                or []
            )
            for site in sites:
                loc = site.get("location", {})
                if not isinstance(loc, dict) or not loc.get("lat"):
                    continue
                sam_type = site.get("sam_type", site.get("type", "sam"))
                sam_sites.append({
                    "name": site.get("name", ""),
                    "faction": faction,
                    "type": str(sam_type),
                    "lat": loc["lat"],
                    "lon": loc["lon"],
                    "range_km": _sam_range(str(sam_type)),
                })
        return sam_sites

    def build_turn_data(self, turn_state) -> dict:
        """Build turn result data (same pattern as ReplayCollector.snapshot_turn)."""
        events = []
        for report in turn_state.combat_reports:
            r = report if isinstance(report, dict) else report.__dict__

            to_lat, to_lon = None, None
            loc = r.get("location")
            if loc and isinstance(loc, (list, tuple)) and len(loc) == 2:
                try:
                    to_lat, to_lon = self.hex_map.hex_to_latlon(
                        int(loc[0]), int(loc[1])
                    )
                except Exception:
                    pass
            if to_lat is None:
                defender = self.units.get_unit(r.get("defender_id", ""))
                if defender:
                    pos = self._resolve_unit_position(defender)
                    if pos:
                        to_lat, to_lon = pos
            if to_lat is None:
                attacker = self.units.get_unit(r.get("attacker_id", ""))
                if attacker:
                    pos = self._resolve_unit_position(attacker)
                    if pos:
                        to_lat, to_lon = pos

            from_lat, from_lon = None, None
            attacker_unit = self.units.get_unit(r.get("attacker_id", ""))
            if attacker_unit:
                pos = self._resolve_origin_position(attacker_unit)
                if pos:
                    from_lat, from_lon = pos

            result_val = r.get("result", "unknown")
            if hasattr(result_val, "value"):
                result_val = result_val.value

            events.append({
                "phase": r.get("phase", "unknown"),
                "attacker": r.get("attacker_id", ""),
                "defender": r.get("defender_id", ""),
                "attacker_faction": (
                    attacker_unit.faction.value if attacker_unit else None
                ),
                "interceptable": self._is_interceptable(attacker_unit),
                "result": str(result_val),
                "lat": round(to_lat, 4) if to_lat else None,
                "lon": round(to_lon, 4) if to_lon else None,
                "from_lat": round(from_lat, 4) if from_lat else None,
                "from_lon": round(from_lon, 4) if from_lon else None,
                "attacker_losses": r.get("attacker_losses", {}),
                "defender_losses": r.get("defender_losses", {}),
                "notes": r.get("notes", []),
            })

        return {
            "turn": turn_state.turn_number,
            "day": turn_state.day,
            "time": turn_state.time_of_day.value,
            "weather": turn_state.weather.value,
            "india_vp": self.turn_manager.game_state.india_vp,
            "pakistan_vp": self.turn_manager.game_state.pakistan_vp,
            "units": self._snapshot_units(),
            "combat_events": events,
        }

    def _snapshot_units(self) -> list:
        """Snapshot all units (same as ReplayCollector._snapshot_units)."""
        units = []
        for uid, unit in self.units.units.items():
            pos = self._resolve_unit_position(unit)
            if pos is None:
                continue
            strength_pct = round(
                unit.state.strength_current / max(1, unit.state.strength_max) * 100
            )
            units.append({
                "id": unit.id,
                "name": unit.name,
                "faction": unit.faction.value,
                "category": unit.category.value,
                "type": unit.unit_type,
                "lat": round(pos[0], 4),
                "lon": round(pos[1], 4),
                "status": unit.status.value,
                "strength": strength_pct,
                "posture": unit.posture.value,
            })
        return units

    def execute_turn(self, human_orders_dict: dict) -> dict:
        """Execute one turn: build Orders from human JSON, call AI, run engine."""
        turn_number = self.turn_manager.game_state.turn + 1

        # Build human Orders from JSON (same as StrategicAgent._dict_to_orders)
        human_orders = Orders(
            faction=self.human_faction,
            turn=turn_number,
            missile_strikes=human_orders_dict.get("missile_strikes", []),
            ew_missions=human_orders_dict.get("ew_missions", []),
            air_missions=human_orders_dict.get("air_missions", []),
            drone_missions=human_orders_dict.get("drone_missions", []),
            artillery_missions=human_orders_dict.get("artillery_missions", []),
            helicopter_missions=human_orders_dict.get("helicopter_missions", []),
            ground_orders=human_orders_dict.get("ground_orders", []),
            sf_missions=human_orders_dict.get("sf_missions", []),
        )

        # Get AI state and generate AI orders
        ai_state = self.turn_manager.get_game_state_for_agent(self.ai_faction)
        previous_reports = []
        if self.turn_manager.game_state.turn_history:
            last = self.turn_manager.game_state.turn_history[-1]
            previous_reports = last.combat_reports

        try:
            ai_orders = self.ai_agent.generate_orders(ai_state, previous_reports)
        except Exception as e:
            logger.error(f"AI agent error: {e}")
            ai_orders = Orders(faction=self.ai_faction, turn=turn_number)

        # Determine which is india/pakistan
        if self.human_faction == "india":
            india_orders, pakistan_orders = human_orders, ai_orders
        else:
            india_orders, pakistan_orders = ai_orders, human_orders

        # Execute turn
        turn_state = self.turn_manager.execute_full_turn(india_orders, pakistan_orders)

        return self.build_turn_data(turn_state)

    # -- Position resolution helpers (mirrors ReplayCollector) --

    def _resolve_unit_position(self, unit, depth=0):
        if depth > 3:
            return None
        loc = unit.location
        if loc.lat is not None and loc.lon is not None:
            return (loc.lat, loc.lon)
        if loc.hex_q is not None and loc.hex_r is not None:
            return self.hex_map.hex_to_latlon(loc.hex_q, loc.hex_r)
        td_loc = unit.type_data.get("location", {})
        if isinstance(td_loc, dict) and td_loc.get("lat") and td_loc.get("lon"):
            return (td_loc["lat"], td_loc["lon"])
        hq_loc = unit.type_data.get("hq_location", {})
        if isinstance(hq_loc, dict) and hq_loc.get("lat") and hq_loc.get("lon"):
            return (hq_loc["lat"], hq_loc["lon"])
        if loc.airbase_id:
            base = self.units.get_airbase(loc.airbase_id)
            if base and base.location.lat is not None:
                return (base.location.lat, base.location.lon)
        if unit.parent_id:
            parent = self.units.get_unit(unit.parent_id)
            if parent:
                return self._resolve_unit_position(parent, depth + 1)
        return None

    def _resolve_origin_position(self, unit):
        if hasattr(unit, "base_id") and unit.base_id:
            base = self.units.get_airbase(unit.base_id)
            if base and base.location.lat is not None:
                return (base.location.lat, base.location.lon)
        if unit.location.airbase_id:
            base = self.units.get_airbase(unit.location.airbase_id)
            if base and base.location.lat is not None:
                return (base.location.lat, base.location.lon)
        return self._resolve_unit_position(unit)

    @staticmethod
    def _is_interceptable(unit):
        if unit is None:
            return True
        UNINTERCEPTABLE = [
            "brahmos", "hypersonic", "zircon", "kinzhal", "df17"
        ]
        name = (unit.name or "").lower().replace("-", "").replace(" ", "")
        uid = (unit.id or "").lower().replace("-", "").replace(" ", "")
        utype = (unit.unit_type or "").lower().replace("-", "").replace(" ", "")
        for w in UNINTERCEPTABLE:
            if w in name or w in uid or w in utype:
                return False
        return True


# ── WebSocket Game Server ──


async def handle_websocket(websocket):
    """Handle a single WebSocket connection (one game session)."""
    session = None

    async def send_json(msg_type: str, data: dict):
        await websocket.send(json.dumps({"type": msg_type, **data}, default=str))

    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await send_json("error", {"message": "Invalid JSON"})
                continue

            msg_type = msg.get("type", "")

            if msg_type == "start_game":
                faction = msg.get("faction", "india")
                if faction not in ("india", "pakistan"):
                    await send_json("error", {"message": "Invalid faction"})
                    continue

                logger.info(f"Starting game: human={faction}")
                session = GameSession()
                session.initialize(faction)

                game_state = session.get_human_state()
                unit_roster = session.get_unit_roster()
                static_data = session.build_static_data()
                targets = session.get_targets(game_state)

                # Build initial turn data (turn 0)
                initial_units = session._snapshot_units()

                await send_json("game_init", {
                    "faction": faction,
                    "turn": 0,
                    "max_turns": session.turn_manager.game_state.max_turns,
                    "game_state": game_state,
                    "unit_roster": unit_roster,
                    "static": static_data,
                    "targets": targets,
                    "initial_turn": {
                        "turn": 0,
                        "day": 1,
                        "time": "pre-war",
                        "weather": session.hex_map.weather.weather.value,
                        "india_vp": 0,
                        "pakistan_vp": 0,
                        "units": initial_units,
                        "combat_events": [],
                    },
                })

                # Immediately send awaiting_orders for turn 1
                await send_json("awaiting_orders", {
                    "turn": 1,
                    "game_state": game_state,
                    "unit_roster": unit_roster,
                    "targets": targets,
                })

            elif msg_type == "submit_orders":
                if session is None:
                    await send_json("error", {"message": "No game in progress"})
                    continue

                orders = msg.get("orders", {})
                logger.info(
                    f"Orders received for turn {msg.get('turn', '?')}: "
                    f"{sum(len(v) for v in orders.values() if isinstance(v, list))} total"
                )

                await send_json("processing", {
                    "message": "AI opponent planning..."
                })

                # Run in executor to not block the event loop
                loop = asyncio.get_event_loop()
                turn_data = await loop.run_in_executor(
                    None, session.execute_turn, orders
                )

                # Add cost-of-war data
                cost_snapshot = session.turn_manager.cost_tracker.get_turn_snapshot()
                turn_data.update(cost_snapshot)

                await send_json("turn_result", {
                    "turn": turn_data["turn"],
                    "turn_data": turn_data,
                })

                # Check game over
                gs = session.turn_manager.game_state
                if gs.game_over:
                    cost_summary = session.turn_manager.cost_tracker.get_summary()
                    await send_json("game_over", {
                        "winner": gs.winner,
                        "final_vp": {
                            "india": gs.india_vp,
                            "pakistan": gs.pakistan_vp,
                        },
                        "cost_summary": cost_summary,
                    })
                else:
                    # Send next turn state
                    game_state = session.get_human_state()
                    unit_roster = session.get_unit_roster()
                    targets = session.get_targets(game_state)
                    await send_json("awaiting_orders", {
                        "turn": gs.turn + 1,
                        "game_state": game_state,
                        "unit_roster": unit_roster,
                        "targets": targets,
                    })

            else:
                await send_json("error", {"message": f"Unknown message type: {msg_type}"})

    except websockets.exceptions.ConnectionClosed:
        logger.info("Client disconnected")


def http_handler(connection, request):
    """Serve game_client.html on GET / (websockets v16 process_request)."""
    if request.path == "/" or request.path == "":
        try:
            body = CLIENT_HTML.read_bytes()
        except FileNotFoundError:
            body = b"<h1>game_client.html not found</h1>"
        return Response(
            200,
            "OK",
            Headers([
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ]),
            body,
        )
    return None  # Let websockets handle WebSocket upgrade


async def main():
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))

    logger.info(f"Starting server on http://{host}:{port}")
    logger.info("Open http://localhost:8080 in your browser")

    async with websockets.serve(
        handle_websocket,
        host,
        port,
        process_request=http_handler,
        max_size=10 * 1024 * 1024,  # 10MB max message
    ):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
