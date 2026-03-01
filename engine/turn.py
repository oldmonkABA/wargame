"""
Turn sequencing system for wargame simulation.

Orchestrates phases: missiles → EW → air → drones → artillery → helicopters → ground → SF → logistics
Each turn represents 6 hours. 16 turns = 4 days.
"""

from dataclasses import dataclass, field
from typing import Optional, Callable, Any
from enum import Enum
import json
import yaml
from pathlib import Path

from .map import HexMap, Weather
from .units import UnitManager, Faction, UnitCategory, UnitStatus
from .logistics import LogisticsSystem
from .fog_of_war import FogOfWar
from .combat import (
    MissileCombat, ElectronicWarfare, AirCombat, DroneCombat,
    ArtilleryCombat, HelicopterCombat, GroundCombat, SpecialForcesCombat
)


class Phase(Enum):
    """Combat phases in order of execution."""
    INTELLIGENCE = "intelligence"  # ISR, detection
    MISSILES = "missiles"
    ELECTRONIC_WARFARE = "ew"
    AIR = "air"
    DRONES = "drones"
    ARTILLERY = "artillery"
    HELICOPTERS = "helicopters"
    GROUND = "ground"
    SPECIAL_FORCES = "special_forces"
    LOGISTICS = "logistics"
    RECOVERY = "recovery"  # Unit recovery, resupply


class TimeOfDay(Enum):
    DAWN = "dawn"      # 0600-1200
    DAY = "day"        # 1200-1800
    DUSK = "dusk"      # 1800-0000
    NIGHT = "night"    # 0000-0600


@dataclass
class TurnState:
    """State of the current turn."""
    turn_number: int
    day: int
    time_of_day: TimeOfDay
    weather: Weather
    current_phase: Phase
    phase_complete: dict[str, bool] = field(default_factory=dict)
    combat_reports: list = field(default_factory=list)
    units_in_combat: set = field(default_factory=set)


@dataclass
class GameState:
    """Complete game state."""
    turn: int = 0
    max_turns: int = 16
    india_vp: int = 0
    pakistan_vp: int = 0
    game_over: bool = False
    winner: Optional[str] = None
    turn_history: list[TurnState] = field(default_factory=list)


@dataclass
class Orders:
    """Orders from an agent for a turn."""
    faction: str
    turn: int
    missile_strikes: list = field(default_factory=list)
    ew_missions: list = field(default_factory=list)
    air_missions: list = field(default_factory=list)
    drone_missions: list = field(default_factory=list)
    artillery_missions: list = field(default_factory=list)
    helicopter_missions: list = field(default_factory=list)
    ground_orders: list = field(default_factory=list)
    sf_missions: list = field(default_factory=list)


