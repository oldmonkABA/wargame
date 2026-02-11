"""
Unit state management for India-Pakistan wargame simulation.

Handles all military units: ground forces, aircraft, missiles, artillery, etc.
"""

import yaml
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any
from pathlib import Path
import uuid


class Faction(Enum):
    INDIA = "india"
    PAKISTAN = "pakistan"


class UnitCategory(Enum):
    AIRCRAFT = "aircraft"
    GROUND = "ground"
    ARTILLERY = "artillery"
    HELICOPTER = "helicopter"
    DRONE = "drone"
    MISSILE = "missile"
    AIR_DEFENSE = "air_defense"
    SPECIAL_FORCES = "special_forces"
    ISR = "isr"


class UnitStatus(Enum):
    READY = "ready"
    ENGAGED = "engaged"
    DAMAGED = "damaged"
    RETREATING = "retreating"
    DESTROYED = "destroyed"
    RELOADING = "reloading"
    REPAIRING = "repairing"
    IN_TRANSIT = "in_transit"


class Posture(Enum):
    ATTACK = "attack"
    DEFEND = "defend"
    DELAY = "delay"
    WITHDRAW = "withdraw"
    RESERVE = "reserve"
    PATROL = "patrol"  # For air units
    STRIKE = "strike"  # For air/missile units


@dataclass
class Location:
    """Unit location, either lat/lon or hex coordinates."""
    lat: Optional[float] = None
    lon: Optional[float] = None
    hex_q: Optional[int] = None
    hex_r: Optional[int] = None
    airbase_id: Optional[str] = None  # For aircraft

    def is_valid(self) -> bool:
        return (self.lat is not None and self.lon is not None) or \
               (self.hex_q is not None and self.hex_r is not None) or \
               self.airbase_id is not None


@dataclass
class UnitState:
    """Runtime state of a unit."""
    strength_current: int  # Current manpower/aircraft count
    strength_max: int
    organization: float = 100.0  # 0-100, cohesion
    morale: float = 85.0  # 0-100
    supply_level: float = 100.0  # 0-100 (ammo, fuel)
    fuel: float = 100.0  # 0-100, separate fuel tracking
    readiness: float = 100.0  # 0-100, maintenance state
    dug_in: int = 0  # 0-3, entrenchment level
    suppression: float = 0.0  # 0-100, temporary combat penalty
    detected: bool = False  # Has enemy spotted this unit
    last_combat_turn: int = -1


