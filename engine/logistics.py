"""
Logistics and supply system for wargame simulation.

Handles:
- Supply consumption and distribution
- Ammunition tracking
- Fuel consumption
- Reinforcements and replacements
- Attrition from supply shortages
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class SupplyType(Enum):
    AMMUNITION = "ammunition"
    FUEL = "fuel"
    FOOD = "food"
    SPARE_PARTS = "spare_parts"
    MEDICAL = "medical"


@dataclass
class SupplyNode:
    """A supply depot or logistics node."""
    id: str
    name: str
    faction: str
    location: tuple[int, int]  # hex coordinates
    capacity: dict[str, float] = field(default_factory=dict)  # by supply type
    current_stock: dict[str, float] = field(default_factory=dict)
    throughput_per_turn: float = 100.0  # Units that can pass through
    is_railhead: bool = False
    is_airfield: bool = False
    is_port: bool = False
    status: float = 100.0  # 0-100, damage degrades capacity


@dataclass
class SupplyRoute:
    """A supply route between nodes."""
    id: str
    from_node: str
    to_node: str
    route_type: str  # "road", "rail", "air", "sea"
    capacity_per_turn: float
    length_km: float
    risk_level: float = 0.0  # 0-1, chance of interdiction
    status: float = 100.0  # Damage level


@dataclass
class LogisticsState:
    """Logistics state for a faction."""
    faction: str
    nodes: dict[str, SupplyNode] = field(default_factory=dict)
    routes: dict[str, SupplyRoute] = field(default_factory=dict)
    total_supply_generated: float = 0.0
    total_supply_consumed: float = 0.0
    units_undersupplied: list[str] = field(default_factory=list)


class LogisticsSystem:
    """Manages logistics and supply for the simulation."""

    # Supply consumption rates per unit type per turn
    CONSUMPTION_RATES = {
        # Ground units (per 1000 strength)
        "infantry": {"ammunition": 5, "fuel": 2, "food": 10},
        "mechanized": {"ammunition": 8, "fuel": 15, "food": 8},
        "armor": {"ammunition": 10, "fuel": 25, "food": 6},
        "artillery": {"ammunition": 20, "fuel": 5, "food": 4},
        "special_forces": {"ammunition": 3, "fuel": 1, "food": 2},

        # Air units (per aircraft per sortie)
        "fighter": {"ammunition": 15, "fuel": 30, "spare_parts": 5},
        "bomber": {"ammunition": 25, "fuel": 50, "spare_parts": 8},
        "helicopter": {"ammunition": 10, "fuel": 20, "spare_parts": 4},

        # Support
        "air_defense": {"ammunition": 8, "fuel": 3, "spare_parts": 2},
        "logistics": {"fuel": 10, "spare_parts": 1},
    }

    # Combat multiplier (supply consumption during combat)
    COMBAT_MULTIPLIER = 3.0

    # Effects of low supply
    LOW_SUPPLY_EFFECTS = {
        75: {"combat": 0.95, "movement": 1.0, "morale": 0.98},
        50: {"combat": 0.80, "movement": 0.9, "morale": 0.90},
        25: {"combat": 0.50, "movement": 0.7, "morale": 0.70},
        10: {"combat": 0.20, "movement": 0.4, "morale": 0.50},
        0: {"combat": 0.05, "movement": 0.1, "morale": 0.20},
    }

    def __init__(self):
        self.india_logistics = LogisticsState(faction="india")
        self.pakistan_logistics = LogisticsState(faction="pakistan")

    def get_faction_logistics(self, faction: str) -> LogisticsState:
        """Get logistics state for a faction."""
        if faction == "india":
            return self.india_logistics
        return self.pakistan_logistics

    def calculate_unit_consumption(
        self,
        unit,
        in_combat: bool = False,
        distance_from_supply: int = 0,
    ) -> dict[str, float]:
        """Calculate supply consumption for a unit this turn."""
        unit_type = self._classify_unit(unit)
        base_rates = self.CONSUMPTION_RATES.get(unit_type, {
            "ammunition": 5, "fuel": 5, "food": 5
        })

        # Scale by unit strength
        strength_factor = unit.state.strength_current / 1000.0

        consumption = {}
        for supply_type, rate in base_rates.items():
            amount = rate * strength_factor

            # Combat multiplier
            if in_combat:
                amount *= self.COMBAT_MULTIPLIER

            # Distance penalty (supply harder to get to front)
            if distance_from_supply > 5:
                amount *= 1.0 + (distance_from_supply - 5) * 0.1

            consumption[supply_type] = amount

        return consumption

    def process_supply_turn(
        self,
        faction: str,
        units: list,
        combat_units: set[str],  # Unit IDs in combat this turn
        hex_map,
    ) -> dict:
        """Process supply for all units of a faction for one turn."""
        logistics = self.get_faction_logistics(faction)
        results = {
            "total_consumed": {},
            "units_supplied": [],
            "units_undersupplied": [],
            "supply_effects": {},
        }

        for unit in units:
            if unit.faction.value != faction:
                continue

            in_combat = unit.id in combat_units
            distance = self._calculate_supply_distance(unit, logistics, hex_map)

            # Calculate consumption
            consumption = self.calculate_unit_consumption(unit, in_combat, distance)

            # Check available supply
            available = self._get_available_supply(unit, logistics, hex_map)

            # Consume and track
            supplied = True
            for supply_type, needed in consumption.items():
                if supply_type not in results["total_consumed"]:
                    results["total_consumed"][supply_type] = 0

                actual = min(needed, available.get(supply_type, 0))
                results["total_consumed"][supply_type] += actual

                if actual < needed * 0.75:
                    supplied = False

            # Update unit supply level
            if supplied:
                results["units_supplied"].append(unit.id)
                # Gradually restore supply level
                unit.state.supply_level = min(100, unit.state.supply_level + 10)
            else:
                results["units_undersupplied"].append(unit.id)
                # Degrade supply level
                shortage = 1.0 - (sum(available.values()) / max(1, sum(consumption.values())))
                unit.state.supply_level = max(0, unit.state.supply_level - shortage * 20)

            # Calculate effects
            effects = self._get_supply_effects(unit.state.supply_level)
            results["supply_effects"][unit.id] = effects

        logistics.units_undersupplied = results["units_undersupplied"]
        return results

    def _classify_unit(self, unit) -> str:
        """Classify unit for supply purposes."""
        unit_type = unit.unit_type.lower()
        category = unit.category.value

        if category == "aircraft":
            if "fighter" in unit_type or "multirole" in unit_type:
                return "fighter"
            return "bomber"
        elif category == "helicopter":
            return "helicopter"
        elif category == "artillery":
            return "artillery"
        elif category == "air_defense":
            return "air_defense"
        elif category == "special_forces":
            return "special_forces"
        elif "armor" in unit_type or "tank" in unit_type:
            return "armor"
        elif "mech" in unit_type:
            return "mechanized"
        else:
            return "infantry"

    def _calculate_supply_distance(
        self,
        unit,
        logistics: LogisticsState,
        hex_map,
    ) -> int:
        """Calculate distance to nearest supply source."""
        if not unit.location.hex_q or not unit.location.hex_r:
            return 10  # Default if no location

        min_distance = 999
        for node in logistics.nodes.values():
            if node.status < 20:  # Node too damaged
                continue
            dist = hex_map.hex_distance(
                unit.location.hex_q, unit.location.hex_r,
                node.location[0], node.location[1]
            )
            min_distance = min(min_distance, dist)

        return min_distance

    def _get_available_supply(
        self,
        unit,
        logistics: LogisticsState,
        hex_map,
    ) -> dict[str, float]:
        """Get supply available to a unit."""
        distance = self._calculate_supply_distance(unit, logistics, hex_map)

        # Base availability (would come from actual supply network)
        base_supply = {
            "ammunition": 100,
            "fuel": 100,
            "food": 100,
            "spare_parts": 50,
        }

        # Distance reduces availability
        distance_factor = max(0.1, 1.0 - distance * 0.08)

        return {k: v * distance_factor for k, v in base_supply.items()}

    def _get_supply_effects(self, supply_level: float) -> dict:
        """Get combat/movement effects for current supply level."""
        for threshold, effects in sorted(self.LOW_SUPPLY_EFFECTS.items(), reverse=True):
            if supply_level >= threshold:
                return effects
        return self.LOW_SUPPLY_EFFECTS[0]

    def add_supply_node(
        self,
        faction: str,
        node: SupplyNode,
    ):
        """Add a supply node."""
        logistics = self.get_faction_logistics(faction)
        logistics.nodes[node.id] = node

    def add_supply_route(
        self,
        faction: str,
        route: SupplyRoute,
    ):
        """Add a supply route."""
        logistics = self.get_faction_logistics(faction)
        logistics.routes[route.id] = route

    def damage_supply_node(
        self,
        faction: str,
        node_id: str,
        damage: float,
    ):
        """Apply damage to a supply node."""
        logistics = self.get_faction_logistics(faction)
        if node_id in logistics.nodes:
            node = logistics.nodes[node_id]
            node.status = max(0, node.status - damage)

    def interdict_supply_route(
        self,
        faction: str,
        route_id: str,
        interdiction_level: float,
    ):
        """Increase interdiction risk on a route."""
        logistics = self.get_faction_logistics(faction)
        if route_id in logistics.routes:
            route = logistics.routes[route_id]
            route.risk_level = min(1.0, route.risk_level + interdiction_level)

    def repair_node(
        self,
        faction: str,
        node_id: str,
        repair_amount: float = 10.0,
    ):
        """Repair a damaged supply node."""
        logistics = self.get_faction_logistics(faction)
        if node_id in logistics.nodes:
            node = logistics.nodes[node_id]
            node.status = min(100, node.status + repair_amount)

    def get_supply_status(self, faction: str) -> dict:
        """Get overall supply status for a faction."""
        logistics = self.get_faction_logistics(faction)

        total_capacity = sum(n.status / 100 * n.throughput_per_turn
                           for n in logistics.nodes.values())
        damaged_nodes = sum(1 for n in logistics.nodes.values() if n.status < 50)
        interdicted_routes = sum(1 for r in logistics.routes.values() if r.risk_level > 0.3)

        return {
            "total_nodes": len(logistics.nodes),
            "damaged_nodes": damaged_nodes,
            "total_routes": len(logistics.routes),
            "interdicted_routes": interdicted_routes,
            "effective_capacity": total_capacity,
            "units_undersupplied": len(logistics.units_undersupplied),
        }