class TurnManager:
    """Manages turn execution and phase sequencing."""

    PHASES = [
        Phase.INTELLIGENCE,
        Phase.MISSILES,
        Phase.ELECTRONIC_WARFARE,
        Phase.AIR,
        Phase.DRONES,
        Phase.ARTILLERY,
        Phase.HELICOPTERS,
        Phase.GROUND,
        Phase.SPECIAL_FORCES,
        Phase.LOGISTICS,
        Phase.RECOVERY,
    ]

    def __init__(
        self,
        hex_map: HexMap,
        unit_manager: UnitManager,
        logistics: LogisticsSystem,
        fog_of_war: FogOfWar,
        data_path: Path | str = "data",
    ):
        self.hex_map = hex_map
        self.units = unit_manager
        self.logistics = logistics
        self.fog = fog_of_war

        # Load swarm config from YAML
        swarm_config = {}
        drones_yaml = Path(data_path) / "schema" / "drones.yaml"
        if drones_yaml.exists():
            with open(drones_yaml) as f:
                data = yaml.safe_load(f)
                swarm_config = data.get("swarm_operations", {})

        # Combat resolvers
        self.missile_combat = MissileCombat()
        self.ew = ElectronicWarfare()
        self.air_combat = AirCombat()
        self.drone_combat = DroneCombat(swarm_config=swarm_config)
        self.artillery_combat = ArtilleryCombat()
        self.heli_combat = HelicopterCombat()
        self.ground_combat = GroundCombat()
        self.sf_combat = SpecialForcesCombat()

        self.game_state = GameState()
        self.current_turn: Optional[TurnState] = None

        # EW effects for current turn (affects other phases)
        self.current_ew_effects: dict[str, Any] = {}

        # Track destroyed units already counted for VP to avoid double-counting
        self._destroyed_units_counted: set[str] = set()

        # Cost-of-war economic tracking
        from .costs import CostTracker
        self.cost_tracker = CostTracker(Path(data_path))

        # Callbacks for agent integration
        self.on_turn_start: Optional[Callable] = None
        self.on_phase_start: Optional[Callable] = None
        self.on_phase_end: Optional[Callable] = None
        self.on_turn_end: Optional[Callable] = None

    def initialize_game(self):
        """Initialize a new game."""
        self.game_state = GameState(turn=0, max_turns=16)
        self.current_turn = None

        # Load units for both factions
        self.units.load_faction_oob(Faction.INDIA)
        self.units.load_faction_oob(Faction.PAKISTAN)

    def get_time_of_day(self, turn: int) -> TimeOfDay:
        """Get time of day for a turn number."""
        # 4 turns per day
        turn_in_day = turn % 4
        return [TimeOfDay.DAWN, TimeOfDay.DAY, TimeOfDay.DUSK, TimeOfDay.NIGHT][turn_in_day]

    def get_day_number(self, turn: int) -> int:
        """Get day number (1-4) for a turn."""
        return (turn // 4) + 1

    def start_turn(self) -> TurnState:
        """Start a new turn."""
        self.game_state.turn += 1
        turn = self.game_state.turn

        time_of_day = self.get_time_of_day(turn - 1)
        is_night = time_of_day == TimeOfDay.NIGHT

        # Update map time
        self.hex_map.set_time_of_day(is_night)

        # Create turn state
        self.current_turn = TurnState(
            turn_number=turn,
            day=self.get_day_number(turn),
            time_of_day=time_of_day,
            weather=self.hex_map.weather.weather,
            current_phase=Phase.INTELLIGENCE,
            phase_complete={p.value: False for p in self.PHASES},
        )

        # Reset per-turn state
        self.current_ew_effects = {}

        # Callback
        if self.on_turn_start:
            self.on_turn_start(self.current_turn)

        return self.current_turn

    def execute_phase(
        self,
        phase: Phase,
        india_orders: Orders,
        pakistan_orders: Orders,
    ) -> list:
        """Execute a single phase."""
        if not self.current_turn:
            raise RuntimeError("Turn not started")

        self.current_turn.current_phase = phase

        if self.on_phase_start:
            self.on_phase_start(phase)

        reports = []

        if phase == Phase.INTELLIGENCE:
            reports = self._execute_intelligence_phase()
        elif phase == Phase.MISSILES:
            reports = self._execute_missile_phase(india_orders, pakistan_orders)
        elif phase == Phase.ELECTRONIC_WARFARE:
            reports = self._execute_ew_phase(india_orders, pakistan_orders)
        elif phase == Phase.AIR:
            reports = self._execute_air_phase(india_orders, pakistan_orders)
        elif phase == Phase.DRONES:
            reports = self._execute_drone_phase(india_orders, pakistan_orders)
        elif phase == Phase.ARTILLERY:
            reports = self._execute_artillery_phase(india_orders, pakistan_orders)
        elif phase == Phase.HELICOPTERS:
            reports = self._execute_helicopter_phase(india_orders, pakistan_orders)
        elif phase == Phase.GROUND:
            reports = self._execute_ground_phase(india_orders, pakistan_orders)
        elif phase == Phase.SPECIAL_FORCES:
            reports = self._execute_sf_phase(india_orders, pakistan_orders)
        elif phase == Phase.LOGISTICS:
            reports = self._execute_logistics_phase()
        elif phase == Phase.RECOVERY:
            reports = self._execute_recovery_phase()

        self.current_turn.phase_complete[phase.value] = True
        self.current_turn.combat_reports.extend(reports)

        if self.on_phase_end:
            self.on_phase_end(phase, reports)

        return reports

    def execute_full_turn(
        self,
        india_orders: Orders,
        pakistan_orders: Orders,
    ) -> TurnState:
        """Execute all phases of a turn."""
        self.start_turn()

        for phase in self.PHASES:
            self.execute_phase(phase, india_orders, pakistan_orders)

        self.end_turn()
        return self.current_turn

    def end_turn(self):
        """End the current turn."""
        if not self.current_turn:
            return

        # Calculate VP changes
        self._calculate_victory_points()

        # Process cost-of-war economics
        self.cost_tracker.process_combat_reports(
            self.current_turn.combat_reports, self.units
        )

        # Check victory conditions
        self._check_victory_conditions()

        # Store turn in history
        self.game_state.turn_history.append(self.current_turn)

        if self.on_turn_end:
            self.on_turn_end(self.current_turn)

    def _execute_intelligence_phase(self) -> list:
        """Execute intelligence/detection phase."""
        india_units = self.units.get_units_by_faction(Faction.INDIA)
        pakistan_units = self.units.get_units_by_faction(Faction.PAKISTAN)

        # India detects Pakistan units
        india_reports = self.fog.process_detection_turn(
            "india", pakistan_units, self.hex_map, self.game_state.turn
        )

        # Pakistan detects India units
        pakistan_reports = self.fog.process_detection_turn(
            "pakistan", india_units, self.hex_map, self.game_state.turn
        )

        # Decay old intel
        self.fog.decay_intel("india", self.game_state.turn)
        self.fog.decay_intel("pakistan", self.game_state.turn)

        return []  # Intel reports are internal

    def _execute_missile_phase(self, india_orders: Orders, pakistan_orders: Orders) -> list:
        """Execute missile strikes."""
        reports = []

        # Process India strikes
        for strike in india_orders.missile_strikes:
            report = self._resolve_missile_strike(strike, "india")
            if report:
                reports.append(report)

        # Process Pakistan strikes
        for strike in pakistan_orders.missile_strikes:
            report = self._resolve_missile_strike(strike, "pakistan")
            if report:
                reports.append(report)

        return reports

    def _resolve_missile_strike(self, strike: dict, faction: str) -> Optional[dict]:
        """Resolve a single missile strike."""
        from .combat.missiles import MissileStrike

        battery_id = strike.get("battery_id", "")
        battery = self.units.get_unit(battery_id)

        # If exact ID not found, try to find a missile unit by partial match
        if not battery:
            faction_enum = Faction.INDIA if faction == "india" else Faction.PAKISTAN
            missile_units = [u for u in self.units.get_units_by_category(UnitCategory.MISSILE)
                           if u.faction == faction_enum]
            if missile_units:
                # Find one with missiles remaining
                for mu in missile_units:
                    if hasattr(mu, "can_fire") and mu.can_fire():
                        battery = mu
                        break

        if not battery or not hasattr(battery, "can_fire") or not battery.can_fire():
            return None

        target_id = strike.get("target_id", "")
        missiles = max(2, strike.get("missiles", 2))  # Minimum salvo of 2
        missiles = min(missiles, battery.missiles_remaining)  # Cap at available

        # Get defending SAMs
        enemy = "pakistan" if faction == "india" else "india"
        enemy_sams = self._get_sams_defending(target_id, enemy)

        # Target hardness based on type
        target_type = strike.get("target_type", "ground_unit")
        hardness_map = {
            "airbase": 80,
            "sam_site": 50,
            "radar": 30,
            "c2": 70,
            "logistics": 40,
            "ground_unit": 40,
        }
        target_hardness = hardness_map.get(target_type, 60)

        # Create strike object
        missile_strike = MissileStrike(
            battery_id=battery.id,
            target_id=target_id,
            target_type=target_type,
            missiles_fired=missiles,
            missile_type=getattr(battery, "missile_type", "cruise"),
        )

        # Resolve
        report = self.missile_combat.resolve_strike(
            missile_strike,
            enemy_sams,
            target_hardness=target_hardness,
            weather_modifier=self.hex_map.weather.air_ops_modifier,
            ew_modifier=1.0 - self.current_ew_effects.get(f"{enemy}_radar_jam", 0),
        )

        # Apply effects
        battery.fire_missile(missiles)
        report.turn = self.game_state.turn

        return report.__dict__

    def _get_sams_defending(self, target_id: str, faction: str) -> list:
        """Get SAM systems defending a target — layered defense.

        Incoming cruise missiles transit through multiple SAM engagement zones.
        Long-range systems (S-400, HQ-9) provide outer umbrella.
        Medium-range (Barak-8/MRSAM, Akash, HQ-16) provide middle layer.
        Short-range (SPYDER, SPADA, FM-90) provide point defense.
        Each layer gets a shot — this is how layered IADS works.
        """
        # SAM range tiers (km) — determines which layers engage incoming missiles
        LONG_RANGE = {"s400", "hq9"}           # 200-400km, outer umbrella
        MEDIUM_RANGE = {"barak8", "mrsam", "akash", "hq16"}  # 30-100km, area defense
        SHORT_RANGE = {"spyder", "spada2000", "fm90"}         # 15-30km, point defense

        # First: SAMs whose protecting list directly covers this target
        protecting_sams = []
        long_range_sams = []
        medium_range_sams = []
        short_range_sams = []

        for unit in self.units.get_units_by_category(UnitCategory.AIR_DEFENSE):
            if unit.faction.value != faction or not unit.is_combat_effective():
                continue
            sam_entry = {
                "type": unit.unit_type,
                "rounds": unit.type_data.get("missiles_available", int(unit.state.supply_level)),
                "ready": unit.status == UnitStatus.READY,
            }
            protecting = unit.type_data.get("protecting", [])
            is_protecting = target_id in protecting or any(target_id in p for p in protecting)

            sam_type = unit.unit_type.lower()
            if is_protecting:
                protecting_sams.append(sam_entry)
            elif sam_type in LONG_RANGE:
                long_range_sams.append(sam_entry)
            elif sam_type in MEDIUM_RANGE:
                medium_range_sams.append(sam_entry)
            elif sam_type in SHORT_RANGE:
                short_range_sams.append(sam_entry)

        # Build layered defense: all directly protecting SAMs +
        # 1 long-range (area umbrella) + 1 medium-range (sector defense)
        # Incoming missile must survive each layer sequentially
        result = protecting_sams[:]
        if long_range_sams:
            result.append(long_range_sams[0])
        if medium_range_sams:
            result.append(medium_range_sams[0])

        # Deduplicate by type (don't double-count same system)
        seen_types = set()
        deduped = []
        for sam in result:
            if sam["type"] not in seen_types:
                seen_types.add(sam["type"])
                deduped.append(sam)

        return deduped if deduped else short_range_sams[:1]

    def _execute_ew_phase(self, india_orders: Orders, pakistan_orders: Orders) -> list:
        """Execute electronic warfare phase."""
        reports = []

        # EW affects subsequent phases
        for mission in india_orders.ew_missions:
            effect, report = self._resolve_ew_mission(mission, "india")
            if effect:
                self.current_ew_effects["pakistan_radar_jam"] = max(
                    self.current_ew_effects.get("pakistan_radar_jam", 0),
                    effect.get("radar_degradation", 0),
                )
                self.current_ew_effects["pakistan_comms_jam"] = max(
                    self.current_ew_effects.get("pakistan_comms_jam", 0),
                    effect.get("comms_degradation", 0),
                )
                if effect.get("cyber_damage"):
                    self.current_ew_effects["pakistan_cyber_damage"] = effect["cyber_damage"]
                if effect.get("gps_degradation"):
                    self.current_ew_effects["pakistan_gps_jam"] = effect["gps_degradation"]
                if effect.get("sigint_intel"):
                    self.current_ew_effects["india_sigint_intel"] = effect["sigint_intel"]
            if report:
                reports.append(report)

        for mission in pakistan_orders.ew_missions:
            effect, report = self._resolve_ew_mission(mission, "pakistan")
            if effect:
                self.current_ew_effects["india_radar_jam"] = max(
                    self.current_ew_effects.get("india_radar_jam", 0),
                    effect.get("radar_degradation", 0),
                )
                self.current_ew_effects["india_comms_jam"] = max(
                    self.current_ew_effects.get("india_comms_jam", 0),
                    effect.get("comms_degradation", 0),
                )
                if effect.get("cyber_damage"):
                    self.current_ew_effects["india_cyber_damage"] = effect["cyber_damage"]
                if effect.get("gps_degradation"):
                    self.current_ew_effects["india_gps_jam"] = effect["gps_degradation"]
                if effect.get("sigint_intel"):
                    self.current_ew_effects["pakistan_sigint_intel"] = effect["sigint_intel"]
            if report:
                reports.append(report)

        return reports

    def _resolve_ew_mission(self, mission: dict, faction: str) -> tuple[Optional[dict], Optional[dict]]:
        """Resolve EW mission. Returns (effect_dict, report_dict)."""
        from .combat.ew import EWMission

        mission_type = mission.get("type", "jam_radar")

        ew_mission = EWMission(
            unit_id=mission.get("unit_id", ""),
            mission_type=mission_type,
            target_area=mission.get("target_area"),
        )

        enemy_units = self.units.get_units_by_faction(
            Faction.PAKISTAN if faction == "india" else Faction.INDIA
        )

        if mission_type == "cyber":
            target_system = mission.get("target_system", "c2")
            target_defense = mission.get("target_cyber_defense", 50.0)
            sophistication = mission.get("attack_sophistication", 60.0)
            report, effect = self.ew.resolve_cyber_attack(
                ew_mission, target_system, target_defense, sophistication
            )
            report.turn = self.game_state.turn
            effect_dict = {
                "cyber_damage": effect.cyber_damage,
                "comms_degradation": effect.comms_degradation,
                "radar_degradation": effect.radar_degradation,
            }
            return effect_dict, report.__dict__

        elif mission_type == "sigint":
            sigint_cap = mission.get("sigint_capability", 60.0)
            comms_activity = mission.get("target_comms_activity", 70.0)
            comsec = mission.get("target_comsec", 50.0)
            report, effect = self.ew.resolve_sigint(
                ew_mission, sigint_cap, comms_activity, comsec
            )
            report.turn = self.game_state.turn
            # Feed SIGINT intel into fog of war
            if effect.intel_gathered.get("unit_locations"):
                from .fog_of_war import IntelReport, IntelQuality
                enemy = "pakistan" if faction == "india" else "india"
                # Partial location intel from intercepted comms
                enemy_faction = Faction.PAKISTAN if faction == "india" else Faction.INDIA
                for unit in self.units.get_units_by_faction(enemy_faction)[:3]:
                    intel_report = IntelReport(
                        unit_id=unit.id,
                        faction=enemy,
                        quality=IntelQuality.DETECTED,
                        last_updated=self.game_state.turn,
                        source="sigint",
                    )
                    self.fog.add_manual_intel(faction, intel_report)
            effect_dict = {"sigint_intel": effect.intel_gathered}
            return effect_dict, report.__dict__

        elif mission_type == "gps_denial":
            # GPS denial uses jamming resolver with GPS-specific effects
            report, effect = self.ew.resolve_jamming(
                ew_mission, mission.get("stats", {}), enemy_units
            )
            report.turn = self.game_state.turn
            effect_dict = {
                "gps_degradation": effect.gps_degradation,
                "radar_degradation": effect.radar_degradation,
            }
            return effect_dict, report.__dict__

        else:
            # jam_radar, jam_comms — existing jamming code
            report, effect = self.ew.resolve_jamming(
                ew_mission,
                mission.get("stats", {}),
                enemy_units,
            )

            report.turn = self.game_state.turn
            report_dict = report.__dict__

            effect_dict = {
                "radar_degradation": effect.radar_degradation,
                "comms_degradation": effect.comms_degradation,
            }

            return effect_dict, report_dict

    def _execute_air_phase(self, india_orders: Orders, pakistan_orders: Orders) -> list:
        """Execute air combat phase."""
        reports = []

        india_air = india_orders.air_missions
        pakistan_air = pakistan_orders.air_missions

        # Separate missions by type
        india_cap = [m for m in india_air if m.get("mission_type", m.get("type", "")) in ("cap", "sweep")]
        india_strike = [m for m in india_air if m.get("mission_type", m.get("type", "")) in ("strike", "sead", "cas")]
        pakistan_cap = [m for m in pakistan_air if m.get("mission_type", m.get("type", "")) in ("cap", "sweep")]
        pakistan_strike = [m for m in pakistan_air if m.get("mission_type", m.get("type", "")) in ("strike", "sead", "cas")]

        # Phase 1: Air-to-air combat (CAP vs CAP/sweep)
        # Match up opposing CAP missions
        for i, india_mission in enumerate(india_cap):
            if i < len(pakistan_cap):
                pak_mission = pakistan_cap[i]
                report = self._resolve_air_to_air(india_mission, pak_mission, "india")
                if report:
                    reports.append(report)
            else:
                # Uncontested CAP - just note air superiority
                report = self._create_cap_report(india_mission, "india", contested=False)
                if report:
                    reports.append(report)

        # Remaining Pakistan CAP (uncontested)
        for i in range(len(india_cap), len(pakistan_cap)):
            report = self._create_cap_report(pakistan_cap[i], "pakistan", contested=False)
            if report:
                reports.append(report)

        # Phase 2: Strike missions (may face opposing CAP)
        for mission in india_strike:
            report = self._resolve_air_strike(mission, "india", enemy_cap=pakistan_cap)
            if report:
                reports.append(report)

        for mission in pakistan_strike:
            report = self._resolve_air_strike(mission, "pakistan", enemy_cap=india_cap)
            if report:
                reports.append(report)

        return reports

    def _get_awacs_bonus(self, faction: str) -> dict:
        """Check if faction has operational AWACS and return radar bonus."""
        awacs_keywords = ("awacs", "aew", "phalcon", "netra", "erieye", "zdk")
        faction_enum = Faction.INDIA if faction == "india" else Faction.PAKISTAN
        for unit in self.units.get_units_by_category(UnitCategory.ISR):
            if unit.faction != faction_enum:
                continue
            unit_type_lower = unit.unit_type.lower()
            if any(kw in unit_type_lower for kw in awacs_keywords) and unit.is_combat_effective():
                radar_boost = 1.5
                bvr_extension = 0.30
                # EW jamming degrades AWACS effectiveness
                jam_key = f"{faction}_radar_jam"
                jam_level = self.current_ew_effects.get(jam_key, 0)
                if jam_level > 0:
                    radar_boost *= (1.0 - jam_level * 0.3)
                return {"radar_boost": radar_boost, "bvr_extension": bvr_extension}
        return {}

    def _resolve_air_to_air(self, attacker_mission: dict, defender_mission: dict, attacker_faction: str) -> Optional[dict]:
        """Resolve air-to-air combat between two missions."""
        from .combat.air import AirMission

        att_sqn_id = attacker_mission.get("squadron_id", "")
        def_sqn_id = defender_mission.get("squadron_id", "")

        att_squadron = self.units.get_unit(att_sqn_id)
        def_squadron = self.units.get_unit(def_sqn_id)

        if not att_squadron or not def_squadron:
            return None

        att_count = attacker_mission.get("aircraft", att_squadron.state.strength_current)
        def_count = defender_mission.get("aircraft", def_squadron.state.strength_current)

        # Pakistan force preservation: don't risk full squadron in one CAP engagement
        PAKISTAN_MAX_CAP_AIRCRAFT = 12
        if attacker_faction == "india":
            def_count = min(def_count, PAKISTAN_MAX_CAP_AIRCRAFT)

        att_mission = AirMission(
            squadron_id=att_sqn_id,
            mission_type="cap",
            aircraft_count=att_count,
            aircraft_type=att_squadron.unit_type,
        )

        def_mission = AirMission(
            squadron_id=def_sqn_id,
            mission_type="cap",
            aircraft_count=def_count,
            aircraft_type=def_squadron.unit_type,
        )

        # Apply AWACS cooperative engagement bonus to attacker
        awacs = self._get_awacs_bonus(attacker_faction)
        att_stats = dict(att_squadron.type_data)
        if awacs:
            att_stats["radar"] = att_stats.get("radar", 70) * awacs.get("radar_boost", 1.0)

        # Apply AWACS bonus to defender
        def_faction = "pakistan" if attacker_faction == "india" else "india"
        def_awacs = self._get_awacs_bonus(def_faction)
        def_stats = dict(def_squadron.type_data)
        if def_awacs:
            def_stats["radar"] = def_stats.get("radar", 70) * def_awacs.get("radar_boost", 1.0)

        report, engagement = self.air_combat.resolve_air_to_air(
            att_mission, def_mission,
            att_stats, def_stats,
            self.hex_map.weather.air_ops_modifier,
        )

        # Apply losses
        if engagement.attacker_losses > 0:
            att_squadron.take_losses(engagement.attacker_losses, 5)
        if engagement.defender_losses > 0:
            def_squadron.take_losses(engagement.defender_losses, 5)

        report.turn = self.game_state.turn
        report.phase = "air_to_air"
        return report.__dict__

    def _create_cap_report(self, mission: dict, faction: str, contested: bool) -> Optional[dict]:
        """Create report for uncontested CAP mission."""
        squadron_id = mission.get("squadron_id", "")
        squadron = self.units.get_unit(squadron_id)
        if not squadron:
            return None

        return {
            "phase": "air_cap",
            "attacker_id": squadron_id,
            "defender_id": "airspace",
            "turn": self.game_state.turn,
            "result": "CombatResult.VICTORY" if not contested else "CombatResult.STALEMATE",
            "attacker_losses": {"aircraft": 0},
            "defender_losses": {},
            "notes": [
                f"CAP mission: {mission.get('aircraft', '?')} aircraft",
                f"Sector: {mission.get('target_id', 'unknown')}",
                "Uncontested - air superiority maintained" if not contested else "Contested airspace"
            ]
        }

    def _resolve_air_strike(self, mission: dict, faction: str, enemy_cap: list = None) -> Optional[dict]:
        """Resolve air strike mission."""
        from .combat.air import AirMission

        squadron_id = mission.get("squadron_id", "")
        squadron = self.units.get_unit(squadron_id)
        if not squadron:
            # Squadron not found - skip
            return None

        mission_type = mission.get("mission_type", mission.get("type", "strike"))

        air_mission = AirMission(
            squadron_id=squadron_id,
            mission_type=mission_type,
            aircraft_count=mission.get("aircraft", squadron.state.strength_current),
            aircraft_type=squadron.unit_type,
            target_id=mission.get("target_id"),
        )

        # Get SAM coverage for target
        enemy = "pakistan" if faction == "india" else "india"
        sams = self._get_sams_defending(mission.get("target_id", ""), enemy)

        # Determine target type for SEAD vs regular strike
        if mission_type == "sead":
            target_type = "sam_site"
            target_defense = 70
        elif mission_type == "cas":
            target_type = "ground_unit"
            target_defense = 40
        else:
            target_type = mission.get("target_type", "ground")
            target_defense = mission.get("target_defense", 50)

        report = self.air_combat.resolve_strike(
            air_mission,
            squadron.type_data,
            target_type,
            target_defense,
            sams,
            self.hex_map.weather.air_ops_modifier,
        )

        # Apply losses
        if report.attacker_losses.get("aircraft", 0) > 0:
            squadron.take_losses(report.attacker_losses["aircraft"], 5)

        report.turn = self.game_state.turn
        report.phase = f"air_{mission_type}"
        return report.__dict__

    def _execute_drone_phase(self, india_orders: Orders, pakistan_orders: Orders) -> list:
        """Execute drone operations phase."""
        reports = []

        for mission in india_orders.drone_missions:
            report = self._resolve_drone_mission(mission, "india")
            if report:
                reports.append(report)

        for mission in pakistan_orders.drone_missions:
            report = self._resolve_drone_mission(mission, "pakistan")
            if report:
                reports.append(report)

        return reports

    def _resolve_drone_mission(self, mission: dict, faction: str) -> Optional[dict]:
        """Resolve a single drone mission."""
        from .combat.drones import DroneMission
        from .fog_of_war import IntelReport, IntelQuality

        unit_id = mission.get("unit_id", "")
        unit = self.units.get_unit(unit_id)
        if not unit:
            return None

        mission_type = mission.get("type", mission.get("mission_type", "strike"))
        target_id = mission.get("target_id", "")
        enemy = "pakistan" if faction == "india" else "india"
        enemy_faction = Faction.PAKISTAN if faction == "india" else Faction.INDIA

        drone_mission = DroneMission(
            unit_id=unit_id,
            mission_type=mission_type,
            drone_count=mission.get("drone_count", unit.state.strength_current),
            drone_type=mission.get("drone_type", unit.unit_type),
            target_id=target_id,
            target_location=mission.get("target_location"),
        )

        ew_degradation = self.current_ew_effects.get(f"{faction}_radar_jam", 0)
        weather_mod = self.hex_map.weather.air_ops_modifier

        if mission_type in ("isr", "recon"):
            # ISR mission — gather intel
            target_area = mission.get("target_location", (0, 0))
            area_radius = mission.get("area_radius", 3)
            enemy_units = self.units.get_units_by_faction(enemy_faction)
            ad_coverage = self._get_ad_coverage_for_drones(target_id, enemy)

            report, engagement = self.drone_combat.resolve_isr_mission(
                drone_mission, target_area, area_radius,
                enemy_units, ad_coverage,
                ew_degradation=ew_degradation,
                weather_modifier=weather_mod,
            )

            # Feed detections into fog of war
            for detected in engagement.intelligence_gathered.get("units_detected", []):
                pos_info = next(
                    (p for p in engagement.intelligence_gathered.get("positions_confirmed", [])
                     if p.get("unit_id") == detected),
                    None,
                )
                intel_report = IntelReport(
                    unit_id=detected,
                    faction=enemy,
                    quality=IntelQuality.IDENTIFIED,
                    last_updated=self.game_state.turn,
                    reported_location=pos_info["location"] if pos_info else None,
                    source="isr",
                )
                self.fog.add_manual_intel(faction, intel_report)

        elif mission_type in ("sead", "swarm"):
            # SEAD / swarm attack on air defenses
            target_sam = self._get_target_sam(target_id, enemy)
            escort_drones = mission.get("escort_drones", 0)

            report, engagement = self.drone_combat.resolve_sead_swarm(
                drone_mission, target_sam, escort_drones=escort_drones,
            )

            # Apply SAM damage
            if engagement.targets_destroyed > 0:
                target_unit = self.units.get_unit(target_id)
                if target_unit:
                    target_unit.take_losses(
                        target_unit.state.strength_current,  # Destroyed
                        50,
                    )
            elif engagement.targets_damaged > 0:
                target_unit = self.units.get_unit(target_id)
                if target_unit:
                    damage_pct = report.defender_losses.get("damage", 30) / 100.0
                    casualties = int(target_unit.state.strength_current * damage_pct)
                    target_unit.take_losses(casualties, 20)

        else:
            # Strike / loitering munition attack
            target_unit = self.units.get_unit(target_id)
            ad_coverage = self._get_ad_coverage_for_drones(target_id, enemy)

            report, engagement = self.drone_combat.resolve_strike_mission(
                drone_mission,
                mission.get("drone_stats", {}),
                target_unit,
                ad_coverage,
                ew_degradation=ew_degradation,
                weather_modifier=weather_mod,
            )

            # Apply target losses
            if target_unit and (engagement.targets_destroyed > 0 or engagement.targets_damaged > 0):
                casualties = engagement.targets_destroyed * 2 + engagement.targets_damaged
                target_unit.take_losses(casualties, engagement.targets_destroyed * 5)

        # Apply drone losses
        if hasattr(unit, 'take_losses'):
            drones_lost = engagement.drones_lost
            if drones_lost > 0:
                unit.take_losses(drones_lost, drones_lost * 3)

        report.turn = self.game_state.turn
        return report.__dict__

    def _get_ad_coverage_for_drones(self, target_id: str, faction: str) -> list:
        """Build AD coverage list from AIR_DEFENSE units of the given faction."""
        ad_coverage = []
        faction_enum = Faction.INDIA if faction == "india" else Faction.PAKISTAN
        for unit in self.units.get_units_by_category(UnitCategory.AIR_DEFENSE):
            if unit.faction == faction_enum and unit.is_combat_effective():
                ad_coverage.append({
                    "type": unit.unit_type,
                    "effectiveness": unit.get_combat_power(attack=True) / 100.0,
                    "missiles": int(unit.state.supply_level / 10),
                    "range_km": unit.type_data.get("range_km", 30),
                })
        return ad_coverage

    def _get_target_sam(self, target_id: str, faction: str) -> dict:
        """Find SAM unit for SEAD targeting."""
        target = self.units.get_unit(target_id)
        if target and target.category == UnitCategory.AIR_DEFENSE:
            return {
                "id": target.id,
                "type": target.unit_type,
                "missiles": int(target.state.supply_level / 5),
                "effectiveness": target.get_combat_power(attack=True) / 100.0,
            }
        # Fallback: find any AD unit of that faction
        faction_enum = Faction.INDIA if faction == "india" else Faction.PAKISTAN
        for unit in self.units.get_units_by_category(UnitCategory.AIR_DEFENSE):
            if unit.faction == faction_enum and unit.is_combat_effective():
                return {
                    "id": unit.id,
                    "type": unit.unit_type,
                    "missiles": int(unit.state.supply_level / 5),
                    "effectiveness": unit.get_combat_power(attack=True) / 100.0,
                }
        return {"id": "none", "type": "none", "missiles": 0, "effectiveness": 0.0}

    def _execute_artillery_phase(self, india_orders: Orders, pakistan_orders: Orders) -> list:
        """Execute artillery phase."""
        reports = []

        for mission in india_orders.artillery_missions:
            report = self._resolve_artillery_mission(mission, "india")
            if report:
                reports.append(report)

        for mission in pakistan_orders.artillery_missions:
            report = self._resolve_artillery_mission(mission, "pakistan")
            if report:
                reports.append(report)

        return reports

    def _resolve_artillery_mission(self, mission: dict, faction: str) -> Optional[dict]:
        """Resolve artillery fire mission."""
        from .combat.artillery import FireMission

        battery_id = mission.get("battery_id", "")
        battery = self.units.get_unit(battery_id)
        if not battery:
            return None

        target_id = mission.get("target_id", "")
        target = self.units.get_unit(target_id)

        fire_mission = FireMission(
            battery_id=battery_id,
            target_id=target_id,
            target_type=mission.get("target_type", "ground_unit"),
            target_location=mission.get("location", (0, 0)),
            rounds=mission.get("rounds", 20),
            mission_type=mission.get("mission_type", "bombardment"),
        )

        # Get terrain concealment
        concealment = 30
        if target and target.location.hex_q:
            cell = self.hex_map.get_cell(target.location.hex_q, target.location.hex_r)
            if cell:
                concealment = self.hex_map.get_concealment(cell)

        report, effect = self.artillery_combat.resolve_fire_mission(
            fire_mission,
            battery.type_data,
            target,
            concealment,
            weather_modifier=self.hex_map.weather.visibility_modifier,
        )

        # Apply effects
        if target and effect.casualties > 0:
            self.artillery_combat.apply_effects(target, effect)
            self.current_turn.units_in_combat.add(target_id)

        # Consume supply
        battery.consume_supply(combat=True)

        report.turn = self.game_state.turn
        return report.__dict__

    def _execute_helicopter_phase(self, india_orders: Orders, pakistan_orders: Orders) -> list:
        """Execute helicopter operations."""
        reports = []

        for mission in india_orders.helicopter_missions:
            report = self._resolve_helicopter_mission(mission, "india")
            if report:
                reports.append(report)

        for mission in pakistan_orders.helicopter_missions:
            report = self._resolve_helicopter_mission(mission, "pakistan")
            if report:
                reports.append(report)

        return reports

    def _resolve_helicopter_mission(self, mission: dict, faction: str) -> Optional[dict]:
        """Resolve a single helicopter mission."""
        from .combat.helicopters import HelicopterMission

        unit_id = mission.get("unit_id", "")
        unit = self.units.get_unit(unit_id)
        if not unit:
            return None

        mission_type = mission.get("type", mission.get("mission_type", "attack"))
        target_id = mission.get("target_id", "")
        enemy = "pakistan" if faction == "india" else "india"

        heli_mission = HelicopterMission(
            unit_id=unit_id,
            mission_type=mission_type,
            helicopter_count=mission.get("helicopter_count", unit.state.strength_current),
            helicopter_type=mission.get("helicopter_type", unit.unit_type),
            target_id=target_id,
            target_location=mission.get("target_location"),
        )

        weather_mod = self.hex_map.weather.air_ops_modifier
        ad_coverage = self._get_ad_coverage_for_drones(target_id, enemy)

        if mission_type == "air_assault":
            troops_count = mission.get("troops", 30)
            lz_security = mission.get("lz_security", "warm")

            report, engagement = self.heli_combat.resolve_air_assault(
                heli_mission, troops_count, lz_security,
                ad_coverage, weather_modifier=weather_mod,
            )
        else:
            # Attack / CAS mission
            target_unit = self.units.get_unit(target_id)
            if not target_unit:
                return None

            # Get terrain concealment for the target's location
            concealment = 30
            if target_unit.location.hex_q is not None and target_unit.location.hex_r is not None:
                cell = self.hex_map.get_cell(target_unit.location.hex_q, target_unit.location.hex_r)
                if cell:
                    concealment = self.hex_map.get_concealment(cell)

            report, engagement = self.heli_combat.resolve_attack_mission(
                heli_mission,
                mission.get("heli_stats", {}),
                target_unit,
                ad_coverage,
                terrain_concealment=concealment,
                weather_modifier=weather_mod,
            )

            # Apply target casualties and equipment losses
            if engagement.target_casualties > 0 or engagement.target_equipment_destroyed > 0:
                target_unit.take_losses(
                    engagement.target_casualties,
                    engagement.target_equipment_destroyed * 3,
                )
                self.current_turn.units_in_combat.add(target_id)

        # Apply helicopter losses
        if engagement.helicopters_lost > 0:
            unit.take_losses(engagement.helicopters_lost, engagement.helicopters_lost * 5)

        report.turn = self.game_state.turn
        return report.__dict__

    def _execute_ground_phase(self, india_orders: Orders, pakistan_orders: Orders) -> list:
        """Execute ground combat phase."""
        reports = []

        # Process all ground engagements
        for order in india_orders.ground_orders:
            report = self._resolve_ground_combat(order, "india")
            if report:
                reports.append(report)

        for order in pakistan_orders.ground_orders:
            report = self._resolve_ground_combat(order, "pakistan")
            if report:
                reports.append(report)

        return reports

    def _resolve_ground_combat(self, order: dict, faction: str) -> Optional[dict]:
        """Resolve ground combat engagement."""
        from .combat.ground import GroundEngagement

        attacker = self.units.get_unit(order.get("unit_id", ""))
        defender = self.units.get_unit(order.get("target_id", ""))

        if not attacker or not defender:
            return None

        location = (attacker.location.hex_q or 0, attacker.location.hex_r or 0)
        cell = self.hex_map.get_cell(*location)
        terrain = cell.terrain.value if cell else "plains"

        engagement = GroundEngagement(
            attacker_id=attacker.id,
            defender_id=defender.id,
            location=location,
            attacker_posture=order.get("posture", "assault"),
            defender_posture=defender.posture.value,
            terrain=terrain,
            terrain_defense_mod=self.hex_map.get_defense_modifier(cell) if cell else 1.0,
        )

        report, result = self.ground_combat.resolve_engagement(
            engagement, attacker, defender,
            weather_modifier=self.hex_map.weather.movement_modifier,
        )

        # Apply results
        self.ground_combat.apply_combat_results(attacker, defender, result)

        self.current_turn.units_in_combat.add(attacker.id)
        self.current_turn.units_in_combat.add(defender.id)

        report.turn = self.game_state.turn
        return report.__dict__

    def _execute_sf_phase(self, india_orders: Orders, pakistan_orders: Orders) -> list:
        """Execute special forces phase."""
        reports = []

        for mission in india_orders.sf_missions:
            report = self._resolve_sf_mission(mission, "india")
            if report:
                reports.append(report)

        for mission in pakistan_orders.sf_missions:
            report = self._resolve_sf_mission(mission, "pakistan")
            if report:
                reports.append(report)

        return reports

    def _resolve_sf_mission(self, mission: dict, faction: str) -> Optional[dict]:
        """Resolve a single special forces mission."""
        from .combat.special_forces import SFMission
        from .fog_of_war import IntelReport, IntelQuality

        unit_id = mission.get("unit_id", "")
        unit = self.units.get_unit(unit_id)
        if not unit:
            return None

        mission_type = mission.get("type", mission.get("mission_type", "raid"))
        target_id = mission.get("target_id", "")
        enemy = "pakistan" if faction == "india" else "india"
        enemy_faction = Faction.PAKISTAN if faction == "india" else Faction.INDIA

        sf_mission = SFMission(
            unit_id=unit_id,
            mission_type=mission_type,
            team_size=mission.get("team_size", unit.state.strength_current),
            target_id=target_id,
            target_location=mission.get("target_location", (0, 0)),
            insertion_method=mission.get("insertion", "ground"),
            extraction_planned=mission.get("extraction", True),
        )

        sf_stats = mission.get("sf_stats", {})
        if not sf_stats.get("type"):
            sf_stats["type"] = unit.unit_type

        if mission_type in ("recon", "sr"):
            # Reconnaissance mission
            enemy_units = self.units.get_units_by_faction(enemy_faction)
            observation_turns = mission.get("observation_turns", 2)

            report, result = self.sf_combat.resolve_recon(
                sf_mission, sf_stats, enemy_units, observation_turns,
            )

            # Feed intel into fog of war with CONFIRMED quality
            for unit_info in result.intel_gathered.get("positions", []):
                intel_report = IntelReport(
                    unit_id=unit_info["unit_id"],
                    faction=enemy,
                    quality=IntelQuality.CONFIRMED,
                    last_updated=self.game_state.turn,
                    reported_location=unit_info.get("location"),
                    source="humint",
                    confidence=unit_info.get("accuracy", 0.9),
                )
                self.fog.add_manual_intel(faction, intel_report)

        else:
            # Raid / sabotage / DA mission
            target_unit = self.units.get_unit(target_id)

            # Determine target security from dug-in level
            if target_unit:
                dug_in = target_unit.state.dug_in
                security_map = {0: "low", 1: "medium", 2: "high", 3: "very_high"}
                target_security = security_map.get(dug_in, "medium")
                target_troops = target_unit.state.strength_current
            else:
                target_security = mission.get("target_security", "medium")
                target_troops = mission.get("target_troops", 50)

            # Get intel quality for the target
            intel_quality = 0.5
            if target_id:
                existing_intel = self.fog.get_unit_intel(faction, target_id)
                if existing_intel:
                    quality_map = {"confirmed": 0.9, "identified": 0.7, "detected": 0.5, "suspected": 0.3}
                    intel_quality = quality_map.get(existing_intel.quality.value, 0.5)

            report, result = self.sf_combat.resolve_mission(
                sf_mission, sf_stats,
                target_security=target_security,
                target_troops=target_troops,
                intel_quality=intel_quality,
                support_available=mission.get("support", False),
            )

            # Apply target damage
            if target_unit and result.enemy_casualties > 0:
                target_unit.take_losses(result.enemy_casualties, result.damage_inflicted * 0.3)
                self.current_turn.units_in_combat.add(target_id)

        # Apply SF casualties
        if result.casualties > 0:
            unit.take_losses(result.casualties, result.casualties * 5)

        report.turn = self.game_state.turn
        return report.__dict__

    def _execute_logistics_phase(self) -> list:
        """Execute logistics phase."""
        reports = []

        # Process supply for both sides
        india_units = self.units.get_units_by_faction(Faction.INDIA)
        pakistan_units = self.units.get_units_by_faction(Faction.PAKISTAN)

        india_result = self.logistics.process_supply_turn(
            "india", india_units,
            self.current_turn.units_in_combat,
            self.hex_map
        )

        pakistan_result = self.logistics.process_supply_turn(
            "pakistan", pakistan_units,
            self.current_turn.units_in_combat,
            self.hex_map
        )

        for faction, result in [("india", india_result), ("pakistan", pakistan_result)]:
            undersupplied = result.get("units_undersupplied", [])
            if undersupplied:
                reports.append({
                    "phase": "logistics",
                    "faction": faction,
                    "turn": self.game_state.turn,
                    "units_undersupplied": undersupplied,
                    "units_supplied": len(result.get("units_supplied", [])),
                    "total_consumed": result.get("total_consumed", {}),
                    "notes": [
                        f"{faction}: {len(undersupplied)} units undersupplied",
                    ],
                })

        return reports

    def _execute_recovery_phase(self) -> list:
        """Execute recovery phase - units recover from combat."""
        turn = self.game_state.turn

        for unit in self.units.units.values():
            unit.recover(turn)

            # Reset daily counters at dawn
            if self.current_turn.time_of_day == TimeOfDay.DAWN:
                if hasattr(unit, "reset_daily"):
                    unit.reset_daily()

        return []

    def _calculate_victory_points(self):
        """Calculate VP changes for the turn based on combat results and unit destruction."""
        from .combat.base import CombatResult

        # VP from combat results this turn
        VP_COMBAT = {
            CombatResult.DECISIVE_VICTORY.value: 5,
            "decisive_victory": 5,
            CombatResult.VICTORY.value: 3,
            "victory": 3,
            CombatResult.MARGINAL.value: 1,
            "marginal": 1,
        }

        VP_UNIT_DESTROY = {
            UnitCategory.AIRCRAFT: 5,
            UnitCategory.AIR_DEFENSE: 4,
            UnitCategory.MISSILE: 3,
            UnitCategory.HELICOPTER: 3,
            UnitCategory.DRONE: 2,
            UnitCategory.ARTILLERY: 2,
            UnitCategory.SPECIAL_FORCES: 3,
            UnitCategory.GROUND: 2,
            UnitCategory.ISR: 2,
        }

        for report in self.current_turn.combat_reports:
            result_val = report.get("result")
            if isinstance(result_val, CombatResult):
                result_val = result_val.value

            vp_award = VP_COMBAT.get(result_val, 0)
            if vp_award == 0:
                continue

            # Determine which faction gets the VP (attacker wins)
            attacker_id = report.get("attacker_id", "")
            attacker_unit = self.units.get_unit(attacker_id)
            if attacker_unit:
                if attacker_unit.faction == Faction.INDIA:
                    self.game_state.india_vp += vp_award
                else:
                    self.game_state.pakistan_vp += vp_award
            else:
                # Infer faction from phase/report metadata
                faction = report.get("faction")
                if faction == "india":
                    self.game_state.india_vp += vp_award
                elif faction == "pakistan":
                    self.game_state.pakistan_vp += vp_award

            # Bonus VP for SEAD successes
            phase = report.get("phase", "")
            if "sead" in phase and vp_award >= 3:
                if attacker_unit and attacker_unit.faction == Faction.INDIA:
                    self.game_state.india_vp += 2
                elif attacker_unit and attacker_unit.faction == Faction.PAKISTAN:
                    self.game_state.pakistan_vp += 2

            # Bonus VP for SF successes
            if "special_forces" in phase and vp_award >= 3:
                if attacker_unit and attacker_unit.faction == Faction.INDIA:
                    self.game_state.india_vp += 1
                elif attacker_unit and attacker_unit.faction == Faction.PAKISTAN:
                    self.game_state.pakistan_vp += 1

        # VP for unit destruction (check all units, only count once)
        for unit in self.units.units.values():
            if unit.status == UnitStatus.DESTROYED and unit.id not in self._destroyed_units_counted:
                self._destroyed_units_counted.add(unit.id)
                vp = VP_UNIT_DESTROY.get(unit.category, 2)
                # Award VP to the opposing faction
                if unit.faction == Faction.INDIA:
                    self.game_state.pakistan_vp += vp
                else:
                    self.game_state.india_vp += vp

    def _check_victory_conditions(self):
        """Check if victory conditions are met."""
        if self.game_state.turn >= self.game_state.max_turns:
            self.game_state.game_over = True
            if self.game_state.india_vp > self.game_state.pakistan_vp:
                self.game_state.winner = "india"
            elif self.game_state.pakistan_vp > self.game_state.india_vp:
                self.game_state.winner = "pakistan"
            else:
                self.game_state.winner = "draw"

    def get_game_state_for_agent(self, faction: str) -> dict:
        """Get game state visible to an agent."""
        visible = self.fog.get_visible_state(
            faction,
            list(self.units.units.values()),
            self.hex_map
        )

        return {
            "turn": self.game_state.turn,
            "day": self.get_day_number(self.game_state.turn),
            "time_of_day": self.get_time_of_day(self.game_state.turn - 1).value if self.game_state.turn > 0 else "dawn",
            "weather": self.hex_map.weather.weather.value,
            "own_units": visible["own_units"],
            "known_enemies": visible["known_enemies"],
            "suspected_enemies": visible["suspected_enemies"],
            "supply_status": self.logistics.get_supply_status(faction),
            "intel_summary": self.fog.get_intel_summary(faction),
            "vp": {
                "india": self.game_state.india_vp,
                "pakistan": self.game_state.pakistan_vp,
            },
        }

    def save_game(self, filepath: Path):
        """Save game state to file."""
        state = {
            "turn": self.game_state.turn,
            "india_vp": self.game_state.india_vp,
            "pakistan_vp": self.game_state.pakistan_vp,
            "game_over": self.game_state.game_over,
            "winner": self.game_state.winner,
        }
        with open(filepath, "w") as f:
            json.dump(state, f, indent=2)

    def load_game(self, filepath: Path):
        """Load game state from file."""
        with open(filepath) as f:
            state = json.load(f)
        self.game_state.turn = state["turn"]
        self.game_state.india_vp = state["india_vp"]
        self.game_state.pakistan_vp = state["pakistan_vp"]
        self.game_state.game_over = state["game_over"]
        self.game_state.winner = state["winner"]