@dataclass
class Unit:
    """Base class for all military units."""
    id: str
    name: str
    faction: Faction
    category: UnitCategory
    unit_type: str  # Reference to type definition (e.g., "su30mki", "armored_brigade")
    location: Location
    state: UnitState
    status: UnitStatus = UnitStatus.READY
    posture: Posture = Posture.DEFEND
    parent_id: Optional[str] = None  # Parent formation
    subordinate_ids: list[str] = field(default_factory=list)
    orders: Optional[dict] = None  # Current orders from agent
    type_data: dict = field(default_factory=dict)  # Loaded type stats

    def is_combat_effective(self) -> bool:
        """Check if unit can still fight."""
        if self.status in (UnitStatus.DESTROYED, UnitStatus.RETREATING):
            return False
        if self.state.strength_current <= 0:
            return False
        if self.state.organization < 20:
            return False
        return True

    def get_combat_power(self, attack: bool = True) -> float:
        """Calculate current combat power."""
        if not self.is_combat_effective():
            return 0.0

        # Base power from type
        base = self.type_data.get("attack" if attack else "defense", 50)

        # Strength modifier
        strength_ratio = self.state.strength_current / max(1, self.state.strength_max)

        # Organization modifier
        org_mod = self.state.organization / 100.0

        # Morale modifier
        morale_mod = 0.5 + (self.state.morale / 200.0)  # 0.5 to 1.0

        # Supply modifier
        if self.state.supply_level < 25:
            supply_mod = 0.4
        elif self.state.supply_level < 50:
            supply_mod = 0.7
        elif self.state.supply_level < 75:
            supply_mod = 0.9
        else:
            supply_mod = 1.0

        # Suppression penalty
        suppression_mod = 1.0 - (self.state.suppression / 100.0)

        return base * strength_ratio * org_mod * morale_mod * supply_mod * suppression_mod

    def take_losses(self, casualties: int, organization_loss: float = 0.0):
        """Apply casualties and organization damage."""
        self.state.strength_current = max(0, self.state.strength_current - casualties)
        self.state.organization = max(0, self.state.organization - organization_loss)

        # Morale impact from losses
        loss_ratio = casualties / max(1, self.state.strength_max)
        self.state.morale = max(0, self.state.morale - loss_ratio * 20)

        # Check for rout
        if self.state.organization < 15 or self.state.morale < 15:
            self.status = UnitStatus.RETREATING

        if self.state.strength_current <= 0:
            self.status = UnitStatus.DESTROYED

    def apply_suppression(self, amount: float):
        """Apply suppression from combat."""
        self.state.suppression = min(100, self.state.suppression + amount)

    def recover(self, turn_number: int):
        """Partial recovery each turn."""
        # Suppression fades
        self.state.suppression = max(0, self.state.suppression - 20)

        # Organization slowly recovers if not in combat
        if self.state.last_combat_turn < turn_number - 1:
            self.state.organization = min(100, self.state.organization + 5)

        # Morale recovery
        if self.state.morale < 50:
            self.state.morale = min(50, self.state.morale + 3)

    def consume_supply(self, combat: bool = False):
        """Consume supply for the turn."""
        base_consumption = 5 if not combat else 15
        self.state.supply_level = max(0, self.state.supply_level - base_consumption)

        if self.category in (UnitCategory.AIRCRAFT, UnitCategory.HELICOPTER):
            self.state.fuel = max(0, self.state.fuel - (10 if combat else 5))


@dataclass
class AircraftSquadron(Unit):
    """Specialized unit for aircraft squadrons."""
    aircraft_type: str = ""
    sortie_rate: float = 1.5  # Sorties per day
    sorties_flown_today: int = 0
    weapons_loadout: list[str] = field(default_factory=list)
    base_id: str = ""  # Home airbase

    def can_sortie(self) -> bool:
        """Check if squadron can fly another sortie."""
        if not self.is_combat_effective():
            return False
        if self.state.fuel < 20:
            return False
        if self.sorties_flown_today >= int(self.sortie_rate * 4):  # 4 turns per day
            return False
        return True

    def fly_sortie(self):
        """Record a sortie being flown."""
        self.sorties_flown_today += 1
        self.state.fuel -= 15
        self.state.readiness -= 2

    def reset_daily(self):
        """Reset daily counters (call at start of new day)."""
        self.sorties_flown_today = 0


@dataclass
class Airbase:
    """Airbase facility."""
    id: str
    name: str
    faction: Faction
    location: Location
    capacity: int
    hardened_shelters: int
    maintenance_rating: int  # 0-100
    runway_status: float = 100.0  # 0-100, damage level
    fuel_storage: float = 100.0  # 0-100
    ammo_storage: float = 100.0  # 0-100
    squadron_ids: list[str] = field(default_factory=list)
    air_defense_ids: list[str] = field(default_factory=list)

    def is_operational(self) -> bool:
        return self.runway_status >= 30

    def get_sortie_modifier(self) -> float:
        """Modifier to sortie rate based on base condition."""
        runway_mod = self.runway_status / 100.0
        maint_mod = self.maintenance_rating / 100.0
        return runway_mod * maint_mod


@dataclass
class MissileBattery(Unit):
    """Missile unit (cruise missiles, ballistic missiles)."""
    missile_type: str = ""
    missiles_remaining: int = 0
    missiles_max: int = 0
    reload_time_turns: int = 4
    turns_until_reload: int = 0
    range_km: int = 0
    is_mobile: bool = True
    is_nuclear_capable: bool = False  # Not used in conventional sim

    def can_fire(self) -> bool:
        if self.missiles_remaining <= 0:
            return False
        if self.turns_until_reload > 0:
            return False
        return self.is_combat_effective()

    def fire_missile(self, count: int = 1):
        """Fire missiles."""
        fired = min(count, self.missiles_remaining)
        self.missiles_remaining -= fired
        self.turns_until_reload = self.reload_time_turns
        return fired

    def tick_reload(self):
        """Progress reload timer."""
        if self.turns_until_reload > 0:
            self.turns_until_reload -= 1


class UnitManager:
    """Manages all units in the simulation."""

    def __init__(self, data_path: Path | str = "data"):
        self.data_path = Path(data_path)
        self.units: dict[str, Unit] = {}
        self.airbases: dict[str, Airbase] = {}
        self.type_definitions: dict[str, dict] = {}

        self._load_type_definitions()

    def _load_type_definitions(self):
        """Load unit type definitions from schema files."""
        schema_path = self.data_path / "schema"
        if not schema_path.exists():
            return

        schemas = ["aircraft", "ground_forces", "missiles", "air_defense",
                   "artillery", "helicopters", "drones", "special_forces"]

        for schema_name in schemas:
            schema_file = schema_path / f"{schema_name}.yaml"
            if schema_file.exists():
                with open(schema_file) as f:
                    data = yaml.safe_load(f)
                    # Flatten type definitions
                    for key, value in data.items():
                        if isinstance(value, dict):
                            if "id" in value or "name" in value:
                                self.type_definitions[key] = value
                            else:
                                # Nested types
                                for subkey, subvalue in value.items():
                                    if isinstance(subvalue, dict):
                                        self.type_definitions[subkey] = subvalue

    def load_faction_oob(self, faction: Faction):
        """Load all units for a faction from OOB files."""
        faction_path = self.data_path / faction.value

        if not faction_path.exists():
            return

        # Load airbases first
        airbases_file = faction_path / "airbases.yaml"
        if airbases_file.exists():
            self._load_airbases(airbases_file, faction)

        # Load other units
        unit_files = {
            "missiles.yaml": self._load_missiles,
            "air_defense.yaml": self._load_air_defense,
            "ground_forces.yaml": self._load_ground_forces,
            "artillery.yaml": self._load_artillery,
            "helicopters.yaml": self._load_helicopters,
            "drones.yaml": self._load_drones,
            "special_forces.yaml": self._load_special_forces,
            "isr.yaml": self._load_isr,
        }

        for filename, loader in unit_files.items():
            filepath = faction_path / filename
            if filepath.exists():
                loader(filepath, faction)

    def _load_airbases(self, filepath: Path, faction: Faction):
        """Load airbases and squadrons."""
        with open(filepath) as f:
            data = yaml.safe_load(f)

        for base_data in data.get("airbases", []):
            base_id = base_data.get("id", str(uuid.uuid4()))
            loc = base_data.get("location", {})

            base = Airbase(
                id=base_id,
                name=base_data.get("name", base_id),
                faction=faction,
                location=Location(lat=loc.get("lat"), lon=loc.get("lon")),
                capacity=base_data.get("capacity", 30),
                hardened_shelters=base_data.get("facilities", {}).get("hardened_shelters", 0),
                maintenance_rating=base_data.get("facilities", {}).get("maintenance", 80),
            )

            # Load squadrons
            for sqn_data in base_data.get("squadrons", []):
                sqn = self._create_squadron(sqn_data, faction, base_id)
                if sqn:
                    self.units[sqn.id] = sqn
                    base.squadron_ids.append(sqn.id)

            self.airbases[base_id] = base

    def _create_squadron(self, data: dict, faction: Faction, base_id: str) -> Optional[AircraftSquadron]:
        """Create an aircraft squadron from data."""
        sqn_id = data.get("id", str(uuid.uuid4()))
        aircraft_type = data.get("aircraft_type", "")
        count = data.get("aircraft_count", 0)

        if count == 0:
            return None

        type_data = self.type_definitions.get(aircraft_type, {})

        return AircraftSquadron(
            id=sqn_id,
            name=data.get("name", sqn_id),
            faction=faction,
            category=UnitCategory.AIRCRAFT,
            unit_type=aircraft_type,
            aircraft_type=aircraft_type,
            location=Location(airbase_id=base_id),
            state=UnitState(strength_current=count, strength_max=count),
            sortie_rate=type_data.get("sortie_rate", 1.5),
            base_id=base_id,
            type_data=type_data,
        )

    def _load_missiles(self, filepath: Path, faction: Faction):
        """Load missile units."""
        with open(filepath) as f:
            data = yaml.safe_load(f)

        for system in data.get("missile_systems", data.get("missiles", [])):
            sys_id = system.get("id", str(uuid.uuid4()))
            launchers = system.get("launchers", 1)
            missiles_per = system.get("missiles_per_launcher", 4)

            unit = MissileBattery(
                id=sys_id,
                name=system.get("name", sys_id),
                faction=faction,
                category=UnitCategory.MISSILE,
                unit_type=system.get("type", "cruise"),
                missile_type=system.get("type", "cruise"),
                location=Location(),  # Position set by scenario
                state=UnitState(strength_current=launchers, strength_max=launchers),
                missiles_remaining=launchers * missiles_per,
                missiles_max=launchers * missiles_per,
                range_km=system.get("range_km", 300),
                is_mobile=system.get("mobile", True),
                type_data=system,
            )
            self.units[sys_id] = unit

    def _load_air_defense(self, filepath: Path, faction: Faction):
        """Load air defense units."""
        with open(filepath) as f:
            data = yaml.safe_load(f)

        for system in data.get("air_defense_systems", data.get("systems", [])):
            sys_id = system.get("id", str(uuid.uuid4()))
            units = system.get("units", system.get("batteries", 1))

            unit = Unit(
                id=sys_id,
                name=system.get("name", sys_id),
                faction=faction,
                category=UnitCategory.AIR_DEFENSE,
                unit_type=system.get("type", "sam"),
                location=Location(),
                state=UnitState(
                    strength_current=units,
                    strength_max=units,
                    supply_level=100.0
                ),
                type_data=system,
            )
            self.units[sys_id] = unit

    def _load_ground_forces(self, filepath: Path, faction: Faction):
        """Load ground force units."""
        with open(filepath) as f:
            data = yaml.safe_load(f)

        # Load corps and divisions
        for corps in data.get("corps", []):
            corps_id = corps.get("id", str(uuid.uuid4()))
            corps_unit = Unit(
                id=corps_id,
                name=corps.get("name", corps_id),
                faction=faction,
                category=UnitCategory.GROUND,
                unit_type=corps.get("type", "infantry_corps"),
                location=Location(),
                state=UnitState(strength_current=1, strength_max=1),
                type_data=corps,
            )
            self.units[corps_id] = corps_unit

            # Load subordinate divisions/brigades
            for div in corps.get("divisions", []):
                div_id = div.get("id", str(uuid.uuid4()))
                div_type = div.get("type", "infantry_division")
                type_data = self.type_definitions.get(div_type, {})

                div_unit = Unit(
                    id=div_id,
                    name=div.get("name", div_id),
                    faction=faction,
                    category=UnitCategory.GROUND,
                    unit_type=div_type,
                    location=Location(),
                    state=UnitState(
                        strength_current=div.get("strength", type_data.get("strength", 10000)),
                        strength_max=div.get("strength", type_data.get("strength", 10000)),
                    ),
                    parent_id=corps_id,
                    type_data={**type_data, **div},
                )
                self.units[div_id] = div_unit
                corps_unit.subordinate_ids.append(div_id)

    def _load_artillery(self, filepath: Path, faction: Faction):
        """Load artillery units."""
        with open(filepath) as f:
            data = yaml.safe_load(f)

        for system in data.get("artillery_systems", data.get("artillery", [])):
            sys_id = system.get("id", str(uuid.uuid4()))
            count = system.get("units", system.get("count", 1))

            unit = Unit(
                id=sys_id,
                name=system.get("name", sys_id),
                faction=faction,
                category=UnitCategory.ARTILLERY,
                unit_type=system.get("type", "tube"),
                location=Location(),
                state=UnitState(strength_current=count, strength_max=count),
                type_data=system,
            )
            self.units[sys_id] = unit

    def _load_helicopters(self, filepath: Path, faction: Faction):
        """Load helicopter units."""
        with open(filepath) as f:
            data = yaml.safe_load(f)

        for heli in data.get("helicopter_units", data.get("helicopters", [])):
            heli_id = heli.get("id", str(uuid.uuid4()))
            count = heli.get("aircraft_count", heli.get("count", 1))

            unit = Unit(
                id=heli_id,
                name=heli.get("name", heli_id),
                faction=faction,
                category=UnitCategory.HELICOPTER,
                unit_type=heli.get("type", "attack"),
                location=Location(),
                state=UnitState(strength_current=count, strength_max=count),
                type_data=heli,
            )
            self.units[heli_id] = unit

    def _load_drones(self, filepath: Path, faction: Faction):
        """Load drone units."""
        with open(filepath) as f:
            data = yaml.safe_load(f)

        for drone in data.get("drone_units", data.get("drones", [])):
            drone_id = drone.get("id", str(uuid.uuid4()))
            count = drone.get("count", drone.get("units", 1))

            unit = Unit(
                id=drone_id,
                name=drone.get("name", drone_id),
                faction=faction,
                category=UnitCategory.DRONE,
                unit_type=drone.get("type", "ucav"),
                location=Location(),
                state=UnitState(strength_current=count, strength_max=count),
                type_data=drone,
            )
            self.units[drone_id] = unit

    def _load_special_forces(self, filepath: Path, faction: Faction):
        """Load special forces units."""
        with open(filepath) as f:
            data = yaml.safe_load(f)

        for sf in data.get("special_forces_units", data.get("units", [])):
            sf_id = sf.get("id", str(uuid.uuid4()))
            count = sf.get("personnel", sf.get("strength", 500))

            unit = Unit(
                id=sf_id,
                name=sf.get("name", sf_id),
                faction=faction,
                category=UnitCategory.SPECIAL_FORCES,
                unit_type=sf.get("type", "special_forces"),
                location=Location(),
                state=UnitState(strength_current=count, strength_max=count),
                type_data=sf,
            )
            self.units[sf_id] = unit

    def _load_isr(self, filepath: Path, faction: Faction):
        """Load ISR assets."""
        with open(filepath) as f:
            data = yaml.safe_load(f)

        for isr in data.get("isr_assets", data.get("assets", [])):
            isr_id = isr.get("id", str(uuid.uuid4()))

            unit = Unit(
                id=isr_id,
                name=isr.get("name", isr_id),
                faction=faction,
                category=UnitCategory.ISR,
                unit_type=isr.get("type", "awacs"),
                location=Location(),
                state=UnitState(
                    strength_current=isr.get("count", 1),
                    strength_max=isr.get("count", 1)
                ),
                type_data=isr,
            )
            self.units[isr_id] = unit

    # Query methods
    def get_unit(self, unit_id: str) -> Optional[Unit]:
        return self.units.get(unit_id)

    def get_airbase(self, base_id: str) -> Optional[Airbase]:
        return self.airbases.get(base_id)

    def get_units_by_faction(self, faction: Faction) -> list[Unit]:
        return [u for u in self.units.values() if u.faction == faction]

    def get_units_by_category(self, category: UnitCategory) -> list[Unit]:
        return [u for u in self.units.values() if u.category == category]

    def get_units_at_location(self, q: int, r: int) -> list[Unit]:
        return [u for u in self.units.values()
                if u.location.hex_q == q and u.location.hex_r == r]

    def get_combat_effective_units(self, faction: Faction) -> list[Unit]:
        return [u for u in self.units.values()
                if u.faction == faction and u.is_combat_effective()]

    def get_stats(self) -> dict:
        """Get unit statistics."""
        stats = {
            "total_units": len(self.units),
            "total_airbases": len(self.airbases),
            "by_faction": {},
            "by_category": {},
        }

        for faction in Faction:
            faction_units = self.get_units_by_faction(faction)
            stats["by_faction"][faction.value] = len(faction_units)

        for category in UnitCategory:
            cat_units = self.get_units_by_category(category)
            stats["by_category"][category.value] = len(cat_units)

        return stats
